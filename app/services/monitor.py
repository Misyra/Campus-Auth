from __future__ import annotations

import asyncio
import contextlib
import copy
import json
import os
import queue
import re
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from app.constants import (
    MONITOR_RELOAD_TIMEOUT,
    MONITOR_STOP_TIMEOUT,
    MONITOR_THREAD_JOIN_TIMEOUT,
)
from app.core.monitor_core import NetworkMonitorCore, NetworkState
from app.network.decision import is_network_available
from app.schemas import MonitorConfigPayload, MonitorStatusResponse
from app.tasks import TaskManager
from app.utils import ConfigValidator
from app.utils.logging import get_logger
from app.utils.login import SCREENSHOT_URL_PATTERN
from app.utils.network_helpers import parse_host_port
from app.workers.playwright_worker import CMD_LOGIN
from app.ws_manager import WebSocketManager

from .config import build_runtime_config, load_runtime_config, load_ui_config
from .profile import ProfileService

# ── 常量 ──

# WS 广播队列排空间隔（秒）
WS_DRAIN_INTERVAL_SECONDS = 0.05

# ── Actor 模型：类型化命令派发 ──


class MonitorCmdType(StrEnum):
    """监控服务命令类型。"""

    START = "start"
    STOP = "stop"
    LOGIN = "login"
    RELOAD = "reload"
    PROFILE_SWITCH = "profile_switch"
    PROFILE_RELOAD = "profile_reload"
    SHUTDOWN = "shutdown"


@dataclass
class MonitorCommand:
    """从 API 线程派发到队列消费者线程的命令。"""

    type: MonitorCmdType
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


service_logger = get_logger("backend.monitor_service", source="backend")


# ── MonitorService（Actor 模型重构）──


