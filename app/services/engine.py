"""ScheduleEngine — 统一的后台服务引擎。

合并 MonitorService（网络监控）和 SchedulerService（定时任务调度）的全部功能，
使用 Actor 模型（线程 + 队列）进行命令派发，零 asyncio 依赖的核心逻辑。
"""

from __future__ import annotations

import contextlib
import copy
import json
import os
import queue
import re
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from app.constants import MONITOR_STOP_TIMEOUT
from app.core.monitor_core import NetworkMonitorCore, NetworkState
from app.network.decision import is_network_available
from app.schemas import MonitorConfigPayload, MonitorStatusResponse
from app.tasks import TaskManager, is_valid_task_id
from app.utils import ConfigValidator
from app.utils.file_helpers import atomic_write
from app.utils.logging import get_logger
from app.utils.login import SCREENSHOT_URL_PATTERN
from app.utils.network_helpers import parse_host_port
from app.utils.shell_policy import ShellCommandPolicy
from app.utils.shell_utils import detect_shells, get_default_shell
from app.ws_manager import WebSocketManager

from .config import build_runtime_config, load_runtime_config, load_ui_config
from .profile import ProfileService

# ── 常量 ──

# WS 广播队列排空间隔（秒）
WS_DRAIN_INTERVAL_SECONDS = 0.05

# 执行历史最大保留条数
MAX_HISTORY_SIZE = 50

# 监控停止超时（秒）
MONITOR_STOP_TIMEOUT_S = MONITOR_STOP_TIMEOUT

# 调度器检查间隔（秒）
SCHEDULER_CHECK_INTERVAL = 30

# 向后兼容：保留旧名称供 API 路由使用
detect_available_shells = detect_shells

# ── Actor 模型：类型化命令派发 ──


class EngineCmdType(StrEnum):
    """引擎命令类型。"""

    START = "start"
    STOP = "stop"
    LOGIN = "login"
    SHUTDOWN = "shutdown"
    RELOAD = "reload"
    APPLY_PROFILE = "apply_profile"


@dataclass
class EngineCommand:
    """从 API 线程派发到队列引擎线程的命令。"""

    type: EngineCmdType
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


engine_logger = get_logger("engine", source="backend")


# ── ScheduleEngine ──


