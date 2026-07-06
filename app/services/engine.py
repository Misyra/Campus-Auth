"""ScheduleEngine — 统一的后台服务引擎。

合并 MonitorService（网络监控）和 SchedulerService（定时任务调度）的全部功能，
使用 Actor 模型（asyncio loop 线程 + asyncio.Queue）进行命令派发。

职责边界：命令队列、监控循环、重试逻辑、调度器、手动网络测试。
WS 广播委托给 WebSocketManager。
"""

from __future__ import annotations

import asyncio
import contextlib
import threading
import time
from collections.abc import Callable
from concurrent.futures import CancelledError, Future
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.services.login_orchestrator import LoginOrchestrator
    from app.utils.logging import DashboardSink

from app.network.decision import is_network_available
from app.network.parsers import parse_ping_targets, parse_url_checks
from app.schemas import MonitorStatusResponse, RuntimeConfig
from app.services.monitor_service import NetworkMonitorCore
from app.services.websocket_manager import WebSocketManager
from app.utils import validate_env_config
from app.utils.logging import get_logger

from .profile_service import ProfileService
from .retry_policy import MonitoredPolicy

# ── Actor 模型：类型化命令派发 ──


class EngineCmdType(StrEnum):
    """引擎命令类型。"""

    START = "start"
    STOP = "stop"
    LOGIN = "login"
    SHUTDOWN = "shutdown"
    RELOAD = "reload"
    APPLY_PROFILE = "apply_profile"
    TEST_NETWORK = "test_network"
    NOOP = "noop"  # 空操作，仅用于唤醒 loop


@dataclass
class EngineCommand:
    """从 API 线程派发到引擎 loop 线程的命令。"""

    type: EngineCmdType
    data: dict = field(default_factory=dict)
    response_future: asyncio.Future | None = None  # engine loop 上创建，调用方 await
    response_data: Any = None  # 由消费者设置
    cancelled: bool = False  # 超时时由派发方置 True，消费者跳过执行


logger = get_logger("engine", source="backend")


# ── StatusSnapshot / StatusManager ──


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


class StatusManager:
    """状态快照管理与 WS 广播桥接。"""

    def __init__(
        self,
        get_monitor_core: Callable[[], NetworkMonitorCore | None],
        ws_manager: WebSocketManager | None = None,
    ) -> None:
        self._get_monitor_core = get_monitor_core
        self._ws_manager = ws_manager
        self._status_snapshot = StatusSnapshot()
        self._last_snapshot_time: float = 0
        self._snapshot_min_interval: float = 1.0
        self._dashboard_sink: DashboardSink | None = None

    def set_ws_manager(self, ws_manager: WebSocketManager) -> None:
        self._ws_manager = ws_manager

    def set_dashboard_sink(self, sink: DashboardSink) -> None:
        self._dashboard_sink = sink

    def update_snapshot(self, force: bool = False) -> None:
        """Read monitor_core state into lock-free StatusSnapshot."""
        now = time.time()
        if not force and now - self._last_snapshot_time < self._snapshot_min_interval:
            return
        self._last_snapshot_time = now

        core = self._get_monitor_core()
        if core is not None:
            try:
                snap = core.snapshot()
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
                logger.warning("状态快照更新失败", exc_info=True)
        else:
            self._status_snapshot = StatusSnapshot(
                snapshot_time=time.time(), status_detail="已停止"
            )

        self._queue_status_broadcast()

    def _queue_status_broadcast(self) -> None:
        if self._ws_manager is None:
            return
        try:
            status = self.get_status()
            self._ws_manager.enqueue_status(status.model_dump())
        except Exception:
            logger.warning("状态广播队列失败", exc_info=True)

    def get_status(self) -> MonitorStatusResponse:
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

    def list_logs(self, limit: int = 200) -> list:
        if limit <= 0 or self._dashboard_sink is None:
            return []
        return self._dashboard_sink.list_logs(limit=limit)


# ── LoginBridge ──


