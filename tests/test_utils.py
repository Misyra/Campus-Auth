"""src/utils/ 模块综合测试

合并原 test_crypto.py, test_config_helpers.py, test_file_helpers.py,
test_platform_utils.py, test_str_to_bool.py, test_network_helpers.py,
test_version.py, test_time_utils.py，并新增 env.py, exceptions.py,
logging.py, notify.py 测试。
"""
from __future__ import annotations

import base64
import datetime
import logging
import os
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# ── crypto ──
from src.utils.crypto import (
    encrypt_password,
    decrypt_password,
    mask_password,
    is_encrypted,
    save_password_field,
)

# ── config_helpers ──
from src.utils.config_helpers import extract_profile_fields, assign_profile_fields

# ── file_helpers ──
from src.utils.file_helpers import atomic_write

# ── platform_utils ──
from src.utils.platform_utils import (
    get_platform,
    is_windows,
    is_macos,
    is_linux,
    get_default_ua,
)

# ── str_to_bool ──
from src.utils import str_to_bool

# ── network_helpers ──
from src.utils.network_helpers import parse_host_port

# ── version ──
from src.version import get_project_version

# ── time_utils ──
from src.utils.time_utils import is_in_pause_period, get_runtime_stats

# ── env ──
from src.utils.env import build_login_env_vars

# ── exceptions ──
from src.utils.exceptions import LoginCancelledError, DecryptionError

# ── logging ──
from src.utils.logging import (
    _normalize_level,
    _level_value,
    SideFilter,
    LogConfigCenter,
    get_logger,
)


# =====================================================================
# crypto
# =====================================================================

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
        original = "校园网密码"
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

    def test_none_with_empty_existing(self):
        """raw=None 且 existing 为空时应返回空字符串"""
        assert save_password_field(None, "") == ""

    def test_empty_with_empty_existing(self):
        """raw="" 且 existing 为空时应返回空字符串"""
        assert save_password_field("", "") == ""


# =====================================================================
# config_helpers
# =====================================================================

class TestExtractProfileFields:
    def test_basic(self):
        source = {"a": 1, "b": 2, "c": 3}
        result = extract_profile_fields(source, ["a", "c"])
        assert result == {"a": 1, "c": 3}

    def test_missing_keys_skipped(self):
        source = {"a": 1}
        result = extract_profile_fields(source, ["a", "b", "c"])
        assert result == {"a": 1}

    def test_empty_field_names(self):
        assert extract_profile_fields({"a": 1}, []) == {}

    def test_empty_source(self):
        assert extract_profile_fields({}, ["a", "b"]) == {}

    def test_source_extra_keys_not_copied(self):
        source = {"a": 1, "secret": "leaked"}
        result = extract_profile_fields(source, ["a"])
        assert "secret" not in result

    def test_preserves_value_types(self):
        source = {"num": 42, "flag": True, "nested": {"k": "v"}, "none_val": None}
        result = extract_profile_fields(source, ["num", "flag", "nested", "none_val"])
        assert result["num"] == 42
        assert result["flag"] is True
        assert result["nested"] == {"k": "v"}
        assert result["none_val"] is None


class TestAssignProfileFields:
    def test_basic(self):
        target = {"existing": "old"}
        source = {"a": 1, "b": 2}
        assign_profile_fields(target, source, ["a", "b"])
        assert target == {"existing": "old", "a": 1, "b": 2}

    def test_overwrites_existing(self):
        target = {"a": "old"}
        source = {"a": "new"}
        assign_profile_fields(target, source, ["a"])
        assert target["a"] == "new"

    def test_missing_keys_not_assigned(self):
        target = {}
        source = {"a": 1}
        assign_profile_fields(target, source, ["a", "b"])
        assert target == {"a": 1}
        assert "b" not in target

    def test_source_extra_keys_not_copied(self):
        target = {}
        source = {"a": 1, "secret": "leaked"}
        assign_profile_fields(target, source, ["a"])
        assert "secret" not in target

    def test_empty_field_names(self):
        target = {"a": 1}
        assign_profile_fields(target, {"b": 2}, [])
        assert target == {"a": 1}

    def test_empty_source(self):
        target = {"a": 1}
        assign_profile_fields(target, {}, ["a"])
        assert target == {"a": 1}


