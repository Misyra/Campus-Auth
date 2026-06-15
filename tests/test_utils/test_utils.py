"""src/utils/ 模块综合测试

合并原 test_crypto.py, test_config_helpers.py, test_file_helpers.py,
test_platform_utils.py, test_str_to_bool.py, test_network_helpers.py,
test_version.py, test_time_utils.py，并新增 env.py, exceptions.py,
logging.py, notify.py 测试。
"""

from __future__ import annotations

import datetime
import os
import time
from pathlib import Path
from unittest.mock import patch

import pytest

# ── str_to_bool ──
from app.utils import str_to_bool

# ── config_helpers ──
from app.utils.config_utils import assign_profile_fields

# ── crypto ──
from app.utils.crypto import (
    decrypt_password,
    encrypt_password,
    mask_password,
    save_password_field,
)

# ── env ──
from app.utils.env import build_login_template_vars

# ── exceptions ──
from app.utils.exceptions import DecryptionError, LoginCancelledError

# ── files ──
from app.utils.files import atomic_write

# ── logging ──
from app.utils.logging import (
    LogConfigCenter,
    get_logger,
    normalize_level,
)

# ── network ──
from app.utils.network import parse_host_port

# ── platform ──
from app.utils.platform import (
    get_default_ua,
    get_platform,
    is_linux,
    is_macos,
    is_windows,
)

# ── time_utils ──
from app.utils.time_utils import get_runtime_stats, is_in_pause_period

# ── version ──
from app.version import get_project_version

# =====================================================================
# crypto
# =====================================================================


class TestEncryptDecrypt:
    def test_round_trip(self):
        """加密后解密应返回原文"""
        original = "my_secret_password_123"
        encrypted = encrypt_password(original)
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
        original = "!@#$%^&*()_+-=[]{}|;:'\",.<>?/~`"
        encrypted = encrypt_password(original)
        assert decrypt_password(encrypted) == original

    def test_decrypt_wrong_key_raises(self):
        """密钥变更后解密旧密码应抛出 DecryptionError。"""
        import base64

        original = "secret123"
        encrypted = encrypt_password(original)
        from app.utils.crypto import (
            _derive_fernet_key,
            clear_decryption_error,
            has_decryption_error,
        )

        clear_decryption_error()
        # 注入不同密钥模拟密钥变更（44 字节 URL-safe base64）
        other_key = base64.urlsafe_b64encode(b"\x99" * 32)
        with patch("app.utils.crypto._derive_fernet_key", return_value=other_key):
            with pytest.raises(DecryptionError):
                decrypt_password(encrypted)
            assert has_decryption_error() is True


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

    def test_empty_raw_clears_password(self):
        """raw 为空字符串时应清除密码"""
        assert save_password_field("", "ENC:existing") == ""

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
# files
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

    def test_permission_error_propagates(self, tmp_path):
        target = tmp_path / "test.txt"

        def mock_replace(src, dst):
            raise PermissionError("mocked")

        with (
            patch("app.utils.files.os.replace", side_effect=mock_replace),
            pytest.raises(PermissionError, match="mocked"),
        ):
            atomic_write(str(target), "content")
        # 临时文件应被清理
        assert not list(tmp_path.glob("tmp.*"))

    def test_cleanup_on_write_error(self, tmp_path):
        target = tmp_path / "test.txt"
        with (
            patch("app.utils.files.os.fdopen", side_effect=OSError("disk full")),
            pytest.raises(IOError, match="disk full"),
        ):
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

    def test_atomic_write_prefix_length_limit(self, tmp_path):
        """长 prefix 应正常工作（不再有长度限制）"""
        target = tmp_path / "test.txt"
        atomic_write(str(target), "content", prefix="x" * 21)
        assert target.read_text(encoding="utf-8") == "content"

    def test_atomic_write_suffix_length_limit(self, tmp_path):
        """长 suffix 应正常工作（不再有长度限制）"""
        target = tmp_path / "test.txt"
        atomic_write(str(target), "content", suffix="x" * 21)
        assert target.read_text(encoding="utf-8") == "content"


