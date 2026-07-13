"""test_services 共享 fixture — 统一 ScheduleEngine 工厂。"""

from __future__ import annotations

import asyncio
import threading
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.schemas import RuntimeConfig
from app.services.config_service import ConfigService
from app.services.engine import ScheduleEngine, StatusManager


def _make_mock_config_service(
    *, runtime_config: RuntimeConfig | None = None, pure_mode: bool = False
) -> MagicMock:
    """创建 mock ConfigService，返回默认 RuntimeConfig。"""
    mock_cs = MagicMock(spec=ConfigService)
    mock_cs.get_runtime_config.return_value = runtime_config or RuntimeConfig()
    mock_cs.pure_mode = pure_mode
    mock_cs.reload.return_value = True
    mock_cs.toggle_pure_mode.return_value = True
    return mock_cs


@pytest.fixture
def engine_factory():
    """创建带有 mock 依赖的 ScheduleEngine 实例。

    提供两种模式：
    - engine_factory(): 标准初始化（启动后停止引擎线程）
    - engine_factory(raw=True): 使用 __new__ 跳过 __init__，用于单元隔离测试

    所有模式都注入 mock config_service。
    """

    def _make(**overrides):
        """标准模式：完整初始化后停止引擎线程。"""

        with patch("app.services.engine.ProfileService") as mock_ps_cls:
            mock_ps = MagicMock()
            mock_ps_cls.return_value = mock_ps

            # 确保 task_executor 有默认值
            if "task_executor" not in overrides:
                overrides["task_executor"] = MagicMock()
            if "profile_service" not in overrides:
                overrides["profile_service"] = mock_ps
            if "config_service" not in overrides:
                overrides["config_service"] = _make_mock_config_service()

            svc = ScheduleEngine.__new__(ScheduleEngine)
            ScheduleEngine.__init__(svc, MagicMock(), **overrides)
            svc._shutdown_event.set()
            if svc._engine_thread and svc._engine_thread.is_alive():
                svc._engine_thread.join(timeout=1)
            return svc

    def _make_raw():
        """原始模式：跳过 __init__，手动设置所有属性。"""
        svc = ScheduleEngine.__new__(ScheduleEngine)
        svc._cmd_queue = asyncio.Queue(maxsize=50)
        svc._shutdown_event = threading.Event()
        svc._engine_loop = None
        svc._engine_thread = None
        svc._engine_running = False
        svc._engine_ready = threading.Event()
        svc._monitor_core = None
        svc._config_service = _make_mock_config_service()
        svc._monitor_check_interval = 300
        svc._next_network_check = 0
        svc._scheduler = MagicMock()
        svc._scheduler.running = False
        svc._scheduler.next_tick_time = 0.0
        svc._scheduler.has_enabled_tasks.return_value = False
        svc._task_registry = MagicMock()
        svc._task_executor = MagicMock()
        svc._manual_login_in_progress = False
        svc._manual_login_lock = threading.Lock()
        svc._start_stop_lock = threading.Lock()
        svc._ws_manager = MagicMock()
        svc._orchestrator = MagicMock()
        svc._profile_service = MagicMock()
        svc._profile_service.set_active_profile.return_value = (True, "ok")
        svc.project_root = MagicMock()
        svc._logger = MagicMock()
        svc._update_status_snapshot = ScheduleEngine._update_status_snapshot.__get__(
            svc
        )

        # StatusManager — 状态快照与广播
        svc._status_manager = StatusManager(
            get_monitor_core=lambda: svc._monitor_core,
            ws_manager=svc._ws_manager,
        )

        # LoginBridge — 使用 AsyncMock 解耦内部实现（submit_login 已改 async）
        svc._login_bridge = AsyncMock()

        def _fake_submit_login(is_manual=False, config_snapshot=None, on_complete=None):
            """模拟 LoginBridge.submit_login：委托 orchestrator 并调用 on_complete。"""
            orchestrator = svc._orchestrator
            config = (
                config_snapshot
                if config_snapshot is not None
                else svc._config_service.get_runtime_config()
            )
            source = "manual" if is_manual else "auto"
            handle = orchestrator.submit(source=source, config=config)
            if handle.rejected_reason is not None:
                if on_complete is not None:
                    on_complete(False, handle.rejected_reason)
                return False
            if handle.future is None:
                if on_complete is not None:
                    on_complete(False, "登录任务已在执行中，请稍后再试")
                return False

            def _on_done(f):
                try:
                    ok, msg = f.result()
                except Exception as exc:
                    ok, msg = False, str(exc)
                if on_complete is not None:
                    on_complete(ok, msg)

            handle.future.add_done_callback(_on_done)
            return True

        svc._login_bridge.submit_login.side_effect = _fake_submit_login
        svc._login_bridge.cancel_login.return_value = (True, "登录已取消")

        return svc

    def factory(raw=False, **overrides):
        if raw:
            return _make_raw()
        return _make(**overrides)

    return factory