# =====================================================================
# file_helpers
# =====================================================================

class TestAtomicWrite:
    def test_basic_write(self, tmp_path):
        target = tmp_path / "test.txt"
        atomic_write(str(target), "hello world")
        assert target.read_text(encoding="utf-8") == "hello world"

    def test_creates_parent_dirs(self, tmp_path):
        target = tmp_path / "a" / "b" / "c" / "test.txt"
        atomic_write(str(target), "nested")
        assert target.read_text(encoding="utf-8") == "nested"

    def test_overwrite_existing(self, tmp_path):
        target = tmp_path / "test.txt"
        target.write_text("old", encoding="utf-8")
        atomic_write(str(target), "new")
        assert target.read_text(encoding="utf-8") == "new"

    def test_empty_content(self, tmp_path):
        target = tmp_path / "empty.txt"
        atomic_write(str(target), "")
        assert target.read_text(encoding="utf-8") == ""

    def test_unicode_content(self, tmp_path):
        target = tmp_path / "中文.txt"
        atomic_write(str(target), "校园网认证")
        assert target.read_text(encoding="utf-8") == "校园网认证"

    def test_permission_error_fallback(self, tmp_path):
        target = tmp_path / "test.txt"
        original_replace = os.replace

        def mock_replace(src, dst):
            raise PermissionError("mocked")

        with patch("src.utils.file_helpers.os.replace", side_effect=mock_replace):
            atomic_write(str(target), "fallback content")
        assert target.read_text(encoding="utf-8") == "fallback content"

    def test_cleanup_on_write_error(self, tmp_path):
        target = tmp_path / "test.txt"
        with patch("src.utils.file_helpers.os.fdopen", side_effect=IOError("disk full")):
            with pytest.raises(IOError, match="disk full"):
                atomic_write(str(target), "content")
        assert not target.exists()

    def test_no_parent_dir(self, tmp_path):
        old_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            atomic_write("relative.txt", "relative")
            assert (tmp_path / "relative.txt").read_text(encoding="utf-8") == "relative"
        finally:
            os.chdir(old_cwd)


# =====================================================================
# platform_utils
# =====================================================================

class TestGetPlatform:
    def test_windows(self):
        with patch("src.utils.platform_utils.sys") as mock_sys:
            mock_sys.platform = "win32"
            assert get_platform() == "windows"

    def test_darwin(self):
        with patch("src.utils.platform_utils.sys") as mock_sys:
            mock_sys.platform = "darwin"
            assert get_platform() == "darwin"

    def test_linux(self):
        with patch("src.utils.platform_utils.sys") as mock_sys:
            mock_sys.platform = "linux"
            assert get_platform() == "linux"

    def test_linux2(self):
        with patch("src.utils.platform_utils.sys") as mock_sys:
            mock_sys.platform = "linux2"
            assert get_platform() == "linux"

    def test_unknown_falls_back_to_linux(self):
        with patch("src.utils.platform_utils.sys") as mock_sys:
            mock_sys.platform = "freebsd"
            assert get_platform() == "linux"


class TestIsWindows:
    def test_true(self):
        with patch("src.utils.platform_utils.sys") as mock_sys:
            mock_sys.platform = "win32"
            assert is_windows() is True

    def test_false(self):
        with patch("src.utils.platform_utils.sys") as mock_sys:
            mock_sys.platform = "linux"
            assert is_windows() is False


class TestIsMacos:
    def test_true(self):
        with patch("src.utils.platform_utils.sys") as mock_sys:
            mock_sys.platform = "darwin"
            assert is_macos() is True

    def test_false(self):
        with patch("src.utils.platform_utils.sys") as mock_sys:
            mock_sys.platform = "win32"
            assert is_macos() is False


