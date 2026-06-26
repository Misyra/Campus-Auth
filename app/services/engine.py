"""ScheduleEngine — 统一的后台服务引擎。

合并 MonitorService（网络监控）和 SchedulerService（定时任务调度）的全部功能，
使用 Actor 模型（线程 + 队列）进行命令派发，零 asyncio 依赖的核心逻辑。

职责边界：命令队列、监控循环、重试逻辑、调度器。
WS 广播委托给 WsBroadcaster，网络测试委托给 NetworkTester。
"""

from __future__ import annotations

import contextlib
from concurrent.futures import CancelledError, Future
import queue
import re
import threading
import time
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from app.schemas import MonitorStatusResponse, RuntimeConfig
from app.services.engine_status import StatusManager
from app.services.monitor_service import NetworkMonitorCore
from app.services.websocket_manager import WebSocketManager
from app.utils import ConfigValidator
from app.utils.logging import get_logger
from app.utils.login import SCREENSHOT_URL_PATTERN

from .profile_service import ProfileService
from .retry_policy import MonitoredPolicy

# 向后兼容：常量已迁移至 ws_broadcaster 模块
from app.services.ws_broadcaster import WS_DRAIN_INTERVAL_SECONDS  # noqa: F401

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


logger = get_logger("engine", source="backend")



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
        ws_broadcaster=None,
        network_tester=None,
        orchestrator=None,
    ):
        self.project_root = project_root
        if profile_service is None:
            raise ValueError("profile_service is required; inject from ServiceContainer")
        self._profile_service = profile_service
        self._ws_manager = ws_manager
        self._login_history = login_history_service
        self._worker_getter = worker_getter

        # 新组件注入
        self._task_registry = task_registry
        self._task_executor = task_executor
        self._ws_broadcaster = ws_broadcaster
        self._network_tester = network_tester

        # 调度状态（从 ScheduledTaskService 搬入）
        self._scheduler_running = False
        self._next_schedule_tick = 0.0

        # 锁（必须在 _reload_config_internal 之前初始化）
        self._manual_login_in_progress = False
        self._manual_login_lock: threading.Lock = threading.Lock()
        self._reload_lock: threading.Lock = threading.Lock()
        self._pure_mode: bool = False
        self._start_stop_lock: threading.Lock = threading.Lock()
        self._retry_time_lock: threading.Lock = threading.Lock()

        # 运行时配置快照（仅在 reload 时更新，读取零拷贝）
        self._runtime_snapshot: RuntimeConfig | None = None
        # 配置对象（由 _reload_config_internal 初始化）
        self._runtime_config: RuntimeConfig = RuntimeConfig()

        # 加载配置（复用 _reload_config_internal）
        self._reload_config_internal()

        self._monitor_core: NetworkMonitorCore | None = None

        # Actor model: command dispatch queue
        self._cmd_queue: queue.Queue[EngineCommand] = queue.Queue(maxsize=50)
        self._shutdown_event = threading.Event()

        # StatusManager — 状态快照与广播
        self._status_manager = StatusManager(
            get_monitor_core=lambda: self._monitor_core,
            ws_broadcaster=self._ws_broadcaster,
        )

        # 登录并发控制 —— 委托 task_executor.is_login_running()

        # ── 统一引擎状态 ──
        self._engine_running = False
        self._next_network_check: float = 0
        self._monitor_check_interval: int = 300
        self._orchestrator = orchestrator  # LoginOrchestrator
        self._retry_policy = MonitoredPolicy()
        self._wakeup_event = threading.Event()  # 唤醒引擎循环
        self._next_retry_time: float = 0  # 下次重试时间（独立于网络检测）

        # LoginBridge — 登录委托
        from app.services.engine_login_bridge import LoginBridge
        self._login_bridge = LoginBridge(
            get_orchestrator=lambda: self._orchestrator,
            get_runtime_config=self.get_runtime_config,
            retry_policy=self._retry_policy,
            status_update_callback=self._update_status_snapshot,
            record_log=self.record_log,
            wakeup_event=self._wakeup_event,
            get_monitor_check_interval=lambda: self._monitor_check_interval,
        )
        # 桥接回调：LoginBridge 调度重试/成功/用尽时更新 engine 状态
        def _bridge_retry_scheduled(delay: float) -> None:
            with self._retry_time_lock:
                self._next_retry_time = time.time() + delay
            self._wakeup_event.set()
        def _bridge_login_success() -> None:
            with self._retry_time_lock:
                self._next_retry_time = 0
        def _bridge_retry_exhausted() -> None:
            with self._retry_time_lock:
                self._next_retry_time = 0
        self._login_bridge._on_retry_scheduled = _bridge_retry_scheduled
        self._login_bridge._on_login_success = _bridge_login_success
        self._login_bridge._on_retry_exhausted = _bridge_retry_exhausted

        # 统一引擎线程（延迟到 boot() 启动，确保依赖注入完成）
        self._engine_thread = threading.Thread(target=self._engine_loop, daemon=True)

    # ── 队列入队辅助 ──

    def _enqueue(self, cmd: EngineCommand) -> bool:
        """尝试将命令入队。返回 True 表示成功。"""
        try:
            self._cmd_queue.put_nowait(cmd)
            if hasattr(self, "_wakeup_event"):
                self._wakeup_event.set()
            return True
        except queue.Full:
            logger.warning("命令队列已满 (type={})，操作被跳过", cmd.type)
            return False

    # ── 统一引擎循环 ──

    # 引擎循环最大睡眠时间（秒）。限制此值确保 _on_done 回调更新
    # _next_network_check 后，引擎线程能及时唤醒执行重试。
    _MAX_LOOP_SLEEP: float = 5.0

    def _engine_loop(self) -> None:
        """统一引擎循环：命令处理 + 网络检测 + 定时任务调度。"""
        self._engine_running = True
        logger.info("引擎循环已启动")

        while not self._shutdown_event.is_set():
            try:
                wakeup_time = self._calculate_wakeup()
                timeout = min(self._MAX_LOOP_SLEEP, max(0.01, wakeup_time - time.time()))

                # 等待唤醒事件（可被 _on_done 等回调中断）或超时
                self._wakeup_event.wait(timeout=timeout)
                self._wakeup_event.clear()

                # 处理命令队列（优先处理命令）
                try:
                    cmd = self._cmd_queue.get_nowait()
                except queue.Empty:
                    cmd = None

                if cmd is not None:
                    self._process_command(cmd)
                    if cmd.type == EngineCmdType.SHUTDOWN:
                        break
                    continue

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
                        self._do_async_login()

                # 网络检测
                if self._is_monitoring and now >= self._next_network_check:
                    self._do_network_check()

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

        if self._is_monitoring:
            candidates.append(float(self._next_network_check))
            with self._retry_time_lock:
                if self._next_retry_time > 0:
                    candidates.append(self._next_retry_time)

        if self._scheduler_running:
            candidates.append(self._next_schedule_tick)

        return min(candidates)

    def _process_command(self, cmd: EngineCommand) -> None:
        """处理一个命令。response_event 由各处理器自行触发。"""
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
            # 异常兜底：必须触发 response_event，否则调用方永远阻塞
            if cmd.response_event:
                if cmd.response_data is None:
                    cmd.response_data = (False, f"命令执行异常: {cmd.type}")
                cmd.response_event.set()
        finally:
            self._cmd_queue.task_done()

    def _do_network_check(self) -> None:
        """执行一次网络检测。"""
        core = self._monitor_core
        if core is None:
            return

        try:
            result = core.check_once()
            self._monitor_check_interval = result.interval

            # BUG-026 修复：先检查方案切换，再决定登录（避免使用旧凭据）
            if core.consume_profile_switch_flag():
                if self._reload_config_internal():
                    self._handle_stop()
                    self._handle_start(EngineCommand(type=EngineCmdType.START))
                    # BUG-016 修复：方案切换后立即检测，不覆盖 _next_network_check
                    return
                else:
                    logger.error("配置重载失败，继续使用当前配置")

            # 网络检测前清除重试定时（避免重复触发）
            with self._retry_time_lock:
                self._next_retry_time = 0

            if result.need_login:
                self._retry_policy.on_network_check(True)
                if self._retry_policy.retries_exhausted:
                    # 重试用尽，重置计数，由下次网络检测触发新一轮重试
                    self._retry_policy.reset()
                    self.record_log(
                        f"重试已用尽（{self._retry_policy.max_retries}/{self._retry_policy.max_retries}），"
                        f"等待下次网络检测（{self._monitor_check_interval}s 后）",
                        level="WARNING", source="network",
                    )
                else:
                    self._do_async_login()
            else:
                self._retry_policy.on_network_check(False)

            self._next_network_check = time.time() + result.interval
            self._update_status_snapshot(force=True)
        except Exception:
            logger.exception("网络检测异常")
            self._next_network_check = time.time() + self._monitor_check_interval

    def _do_async_login(self, is_manual: bool = False, config_snapshot: RuntimeConfig | None = None) -> bool:
        """【委托】提交登录到 LoginBridge。"""
        return self._login_bridge.submit_login(is_manual=is_manual, config_snapshot=config_snapshot)

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
            if cmd.response_event:
                cmd.response_event.set()
            return

        # 统一验证配置（确保所有路径都经过验证）
        valid, error = ConfigValidator.validate_env_config(self._runtime_config)
        if not valid:
            self.record_log(f"配置无效，无法启动监控: {error}", level="ERROR", source="backend")
            if cmd.response_event:
                cmd.response_event.set()
            return

        config = self._runtime_config
        pure_mode = cmd.data.get("pure_mode", self.pure_mode)
        if pure_mode:
            # frozen model: create new browser copy with pure_mode=True
            config = config.model_copy(update={"browser": config.browser.model_copy(update={"pure_mode": True})})

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
        self._update_status_snapshot(force=True)
        self.record_log("监控已启动", level="INFO", source="backend")
        if cmd.response_event:
            cmd.response_event.set()

    def _handle_stop(self, cmd: EngineCommand | None = None) -> None:
        """停止监控。"""
        core = self._monitor_core
        if core is None:
            if cmd and cmd.response_event:
                cmd.response_event.set()
            return

        core.stop_monitoring()
        self._monitor_core = None
        self._next_network_check = 0
        with self._retry_time_lock:
            self._next_retry_time = 0

        self.record_log("监控已停止", level="INFO", source="backend")
        self._update_status_snapshot(force=True)
        if cmd and cmd.response_event:
            cmd.response_event.set()

    def _handle_shutdown(self, cmd: EngineCommand) -> None:
        """处理关闭命令。"""
        self._handle_stop()

    def _handle_login(self, cmd: EngineCommand) -> None:
        """执行一次性登录（手动触发，异步等待完成）。

        提交登录任务后立即返回，由 done_callback 通知 API 线程结果。
        引擎线程不再阻塞，可继续处理 STOP/RELOAD/SHUTDOWN 等命令。
        """
        if self._orchestrator is None:
            cmd.response_data = (False, "登录服务未初始化")
            cmd.response_event.set()
            return
        err = self._orchestrator.validate(self._runtime_config)
        if err is not None:
            cmd.response_data = (False, err)
            cmd.response_event.set()
            return

        handle = self._orchestrator.submit(source="manual", config=self._runtime_config)
        if handle.rejected_reason is not None:
            cmd.response_data = (False, handle.rejected_reason)
            cmd.response_event.set()
            return
        if handle.future is None:
            cmd.response_data = (False, "登录任务已在执行中，请稍后再试")
            cmd.response_event.set()
            return

        # 非阻塞：注册回调，由回调通知 API 线程
        def _on_login_done(f: Future) -> None:
            try:
                ok, msg = f.result()
            except CancelledError:
                ok, msg = False, "登录已取消"
            except Exception as e:
                ok, msg = False, f"登录内部错误: {e}"
            cmd.response_data = (ok, msg)
            if cmd.response_event:
                cmd.response_event.set()

        handle.future.add_done_callback(_on_login_done)

    def cancel_login(self) -> tuple[bool, str]:
        """取消当前正在执行的登录。"""
        return self._login_bridge.cancel_login()

    def _handle_reload(self, cmd: EngineCommand) -> None:
        """重载配置并重启监控（仅在引擎线程中调用）。"""
        was_monitoring = self._is_monitoring

        # 先加载新配置（不修改当前运行状态）
        if not self._reload_config_internal():
            logger.error("配置重载失败，监控继续使用旧配置运行")
            cmd.response_data = (False, "配置重载失败")
            if cmd.response_event:
                cmd.response_event.set()
            return

        # 仅当重载成功且之前处于监控状态时，才执行 stop/start
        if was_monitoring:
            self._handle_stop()
            self._handle_start(EngineCommand(type=EngineCmdType.START))
        logger.info("配置已重载")
        cmd.response_data = (True, "配置重载成功")
        if cmd.response_event:
            cmd.response_event.set()

    def _handle_apply_profile(self, cmd: EngineCommand) -> None:
        """切换方案并重启监控（仅在引擎线程中调用）。

        内部自动设置活跃方案，调用方无需先调 set_active_profile。
        """
        profile_id = cmd.data.get("profile_id", "")
        was_monitoring = self._is_monitoring

        # 内部设置活跃方案，不再依赖调用方
        ok, msg = self._profile_service.set_active_profile(profile_id)
        if not ok:
            cmd.response_data = (False, msg)
            if cmd.response_event:
                cmd.response_event.set()
            return

        # 加载新配置
        if not self._reload_config_internal():
            logger.error("配置重载失败，监控继续使用旧方案运行")
            cmd.response_data = (False, "方案切换失败")
            if cmd.response_event:
                cmd.response_event.set()
            return

        # 直接用 profile_id 记录日志，避免重复 load
        new_url = self._runtime_config.credentials.auth_url
        new_user = self._runtime_config.credentials.username
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
        if cmd.response_event:
            cmd.response_event.set()

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
        self._status_manager.update_snapshot(force=force)

    def set_ws_broadcaster(self, ws_broadcaster) -> None:
        """注入 WsBroadcaster（供 container 轻量模式唤醒时调用）。"""
        self._status_manager.set_ws_broadcaster(ws_broadcaster)

    # ── 公共 API（监控 — 从 API 线程 / main.py 调用）──

    def start_thread(self) -> None:
        """仅启动引擎线程（命令处理循环），不启动监控。

        用于 startup_action=none 场景：引擎线程必须运行以处理
        配置保存等命令，但监控由用户手动启动。
        """
        if not self._engine_thread.is_alive():
            self._shutdown_event.clear()
            self._wakeup_event.clear()
            # 清除上次残留的命令
            while not self._cmd_queue.empty():
                try:
                    self._cmd_queue.get_nowait()
                except Exception:
                    break
            self._engine_thread = threading.Thread(target=self._engine_loop, daemon=True)
            self._engine_thread.start()

    def boot(self) -> None:
        """启动引擎（线程 + 监控）。由调用方决定是否调用，不再自行判断配置。"""
        # 启动引擎线程（确保所有依赖注入完成后再启动）
        self.start_thread()
        self.start_monitoring()

    @property
    def login_in_progress(self) -> bool:
        return self._task_executor.is_login_running() if self._task_executor else False

    def set_dashboard_sink(self, sink) -> None:
        self._status_manager.set_dashboard_sink(sink)

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

    def get_config(self) -> RuntimeConfig:
        return self._runtime_config

    def _reload_config_internal(self) -> bool:
        """从 settings.json 重新加载 UI 和运行时配置。返回 True 表示成功。"""
        try:
            with self._reload_lock:
                data = self._profile_service.load()
                self._runtime_config = self._profile_service.build_runtime_config(data)
                self._runtime_snapshot = self._runtime_config
                self._pure_mode = data.global_config.browser.pure_mode
            return True
        except Exception:
            logger.exception("配置重载失败")
            return False

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

            # 提前验证，立即返回错误信息（_handle_start 中也会验证）
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
        self._stop_scheduler()

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
        return self._status_manager.get_status()

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
            # API 等待超时应略大于 Worker 超时，给足执行余量
            login_timeout = self._runtime_config.browser.login_timeout
            worker_timeout = max(login_timeout, 60)
            api_wait_timeout = worker_timeout + 10
            cmd.response_event.wait(timeout=api_wait_timeout)

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
                logger.info("手动登录成功")
                return True, "登录成功"

            log_msg = re.sub(SCREENSHOT_URL_PATTERN, "", message)
            logger.warning("手动登录失败: {}", log_msg)
            return False, f"登录失败：{message}"
        finally:
            with self._manual_login_lock:
                self._manual_login_in_progress = False

    def test_network(self) -> tuple[bool, str]:
        """委托 NetworkTester 执行手动网络测试。"""
        if self._network_tester is None:
            return False, "网络测试服务未初始化"
        self.record_log("开始手动网络测试", "INFO", "network")
        result = self._network_tester.test_network(self._runtime_config)
        success, message = result
        if success:
            self.record_log("手动测试结果: 网络正常", "INFO", "network")
        else:
            self.record_log("手动测试结果: 网络异常", "WARNING", "network")
        self.notify_network_state_changed()
        return result

    def list_logs(self, limit: int = 200) -> list:
        return self._status_manager.list_logs(limit=limit)

    def toggle_pure_mode(self) -> bool:
        """切换纯净模式，返回新值。"""
        with self._reload_lock:
            new_value = not self._pure_mode
            self._pure_mode = new_value
        # 持久化在锁外执行，避免持锁做磁盘 I/O
        self._profile_service.update(
            lambda d: setattr(
                d, "global_config",
                d.global_config.model_copy(update={
                    "browser": d.global_config.browser.model_copy(update={"pure_mode": new_value})
                }),
            )
        )
        return new_value

    def get_runtime_config(self) -> RuntimeConfig:
        """线程安全地获取运行时配置（frozen 对象，直接返回引用）。"""
        return self._runtime_config

    # ── 定时任务调度 ──

    @property
    def scheduler_running(self) -> bool:
        """调度器是否正在运行。"""
        return self._scheduler_running

    def has_enabled_tasks(self) -> bool:
        """检查是否存在启用的定时任务（委托）。"""
        return self._task_executor.has_enabled_tasks() if self._task_executor else False

    def sync_scheduler_state(self) -> None:
        """根据是否有启用任务自动启停调度器。"""
        has_tasks = self._task_executor.has_enabled_tasks() if self._task_executor else False
        if has_tasks and not self._scheduler_running:
            self._start_scheduler()
        elif not has_tasks and self._scheduler_running:
            self._stop_scheduler()

    def _start_scheduler(self) -> None:
        """启动定时任务调度（内部方法）。"""
        if self._scheduler_running:
            return
        self._scheduler_running = True
        self._next_schedule_tick = (int(time.time() // 60) * 60) + 60
        logger.info("定时任务调度器已启动")

    def _stop_scheduler(self) -> None:
        """停止定时任务调度（内部方法）。"""
        self._scheduler_running = False
        logger.info("定时任务调度器已停止")