class ScheduleEngine:
    """统一的后台服务引擎，合并网络监控与定时任务调度。"""

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
        # 固定的空广播队列，避免轻量模式下每次创建临时对象
        self._empty_broadcast_queue: deque = deque(maxlen=200)

        # 锁（必须在 _reload_config_internal 之前初始化）
        self._login_lock: threading.Lock = threading.Lock()
        self._reload_lock: threading.Lock = threading.Lock()
        self._pure_mode_lock: threading.Lock = threading.Lock()
        self._start_stop_lock: threading.Lock = threading.Lock()

        # 运行时配置快照（仅在 reload 时深拷贝，读取零拷贝）
        self._runtime_snapshot: dict = {}

        # 状态快照限流
        self._last_snapshot_time: float = 0
        self._SNAPSHOT_MIN_INTERVAL: float = 1.0

        # 加载配置（复用 _reload_config_internal）
        self._reload_config_internal()

        self._monitor_core: NetworkMonitorCore | None = None
        self._pure_mode: bool = self._profile_service.load().system.pure_mode

        # Actor model: command dispatch queue
        self._cmd_queue: queue.Queue[EngineCommand] = queue.Queue(maxsize=50)
        self._shutdown_event = threading.Event()

        # Lock-free status snapshot — written by consumer, read by API threads
        self._status_snapshot = StatusSnapshot()

        # 登录并发控制 —— 防止同时提交多个登录任务到 Worker
        self._login_in_progress = threading.Event()

        # ── 定时任务调度器状态 ──
        self._scheduler_tasks_dir = project_root / "tasks" / "scheduled"
        self._scheduler_history_dir = self._scheduler_tasks_dir / "history"
        self._scheduler_tasks_dir.mkdir(parents=True, exist_ok=True)
        self._scheduler_history_dir.mkdir(parents=True, exist_ok=True)

        self._scheduler_running = False
        self._running_task_threads: list[threading.Thread] = []
        self._running_tasks_lock = threading.Lock()
        self._history_lock = threading.Lock()
        self._last_triggered_minute: tuple[int, int] | None = None
        self._has_enabled_cache: tuple[float, bool] | None = None

        # Shell 安全策略
        self._shell_policy = ShellCommandPolicy(
            allowlist=[s["path"] for s in detect_available_shells()]
        )

        # ── 统一引擎状态 ──
        self._engine_running = False
        self._next_network_check: float = 0
        self._monitor_check_interval: int = 300
        self._login_retry_count: int = 0
        self._last_login_attempt: float = 0
        self._login_retry_config: tuple | None = None

        # 统一引擎线程
        self._engine_thread = threading.Thread(target=self._engine_loop, daemon=True)
        self._engine_thread.start()

    # ── 队列入队辅助 ──

    def _enqueue(self, cmd: EngineCommand, retries: int = 2) -> bool:
        """尝试将命令入队，带重试。返回 True 表示成功。"""
        for i in range(retries):
            try:
                self._cmd_queue.put_nowait(cmd)
                return True
            except queue.Full:
                if i < retries - 1:
                    time.sleep(0.05)
                else:
                    engine_logger.warning(
                        "命令队列已满 (type={})，操作被跳过", cmd.type
                    )
        return False

    # ── 队列消费者（在专用守护线程中运行）──

    # 命令类型 → handler 方法名
    _CMD_ROUTES: dict[EngineCmdType, str] = {
        EngineCmdType.START: "_handle_start",
        EngineCmdType.STOP: "_handle_stop",
        EngineCmdType.LOGIN: "_handle_login",
        EngineCmdType.RELOAD: "_handle_reload",
        EngineCmdType.APPLY_PROFILE: "_handle_apply_profile",
    }

    # ── 统一引擎循环 ──

    def _engine_loop(self) -> None:
        """统一引擎循环：命令处理 + 网络检测 + 定时任务调度。"""
        self._engine_running = True
        engine_logger.info("统一引擎循环已启动")

        while not self._shutdown_event.is_set():
            try:
                wakeup_time = self._calculate_wakeup()

                try:
                    timeout = max(0.01, wakeup_time - time.time())
                    cmd = self._cmd_queue.get(timeout=timeout)
                except queue.Empty:
                    cmd = None

                if cmd is not None:
                    self._process_command(cmd)
                    if cmd.type == EngineCmdType.SHUTDOWN:
                        break
                    continue

                now = time.time()

                # 网络检测
                if self._is_monitoring and now >= self._next_network_check:
                    self._do_network_check()

                # 登录重试
                if self._login_retry_needed(now):
                    self._do_async_login()

                # 定时任务
                if self._scheduler_running:
                    self._check_scheduled_tasks()
            except Exception:
                engine_logger.exception("引擎循环异常，继续运行")
                time.sleep(1)

        self._engine_running = False
        engine_logger.info("统一引擎循环已退出")

    def _calculate_wakeup(self) -> float:
        """计算下次唤醒时间。"""
        now = time.time()
        candidates: list[float] = [now + 60]

        try:
            if self._is_monitoring:
                candidates.append(float(self._next_network_check))

            if self._login_retry_count > 0 and self._login_retry_config:
                _, intervals = self._login_retry_config
                idx = self._login_retry_count - 1
                if idx < len(intervals):
                    candidates.append(float(self._last_login_attempt + intervals[idx]))

            if self._scheduler_running:
                candidates.append(now + float(SCHEDULER_CHECK_INTERVAL))
        except (TypeError, ValueError, AttributeError):
            # 异常时回退到默认唤醒时间
            return now + 5

        return min(candidates)

    def _process_command(self, cmd: EngineCommand) -> None:
        """处理一个命令。"""
        try:
            if cmd.type == EngineCmdType.SHUTDOWN:
                self._handle_stop()
            else:
                handler_name = self._CMD_ROUTES.get(cmd.type)
                if handler_name:
                    getattr(self, handler_name)(cmd)
        except Exception:
            engine_logger.exception("命令执行失败: {}", cmd.type)
        finally:
            if cmd.response_event:
                cmd.response_event.set()
            self._cmd_queue.task_done()

    def _do_network_check(self) -> None:
        """执行一次网络检测。"""
        if self._monitor_core is None:
            return

        try:
            result = self._monitor_core.check_once()
            interval = int(result.get("interval", self._monitor_check_interval))
            self._monitor_check_interval = interval

            if result.get("need_login", False):
                self._login_retry_config = self._get_retry_config()
                self._login_retry_count = 0
                self._do_async_login()
            else:
                self._login_retry_count = 0

            self._next_network_check = time.time() + interval
            self._update_status_snapshot()
        except Exception:
            engine_logger.exception("网络检测异常")
            self._next_network_check = time.time() + self._monitor_check_interval

    def _login_retry_needed(self, now: float) -> bool:
        """检查是否需要登录重试。"""
        if self._login_retry_count == 0 or not self._login_retry_config:
            return False
        if self._login_in_progress.is_set():
            return False
        max_retries, intervals = self._login_retry_config
        if self._login_retry_count >= max_retries:
            return False
        idx = self._login_retry_count - 1
        if idx >= len(intervals):
            return False
        return now >= self._last_login_attempt + intervals[idx]

    def _do_async_login(self) -> None:
        """在独立线程中执行登录（不阻塞引擎循环）。"""
        if self._login_in_progress.is_set():
            return
        self._login_in_progress.set()
        self._last_login_attempt = time.time()
        self._login_retry_count += 1

        def _login_thread():
            try:
                config = self._copy_runtime_config()
                pure_mode = self.pure_mode
                if pure_mode:
                    config.setdefault("browser_settings", {})["pure_mode"] = True
                login_timeout = getattr(self._ui_config, "login_timeout", 120)

                from app.workers.playwright_worker import CMD_LOGIN

                result = self._worker_getter().submit(
                    CMD_LOGIN,
                    data={
                        "config": config,
                        "pure_mode": pure_mode,
                        "skip_pause_check": False,
                    },
                    timeout=login_timeout,
                )

                if result.success:
                    if self._monitor_core:
                        self._monitor_core.update_status_after_login(True)
                    self._login_retry_count = 0
                else:
                    if self._monitor_core:
                        self._monitor_core.update_status_after_login(
                            False, result.error or ""
                        )
            except Exception as e:
                engine_logger.exception("异步登录异常")
                if self._monitor_core:
                    self._monitor_core.update_status_after_login(False, str(e))
            finally:
                self._login_in_progress.clear()
                self._update_status_snapshot()

        threading.Thread(target=_login_thread, daemon=True).start()

    def _get_retry_config(self) -> tuple[int, list[int]]:
        """获取登录重试配置。"""
        try:
            config = self._copy_runtime_config()
            retry = config.get("retry_settings", {})
            max_retries = retry.get("max_retries", 3)
            interval = retry.get("retry_interval", 30)
            intervals = [interval] * max_retries
            return max_retries, intervals
        except Exception:
            return 3, [30, 30, 30]

    def _check_scheduled_tasks(self) -> None:
        """检查并执行到期的定时任务。"""
        now = datetime.now()
        current_minute = (now.hour, now.minute)
        if current_minute == self._last_triggered_minute:
            return
        if not self.has_enabled_tasks():
            return
        self._last_triggered_minute = current_minute

        tasks = self.list_tasks()
        for task in tasks:
            if not task.get("enabled", False):
                continue
            schedule = task.get("schedule", {})
            if now.hour != schedule.get("hour", -1) or now.minute != schedule.get("minute", -1):
                continue
            task_id = task.get("id", "")
            engine_logger.info("触发定时任务: {}", task_id)
            t = threading.Thread(
                target=self._execute_task_wrapper, args=(task_id,), daemon=True
            )
            with self._running_tasks_lock:
                self._running_task_threads.append(t)
            t.start()

    def _handle_start(self, cmd: EngineCommand) -> None:
        """启动监控（在引擎循环中调用）。"""
        if self._monitor_core is not None and self._monitor_core.monitoring:
            self.record_log(
                "监控已在运行中，忽略重复启动",
                level="WARNING",
                source="backend",
            )
            return

        config = self._copy_runtime_config()
        pure_mode = cmd.data.get("pure_mode", self.pure_mode)
        if pure_mode:
            config.setdefault("browser_settings", {})["pure_mode"] = True

        core = NetworkMonitorCore(
            config=config,
            log_callback=self.record_log,
            login_history=self._login_history,
            worker_getter=self._worker_getter,
        )
        core.set_profile_service(self._profile_service)
        core.init_monitoring()  # 只初始化，不启动循环
        self._monitor_core = core
        self._next_network_check = time.time()  # 立即执行第一次检测
        self._login_retry_count = 0
        self._update_status_snapshot()
        self.record_log("监控已启动（统一引擎驱动）", level="INFO", source="backend")

    def _handle_stop(self, cmd: EngineCommand | None = None) -> None:
        """停止监控。"""
        core = self._monitor_core
        if core is None:
            return

        core.stop_monitoring()
        self._monitor_core = None
        self._login_retry_count = 0
        self._next_network_check = 0

        self.record_log("监控已停止", level="INFO", source="backend")
        self._update_status_snapshot()

    def _handle_login(self, cmd: EngineCommand) -> None:
        """执行一次性登录（手动触发，异步执行）。"""
        self._do_async_login()
        cmd.response_data = (True, "登录已提交")

    def _handle_reload(self, cmd: EngineCommand) -> None:
        """重载配置并重启监控（仅在引擎线程中调用）。"""
        was_monitoring = self._is_monitoring
        if was_monitoring:
            self._handle_stop()
        self._reload_config_internal()
        if was_monitoring:
            self._handle_start(EngineCommand(type=EngineCmdType.START))
        engine_logger.info("配置已从 settings.json 重载")

    def _handle_apply_profile(self, cmd: EngineCommand) -> None:
        """切换方案并重启监控（仅在引擎线程中调用）。"""
        profile_id = cmd.data.get("profile_id", "")
        was_monitoring = self._is_monitoring
        if was_monitoring:
            self._handle_stop()

        # 重载配置（方案已由 API 路由持久化，此处重新读取）
        self._reload_config_internal()

        # 直接用 profile_id 记录日志，避免重复 load
        new_url = self._runtime_config.get("auth_url", "")
        new_user = self._runtime_config.get("username", "")
        self.record_log(
            f"切换方案 -> {profile_id} (认证={new_url}, 用户={new_user})",
            level="INFO",
            source="backend",
        )

        if was_monitoring:
            self._handle_start(EngineCommand(type=EngineCmdType.START))
            self.record_log(
                "监控正在按新方案重启",
                level="INFO",
                source="backend",
            )

    # ── 日志 / 状态快照桥接 ──

    def record_log(
        self, message: str, level: str = "INFO",
        source: str = "backend", name: str = "engine"
    ) -> None:
        """委托 loguru 统一处理（自动触发所有 sink）。"""
        bound_logger = get_logger(name, source)
        level_name = str(level or "INFO").upper()
        log_func = getattr(bound_logger, level_name.lower(), bound_logger.info)
        log_func("{}", message)

        # 监控相关日志 → 更新状态快照（业务逻辑，不属于日志管道）
        if source in ("network",):
            self._update_status_snapshot()

    def _update_status_snapshot(self) -> None:
        """Read monitor_core state into lock-free StatusSnapshot."""
        now = time.time()
        if now - self._last_snapshot_time < self._SNAPSHOT_MIN_INTERVAL:
            return
        self._last_snapshot_time = now

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
                engine_logger.exception("状态快照更新失败")
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
            engine_logger.exception("状态广播队列失败")

    # ── WebSocket 排空（主事件循环）──

    async def ws_drain_loop(self) -> None:
        """后台 asyncio 任务：定期排空 WS 广播队列。

        Runs until the asyncio task is cancelled (by lifespan shutdown).
        """
        import asyncio

        while True:
            try:
                await asyncio.sleep(WS_DRAIN_INTERVAL_SECONDS)
                await self.drain_ws_queue()
            except asyncio.CancelledError:
                break
            except Exception:
                engine_logger.exception("WS 排空循环异常")

    async def drain_ws_queue(self) -> None:
        """Flush pending WS broadcast messages to WebSocket clients."""
        broadcast_queue = self.ws_broadcast_queue
        while True:
            try:
                data = broadcast_queue.popleft()
            except IndexError:
                break
            try:
                if self._ws_manager:
                    import json as _json

                    await self._ws_manager.broadcast(_json.dumps(data))
            except Exception:
                engine_logger.exception("WS 广播发送失败")

    # ── 公共 API（监控 — 从 API 线程 / main.py 调用）──

    def boot(self) -> None:
        # --no-auto 启动标志：跳过 login_then_exit 和 auto_start，用于恢复设置
        if os.environ.pop("CAMPUS_AUTH_NO_AUTO", None):
            engine_logger.info("--no-auto 模式：跳过自动启动监控")
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
        if core is not None:
            core._login_recovery_in_progress.wait(timeout=timeout)

    @property
    def ws_broadcast_queue(self) -> deque:
        """WS 广播队列（从 DashboardSink 获取）。"""
        if self._dashboard_sink is None:
            return self._empty_broadcast_queue
        return self._dashboard_sink.broadcast_queue

    @property
    def pure_mode(self) -> bool:
        """线程安全地读取纯净模式标志。"""
        with self._pure_mode_lock:
            return self._pure_mode

    @property
    def _is_monitoring(self) -> bool:
        return self._monitor_core is not None and self._monitor_core.monitoring

    def get_config(self) -> MonitorConfigPayload:
        with self._reload_lock:
            return self._ui_config.model_copy(deep=True)

    def _reload_config_internal(self) -> None:
        """从 settings.json 重新加载 UI 和运行时配置。"""
        with self._reload_lock:
            # 单次 load，避免多次 load 之间数据版本不一致
            data = self._profile_service.load()
            self._ui_config = load_ui_config(self._profile_service, data=data)
            runtime_payload, has_decrypt_error = load_runtime_config(
                self._profile_service, data=data
            )
            if has_decrypt_error:
                engine_logger.warning("配置重载时部分密码解密失败")
            self._runtime_config = build_runtime_config(
                runtime_payload,
                data.system,
            )
            self._runtime_snapshot = copy.deepcopy(self._runtime_config)

    def _copy_runtime_config(self) -> dict:
        """返回运行时配置快照（仅在 reload 时更新，读取零拷贝）。"""
        snapshot = getattr(self, "_runtime_snapshot", None)
        if snapshot is not None:
            return snapshot
        # 回退：__new__ 构造（测试场景）未初始化快照，走旧的深拷贝路径
        return copy.deepcopy(self._runtime_config)

    def reload_config(self) -> None:
        """重新加载配置并重启监控（如果正在运行）。

        通过队列派发到引擎线程执行，确保线程安全。
        """
        cmd = EngineCommand(
            type=EngineCmdType.RELOAD,
            response_event=threading.Event(),
        )
        if not self._enqueue(cmd):
            engine_logger.warning("配置重载失败：队列已满")
            return
        # 等待消费者完成（最多 30 秒，避免无限阻塞 API 线程）
        if not cmd.response_event.wait(timeout=30):
            engine_logger.warning("配置重载超时（30s），引擎线程可能繁忙")

    def apply_profile(self, profile_id: str) -> None:
        """切换到新方案：停止监控 → 重载配置 → 重启监控。

        通过队列派发到引擎线程执行，确保线程安全。
        """
        cmd = EngineCommand(
            type=EngineCmdType.APPLY_PROFILE,
            data={"profile_id": profile_id},
            response_event=threading.Event(),
        )
        if not self._enqueue(cmd):
            engine_logger.warning("方案切换失败：队列已满")
            return
        # 等待消费者完成（最多 30 秒）
        if not cmd.response_event.wait(timeout=30):
            engine_logger.warning("方案切换超时（30s），引擎线程可能繁忙")

    def start_monitoring(self) -> tuple[bool, str]:
        engine_logger.debug("收到启动监控请求")
        with self._start_stop_lock:
            if self._is_monitoring:
                return False, "监控已在运行中"

            valid, error = ConfigValidator.validate_env_config(self._runtime_config)
            if not valid:
                return False, f"配置无效: {error}"

            if not self._enqueue(EngineCommand(type=EngineCmdType.START)):
                return False, "队列已满"

            return True, "监控已启动"

    def stop_monitoring(self) -> tuple[bool, str]:
        engine_logger.debug("收到停止监控请求")
        with self._start_stop_lock:
            if not self._is_monitoring:
                return False, "监控未运行"

            if not self._enqueue(EngineCommand(type=EngineCmdType.STOP)):
                return False, "队列已满"
            return True, "监控已停止"

    def shutdown(self) -> None:
        """完全关闭 ScheduleEngine：停止监控 + 停止调度器 + 终止引擎线程。"""
        if self._shutdown_event.is_set():
            return
        # 停止调度器并等待运行中的任务线程完成
        self.stop_scheduler()

        # 直接停止监控核心（不等待 response，避免阻塞）
        if self._monitor_core is not None:
            with contextlib.suppress(Exception):
                self._monitor_core.stop_monitoring()
        self._monitor_core = None

        # 设置关闭事件，通知引擎线程退出循环
        self._shutdown_event.set()

        # 发送 shutdown 命令确保引擎能立即处理退出
        with contextlib.suppress(queue.Full):
            self._cmd_queue.put_nowait(EngineCommand(type=EngineCmdType.SHUTDOWN))

        # 短超时等待，不阻塞（守护线程会随进程退出）
        if self._engine_thread and self._engine_thread.is_alive():
            self._engine_thread.join(timeout=1)

        engine_logger.info("引擎服务已关闭")

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
            engine_logger.debug("收到手动登录请求")

            cmd = EngineCommand(
                type=EngineCmdType.LOGIN,
                data={"skip_pause_check": True},
                response_event=threading.Event(),
            )
            if not self._enqueue(cmd):
                self._login_in_progress.clear()
                return False, "队列已满"
            cmd_in_queue = True
        except Exception:
            if not cmd_in_queue:
                self._login_in_progress.clear()
            raise

        # Wait for consumer to execute login (with timeout)
        login_timeout = getattr(self._ui_config, "login_timeout", 120)
        cmd.response_event.wait(timeout=login_timeout)

        if cmd.response_data is None:
            # 超时：检查引擎线程是否存活
            # 如果引擎线程已死，主动清除标志位（防止永久卡住）
            if not self._engine_thread.is_alive():
                engine_logger.error("引擎线程已退出，主动清除 _login_in_progress")
                self._login_in_progress.clear()
            return False, "手动登录超时"

        success, message = cmd.response_data
        if success:
            # network_state 已由消费者 _handle_login 统一赋值，无需 API 线程操作
            self._update_status_snapshot()
            engine_logger.info("手动登录成功")
            return True, f"手动登录成功：{message}"

        log_msg = re.sub(SCREENSHOT_URL_PATTERN, "", message)
        engine_logger.warning("手动登录失败: {}", log_msg)
        return False, f"手动登录失败：{message}"

    def test_network(self) -> tuple[bool, str]:
        engine_logger.debug("手动网络测试")
        config = self._copy_runtime_config()
        monitor_cfg = config.get("monitor", {})
        targets = monitor_cfg.get("ping_targets", [])
        enable_tcp = monitor_cfg.get("enable_tcp_check", True)
        enable_http = monitor_cfg.get("enable_http_check", True)
        url_checks = monitor_cfg.get("url_check_urls", None)
        # 解析 host:port 为 (host, port) 元组列表
        test_sites = parse_host_port(targets)
        mode_desc = []
        if enable_tcp:
            mode_desc.append("TCP")
        if enable_http:
            mode_desc.append("HTTP")
        if url_checks:
            mode_desc.append("网址响应")
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
                url_checks=url_checks if url_checks else None,
            )
            if ok:
                self.record_log("手动测试结果: 网络正常", "INFO", "network")
                return True, "网络连接正常"
            else:
                self.record_log("手动测试结果: 网络异常", "WARNING", "network")
                return False, "网络连接异常"
        except Exception as exc:
            engine_logger.exception("网络测试失败")
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

    # ── 公共 API（定时任务调度器）──

    @staticmethod
    def _validate_task_id(task_id: str) -> bool:
        """校验 task_id 是否安全且格式有效。"""
        return is_valid_task_id(task_id)

    def has_enabled_tasks(self) -> bool:
        """检查是否存在启用的定时任务。"""
        now = time.time()
        if self._has_enabled_cache is not None and (now - self._has_enabled_cache[0]) < 5:
            return self._has_enabled_cache[1]
        for file in self._scheduler_tasks_dir.glob("*.json"):
            if file.name.startswith("."):
                continue
            try:
                data = json.loads(file.read_text(encoding="utf-8"))
                if data.get("enabled", False):
                    self._has_enabled_cache = (now, True)
                    return True
            except Exception:
                continue
        self._has_enabled_cache = (now, False)
        return False

    def list_tasks(self) -> list[dict[str, Any]]:
        """列出所有定时任务。"""
        tasks = []
        for file in self._scheduler_tasks_dir.glob("*.json"):
            if file.name.startswith("."):
                continue
            try:
                data = json.loads(file.read_text(encoding="utf-8"))
                data["id"] = file.stem
                tasks.append(data)
            except Exception as e:
                engine_logger.error("读取定时任务失败 {}: {}", file, e)
        return sorted(tasks, key=lambda t: t.get("name", ""))

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        """获取定时任务详情。"""
        if not self._validate_task_id(task_id):
            return None
        file = self._scheduler_tasks_dir / f"{task_id}.json"
        if not file.exists():
            return None
        try:
            data = json.loads(file.read_text(encoding="utf-8"))
            data["id"] = task_id
            return data
        except Exception as e:
            engine_logger.error("读取定时任务失败 {}: {}", file, e)
            return None

    def save_task(self, task_id: str, config: dict[str, Any]) -> tuple[bool, str]:
        """保存定时任务。"""
        if not self._validate_task_id(task_id):
            return False, "无效的任务 ID"
        file = self._scheduler_tasks_dir / f"{task_id}.json"
        try:
            atomic_write(str(file), json.dumps(config, ensure_ascii=False, indent=2))
            self._has_enabled_cache = None  # 清除缓存，确保调度器感知变更
            engine_logger.info("定时任务已保存: {}", task_id)
            return True, "定时任务保存成功"
        except Exception as e:
            engine_logger.error("保存定时任务失败 {}: {}", task_id, e)
            return False, f"定时任务保存失败，请检查配置后重试: {e}"

    def delete_task(self, task_id: str) -> tuple[bool, str]:
        """删除定时任务。"""
        if not self._validate_task_id(task_id):
            return False, "无效的任务 ID"
        file = self._scheduler_tasks_dir / f"{task_id}.json"
        if not file.exists():
            return False, "定时任务不存在"
        try:
            file.unlink()
            self._has_enabled_cache = None  # 清除缓存，确保调度器感知变更
            # 同时删除历史记录
            history_file = self._scheduler_history_dir / f"{task_id}.json"
            if history_file.exists():
                history_file.unlink()
            engine_logger.info("定时任务已删除: {}", task_id)
            return True, "定时任务删除成功"
        except Exception as e:
            engine_logger.error("删除定时任务失败 {}: {}", task_id, e)
            return False, f"定时任务删除失败，请稍后重试: {e}"

    def get_history(self, task_id: str) -> list[dict[str, Any]]:
        """获取任务执行历史。"""
        if not self._validate_task_id(task_id):
            return []
        history_file = self._scheduler_history_dir / f"{task_id}.json"
        if not history_file.exists():
            return []
        try:
            data = json.loads(history_file.read_text(encoding="utf-8"))
            return data.get("runs", [])
        except Exception as e:
            engine_logger.error("读取执行历史失败 {}: {}", task_id, e)
            return []

    def _add_history_sync(
        self, task_id: str, status: str, message: str, duration: float
    ) -> None:
        """添加执行历史记录（同步，使用 threading.Lock 保护并发写入）。"""
        if not self._validate_task_id(task_id):
            return
        with self._history_lock:
            history_file = self._scheduler_history_dir / f"{task_id}.json"
            try:
                if history_file.exists():
                    data = json.loads(history_file.read_text(encoding="utf-8"))
                else:
                    data = {"runs": []}

                data["runs"].insert(
                    0,
                    {
                        "timestamp": datetime.now().isoformat(),
                        "status": status,
                        "message": message[:500],
                        "duration": round(duration, 2),
                    },
                )

                # 保留最近 N 条
                data["runs"] = data["runs"][:MAX_HISTORY_SIZE]

                atomic_write(
                    str(history_file),
                    json.dumps(data, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            except Exception as e:
                engine_logger.error("保存执行历史失败 {}: {}", task_id, e)

    def execute_task(self, task_id: str) -> tuple[bool, str]:
        """执行定时任务。"""
        task = self.get_task(task_id)
        if not task:
            return False, "定时任务不存在"

        task_type = task.get("type", "")
        timeout = task.get("timeout", 60)
        start = time.perf_counter()

        try:
            if task_type == "script":
                success, message = self._execute_script_sync(
                    task.get("target_id", ""), timeout
                )
            elif task_type == "browser":
                success, message = self._execute_browser_sync(
                    task.get("target_id", ""), timeout
                )
            elif task_type == "shell":
                success, message = self._execute_shell_sync(
                    task.get("command", ""), timeout, task.get("shell_path", "")
                )
            else:
                success, message = False, f"不支持的任务类型: {task_type}，当前支持: script、browser、shell"
        except Exception as e:
            success, message = False, f"执行异常: {e}"

        duration = time.perf_counter() - start
        self._add_history_sync(
            task_id, "success" if success else "failure", message, duration
        )

        # 更新最后执行时间（重新读取配置，避免覆盖用户在执行期间的修改）
        fresh_task = self.get_task(task_id)
        if fresh_task is not None:
            fresh_task["last_run"] = datetime.now().isoformat()
            fresh_task["last_status"] = "success" if success else "failure"
            self.save_task(task_id, fresh_task)

        engine_logger.info(
            "定时任务执行完成 {}: success={}, message={}",
            task_id,
            success,
            message[:100],
        )
        return success, message

    def _execute_script_sync(self, script_id: str, timeout: int) -> tuple[bool, str]:
        """执行自定义脚本任务。"""
        if not self._task_manager:
            return False, "任务服务未初始化"

        task = self._task_manager.get_task(script_id)
        if not task or task.get("type") != "script":
            return False, f"脚本任务不存在: {script_id}"

        script_path = self._task_manager.get_script_path(script_id)
        if not script_path or not script_path.exists():
            return False, f"脚本文件不存在: {script_id}"

        from app.workers.script_runner import ScriptRunner

        runner = ScriptRunner(
            script_path,
            timeout=timeout,
            binary_path=task.get("binary_path", ""),
        )

        return runner.run()

    def _execute_browser_sync(self, task_id: str, timeout: int) -> tuple[bool, str]:
        """执行浏览器任务。

        通过 PlaywrightWorker 执行浏览器自动化任务。
        使用 _login_lock 与监控登录互斥。
        """
        if not self._task_manager:
            return False, "任务服务未初始化"

        task = self._task_manager.get_task(task_id)
        if not task or task.get("type") != "browser":
            return False, f"浏览器任务不存在: {task_id}"

        # 等待监控登录恢复完成，避免重复执行
        if (
            self.login_in_progress
            or self.login_recovery_in_progress
        ):
            engine_logger.info("监控正在登录，等待完成后再执行定时任务")
            self.wait_for_login_recovery()

        start_time = time.perf_counter()
        try:
            from app.workers.playwright_worker import CMD_LOGIN, get_worker

            # 获取登录锁，防止与监控核心的登录流程并发
            acquired = False
            with self._login_lock:
                if self._login_in_progress.is_set():
                    engine_logger.info("获取登录锁时发现登录正在进行，跳过本次执行")
                    return False, "登录操作正在进行中，定时任务跳过"
                self._login_in_progress.set()
                acquired = True

            try:
                # 获取运行时配置
                config = self.get_runtime_config()
                pure_mode = config.get("browser_settings", {}).get("pure_mode", False)

                # 获取 Worker 并提交登录命令
                worker = get_worker()
                result = worker.submit(
                    CMD_LOGIN,
                    data={
                        "config": config,
                        "pure_mode": pure_mode,
                        "skip_pause_check": True,  # 定时任务跳过暂停检查
                    },
                    wait=True,
                    timeout=timeout,
                )
            finally:
                if acquired:
                    self._login_in_progress.clear()

            duration_ms = int((time.perf_counter() - start_time) * 1000)
            if result.success:
                self._record_login_history(True, duration_ms)
                return True, result.data if isinstance(
                    result.data, str
                ) else "浏览器任务执行成功"
            else:
                error_msg = result.error or "浏览器任务执行失败"
                self._record_login_history(False, duration_ms, error=error_msg)
                return False, error_msg

        except ImportError as e:
            duration_ms = int((time.perf_counter() - start_time) * 1000)
            engine_logger.warning("浏览器任务执行缺少依赖: {}", e)
            self._record_login_history(False, duration_ms, error=str(e))
            return False, "浏览器任务执行需要额外依赖，请在设置中检查 Playwright 安装状态"
        except Exception as e:
            duration_ms = int((time.perf_counter() - start_time) * 1000)
            engine_logger.error("浏览器任务执行异常: {}", e)
            self._record_login_history(False, duration_ms, error=str(e))
            return False, f"浏览器任务执行异常: {e}"

    def _record_login_history(
        self, success: bool, duration_ms: int, error: str = ""
    ) -> None:
        """记录登录历史（委托 LoginHistoryService.record 自动提取方案/任务名称）。"""
        if self._login_history is None:
            return
        try:
            self._login_history.record(
                success=success,
                duration_ms=duration_ms,
                profile_service=self._profile_service,
                task_manager=self._task_manager,
                error=error,
            )
        except Exception:
            engine_logger.debug("记录登录历史失败", exc_info=True)

    def _execute_shell_sync(
        self, command: str, timeout: int, shell_path: str = ""
    ) -> tuple[bool, str]:
        """执行 Shell 命令。"""
        if not command.strip():
            return False, "命令为空"

        # 如果没有指定 shell，使用全局配置或默认值
        if not shell_path:
            try:
                config = self.get_runtime_config()
                shell_path = config.get("shell_path", "")
            except Exception:
                engine_logger.debug("获取运行时 shell_path 失败，使用默认值", exc_info=True)

        if not shell_path:
            shell_path = get_default_shell()

        # 使用缓存的 ShellCommandPolicy 进行安全校验和执行
        policy = self._shell_policy

        try:
            # 根据 shell 类型构建命令
            shell_lower = shell_path.lower()
            if "powershell" in shell_lower or "pwsh" in shell_lower:
                cmd_args = [shell_path, "-Command", command]
            elif sys.platform == "win32" and "cmd" in shell_lower:
                cmd_args = [shell_path, "/c", command]
            else:
                # bash / zsh / fish / git-bash 等 POSIX shell
                cmd_args = [shell_path, "-c", command]

            returncode, stdout_str, stderr_str = policy.run_sync(
                cmd_args,
                timeout=timeout,
            )

            if returncode == 0:
                output = stdout_str[:500] or "(无输出)"
                return True, output
            else:
                output = stderr_str[:500] or stdout_str[:500] or f"退出码: {returncode}"
                return False, output

        except PermissionError as e:
            return False, str(e)
        except Exception as e:
            return False, f"执行异常: {e}"

    # ── 调度器生命周期 ──

    def start_scheduler(self) -> None:
        """启动定时任务调度（由引擎循环驱动）。"""
        if self._scheduler_running:
            return
        self._scheduler_running = True
        self._last_triggered_minute = None
        engine_logger.info("定时任务调度器已启动（引擎驱动）")

    def stop_scheduler(self) -> None:
        """停止调度器，等待运行中的任务线程完成。"""
        if not self._scheduler_running:
            return
        self._scheduler_running = False

        # 等待所有运行中的任务线程
        with self._running_tasks_lock:
            running = list(self._running_task_threads)
        for t in running:
            t.join(timeout=30)
        with self._running_tasks_lock:
            self._running_task_threads.clear()

        engine_logger.info("定时任务调度器已停止")

    def _execute_task_wrapper(self, task_id: str) -> None:
        """任务执行包装器（在守护线程中运行），负责清理线程引用。"""
        try:
            self.execute_task(task_id)
        except Exception as e:
            engine_logger.error("定时任务执行异常: {}", e)
        finally:
            with self._running_tasks_lock:
                if threading.current_thread() in self._running_task_threads:
                    self._running_task_threads.remove(threading.current_thread())
