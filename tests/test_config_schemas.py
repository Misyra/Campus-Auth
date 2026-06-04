"""配置与数据模型综合测试

合并原 test_config.py 和 test_schemas.py。
覆盖 ConfigValidator、config_service 工具函数、Pydantic 模型等。
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from src.utils.config import ConfigValidator
from backend.config_service import (
    _safe_decrypt,
    _normalize_level,
    _normalize_targets,
    _normalize_headers_json,
)
from src.utils.crypto import encrypt_password
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
# 第一部分：ConfigValidator（原 test_config.py 前半部分）
# =====================================================================

class TestValidateGuiConfig:
    def test_valid_config(self):
        ok, msg = ConfigValidator.validate_gui_config(
            username="testuser",
            password="testpass",
            check_interval="5",
        )
        assert ok is True
        assert msg == ""

    def test_empty_username(self):
        ok, msg = ConfigValidator.validate_gui_config(
            username="", password="pass", check_interval="5"
        )
        assert ok is False
        assert "账号" in msg

    def test_masked_password_accepted(self):
        ok, msg = ConfigValidator.validate_gui_config(
            username="testuser",
            password="••••••••",
            check_interval="5",
        )
        assert ok is True

    def test_empty_password_without_mask(self):
        ok, msg = ConfigValidator.validate_gui_config(
            username="testuser", password="", check_interval="5"
        )
        assert ok is False
        assert "密码" in msg

    def test_invalid_interval(self):
        ok, msg = ConfigValidator.validate_gui_config(
            username="testuser", password="testpass", check_interval="abc"
        )
        assert ok is False
        assert "间隔" in msg

    def test_interval_too_large(self):
        ok, msg = ConfigValidator.validate_gui_config(
            username="testuser", password="testpass", check_interval="90000"
        )
        assert ok is False

    def test_interval_zero(self):
        ok, msg = ConfigValidator.validate_gui_config(
            username="testuser", password="testpass", check_interval="0"
        )
        assert ok is False

    def test_interval_negative(self):
        ok, msg = ConfigValidator.validate_gui_config(
            username="testuser", password="testpass", check_interval="-5"
        )
        assert ok is False

    def test_short_username(self):
        ok, msg = ConfigValidator.validate_gui_config(
            username="a", password="testpass", check_interval="5"
        )
        assert ok is False
        assert "账号" in msg

    def test_short_password(self):
        ok, msg = ConfigValidator.validate_gui_config(
            username="testuser", password="a", check_interval="5"
        )
        assert ok is False
        assert "密码" in msg

    def test_masked_short_password_accepted(self):
        """掩码密码即使长度短也应被接受"""
        ok, msg = ConfigValidator.validate_gui_config(
            username="testuser", password="••", check_interval="5"
        )
        assert ok is True


class TestValidateEnvConfig:
    def test_valid_config(self):
        ok, msg = ConfigValidator.validate_env_config({
            "username": "testuser",
            "password": "testpass",
            "auth_url": "http://10.0.0.1",
        })
        assert ok is True

    def test_missing_username(self):
        ok, msg = ConfigValidator.validate_env_config({
            "username": "",
            "password": "pass",
            "auth_url": "http://10.0.0.1",
        })
        assert ok is False

    def test_missing_auth_url(self):
        ok, msg = ConfigValidator.validate_env_config({
            "username": "user",
            "password": "pass",
            "auth_url": "",
        })
        assert ok is False

    def test_missing_password(self):
        ok, msg = ConfigValidator.validate_env_config({
            "username": "user",
            "password": "",
            "auth_url": "http://10.0.0.1",
        })
        assert ok is False

    def test_all_empty(self):
        ok, msg = ConfigValidator.validate_env_config({
            "username": "",
            "password": "",
            "auth_url": "",
        })
        assert ok is False

    def test_none_values(self):
        ok, msg = ConfigValidator.validate_env_config({
            "username": None,
            "password": None,
            "auth_url": None,
        })
        assert ok is False


# =====================================================================
# 第二部分：config_service 工具函数（原 test_config.py 后半部分）
# =====================================================================

class TestSafeDecrypt:
    def test_decrypt_encrypted_value(self):
        """应能解密 ENC: 前缀的值"""
        encrypted = encrypt_password("test123")
        result, has_error = _safe_decrypt(encrypted)
        assert result == "test123"
        assert has_error is False

    def test_decrypt_empty_string(self):
        """空字符串应返回空字符串"""
        result, has_error = _safe_decrypt("")
        assert result == ""
        assert has_error is False

    def test_decrypt_plaintext_passthrough(self):
        """无 ENC: 前缀的明文应原样返回"""
        result, has_error = _safe_decrypt("plaintext")
        assert result == "plaintext"
        assert has_error is False


class TestNormalizeLevelService:
    def test_valid_levels(self):
        assert _normalize_level("DEBUG") == "DEBUG"
        assert _normalize_level("INFO") == "INFO"
        assert _normalize_level("WARNING") == "WARNING"
        assert _normalize_level("ERROR") == "ERROR"
        assert _normalize_level("CRITICAL") == "CRITICAL"

    def test_case_insensitive(self):
        assert _normalize_level("debug") == "DEBUG"
        assert _normalize_level("info") == "INFO"

    def test_strips_whitespace(self):
        assert _normalize_level("  ERROR  ") == "ERROR"

    def test_invalid_returns_default(self):
        assert _normalize_level("TRACE") == "WARNING"
        assert _normalize_level("INVALID") == "WARNING"

    def test_empty_returns_default(self):
        assert _normalize_level("") == "WARNING"
        assert _normalize_level(None) == "WARNING"

    def test_custom_default(self):
        assert _normalize_level("INVALID", default="ERROR") == "ERROR"

    def test_valid_with_custom_default(self):
        assert _normalize_level("DEBUG", default="ERROR") == "DEBUG"


class TestNormalizeTargets:
    def test_valid_targets(self):
        result = _normalize_targets("8.8.8.8:53,1.1.1.1:443")
        assert result == "8.8.8.8:53,1.1.1.1:443"

    def test_empty_returns_default(self):
        result = _normalize_targets("")
        assert "8.8.8.8:53" in result
        assert "114.114.114.114:53" in result

    def test_none_returns_default(self):
        result = _normalize_targets(None)
        assert "8.8.8.8:53" in result

    def test_whitespace_trimming(self):
        result = _normalize_targets("  8.8.8.8:53  ,  1.1.1.1:443  ")
        assert result == "8.8.8.8:53,1.1.1.1:443"

    def test_empty_items_filtered(self):
        result = _normalize_targets("8.8.8.8:53,,,1.1.1.1:443,")
        assert result == "8.8.8.8:53,1.1.1.1:443"

    def test_single_target(self):
        result = _normalize_targets("10.0.0.1:8080")
        assert result == "10.0.0.1:8080"


class TestNormalizeHeadersJson:
    def test_valid_json_object(self):
        result = _normalize_headers_json('{"X-Custom": "value"}')
        assert result == '{"X-Custom":"value"}'

    def test_empty_string(self):
        assert _normalize_headers_json("") == ""

    def test_none(self):
        assert _normalize_headers_json(None) == ""

    def test_whitespace_strips(self):
        result = _normalize_headers_json('  {"k": "v"}  ')
        assert result == '{"k":"v"}'

    def test_invalid_json_raises(self):
        with pytest.raises(ValueError, match="JSON"):
            _normalize_headers_json("not json")

    def test_json_array_raises(self):
        with pytest.raises(ValueError, match="JSON 对象"):
            _normalize_headers_json("[1, 2, 3]")

    def test_json_string_raises(self):
        with pytest.raises(ValueError, match="JSON 对象"):
            _normalize_headers_json('"just a string"')

    def test_preserves_unicode(self):
        result = _normalize_headers_json('{"中文": "值"}')
        parsed = json.loads(result)
        assert parsed["中文"] == "值"

    def test_compact_format(self):
        """输出应为紧凑格式（无多余空格）"""
        result = _normalize_headers_json('{  "key" :  "value"  }')
        assert result == '{"key":"value"}'


# =====================================================================
# 第三部分：Pydantic 模型（原 test_schemas.py）
# =====================================================================

# ---------------------------------------------------------------------
# auth_url 验证器
# ---------------------------------------------------------------------

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


# ---------------------------------------------------------------------
# 浏览器请求头 JSON 验证器
# ---------------------------------------------------------------------

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


# ---------------------------------------------------------------------
# 日志级别验证器
# ---------------------------------------------------------------------

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


# ---------------------------------------------------------------------
# 自定义变量验证器
# ---------------------------------------------------------------------

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


# ---------------------------------------------------------------------
# 约束字段
# ---------------------------------------------------------------------

class TestConstrainedFields:
    def test_browser_timeout_valid(self):
        m = MonitorConfigPayload(browser_timeout=5)
        assert m.browser_timeout == 5

    def test_browser_timeout_too_low(self):
        m = MonitorConfigPayload(browser_timeout=0)
        assert m.browser_timeout == 1  # 自动钳制到下限

    def test_browser_timeout_too_high(self):
        m = MonitorConfigPayload(browser_timeout=61)
        assert m.browser_timeout == 60  # 自动钳制到上限

    def test_app_port_valid(self):
        m = MonitorConfigPayload(app_port=8080)
        assert m.app_port == 8080

    def test_app_port_too_low(self):
        m = MonitorConfigPayload(app_port=1023)
        assert m.app_port == 1024  # 自动钳制到下限

    def test_app_port_too_high(self):
        m = MonitorConfigPayload(app_port=65536)
        assert m.app_port == 65535  # 自动钳制到上限

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
        m = MonitorConfigPayload(login_timeout=5)
        assert m.login_timeout == 10  # 自动钳制到下限

    def test_network_check_timeout_valid(self):
        m = MonitorConfigPayload(network_check_timeout=5)
        assert m.network_check_timeout == 5

    def test_network_check_timeout_too_high(self):
        m = MonitorConfigPayload(network_check_timeout=31)
        assert m.network_check_timeout == 30  # 自动钳制到上限

    def test_browser_viewport_valid(self):
        m = MonitorConfigPayload(browser_viewport_width=1920, browser_viewport_height=1080)
        assert m.browser_viewport_width == 1920
        assert m.browser_viewport_height == 1080

    def test_browser_viewport_too_low(self):
        m = MonitorConfigPayload(browser_viewport_width=100)
        assert m.browser_viewport_width == 320  # 自动钳制到下限

    def test_browser_viewport_too_high(self):
        m = MonitorConfigPayload(browser_viewport_width=5000)
        assert m.browser_viewport_width == 3840  # 自动钳制到上限


# ---------------------------------------------------------------------
# LogEntry
# ---------------------------------------------------------------------

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


# ---------------------------------------------------------------------
# ProfileSettings
# ---------------------------------------------------------------------

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


# ---------------------------------------------------------------------
# SystemSettings
# ---------------------------------------------------------------------

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


# ---------------------------------------------------------------------
# ProfilesData
# ---------------------------------------------------------------------

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


# ---------------------------------------------------------------------
# ActionResponse
# ---------------------------------------------------------------------

class TestActionResponse:
    def test_success(self):
        r = ActionResponse(success=True, message="操作成功")
        assert r.success is True
        assert r.message == "操作成功"

    def test_failure(self):
        r = ActionResponse(success=False, message="操作失败")
        assert r.success is False
        assert r.message == "操作失败"


# ---------------------------------------------------------------------
# MonitorStatusResponse
# ---------------------------------------------------------------------

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


# ---------------------------------------------------------------------
# AutoStartStatusResponse
# ---------------------------------------------------------------------

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


# ---------------------------------------------------------------------
# MonitorConfigPayload — 完整构造
# ---------------------------------------------------------------------

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
