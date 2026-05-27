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

from fastapi import WebSocket

from src.monitor_core import NetworkMonitorCore
from src.playwright_worker import get_worker, CMD_LOGIN
from src.network_decision import is_network_available
from src.utils import ConfigValidator
from src.utils.logging import get_logger
from src.utils.login import SCREENSHOT_URL_PATTERN
from src.utils.network_helpers import parse_host_port

from .config_service import build_runtime_config, load_runtime_config, load_ui_config
from .profile_service import ProfileService
from .schemas import LogEntry, MonitorConfigPayload, MonitorStatusResponse


# ── Actor model: typed command dispatch ──


@dataclass
class MonitorCommand:
    """Command dispatched from API thread to queue consumer thread."""

    type: str  # "start" | "stop" | "login" | "reload" | "profile_switch" | "shutdown"
    data: dict = field(default_factory=dict)
    response_event: threading.Event | None = None  # caller waits on this
    response_data: Any = None  # set by consumer


@dataclass
class StatusSnapshot:
    """Lock-free snapshot of monitor state, read directly by API handlers."""

    monitoring: bool = False
    last_network_ok: bool = False
    start_time: float | None = None
    network_check_count: int = 0
    login_attempt_count: int = 0
    last_check_time: str | None = None
    snapshot_time: float = 0.0


# ── WebSocket Manager (unchanged) ──


class WebSocketManager:
    """WebSocket 管理器 - 实时日志推送"""

    def __init__(self):
        self._connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self._connections.append(websocket)

    async def disconnect(self, websocket: WebSocket):
        if websocket in self._connections:
            self._connections.remove(websocket)

    async def broadcast(self, message: str):
        """广播消息（直接发送，保证实时性）"""
        connections = self._connections.copy()

        if not connections:
            return

        # 并发发送给所有连接
        tasks = [self._send_safe(ws, message) for ws in connections]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 清理断开连接
        for ws, result in zip(connections, results):
            if isinstance(result, Exception) and ws in self._connections:
                self._connections.remove(ws)

    async def close_all(self):
        """关闭所有 WebSocket 连接"""
        connections = self._connections.copy()
        self._connections.clear()

        for ws in connections:
            try:
                await ws.close(code=1001, reason="Server shutting down")
            except Exception:
                pass

    async def _send_safe(self, ws: WebSocket, message: str):
        await ws.send_text(message)


ws_manager = WebSocketManager()
service_logger = get_logger("backend.monitor_service", side="BACKEND")


# ── MonitorService (refactored to Actor model) ──