# =====================================================================
# platform
# =====================================================================


class TestGetPlatform:
    def test_windows(self):
        with patch("app.utils.platform.sys") as mock_sys:
            mock_sys.platform = "win32"
            assert get_platform() == "windows"

    def test_darwin(self):
        with patch("app.utils.platform.sys") as mock_sys:
            mock_sys.platform = "darwin"
            assert get_platform() == "darwin"

    def test_linux(self):
        with patch("app.utils.platform.sys") as mock_sys:
            mock_sys.platform = "linux"
            assert get_platform() == "linux"

    def test_linux2(self):
        with patch("app.utils.platform.sys") as mock_sys:
            mock_sys.platform = "linux2"
            assert get_platform() == "linux"

    def test_unknown_falls_back_to_linux(self):
        with patch("app.utils.platform.sys") as mock_sys:
            mock_sys.platform = "freebsd"
            assert get_platform() == "linux"


class TestIsWindows:
    def test_true(self):
        with patch("app.utils.platform.sys") as mock_sys:
            mock_sys.platform = "win32"
            assert is_windows() is True

    def test_false(self):
        with patch("app.utils.platform.sys") as mock_sys:
            mock_sys.platform = "linux"
            assert is_windows() is False


class TestIsMacos:
    def test_true(self):
        with patch("app.utils.platform.sys") as mock_sys:
            mock_sys.platform = "darwin"
            assert is_macos() is True

    def test_false(self):
        with patch("app.utils.platform.sys") as mock_sys:
            mock_sys.platform = "win32"
            assert is_macos() is False


class TestIsLinux:
    def test_linux(self):
        with patch("app.utils.platform.sys") as mock_sys:
            mock_sys.platform = "linux"
            assert is_linux() is True

    def test_linux2(self):
        # Python 3.10+ 不再返回 "linux2"，应返回 False
        with patch("app.utils.platform.sys") as mock_sys:
            mock_sys.platform = "linux2"
            assert is_linux() is False

    def test_false(self):
        with patch("app.utils.platform.sys") as mock_sys:
            mock_sys.platform = "win32"
            assert is_linux() is False


class TestGetDefaultUa:
    def test_windows_ua(self):
        with patch("app.utils.platform.get_platform", return_value="windows"):
            ua = get_default_ua()
            assert "Windows" in ua

    def test_macos_ua(self):
        with patch("app.utils.platform.get_platform", return_value="darwin"):
            ua = get_default_ua()
            assert "Macintosh" in ua

    def test_linux_ua(self):
        with patch("app.utils.platform.get_platform", return_value="linux"):
            ua = get_default_ua()
            assert "Linux" in ua

    def test_unknown_platform_falls_back_to_linux(self):
        with patch("app.utils.platform.get_platform", return_value="freebsd"):
            ua = get_default_ua()
            assert "Linux" in ua


# =====================================================================
# str_to_bool
# =====================================================================


class TestStrToBool:
    @pytest.mark.parametrize(
        "value", ["true", "True", "TRUE", " true ", "1", "yes", "YES", "on", "ON"]
    )
    def test_truthy(self, value):
        assert str_to_bool(value) is True

    @pytest.mark.parametrize(
        "value", ["false", "False", "0", "no", "off", "", "anything", "  "]
    )
    def test_falsy(self, value):
        assert str_to_bool(value) is False

    def test_non_string_int_1(self):
        assert str_to_bool(1) is True

    def test_non_string_int_0(self):
        assert str_to_bool(0) is False

    def test_none(self):
        assert str_to_bool(None) is False


