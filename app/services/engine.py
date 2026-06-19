"""ScheduleEngine — 统一的后台服务引擎。

合并 MonitorService（网络监控）和 SchedulerService（定时任务调度）的全部功能，
使用 Actor 模型（线程 + 队列）进行命令派发，零 asyncio 依赖的核心逻辑。

NOT-TO-DO: 不要拆分此文件。ScheduleEngine 是调度核心，职责清晰（命令队列、
监控循环、重试逻辑、调度器），拆分只会增加模块间耦合。
"""

from __future__ import annotations

import contextlib
from concurrent.futures import Future
import json
import queue
import re
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from app.network.decision import is_network_available
from app.schemas import MonitorConfigPayload, MonitorStatusResponse
from app.services.monitor_service import NetworkMonitorCore
from app.services.websocket_manager import WebSocketManager
from app.utils import ConfigValidator
from app.utils.logging import get_logger
from app.utils.login import SCREENSHOT_URL_PATTERN
from app.utils.network import parse_ping_targets

from .profile_service import ProfileService

# ── 常量 ──

# WS 广播队列排空间隔（秒）
WS_DRAIN_INTERVAL_SECONDS = 0.05

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


logger = get_logger("engine", source="backend")


@dataclass
class _LoginRetryState:
    """登录重试状态。"""

    count: int = 0
    last_attempt: float = 0.0
    config: tuple[int, list[int]] | None = None  # (max_retries, intervals)


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
        task_registry=None,
        task_executor=None,
    ):
        self.project_root = project_root
        self._profile_service = profile_service or ProfileService(project_root)
        self._ws_manager = ws_manager
        self._login_history = login_history_service
        self._worker_getter = worker_getter

        # 新组件注入
        self._task_registry = task_registry
        self._task_executor = task_executor

        # 调度状态（从 ScheduledTaskService 搬入）
        self._scheduler_running = False
        self._next_schedule_tick = 0.0

        # DashboardSink — 由 container.startup 注入
        self._dashboard_sink = None
        # 轻量模式下的空广播队列（仅接收不消费，小容量即可）
        self._empty_broadcast_queue: deque = deque(maxlen=10)

        # 锁（必须在 _reload_config_internal 之前初始化）
        self._manual_login_in_progress = False
        self._manual_login_lock: threading.Lock = threading.Lock()
        self._reload_lock: threading.Lock = threading.Lock()
        self._pure_mode_lock: threading.Lock = threading.Lock()
        self._start_stop_lock: threading.Lock = threading.Lock()

        # 运行时配置快照（仅在 reload 时深拷贝，读取零拷贝）
        self._runtime_snapshot: dict = {}
        # 配置对象（由 _reload_config_internal 初始化）
        self._ui_config: MonitorConfigPayload = MonitorConfigPayload()
        self._runtime_config: dict = {}

        # 状态快照限流
        self._last_snapshot_time: float = 0
        self._snapshot_min_interval: float = 1.0

        # 加载配置（复用 _reload_config_internal）
        self._reload_config_internal()

        self._monitor_core: NetworkMonitorCore | None = None

        # Actor model: command dispatch queue
        self._cmd_queue: queue.Queue[EngineCommand] = queue.Queue(maxsize=50)
        self._shutdown_event = threading.Event()

        # Lock-free status snapshot — written by consumer, read by API threads
        self._status_snapshot = StatusSnapshot()

        # 登录并发控制 —— 委托 task_executor.is_login_running()

        # ── 统一引擎状态 ──
        self._engine_running = False
        self._next_network_check: float = 0
        self._monitor_check_interval: int = 300
        self._login_retry = _LoginRetryState()

        # 统一引擎线程
        self._engine_thread = threading.Thread(target=self._engine_loop, daemon=True)
        self._engine_thread.start()

    # ── 队列入队辅助 ──

    def _enqueue(self, cmd: EngineCommand) -> bool:
        """尝试将命令入队。返回 True 表示成功。"""
        try:
            self._cmd_queue.put_nowait(cmd)
            return True
        except queue.Full:
            logger.warning("命令队列已满 (type={})，操作被跳过", cmd.type)
            return False

    # ── 统一引擎循环 ──

    def _engine_loop(self) -> None:
        """统一引擎循环：命令处理 + 网络检测 + 定时任务调度。"""
        self._engine_running = True
        logger.info("引擎循环已启动")

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

                # 登录重试：前次 check_once 已判定 need_login，跳过 attempt_login 内冗余检测
                if self._login_retry_needed(now):
                    self._do_async_login()

                # 定时任务
                if self._scheduler_running and now >= self._next_schedule_tick:
                    self._run_schedule_tick()
            except Exception:
                logger.exception("引擎循环异常，继续运行")
                time.sleep(1)

        self._engine_running = False
        logger.info("引擎循环已退出")

    def _calculate_wakeup(self) -> float:
        """计算下次唤醒时间。"""
        now = time.time()
        candidates: list[float] = [now + 60]

        try:
            if self._is_monitoring:
                candidates.append(float(self._next_network_check))

            if self._login_retry.count > 0 and self._login_retry.config:
                _, intervals = self._login_retry.config
                idx = self._login_retry.count - 1
                if idx < len(intervals):
                    candidates.append(
                        float(self._login_retry.last_attempt + intervals[idx])
                    )

            if self._scheduler_running:
                candidates.append(self._next_schedule_tick)
        except (TypeError, ValueError, AttributeError):
            # 异常时回退到默认唤醒时间
            return now + 5

        return min(candidates)

    def _process_command(self, cmd: EngineCommand) -> None:
        """处理一个命令。"""
        try:
            if cmd.type == EngineCmdType.START:
                self._handle_start(cmd)
            elif cmd.type == EngineCmdType.STOP:
                self._handle_stop(cmd)
            elif cmd.type == EngineCmdType.LOGIN:
                self._handle_login(cmd)
            elif cmd.type == EngineCmdType.SHUTDOWN:
                self._handle_shutdown(cmd)
            elif cmd.type == EngineCmdType.RELOAD:
                self._handle_reload(cmd)
            elif cmd.type == EngineCmdType.APPLY_PROFILE:
                self._handle_apply_profile(cmd)
        except Exception:
            logger.exception("命令执行失败: {}", cmd.type)
        finally:
            if cmd.response_event:
                cmd.response_event.set()
            self._cmd_queue.task_done()

    def _do_network_check(self) -> None:
        """执行一次网络检测。"""
        core = self._monitor_core
        if core is None:
            return

        try:
            result = core.check_once()
            interval = int(result.get("interval", self._monitor_check_interval))
            self._monitor_check_interval = interval

            if result.get("need_login", False):
                self._login_retry.config = self._get_retry_config()
                self._login_retry.count = 0
                # check_once 已完成暂停/网络检测，跳过 attempt_login 内冗余二次检测
                self._do_async_login()
            else:
                self._login_retry.count = 0

            # 检查是否需要重启（自动切换方案）
            if core.consume_profile_switch_flag():
                logger.info("检测到方案切换，准备重启监控")
                # 先 reload，成功后再 stop → start（失败则旧 core 继续运行）
                if self._reload_config_internal():
                    self._handle_stop()
                    self._handle_start(EngineCommand(type=EngineCmdType.START))
                else:
                    logger.error("配置重载失败，继续使用当前配置")

            self._next_network_check = time.time() + interval
            self._update_status_snapshot(force=True)
        except Exception:
            logger.exception("网络检测异常")
            self._next_network_check = time.time() + self._monitor_check_interval

    def _login_retry_needed(self, now: float) -> bool:
        """检查是否需要登录重试。"""
        if self._login_retry.count == 0 or not self._login_retry.config:
            return False
        if self._task_executor.is_login_running():
            return False
        max_retries, intervals = self._login_retry.config
        if self._login_retry.count >= max_retries:
            return False
        idx = self._login_retry.count - 1
        if idx >= len(intervals):
            return False
        return now >= self._login_retry.last_attempt + intervals[idx]

    def _do_async_login(self, is_manual: bool = False, config_snapshot: dict | None = None) -> bool:
        """提交登录到 executor 的 login_pool。返回 True 表示已提交。"""
        if self._task_executor.is_login_running():
            if not is_manual:
                return False
            # 手动登录：取消卡住的自动登录，等待完成后重新提交
            logger.info("手动登录：取消当前登录任务")
            self._task_executor.cancel_login()
            deadline = time.time() + 5
            while self._task_executor.is_login_running() and time.time() < deadline:
                time.sleep(0.1)
            if self._task_executor.is_login_running():
                logger.warning("取消当前登录超时，将尝试提交新登录")
        self._login_retry.last_attempt = time.time()
        if not is_manual:
            self._login_retry.count += 1

        try:
            future = self._task_executor.execute_login_async(
                config_snapshot=config_snapshot,
            )
        except Exception:
            self._update_status_snapshot()
            raise
        if future is not None:

            def _on_done(f: Future) -> None:
                self._update_status_snapshot()
                try:
                    ok, msg = f.result()
                    tag = "手动登录" if is_manual else "自动登录"
                    if ok:
                        logger.info("{}完成: {}", tag, msg)
                    else:
                        logger.warning("{}失败: {}", tag, msg)
                except Exception:
                    logger.exception("登录任务异常")

            future.add_done_callback(_on_done)
            return True
        else:
            self._update_status_snapshot()
            return False

    def _get_retry_config(self) -> tuple[int, list[int]]:
        """获取登录重试配置。"""
        try:
            config = self._copy_runtime_config()
            retry = config.get("retry_settings", {})
            max_retries = retry.get("max_retries", 3)
            interval = retry.get("retry_interval", 5)
            # 延迟导入：测试中需要 mock 此函数，顶层导入会导致 mock 路径变化
            from app.utils.retry import get_retry_intervals

            intervals = get_retry_intervals(interval, max_retries, exponential=False)
            return max_retries, intervals
        except Exception:
            return 3, [5, 5, 5]

    def _run_schedule_tick(self) -> None:
        """执行定时任务调度（使用 TaskRegistry + TaskExecutor）。"""
        from datetime import datetime

        now = datetime.now()
        registry = getattr(self, "_task_registry", None)
        executor = getattr(self, "_task_executor", None)
        if registry and executor:
            due_tasks = registry.get_due_tasks(now.hour, now.minute)
            for task_id in due_tasks:
                executor.execute_task_async(task_id)
        # 计算下一个整分钟
        self._next_schedule_tick = (int(time.time() // 60) * 60) + 60

    def _handle_start(self, cmd: EngineCommand) -> None:
        """启动监控（在引擎循环中调用）。"""
        if self._monitor_core is not None and self._monitor_core.monitoring:
            self.record_log(
                "监控已在运行中",
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
        self._login_retry.count = 0
        self._update_status_snapshot(force=True)
        self.record_log("监控已启动", level="INFO", source="backend")

    def _handle_stop(self, cmd: EngineCommand | None = None) -> None:
        """停止监控。"""
        core = self._monitor_core
        if core is None:
            return

        core.stop_monitoring()
        self._monitor_core = None
        self._login_retry.count = 0
        self._next_network_check = 0

        self.record_log("监控已停止", level="INFO", source="backend")
        self._update_status_snapshot(force=True)

    def _handle_shutdown(self, cmd: EngineCommand) -> None:
        """处理关闭命令。"""
        self._handle_stop()

    def _handle_login(self, cmd: EngineCommand) -> None:
        """执行一次性登录（手动触发，异步执行）。"""
        config = self._copy_runtime_config()
        if not config.get("username") or not config.get("password") or not config.get("auth_url"):
            cmd.response_data = (False, "登录配置不完整（请先设置认证地址、用户名和密码）")
            return
        if self._do_async_login(is_manual=True, config_snapshot=config):
            cmd.response_data = (True, "登录已提交")
        else:
            cmd.response_data = (False, "登录任务已在执行中，请稍后再试")

    def _handle_reload(self, cmd: EngineCommand) -> None:
        """重载配置并重启监控（仅在引擎线程中调用）。"""
        was_monitoring = self._is_monitoring

        # 先加载新配置（不修改当前运行状态）
        if not self._reload_config_internal():
            logger.error("配置重载失败，监控继续使用旧配置运行")
            cmd.response_data = (False, "配置重载失败")
            return

        # 仅当重载成功且之前处于监控状态时，才执行 stop/start
        if was_monitoring:
            self._handle_stop()
            self._handle_start(EngineCommand(type=EngineCmdType.START))
        logger.info("配置已重载")
        cmd.response_data = (True, "配置重载成功")

    def _handle_apply_profile(self, cmd: EngineCommand) -> None:
        """切换方案并重启监控（仅在引擎线程中调用）。"""
        profile_id = cmd.data.get("profile_id", "")
        was_monitoring = self._is_monitoring

        # 先加载新配置（不修改当前运行状态）
        if not self._reload_config_internal():
            logger.error("配置重载失败，监控继续使用旧方案运行")
            cmd.response_data = (False, "方案切换失败")
            return

        # 直接用 profile_id 记录日志，避免重复 load
        new_url = self._runtime_config.get("auth_url", "")
        new_user = self._runtime_config.get("username", "")
        self.record_log(f"切换方案: {profile_id}", level="INFO", source="backend")
        logger.debug("方案详情: 认证={}, 用户={}", new_url, new_user)

        if was_monitoring:
            self._handle_stop()
            self._handle_start(EngineCommand(type=EngineCmdType.START))
            self.record_log(
                "监控正在按新方案重启",
                level="INFO",
                source="backend",
            )
        cmd.response_data = (True, "方案切换成功")

    # ── 日志 / 状态快照桥接 ──

    def record_log(
        self,
        message: str,
        level: str = "INFO",
        source: str = "backend",
        name: str = "engine",
    ) -> None:
        """委托 loguru 统一处理（自动触发所有 sink）。"""
        bound_logger = get_logger(name, source)
        level_name = str(level or "INFO").upper()
        log_func = getattr(bound_logger, level_name.lower(), bound_logger.info)
        log_func("{}", message)

    def notify_network_state_changed(self) -> None:
        """网络状态变化时显式调用，更新状态快照。"""
        self._update_status_snapshot()

    def _update_status_snapshot(self, force: bool = False) -> None:
        """Read monitor_core state into lock-free StatusSnapshot.

        Args:
            force: 跳过节流，立即更新（用于状态切换等关键场景）。
        """
        now = time.time()
        if not force and now - self._last_snapshot_time < self._snapshot_min_interval:
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
                logger.exception("状态快照更新失败")
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
            logger.exception("状态广播队列失败")

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
                logger.exception("WS 排空循环异常")

    async def drain_ws_queue(self) -> None:
        """Flush pending WS broadcast messages to WebSocket clients."""
        if self._ws_manager is None:
            return
        broadcast_queue = self.ws_broadcast_queue
        while True:
            try:
                data = broadcast_queue.popleft()
            except IndexError:
                break
            try:
                await self._ws_manager.broadcast(json.dumps(data))
            except Exception:
                logger.exception("WS 广播发送失败")

    # ── 公共 API（监控 — 从 API 线程 / main.py 调用）──

    def boot(self) -> None:
        """启动引擎。由调用方决定是否调用，不再自行判断配置。"""
        self.start_monitoring()

    @property
    def login_in_progress(self) -> bool:
        return self._task_executor.is_login_running()

    def set_dashboard_sink(self, sink) -> None:
        """注入 DashboardSink 实例（由 container.start_web_services 调用）。"""
        self._dashboard_sink = sink

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
        core = self._monitor_core
        return core is not None and core.monitoring

    @property
    def tasks(self):
        """定时任务接口（供 API 路由使用）。"""
        return self._task_executor

    def get_config(self) -> MonitorConfigPayload:
        return self._ui_config.model_copy(deep=True)

    def _reload_config_internal(self) -> bool:
        """从 settings.json 重新加载 UI 和运行时配置。返回 True 表示成功。"""
        import copy

        # 延迟导入：测试中需要 mock 这些函数的返回值，顶层导入会导致 mock 路径变化
        from .config_service import build_runtime_dict_from_payload
        from .runtime_config import load_runtime_config, load_ui_config

        try:
            with self._reload_lock:
                data = self._profile_service.load()
                self._ui_config = load_ui_config(self._profile_service, data=data)
                runtime_payload, has_decrypt_error = load_runtime_config(
                    self._profile_service, data=data
                )
                if has_decrypt_error:
                    logger.warning("配置重载时部分密码解密失败")
                self._runtime_config = build_runtime_dict_from_payload(
                    runtime_payload,
                    global_settings=data.global_settings,
                )
                self._runtime_snapshot = copy.deepcopy(self._runtime_config)
                with self._pure_mode_lock:
                    self._pure_mode = data.global_settings.pure_mode
            return True
        except Exception:
            logger.exception("配置重载失败")
            with self._pure_mode_lock:
                self._pure_mode = False
            return False

    def _copy_runtime_config(self) -> dict:
        """返回运行时配置快照（仅在 reload 时更新，读取零拷贝）。"""
        import copy

        return copy.deepcopy(self._runtime_config)

    def reload_config(self) -> tuple[bool, str]:
        """重新加载配置并重启监控（如果正在运行）。

        通过队列派发到引擎线程执行，确保线程安全。
        """
        cmd = EngineCommand(
            type=EngineCmdType.RELOAD,
            response_event=threading.Event(),
        )
        if not self._enqueue(cmd):
            return False, "配置重载失败：队列已满"
        # 等待消费者完成（最多 10 秒，避免无限阻塞 API 线程）
        if not cmd.response_event.wait(timeout=10):
            return False, "配置重载超时，将在引擎空闲后生效"
        if cmd.response_data:
            return cmd.response_data
        return False, "配置重载未返回结果"

    def apply_profile(self, profile_id: str) -> tuple[bool, str]:
        """切换到新方案：停止监控 → 重载配置 → 重启监控。

        通过队列派发到引擎线程执行，确保线程安全。
        """
        cmd = EngineCommand(
            type=EngineCmdType.APPLY_PROFILE,
            data={"profile_id": profile_id},
            response_event=threading.Event(),
        )
        if not self._enqueue(cmd):
            return False, "方案切换失败：队列已满"
        # 等待消费者完成（最多 10 秒）
        if not cmd.response_event.wait(timeout=10):
            return False, "方案切换超时，将在引擎空闲后生效"
        if cmd.response_data:
            return cmd.response_data
        return False, "方案切换未返回结果"

    def start_monitoring(self) -> tuple[bool, str]:
        logger.debug("收到启动监控请求")
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
        logger.debug("收到停止监控请求")
        with self._start_stop_lock:
            if not self._is_monitoring:
                return False, "监控未运行"

            if not self._enqueue(EngineCommand(type=EngineCmdType.STOP)):
                return False, "队列已满"
            return True, "监控已停止"

    def shutdown(self) -> None:
        """两阶段 shutdown：先通知引擎线程退出，等待确认后再清理资源。"""
        if self._shutdown_event.is_set():
            return
        self._scheduler_running = False

        # 阶段 1：通知引擎线程退出
        self._shutdown_event.set()
        with contextlib.suppress(queue.Full):
            self._cmd_queue.put_nowait(EngineCommand(type=EngineCmdType.SHUTDOWN))

        # 等待引擎线程退出（最多 5 秒）
        if self._engine_thread and self._engine_thread.is_alive():
            self._engine_thread.join(timeout=5.0)

        # 阶段 2：引擎线程已退出，安全清理（不会再有并发修改）
        core = self._monitor_core
        if core is not None:
            with contextlib.suppress(Exception):
                core.stop_monitoring()
        self._monitor_core = None

        logger.info("引擎服务已关闭")

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
        with self._manual_login_lock:
            if self._manual_login_in_progress:
                return False, "登录操作正在进行中"
            self._manual_login_in_progress = True
        try:
            logger.debug("收到手动登录请求")

            cmd = EngineCommand(
                type=EngineCmdType.LOGIN,
                data={},
                response_event=threading.Event(),
            )
            if not self._enqueue(cmd):
                return False, "队列已满"

            # Wait for consumer to execute login (with timeout)
            login_timeout = self._ui_config.login_timeout
            cmd.response_event.wait(timeout=login_timeout)

            if cmd.response_data is None:
                # 超时：检查引擎线程是否存活
                # 如果引擎线程已死，返回明确错误信息
                if not self._engine_thread.is_alive():
                    logger.error("引擎线程已退出")
                    return False, "手动登录超时（引擎线程已退出）"
                return False, "手动登录超时"

            success, message = cmd.response_data
            if success:
                # network_state 已由消费者 _handle_login 统一赋值，无需 API 线程操作
                self._update_status_snapshot()
                logger.info("手动登录任务已提交")
                return True, "登录已提交"

            log_msg = re.sub(SCREENSHOT_URL_PATTERN, "", message)
            logger.warning("手动登录提交失败: {}", log_msg)
            return False, f"登录提交失败：{message}"
        finally:
            with self._manual_login_lock:
                self._manual_login_in_progress = False

    def test_network(self) -> tuple[bool, str]:
        logger.debug("开始手动网络测试")
        config = self._copy_runtime_config()
        monitor_cfg = config.get("monitor", {})
        targets = monitor_cfg.get("ping_targets", [])
        enable_tcp = monitor_cfg.get("enable_tcp_check", False)
        enable_http = monitor_cfg.get("enable_http_check", False)
        url_checks = monitor_cfg.get("url_check_urls", None)
        test_sites = parse_ping_targets(targets)
        mode_desc = []
        if enable_tcp:
            mode_desc.append(f"TCP({len(test_sites) if test_sites else 2})")
        if enable_http:
            mode_desc.append("HTTP(2)")
        if url_checks:
            mode_desc.append(f"网址响应({len(url_checks)})")
        self.record_log("开始手动网络测试", "INFO", "network")
        logger.debug("检测方式: {}", "+".join(mode_desc) or "无")
        try:
            timeout = monitor_cfg.get("network_check_timeout", 2)
            is_available = is_network_available(
                test_sites=test_sites if test_sites else None,
                timeout=timeout,
                enable_tcp=enable_tcp,
                enable_http=enable_http,
                url_checks=url_checks if url_checks else None,
            )
            if is_available:
                self.record_log("手动测试结果: 网络正常", "INFO", "network")
                self.notify_network_state_changed()  # 新增
                return True, "网络连接正常"
            else:
                self.record_log("手动测试结果: 网络异常", "WARNING", "network")
                self.notify_network_state_changed()  # 新增
                return False, "网络连接异常"
        except Exception as exc:
            logger.exception("网络测试失败")
            self.record_log(f"手动测试异常: {exc}", "ERROR", "network")
            self.notify_network_state_changed()  # 新增
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
                lambda d: setattr(d.global_settings, "pure_mode", new_value)
            )
            self._pure_mode = new_value
            return new_value

    def get_runtime_config(self) -> dict:
        """线程安全地获取运行时配置副本"""
        return self._copy_runtime_config()

    # ── 定时任务调度 ──

    @property
    def scheduler_running(self) -> bool:
        """调度器是否正在运行。"""
        return self._scheduler_running

    def has_enabled_tasks(self) -> bool:
        """检查是否存在启用的定时任务（委托）。"""
        return self._task_executor.has_enabled_tasks()

    def start_scheduler(self) -> None:
        """启动定时任务调度。"""
        if self._scheduler_running:
            return
        self._scheduler_running = True
        self._next_schedule_tick = (int(time.time() // 60) * 60) + 60
        logger.info("定时任务调度器已启动")

    def stop_scheduler(self) -> None:
        """停止定时任务调度。"""
        self._scheduler_running = False
        logger.info("定时任务调度器已停止")
