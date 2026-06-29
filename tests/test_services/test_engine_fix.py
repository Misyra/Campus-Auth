"""测试引擎网络检测的默认配置一致性 & TOCTOU 竞态修复 & F06 手动取消竞态窗口。"""

import inspect
import queue
import threading
import time
from unittest.mock import MagicMock, patch

from app.schemas import LoginCredentials, RuntimeConfig


def test_engine_test_network_default_false():
    """test_network 的 enable_tcp_check / enable_http_check 默认值应为 False。"""
    from app.schemas import MonitorSettings

    # 获取 schema 权威默认值
    field_info_tcp = MonitorSettings.model_fields["enable_tcp_check"]
    field_info_http = MonitorSettings.model_fields["enable_http_check"]
    assert field_info_tcp.default is False
    assert field_info_http.default is False

    # test_network 中不应有 fallback 默认值（通过 RuntimeConfig 属性访问）
    from app.services.engine import ScheduleEngine

    source = inspect.getsource(ScheduleEngine.test_network)
    # 不应出现 .get() 调用（已迁移到属性访问）
    assert '.get(' not in source


def test_handle_login_uses_validated_config():
    """_handle_login 应将校验通过的配置传递给 orchestrator.submit。"""
    from app.services.engine import EngineCmdType, EngineCommand, ScheduleEngine

    engine = ScheduleEngine.__new__(ScheduleEngine)
    engine._command_queue = queue.Queue()

    # 模拟配置
    engine._runtime_config = RuntimeConfig(
        credentials=LoginCredentials(
            username="u", password="p", auth_url="http://x",
        ),
    )
    engine._orchestrator = MagicMock()
    engine._orchestrator.validate.return_value = None
    mock_handle = MagicMock()
    mock_handle.rejected_reason = None
    from concurrent.futures import Future
    mock_future = Future()
    mock_handle.future = mock_future
    engine._orchestrator.submit.return_value = mock_handle

    cmd = EngineCommand(type=EngineCmdType.LOGIN, data={}, response_event=threading.Event())
    engine._handle_login(cmd)
    # 异步模式：模拟登录完成，触发回调
    mock_future.set_result((True, "登录成功"))
    cmd.response_event.wait(timeout=2)

    # orchestrator.submit 应收到正确的 source 和 config（RuntimeConfig 格式）
    submitted_config = engine._orchestrator.submit.call_args[1]["config"]
    assert isinstance(submitted_config, RuntimeConfig)
    assert submitted_config.credentials.username == "u"
    assert submitted_config.credentials.password == "p"
    assert submitted_config.credentials.auth_url == "http://x"
    assert cmd.response_data == (True, "登录成功")


# =====================================================================
# F06 — 手动取消竞态窗口修复
# =====================================================================


class TestManualLoginCancelRaceFix:
    """F06: 手动登录委托 orchestrator 处理取消与抢占。"""

    def _make_engine(self):
        """构造一个最小化的 engine 用于测试。"""
        import threading

        from app.services.engine import ScheduleEngine
        from app.services.engine_login_bridge import LoginBridge
        from app.services.retry_policy import MonitoredPolicy

        engine = ScheduleEngine.__new__(ScheduleEngine)
        engine._task_executor = MagicMock()
        engine._update_status_snapshot = MagicMock()
        engine._runtime_config = RuntimeConfig(
            credentials=LoginCredentials(
                username="u", password="p", auth_url="http://x",
            ),
        )
        engine._orchestrator = MagicMock()
        engine._login_history = MagicMock()
        engine._wakeup_event = threading.Event()
        engine._retry_policy = MonitoredPolicy()
        engine._monitor_check_interval = 300
        engine.record_log = MagicMock()
        engine._login_bridge = LoginBridge(
            get_orchestrator=lambda: engine._orchestrator,
            get_runtime_config=lambda: engine._runtime_config,
            retry_policy=engine._retry_policy,
            status_update_callback=engine._update_status_snapshot,
            record_log=engine.record_log,
            wakeup_event=engine._wakeup_event,
            get_monitor_check_interval=lambda: engine._monitor_check_interval,
        )
        engine._retry_time_lock = threading.Lock()
        def _bridge_retry_scheduled(delay: float) -> None:
            with engine._retry_time_lock:
                engine._next_retry_time = time.time() + delay
            engine._wakeup_event.set()
        def _bridge_login_success() -> None:
            with engine._retry_time_lock:
                engine._next_retry_time = 0
        def _bridge_retry_exhausted() -> None:
            with engine._retry_time_lock:
                engine._next_retry_time = 0
        engine._login_bridge._on_retry_scheduled = _bridge_retry_scheduled
        engine._login_bridge._on_login_success = _bridge_login_success
        engine._login_bridge._on_retry_exhausted = _bridge_retry_exhausted
        engine._next_retry_time = 0
        return engine

    def test_manual_login_submits_to_orchestrator(self):
        """手动登录应通过 orchestrator.submit(source='manual') 提交。"""
        from concurrent.futures import Future

        engine = self._make_engine()
        future = Future()
        handle = MagicMock()
        handle.rejected_reason = None
        handle.future = future
        engine._orchestrator.submit.return_value = handle

        result = engine._do_async_login(is_manual=True)

        assert result is True
        call_kwargs = engine._orchestrator.submit.call_args[1]
        assert call_kwargs["source"] == "manual"
        assert isinstance(call_kwargs["config"], RuntimeConfig)
        assert call_kwargs["config"].credentials.username == "u"

    def test_auto_login_submits_to_orchestrator(self):
        """自动登录应通过 orchestrator.submit(source='auto') 提交。"""
        from concurrent.futures import Future

        engine = self._make_engine()
        future = Future()
        handle = MagicMock()
        handle.rejected_reason = None
        handle.future = future
        engine._orchestrator.submit.return_value = handle

        result = engine._do_async_login(is_manual=False)

        assert result is True
        call_kwargs = engine._orchestrator.submit.call_args[1]
        assert call_kwargs["source"] == "auto"
        assert isinstance(call_kwargs["config"], RuntimeConfig)
        assert call_kwargs["config"].credentials.username == "u"

    def test_rejected_handle_returns_false(self):
        """orchestrator 返回 rejected handle 时应返回 False。"""
        engine = self._make_engine()
        handle = MagicMock()
        handle.rejected_reason = "登录配置不完整"
        handle.future = None
        engine._orchestrator.submit.return_value = handle

        result = engine._do_async_login(is_manual=False)

        assert result is False

    def test_dedup_handle_returns_false(self):
        """orchestrator 返回去重 handle（future=None）时应返回 False。"""
        engine = self._make_engine()
        handle = MagicMock()
        handle.rejected_reason = None
        handle.future = None
        engine._orchestrator.submit.return_value = handle

        result = engine._do_async_login(is_manual=False)

        assert result is False