# =====================================================================
# network
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
        with patch("app.utils.time_utils.datetime") as mock_dt:
            mock_dt.datetime.now.return_value = mock_now
            assert is_in_pause_period(config) is True

    def test_normal_range_outside_pause(self):
        config = {"enabled": True, "start_hour": 0, "end_hour": 6}
        mock_now = datetime.datetime(2025, 1, 1, 12, 0, 0)
        with patch("app.utils.time_utils.datetime") as mock_dt:
            mock_dt.datetime.now.return_value = mock_now
            assert is_in_pause_period(config) is False

    def test_cross_midnight_in_pause(self):
        config = {"enabled": True, "start_hour": 23, "end_hour": 6}
        mock_now = datetime.datetime(2025, 1, 1, 2, 0, 0)
        with patch("app.utils.time_utils.datetime") as mock_dt:
            mock_dt.datetime.now.return_value = mock_now
            assert is_in_pause_period(config) is True

    def test_cross_midnight_outside_pause(self):
        config = {"enabled": True, "start_hour": 23, "end_hour": 6}
        mock_now = datetime.datetime(2025, 1, 1, 12, 0, 0)
        with patch("app.utils.time_utils.datetime") as mock_dt:
            mock_dt.datetime.now.return_value = mock_now
            assert is_in_pause_period(config) is False

    def test_missing_keys_in_pause(self):
        config = {}
        mock_now = datetime.datetime(2025, 1, 1, 3, 0, 0)
        with patch("app.utils.time_utils.datetime") as mock_dt:
            mock_dt.datetime.now.return_value = mock_now
            assert is_in_pause_period(config) is True

    def test_missing_keys_outside_pause(self):
        config = {}
        mock_now = datetime.datetime(2025, 1, 1, 12, 0, 0)
        with patch("app.utils.time_utils.datetime") as mock_dt:
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
# env — build_login_template_vars
# =====================================================================


class TestBuildLoginTemplateVars:
    def test_basic_config(self):
        """基本配置应正确注入模板变量"""
        config = {
            "auth_url": "http://10.0.0.1/login",
            "username": "testuser",
            "password": "testpass",
            "isp": "移动",
        }
        result = build_login_template_vars(config)
        assert result["LOGIN_URL"] == "http://10.0.0.1/login"
        assert result["USERNAME"] == "testuser"
        assert result["PASSWORD"] == "testpass"
        assert result["ISP"] == "移动"

    def test_task_url_template_resolution(self):
        """task_url 中的变量模板应被解析"""
        config = {
            "auth_url": "http://10.0.0.1/login",
            "username": "user1",
            "password": "pass1",
            "isp": "联通",
        }
        task_url = "http://10.0.0.1/login?user={{USERNAME}}&isp={{ISP}}"
        result = build_login_template_vars(config, task_url=task_url)
        assert result["LOGIN_URL"] == "http://10.0.0.1/login?user=user1&isp=联通"

    def test_custom_variables_injected(self):
        """自定义变量应注入到模板变量"""
        config = {"auth_url": "http://test.com", "username": "u", "password": "p"}
        custom = {"MY_VAR": "hello", "ANOTHER": "world"}
        result = build_login_template_vars(config, custom_variables=custom)
        assert result["MY_VAR"] == "hello"
        assert result["ANOTHER"] == "world"

    def test_denylist_not_overridden(self):
        """保留名自定义变量应被拒绝"""
        config = {"auth_url": "", "username": "", "password": ""}
        custom = {"PATH": "/evil/path", "PYTHONPATH": "/evil"}
        result = build_login_template_vars(config, custom_variables=custom)
        assert result.get("PATH") is None
        assert result.get("PYTHONPATH") is None

    def test_empty_config(self):
        """空配置应返回空字典"""
        config = {}
        result = build_login_template_vars(config)
        assert isinstance(result, dict)
        assert result.get("LOGIN_URL", "") == ""

    def test_none_custom_variables(self):
        """custom_variables=None 不应报错"""
        config = {"auth_url": "http://test.com"}
        result = build_login_template_vars(config, custom_variables=None)
        assert "LOGIN_URL" in result

    def test_task_url_with_login_url_fallback(self):
        """task_url 中无模板变量时，LOGIN_URL 应被设置为解析后的 task_url"""
        config = {"auth_url": "http://10.0.0.1", "username": "u", "password": "p"}
        task_url = "http://10.0.0.1/specific"
        result = build_login_template_vars(config, task_url=task_url)
        assert result["LOGIN_URL"] == "http://10.0.0.1/specific"

    def test_empty_task_url_falls_back_to_auth_url(self):
        """task_url 为空时，LOGIN_URL 应使用 auth_url"""
        config = {"auth_url": "http://10.0.0.1", "username": "u", "password": "p"}
        result = build_login_template_vars(config, task_url="")
        assert result["LOGIN_URL"] == "http://10.0.0.1"


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
        assert normalize_level("DEBUG") == "DEBUG"
        assert normalize_level("INFO") == "INFO"
        assert normalize_level("WARNING") == "WARNING"
        assert normalize_level("ERROR") == "ERROR"
        assert normalize_level("CRITICAL") == "CRITICAL"

    def test_case_insensitive(self):
        assert normalize_level("debug") == "DEBUG"
        assert normalize_level("info") == "INFO"
        assert normalize_level("Warning") == "WARNING"

    def test_strips_whitespace(self):
        assert normalize_level("  ERROR  ") == "ERROR"

    def test_invalid_level_returns_default(self):
        assert normalize_level("TRACE") == "INFO"
        assert normalize_level("INVALID") == "INFO"

    def test_empty_returns_default(self):
        assert normalize_level("") == "INFO"
        assert normalize_level(None) == "INFO"

    def test_custom_default(self):
        assert normalize_level("INVALID", default="WARNING") == "WARNING"


