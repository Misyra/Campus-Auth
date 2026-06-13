"""crypto.py 第 83 行 Windows 权限问题修复测试。

验证 USERNAME 环境变量缺失时，icacls 命令使用 getpass.getuser() 返回的真实用户名，
而非硬编码的 "Users" 组名。
"""

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def _reset_crypto_cache(tmp_path):
    """重置 crypto 模块的全局缓存，确保每次测试独立。"""
    import app.utils.crypto as crypto_mod

    old_raw = crypto_mod._cached_raw_key
    old_fernet = crypto_mod._cached_fernet_key
    old_dir = crypto_mod._KEY_DIR
    old_file = crypto_mod._KEY_FILE
    crypto_mod._cached_raw_key = None
    crypto_mod._cached_fernet_key = None
    crypto_mod._KEY_DIR = tmp_path
    crypto_mod._KEY_FILE = tmp_path / ".enc_key"
    yield crypto_mod
    crypto_mod._cached_raw_key = old_raw
    crypto_mod._cached_fernet_key = old_fernet
    crypto_mod._KEY_DIR = old_dir
    crypto_mod._KEY_FILE = old_file


class TestWindowsIcaclsUsername:
    """测试 Windows icacls 命令中的用户名来源。"""

    def test_icacls_uses_real_username_when_env_missing(self, _reset_crypto_cache):
        """当 USERNAME 环境变量不存在时，应使用 getpass.getuser() 返回的真实用户名，
        而非硬编码的 'Users' 组名。"""
        crypto_mod = _reset_crypto_cache
        fake_username = "RealTestUser"

        mock_run = MagicMock(return_value=MagicMock(returncode=0))

        # 模拟：is_windows=True，USERNAME 环境变量不存在，getpass.getuser 返回真实用户名
        # subprocess 在函数内局部 import，所以 mock "subprocess.run"
        with (
            patch.object(crypto_mod, "is_windows", return_value=True),
            patch("subprocess.run", mock_run),
            patch.dict("os.environ", {}, clear=True),
            patch("getpass.getuser", return_value=fake_username),
        ):
            crypto_mod._get_or_create_key()

        assert mock_run.called, "subprocess.run 应该被调用"
        cmd = mock_run.call_args[0][0]
        # cmd: ["icacls", path, "/inheritance:r", "/grant", "username:F"]
        grant_arg = cmd[4]
        assert grant_arg == f"{fake_username}:F", (
            f"icacls 应使用真实用户名 '{fake_username}'，实际为 '{grant_arg}'"
        )
        assert "Users:F" not in cmd, "不应使用 'Users' 组名作为默认值"

    def test_icacls_uses_env_username_when_present(self, _reset_crypto_cache):
        """当 USERNAME 环境变量存在时，应优先使用环境变量中的值。"""
        crypto_mod = _reset_crypto_cache
        mock_run = MagicMock(return_value=MagicMock(returncode=0))

        with (
            patch.object(crypto_mod, "is_windows", return_value=True),
            patch("subprocess.run", mock_run),
            patch.dict("os.environ", {"USERNAME": "EnvUser"}, clear=True),
        ):
            crypto_mod._get_or_create_key()

        assert mock_run.called
        cmd = mock_run.call_args[0][0]
        assert cmd[4] == "EnvUser:F"
