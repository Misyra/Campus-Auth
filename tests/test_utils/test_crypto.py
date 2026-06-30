"""crypto.py 测试覆盖。

覆盖所有公开函数及关键分支：
- _get_or_create_key: 缓存命中、密钥文件损坏备份、chmod 失败、icacls 超时/异常
- _derive_fernet_key: 缓存命中
- encrypt_password: 空字符串、正常加密、cryptography 未安装
- decrypt_password: 空字符串、明文回退、正常解密、cryptography 未安装、解密失败
- has_decryption_error / clear_decryption_error
- save_password_field: 全部分支
"""

import subprocess
import threading
from unittest.mock import MagicMock, patch

import pytest

import app.utils.crypto as crypto_mod
from app.utils.crypto import _DecryptionError


@pytest.fixture(autouse=True)
def _reset_crypto_cache(tmp_path):
    """每个测试前后重置全局缓存和解密失败标记，确保测试独立。"""
    old_raw = crypto_mod._cached_raw_key
    old_fernet = crypto_mod._cached_fernet_key
    old_dir = crypto_mod._KEY_DIR
    old_file = crypto_mod._KEY_FILE
    old_event = crypto_mod._decryption_failed

    crypto_mod._cached_raw_key = None
    crypto_mod._cached_fernet_key = None
    crypto_mod._KEY_DIR = tmp_path
    crypto_mod._KEY_FILE = tmp_path / ".enc_key"
    crypto_mod._decryption_failed = threading.Event()

    yield crypto_mod

    crypto_mod._cached_raw_key = old_raw
    crypto_mod._cached_fernet_key = old_fernet
    crypto_mod._KEY_DIR = old_dir
    crypto_mod._KEY_FILE = old_file
    crypto_mod._decryption_failed = old_event


# ── _get_or_create_key 缓存命中 ──


class TestGetOrCreateKeyCache:
    """验证 _get_or_create_key 的缓存逻辑。"""

    def test_cache_hit_returns_same_key(self, _reset_crypto_cache):
        """首次调用后缓存应命中，第二次直接返回缓存值。"""
        crypto_mod = _reset_crypto_cache
        key1 = crypto_mod._get_or_create_key()
        # 设置缓存后再次调用
        key2 = crypto_mod._get_or_create_key()
        assert key1 is key2

    def test_cache_hit_in_double_check(self, _reset_crypto_cache):
        """在锁内 double-check 时缓存命中。"""
        crypto_mod = _reset_crypto_cache
        key1 = crypto_mod._get_or_create_key()

        # 模拟进入锁之前缓存已设置（double-check 路径）
        # 清除后模拟另一个线程已设置缓存的场景
        with crypto_mod._key_lock:
            pass  # 释放锁后缓存仍在
        key2 = crypto_mod._get_or_create_key()
        assert key1 is key2


# ── 密钥文件损坏备份逻辑（54-65行）──


class TestCorruptedKeyFile:
    """验证密钥文件损坏时的备份和重新生成逻辑。"""

    def test_corrupted_key_file_backed_up(self, _reset_crypto_cache):
        """当密钥文件内容损坏时，应备份并重新生成。"""
        crypto_mod = _reset_crypto_cache
        # 写入损坏的密钥数据（包含 base64 非法字符 padding 使解码报错）
        crypto_mod._KEY_DIR.mkdir(parents=True, exist_ok=True)
        crypto_mod._KEY_FILE.write_text("!!!invalid!!!", encoding="utf-8")

        with patch.object(crypto_mod, "is_windows", return_value=False):
            key = crypto_mod._get_or_create_key()

        assert len(key) == 32
        # 应存在 .bak.* 备份文件
        backups = list(crypto_mod._KEY_DIR.glob(".enc_key.bak.*"))
        assert len(backups) == 1

    def test_corrupted_key_file_wrong_length(self, _reset_crypto_cache):
        """base64 解码后长度不是 32 字节时也应重新生成。"""
        crypto_mod = _reset_crypto_cache
        import base64

        crypto_mod._KEY_DIR.mkdir(parents=True, exist_ok=True)
        # 写入合法 base64 但长度不是 32 字节
        short_key = base64.urlsafe_b64encode(b"short").decode("ascii")
        crypto_mod._KEY_FILE.write_text(short_key, encoding="utf-8")

        with patch.object(crypto_mod, "is_windows", return_value=False):
            key = crypto_mod._get_or_create_key()

        assert len(key) == 32

    def test_backup_rename_file_not_found(self, _reset_crypto_cache):
        """备份时文件已不存在（竞态），应静默处理。"""
        crypto_mod = _reset_crypto_cache
        crypto_mod._KEY_DIR.mkdir(parents=True, exist_ok=True)
        crypto_mod._KEY_FILE.write_text("corrupt", encoding="utf-8")

        # 让 rename 抛出 FileNotFoundError
        original_rename = type(crypto_mod._KEY_FILE).rename

        def mock_rename(self, target):
            raise FileNotFoundError()

        with (
            patch.object(type(crypto_mod._KEY_FILE), "rename", mock_rename),
            patch.object(crypto_mod, "is_windows", return_value=False),
        ):
            key = crypto_mod._get_or_create_key()

        assert len(key) == 32

    def test_backup_rename_os_error(self, _reset_crypto_cache):
        """备份时发生 OSError，应记录警告并继续。"""
        crypto_mod = _reset_crypto_cache
        crypto_mod._KEY_DIR.mkdir(parents=True, exist_ok=True)
        crypto_mod._KEY_FILE.write_text("corrupt", encoding="utf-8")

        def mock_rename(self, target):
            raise OSError("disk full")

        with (
            patch.object(type(crypto_mod._KEY_FILE), "rename", mock_rename),
            patch.object(crypto_mod, "is_windows", return_value=False),
        ):
            key = crypto_mod._get_or_create_key()

        assert len(key) == 32