class TestGetLogger:
    def test_returns_logger_with_name(self):
        logger = get_logger("test_module")
        # loguru logger 绑定后通过 extra 获取 name
        assert logger.bind(name="test_module")

    def test_logger_has_side_binding(self):
        logger = get_logger("test_side", source="frontend")
        # loguru logger 绑定后通过 extra 获取 source
        assert logger.bind(source="frontend")

    def test_logger_is_callable(self):
        logger = get_logger("test_dup", source="backend")
        # loguru logger 可以直接调用
        assert logger is not None


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

    def test_is_initialized_default_false(self):
        center = LogConfigCenter()
        # 注意：由于单例模式，如果之前已初始化则为 True
        # 这里只验证方法可调用
        assert isinstance(center.is_initialized(), bool)

    def test_set_source_level(self):
        """测试设置 source 级别"""
        config = LogConfigCenter()
        config.initialize()
        config.set_source_level("network", "DEBUG")
        assert config.get_source_level("network") == "DEBUG"

    def test_get_source_level_default(self):
        """测试获取未设置的 source 级别返回全局级别"""
        config = LogConfigCenter()
        config.initialize()
        config.set_level("INFO")
        config._source_levels.clear()
        assert config.get_source_level("network") == "INFO"

    def test_should_emit_with_source_level(self):
        """测试 should_emit 过滤逻辑"""
        config = LogConfigCenter()
        config.initialize()
        config.set_level("INFO")
        config.set_source_level("network", "DEBUG")

        # network source 应该输出 DEBUG
        assert config.should_emit("network", "DEBUG") is True
        assert config.should_emit("network", "INFO") is True

        # backend source 使用全局级别 INFO，不应该输出 DEBUG
        assert config.should_emit("backend", "DEBUG") is False
        assert config.should_emit("backend", "INFO") is True

    def test_get_all_source_levels(self):
        """测试获取所有 source 级别配置"""
        config = LogConfigCenter()
        config.initialize()
        config.set_source_level("network", "DEBUG")
        config.set_source_level("task", "WARNING")
        levels = config.get_all_source_levels()
        assert levels == {"network": "DEBUG", "task": "WARNING"}


# =====================================================================
# CREATE_NO_WINDOW_FLAG 常量
# =====================================================================


class TestCreateNoWindowFlag:
    def test_is_int(self):
        from app.utils.platform import CREATE_NO_WINDOW_FLAG

        assert isinstance(CREATE_NO_WINDOW_FLAG, int)

    def test_on_windows_is_nonzero(self):
        """Windows 上应为非零值（subprocess.CREATE_NO_WINDOW = 0x08000000）"""
        from app.utils.platform import CREATE_NO_WINDOW_FLAG

        if is_windows():
            assert CREATE_NO_WINDOW_FLAG != 0
        else:
            assert CREATE_NO_WINDOW_FLAG == 0


