"""backend/schemas.py — Pydantic 模型综合测试

在原测试基础上扩展，覆盖 ProfilesData, SystemSettings,
ActionResponse, MonitorStatusResponse 等模型。
"""
from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from backend.schemas import (
    MonitorConfigPayload,
    ProfileSettings,
    LogEntry,
    ProfilesData,
    SystemSettings,
    ActionResponse,
    MonitorStatusResponse,
    AutoStartStatusResponse,
)


# =====================================================================
# auth_url 验证器
# =====================================================================

class TestAuthUrlValidator:
    def test_valid_http(self):
        m = MonitorConfigPayload(auth_url="http://10.0.0.1/login")
        assert m.auth_url == "http://10.0.0.1/login"

    def test_valid_https(self):
        m = MonitorConfigPayload(auth_url="https://example.com/auth")
        assert m.auth_url == "https://example.com/auth"

    def test_empty_passes(self):
        m = MonitorConfigPayload(auth_url="")
        assert m.auth_url == ""

    def test_strips_whitespace(self):
        m = MonitorConfigPayload(auth_url="  http://example.com  ")
        assert m.auth_url == "http://example.com"

    def test_ftp_rejected(self):
        with pytest.raises(ValidationError, match="http"):
            MonitorConfigPayload(auth_url="ftp://files.example.com")

    def test_no_scheme_rejected(self):
        with pytest.raises(ValidationError, match="http"):
            MonitorConfigPayload(auth_url="example.com")

    def test_profile_settings_same_validator(self):
        p = ProfileSettings(auth_url="http://10.0.0.1")
        assert p.auth_url == "http://10.0.0.1"
        with pytest.raises(ValidationError, match="http"):
            ProfileSettings(auth_url="invalid")


# =====================================================================
# 浏览器请求头 JSON 验证器
# =====================================================================

class TestHeadersJsonValidator:
    def test_valid_json_object(self):
        m = MonitorConfigPayload(browser_extra_headers_json='{"X-Custom": "value"}')
        assert m.browser_extra_headers_json == '{"X-Custom": "value"}'

    def test_empty_string(self):
        m = MonitorConfigPayload(browser_extra_headers_json="")
        assert m.browser_extra_headers_json == ""

    def test_strips_whitespace(self):
        m = MonitorConfigPayload(browser_extra_headers_json='  {"k": "v"}  ')
        assert m.browser_extra_headers_json == '{"k": "v"}'

    def test_invalid_json(self):
        with pytest.raises(ValidationError, match="JSON"):
            MonitorConfigPayload(browser_extra_headers_json="not json")

    def test_json_array_rejected(self):
        with pytest.raises(ValidationError, match="JSON 对象"):
            MonitorConfigPayload(browser_extra_headers_json="[1, 2, 3]")


# =====================================================================
# 日志级别验证器
# =====================================================================

class TestLogLevelValidator:
    def test_valid_level(self):
        m = MonitorConfigPayload(backend_log_level="INFO")
        assert m.backend_log_level == "INFO"

    def test_case_insensitive(self):
        m = MonitorConfigPayload(backend_log_level="warning")
        assert m.backend_log_level == "WARNING"

    def test_strips_whitespace(self):
        m = MonitorConfigPayload(backend_log_level="  error  ")
        assert m.backend_log_level == "ERROR"

    def test_invalid_level(self):
        with pytest.raises(ValidationError, match="日志级别"):
            MonitorConfigPayload(backend_log_level="TRACE")

    def test_empty_passes(self):
        m = MonitorConfigPayload(backend_log_level="")
        assert m.backend_log_level == ""

    def test_frontend_log_level(self):
        m = MonitorConfigPayload(frontend_log_level="DEBUG")
        assert m.frontend_log_level == "DEBUG"


# =====================================================================
# 自定义变量验证器
# =====================================================================

class TestCustomVariablesValidator:
    def test_valid(self):
        m = MonitorConfigPayload(custom_variables={"key": "value"})
        assert m.custom_variables == {"key": "value"}

    def test_too_many_keys(self):
        vars_ = {f"var_{i}": "v" for i in range(51)}
        with pytest.raises(ValidationError, match="50"):
            MonitorConfigPayload(custom_variables=vars_)

    def test_key_too_long(self):
        with pytest.raises(ValidationError, match="100"):
            MonitorConfigPayload(custom_variables={"a" * 101: "v"})

    def test_value_too_long(self):
        with pytest.raises(ValidationError, match="10000"):
            MonitorConfigPayload(custom_variables={"k": "v" * 10001})

    def test_boundary_50_keys(self):
        vars_ = {f"var_{i}": "v" for i in range(50)}
        m = MonitorConfigPayload(custom_variables=vars_)
        assert len(m.custom_variables) == 50

    def test_empty_dict(self):
        m = MonitorConfigPayload(custom_variables={})
        assert m.custom_variables == {}


