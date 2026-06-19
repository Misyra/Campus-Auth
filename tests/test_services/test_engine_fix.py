"""测试引擎网络检测的默认配置一致性 & TOCTOU 竞态修复。"""

import inspect
import queue
from unittest.mock import MagicMock


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
