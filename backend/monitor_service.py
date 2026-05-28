from __future__ import annotations

import asyncio
import datetime
import json
import logging
import os
import queue
import re
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from typing import TYPE_CHECKING

from src.monitor_core import NetworkMonitorCore

if TYPE_CHECKING:
    from fastapi import WebSocket
from src.playwright_worker import get_worker, CMD_LOGIN
from src.network_decision import is_network_available
from src.utils import ConfigValidator
from src.utils.logging import get_logger
from src.utils.login import SCREENSHOT_URL_PATTERN
from src.utils.network_helpers import parse_host_port

from .config_service import build_runtime_config, load_runtime_config, load_ui_config
from .profile_service import ProfileService
from .schemas import LogEntry, MonitorConfigPayload, MonitorStatusResponse
from .ws_manager import WebSocketManager


# ── Actor 模型：类型化命令派发 ──


@dataclass
class MonitorCommand:
    """从 API 线程派发到队列消费者线程的命令。"""

    type: str  # "start" | "stop" | "login" | "reload" | "profile_switch" | "shutdown"
    data: dict = field(default_factory=dict)
    response_event: threading.Event | None = None  # 调用方在此事件上等待
    response_data: Any = None  # 由消费者设置


@dataclass
class StatusSnapshot:
    """基于引用替换的监控状态快照，由 API 处理器直接读取。"""

    monitoring: bool = False
    last_network_ok: bool = False
    start_time: float | None = None
    network_check_count: int = 0
    login_attempt_count: int = 0
    last_check_time: str | None = None
    snapshot_time: float = 0.0
    status_detail: str = "正常"
    network_state: str = "unknown"


service_logger = get_logger("backend.monitor_service", side="BACKEND")


# ── MonitorService（Actor 模型重构）──


