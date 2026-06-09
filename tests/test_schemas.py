"""数据模型测试 — 覆盖 Pydantic 模型验证逻辑。"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas import (
    ActionResponse,
    AutoStartStatusResponse,
    LogEntry,
    MonitorStatusResponse,
    ProfilesData,
    ProfileSettings,
    SystemSettings,
)

# ── ActionResponse ──


class TestActionResponse:
    """操作响应模型。"""

    def test_basic_creation(self):
        """基本创建。"""
        resp = ActionResponse(success=True, message="ok")
        assert resp.success is True
        assert resp.message == "ok"

    def test_failure(self):
        """失败响应。"""
        resp = ActionResponse(success=False, message="error")
        assert resp.success is False


# ── MonitorStatusResponse ──


class TestMonitorStatusResponse:
    """监控状态响应。"""

    def test_basic_creation(self):
        """基本创建。"""
        resp = MonitorStatusResponse(
            monitoring=True,
            network_check_count=10,
            login_attempt_count=2,
            last_check_time="2026-06-01T12:00:00",
            runtime_seconds=3600,
        )
        assert resp.monitoring is True
        assert resp.network_check_count == 10
        assert resp.runtime_seconds == 3600

    def test_default_values(self):
        """默认值。"""
        resp = MonitorStatusResponse(
            monitoring=False,
            network_check_count=0,
            login_attempt_count=0,
            last_check_time=None,
            runtime_seconds=0,
        )
        assert resp.network_connected is False
        assert resp.status_detail == "正常"
        assert resp.network_state == "unknown"


# ── LogEntry ──


class TestLogEntry:
    """日志条目。"""

    def test_basic_creation(self):
        """基本创建。"""
        entry = LogEntry(timestamp="2026-06-01 12:00:00", message="test")
        assert entry.level == "INFO"
        assert entry.source == "backend"

    def test_level_normalized(self):
        """级别标准化为大写。"""
        entry = LogEntry(timestamp="2026-06-01 12:00:00", level="info", message="test")
        assert entry.level == "INFO"

    def test_invalid_level_fallback(self):
        """无效级别回退到 INFO。"""
        entry = LogEntry(
            timestamp="2026-06-01 12:00:00", level="invalid", message="test"
        )
        assert entry.level == "INFO"


# ── AutoStartStatusResponse ──


class TestAutoStartStatusResponse:
    """自启动状态响应。"""

    def test_basic_creation(self):
        """基本创建。"""
        resp = AutoStartStatusResponse(
            platform="Windows",
            enabled=True,
            method="VBScript",
            location="C:\\test.vbs",
        )
        assert resp.platform == "Windows"
        assert resp.enabled is True


# ── SystemSettings ──


class TestSystemSettings:
    """系统设置。"""

    def test_default_values(self):
        """默认值。"""
        settings = SystemSettings()
        assert settings.pure_mode is False
        assert settings.network_check_timeout == 2
        assert settings.block_proxy is True
        assert settings.app_port == 50721
        assert settings.max_retries == 3
        assert settings.retry_interval == 5

    def test_log_level_validation(self):
        """日志级别验证。"""
        settings = SystemSettings(backend_log_level="debug")
        assert settings.backend_log_level == "DEBUG"

    def test_invalid_log_level_raises(self):
        """无效日志级别抛异常。"""
        with pytest.raises(ValidationError):
            SystemSettings(backend_log_level="INVALID")

    def test_auth_url_validation(self):
        """认证地址验证。"""
        settings = SystemSettings(auth_url="http://example.com")
        assert settings.auth_url == "http://example.com"

    def test_invalid_auth_url_raises(self):
        """无效认证地址抛异常。"""
        with pytest.raises(ValidationError):
            SystemSettings(auth_url="ftp://example.com")

    def test_empty_auth_url_accepted(self):
        """空认证地址被接受。"""
        settings = SystemSettings(auth_url="")
        assert settings.auth_url == ""


# ── ProfileSettings ──


class TestProfileSettings:
    """方案设置。"""

    def test_default_values(self):
        """默认值。"""
        settings = ProfileSettings()
        assert settings.name == "默认方案"
        assert settings.use_global_credentials is True
        assert settings.use_global_advanced is True

    def test_custom_name(self):
        """自定义名称。"""
        settings = ProfileSettings(name="宿舍")
        assert settings.name == "宿舍"


# ── ProfilesData ──


class TestProfilesData:
    """配置数据。"""

    def test_default_values(self):
        """默认值。"""
        data = ProfilesData()
        assert data.auto_switch is False
        assert data.active_profile == "default"
        assert isinstance(data.system, SystemSettings)
        assert data.profiles == {}

    def test_with_profiles(self):
        """包含方案。"""
        data = ProfilesData(
            active_profile="dorm",
            profiles={"dorm": ProfileSettings(name="宿舍")},
        )
        assert data.active_profile == "dorm"
        assert "dorm" in data.profiles

    def test_json_roundtrip(self):
        """JSON 往返。"""
        data = ProfilesData(
            auto_switch=True,
            active_profile="test",
            system=SystemSettings(app_port=8080),
        )
        json_str = data.model_dump_json()
        restored = ProfilesData.model_validate_json(json_str)
        assert restored.auto_switch is True
        assert restored.system.app_port == 8080


# ── _ClampMixin 钳制逻辑 ──


class TestClampMixin:
    """数值钳制逻辑。"""

    def test_below_ge_clamped(self):
        """低于下限被钳制。"""
        settings = SystemSettings(app_port=100)  # ge=1024
        assert settings.app_port == 1024

    def test_above_le_clamped(self):
        """高于上限被钳制。"""
        settings = SystemSettings(app_port=99999)  # le=65535
        assert settings.app_port == 65535

    def test_within_range_unchanged(self):
        """范围内不变。"""
        settings = SystemSettings(app_port=8080)
        assert settings.app_port == 8080

    def test_boundary_values(self):
        """边界值。"""
        settings = SystemSettings(app_port=1024)
        assert settings.app_port == 1024
        settings = SystemSettings(app_port=65535)
        assert settings.app_port == 65535


# ── _BrowserValidatorsMixin ──


class TestBrowserValidators:
    """浏览器验证器。"""

    def test_empty_headers_accepted(self):
        """空请求头被接受。"""
        settings = ProfileSettings(browser_extra_headers_json="")
        assert settings.browser_extra_headers_json == ""

    def test_valid_json_headers(self):
        """有效 JSON 请求头。"""
        settings = ProfileSettings(browser_extra_headers_json='{"X-Test": "value"}')
        assert settings.browser_extra_headers_json == '{"X-Test": "value"}'

    def test_invalid_json_raises(self):
        """无效 JSON 抛异常。"""
        with pytest.raises(ValidationError):
            ProfileSettings(browser_extra_headers_json="not json")

    def test_non_dict_json_raises(self):
        """非字典 JSON 抛异常。"""
        with pytest.raises(ValidationError):
            ProfileSettings(browser_extra_headers_json='["array"]')


# ── _SharedValidatorsMixin ──


class TestSharedValidators:
    """共享验证器。"""

    def test_http_url_accepted(self):
        """HTTP URL 被接受。"""
        settings = ProfileSettings(auth_url="http://example.com")
        assert settings.auth_url == "http://example.com"

    def test_https_url_accepted(self):
        """HTTPS URL 被接受。"""
        settings = ProfileSettings(auth_url="https://example.com")
        assert settings.auth_url == "https://example.com"

    def test_ftp_url_raises(self):
        """FTP URL 抛异常。"""
        with pytest.raises(ValidationError):
            ProfileSettings(auth_url="ftp://example.com")

    def test_empty_url_accepted(self):
        """空 URL 被接受。"""
        settings = ProfileSettings(auth_url="")
        assert settings.auth_url == ""

    def test_whitespace_trimmed(self):
        """首尾空格被去除。"""
        settings = ProfileSettings(auth_url="  http://example.com  ")
        assert settings.auth_url == "http://example.com"