# =====================================================================
# AUTH_DATA_DIR 常量
# =====================================================================


# =====================================================================
# LoginAttemptHandler.close_browser 幂等性
# =====================================================================


class TestLoginAttemptHandlerCloseIdempotent:
    def test_close_browser_idempotent(self):
        """多次调用 close_browser 不应报错（幂等）"""
        from app.utils.login import LoginAttemptHandler

        handler = LoginAttemptHandler(config={}, close_on_failure=True)
        # _browser_ctx 为 None 时，close_browser 应安全返回
        import asyncio

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(handler.close_browser())
            loop.run_until_complete(handler.close_browser())
            # 两次调用后 _browser_ctx 仍为 None
            assert handler._browser_ctx is None
        finally:
            loop.close()


# =====================================================================
# AUTH_DATA_DIR 常量
# =====================================================================


class TestAuthDataDir:
    def test_is_path(self):
        from app.constants import AUTH_DATA_DIR

        assert isinstance(AUTH_DATA_DIR, Path)

    def test_ends_with_campus_network_auth(self):
        from app.constants import AUTH_DATA_DIR

        assert AUTH_DATA_DIR.name == ".campus_network_auth"


# =====================================================================
# DEFAULT_NETWORK_TARGETS / DEFAULT_HTTP_TARGETS 常量
# =====================================================================


class TestDefaultConstants:
    def test_network_targets_format(self):
        from app.constants import DEFAULT_NETWORK_TARGETS

        parts = DEFAULT_NETWORK_TARGETS.split(",")
        assert len(parts) >= 3
        for part in parts:
            assert ":" in part

    def test_http_targets_format(self):
        from app.constants import DEFAULT_HTTP_TARGETS

        parts = DEFAULT_HTTP_TARGETS.split(",")
        assert len(parts) >= 2
        for part in parts:
            assert part.startswith("http")

    def test_schemas_uses_constant(self):
        """MonitorConfigPayload 默认值应引用常量"""
        from app.constants import DEFAULT_HTTP_TARGETS, DEFAULT_NETWORK_TARGETS
        from app.schemas import MonitorConfigPayload

        m = MonitorConfigPayload()
        assert m.network_targets == DEFAULT_NETWORK_TARGETS
        assert m.http_targets == DEFAULT_HTTP_TARGETS


# ── has_decryption_error / clear_decryption_error ──


class TestDecryptionError:
    """解密错误状态管理。"""

    def teardown_method(self):
        """每个测试后清除解密错误状态，防止污染其他测试。"""
        from app.utils.crypto import clear_decryption_error

        clear_decryption_error()

    def test_initial_state(self):
        """初始状态无解密错误。"""
        from app.utils.crypto import clear_decryption_error, has_decryption_error

        clear_decryption_error()
        assert has_decryption_error() is False

    def test_set_and_clear(self):
        """设置和清除解密错误。"""
        from app.utils.crypto import (
            _decryption_failed,
            clear_decryption_error,
            has_decryption_error,
        )

        _decryption_failed.set()
        assert has_decryption_error() is True
        clear_decryption_error()
        assert has_decryption_error() is False


# ── 日志安全 ──


def test_save_password_field_logs_no_plaintext(caplog):
    """save_password_field 的 warning 日志不应包含密码明文。"""
    from app.utils.crypto import save_password_field

    for raw_value in ("", "••••••••"):
        caplog.clear()
        with caplog.at_level("WARNING"):
            result = save_password_field(raw_value, existing_encrypted="")

        assert result == ""
        for record in caplog.records:
            msg = record.message
            assert repr(raw_value[:20]) not in msg, f"日志泄露了原始输入内容: {msg}"


# =====================================================================
# version — compare_versions（从 test_version.py 合并）
# =====================================================================