# =====================================================================
# 约束字段
# =====================================================================

class TestConstrainedFields:
    def test_browser_timeout_valid(self):
        m = MonitorConfigPayload(browser_timeout=5)
        assert m.browser_timeout == 5

    def test_browser_timeout_too_low(self):
        with pytest.raises(ValidationError):
            MonitorConfigPayload(browser_timeout=0)

    def test_browser_timeout_too_high(self):
        with pytest.raises(ValidationError):
            MonitorConfigPayload(browser_timeout=61)

    def test_app_port_valid(self):
        m = MonitorConfigPayload(app_port=8080)
        assert m.app_port == 8080

    def test_app_port_too_low(self):
        with pytest.raises(ValidationError):
            MonitorConfigPayload(app_port=1023)

    def test_app_port_too_high(self):
        with pytest.raises(ValidationError):
            MonitorConfigPayload(app_port=65536)

    def test_check_interval_boundary(self):
        m = MonitorConfigPayload(check_interval_seconds=10)
        assert m.check_interval_seconds == 10
        m2 = MonitorConfigPayload(check_interval_seconds=86400)
        assert m2.check_interval_seconds == 86400

    def test_pause_hours_boundary(self):
        m = MonitorConfigPayload(pause_start_hour=0, pause_end_hour=23)
        assert m.pause_start_hour == 0
        assert m.pause_end_hour == 23

    def test_login_timeout_valid(self):
        m = MonitorConfigPayload(login_timeout=120)
        assert m.login_timeout == 120

    def test_login_timeout_too_low(self):
        with pytest.raises(ValidationError):
            MonitorConfigPayload(login_timeout=5)

    def test_network_check_timeout_valid(self):
        m = MonitorConfigPayload(network_check_timeout=5)
        assert m.network_check_timeout == 5

    def test_network_check_timeout_too_high(self):
        with pytest.raises(ValidationError):
            MonitorConfigPayload(network_check_timeout=31)

    def test_browser_viewport_valid(self):
        m = MonitorConfigPayload(browser_viewport_width=1920, browser_viewport_height=1080)
        assert m.browser_viewport_width == 1920
        assert m.browser_viewport_height == 1080

    def test_browser_viewport_too_low(self):
        with pytest.raises(ValidationError):
            MonitorConfigPayload(browser_viewport_width=100)

    def test_browser_viewport_too_high(self):
        with pytest.raises(ValidationError):
            MonitorConfigPayload(browser_viewport_width=5000)


# =====================================================================
# LogEntry
# =====================================================================

class TestLogEntry:
    def test_valid_level(self):
        entry = LogEntry(timestamp="2025-01-01", level="WARNING", message="test")
        assert entry.level == "WARNING"

    def test_case_normalize(self):
        entry = LogEntry(timestamp="2025-01-01", level="error", message="test")
        assert entry.level == "ERROR"

    def test_invalid_level_defaults_to_info(self):
        entry = LogEntry(timestamp="2025-01-01", level="TRACE", message="test")
        assert entry.level == "INFO"

    def test_default_source(self):
        entry = LogEntry(timestamp="2025-01-01", message="test")
        assert entry.source == "monitor"

    def test_custom_source(self):
        entry = LogEntry(timestamp="2025-01-01", source="backend", message="test")
        assert entry.source == "backend"


# =====================================================================
# ProfileSettings
# =====================================================================

class TestProfileSettingsDefaults:
    def test_defaults(self):
        p = ProfileSettings()
        assert p.name == "默认方案"
        assert p.use_global_credentials is True
        assert p.headless is True
        assert p.check_interval_seconds == 300
        assert p.pause_enabled is True

    def test_custom_name(self):
        p = ProfileSettings(name="自定义方案")
        assert p.name == "自定义方案"

    def test_use_global_flags(self):
        p = ProfileSettings(
            use_global_credentials=False,
            use_global_advanced=False,
            use_global_auth_url=False,
            use_global_task=False,
        )
        assert p.use_global_credentials is False
        assert p.use_global_advanced is False
        assert p.use_global_auth_url is False
        assert p.use_global_task is False

    def test_match_fields(self):
        p = ProfileSettings(
            match_gateway_ip="10.0.0.1",
            match_ssid="CampusWiFi",
        )
        assert p.match_gateway_ip == "10.0.0.1"
        assert p.match_ssid == "CampusWiFi"


# =====================================================================
# SystemSettings
# =====================================================================