class MonitorService:
    def __init__(
        self,
        project_root: Path,
        profile_service: ProfileService | None = None,
        ws_manager: WebSocketManager | None = None,
    ):
        self.project_root = project_root
        self._profile_service = profile_service or ProfileService(project_root)
        self._ws_manager = ws_manager

        # State (previously guarded by RLock)
        self._logs: deque[LogEntry] = deque(maxlen=1200)

        self._ui_config = load_ui_config(self._profile_service)
        self._runtime_config = build_runtime_config(
            load_runtime_config(self._profile_service),
            self._profile_service.load().system,
        )

        self._monitor_core: NetworkMonitorCore | None = None
        self._monitor_thread: threading.Thread | None = None
        self._thread_done = threading.Event()
        self.pure_mode: bool = self._profile_service.load().system.pure_mode

        # Actor model: command dispatch queue (replaces RLock + cross-thread asyncio)
        self._cmd_queue: queue.Queue[MonitorCommand] = queue.Queue(maxsize=50)
        self._shutdown_event = threading.Event()

        # Lock-free status snapshot — written by consumer, read by API threads
        self._status_snapshot = StatusSnapshot()

        # WebSocket 广播队列 —— 由 _push_log / _queue_status_broadcast 写入，
        # 从主事件循环异步排空
        self._ws_broadcast_queue: deque[dict] = deque(maxlen=200)

        # 登录并发控制 —— 防止同时提交多个登录任务到 Worker
        # 使用 Lock 保护 check-then-set 操作，避免竞态条件
        self._login_in_progress: bool = False
        self._login_lock: threading.Lock = threading.Lock()

        # Start queue consumer daemon thread
        self._consumer_thread = threading.Thread(
            target=self._queue_consumer, daemon=True
        )
        self._consumer_thread.start()

    # ── 队列消费者（在专用守护线程中运行）──

    def _queue_consumer(self) -> None:
        """专用线程：从 _cmd_queue 拉取命令并执行。

        消费者线程在整个进程生命周期内运行，
        仅 "shutdown" 命令会跳出循环。
        """
        while not self._shutdown_event.is_set():
            try:
                cmd = self._cmd_queue.get(timeout=0.1)
            except queue.Empty:
                continue

            try:
                if cmd.type == "start":
                    self._handle_start(cmd)
                elif cmd.type == "stop":
                    self._handle_stop()
                elif cmd.type == "login":
                    self._handle_login(cmd)
                elif cmd.type == "reload":
                    self._handle_reload(cmd)
                elif cmd.type == "profile_switch":
                    self._handle_profile_switch(cmd)
                elif cmd.type == "shutdown":
                    self._handle_stop()
                    break
            except Exception:
                service_logger.exception("队列命令执行失败: %s", cmd.type)
            finally:
                self._cmd_queue.task_done()

    def _handle_start(self, cmd: MonitorCommand) -> None:
        """启动监控（仅在消费者线程中调用）。"""
        # 二次检查：防止重复启动
        if self._monitor_thread and self._monitor_thread.is_alive():
            self._push_log("监控线程已在运行，忽略重复启动", level="WARNING", source="backend.monitor_service")
            return
        config = cmd.data.get("config", self._runtime_config.copy())
        pure_mode = cmd.data.get("pure_mode", self.pure_mode)
        if pure_mode:
            config.setdefault("browser_settings", {})["pure_mode"] = True
        self._thread_done.clear()
        core = NetworkMonitorCore(
            config=config,
            log_callback=self._push_log,
            thread_done=self._thread_done,
        )
        core.set_profile_service(
            self._profile_service, on_switch=self._on_profile_switch
        )
        thread = threading.Thread(target=core.start_monitoring, daemon=True)

        self._monitor_core = core
        self._monitor_thread = thread
        thread.start()

        self._push_log("监控线程已启动", level="INFO", source="backend.monitor_service")
        self._update_status_snapshot()

    def _handle_stop(self) -> None:
        """停止监控（仅在消费者线程中调用）。"""
        core = self._monitor_core
        thread = self._monitor_thread

        if core:
            core.stop_monitoring()

        if thread:
            thread.join(timeout=8)
            if thread.is_alive():
                self._thread_done.wait(timeout=10)

        self._monitor_core = None
        self._monitor_thread = None
        self._thread_done.clear()

        self._push_log("监控已停止", level="INFO", source="backend.monitor_service")
        self._update_status_snapshot()

    def _handle_login(self, cmd: MonitorCommand) -> None:
        """执行一次性登录尝试（仅在消费者线程中调用）。"""
        config = cmd.data.get("config", self._runtime_config.copy())
        pure_mode = cmd.data.get("pure_mode", self.pure_mode)
        skip_pause_check = cmd.data.get("skip_pause_check", False)
        if pure_mode:
            config.setdefault("browser_settings", {})["pure_mode"] = True

        # 通过 Worker 派发登录，替代临时 NetworkMonitorCore 实例
        login_timeout = getattr(self._ui_config, "login_timeout", 120)
        try:
            result = get_worker().submit(
                CMD_LOGIN,
                data={
                    "config": config,
                    "pure_mode": pure_mode,
                    "skip_pause_check": skip_pause_check,
                },
                timeout=login_timeout,
            )
            if result.success:
                cmd.response_data = (True, result.data)
            else:
                cmd.response_data = (False, result.error or "登录失败")
        except Exception as exc:
            service_logger.exception(
                "手动登录异常 (username=%s, url=%s)",
                config.get("username", "?"), config.get("auth_url", "?"),
            )
            cmd.response_data = (False, str(exc))

        if cmd.response_event:
            cmd.response_event.set()

    def _handle_reload(self, cmd: MonitorCommand) -> None:
        """Hot-update config on a running monitor (consumer thread only)."""
        new_config = cmd.data.get("config")
        if new_config and self._monitor_core and self._monitor_core.monitoring:
            self._monitor_core.update_config(new_config)

    def _handle_profile_switch(self, cmd: MonitorCommand) -> None:
        """停止当前监控并使用新方案配置重新启动。"""
        new_config = cmd.data.get("config", {})
        if not new_config:
            return

        self._handle_stop()

        pure_mode = cmd.data.get("pure_mode", self.pure_mode)
        if pure_mode:
            new_config.setdefault("browser_settings", {})["pure_mode"] = True

        self._thread_done.clear()
        core = NetworkMonitorCore(
            config=new_config,
            log_callback=self._push_log,
            thread_done=self._thread_done,
        )
        core.set_profile_service(
            self._profile_service, on_switch=self._on_profile_switch
        )
        thread = threading.Thread(target=core.start_monitoring, daemon=True)

        self._monitor_core = core
        self._monitor_thread = thread
        thread.start()

        self._push_log(
            "监控已按新方案重启", level="INFO", source="backend.monitor_service"
        )
        self._update_status_snapshot()

    # ── 日志 / 状态快照桥接 ──

    def _push_log(
        self, message: str, level: str = "INFO", source: str = "monitor"
    ) -> None:
        """Record a log entry + queue WebSocket broadcast (no asyncio cross-thread calls)."""
        stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        level_name = str(level or "INFO").upper()
        source_name = str(source or "monitor")
        entry = LogEntry(
            timestamp=stamp,
            level=level_name,
            source=source_name,
            message=message,
        )
        self._logs.append(entry)

        # 同步写入 Python 日志系统 → 自动持久化到文件
        log_level = (
            getattr(logging, level_name, logging.INFO)
            if hasattr(logging, level_name)
            else logging.INFO
        )
        record = service_logger.makeRecord(
            service_logger.name,
            log_level,
            "(monitor_service)",
            0,
            "[%s] %s",
            (source_name, message),
            None,
        )
        record.side = "FRONTEND" if source_name == "frontend" else "BACKEND"
        service_logger.handle(record)

        # 监控相关日志 → 更新状态快照
        if source_name in ("monitor.core", "monitor", "network"):
            self._update_status_snapshot()

        # 排队 WebSocket 广播（主事件循环的 drain_ws_queue 异步消费）
        self._ws_broadcast_queue.append(
            {
                "type": "log",
                "data": {
                    "timestamp": stamp,
                    "level": level_name,
                    "source": source_name,
                    "message": message,
                },
            }
        )

    def _update_status_snapshot(self) -> None:
        """Read monitor_core state into lock-free StatusSnapshot."""
        core = self._monitor_core
        if core is not None:
            try:
                snap = core.snapshot()
                # 将 network_state 枚举转换为 network_connected 布尔值
                network_state = snap.get("network_state", "unknown")
                network_connected = network_state == "connected"
                self._status_snapshot = StatusSnapshot(
                    monitoring=core.monitoring,
                    last_network_ok=network_connected,
                    start_time=snap.get("start_time"),
                    network_check_count=int(snap.get("network_check_count", 0)),
                    login_attempt_count=int(snap.get("login_attempt_count", 0)),
                    last_check_time=snap.get("last_check_time"),
                    snapshot_time=time.time(),
                    status_detail=snap.get("status_detail", "正常"),
                    network_state=network_state,
                )
            except Exception:
                service_logger.exception("状态快照更新失败")
                return
        else:
            self._status_snapshot = StatusSnapshot(
                snapshot_time=time.time(), status_detail="已停止"
            )

        self._queue_status_broadcast()

    def _queue_status_broadcast(self) -> None:
        """将当前状态放入 WS 广播队列。"""
        try:
            status = self.get_status()
            self._ws_broadcast_queue.append(
                {"type": "status", "data": status.model_dump()}
            )
        except Exception:
            service_logger.exception("状态广播队列失败")

    # ── WebSocket 排空（主事件循环）──

    async def _ws_drain_loop(self) -> None:
        """后台 asyncio 任务：定期排空 WS 广播队列。

        Runs until the asyncio task is cancelled (by lifespan shutdown).
        """
        while True:
            try:
                await asyncio.sleep(0.05)
                await self.drain_ws_queue()
            except asyncio.CancelledError:
                break
            except Exception:
                service_logger.exception("WS drain loop error")

    async def drain_ws_queue(self) -> None:
        """Flush pending WS broadcast messages to WebSocket clients.

        Called by the main asyncio event loop (via _ws_drain_loop).
        No cross-thread asyncio calls remain in this module.
        """
        while True:
            try:
                data = self._ws_broadcast_queue.popleft()
            except IndexError:
                break
            if self._ws_manager:
                await self._ws_manager.broadcast(json.dumps(data))

    # ── 公共 API（从 API 线程 / main.py 调用）──

    def boot(self) -> None:
        # --no-auto 启动标志：跳过 login_then_exit 和 auto_start，用于恢复设置
        if os.environ.pop("CAMPUS_AUTH_NO_AUTO", None):
            service_logger.info("--no-auto 模式：跳过自动启动监控")
            return

        # WS drain loop 由 main.py lifespan 统一启动和管理生命周期

        if self._ui_config.auto_start:
            self.start_monitoring()

    @property
    def login_in_progress(self) -> bool:
        return self._login_in_progress

    @property
    def _is_monitoring(self) -> bool:
        """Read monitoring state from lock-free snapshot."""
        return self._status_snapshot.monitoring

    def get_config(self) -> MonitorConfigPayload:
        return self._ui_config.model_copy(deep=True)

    def reload_config(self) -> None:
        """重新加载配置（从 settings.json），并通过队列推送到运行中的监控"""
        self._ui_config = load_ui_config(self._profile_service)
        self._runtime_config = build_runtime_config(
            load_runtime_config(self._profile_service),
            self._profile_service.load().system,
        )

        # Consumer handles the hot-update on the monitor core
        if self._is_monitoring:
            self._cmd_queue.put(
                MonitorCommand(
                    type="reload",
                    data={"config": self._runtime_config.copy()},
                )
            )

        service_logger.info("Config reloaded from settings.json")

    def apply_profile(self, profile_name: str) -> None:
        """切换到新方案并通过队列重启监控"""
        self.reload_config()
        new_url = self._runtime_config.get("auth_url", "")
        new_user = self._runtime_config.get("username", "")
        self._push_log(
            f"切换方案 → {profile_name} (认证={new_url}, 用户={new_user})",
            level="INFO",
            source="backend.monitor_service",
        )

        if self._is_monitoring:
            self._cmd_queue.put(
                MonitorCommand(
                    type="profile_switch",
                    data={
                        "profile": profile_name,
                        "config": self._runtime_config.copy(),
                        "pure_mode": self.pure_mode,
                    },
                )
            )
            self._push_log(
                "监控正在按新方案重启",
                level="INFO",
                source="backend.monitor_service",
            )

    def start_monitoring(self) -> tuple[bool, str]:
        service_logger.info("收到启动监控请求")
        if self._is_monitoring:
            return False, "监控已在运行中"

        valid, error = ConfigValidator.validate_env_config(self._runtime_config)
        if not valid:
            return False, f"配置无效: {error}"

        config = self._runtime_config.copy()
        self._cmd_queue.put(
            MonitorCommand(
                type="start", data={"config": config, "pure_mode": self.pure_mode}
            )
        )

        return True, "监控已启动"

    def _on_profile_switch(self, profile_name: str) -> None:
        """自动切换方案时的回调（从监控线程调用）。"""
        self.reload_config()
        new_url = self._runtime_config.get("auth_url", "")
        new_user = self._runtime_config.get("username", "")
        self._push_log(
            f"自动切换方案 → {profile_name} (认证={new_url}, 用户={new_user})",
            level="INFO",
            source="backend.monitor_service",
        )

    def stop_monitoring(self) -> tuple[bool, str]:
        service_logger.info("收到停止监控请求")
        if not self._is_monitoring:
            return False, "监控未运行"

        self._cmd_queue.put(MonitorCommand(type="stop"))
        return True, "监控已停止"

    def shutdown(self) -> None:
        """完全关闭 MonitorService：停止监控 + 终止消费者线程。"""
        # 停止监控（如果正在运行）
        if self._is_monitoring:
            self._cmd_queue.put(MonitorCommand(type="stop"))

        # 设置关闭事件，通知消费者线程退出循环
        self._shutdown_event.set()

        # 发送 shutdown 命令确保消费者能立即处理退出
        try:
            self._cmd_queue.put_nowait(MonitorCommand(type="shutdown"))
        except queue.Full:
            pass

        # 等待消费者线程结束
        if self._consumer_thread and self._consumer_thread.is_alive():
            self._consumer_thread.join(timeout=5)

        service_logger.info("MonitorService 已关闭")

    def get_status(self) -> MonitorStatusResponse:
        """Lock-free status read directly from StatusSnapshot."""
        snap = self._status_snapshot
        runtime_seconds = (
            int(time.time() - snap.start_time)
            if snap.monitoring and snap.start_time
            else 0
        )
        return MonitorStatusResponse(
            monitoring=snap.monitoring,
            network_check_count=snap.network_check_count,
            login_attempt_count=snap.login_attempt_count,
            last_check_time=snap.last_check_time,
            runtime_seconds=runtime_seconds,
            network_connected=snap.monitoring and snap.last_network_ok,
            status_detail=snap.status_detail,
            network_state=snap.network_state,
        )

    def run_manual_login(self) -> tuple[bool, str]:
        with self._login_lock:
            if self._login_in_progress:
                return False, "登录操作正在进行中"
            self._login_in_progress = True
        try:
            service_logger.info("Manual login requested")
            runtime_config = self._runtime_config.copy()

            cmd = MonitorCommand(
                type="login",
                data={
                    "config": runtime_config,
                    "pure_mode": self.pure_mode,
                    "skip_pause_check": True,
                },
                response_event=threading.Event(),
            )
            self._cmd_queue.put(cmd)

            # Wait for consumer to execute login (with timeout)
            login_timeout = getattr(self._ui_config, "login_timeout", 120)
            cmd.response_event.wait(timeout=login_timeout)

            if cmd.response_data is None:
                return False, "手动登录超时"

            success, message = cmd.response_data
            if success:
                # Sync status to running monitor core if active
                core = self._monitor_core
                if core is not None and core.monitoring:
                    core.last_network_ok = True
                self._update_status_snapshot()
                service_logger.info("Manual login succeeded")
                return True, f"手动登录成功：{message}"

            log_msg = re.sub(SCREENSHOT_URL_PATTERN, "", message)
            service_logger.warning("Manual login failed: %s", log_msg)
            return False, f"手动登录失败：{message}"
        finally:
            with self._login_lock:
                self._login_in_progress = False

    def test_network(self) -> tuple[bool, str]:
        service_logger.info("手动网络测试")
        config = self._runtime_config.copy()
        monitor_cfg = config.get("monitor", {})
        targets = monitor_cfg.get("ping_targets", [])
        enable_tcp = monitor_cfg.get("enable_tcp_check", True)
        enable_http = monitor_cfg.get("enable_http_check", True)
        portal_checks = monitor_cfg.get("portal_check_urls", None)
        # 解析 host:port 为 (host, port) 元组列表
        test_sites = parse_host_port(targets)
        mode_desc = []
        if enable_tcp:
            mode_desc.append("TCP")
        if enable_http:
            mode_desc.append("HTTP")
        if portal_checks:
            mode_desc.append("Portal")
        self._push_log(
            f"手动网络测试 → 目标={len(test_sites)} 检测方式={'+'.join(mode_desc) or '无'}",
            "INFO",
            "network",
        )
        try:
            ok = is_network_available(
                test_sites=test_sites if test_sites else None,
                timeout=2,
                enable_tcp=enable_tcp,
                enable_http=enable_http,
                portal_checks=portal_checks if portal_checks else None,
            )
            if ok:
                self._push_log("手动测试结果: 网络正常", "INFO", "network")
                return True, "网络连接正常"
            else:
                self._push_log("手动测试结果: 网络异常", "WARNING", "network")
                return False, "网络连接异常"
        except Exception as exc:
            service_logger.exception("Network test failed")
            self._push_log(f"手动测试异常: {exc}", "ERROR", "network")
            return False, f"网络测试失败: {exc}"

    def list_logs(self, limit: int = 200) -> list[LogEntry]:
        if limit <= 0:
            return []
        snapshot = list(self._logs)
        if len(snapshot) <= limit:
            return snapshot
        return snapshot[-limit:]

    def toggle_pure_mode(self) -> bool:
        """切换纯净模式，返回新值"""
        with self._login_lock:
            new_value = not self.pure_mode
            data = self._profile_service.load()
            data.system.pure_mode = new_value
            self._profile_service.save(data)
            self.pure_mode = new_value
            return new_value

    def get_runtime_config(self) -> dict:
        """线程安全地获取运行时配置副本"""
        return self._runtime_config.copy()
