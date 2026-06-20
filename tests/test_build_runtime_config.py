# tests/test_build_runtime_config.py
"""build_runtime_config 的单元测试。"""
from __future__ import annotations

from app.schemas import MonitorConfigPayload, SystemSettings


def _make_payload(**overrides) -> MonitorConfigPayload:
    defaults = {
        "username": "testuser",
        "password": "testpass",
        "auth_url": "https://auth.example.com",
        "carrier": "电信",
    }
    defaults.update(overrides)
    return MonitorConfigPayload(**defaults)


def _make_gs(**overrides) -> SystemSettings:
    return SystemSettings(**overrides)


def test_build_runtime_config_returns_runtime_config():
    from app.services.config_service import build_runtime_config
    from app.schemas import RuntimeConfig

    payload = _make_payload()
    gs = _make_gs()
    rc = build_runtime_config(payload, gs)
    assert isinstance(rc, RuntimeConfig)


def test_build_runtime_config_credentials():
    from app.services.config_service import build_runtime_config

    payload = _make_payload(carrier="自定义", carrier_custom="myisp")
    rc = build_runtime_config(payload, _make_gs())
    assert rc.credentials.username == "testuser"
    assert rc.credentials.password == "testpass"
    assert rc.credentials.auth_url == "https://auth.example.com"
    assert rc.credentials.isp == "myisp"
    assert rc.credentials.carrier_custom == "myisp"


def test_build_runtime_config_carrier_mapping():
    """carrier='无' -> isp='', carrier='电信' -> isp='电信'"""
    from app.services.config_service import build_runtime_config

    rc1 = build_runtime_config(_make_payload(carrier="无"), _make_gs())
    assert rc1.credentials.isp == ""

    rc2 = build_runtime_config(_make_payload(carrier="电信"), _make_gs())
    assert rc2.credentials.isp == "电信"


def test_build_runtime_config_browser_from_gs():
    from app.services.config_service import build_runtime_config

    gs = _make_gs(headless=False, browser_timeout=20)
    rc = build_runtime_config(_make_payload(), gs)
    assert rc.browser.headless is False
    assert rc.browser.timeout == 20


def test_build_runtime_config_monitor_fields():
    from app.services.config_service import build_runtime_config

    payload = _make_payload(check_interval_seconds=600, enable_tcp_check=True)
    rc = build_runtime_config(payload, _make_gs(network_check_timeout=5))
    assert rc.monitor.check_interval_seconds == 600
    assert rc.monitor.enable_tcp_check is True
    assert rc.monitor.network_check_timeout == 5


def test_build_runtime_config_passthrough_fields():
    from app.services.config_service import build_runtime_config

    payload = _make_payload(block_proxy=True, shell_path="/bin/bash")
    rc = build_runtime_config(payload, _make_gs())
    assert rc.block_proxy is True
    assert rc.shell_path == "/bin/bash"


def test_build_runtime_config_strip_fields():
    """proxy 和 browser_custom_path 应被 strip。"""
    from app.services.config_service import build_runtime_config

    gs = _make_gs(proxy="  http://proxy:8080  ", browser_custom_path="  /usr/bin/chrome  ")
    rc = build_runtime_config(_make_payload(), gs)
    assert rc.browser.browser_custom_path == "/usr/bin/chrome"