class LoginBridge:
    """登录提交与回调管理，从 ScheduleEngine._do_async_login 提取。"""

    def __init__(
        self,
        get_orchestrator: Callable[[], LoginOrchestrator | None],
        get_runtime_config: Callable[[], RuntimeConfig],
        retry_policy: MonitoredPolicy,
        status_update_callback: Callable[[], None],
        logger,
        get_monitor_check_interval: Callable[[], int],
        on_retry_scheduled: Callable[[float], None] | None = None,
        on_login_success: Callable[[], None] | None = None,
        on_retry_exhausted: Callable[[], None] | None = None,
    ) -> None:
        self._get_orchestrator = get_orchestrator
        self._get_runtime_config = get_runtime_config
        self._retry_policy = retry_policy
        self._status_update_callback = status_update_callback
        self._logger = logger
        self._get_monitor_check_interval = get_monitor_check_interval
        self._registered_futures: set[Future] = set()
        self._futures_lock = threading.Lock()
        self._on_retry_scheduled = on_retry_scheduled or (lambda delay: None)
        self._on_login_success = on_login_success or (lambda: None)
        self._on_retry_exhausted = on_retry_exhausted or (lambda: None)

    async def submit_login(
        self,
        is_manual: bool = False,
        config_snapshot: RuntimeConfig | None = None,
        on_complete: Callable[[bool, str], None] | None = None,
    ) -> bool:
        """提交登录到 LoginOrchestrator。

        Args:
            on_complete: 登录完成回调（含被拒、取消、异常所有终态）。
                None 时走 auto 路径的 retry_policy 逻辑；非 None 时走 manual 路径，
                由调用方自行处理重试（manual 不参与 retry_policy）。
        """
        # 清理已完成的 Future 引用，防止极端情况下残留
        with self._futures_lock:
            self._registered_futures = {
                f for f in self._registered_futures if not f.done()
            }

        orchestrator = self._get_orchestrator()
        if orchestrator is None:
            if on_complete is not None:
                on_complete(False, "登录服务未初始化")
            return False

        config = (
            config_snapshot
            if config_snapshot is not None
            else self._get_runtime_config()
        )

        # 自动登录前检查物理网络和认证地址可达性
        if not is_manual:
            m = config.monitor
            if m.enable_local_check or m.check_auth_url:
                from app.network.decision import check_login_prerequisites

                ok, reason = await check_login_prerequisites(
                    m, config.credentials.auth_url
                )
                if not ok:
                    self._logger.warning("登录前置检查未通过: {}", reason)
                    if on_complete is not None:
                        on_complete(False, reason)
                    return False

        source = "manual" if is_manual else "auto"
        try:
            handle = orchestrator.submit(source=source, config=config)
        except Exception as exc:
            self._logger.error("登录提交异常: {}", exc)
            if on_complete is not None:
                on_complete(False, str(exc))
            return False

        if handle.rejected_reason is not None:
            self._logger.warning("登录被拒绝: {}", handle.rejected_reason)
            if on_complete is not None:
                on_complete(False, handle.rejected_reason)
            return False

        if handle.future is None:
            # 复用了旧 handle（去重命中），不算新提交
            msg = "登录任务已在执行中，请稍后再试"
            if on_complete is not None:
                on_complete(False, msg)
            return False

        # 防止去重命中时重复注册回调
        with self._futures_lock:
            if handle.future in self._registered_futures:
                msg = "登录任务已在执行中，请稍后再试"
                if on_complete is not None:
                    on_complete(False, msg)
                return False

        def _on_done(f: Future) -> None:
            with self._futures_lock:
                self._registered_futures.discard(f)
            self._status_update_callback()
            try:
                ok, msg = f.result()
                if on_complete is not None:
                    # manual 路径：直接回调，不参与 retry_policy
                    on_complete(ok, msg)
                elif not is_manual:
                    # auto 路径：维护 retry_policy 状态
                    if ok:
                        self._retry_policy.on_login_done(success=True)
                        self._on_login_success()
                    else:
                        delay = self._retry_policy.on_login_done(success=False)
                        if delay is None:
                            self._on_retry_exhausted()
                            logger.warning(
                                "登录重试次数已用尽（{}/{}），等待网络恢复（下次检测 {}s 后）",
                                self._retry_policy.attempt,
                                self._retry_policy.max_retries,
                                self._get_monitor_check_interval(),
                            )
                        else:
                            from datetime import datetime as _dt

                            next_time = _dt.fromtimestamp(time.time() + delay).strftime(
                                "%H:%M:%S"
                            )
                            logger.debug(
                                "重试 {}/{}, 下次重试: {}s 后 ({})",
                                self._retry_policy.attempt,
                                self._retry_policy.max_retries,
                                int(delay),
                                next_time,
                            )
                            self._on_retry_scheduled(delay)
                # is_manual=True 且无 on_complete：仅更新状态，不动 retry_policy
            except CancelledError:
                logger.warning("登录任务已取消 (source={})", source)
                if on_complete is not None:
                    on_complete(False, "登录已取消")
            except Exception as e:
                logger.exception("登录任务异常: {}", e)
                if on_complete is not None:
                    on_complete(False, f"登录内部错误: {e}")

        with self._futures_lock:
            self._registered_futures.add(handle.future)
        handle.future.add_done_callback(_on_done)
        return True

    def cancel_login(self) -> tuple[bool, str]:
        """取消当前正在执行的登录。"""
        orchestrator = self._get_orchestrator()
        if orchestrator is None:
            return False, "登录服务未初始化"
        orchestrator.cancel_running()
        return True, "登录已取消"


# ── ScheduleEngine ──