class TestSystemSettings:
    def test_defaults(self):
        s = SystemSettings()
        assert s.username == ""
        assert s.password == ""
        assert s.auth_url == ""
        assert s.backend_log_level == "INFO"
        assert s.frontend_log_level == "INFO"
        assert s.max_retries == 3
        assert s.retry_interval == 5
        assert s.app_port == 50721

    def test_pure_mode(self):
        s = SystemSettings(pure_mode=True)
        assert s.pure_mode is True

    def test_block_proxy(self):
        s = SystemSettings(block_proxy=False)
        assert s.block_proxy is False

    def test_log_level_validation(self):
        s = SystemSettings(backend_log_level="debug")
        assert s.backend_log_level == "DEBUG"

    def test_invalid_log_level(self):
        with pytest.raises(ValidationError):
            SystemSettings(backend_log_level="INVALID")


# =====================================================================
# ProfilesData
# =====================================================================

class TestProfilesData:
    def test_defaults(self):
        data = ProfilesData()
        assert data.auto_switch is False
        assert data.active_profile == "default"
        assert isinstance(data.system, SystemSettings)
        assert isinstance(data.profiles, dict)

    def test_with_profiles(self):
        data = ProfilesData(
            auto_switch=True,
            active_profile="campus",
            profiles={
                "default": ProfileSettings(name="默认"),
                "campus": ProfileSettings(name="校园"),
            },
        )
        assert data.auto_switch is True
        assert data.active_profile == "campus"
        assert len(data.profiles) == 2
        assert data.profiles["default"].name == "默认"

    def test_empty_profiles(self):
        data = ProfilesData(profiles={})
        assert len(data.profiles) == 0


# =====================================================================
# ActionResponse
# =====================================================================

class TestActionResponse:
    def test_success(self):
        r = ActionResponse(success=True, message="操作成功")
        assert r.success is True
        assert r.message == "操作成功"

    def test_failure(self):
        r = ActionResponse(success=False, message="操作失败")
        assert r.success is False
        assert r.message == "操作失败"


# =====================================================================
# MonitorStatusResponse
# =====================================================================

class TestMonitorStatusResponse:
    def test_defaults(self):
        r = MonitorStatusResponse(
            monitoring=False,
            network_check_count=0,
            login_attempt_count=0,
            last_check_time=None,
            runtime_seconds=0,
        )
        assert r.monitoring is False
        assert r.network_connected is False
        assert r.status_detail == "正常"
        assert r.network_state == "unknown"

    def test_active_monitoring(self):
        r = MonitorStatusResponse(
            monitoring=True,
            network_check_count=10,
            login_attempt_count=2,
            last_check_time="2025-01-01 12:00:00",
            runtime_seconds=3600,
            network_connected=True,
            status_detail="正常",
            network_state="connected",
        )
        assert r.monitoring is True
        assert r.network_check_count == 10
        assert r.network_connected is True


# =====================================================================
# AutoStartStatusResponse
# =====================================================================

class TestAutoStartStatusResponse:
    def test_basic(self):
        r = AutoStartStatusResponse(
            platform="windows",
            enabled=True,
            method="registry",
            location=r"HKCU\Software\Microsoft\Windows\CurrentVersion\Run",
        )
        assert r.platform == "windows"
        assert r.enabled is True
        assert r.method == "registry"

    def test_disabled(self):
        r = AutoStartStatusResponse(
            platform="linux",
            enabled=False,
            method="none",
            location="",
        )
        assert r.enabled is False


# =====================================================================
# MonitorConfigPayload — 完整构造
# =====================================================================

class TestMonitorConfigPayloadFull:
    def test_full_construct(self):
        """完整字段构造应成功"""
        m = MonitorConfigPayload(
            username="testuser",
            password="testpass",
            auth_url="http://10.0.0.1/login",
            check_interval_seconds=600,
            headless=False,
            browser_timeout=10,
            pause_enabled=False,
            enable_tcp_check=True,
            enable_http_check=False,
            custom_variables={"KEY": "VAL"},
        )
        assert m.username == "testuser"
        assert m.check_interval_seconds == 600
        assert m.headless is False
        assert m.enable_http_check is False
        assert m.custom_variables == {"KEY": "VAL"}

    def test_default_construct(self):
        """默认构造应成功"""
        m = MonitorConfigPayload()
        assert m.username == ""
        assert m.auth_url == ""
        assert m.headless is True
        assert m.enable_tcp_check is True
        assert m.enable_http_check is True

    def test_carrier_fields(self):
        m = MonitorConfigPayload(carrier="自定义", carrier_custom="校园网")
        assert m.carrier == "自定义"
        assert m.carrier_custom == "校园网"
