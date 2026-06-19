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
    """_handle_login 应将校验通过的配置传递给 executor，避免二次读取。"""
    from app.services.engine import EngineCmdType, EngineCommand, ScheduleEngine

    engine = ScheduleEngine.__new__(ScheduleEngine)
    engine._command_queue = queue.Queue()

    # 模拟配置快照
    snapshot = {"username": "u", "password": "p", "auth_url": "http://x"}

    engine._copy_runtime_config = MagicMock(return_value=snapshot)
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
    """F06: 手动取消超时后，应强制清理旧槽并提交新登录。"""

    def _make_engine(self):
        """构造一个最小化的 engine 用于测试。"""
        from app.services.engine import ScheduleEngine

        engine = ScheduleEngine.__new__(ScheduleEngine)
        engine._task_executor = MagicMock()
        engine._login_retry = MagicMock()
        engine._login_retry.reset = MagicMock()
        engine._update_status_snapshot = MagicMock()
        engine._validate_login_config = MagicMock(return_value=None)
        engine._copy_runtime_config = MagicMock(
            return_value={"username": "u", "password": "p", "auth_url": "http://x"}
        )
        engine._login_history = MagicMock()
        engine._ui_config = MagicMock()
        engine._ui_config.login_timeout = 30
        engine._consecutive_login_failures = 0
        engine._backoff_check_multiplier = 1
        engine._login_retry_max_cycles = MagicMock(return_value=3)
        engine._apply_backoff_interval = MagicMock()
        return engine

    def test_manual_login_force_clear_on_timeout(self):
        """取消超时后应调用 force_clear_login_slot 并提交新 future。"""
        from concurrent.futures import Future

        engine = self._make_engine()

        # is_login_running 先返回 True（取消前），然后 True（取消后超时），然后 False（force_clear 后）
        call_count = [0]

        def fake_is_running():
            call_count[0] += 1
            # 第1次: is_login_running 检查（进入 if）
            # 第2次: while 循环条件（超时后仍为 True）
            # 第3次: 超时后 if 检查（为 True，触发 force_clear）
            if call_count[0] <= 3:
                return True
            # 之后 force_clear 已执行，新 future 提交后返回 False
            return False

        engine._task_executor.is_login_running = fake_is_running
        engine._task_executor.cancel_login = MagicMock()

        new_future = Future()
        new_future.set_result((True, "ok"))
        engine._task_executor.execute_login_async = MagicMock(return_value=new_future)

        # 模拟 time.time 让 deadline 立即超时
        times = [0, 100, 200]  # start, check1(超时), check2(超时)
        time_iter = iter(times)

        with patch("app.services.engine.time") as mock_time:
            mock_time.time = MagicMock(side_effect=lambda: next(time_iter))
            mock_time.sleep = MagicMock()
            result = engine._do_async_login(is_manual=True)

        assert result is True
        engine._task_executor.cancel_login.assert_called_once()
        engine._task_executor.force_clear_login_slot.assert_called_once()
        # 验证传入了新的 cancel_event
        call_kwargs = engine._task_executor.execute_login_async.call_args
        assert call_kwargs.kwargs["cancel_event"] is not None
        assert isinstance(call_kwargs.kwargs["cancel_event"], threading.Event)
        assert call_kwargs.kwargs["config_snapshot"] is not None

    def test_manual_login_no_force_clear_when_cancel_succeeds(self):
        """取消成功（未超时）时不应调用 force_clear_login_slot。"""
        from concurrent.futures import Future

        engine = self._make_engine()

        # is_login_running: True（初始）-> False（取消后）
        call_count = [0]

        def fake_is_running():
            call_count[0] += 1
            return call_count[0] <= 1

        engine._task_executor.is_login_running = fake_is_running
        engine._task_executor.cancel_login = MagicMock()

        new_future = Future()
        new_future.set_result((True, "ok"))
        engine._task_executor.execute_login_async = MagicMock(return_value=new_future)

        with patch("app.services.engine.time") as mock_time:
            mock_time.time = MagicMock(return_value=0)
            mock_time.sleep = MagicMock()
            result = engine._do_async_login(is_manual=True)

        assert result is True
        engine._task_executor.cancel_login.assert_called_once()
        engine._task_executor.force_clear_login_slot.assert_not_called()

    def test_auto_login_no_force_clear(self):
        """自动登录路径不应触发 force_clear。"""
        from concurrent.futures import Future

        engine = self._make_engine()
        engine._task_executor.is_login_running = MagicMock(return_value=True)
        engine._task_executor.cancel_login = MagicMock()
        engine._task_executor.force_clear_login_slot = MagicMock()

        result = engine._do_async_login(is_manual=False)

        assert result is False
        engine._task_executor.cancel_login.assert_not_called()
        engine._task_executor.force_clear_login_slot.assert_not_called()

    def test_manual_login_passes_cancel_event(self):
        """手动登录应显式传入 cancel_event。"""
        from concurrent.futures import Future

        engine = self._make_engine()
        engine._task_executor.is_login_running = MagicMock(return_value=False)

        new_future = Future()
        new_future.set_result((True, "ok"))
        engine._task_executor.execute_login_async = MagicMock(return_value=new_future)

        result = engine._do_async_login(is_manual=True)

        assert result is True
        call_kwargs = engine._task_executor.execute_login_async.call_args
        cancel = call_kwargs.kwargs["cancel_event"]
        assert isinstance(cancel, threading.Event)

    def test_auto_login_no_cancel_event(self):
        """自动登录路径不应传入 cancel_event。"""
        from concurrent.futures import Future

        engine = self._make_engine()
        engine._task_executor.is_login_running = MagicMock(return_value=False)

        new_future = Future()
        new_future.set_result((True, "ok"))
        engine._task_executor.execute_login_async = MagicMock(return_value=new_future)

        result = engine._do_async_login(is_manual=False)

        assert result is True
        call_kwargs = engine._task_executor.execute_login_async.call_args
        cancel = call_kwargs.kwargs["cancel_event"]
        assert cancel is None