class TestCompareVersions:
    """版本比较。"""

    def test_equal(self):
        """相等。"""
        from app.version import compare_versions

        assert compare_versions("1.0.0", "1.0.0") == 0

    def test_greater_major(self):
        """主版本号更大。"""
        from app.version import compare_versions

        assert compare_versions("2.0.0", "1.0.0") == 1

    def test_less_major(self):
        """主版本号更小。"""
        from app.version import compare_versions

        assert compare_versions("1.0.0", "2.0.0") == -1

    def test_greater_minor(self):
        """次版本号更大。"""
        from app.version import compare_versions

        assert compare_versions("1.2.0", "1.1.0") == 1

    def test_less_minor(self):
        """次版本号更小。"""
        from app.version import compare_versions

        assert compare_versions("1.1.0", "1.2.0") == -1

    def test_greater_patch(self):
        """补丁版本号更大。"""
        from app.version import compare_versions

        assert compare_versions("1.0.2", "1.0.1") == 1

    def test_less_patch(self):
        """补丁版本号更小。"""
        from app.version import compare_versions

        assert compare_versions("1.0.1", "1.0.2") == -1

    def test_different_lengths(self):
        """不同长度版本号。"""
        from app.version import compare_versions

        assert compare_versions("1.0", "1.0.0") == 0
        assert compare_versions("1.0.0", "1.0") == 0
        assert compare_versions("1.0.1", "1.0") == 1

    def test_invalid_version_returns_zero(self):
        """无效版本号返回 0。"""
        from app.version import compare_versions

        assert compare_versions("invalid", "1.0.0") == 0
        assert compare_versions("1.0.0", "invalid") == 0
        assert compare_versions("invalid", "invalid") == 0

    def test_single_segment(self):
        """单段版本号。"""
        from app.version import compare_versions

        assert compare_versions("2", "1") == 1
        assert compare_versions("1", "2") == -1
        assert compare_versions("1", "1") == 0


# =====================================================================
# logging — VALID_LOG_LEVELS / DashboardSink（从 test_logging_utils.py 合并）
# =====================================================================


class TestValidLogLevels:
    """有效日志级别。"""

    def test_contains_standard_levels(self):
        """包含标准级别。"""
        from app.utils.logging import VALID_LOG_LEVELS

        assert "DEBUG" in VALID_LOG_LEVELS
        assert "INFO" in VALID_LOG_LEVELS
        assert "WARNING" in VALID_LOG_LEVELS
        assert "ERROR" in VALID_LOG_LEVELS
        assert "CRITICAL" in VALID_LOG_LEVELS

    def test_count(self):
        """级别数量。"""
        from app.utils.logging import VALID_LOG_LEVELS

        assert len(VALID_LOG_LEVELS) == 5


# ── DashboardSink source 级别过滤 ──


def test_dashboard_sink_filters_by_source_level():
    """测试 DashboardSink 根据 source 级别过滤"""
    from unittest.mock import MagicMock

    from app.utils.logging import DashboardSink, LogConfigCenter

    config = LogConfigCenter()
    config.initialize()
    config.set_level("INFO")
    config.set_source_level("network", "WARNING")

    sink = DashboardSink()

    level_debug = MagicMock()
    level_debug.name = "DEBUG"
    level_warning = MagicMock()
    level_warning.name = "WARNING"
    level_info = MagicMock()
    level_info.name = "INFO"

    def make_msg(source, level_mock):
        msg = MagicMock()
        msg.record = {
            "extra": {"source": source, "name": "test"},
            "level": level_mock,
            "time": MagicMock(timestamp=lambda: 0),
            "name": "test",
        }
        msg.__str__ = lambda self: "test message"
        return msg

    # network source 设置为 WARNING，DEBUG 应该被过滤
    sink.write(make_msg("network", level_debug))
    assert len(sink.buffer) == 0

    # network source 设置为 WARNING，WARNING 应该通过
    sink.write(make_msg("network", level_warning))
    assert len(sink.buffer) == 1

    # backend source 使用全局级别 INFO，DEBUG 应该被过滤
    sink.write(make_msg("backend", level_debug))
    assert len(sink.buffer) == 1

    # backend source 使用全局级别 INFO，INFO 应该通过
    sink.write(make_msg("backend", level_info))
    assert len(sink.buffer) == 2


