"""test_services 共享 fixture — 统一 ScheduleEngine 工厂。"""

from __future__ import annotations

import queue
import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from app.schemas import RuntimeConfig
from app.services.engine import ScheduleEngine
from app.services.engine_status import StatusManager, StatusSnapshot
from app.services.retry_policy import MonitoredPolicy


@pytest.fixture
def engine_factory():
    """创建带有 mock 依赖的 ScheduleEngine 实例。

    提供两种模式：
    - engine_factory(): 标准初始化（启动后停止引擎线程）
    - engine_factory(raw=True): 使用 __new__ 跳过 __init__，用于单元隔离测试

    所有模式都 patch 相同的 2 个依赖：
    - engine._reload_config_internal
    - engine.ProfileService
    """

    def _make(**overrides):
        """标准模式：完整初始化后停止引擎线程。"""

        def _fake_reload(self_inner):
            """模拟 _reload_config_internal：设置所有由原方法初始化的属性。"""
            self_inner._runtime_config = RuntimeConfig()
            self_inner._runtime_snapshot = self_inner._runtime_config
            self_inner._pure_mode = False
            return True

        with (
            patch.object(ScheduleEngine, "_reload_config_internal", _fake_reload),
            patch("app.services.engine.ProfileService") as mock_ps_cls,
        ):
            mock_ps = MagicMock()
            mock_ps_cls.return_value = mock_ps

            # 确保 task_executor 有默认值
            if "task_executor" not in overrides:
                overrides["task_executor"] = MagicMock()
            if "profile_service" not in overrides:
                overrides["profile_service"] = mock_ps

            svc = ScheduleEngine.__new__(ScheduleEngine)
            ScheduleEngine.__init__(svc, MagicMock(), **overrides)
            svc._shutdown_event.set()
            if svc._engine_thread and svc._engine_thread.is_alive():
                svc._engine_thread.join(timeout=1)
            return svc

    def _make_raw():
        """原始模式：跳过 __init__，手动设置所有属性。"""
        svc = ScheduleEngine.__new__(ScheduleEngine)
        svc._cmd_queue = queue.Queue(maxsize=50)
        svc._shutdown_event = threading.Event()
        svc._wakeup_event = threading.Event()
        svc._monitor_core = None
        svc._engine_running = False
        svc._retry_policy = MonitoredPolicy()
        svc._runtime_config = RuntimeConfig()
        svc._runtime_snapshot = None
        svc._monitor_check_interval = 300
        svc._next_network_check = 0
        svc._scheduler_running = False
        svc._next_schedule_tick = 0.0
        svc._task_registry = MagicMock()
        svc._task_executor = MagicMock()
        svc._engine_thread = MagicMock()
        svc._engine_thread.is_alive.return_value = False
        svc._manual_login_in_progress = False
        svc._manual_login_lock = threading.Lock()
        svc._reload_lock = threading.Lock()
        svc._start_stop_lock = threading.Lock()
        svc._retry_time_lock = threading.Lock()
        svc._pure_mode = False
        svc._ws_manager = None
        svc._ws_broadcaster = MagicMock()
        svc._network_tester = MagicMock()
        svc._orchestrator = MagicMock()
        svc._login_history = None
        svc._worker_getter = None
        svc._profile_service = MagicMock()
        svc._profile_service.set_active_profile.return_value = (True, "ok")
        svc.project_root = MagicMock()
        svc.record_log = MagicMock()
        svc._update_status_snapshot = MagicMock()

        # StatusManager — 状态快照与广播
        svc._status_manager = StatusManager(
            get_monitor_core=lambda: svc._monitor_core,
            ws_broadcaster=svc._ws_broadcaster,
        )

        # LoginBridge — 登录委托
        from app.services.engine_login_bridge import LoginBridge
        svc._login_bridge = LoginBridge(
            get_orchestrator=lambda: svc._orchestrator,
            get_runtime_config=lambda: svc._runtime_config,
            retry_policy=svc._retry_policy,
            status_update_callback=svc._update_status_snapshot,
            record_log=svc.record_log,
            wakeup_event=svc._wakeup_event,
            get_monitor_check_interval=lambda: svc._monitor_check_interval,
        )
        # 桥接回调：模拟 engine 的 _bridge_retry_scheduled / _bridge_login_success / _bridge_retry_exhausted
        def _bridge_retry_scheduled(delay: float) -> None:
            with svc._retry_time_lock:
                svc._next_retry_time = time.time() + delay
            svc._wakeup_event.set()
        def _bridge_login_success() -> None:
            with svc._retry_time_lock:
                svc._next_retry_time = 0
        def _bridge_retry_exhausted() -> None:
            with svc._retry_time_lock:
                svc._next_retry_time = 0
        svc._login_bridge._on_retry_scheduled = _bridge_retry_scheduled
        svc._login_bridge._on_login_success = _bridge_login_success
        svc._login_bridge._on_retry_exhausted = _bridge_retry_exhausted
        svc._next_retry_time = 0

        return svc

    def factory(raw=False, **overrides):
        if raw:
            return _make_raw()
        return _make(**overrides)

    return factory
