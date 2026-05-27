"""配置相关模块综合测试

合并原 test_config_validator.py，并新增 backend/config_service.py 工具函数测试。
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from src.utils.config import ConfigValidator
from backend.config_service import (
    _safe_decrypt,
    _normalize_level,
    _normalize_targets,
    _normalize_headers_json,
)
from src.utils.crypto import encrypt_password


# =====================================================================
# ConfigValidator
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
            username="testuser", password="testpass", check_interval="2000"
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
# backend/config_service.py 工具函数
# =====================================================================

class TestSafeDecrypt:
    def test_decrypt_encrypted_value(self):
        """应能解密 ENC: 前缀的值"""
        encrypted = encrypt_password("test123")
        result = _safe_decrypt(encrypted)
        assert result == "test123"

    def test_decrypt_empty_string(self):
        """空字符串应返回空字符串"""
        assert _safe_decrypt("") == ""

    def test_decrypt_plaintext_passthrough(self):
        """无 ENC: 前缀的明文应原样返回"""
        assert _safe_decrypt("plaintext") == "plaintext"


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