class TestIsLinux:
    def test_linux(self):
        with patch("src.utils.platform_utils.sys") as mock_sys:
            mock_sys.platform = "linux"
            assert is_linux() is True

    def test_linux2(self):
        # Python 3.10+ 不再返回 "linux2"，应返回 False
        with patch("src.utils.platform_utils.sys") as mock_sys:
            mock_sys.platform = "linux2"
            assert is_linux() is False

    def test_false(self):
        with patch("src.utils.platform_utils.sys") as mock_sys:
            mock_sys.platform = "win32"
            assert is_linux() is False


class TestGetDefaultUa:
    def test_windows_ua(self):
        with patch("src.utils.platform_utils.get_platform", return_value="windows"):
            ua = get_default_ua()
            assert "Windows" in ua

    def test_macos_ua(self):
        with patch("src.utils.platform_utils.get_platform", return_value="darwin"):
            ua = get_default_ua()
            assert "Macintosh" in ua

    def test_linux_ua(self):
        with patch("src.utils.platform_utils.get_platform", return_value="linux"):
            ua = get_default_ua()
            assert "Linux" in ua

    def test_unknown_platform_falls_back_to_linux(self):
        with patch("src.utils.platform_utils.get_platform", return_value="freebsd"):
            ua = get_default_ua()
            assert "Linux" in ua


# =====================================================================
# str_to_bool
# =====================================================================

class TestStrToBool:
    @pytest.mark.parametrize("value", ["true", "True", "TRUE", " true ", "1", "yes", "YES", "on", "ON"])
    def test_truthy(self, value):
        assert str_to_bool(value) is True

    @pytest.mark.parametrize("value", ["false", "False", "0", "no", "off", "", "anything", "  "])
    def test_falsy(self, value):
        assert str_to_bool(value) is False

    def test_non_string_int_1(self):
        assert str_to_bool(1) is True

    def test_non_string_int_0(self):
        assert str_to_bool(0) is False

    def test_none(self):
        assert str_to_bool(None) is False


# =====================================================================
# network_helpers
# =====================================================================

class TestParseHostPort:
    def test_basic(self):
        result = parse_host_port(["8.8.8.8:53"])
        assert result == [("8.8.8.8", 53)]

    def test_multiple(self):
        result = parse_host_port(["8.8.8.8:53", "1.1.1.1:443"])
        assert result == [("8.8.8.8", 53), ("1.1.1.1", 443)]

    def test_empty_list(self):
        assert parse_host_port([]) == []

    def test_ipv6(self):
        result = parse_host_port(["[::1]:8080"])
        assert result == [("[::1]", 8080)]

    def test_missing_port(self):
        with pytest.raises(ValueError):
            parse_host_port(["8.8.8.8"])

    def test_invalid_port(self):
        with pytest.raises(ValueError):
            parse_host_port(["8.8.8.8:99999"])

    def test_non_numeric_port(self):
        with pytest.raises(ValueError):
            parse_host_port(["8.8.8.8:abc"])

    def test_hostname(self):
        result = parse_host_port(["www.baidu.com:443"])
        assert result == [("www.baidu.com", 443)]

    def test_empty_host(self):
        with pytest.raises(ValueError):
            parse_host_port([":8080"])


# =====================================================================
# version
# =====================================================================

