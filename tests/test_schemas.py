"""backend/schemas.py — Pydantic 模型验证测试"""
from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from backend.schemas import (
    MonitorConfigPayload,
    ProfileSettings,
    LogEntry,
)


class TestAuthUrlValidator:
    """validate_auth_url 在 MonitorConfigPayload 和 ProfileSettings 中共享"""

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


class TestConstrainedFields:
    def test_browser_timeout_valid(self):
        m = MonitorConfigPayload(browser_timeout=5000)
        assert m.browser_timeout == 5000

    def test_browser_timeout_too_low(self):
        with pytest.raises(ValidationError):
            MonitorConfigPayload(browser_timeout=999)

    def test_browser_timeout_too_high(self):
        with pytest.raises(ValidationError):
            MonitorConfigPayload(browser_timeout=60001)

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


class TestProfileSettingsDefaults:
    def test_defaults(self):
        p = ProfileSettings()
        assert p.name == "默认方案"
        assert p.use_global_credentials is True
        assert p.headless is True
        assert p.check_interval_seconds == 300
        assert p.pause_enabled is True
