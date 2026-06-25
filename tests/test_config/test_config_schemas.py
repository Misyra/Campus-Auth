"""配置与数据模型综合测试

合并原 test_config.py 和 test_schemas.py。
覆盖 ConfigValidator、config_service 工具函数、Pydantic 模型等。
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from app.schemas import (
    ActionResponse,
    Profile,
    AutoStartStatusResponse,
    LogEntry,
    MonitorStatusResponse,
    ProfilesData,
)
from app.utils.crypto import decrypt_password_field, safe_decrypt
from app.schemas import LoginCredentials, RuntimeConfig
from app.utils.config_utils import ConfigValidator
from app.utils.crypto import encrypt_password
from app.utils.logging import normalize_level as _normalize_level

# =====================================================================
# 第一部分：ConfigValidator（原 test_config.py 前半部分）
# =====================================================================


class TestValidateEnvConfig:
    def setup_method(self):
        """清除解密错误状态，防止其他测试污染。"""
        from app.utils.crypto import clear_decryption_error

        clear_decryption_error()

    def test_valid_config(self):
        ok, msg = ConfigValidator.validate_env_config(
            RuntimeConfig(
                credentials=LoginCredentials(
                    username="testuser",
                    password="testpass",
                    auth_url="http://10.0.0.1",
                )
            )
        )
        assert ok is True

    def test_missing_username(self):
        ok, msg = ConfigValidator.validate_env_config(
            RuntimeConfig(
                credentials=LoginCredentials(
                    username="",
                    password="pass",
                    auth_url="http://10.0.0.1",
                )
            )
        )
        assert ok is False

    def test_missing_auth_url(self):
        ok, msg = ConfigValidator.validate_env_config(
            RuntimeConfig(
                credentials=LoginCredentials(
                    username="user",
                    password="pass",
                    auth_url="",
                )
            )
        )
        assert ok is False

    def test_missing_password(self):
        ok, msg = ConfigValidator.validate_env_config(
            RuntimeConfig(
                credentials=LoginCredentials(
                    username="user",
                    password="",
                    auth_url="http://10.0.0.1",
                )
            )
        )
        assert ok is False

    def test_all_empty(self):
        ok, msg = ConfigValidator.validate_env_config(
            RuntimeConfig(
                credentials=LoginCredentials(
                    username="",
                    password="",
                    auth_url="",
                )
            )
        )
        assert ok is False

    def test_none_values(self):
        ok, msg = ConfigValidator.validate_env_config(
            RuntimeConfig()
        )
        assert ok is False


# =====================================================================
# 第二部分：config_service 工具函数（原 test_config.py 后半部分）
# =====================================================================


class TestSafeDecrypt:
    def test_decrypt_encrypted_value(self):
        """应能解密 ENC: 前缀的值"""
        encrypted = encrypt_password("test123")
        result, has_error = safe_decrypt(encrypted)
        assert result == "test123"
        assert has_error is False

    def test_decrypt_empty_string(self):
        """空字符串应返回空字符串"""
        result, has_error = safe_decrypt("")
        assert result == ""
        assert has_error is False

    def test_decrypt_plaintext_passthrough(self):
        """无 ENC: 前缀的明文应原样返回"""
        result, has_error = safe_decrypt("plaintext")
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
        assert _normalize_level("TRACE") == "INFO"
        assert _normalize_level("INVALID") == "INFO"

    def test_empty_returns_default(self):
        assert _normalize_level("") == "INFO"
        assert _normalize_level(None) == "INFO"

    def test_custom_default(self):
        assert _normalize_level("INVALID", default="ERROR") == "ERROR"

    def test_valid_with_custom_default(self):
        assert _normalize_level("DEBUG", default="ERROR") == "DEBUG"


# =====================================================================
# 第三部分：Pydantic 模型（原 test_schemas.py）
# =====================================================================

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
        assert entry.source == "backend"

    def test_custom_source(self):
        entry = LogEntry(timestamp="2025-01-01", source="backend", message="test")
        assert entry.source == "backend"


# ---------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------


class TestProfileDefaults:
    def test_defaults(self):
        p = Profile()
        assert p.name == "默认方案"
        assert p.username == ""
        assert p.password == ""
        assert p.carrier == "无"
        assert p.auth_url == ""

    def test_custom_name(self):
        p = Profile(name="自定义方案")
        assert p.name == "自定义方案"

    def test_match_fields(self):
        p = Profile(
            match_gateway_ip="10.0.0.1",
            match_ssid="CampusWiFi",
        )
        assert p.match_gateway_ip == "10.0.0.1"
        assert p.match_ssid == "CampusWiFi"


class TestProfile:
    """Profile 测试"""

    def test_custom_values(self):
        """测试自定义值"""
        profile = Profile(
            name="测试方案",
            username="testuser",
            password="testpass",
            carrier="移动",
            auth_url="http://example.com",
        )
        assert profile.name == "测试方案"
        assert profile.username == "testuser"
        assert profile.password == "testpass"
        assert profile.carrier == "移动"
        assert profile.auth_url == "http://example.com"

    def test_invalid_auth_url(self):
        """测试无效认证地址"""
        with pytest.raises(ValidationError, match="认证地址必须以 http"):
            Profile(auth_url="not-a-url")


# ---------------------------------------------------------------------
# SystemSettings
# ---------------------------------------------------------------------


# ---------------------------------------------------------------------
# ProfilesData
# ---------------------------------------------------------------------


class TestProfilesData:
    def test_default_profile_auto_created(self):
        """测试自动创建 default profile"""
        from app.schemas import Profile

        data = ProfilesData()
        assert "default" in data.profiles
        assert isinstance(data.profiles["default"], Profile)
        assert data.profiles["default"].name == "默认方案"

    def test_config_version_default(self):
        data = ProfilesData()
        assert data.config_version == 5

    def test_config_is_global_config(self):
        from app.schemas import GlobalConfig
        data = ProfilesData()
        assert isinstance(data.global_config, GlobalConfig)

    def test_no_global_settings(self):
        data = ProfilesData()
        assert not hasattr(data, "global_settings")

    def test_custom_profiles(self):
        """测试自定义 profiles"""
        from app.schemas import Profile

        data = ProfilesData(
            profiles={
                "default": Profile(name="默认"),
                "custom": Profile(name="自定义"),
            }
        )
        assert len(data.profiles) == 2
        assert data.profiles["default"].name == "默认"
        assert data.profiles["custom"].name == "自定义"

    def test_defaults(self):
        from app.schemas import GlobalConfig, Profile

        data = ProfilesData()
        assert data.auto_switch is False
        assert data.active_profile == "default"
        assert isinstance(data.global_config, GlobalConfig)
        assert isinstance(data.profiles, dict)
        assert isinstance(data.profiles["default"], Profile)

    def test_with_profiles(self):
        from app.schemas import Profile

        data = ProfilesData(
            auto_switch=True,
            active_profile="campus",
            profiles={
                "default": Profile(name="默认"),
                "campus": Profile(name="校园"),
            },
        )
        assert data.auto_switch is True
        assert data.active_profile == "campus"
        assert len(data.profiles) == 2
        assert data.profiles["default"].name == "默认"

    def test_empty_profiles_creates_default(self):
        from app.schemas import Profile

        data = ProfilesData(profiles={})
        assert "default" in data.profiles
        assert isinstance(data.profiles["default"], Profile)
        assert data.profiles["default"].name == "默认方案"


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


# ── 密码字段解密 ──


class TestDecryptPasswordField:
    """密码字段解密。"""

    def test_encrypted_password(self):
        """ENC: 前缀密码解密。"""
        from unittest.mock import patch

        with patch(
            "app.utils.crypto.decrypt_password", return_value="secret"
        ):
            result, has_error = decrypt_password_field("ENC:encrypted")
            assert result == "secret"
            assert has_error is False

    def test_masked_password_with_fallback(self):
        """掩码密码使用回退。"""
        from unittest.mock import patch

        with patch(
            "app.utils.crypto.decrypt_password", return_value="fallback"
        ):
            result, has_error = decrypt_password_field(
                "••••••••", "ENC:fallback_encrypted"
            )
            assert result == "fallback"
            assert has_error is False

    def test_masked_password_no_fallback(self):
        """掩码密码无回退返回空。"""
        result, has_error = decrypt_password_field("••••••••", "")
        assert result == ""
        assert has_error is False

    def test_plain_password(self):
        """明文密码直接返回。"""
        result, has_error = decrypt_password_field("mypassword")
        assert result == "mypassword"
        assert has_error is False