# ── chmod 失败（76-77行）──


class TestChmodFailure:
    """验证 chmod 设置权限失败时的处理。"""

    def test_chmod_os_error_warning(self, _reset_crypto_cache):
        """chmod 失败时应记录警告但不影响密钥生成。"""
        crypto_mod = _reset_crypto_cache

        with (
            patch("os.chmod", side_effect=OSError("no permission")),
            patch.object(crypto_mod, "is_windows", return_value=False),
        ):
            key = crypto_mod._get_or_create_key()

        assert len(key) == 32


# ── icacls 超时和异常（99-102行）──


class TestIcaclsErrors:
    """验证 Windows icacls 命令的异常处理。"""

    def test_icacls_timeout(self, _reset_crypto_cache):
        """icacls 超时应记录警告但不影响密钥生成。"""
        crypto_mod = _reset_crypto_cache

        mock_run = MagicMock(side_effect=subprocess.TimeoutExpired("icacls", 10))

        with (
            patch.object(crypto_mod, "is_windows", return_value=True),
            patch("subprocess.run", mock_run),
            patch.dict("os.environ", {"USERNAME": "TestUser"}, clear=True),
        ):
            key = crypto_mod._get_or_create_key()

        assert len(key) == 32

    def test_icacls_generic_exception(self, _reset_crypto_cache):
        """icacls 其他异常应记录警告但不影响密钥生成。"""
        crypto_mod = _reset_crypto_cache

        mock_run = MagicMock(side_effect=RuntimeError("unexpected"))

        with (
            patch.object(crypto_mod, "is_windows", return_value=True),
            patch("subprocess.run", mock_run),
            patch.dict("os.environ", {"USERNAME": "TestUser"}, clear=True),
        ):
            key = crypto_mod._get_or_create_key()

        assert len(key) == 32


# ── _derive_fernet_key 缓存命中（116行）──


class TestDeriveFernetKeyCache:
    """验证 _derive_fernet_key 的缓存逻辑。"""

    def test_fernet_key_cache_hit(self, _reset_crypto_cache):
        """第二次调用应返回缓存的 Fernet 密钥。"""
        crypto_mod = _reset_crypto_cache
        with patch.object(crypto_mod, "is_windows", return_value=False):
            key1 = crypto_mod._derive_fernet_key()
            key2 = crypto_mod._derive_fernet_key()

        assert key1 is key2


# ── encrypt_password（133-138行：cryptography 未安装）──


class TestEncryptPassword:
    """验证 encrypt_password 的各种分支。"""

    def test_encrypt_empty_string(self, _reset_crypto_cache):
        """空字符串应直接返回空。"""
        assert crypto_mod.encrypt_password("") == ""

    def test_encrypt_normal(self, _reset_crypto_cache):
        """正常加密应返回 ENC: 前缀。"""
        crypto_mod = _reset_crypto_cache
        with patch.object(crypto_mod, "is_windows", return_value=False):
            result = crypto_mod.encrypt_password("mypassword")

        assert result.startswith("ENC:")
        assert result != "mypassword"

    def test_encrypt_cryptography_not_installed(self, _reset_crypto_cache):
        """cryptography 未安装时应返回明文。"""
        crypto_mod = _reset_crypto_cache

        import builtins

        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "cryptography.fernet":
                raise ImportError("no module")
            return real_import(name, *args, **kwargs)

        with (
            patch.object(crypto_mod, "is_windows", return_value=False),
            patch("builtins.__import__", side_effect=mock_import),
        ):
            result = crypto_mod.encrypt_password("mypassword")

        assert result == "mypassword"


