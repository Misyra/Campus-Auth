"""测试引擎网络检测的默认配置一致性 & TOCTOU 竞态修复 & F06 手动取消竞态窗口。"""

import inspect
import queue
import threading
from unittest.mock import MagicMock, patch

from app.schemas import LoginCredentials, RuntimeConfig


def test_engine_test_network_default_true():
    """test_network 的 enable_tcp_check / enable_http_check 默认值应为 True。"""
    from app.schemas import MonitorSettings

    # 获取 schema 权威默认值
    field_info_tcp = MonitorSettings.model_fields["enable_tcp_check"]
    field_info_http = MonitorSettings.model_fields["enable_http_check"]
    assert field_info_tcp.default is True
    assert field_info_http.default is True

    # test_network 中不应有 fallback 默认值（现在通过 RuntimeConfig 属性访问）
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
    engine._ui_config = MagicMock()
    engine._ui_config.browser.login_timeout = 30
    engine._orchestrator = MagicMock()
    engine._orchestrator.validate.return_value = None
    mock_handle = MagicMock()
    mock_handle.rejected_reason = None
    mock_handle.future = MagicMock()
    mock_handle.result.return_value = (True, "登录成功")
    engine._orchestrator.submit.return_value = mock_handle

    cmd = EngineCommand(type=EngineCmdType.LOGIN, data={})
    engine._handle_login(cmd)

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
        engine._ui_config = MagicMock()
        engine._ui_config.browser.login_timeout = 30
        engine._registered_futures = set()
        engine._futures_lock = threading.Lock()
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
