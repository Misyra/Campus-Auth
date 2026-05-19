from __future__ import annotations


from src.utils.crypto import encrypt_password, decrypt_password


class TestCryptoRoundtrip:

    def test_encrypt_decrypt_roundtrip(self):
        original = "my_secret_password"
        encrypted = encrypt_password(original)
        assert encrypted.startswith("ENC:")
        decrypted = decrypt_password(encrypted)
        assert decrypted == original

    def test_empty_string(self):
        encrypted = encrypt_password("")
        assert encrypted == ""

    def test_non_encrypted_passthrough(self):
        result = decrypt_password("plain_password")
        assert result == "plain_password"

    def test_invalid_encrypted_value(self):
        result = decrypt_password("ENC:invalid_base64_data")
        assert result == ""