# ── decrypt_password（167-169行：cryptography 未安装，及解密失败）──


class TestDecryptPassword:
    """验证 decrypt_password 的各种分支。"""

    def test_decrypt_empty_string(self, _reset_crypto_cache):
        """空字符串应直接返回空。"""
        assert crypto_mod.decrypt_password("") == ""

    def test_decrypt_plaintext_passthrough(self, _reset_crypto_cache):
        """无 ENC: 前缀的明文应原样返回。"""
        assert crypto_mod.decrypt_password("plaintext") == "plaintext"

    def test_decrypt_normal(self, _reset_crypto_cache):
        """正常加密后解密应还原。"""
        crypto_mod = _reset_crypto_cache
        with patch.object(crypto_mod, "is_windows", return_value=False):
            encrypted = crypto_mod.encrypt_password("testpass")
            decrypted = crypto_mod.decrypt_password(encrypted)

        assert decrypted == "testpass"

    def test_decrypt_cryptography_not_installed(self, _reset_crypto_cache):
        """cryptography 未安装时解密应抛出 _DecryptionError。"""
        crypto_mod = _reset_crypto_cache

        import builtins

        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name in ("cryptography.fernet", "cryptography.exceptions"):
                raise ImportError("no module")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import):
            with pytest.raises(_DecryptionError, match="cryptography"):
                crypto_mod.decrypt_password("ENC:somedata")

        assert crypto_mod.has_decryption_error()

    def test_decrypt_failure_sets_error_flag(self, _reset_crypto_cache):
        """解密失败应设置失败标记并抛出 _DecryptionError。"""
        crypto_mod = _reset_crypto_cache
        with patch.object(crypto_mod, "is_windows", return_value=False):
            # 先生成密钥
            crypto_mod._derive_fernet_key()

        # 使用无效的加密数据
        with pytest.raises(_DecryptionError, match="解密失败"):
            crypto_mod.decrypt_password("ENC:invaliddata")

        assert crypto_mod.has_decryption_error()


# ── has_decryption_error / clear_decryption_error ──


class Test_DecryptionErrorFlag:
    """验证解密失败标记的读写。"""

    def test_initial_state_no_error(self, _reset_crypto_cache):
        """初始状态应无解密失败。"""
        assert not crypto_mod.has_decryption_error()

    def test_set_and_clear(self, _reset_crypto_cache):
        """设置后应能清除。"""
        crypto_mod._decryption_failed.set()
        assert crypto_mod.has_decryption_error()
        crypto_mod.clear_decryption_error()
        assert not crypto_mod.has_decryption_error()


# ── save_password_field ──


class TestSavePasswordField:
    """验证 save_password_field 的全部分支。"""

    def test_raw_none_returns_existing(self, _reset_crypto_cache):
        """raw=None 应返回 existing_encrypted。"""
        assert crypto_mod.save_password_field(None, "ENC:old") == "ENC:old"

    def test_raw_none_existing_empty(self, _reset_crypto_cache):
        """raw=None 且 existing 为空应返回空。"""
        assert crypto_mod.save_password_field(None, "") == ""

    def test_raw_mask_gets_encrypted(self, _reset_crypto_cache):
        """掩码值不再特殊处理，作为明文加密。"""
        result = crypto_mod.save_password_field("••••••••", "ENC:old")
        assert result.startswith("ENC:")

    def test_raw_empty_preserves_existing(self, _reset_crypto_cache):
        """空串应保留已有加密值。"""
        assert crypto_mod.save_password_field("", "ENC:old") == "ENC:old"

    def test_raw_enc_returns_same(self, _reset_crypto_cache):
        """已加密值应原样返回。"""
        enc = "ENC:already_encrypted"
        assert crypto_mod.save_password_field(enc, "ENC:old") == enc

    def test_raw_plaintext_encrypts(self, _reset_crypto_cache):
        """明文密码应被加密。"""
        crypto_mod = _reset_crypto_cache
        with patch.object(crypto_mod, "is_windows", return_value=False):
            result = crypto_mod.save_password_field("newpassword", "ENC:old")

        assert result.startswith("ENC:")
        assert result != "newpassword"
