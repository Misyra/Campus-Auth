"""加密工具测试 — 覆盖密码加密/解密的纯逻辑。"""

from __future__ import annotations

from unittest.mock import patch

from app.utils.crypto import (
    _simple_deobfuscate,
    _simple_obfuscate,
    clear_decryption_error,
    has_decryption_error,
    is_encrypted,
    mask_password,
    save_password_field,
)

# ── is_encrypted ──


class TestIsEncrypted:
    """加密状态判断。"""

    def test_encrypted_value(self):
        """ENC: 前缀判断为已加密。"""
        assert is_encrypted("ENC:gAAAAABh...") is True

    def test_plain_text(self):
        """明文判断为未加密。"""
        assert is_encrypted("mypassword") is False

    def test_empty_string(self):
        """空字符串判断为未加密。"""
        assert is_encrypted("") is False

    def test_none(self):
        """None 判断为未加密。"""
        assert is_encrypted(None) is False

    def test_enc_prefix_only(self):
        """仅 ENC: 前缀也算已加密。"""
        assert is_encrypted("ENC:") is True


# ── mask_password ──


class TestMaskPassword:
    """密码脱敏。"""

    def test_normal_password(self):
        """正常密码返回掩码。"""
        assert mask_password("mypassword") == "••••••••"

    def test_empty_password(self):
        """空密码返回空字符串。"""
        assert mask_password("") == ""

    def test_none_password(self):
        """None 返回空字符串。"""
        assert mask_password(None) == ""

    def test_mask_length_constant(self):
        """掩码长度固定，不泄露密码长度。"""
        assert mask_password("a") == mask_password("a" * 100) == "••••••••"


# ── save_password_field ──


class TestSavePasswordField:
    """密码字段保存逻辑。"""

    def test_none_returns_existing(self):
        """raw=None 返回已有加密值。"""
        result = save_password_field(None, "ENC:existing")
        assert result == "ENC:existing"

    def test_none_with_empty_existing(self):
        """raw=None 且无已有值返回空。"""
        result = save_password_field(None, "")
        assert result == ""

    def test_empty_returns_existing(self):
        """raw='' 返回已有加密值。"""
        result = save_password_field("", "ENC:existing")
        assert result == "ENC:existing"

    def test_empty_with_no_existing(self):
        """raw='' 且无已有值返回空。"""
        result = save_password_field("", "")
        assert result == ""

    def test_mask_returns_existing(self):
        """掩码返回已有加密值。"""
        result = save_password_field("••••••••", "ENC:existing")
        assert result == "ENC:existing"

    def test_enc_value_passthrough(self):
        """ENC: 前缀原样返回。"""
        result = save_password_field("ENC:gAAAAABh...", "old")
        assert result == "ENC:gAAAAABh..."

    def test_plain_text_encrypted(self):
        """明文被加密。"""
        with patch("app.utils.crypto.encrypt_password", return_value="ENC:encrypted") as mock_enc:
            result = save_password_field("mypassword", "")
            mock_enc.assert_called_once_with("mypassword")
            assert result == "ENC:encrypted"


# ── _simple_obfuscate / _simple_deobfuscate ──


class TestSimpleObfuscate:
    """简单 Base64 混淆。"""

    def test_roundtrip(self):
        """混淆 -> 反混淆往返。"""
        original = "test_password_123"
        obfuscated = _simple_obfuscate(original)
        assert obfuscated.startswith("ENC:B64:")
        deobfuscated = _simple_deobfuscate(obfuscated[len("ENC:"):])
        assert deobfuscated == original

    def test_unicode(self):
        """Unicode 字符支持。"""
        original = "密码测试"
        obfuscated = _simple_obfuscate(original)
        deobfuscated = _simple_deobfuscate(obfuscated[len("ENC:"):])
        assert deobfuscated == original

    def test_empty_string(self):
        """空字符串。"""
        obfuscated = _simple_obfuscate("")
        assert obfuscated == "ENC:B64:"

    def test_deobfuscate_without_prefix(self):
        """无 B64: 前缀原样返回。"""
        result = _simple_deobfuscate("plaintext")
        assert result == "plaintext"


# ── has_decryption_error / clear_decryption_error ──


class TestDecryptionError:
    """解密错误状态管理。"""

    def test_initial_state(self):
        """初始状态无解密错误。"""
        clear_decryption_error()
        assert has_decryption_error() is False

    def test_set_and_clear(self):
        """设置和清除解密错误。"""
        from app.utils.crypto import _decryption_failed
        _decryption_failed.set()
        assert has_decryption_error() is True
        clear_decryption_error()
        assert has_decryption_error() is False