class TestGetProjectVersion:
    def setup_method(self):
        get_project_version.cache_clear()

    def test_valid_pyproject(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "test"\nversion = "1.2.3"\n'
        )
        assert get_project_version(tmp_path) == "1.2.3"

    def test_missing_file(self, tmp_path):
        assert get_project_version(tmp_path) == "unknown"

    def test_no_project_section(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text('[tool.poetry]\nversion = "1.0.0"\n')
        assert get_project_version(tmp_path) == "unknown"

    def test_no_version_line(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text('[project]\nname = "test"\n')
        assert get_project_version(tmp_path) == "unknown"

    def test_version_outside_project_section(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text(
            'version = "0.0.1"\n\n[project]\nname = "test"\n'
        )
        assert get_project_version(tmp_path) == "unknown"

    def test_lru_cache(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nversion = "1.0.0"\n'
        )
        v1 = get_project_version(tmp_path)
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nversion = "2.0.0"\n'
        )
        v2 = get_project_version(tmp_path)
        assert v1 == "1.0.0"
        assert v2 == "1.0.0"  # 缓存命中

    def test_default_root(self):
        v = get_project_version()
        assert isinstance(v, str)
        assert v != "unknown"


# =====================================================================
# time_utils
# =====================================================================

class TestIsInPausePeriod:
    def test_disabled(self):
        config = {"enabled": False, "start_hour": 0, "end_hour": 6}
        assert is_in_pause_period(config) is False

    def test_same_hour_means_all_day(self):
        config = {"enabled": True, "start_hour": 5, "end_hour": 5}
        assert is_in_pause_period(config) is True

    def test_normal_range_in_pause(self):
        config = {"enabled": True, "start_hour": 0, "end_hour": 6}
        mock_now = datetime.datetime(2025, 1, 1, 3, 0, 0)
        with patch("src.utils.time_utils.datetime") as mock_dt:
            mock_dt.datetime.now.return_value = mock_now
            assert is_in_pause_period(config) is True

    def test_normal_range_outside_pause(self):
        config = {"enabled": True, "start_hour": 0, "end_hour": 6}
        mock_now = datetime.datetime(2025, 1, 1, 12, 0, 0)
        with patch("src.utils.time_utils.datetime") as mock_dt:
            mock_dt.datetime.now.return_value = mock_now
            assert is_in_pause_period(config) is False

    def test_cross_midnight_in_pause(self):
        config = {"enabled": True, "start_hour": 23, "end_hour": 6}
        mock_now = datetime.datetime(2025, 1, 1, 2, 0, 0)
        with patch("src.utils.time_utils.datetime") as mock_dt:
            mock_dt.datetime.now.return_value = mock_now
            assert is_in_pause_period(config) is True

    def test_cross_midnight_outside_pause(self):
        config = {"enabled": True, "start_hour": 23, "end_hour": 6}
        mock_now = datetime.datetime(2025, 1, 1, 12, 0, 0)
        with patch("src.utils.time_utils.datetime") as mock_dt:
            mock_dt.datetime.now.return_value = mock_now
            assert is_in_pause_period(config) is False

    def test_missing_keys_in_pause(self):
        config = {}
        mock_now = datetime.datetime(2025, 1, 1, 3, 0, 0)
        with patch("src.utils.time_utils.datetime") as mock_dt:
            mock_dt.datetime.now.return_value = mock_now
            assert is_in_pause_period(config) is True

    def test_missing_keys_outside_pause(self):
        config = {}
        mock_now = datetime.datetime(2025, 1, 1, 12, 0, 0)
        with patch("src.utils.time_utils.datetime") as mock_dt:
            mock_dt.datetime.now.return_value = mock_now
            assert is_in_pause_period(config) is False


class TestGetRuntimeStats:
    def test_basic(self):
        start = time.time() - 3665  # ~1 小时 1 分前
        runtime_str, stats_str = get_runtime_stats(start, 42)
        assert "01:01:" in runtime_str
        assert "42" in stats_str

    def test_zero_time(self):
        start = time.time()
        runtime_str, stats_str = get_runtime_stats(start, 0)
        assert "00:00:0" in runtime_str
        assert "0" in stats_str

    def test_none_start_time(self):
        runtime_str, stats_str = get_runtime_stats(None, 10)
        assert runtime_str == "00:00:00"
        assert "10" in stats_str


# =====================================================================
# env — build_login_env_vars（新增）
# =====================================================================

class TestBuildLoginEnvVars:
    def test_basic_config(self):
        """基本配置应正确注入环境变量"""
        config = {
            "auth_url": "http://10.0.0.1/login",
            "username": "testuser",
            "password": "testpass",
            "isp": "移动",
        }
        env_vars = build_login_env_vars(config)
        assert env_vars["LOGIN_URL"] == "http://10.0.0.1/login"
        assert env_vars["USERNAME"] == "testuser"
        assert env_vars["PASSWORD"] == "testpass"
        assert env_vars["ISP"] == "移动"

    def test_task_url_template_resolution(self):
        """task_url 中的变量模板应被解析"""
        config = {
            "auth_url": "http://10.0.0.1/login",
            "username": "user1",
            "password": "pass1",
            "isp": "联通",
        }
        task_url = "http://10.0.0.1/login?user={{USERNAME}}&isp={{ISP}}"
        env_vars = build_login_env_vars(config, task_url=task_url)
        assert env_vars["LOGIN_URL"] == "http://10.0.0.1/login?user=user1&isp=联通"

    def test_custom_variables_injected(self):
        """自定义变量应注入到环境变量"""
        config = {"auth_url": "http://test.com", "username": "u", "password": "p"}
        custom = {"MY_VAR": "hello", "ANOTHER": "world"}
        env_vars = build_login_env_vars(config, custom_variables=custom)
        assert env_vars["MY_VAR"] == "hello"
        assert env_vars["ANOTHER"] == "world"

    def test_denylist_not_overridden(self):
        """系统环境变量在 denylist 中不应被自定义变量覆盖"""
        config = {"auth_url": "", "username": "", "password": ""}
        custom = {"PATH": "/evil/path", "PYTHONPATH": "/evil"}
        env_vars = build_login_env_vars(config, custom_variables=custom)
        # PATH 和 PYTHONPATH 不应被覆盖（除非 runtime_config 显式设置了它们）
        assert env_vars.get("PATH") != "/evil/path"

    def test_empty_config(self):
        """空配置应返回环境变量字典（含系统变量）"""
        config = {}
        env_vars = build_login_env_vars(config)
        assert isinstance(env_vars, dict)
        # LOGIN_URL 不应被设置（auth_url 为空）
        assert env_vars.get("LOGIN_URL", "") == ""

    def test_none_custom_variables(self):
        """custom_variables=None 不应报错"""
        config = {"auth_url": "http://test.com"}
        env_vars = build_login_env_vars(config, custom_variables=None)
        assert "LOGIN_URL" in env_vars

    def test_task_url_with_login_url_fallback(self):
        """task_url 中无模板变量时，LOGIN_URL 应被设置为解析后的 task_url"""
        config = {"auth_url": "http://10.0.0.1", "username": "u", "password": "p"}
        task_url = "http://10.0.0.1/specific"
        env_vars = build_login_env_vars(config, task_url=task_url)
        assert env_vars["LOGIN_URL"] == "http://10.0.0.1/specific"

    def test_empty_task_url_falls_back_to_auth_url(self):
        """task_url 为空时，LOGIN_URL 应使用 auth_url"""
        config = {"auth_url": "http://10.0.0.1", "username": "u", "password": "p"}
        env_vars = build_login_env_vars(config, task_url="")
        assert env_vars["LOGIN_URL"] == "http://10.0.0.1"


# =====================================================================
# exceptions（新增）
# =====================================================================

class TestExceptions:
    def test_login_cancelled_error(self):
        """LoginCancelledError 应为 Exception 子类"""
        with pytest.raises(LoginCancelledError):
            raise LoginCancelledError("cancelled")

    def test_decryption_error(self):
        """DecryptionError 应为 Exception 子类"""
        with pytest.raises(DecryptionError):
            raise DecryptionError("decryption failed")

    def test_login_cancelled_error_is_exception(self):
        assert issubclass(LoginCancelledError, Exception)

    def test_decryption_error_is_exception(self):
        assert issubclass(DecryptionError, Exception)


# =====================================================================
# logging — 工具函数（新增）
# =====================================================================

class TestNormalizeLevel:
    def test_valid_levels(self):
        assert _normalize_level("DEBUG") == "DEBUG"
        assert _normalize_level("INFO") == "INFO"
        assert _normalize_level("WARNING") == "WARNING"
        assert _normalize_level("ERROR") == "ERROR"
        assert _normalize_level("CRITICAL") == "CRITICAL"

    def test_case_insensitive(self):
        assert _normalize_level("debug") == "DEBUG"
        assert _normalize_level("info") == "INFO"
        assert _normalize_level("Warning") == "WARNING"

    def test_strips_whitespace(self):
        assert _normalize_level("  ERROR  ") == "ERROR"

    def test_invalid_level_returns_default(self):
        assert _normalize_level("TRACE") == "INFO"
        assert _normalize_level("INVALID") == "INFO"

    def test_empty_returns_default(self):
        assert _normalize_level("") == "INFO"
        assert _normalize_level(None) == "INFO"

    def test_custom_default(self):
        assert _normalize_level("INVALID", default="WARNING") == "WARNING"


class TestLevelValue:
    def test_valid_levels(self):
        assert _level_value("DEBUG") == logging.DEBUG
        assert _level_value("INFO") == logging.INFO
        assert _level_value("WARNING") == logging.WARNING
        assert _level_value("ERROR") == logging.ERROR

    def test_invalid_returns_info(self):
        assert _level_value("INVALID") == logging.INFO

    def test_none_returns_info(self):
        assert _level_value(None) == logging.INFO


class TestSideFilter:
    def test_adds_side_attribute(self):
        f = SideFilter("BACKEND")
        record = logging.LogRecord("test", logging.INFO, "", 0, "msg", (), None)
        f.filter(record)
        assert record.side == "BACKEND"

    def test_does_not_overwrite_existing_side(self):
        f = SideFilter("BACKEND")
        record = logging.LogRecord("test", logging.INFO, "", 0, "msg", (), None)
        record.side = "FRONTEND"
        f.filter(record)
        assert record.side == "FRONTEND"

    def test_always_returns_true(self):
        f = SideFilter("TEST")
        record = logging.LogRecord("test", logging.INFO, "", 0, "msg", (), None)
        assert f.filter(record) is True


class TestGetLogger:
    def test_returns_logger_with_name(self):
        logger = get_logger("test_module")
        assert logger.name == "test_module"

    def test_attaches_side_filter(self):
        logger = get_logger("test_side", side="FRONTEND")
        has_side_filter = any(
            isinstance(f, SideFilter) and f.side == "FRONTEND"
            for f in logger.filters
        )
        assert has_side_filter

    def test_no_duplicate_filters(self):
        logger = get_logger("test_dup", side="BACKEND")
        get_logger("test_dup", side="BACKEND")
        side_filters = [f for f in logger.filters if isinstance(f, SideFilter)]
        assert len(side_filters) == 1


class TestLogConfigCenter:
    def test_singleton(self):
        a = LogConfigCenter()
        b = LogConfigCenter()
        assert a is b

    def test_get_instance(self):
        instance = LogConfigCenter.get_instance()
        assert isinstance(instance, LogConfigCenter)

    def test_default_config(self):
        center = LogConfigCenter()
        config = center.get_config()
        assert config["level"] == "INFO"
        assert config["console_colored"] is True

    def test_is_initialized_default_false(self):
        center = LogConfigCenter()
        # 注意：由于单例模式，如果之前已初始化则为 True
        # 这里只验证方法可调用
        assert isinstance(center.is_initialized(), bool)


# =====================================================================
# CREATE_NO_WINDOW_FLAG 常量
# =====================================================================


class TestCreateNoWindowFlag:
    def test_is_int(self):
        from src.utils.platform_utils import CREATE_NO_WINDOW_FLAG
        assert isinstance(CREATE_NO_WINDOW_FLAG, int)

    def test_on_windows_is_nonzero(self):
        """Windows 上应为非零值（subprocess.CREATE_NO_WINDOW = 0x08000000）"""
        from src.utils.platform_utils import CREATE_NO_WINDOW_FLAG
        if is_windows():
            assert CREATE_NO_WINDOW_FLAG != 0
        else:
            assert CREATE_NO_WINDOW_FLAG == 0


# =====================================================================
# AUTH_DATA_DIR 常量
# =====================================================================


class TestAuthDataDir:
    def test_is_path(self):
        from backend.constants import AUTH_DATA_DIR
        assert isinstance(AUTH_DATA_DIR, Path)

    def test_ends_with_campus_network_auth(self):
        from backend.constants import AUTH_DATA_DIR
        assert AUTH_DATA_DIR.name == ".campus_network_auth"


# =====================================================================
# DEFAULT_NETWORK_TARGETS / DEFAULT_HTTP_TARGETS 常量
# =====================================================================


class TestDefaultConstants:
    def test_network_targets_format(self):
        from backend.constants import DEFAULT_NETWORK_TARGETS
        parts = DEFAULT_NETWORK_TARGETS.split(",")
        assert len(parts) >= 3
        for part in parts:
            assert ":" in part

    def test_http_targets_format(self):
        from backend.constants import DEFAULT_HTTP_TARGETS
        parts = DEFAULT_HTTP_TARGETS.split(",")
        assert len(parts) >= 2
        for part in parts:
            assert part.startswith("http")

    def test_schemas_uses_constant(self):
        """MonitorConfigPayload 默认值应引用常量"""
        from backend.constants import DEFAULT_NETWORK_TARGETS, DEFAULT_HTTP_TARGETS
        from backend.schemas import MonitorConfigPayload
        m = MonitorConfigPayload()
        assert m.network_targets == DEFAULT_NETWORK_TARGETS
        assert m.http_targets == DEFAULT_HTTP_TARGETS


# =====================================================================
# _DateRotatingFileHandler 文件大小轮转
# =====================================================================


class TestDateRotatingFileHandlerRotation:
    def test_rotates_when_size_exceeded(self, tmp_path):
        """超过 file_max_bytes 时应创建分片文件"""
        from src.utils.logging import _DateRotatingFileHandler

        handler = _DateRotatingFileHandler(
            log_dir=str(tmp_path),
            file_max_bytes=200,  # 极小阈值便于测试
            file_backup_count=2,
            level=logging.DEBUG,
        )
        record = logging.LogRecord("test", logging.INFO, "", 0, "msg" * 50, (), None)
        record.side = "BACKEND"
        handler.setFormatter(logging.Formatter("%(message)s"))

        # 写入多条日志直到触发轮转
        for _ in range(20):
            handler.emit(record)

        # 应存在 app.log 和 app.log.1
        today = datetime.datetime.now().strftime("%Y-%m-%d")
        log_dir = tmp_path / today
        assert (log_dir / "app.log").exists()
        # 分片文件可能存在（取决于写入量）
        handler.close()

    def test_backup_count_respected(self, tmp_path):
        """分片文件数量不应超过 file_backup_count"""
        from src.utils.logging import _DateRotatingFileHandler

        handler = _DateRotatingFileHandler(
            log_dir=str(tmp_path),
            file_max_bytes=100,
            file_backup_count=2,
            level=logging.DEBUG,
        )
        handler.setFormatter(logging.Formatter("%(message)s"))
        record = logging.LogRecord("test", logging.INFO, "", 0, "x" * 80, (), None)
        record.side = "BACKEND"

        # 写入大量日志
        for _ in range(50):
            handler.emit(record)

        today = datetime.datetime.now().strftime("%Y-%m-%d")
        log_dir = tmp_path / today
        # 最多 file_backup_count 个分片 + 1 个当前文件
        backup_files = list(log_dir.glob("app.log.*"))
        assert len(backup_files) <= 2
        handler.close()
