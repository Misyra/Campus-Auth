"""test_services 共享 fixture — 统一 ScheduleEngine 工厂。"""

from __future__ import annotations

import queue
import threading
from unittest.mock import MagicMock, patch

import pytest

from app.services.engine import ScheduleEngine, StatusSnapshot
from app.services.retry_policy import MonitoredPolicy


@pytest.fixture
def engine_factory():
    """创建带有 mock 依赖的 ScheduleEngine 实例。

    提供两种模式：
    - engine_factory(): 标准初始化（启动后停止引擎线程）
    - engine_factory(raw=True): 使用 __new__ 跳过 __init__，用于单元隔离测试

    所有模式都 patch 相同的 4 个依赖：
    - config_service.build_runtime_dict_from_payload
    - runtime_config.load_runtime_config
    - runtime_config.load_ui_config
    - engine.ProfileService
    """

    def _make(**overrides):
        """标准模式：完整初始化后停止引擎线程。"""
        with (
            patch("app.services.config_service.build_runtime_dict_from_payload", return_value={}),
            patch(
                "app.services.runtime_config.load_runtime_config",
                return_value=(MagicMock(), False),
            ),
            patch("app.services.runtime_config.load_ui_config") as mock_load_ui,
            patch("app.services.engine.ProfileService") as mock_ps_cls,
        ):
            mock_ps = MagicMock()
            mock_ps_cls.return_value = mock_ps
            mock_ps.load.return_value.global_settings.pure_mode = False
            mock_load_ui.return_value = MagicMock()

            # 确保 task_executor 有默认值
            if "task_executor" not in overrides:
                overrides["task_executor"] = MagicMock()

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
        svc._monitor_core = None
        svc._engine_running = False
        svc._retry_policy = MonitoredPolicy()
        svc._runtime_config = {}
        svc._runtime_snapshot = {}
        svc._monitor_check_interval = 300
        svc._next_network_check = 0
        svc._scheduler_running = False
        svc._next_schedule_tick = 0.0
        svc._task_registry = MagicMock()
        svc._task_executor = MagicMock()
        svc._status_snapshot = StatusSnapshot()
        svc._snapshot_min_interval = 1.0
        svc._last_snapshot_time = 0
        svc._engine_thread = MagicMock()
        svc._engine_thread.is_alive.return_value = False
        svc._manual_login_in_progress = False
        svc._manual_login_lock = threading.Lock()
        svc._reload_lock = threading.Lock()
        svc._pure_mode_lock = threading.Lock()
        svc._start_stop_lock = threading.Lock()
        svc._pure_mode = False
        svc._dashboard_sink = None
        from collections import deque
        svc._empty_broadcast_queue = deque(maxlen=10)
        svc._ws_manager = None
        svc._ui_config = MagicMock()
        svc._ui_config.login_timeout = 120
        svc._orchestrator = MagicMock()
        svc._login_history = None
        svc._worker_getter = None
        svc._profile_service = MagicMock()
        svc.project_root = MagicMock()
        svc.record_log = MagicMock()
        svc._update_status_snapshot = MagicMock()
        return svc

    def factory(raw=False, **overrides):
        if raw:
            return _make_raw()
        return _make(**overrides)

    return factory