class ScheduleEngine:
    """统一的后台服务引擎，合并网络监控与定时任务调度。"""

    def __init__(
        self,
        project_root: Path,
        profile_service: ProfileService = None,
        ws_manager: WebSocketManager | None = None,
        login_history_service=None,
        worker_getter=None,
        task_registry=None,
        task_executor=None,
        orchestrator=None,
        scheduler=None,
    ):
        self.project_root = project_root
        if profile_service is None:
            raise ValueError(
                "profile_service is required; inject from ServiceContainer"
            )
        self._profile_service = profile_service
        self._ws_manager = ws_manager
        self._login_history = login_history_service
        self._worker_getter = worker_getter

        # 新组件注入
        self._task_registry = task_registry
        self._task_executor = task_executor

        # 调度器（从 ScheduleEngine 提取为独立组件）
        self._scheduler = scheduler

        # 锁（必须在 _reload_config_internal 之前初始化）
        self._manual_login_in_progress = False
        self._manual_login_lock: threading.Lock = threading.Lock()
        self._reload_lock: threading.Lock = threading.Lock()
        self._pure_mode: bool = False
        self._start_stop_lock: threading.Lock = threading.Lock()
        self._retry_time_lock: threading.Lock = threading.Lock()

        # 配置对象（由 _reload_config_internal 初始化）
        self._runtime_config: RuntimeConfig = RuntimeConfig()

        # 加载配置（复用 _reload_config_internal）
        self._reload_config_internal()

        self._monitor_core: NetworkMonitorCore | None = None

        # Actor model: command dispatch queue (asyncio.Queue on engine loop)
        self._cmd_queue: asyncio.Queue[EngineCommand] = asyncio.Queue(maxsize=50)
        self._shutdown_event = threading.Event()
        self._engine_loop: asyncio.AbstractEventLoop | None = None
        self._engine_thread: threading.Thread | None = None
        self._engine_ready = threading.Event()

        # StatusManager — 状态快照与广播
        self._status_manager = StatusManager(
            get_monitor_core=lambda: self._monitor_core,
            ws_manager=self._ws_manager,
        )

        # 登录并发控制 —— 委托 task_executor.is_login_running()

        # ── 统一引擎状态 ──
        self._engine_running = False
        self._next_network_check: float = 0
        self._monitor_check_interval: int = 300
        self._orchestrator = orchestrator  # LoginOrchestrator
        self._logger = get_logger("engine", source="backend")
        self._retry_policy = MonitoredPolicy()
        self._next_retry_time: float = 0  # 下次重试时间（独立于网络检测）

        # LoginBridge — 登录委托
        def _bridge_retry_scheduled(delay: float) -> None:
            with self._retry_time_lock:
                self._next_retry_time = time.time() + delay
            # 投 noop 命令唤醒 engine loop（不等 asyncio.wait_for timeout）
            loop = self._engine_loop
            if loop is not None and loop.is_running():
                with contextlib.suppress(RuntimeError):
                    loop.call_soon_threadsafe(
                        self._cmd_queue.put_nowait,
                        EngineCommand(type=EngineCmdType.NOOP),
                    )

        def _bridge_login_success() -> None:
            with self._retry_time_lock:
                self._next_retry_time = 0

        def _bridge_retry_exhausted() -> None:
            with self._retry_time_lock:
                self._next_retry_time = 0

        self._login_bridge = LoginBridge(
            get_orchestrator=lambda: self._orchestrator,
            get_runtime_config=self.get_runtime_config,
            retry_policy=self._retry_policy,
            status_update_callback=self._update_status_snapshot,
            logger=self._logger,
            get_monitor_check_interval=lambda: self._monitor_check_interval,
            on_retry_scheduled=_bridge_retry_scheduled,
            on_login_success=_bridge_login_success,
            on_retry_exhausted=_bridge_retry_exhausted,
        )

    # ── Engine loop 线程入口 ──

    _MAX_LOOP_SLEEP: float = 5.0

    def _engine_entry(self) -> None:
        """Engine 线程入口 — 创建独立 asyncio loop，运行 _engine_loop_async task。"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._engine_loop = loop
        self._engine_ready.set()
        try:
            loop.create_task(self._engine_loop_async())
            loop.run_forever()
        finally:
            if not loop.is_closed():
                loop.close()
            self._engine_loop = None
            logger.info("Engine 事件循环已关闭")

    async def _engine_loop_async(self) -> None:
        """异步引擎循环：命令处理 + 网络检测 + 定时任务调度。"""
        self._engine_running = True
        logger.info("引擎循环已启动")

        while not self._shutdown_event.is_set():
            try:
                # 计算下次唤醒时间
                wakeup_time = self._calculate_wakeup()
                timeout = min(
                    self._MAX_LOOP_SLEEP, max(0.01, wakeup_time - time.time())
                )

                # 等待命令或超时
                try:
                    cmd = await asyncio.wait_for(self._cmd_queue.get(), timeout=timeout)
                    await self._process_command_async(cmd)
                    if cmd.type == EngineCmdType.SHUTDOWN:
                        break
                except TimeoutError:
                    pass  # 超时，继续执行周期任务

                now = time.time()

                # 重试（独立于网络检测，延迟后直接登录）
                if self._is_monitoring:
                    with self._retry_time_lock:
                        retry_time = self._next_retry_time
                        if retry_time > 0 and now >= retry_time:
                            self._next_retry_time = 0
                            retry_fired = True
                        else:
                            retry_fired = False
                    if retry_fired:
                        await self._do_async_login()

                # 网络检测
                if self._is_monitoring and now >= self._next_network_check:
                    await self._do_network_check_async()

                # 定时任务
                if self._scheduler and self._scheduler.should_tick(now):
                    self._scheduler.tick(now)
            except Exception as e:
                logger.exception("引擎循环异常，继续运行: {}", e)
                await asyncio.sleep(1)

        self._engine_running = False
        logger.debug("引擎循环已退出")
        # 停止事件循环
        if self._engine_loop and not self._engine_loop.is_closed():
            self._engine_loop.stop()

    def _calculate_wakeup(self) -> float:
        """计算下次唤醒时间。"""
        now = time.time()
        candidates: list[float] = [now + 60]

        if self._is_monitoring:
            candidates.append(float(self._next_network_check))
            with self._retry_time_lock:
                if self._next_retry_time > 0:
                    candidates.append(self._next_retry_time)

        if self._scheduler and self._scheduler.running:
            candidates.append(self._scheduler.next_tick_time)

        return min(candidates)

    async def _process_command_async(self, cmd: EngineCommand) -> None:
        """处理一个命令（async 版本）。response_future 由各处理器自行触发。"""
        try:
            if cmd.cancelled:
                return
            if cmd.type == EngineCmdType.START:
                self._handle_start(cmd)
            elif cmd.type == EngineCmdType.STOP:
                self._handle_stop(cmd)
            elif cmd.type == EngineCmdType.LOGIN:
                await self._handle_login(cmd)
            elif cmd.type == EngineCmdType.SHUTDOWN:
                self._handle_shutdown(cmd)
            elif cmd.type == EngineCmdType.RELOAD:
                self._handle_reload(cmd)
            elif cmd.type == EngineCmdType.APPLY_PROFILE:
                self._handle_apply_profile(cmd)
            elif cmd.type == EngineCmdType.TEST_NETWORK:
                await self._handle_test_network(cmd)
            elif cmd.type == EngineCmdType.NOOP:
                pass  # 空操作，仅唤醒 loop
        except Exception:
            logger.warning("命令执行失败: {}", cmd.type, exc_info=True)
            if cmd.response_future and not cmd.response_future.done():
                cmd.response_data = (False, f"命令执行异常: {cmd.type}")
                cmd.response_future.set_result(cmd.response_data)
        finally:
            self._cmd_queue.task_done()

    async def _do_network_check_async(self) -> None:
        """执行一次网络检测（async 版本）。"""
        core = self._monitor_core
        if core is None:
            return

        try:
            result = await core.check_once()
            self._monitor_check_interval = result.interval

            # BUG-026 修复：先检查方案切换，再决定登录（避免使用旧凭据）
            if core.consume_profile_switch_flag():
                if self._reload_config_internal():
                    self._handle_stop()
                    self._handle_start(EngineCommand(type=EngineCmdType.START))
                    # BUG-016 修复：方案切换后立即检测，不覆盖 _next_network_check
                    return
                else:
                    logger.warning("配置重载失败，继续使用当前配置")

            # 网络检测前清除重试定时（避免重复触发）
            with self._retry_time_lock:
                self._next_retry_time = 0

            if result.need_login:
                self._retry_policy.on_network_check(True)
                if self._retry_policy.retries_exhausted:
                    # 重试用尽，重置计数，由下次网络检测触发新一轮重试
                    self._retry_policy.reset()
                    self._logger.warning(
                        "重试已用尽 ({}/{})，等待下次网络检测 ({}s 后)",
                        self._retry_policy.max_retries,
                        self._retry_policy.max_retries,
                        self._monitor_check_interval,
                    )
                else:
                    await self._do_async_login()
            else:
                self._retry_policy.on_network_check(False)

            self._next_network_check = time.time() + result.interval
            self._update_status_snapshot(force=True)
        except Exception as e:
            logger.exception("网络检测异常: {}", e)
            self._next_network_check = time.time() + self._monitor_check_interval

    async def _do_async_login(
        self, is_manual: bool = False, config_snapshot: RuntimeConfig | None = None
    ) -> bool:
        """【委托】提交登录到 LoginBridge。"""
        return await self._login_bridge.submit_login(
            is_manual=is_manual, config_snapshot=config_snapshot
        )

    def _handle_start(self, cmd: EngineCommand) -> None:
        """启动监控（在引擎循环中调用）。"""
        if self._monitor_core is not None and self._monitor_core.monitoring:
            self._logger.warning("监控已在运行中")
            if cmd.response_future and not cmd.response_future.done():
                cmd.response_future.set_result((True, "监控已在运行中"))
            return

        # 统一验证配置（确保所有路径都经过验证）
        valid, error = validate_env_config(self._runtime_config)
        if not valid:
            self._logger.warning("启动监控失败: 配置无效: {}", error)
            if cmd.response_future and not cmd.response_future.done():
                cmd.response_future.set_result((False, f"配置无效: {error}"))
            return

        pure_mode = cmd.data.get("pure_mode", self.pure_mode)
        # pure_mode 影响 browser 配置，需临时覆盖 getter
        if pure_mode:
            # 动态覆盖：getter 每次取最新 runtime_config 并叠加 pure_mode=True
            # 这样 reload 后 config 变化能自动生效，pure_mode 覆盖仍保持
            base_getter = self.get_runtime_config

            def get_config() -> RuntimeConfig:
                base = base_getter()
                if base.browser.pure_mode:
                    return base
                return base.model_copy(
                    update={
                        "browser": base.browser.model_copy(update={"pure_mode": True})
                    }
                )
        else:
            get_config = self.get_runtime_config

        try:
            core = NetworkMonitorCore(
                get_config=get_config,
                logger=self._logger,
                login_history=self._login_history,
            )
            core.set_profile_service(self._profile_service)
            core.init_monitoring()  # 只初始化，不启动循环
            self._monitor_core = core

            # 传递网卡绑定代理 URL 到登录编排器
            if self._orchestrator is not None:
                self._orchestrator.set_bind_proxy(core.bind_proxy_url)
            self._next_network_check = time.time()  # 立即执行第一次检测
            self._update_status_snapshot(force=True)
            self._logger.info("监控已启动")
            if cmd.response_future and not cmd.response_future.done():
                cmd.response_future.set_result((True, "监控已启动"))
            return
        except Exception as exc:
            self._logger.exception("监控启动失败: {}", exc)
            if cmd.response_future and not cmd.response_future.done():
                cmd.response_future.set_result((False, f"监控启动失败: {exc}"))
            return

    def _handle_stop(self, cmd: EngineCommand | None = None) -> None:
        """停止监控。"""
        core = self._monitor_core
        if core is None:
            if cmd and cmd.response_future and not cmd.response_future.done():
                cmd.response_future.set_result((True, "监控未运行"))
            return

        core.stop_monitoring()
        self._monitor_core = None
        self._next_network_check = 0
        with self._retry_time_lock:
            self._next_retry_time = 0

        self._logger.info("监控已停止")
        self._update_status_snapshot(force=True)
        if cmd and cmd.response_future and not cmd.response_future.done():
            cmd.response_future.set_result((True, "监控已停止"))

    def _handle_shutdown(self, cmd: EngineCommand) -> None:
        """处理关闭命令。"""
        self._handle_stop()

    async def _handle_login(self, cmd: EngineCommand) -> None:
        """执行一次性登录（手动触发，异步等待完成）。

        委托 LoginBridge.submit_login，通过 on_complete 回调统一处理
        被拒/已完成/异步完成所有终态，避免与 auto 路径分叉。
        """

        def _on_complete(ok: bool, msg: str) -> None:
            cmd.response_data = (ok, msg)
            if cmd.response_future and not cmd.response_future.done():
                # _on_complete 由 concurrent.futures.Future.add_done_callback 触发，
                # 可能在 TaskExecutor 的工作线程中执行，必须用 call_soon_threadsafe
                # 将结果安全地设置到 engine loop 上的 asyncio.Future。
                loop = self._engine_loop
                if loop and not loop.is_closed():
                    loop.call_soon_threadsafe(
                        cmd.response_future.set_result, cmd.response_data
                    )

        await self._login_bridge.submit_login(
            is_manual=True,
            config_snapshot=self._runtime_config,
            on_complete=_on_complete,
        )

    def cancel_login(self) -> tuple[bool, str]:
        """取消当前正在执行的登录。"""
        ok, msg = self._login_bridge.cancel_login()
        if not ok:
            logger.warning("取消登录失败: {}", msg)
        return ok, msg

    def _handle_reload(self, cmd: EngineCommand) -> None:
        """重载配置（仅在引擎线程中调用）。

        B2 优化：不再 stop+start 重建 core。_swap_runtime_config 后
        NetworkMonitorCore 通过 getter 自动看到新配置。
        仅当 bind_interface_name 变化时才重建 SOCKS5 Forwarder。
        """
        if not self._reload_config_internal():
            logger.warning("配置重载失败，继续使用当前配置")
            cmd.response_data = (False, "配置重载失败")
            if cmd.response_future and not cmd.response_future.done():
                cmd.response_future.set_result(cmd.response_data)
            return

        # 若监控运行中且 bind_interface_name 变化，重建 core 的 bind proxy
        core = self._monitor_core
        if core is not None and core.monitoring and core._needs_bind_proxy_rebuild():
            self._logger.info("网卡绑定配置变化，重建 SOCKS5 Forwarder")
            core.stop_monitoring()
            core.init_monitoring()  # 重新 _start_bind_proxy

        logger.info("配置已重载")
        cmd.response_data = (True, "配置重载成功")
        if cmd.response_future and not cmd.response_future.done():
            cmd.response_future.set_result(cmd.response_data)

    def _handle_apply_profile(self, cmd: EngineCommand) -> None:
        """切换方案（仅在引擎线程中调用）。

        B2 优化：不再 stop+start 重建 core。
        """
        profile_id = cmd.data.get("profile_id", "")
        ok, msg = self._profile_service.set_active_profile(profile_id)
        if not ok:
            cmd.response_data = (False, msg)
            if cmd.response_future and not cmd.response_future.done():
                cmd.response_future.set_result(cmd.response_data)
            return

        if not self._reload_config_internal():
            logger.warning("配置重载失败，继续使用当前配置")
            cmd.response_data = (False, "方案切换失败")
            if cmd.response_future and not cmd.response_future.done():
                cmd.response_future.set_result(cmd.response_data)
            return

        new_url = self._runtime_config.credentials.auth_url
        new_user = self._runtime_config.credentials.username
        self._logger.info("切换方案: {}", profile_id)
        logger.debug(
            "方案详情: 认证={}, 用户={}",
            new_url,
            new_user[:3] + "***" if new_user else "",
        )

        # 若监控运行中且 bind_interface_name 变化，重建 core 的 bind proxy
        core = self._monitor_core
        if core is not None and core.monitoring and core._needs_bind_proxy_rebuild():
            self._logger.info("方案切换导致网卡绑定变化，重建 SOCKS5 Forwarder")
            core.stop_monitoring()
            core.init_monitoring()

        cmd.response_data = (True, "方案切换成功")
        if cmd.response_future and not cmd.response_future.done():
            cmd.response_future.set_result(cmd.response_data)

    async def _handle_test_network(self, cmd: EngineCommand) -> None:
        """执行手动网络测试（引擎 loop 内异步调用）。"""
        monitor = self._runtime_config.monitor
        targets = monitor.ping_targets
        enable_tcp = monitor.enable_tcp_check
        enable_http = monitor.enable_http_check

        url_checks = parse_url_checks(monitor.url_check_urls)
        test_sites = parse_ping_targets(targets)

        mode_desc = []
        if enable_tcp:
            mode_desc.append(f"TCP({len(test_sites) if test_sites else 2})")
        if enable_http:
            mode_desc.append("HTTP(2)")
        if url_checks:
            mode_desc.append(f"网址响应({len(url_checks)})")

        logger.debug("手动网络测试: {}", "+".join(mode_desc) or "无")

        try:
            timeout = monitor.network_check_timeout
            is_available = await is_network_available(
                test_sites=test_sites if test_sites else None,
                test_urls=monitor.test_urls or None,
                timeout=timeout,
                enable_tcp=enable_tcp,
                enable_http=enable_http,
                url_checks=url_checks if url_checks else None,
            )
            self._update_status_snapshot()
            if is_available:
                cmd.response_data = (True, "网络连接正常")
            else:
                cmd.response_data = (False, "网络连接异常")
        except Exception as exc:
            logger.warning("网络测试失败", exc_info=True)
            self._update_status_snapshot()
            cmd.response_data = (False, f"网络测试失败: {exc}")

        if cmd.response_future and not cmd.response_future.done():
            cmd.response_future.set_result(cmd.response_data)

    def _update_status_snapshot(self, force: bool = False) -> None:
        self._status_manager.update_snapshot(force=force)

    def set_ws_manager(self, ws_manager: WebSocketManager) -> None:
        """注入 WebSocketManager（供 container 轻量模式唤醒时调用）。"""
        self._ws_manager = ws_manager
        self._status_manager.set_ws_manager(ws_manager)

    # ── 公共 API（监控 — 从 API 线程 / main.py 调用）──

    def start_thread(self) -> None:
        """仅启动引擎线程（命令处理循环），不启动监控。

        用于 startup_action=none 场景：引擎线程必须运行以处理
        配置保存等命令，但监控由用户手动启动。
        """
        if self._engine_thread is not None and self._engine_thread.is_alive():
            return
        self._start_engine_thread()

    def boot(self) -> None:
        """启动引擎 loop 线程并自动启动监控。"""
        if self._engine_thread is not None and self._engine_thread.is_alive():
            self.start_monitoring()
            return
        self._start_engine_thread()
        self.start_monitoring()

    def _start_engine_thread(self) -> None:
        """启动引擎 loop 线程（内部方法）。"""
        # 启动前清理孤儿浏览器（所有启动入口统一执行）
        from app.workers.playwright_worker import cleanup_orphan_browsers

        try:
            cleanup_orphan_browsers()
        except Exception as exc:
            logger.warning("清理孤儿浏览器失败: {}", exc)

        self._shutdown_event.clear()
        self._engine_ready.clear()
        self._engine_thread = threading.Thread(
            target=self._engine_entry, daemon=True, name="schedule-engine"
        )
        self._engine_thread.start()
        self._engine_ready.wait(timeout=5.0)
        if not self._engine_ready.is_set():
            logger.warning("Engine 启动失败: loop 超时")
        else:
            logger.info("Engine 启动成功")

    @property
    def pure_mode(self) -> bool:
        """线程安全地读取纯净模式标志。"""
        with self._reload_lock:
            return self._pure_mode

    @property
    def _is_monitoring(self) -> bool:
        core = self._monitor_core
        return core is not None and core.monitoring

    @property
    def tasks(self):
        """定时任务接口（供 API 路由使用）。"""
        return self._task_executor

    def _swap_runtime_config(
        self, new: RuntimeConfig, *, pure_mode: bool | None = None
    ) -> None:
        """原子替换运行时配置（线程安全）。

        所有 _runtime_config 写入必须经此方法，在 _reload_lock 保护下
        原子替换 frozen 引用。禁止直接赋值 self._runtime_config = ...
        """
        with self._reload_lock:
            self._runtime_config = new
            if pure_mode is not None:
                self._pure_mode = pure_mode

    def update_log_level(self, level: str) -> None:
        """更新运行时日志级别（线程安全，供 API 层调用）。

        替代 api/config.py 直接裸改 _runtime_config 的旧行为。
        不入队命令队列——frozen 引用替换已是原子操作，无需串行化。
        """
        from app.constants import VALID_LOG_LEVELS

        if level not in VALID_LOG_LEVELS:
            raise ValueError(f"无效的日志级别: {level}")
        new_config = self._runtime_config.model_copy(
            update={
                "logging": self._runtime_config.logging.model_copy(
                    update={"level": level}
                )
            }
        )
        self._swap_runtime_config(new_config)

    def _reload_config_internal(self) -> bool:
        """从 settings.json 重新加载 UI 和运行时配置。返回 True 表示成功。

        磁盘 IO 在锁外执行（B5：缩小锁粒度），仅 frozen 引用替换持锁。
        """
        try:
            # 无锁加载+构建（磁盘 IO 不持锁，避免阻塞 pure_mode getter）
            data = self._profile_service.load()
            new_config = self._profile_service.build_runtime_config(data)
            pure_mode = data.global_config.browser.pure_mode
        except Exception:
            logger.warning("配置重载失败", exc_info=True)
            return False
        # 持锁原子替换
        self._swap_runtime_config(new_config, pure_mode=pure_mode)
        return True

    # ── 跨线程命令派发桥接 ──

    def _dispatch_command(
        self, cmd_type: EngineCmdType, data: dict | None = None, timeout: float = 10.0
    ) -> tuple[bool, str]:
        """同步派发命令到 engine loop 并等待结果（跨线程桥接）。"""
        if self._engine_loop is None or not self._engine_loop.is_running():
            return False, "引擎未运行"

        async def _send_and_wait():
            cmd = EngineCommand(type=cmd_type, data=data or {})
            cmd.response_future = asyncio.Future()
            await self._cmd_queue.put(cmd)
            try:
                return await asyncio.wait_for(cmd.response_future, timeout=timeout)
            except TimeoutError:
                cmd.cancelled = True  # 标记命令已取消，消费者将跳过执行
                return (False, f"操作超时 ({cmd_type.value})")

        # run_coroutine_threadsafe 返回 concurrent.futures.Future
        future = asyncio.run_coroutine_threadsafe(_send_and_wait(), self._engine_loop)
        try:
            return future.result(timeout=timeout + 5)  # 额外 5s 余量
        except Exception as exc:
            return False, f"命令派发失败: {exc}"

    # ── 公共 API（监控 — 从 API 线程 / main.py 调用）──

    def reload_config(self) -> tuple[bool, str]:
        """重新加载配置并重启监控（如果正在运行）。"""
        return self._dispatch_command(EngineCmdType.RELOAD)

    def apply_profile(self, profile_id: str) -> tuple[bool, str]:
        """切换到新方案：停止监控 → 重载配置 → 重启监控。"""
        return self._dispatch_command(
            EngineCmdType.APPLY_PROFILE, {"profile_id": profile_id}
        )

    def start_monitoring(self) -> tuple[bool, str]:
        logger.debug("收到启动监控请求")
        with self._start_stop_lock:
            if self._is_monitoring:
                return False, "监控已在运行中"

            return self._dispatch_command(EngineCmdType.START, timeout=5.0)

    def stop_monitoring(self) -> tuple[bool, str]:
        logger.debug("收到停止监控请求")
        with self._start_stop_lock:
            if not self._is_monitoring:
                return False, "监控未运行"

            return self._dispatch_command(EngineCmdType.STOP, timeout=5.0)

    def shutdown(self) -> None:
        """两阶段 shutdown。"""
        if self._shutdown_event.is_set():
            return
        if self._scheduler:
            self._scheduler.stop()

        self._shutdown_event.set()
        # 发送 SHUTDOWN 命令
        if self._engine_loop and self._engine_loop.is_running():
            with contextlib.suppress(RuntimeError):
                self._engine_loop.call_soon_threadsafe(
                    self._cmd_queue.put_nowait,
                    EngineCommand(type=EngineCmdType.SHUTDOWN),
                )

        if self._engine_thread and self._engine_thread.is_alive():
            self._engine_thread.join(timeout=5.0)
            if self._engine_thread.is_alive():
                logger.warning("Engine 线程退出超时，强制停止 loop")
                if self._engine_loop and self._engine_loop.is_running():
                    self._engine_loop.call_soon_threadsafe(self._engine_loop.stop)
                self._engine_thread.join(timeout=3.0)

        # 清理 monitor core
        core = self._monitor_core
        if core is not None:
            with contextlib.suppress(Exception):
                core.stop_monitoring()
        self._monitor_core = None
        logger.info("引擎服务已关闭")

    def get_status(self) -> MonitorStatusResponse:
        return self._status_manager.get_status()

    def run_manual_login(self) -> tuple[bool, str]:
        with self._manual_login_lock:
            if self._manual_login_in_progress:
                return False, "登录操作正在进行中"
            self._manual_login_in_progress = True
        try:
            logger.debug("收到手动登录请求")

            # API 等待超时应略大于 Worker 超时，给足执行余量
            login_timeout = self._runtime_config.browser.login_timeout
            worker_timeout = max(login_timeout, 60)
            api_wait_timeout = worker_timeout + 10

            ok, msg = self._dispatch_command(
                EngineCmdType.LOGIN, timeout=api_wait_timeout
            )

            if ok:
                self._update_status_snapshot()
                return True, "登录成功"

            # 超时时取消正在执行的登录任务，避免浏览器资源泄漏
            if "超时" in msg:
                self._login_bridge.cancel_login()
                if self._engine_thread and not self._engine_thread.is_alive():
                    logger.warning("引擎线程已退出")
                    return False, "手动登录超时（引擎线程已退出）"

            return False, f"登录失败：{msg}"
        finally:
            with self._manual_login_lock:
                self._manual_login_in_progress = False

    def test_network(self) -> tuple[bool, str]:
        """执行手动网络测试（派发到引擎 loop 异步执行）。"""
        logger.debug("收到手动网络测试请求")
        return self._dispatch_command(EngineCmdType.TEST_NETWORK)

    def list_logs(self, limit: int = 200) -> list:
        return self._status_manager.list_logs(limit=limit)

    def toggle_pure_mode(self) -> bool:
        """切换纯净模式，返回新值。

        行为变更（Review 标注）：profile_service.update 原在 _reload_lock 内，
        现移出锁外。toggle_pure_mode 极少并发调用（仅 API 手动触发），
        profile_service 内部有锁，风险可接受。
        """
        with self._reload_lock:
            new_value = not self._pure_mode
            base_config = self._runtime_config
        # 磁盘持久化（profile_service 内部有自己的锁，无需 _reload_lock 保护）
        self._profile_service.update(
            lambda d: d.model_copy(
                update={
                    "global_config": d.global_config.model_copy(
                        update={
                            "browser": d.global_config.browser.model_copy(
                                update={"pure_mode": new_value}
                            )
                        }
                    )
                }
            )
        )
        # 原子替换运行时配置（通过 _swap_runtime_config 同步 _pure_mode）
        new_config = base_config.model_copy(
            update={
                "browser": base_config.browser.model_copy(
                    update={"pure_mode": new_value}
                )
            }
        )
        self._swap_runtime_config(new_config, pure_mode=new_value)
        return new_value

    def get_runtime_config(self) -> RuntimeConfig:
        """线程安全地获取运行时配置（frozen 对象，直接返回引用）。"""
        return self._runtime_config

    # ── 定时任务调度（委托代理，向后兼容 API 路由）──

    def sync_scheduler_state(self) -> None:
        """根据是否有启用任务自动启停调度器（委托）。"""
        if self._scheduler:
            self._scheduler.sync_state()
