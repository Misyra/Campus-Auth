"""配置服务逻辑测试 — 覆盖纯逻辑函数。"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.services.config import (
    _decrypt_password_field,
    _normalize_headers_json,
    _normalize_targets,
    _safe_decrypt,
)

# ── _safe_decrypt ──


class TestSafeDecrypt:
    """安全解密。"""

    def test_empty_returns_empty(self):
        """空字符串返回空。"""
        result, has_error = _safe_decrypt("")
        assert result == ""
        assert has_error is False

    def test_decrypt_success(self):
        """解密成功。"""
        with patch("app.services.config.decrypt_password", return_value="plaintext"):
            result, has_error = _safe_decrypt("ENC:encrypted")
            assert result == "plaintext"
            assert has_error is False

    def test_decrypt_failure(self):
        """解密失败返回空和错误标记。"""
        from app.utils.exceptions import DecryptionError

        with patch(
            "app.services.config.decrypt_password", side_effect=DecryptionError("fail")
        ):
            result, has_error = _safe_decrypt("ENC:bad_data")
            assert result == ""
            assert has_error is True


# ── _decrypt_password_field ──


class TestDecryptPasswordField:
    """密码字段解密。"""

    def test_encrypted_password(self):
        """ENC: 前缀密码解密。"""
        with patch("app.services.config.decrypt_password", return_value="secret"):
            result, has_error = _decrypt_password_field("ENC:encrypted")
            assert result == "secret"
            assert has_error is False

    def test_masked_password_with_fallback(self):
        """掩码密码使用回退。"""
        with patch("app.services.config.decrypt_password", return_value="fallback"):
            result, has_error = _decrypt_password_field(
                "••••••••", "ENC:fallback_encrypted"
            )
            assert result == "fallback"
            assert has_error is False

    def test_masked_password_no_fallback(self):
        """掩码密码无回退返回空。"""
        result, has_error = _decrypt_password_field("••••••••", "")
        assert result == ""
        assert has_error is False

    def test_plain_password(self):
        """明文密码直接返回。"""
        result, has_error = _decrypt_password_field("mypassword")
        assert result == "mypassword"
        assert has_error is False

    def test_empty_with_fallback(self):
        """空密码使用回退。"""
        with patch("app.services.config.decrypt_password", return_value="fallback"):
            result, has_error = _decrypt_password_field("", "ENC:fallback")
            assert result == "fallback"

    def test_empty_no_fallback(self):
        """空密码无回退返回空。"""
        result, has_error = _decrypt_password_field("", "")
        assert result == ""
        assert has_error is False


# ── _normalize_targets ──


class TestNormalizeTargets:
    """目标地址标准化。"""

    def test_valid_targets(self):
        """有效目标。"""
        result = _normalize_targets("8.8.8.8:53,1.1.1.1:53")
        assert result == "8.8.8.8:53,1.1.1.1:53"

    def test_whitespace_trimmed(self):
        """空格被去除。"""
        result = _normalize_targets("  8.8.8.8:53  ,  1.1.1.1:53  ")
        assert result == "8.8.8.8:53,1.1.1.1:53"

    def test_empty_returns_default(self):
        """空返回默认值。"""
        from app.constants import DEFAULT_NETWORK_TARGETS

        result = _normalize_targets("")
        assert result == DEFAULT_NETWORK_TARGETS

    def test_none_returns_default(self):
        """None 返回默认值。"""
        from app.constants import DEFAULT_NETWORK_TARGETS

        result = _normalize_targets(None)
        assert result == DEFAULT_NETWORK_TARGETS

    def test_whitespace_only_returns_default(self):
        """纯空格返回默认值。"""
        from app.constants import DEFAULT_NETWORK_TARGETS

        result = _normalize_targets("  ,  ,  ")
        assert result == DEFAULT_NETWORK_TARGETS


# ── _normalize_headers_json ──


class TestNormalizeHeadersJson:
    """请求头 JSON 标准化。"""

    def test_valid_json(self):
        """有效 JSON 被标准化。"""
        result = _normalize_headers_json('{"X-Test": "value"}')
        assert "X-Test" in result
        assert "value" in result

    def test_empty_string(self):
        """空字符串。"""
        result = _normalize_headers_json("")
        assert result == ""

    def test_none(self):
        """None。"""
        result = _normalize_headers_json(None)
        assert result == ""

    def test_whitespace_trimmed(self):
        """空格被去除后解析。"""
        result = _normalize_headers_json('  {"X-Test": "value"}  ')
        assert "X-Test" in result

    def test_invalid_json_raises(self):
        """无效 JSON 抛异常。"""
        with pytest.raises(ValueError, match="JSON"):
            _normalize_headers_json("not json")

    def test_non_dict_json_raises(self):
        """非字典 JSON 抛异常。"""
        with pytest.raises(ValueError, match="格式不正确"):
            _normalize_headers_json('["array"]')

    def test_normalized_format(self):
        """标准化格式。"""
        result = _normalize_headers_json('{"X-Test": "value", "X-Other": "test"}')
        # 输出是紧凑格式
        assert "," in result
        assert ":" in result
