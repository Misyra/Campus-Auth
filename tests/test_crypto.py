from __future__ import annotations

import pytest

from src.utils.crypto import encrypt_password, decrypt_password
from src.utils.exceptions import DecryptionError


class TestCryptoRoundtrip:

    def test_encrypt_decrypt_roundtrip(self):
        original = "my_secret_password"
        encrypted = encrypt_password(original)
        assert encrypted.startswith("ENC:")
        decrypted = decrypt_password(encrypted)
        assert decrypted == original

    def test_encrypt_empty_string(self):
        encrypted = encrypt_password("")
        assert encrypted == ""

    def test_decrypt_empty_string(self):
        result = decrypt_password("")
        assert result == ""

    def test_non_encrypted_passthrough(self):
        result = decrypt_password("plain_password")
        assert result == "plain_password"

    def test_corrupted_ciphertext_raises_decryption_error(self):
        with pytest.raises(DecryptionError):
            decrypt_password("ENC:invalid_base64_data")

    def test_wrong_key_raises_decryption_error(self):
        encrypted = encrypt_password("test_password")
        # Tamper with the ciphertext to simulate wrong key / corrupted data
        tampered = encrypted[:6] + ("X" if encrypted[6] != "X" else "Y") + encrypted[7:]
        with pytest.raises(DecryptionError):
            decrypt_password(tampered)