class MonitorService:
    def __init__(
        self, project_root: Path, profile_service: ProfileService | None = None
    ):
        self.project_root = project_root
        self._profile_service = profile_service or ProfileService(project_root)

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
        self.safe_mode: bool = self._profile_service.load().system.safe_mode

        # Actor model: command dispatch queue (replaces RLock + cross-thread asyncio)
        self._cmd_queue: queue.Queue[MonitorCommand] = queue.Queue(maxsize=50)
        self._shutdown_event = threading.Event()

        # Lock-free status snapshot — written by consumer, read by API threads
        self._status_snapshot = StatusSnapshot()

        # WebSocket broadcast queue — fed by _push_log / _queue_status_broadcast,
        # drained asynchronously from the main event loop
        self._ws_broadcast_queue: deque[dict] = deque(maxlen=200)

        # Guard against duplicate WS drain loop startup
        self._drain_started = False

        # Login concurrency guard — 防止同时启动多个浏览器进程
        # 使用 Lock 保护 check-then-set 操作，避免竞态条件
        self._login_in_progress: bool = False
        self._login_lock: threading.Lock = threading.Lock()

        # Start queue consumer daemon thread
        self._consumer_thread = threading.Thread(
            target=self._queue_consumer, daemon=True
        )
        self._consumer_thread.start()

    # ── Queue consumer (runs in dedicated daemon thread) ──

    def _queue_consumer(self) -> None:
        """Dedicated thread: pull commands from _cmd_queue and execute them.

        The consumer thread runs for the entire process lifetime.
        Only the "shutdown" command breaks the loop.
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
                service_logger.exception("Queue command failed: %s", cmd.type)
            finally:
                self._cmd_queue.task_done()

    def _handle_start(self, cmd: MonitorCommand) -> None:
        """Start monitoring (consumer thread only)."""
        config = cmd.data.get("config", self._runtime_config.copy())
        safe_mode = cmd.data.get("safe_mode", self.safe_mode)
        if safe_mode:
            config.setdefault("browser_settings", {})["safe_mode"] = True
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
        """Stop monitoring (consumer thread only)."""
        core = self._monitor_core
        thread = self._monitor_thread

        if core:
            core.stop_monitoring()

        if thread:
            thread.join(timeout=3)
            if thread.is_alive():
                self._thread_done.wait(timeout=5)

        self._monitor_core = None
        self._monitor_thread = None
        self._thread_done.clear()

        self._push_log("监控已停止", level="INFO", source="backend.monitor_service")
        self._update_status_snapshot()

    def _handle_login(self, cmd: MonitorCommand) -> None:
        """Execute a one-shot login attempt (consumer thread only)."""
        config = cmd.data.get("config", self._runtime_config.copy())
        safe_mode = cmd.data.get("safe_mode", self.safe_mode)
        skip_pause_check = cmd.data.get("skip_pause_check", False)
        if safe_mode:
            config.setdefault("browser_settings", {})["safe_mode"] = True

        # 通过 Worker 派发登录，替代临时 NetworkMonitorCore 实例
        login_timeout = getattr(self._ui_config, "login_timeout", 120)
        try:
            result = get_worker().submit(
                CMD_LOGIN,
                data={
                    "config": config,
                    "safe_mode": safe_mode,
                    "skip_pause_check": skip_pause_check,
                },
                timeout=login_timeout,
            )
            if result.success:
                cmd.response_data = (True, result.data)
            else:
                cmd.response_data = (False, result.error or "登录失败")
        except Exception as exc:
            service_logger.exception("Manual login failed with exception")
            cmd.response_data = (False, str(exc))

        if cmd.response_event:
            cmd.response_event.set()

    def _handle_reload(self, cmd: MonitorCommand) -> None:
        """Hot-update config on a running monitor (consumer thread only)."""
        new_config = cmd.data.get("config")
        if new_config and self._monitor_core and self._monitor_core.monitoring:
            self._monitor_core.update_config(new_config)

    def _handle_profile_switch(self, cmd: MonitorCommand) -> None:
        """Stop current monitoring and start with a new profile's config."""
        new_config = cmd.data.get("config", {})
        if not new_config:
            return

        self._handle_stop()

        safe_mode = cmd.data.get("safe_mode", self.safe_mode)
        if safe_mode:
            new_config.setdefault("browser_settings", {})["safe_mode"] = True

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

    # ── Logging / snapshot bridge ──

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
                self._status_snapshot = StatusSnapshot(
                    monitoring=core.monitoring,
                    last_network_ok=bool(snap.get("last_network_ok")),
                    start_time=snap.get("start_time"),
                    network_check_count=int(snap.get("network_check_count", 0)),
                    login_attempt_count=int(snap.get("login_attempt_count", 0)),
                    last_check_time=snap.get("last_check_time"),
                    snapshot_time=time.time(),
                )
            except Exception:
                service_logger.exception("Status snapshot update failed")
                return
        else:
            self._status_snapshot = StatusSnapshot(snapshot_time=time.time())

        self._queue_status_broadcast()

    def _queue_status_broadcast(self) -> None:
        """Put current status onto the WS broadcast queue."""
        try:
            status = self.get_status()
            self._ws_broadcast_queue.append(
                {"type": "status", "data": status.model_dump()}
            )
        except Exception:
            service_logger.exception("Status broadcast queue failed")

    # ── WebSocket drain (main event loop) ──

    async def _ws_drain_loop(self) -> None:
        """Background asyncio task: periodically drain WS broadcast queue.

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
            await ws_manager.broadcast(json.dumps(data))

    # ── Public API (called from API threads / main.py) ──

    def boot(self) -> None:
        # --no-auto 启动标志：跳过 login_then_exit 和 auto_start，用于恢复设置
        if os.environ.pop("CAMPUS_AUTH_NO_AUTO", None):
            service_logger.info("--no-auto 模式：跳过自动启动监控")
            return

        # Start the async WS drain loop if a running loop is available
        if not self._drain_started:
            try:
                asyncio.ensure_future(self._ws_drain_loop())
                self._drain_started = True
            except RuntimeError:
                pass

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
                        "safe_mode": self.safe_mode,
                    },
                )
            )
            self._push_log(
                "监控已按新方案重启",
                level="INFO",
                source="backend.monitor_service",
            )

    def start_monitoring(self) -> tuple[bool, str]:
        service_logger.info("Start monitoring requested")
        if self._is_monitoring:
            return False, "监控已在运行中"

        valid, error = ConfigValidator.validate_env_config(self._runtime_config)
        if not valid:
            return False, f"配置无效: {error}"

        config = self._runtime_config.copy()
        self._cmd_queue.put(
            MonitorCommand(
                type="start", data={"config": config, "safe_mode": self.safe_mode}
            )
        )

        return True, "监控已启动"

    def _on_profile_switch(self, profile_name: str) -> None:
        """自动切换方案时的回调（从监控线程调用）。

        Reloads config files and sends a reload command to the queue consumer,
        which will hot-update the running NetworkMonitorCore.
        """
        new_url = self._runtime_config.get("auth_url", "")
        new_user = self._runtime_config.get("username", "")
        self._push_log(
            f"自动切换方案 → {profile_name} (认证={new_url}, 用户={new_user})",
            level="INFO",
            source="backend.monitor_service",
        )
        self.reload_config()

    def stop_monitoring(self) -> tuple[bool, str]:
        service_logger.info("Stop monitoring requested")
        if not self._is_monitoring:
            return False, "监控未运行"

        self._cmd_queue.put(MonitorCommand(type="stop"))
        return True, "监控已停止"

    def get_status(self) -> MonitorStatusResponse:
        """Lock-free status read directly from StatusSnapshot."""
        snap = self._status_snapshot
        runtime_seconds = (
            int(time.time() - snap.snapshot_time)
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
                    "safe_mode": self.safe_mode,
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
        # 解析 host:port 为 (host, port) 元组列表
        test_sites = parse_host_port(targets)
        mode_desc = []
        if enable_tcp:
            mode_desc.append("TCP")
        if enable_http:
            mode_desc.append("HTTP")
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

    def toggle_safe_mode(self) -> bool:
        """切换安全模式，返回新值"""
        new_value = not self.safe_mode
        data = self._profile_service.load()
        data.system.safe_mode = new_value
        self._profile_service.save(data)
        self.safe_mode = new_value
        return new_value

    def get_runtime_config(self) -> dict:
        """线程安全地获取运行时配置副本"""
        return self._runtime_config.copy()