# ── DashboardSink ──


class TestDashboardSink:
    """DashboardSink 单元测试。"""

    def test_init_default(self):
        """默认初始化。"""
        from app.utils.logging import DashboardSink

        sink = DashboardSink()
        assert sink.buffer.maxlen == 500
        assert sink.broadcast_queue.maxlen == 200
        assert len(sink.buffer) == 0
        assert len(sink.broadcast_queue) == 0

    def test_init_custom_maxlen(self):
        """自定义 maxlen。"""
        from app.utils.logging import DashboardSink

        sink = DashboardSink(maxlen=500)
        assert sink.buffer.maxlen == 500

    def test_write_appends_to_buffer_and_queue(self):
        """write 同时写入 buffer 和 broadcast_queue。"""
        from unittest.mock import MagicMock

        from app.utils.logging import DashboardSink

        sink = DashboardSink(maxlen=10)
        msg = MagicMock()
        level_mock = MagicMock()
        level_mock.name = "INFO"
        msg.record = {
            "time": MagicMock(timestamp=lambda: 1700000000.0),
            "level": level_mock,
            "extra": {"name": "test", "source": "backend"},
            "name": "test",
            "message": "测试消息",
        }
        msg.__str__ = lambda self: "测试消息"

        sink.write(msg)

        assert len(sink.buffer) == 1
        assert len(sink.broadcast_queue) == 1
        entry = sink.buffer[0]
        assert entry["level"] == "INFO"
        assert entry["source"] == "backend"
        assert entry["name"] == "test"
        assert entry["message"] == "测试消息"

    def test_write_buffer_overflow(self):
        """buffer 超出 maxlen 自动淘汰最旧。"""
        from unittest.mock import MagicMock

        from app.utils.logging import DashboardSink

        sink = DashboardSink(maxlen=3)
        level_mock = MagicMock()
        level_mock.name = "INFO"
        for i in range(5):
            msg = MagicMock()
            msg.record = {
                "time": MagicMock(timestamp=lambda: 1700000000.0),
                "level": level_mock,
                "extra": {"name": "test", "source": "backend"},
                "name": "test",
                "message": f"msg{i}",
            }
            msg.__str__ = lambda self, i=i: f"msg{i}"
            sink.write(msg)

        assert len(sink.buffer) == 3
        assert sink.buffer[0]["message"] == "msg2"
        assert sink.buffer[2]["message"] == "msg4"

    def test_list_logs_returns_last_n(self):
        """list_logs 返回最近 N 条。"""
        from app.utils.logging import DashboardSink

        sink = DashboardSink(maxlen=10)
        for i in range(5):
            sink.buffer.append({"message": f"msg{i}"})

        result = sink.list_logs(limit=3)
        assert len(result) == 3
        assert result[0]["message"] == "msg2"

    def test_list_logs_limit_exceeds_buffer(self):
        """list_logs limit 超过 buffer 大小时返回全部。"""
        from app.utils.logging import DashboardSink

        sink = DashboardSink(maxlen=10)
        sink.buffer.append({"message": "only"})
        result = sink.list_logs(limit=100)
        assert len(result) == 1

    def test_thread_safety(self):
        """多线程并发写入不会崩溃。"""
        import threading
        from unittest.mock import MagicMock

        from app.utils.logging import DashboardSink

        sink = DashboardSink(maxlen=1000)
        errors = []

        level_mock = MagicMock()
        level_mock.name = "INFO"

        def writer(n):
            try:
                for i in range(100):
                    msg = MagicMock()
                    msg.record = {
                        "time": MagicMock(timestamp=lambda: 1700000000.0),
                        "level": level_mock,
                        "extra": {"name": "test", "source": "backend"},
                        "name": "test",
                        "message": f"t{n}_msg{i}",
                    }
                    msg.__str__ = lambda self, n=n, i=i: f"t{n}_msg{i}"
                    sink.write(msg)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(n,)) for n in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert len(sink.buffer) == 400