class MonitorService:
    def __init__(
        self,
        project_root: Path,
        profile_service: ProfileService | None = None,
        ws_manager: WebSocketManager | None = None,
        login_history_service=None,
        worker_getter=None,
    ):
        self.project_root = project_root
        self._profile_service = profile_service or ProfileService(project_root)
        self._ws_manager = ws_manager
        self._login_history = login_history_service
        self._worker_getter = worker_getter
        self._task_manager = TaskManager(project_root / "tasks")

        # DashboardSink — 由 container.startup 注入
        self._dashboard_sink = None

        # 锁（必须在 _reload_config_internal 之前初始化）
        self._login_lock: threading.Lock = threading.Lock()
        self._reload_lock: threading.Lock = threading.Lock()
        self._pure_mode_lock: threading.Lock = threading.Lock()

        # 加载配置（复用 _reload_config_internal）
        self._reload_config_internal()

        self._monitor_core: NetworkMonitorCore | None = None
        self._monitor_thread: threading.Thread | None = None
        self._thread_done = threading.Event()
        self._pure_mode: bool = self._profile_service.load().system.pure_mode

        # Actor model: command dispatch queue (replaces RLock + cross-thread asyncio)
        self._cmd_queue: queue.Queue[MonitorCommand] = queue.Queue(maxsize=50)
        self._shutdown_event = threading.Event()

        # Lock-free status snapshot — written by consumer, read by API threads
        self._status_snapshot = StatusSnapshot()

        # 登录并发控制 —— 防止同时提交多个登录任务到 Worker
        self._login_in_progress = threading.Event()

        # Start queue consumer daemon thread
        self._consumer_thread = threading.Thread(
            target=self._queue_consumer, daemon=True
        )
        self._consumer_thread.start()

    # ── 队列消费者（在专用守护线程中运行）──

    # 命令类型 → handler 方法名
    _CMD_ROUTES: dict[MonitorCmdType, str] = {
        MonitorCmdType.START: "_handle_start",
        MonitorCmdType.STOP: "_handle_stop",
        MonitorCmdType.LOGIN: "_handle_login",
        MonitorCmdType.RELOAD: "_handle_reload",
        MonitorCmdType.PROFILE_SWITCH: "_handle_profile_switch",
        MonitorCmdType.PROFILE_RELOAD: "_handle_profile_reload",
    }

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
                if cmd.type == MonitorCmdType.SHUTDOWN:
                    self._handle_stop()
                    break

                handler_name = self._CMD_ROUTES.get(cmd.type)
                if handler_name:
                    getattr(self, handler_name)(cmd)
                    # "stop" 命令需要手动通知响应
                    if cmd.type == MonitorCmdType.STOP and cmd.response_event:
                        cmd.response_event.set()
            except Exception:
                service_logger.exception("队列命令执行失败: {}", cmd.type)
            finally:
                self._cmd_queue.task_done()

    def _start_monitor_core(self, config: dict, pure_mode: bool) -> None:
        """创建并启动监控核心（在消费者线程中调用，供 _handle_start 和 _handle_profile_switch 复用）。"""
        self._thread_done.clear()
        core = NetworkMonitorCore(
            config=config,
            log_callback=self.record_log,
            thread_done=self._thread_done,
            login_history=self._login_history,
            worker_getter=self._worker_getter,
        )
        core.set_profile_service(
            self._profile_service, on_switch=self._on_profile_switch
        )
        thread = threading.Thread(target=core.start_monitoring, daemon=True)

        self._monitor_core = core
        self._monitor_thread = thread
        thread.start()

    def _prepare_command_config(self, cmd: MonitorCommand) -> tuple[dict, bool]:
        """从命令数据中提取配置和 pure_mode，统一预处理。

        返回: (config_dict, pure_mode)
        """
        config = cmd.data.get("config", self._runtime_config)
        pure_mode = cmd.data.get("pure_mode", self.pure_mode)
        if config is self._runtime_config:
            config = {
                **self._runtime_config,
                "browser_settings": dict(
                    self._runtime_config.get("browser_settings", {})
                ),
            }
        if pure_mode:
            config.setdefault("browser_settings", {})["pure_mode"] = True
        return config, pure_mode

    def _handle_start(self, cmd: MonitorCommand) -> None:
        """启动监控（仅在消费者线程中调用）。"""
        # 二次检查：防止重复启动
        if self._monitor_thread and self._monitor_thread.is_alive():
            self.record_log(
                "监控线程已在运行，忽略重复启动",
                level="WARNING",
                source="backend.monitor_service",
            )
            return
        config, pure_mode = self._prepare_command_config(cmd)
        self._start_monitor_core(config, pure_mode)

        self.record_log(
            "监控线程已启动", level="INFO", source="backend.monitor_service"
        )
        self._update_status_snapshot()

    def _handle_stop(self, cmd: MonitorCommand | None = None) -> None:
        """停止监控（仅在消费者线程中调用）。"""
        # 幂等保护：如果已经停止，直接返回
        if self._monitor_core is None and self._monitor_thread is None:
            return

        core = self._monitor_core
        thread = self._monitor_thread

        if core:
            core.stop_monitoring()

        if thread:
            thread.join(timeout=MONITOR_THREAD_JOIN_TIMEOUT)
            if thread.is_alive():
                self._thread_done.wait(timeout=MONITOR_STOP_TIMEOUT)
            if thread.is_alive():
                service_logger.warning("监控线程在超时后仍未结束")

        self._monitor_core = None
        self._monitor_thread = None
        self._thread_done.clear()

        self.record_log("监控已停止", level="INFO", source="backend.monitor_service")
        self._update_status_snapshot()

    def _handle_login(self, cmd: MonitorCommand) -> None:
        """执行一次性登录尝试（仅在消费者线程中调用）。"""
        config, pure_mode = self._prepare_command_config(cmd)
        skip_pause_check = cmd.data.get("skip_pause_check", False)

        # 通过 Worker 派发登录，替代临时 NetworkMonitorCore 实例
        login_timeout = getattr(self._ui_config, "login_timeout", 120)
        start_time = time.perf_counter()
        success = False
        error_msg = ""
        try:
            result = self._worker_getter().submit(
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
                success = True
                # 统一在消费者线程设置 network_state（BE-7 修复）
                core = self._monitor_core
                if core is not None and core.monitoring:
                    core.network_state = NetworkState.CONNECTED
            else:
                error_msg = result.error or "登录失败"
                cmd.response_data = (False, error_msg)
        except Exception as exc:
            service_logger.exception(
                "手动登录异常 (username={}, url={})",
                config.get("username", "?"),
                config.get("auth_url", "?"),
            )
            error_msg = str(exc)
            cmd.response_data = (False, error_msg)
        finally:
            duration_ms = int((time.perf_counter() - start_time) * 1000)
            self._login_in_progress.clear()
            # 记录登录历史
            if self._login_history is not None:
                try:
                    self._login_history.record(
                        success=success,
                        duration_ms=duration_ms,
                        profile_service=self._profile_service,
                        task_manager=self._task_manager,
                        error=error_msg,
                    )
                except Exception:
                    service_logger.debug("记录登录历史失败", exc_info=True)

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
        self._start_monitor_core(new_config, pure_mode)

        self.record_log(
            "监控已按新方案重启", level="INFO", source="backend.monitor_service"
        )
        self._update_status_snapshot()

    def _handle_profile_reload(self, cmd: MonitorCommand) -> None:
        """自动切换方案后重载配置（仅在消费者线程中调用）。"""
        profile_name = cmd.data.get("profile_name", "")
        try:
            # 直接在消费者线程中重载配置（不通过队列，避免递归入队）
            self._reload_config_internal()
        except Exception:
            service_logger.exception("自动切换方案配置加载失败: {}", profile_name)
            return
        if self._monitor_core and self._monitor_core.monitoring:
            try:
                self._cmd_queue.put_nowait(
                    MonitorCommand(
                        type=MonitorCmdType.RELOAD,
                        data={"config": self._copy_runtime_config()},
                    )
                )
            except queue.Full:
                service_logger.warning("命令队列已满，跳过 reload 命令入队")
        new_url = self._runtime_config.get("auth_url", "")
        new_user = self._runtime_config.get("username", "")
        self.record_log(
            f"自动切换方案 -> {profile_name} (认证={new_url}, 用户={new_user})",
            level="INFO",
            source="backend.monitor_service",
        )

    # ── 日志 / 状态快照桥接 ──

    def record_log(
        self, message: str, level: str = "INFO", source: str = "backend"
    ) -> None:
        """委托 loguru 统一处理（自动触发所有 sink）。"""
        bound_logger = get_logger("record", source)
        level_name = str(level or "INFO").upper()
        log_func = getattr(bound_logger, level_name.lower(), bound_logger.info)
        log_func("{}", message)

        # 监控相关日志 → 更新状态快照（业务逻辑，不属于日志管道）
        if source in ("network",):
            self._update_status_snapshot()

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
        else:
            self._status_snapshot = StatusSnapshot(
                snapshot_time=time.time(), status_detail="已停止"
            )

        self._queue_status_broadcast()

    def _queue_status_broadcast(self) -> None:
        """将当前状态放入 WS 广播队列。"""
        try:
            status = self.get_status()
            self.ws_broadcast_queue.append(
                {"type": "status", "data": status.model_dump()}
            )
        except Exception:
            service_logger.exception("状态广播队列失败")

    # ── WebSocket 排空（主事件循环）──

    async def ws_drain_loop(self) -> None:
        """后台 asyncio 任务：定期排空 WS 广播队列。

        Runs until the asyncio task is cancelled (by lifespan shutdown).
        """
        while True:
            try:
                await asyncio.sleep(WS_DRAIN_INTERVAL_SECONDS)
                await self.drain_ws_queue()
            except asyncio.CancelledError:
                break
            except Exception:
                service_logger.exception("WS 排空循环异常")

    async def drain_ws_queue(self) -> None:
        """Flush pending WS broadcast messages to WebSocket clients."""
        queue = self.ws_broadcast_queue
        while True:
            try:
                data = queue.popleft()
            except IndexError:
                break
            try:
                if self._ws_manager:
                    await self._ws_manager.broadcast(json.dumps(data))
            except Exception:
                service_logger.exception("WS 广播发送失败")

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
        return self._login_in_progress.is_set()

    @property
    def login_recovery_in_progress(self) -> bool:
        """监控是否正在进行登录恢复重试。"""
        core = self._monitor_core
        return core is not None and core._login_recovery_in_progress.is_set()

    def wait_for_login_recovery(self, timeout: float = 300) -> None:
        """等待监控登录恢复循环结束（供定时任务使用）。

        如果监控正在进行登录重试，阻塞直到重试循环结束或超时。
        """
        core = self._monitor_core
        if core is None or not core.monitoring:
            return
        core._login_recovery_in_progress.wait(timeout=timeout)

    @property
    def ws_broadcast_queue(self) -> deque:
        """WS 广播队列（从 DashboardSink 获取）。"""
        if self._dashboard_sink is None:
            return deque(maxlen=200)
        return self._dashboard_sink.broadcast_queue

    @property
    def pure_mode(self) -> bool:
        """线程安全地读取纯净模式标志。"""
        with self._pure_mode_lock:
            return self._pure_mode

    @property
    def _is_monitoring(self) -> bool:
        """Read monitoring state from lock-free snapshot."""
        return self._status_snapshot.monitoring

    def get_config(self) -> MonitorConfigPayload:
        with self._reload_lock:
            return self._ui_config.model_copy(deep=True)

    def _reload_config_internal(self) -> None:
        """从 settings.json 重新加载 UI 和运行时配置（内部方法，由 reload_config 和 _handle_profile_reload 复用）。"""
        with self._reload_lock:
            # 单次 load，避免多次 load 之间数据版本不一致
            data = self._profile_service.load()
            self._ui_config = load_ui_config(self._profile_service, data=data)
            runtime_payload, has_decrypt_error = load_runtime_config(
                self._profile_service, data=data
            )
            if has_decrypt_error:
                service_logger.warning("配置重载时部分密码解密失败")
            self._runtime_config = build_runtime_config(
                runtime_payload,
                data.system,
            )

    def _copy_runtime_config(self) -> dict:
        """深拷贝运行时配置，防止嵌套字典被意外修改。"""
        return copy.deepcopy(self._runtime_config)

    def reload_config(self) -> None:
        """重新加载配置（从 settings.json），并通过队列推送到运行中的监控"""
        self._reload_config_internal()

        # Consumer handles the hot-update on the monitor core
        if self._is_monitoring:
            try:
                self._cmd_queue.put_nowait(
                    MonitorCommand(
                        type=MonitorCmdType.RELOAD,
                        data={"config": self._copy_runtime_config()},
                    )
                )
            except queue.Full:
                service_logger.warning("命令队列已满，跳过 reload 命令入队")
                return

        service_logger.info("配置已从 settings.json 重载")

    def apply_profile(self, profile_id: str) -> None:
        """切换到新方案并通过队列重启监控"""
        self.reload_config()
        new_url = self._runtime_config.get("auth_url", "")
        new_user = self._runtime_config.get("username", "")

        # 解析可读名称用于日志，ID 作为 fallback
        try:
            data = self._profile_service.load()
            profile = data.profiles.get(profile_id)
            display_name = profile.name if profile else profile_id
        except Exception:
            display_name = profile_id

        self.record_log(
            f"切换方案 -> {display_name} (认证={new_url}, 用户={new_user})",
            level="INFO",
            source="backend.monitor_service",
        )

        if self._is_monitoring:
            try:
                self._cmd_queue.put_nowait(
                    MonitorCommand(
                        type=MonitorCmdType.PROFILE_SWITCH,
                        data={
                            "profile": profile_id,
                            "config": self._copy_runtime_config(),
                            "pure_mode": self.pure_mode,
                        },
                    )
                )
            except queue.Full:
                service_logger.warning("命令队列已满，跳过 profile_switch 命令入队")
                return
            self.record_log(
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

        config = self._copy_runtime_config()
        try:
            self._cmd_queue.put_nowait(
                MonitorCommand(
                    type=MonitorCmdType.START,
                    data={"config": config, "pure_mode": self.pure_mode},
                )
            )
        except queue.Full:
            service_logger.warning("命令队列已满，跳过 start 命令入队")
            return False, "队列已满"

        return True, "监控已启动"

    def _on_profile_switch(self, profile_name: str) -> None:
        """自动切换方案时的回调（从监控线程调用）。"""
        try:
            self._cmd_queue.put_nowait(
                MonitorCommand(
                    type=MonitorCmdType.PROFILE_RELOAD,
                    data={"profile_name": profile_name},
                )
            )
        except queue.Full:
            service_logger.warning(
                "命令队列已满(qsize={})，跳过 profile_reload 命令入队",
                self._cmd_queue.qsize(),
            )

    def stop_monitoring(self) -> tuple[bool, str]:
        service_logger.info("收到停止监控请求")
        if not self._is_monitoring:
            return False, "监控未运行"

        try:
            self._cmd_queue.put_nowait(MonitorCommand(type=MonitorCmdType.STOP))
        except queue.Full:
            service_logger.warning("命令队列已满，跳过 stop 命令入队")
            return False, "队列已满"
        return True, "监控已停止"

    def shutdown(self) -> None:
        """完全关闭 MonitorService：停止监控 + 终止消费者线程。"""
        # 通过队列发送 stop 命令（消费者执行 _handle_stop 后设置 response_event）
        try:
            cmd = MonitorCommand(
                type=MonitorCmdType.STOP, response_event=threading.Event()
            )
            self._cmd_queue.put(cmd, timeout=3)
            cmd.response_event.wait(timeout=MONITOR_RELOAD_TIMEOUT)
        except queue.Full:
            # 队列满时直接调用 _handle_stop() 作为回退
            if self._is_monitoring:
                self._handle_stop()

        # 设置关闭事件，通知消费者线程退出循环
        self._shutdown_event.set()

        # 发送 shutdown 命令确保消费者能立即处理退出
        with contextlib.suppress(queue.Full):
            self._cmd_queue.put_nowait(MonitorCommand(type=MonitorCmdType.SHUTDOWN))

        # 等待消费者线程结束
        if self._consumer_thread and self._consumer_thread.is_alive():
            self._consumer_thread.join(timeout=5)

        service_logger.info("监控服务已关闭")

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
            if self._login_in_progress.is_set():
                return False, "登录操作正在进行中"
            self._login_in_progress.set()
        cmd_in_queue = False
        try:
            service_logger.info("收到手动登录请求")
            runtime_config = self._copy_runtime_config()

            cmd = MonitorCommand(
                type=MonitorCmdType.LOGIN,
                data={
                    "config": runtime_config,
                    "pure_mode": self.pure_mode,
                    "skip_pause_check": True,
                },
                response_event=threading.Event(),
            )
            try:
                self._cmd_queue.put_nowait(cmd)
                cmd_in_queue = True
            except queue.Full:
                service_logger.warning("命令队列已满，跳过 login 命令入队")
                self._login_in_progress.clear()
                return False, "队列已满"
        except Exception:
            if not cmd_in_queue:
                self._login_in_progress.clear()
            raise

        # Wait for consumer to execute login (with timeout)
        login_timeout = getattr(self._ui_config, "login_timeout", 120)
        cmd.response_event.wait(timeout=login_timeout)

        if cmd.response_data is None:
            # 超时也主动清除，防止消费者线程异常时标志永久残留
            self._login_in_progress.clear()
            return False, "手动登录超时"

        success, message = cmd.response_data
        if success:
            # network_state 已由消费者 _handle_login 统一赋值，无需 API 线程操作
            self._update_status_snapshot()
            service_logger.info("手动登录成功")
            return True, f"手动登录成功：{message}"

        log_msg = re.sub(SCREENSHOT_URL_PATTERN, "", message)
        service_logger.warning("手动登录失败: {}", log_msg)
        return False, f"手动登录失败：{message}"

    def test_network(self) -> tuple[bool, str]:
        service_logger.info("手动网络测试")
        config = self._copy_runtime_config()
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
        self.record_log(
            f"手动网络测试 -> 目标={len(test_sites)} 检测方式={'+'.join(mode_desc) or '无'}",
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
                self.record_log("手动测试结果: 网络正常", "INFO", "network")
                return True, "网络连接正常"
            else:
                self.record_log("手动测试结果: 网络异常", "WARNING", "network")
                return False, "网络连接异常"
        except Exception as exc:
            service_logger.exception("网络测试失败")
            self.record_log(f"手动测试异常: {exc}", "ERROR", "network")
            return False, f"网络测试失败: {exc}"

    def list_logs(self, limit: int = 200) -> list:
        """返回最近 limit 条日志（从 DashboardSink 读取）。"""
        if limit <= 0 or self._dashboard_sink is None:
            return []
        return self._dashboard_sink.list_logs(limit=limit)

    def toggle_pure_mode(self) -> bool:
        """切换纯净模式，返回新值"""
        with self._pure_mode_lock:
            new_value = not self._pure_mode
            self._profile_service.update(
                lambda d: setattr(d.system, "pure_mode", new_value)
            )
            self._pure_mode = new_value
            return new_value

    def get_runtime_config(self) -> dict:
        """线程安全地获取运行时配置副本"""
        return self._copy_runtime_config()
