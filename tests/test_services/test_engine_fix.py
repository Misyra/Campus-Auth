"""测试引擎网络检测的默认配置一致性 & TOCTOU 竞态修复 & F06 手动取消竞态窗口。"""

import inspect
import queue
import threading
from unittest.mock import MagicMock, patch


def test_engine_test_network_default_false():
    """test_network 的 enable_tcp_check / enable_http_check 默认值应为 False。"""
    from app.schemas import _MonitorFieldsMixin

    # 获取 schema 权威默认值
    field_info_tcp = _MonitorFieldsMixin.model_fields["enable_tcp_check"]
    field_info_http = _MonitorFieldsMixin.model_fields["enable_http_check"]
    assert field_info_tcp.default is False
    assert field_info_http.default is False

    # test_network 中的 fallback 应与 schema 一致
    from app.services.engine import ScheduleEngine

    source = inspect.getsource(ScheduleEngine.test_network)
    # 不应出现默认值 True
    assert 'enable_tcp_check", True' not in source
    assert 'enable_http_check", True' not in source

    # init_monitoring 中的 fallback 也应与 schema 一致
    from app.services.monitor_service import NetworkMonitorCore

    source_monitor = inspect.getsource(NetworkMonitorCore.init_monitoring)
    assert 'enable_tcp_check", True' not in source_monitor
    assert 'enable_http_check", True' not in source_monitor


def test_handle_login_uses_validated_config():
    """_handle_login 应将校验通过的配置传递给 _do_async_login，避免二次读取。"""
    from app.services.engine import EngineCmdType, EngineCommand, ScheduleEngine

    engine = ScheduleEngine.__new__(ScheduleEngine)
    engine._command_queue = queue.Queue()

    # 模拟配置快照
    snapshot = {"username": "u", "password": "p", "auth_url": "http://x"}

    engine._copy_runtime_config = MagicMock(return_value=snapshot)
    engine._orchestrator = MagicMock()
    engine._orchestrator.validate.return_value = None
    engine._do_async_login = MagicMock(return_value=True)

    cmd = EngineCommand(type=EngineCmdType.LOGIN, data={})
    engine._handle_login(cmd)

    # _do_async_login 应收到 config_snapshot 参数
    engine._do_async_login.assert_called_once_with(
        is_manual=True, config_snapshot=snapshot,
    )


# =====================================================================
# F06 — 手动取消竞态窗口修复
# =====================================================================


class TestManualLoginCancelRaceFix:
    """F06: 手动登录委托 orchestrator 处理取消与抢占。"""

    def _make_engine(self):
        """构造一个最小化的 engine 用于测试。"""
        from app.services.engine import ScheduleEngine

        engine = ScheduleEngine.__new__(ScheduleEngine)
        engine._task_executor = MagicMock()
        engine._update_status_snapshot = MagicMock()
        engine._copy_runtime_config = MagicMock(
            return_value={"username": "u", "password": "p", "auth_url": "http://x"}
        )
        engine._orchestrator = MagicMock()
        engine._login_history = MagicMock()
        engine._ui_config = MagicMock()
        engine._ui_config.login_timeout = 30
        engine._consecutive_login_failures = 0
        engine._backoff_check_multiplier = 1
        engine._login_retry_max_cycles = MagicMock(return_value=3)
        engine._apply_backoff_interval = MagicMock()
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
        engine._orchestrator.submit.assert_called_once_with(
            source="manual", config=engine._copy_runtime_config()
        )

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
        engine._orchestrator.submit.assert_called_once_with(
            source="auto", config=engine._copy_runtime_config()
        )

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
