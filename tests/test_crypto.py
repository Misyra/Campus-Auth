"""src/utils/crypto.py 测试"""
from __future__ import annotations

from src.utils.crypto import (
    encrypt_password,
    decrypt_password,
    mask_password,
    is_encrypted,
    save_password_field,
)


class TestEncryptDecrypt:
    def test_round_trip(self):
        """加密后解密应返回原文"""
        original = "my_secret_password_123"
        encrypted = encrypt_password(original)
        assert is_encrypted(encrypted)
        assert decrypt_password(encrypted) == original

    def test_empty_string(self):
        """空字符串加密应返回空字符串"""
        assert encrypt_password("") == ""
        assert decrypt_password("") == ""

    def test_plaintext_passthrough(self):
        """无 ENC: 前缀的明文应原样返回（向后兼容）"""
        plaintext = "old_password"
        assert decrypt_password(plaintext) == plaintext

    def test_enc_prefix(self):
        """加密结果应有 ENC: 前缀"""
        encrypted = encrypt_password("test")
        assert encrypted.startswith("ENC:")

    def test_unicode_password(self):
        """中文密码应正常加解密"""
        original = "校园网密码🔑"
        encrypted = encrypt_password(original)
        assert decrypt_password(encrypted) == original

    def test_long_password(self):
        """长密码应正常加解密"""
        original = "a" * 1000
        encrypted = encrypt_password(original)
        assert decrypt_password(encrypted) == original

    def test_special_characters(self):
        """特殊字符密码应正常加解密"""
        original = '!@#$%^&*()_+-=[]{}|;:\'",.<>?/~`'
        encrypted = encrypt_password(original)
        assert decrypt_password(encrypted) == original


class TestIsEncrypted:
    def test_encrypted_value(self):
        assert is_encrypted("ENC:something") is True

    def test_plaintext_value(self):
        assert is_encrypted("plaintext") is False

    def test_empty_string(self):
        assert is_encrypted("") is False

    def test_enc_prefix_only(self):
        assert is_encrypted("ENC:") is True


class TestMaskPassword:
    def test_empty(self):
        assert mask_password("") == ""

    def test_encrypted(self):
        """加密密码应返回固定长度掩码"""
        assert mask_password("ENC:abc123") == "••••••••"

    def test_plaintext_unified_mask(self):
        """明文密码应返回统一长度掩码（不泄露长度）"""
        assert mask_password("ab") == "••••••••"
        assert mask_password("abcdef") == "••••••••"
        assert mask_password("a" * 100) == "••••••••"


class TestSavePasswordField:
    def test_none_returns_existing(self):
        """raw=None 时应返回原加密值"""
        assert save_password_field(None, "ENC:existing") == "ENC:existing"

    def test_empty_raw_returns_existing(self):
        """raw 为空字符串时应返回原加密值"""
        assert save_password_field("", "ENC:existing") == "ENC:existing"

    def test_mask_preserves_existing(self):
        """raw 为掩码时应保留原加密值"""
        assert save_password_field("••••", "ENC:existing") == "ENC:existing"

    def test_enc_passthrough(self):
        """raw 已有 ENC: 前缀应原样返回"""
        assert save_password_field("ENC:abc", "ENC:old") == "ENC:abc"

    def test_new_plaintext_gets_encrypted(self):
        """新的明文密码应被加密"""
        result = save_password_field("new_password", "")
        assert result.startswith("ENC:")
        assert decrypt_password(result) == "new_password"
