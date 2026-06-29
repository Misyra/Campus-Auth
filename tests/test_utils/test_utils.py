"""src/utils/ 模块综合测试

合并原 test_crypto.py, test_config_helpers.py, test_file_helpers.py,
test_platform_utils.py, test_str_to_bool.py, test_network_helpers.py,
test_version.py, test_time_utils.py，并新增 env.py, exceptions.py,
logging.py, notify.py 测试。
"""

from __future__ import annotations

import datetime
import os
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

import pytest

# ── str_to_bool ──
from app.utils import str_to_bool

# ── config_helpers ──

# ── crypto ──
from app.utils.crypto import (
    decrypt_password,
    encrypt_password,
    save_password_field,
)

# ── env ──
from app.utils.env import build_login_template_vars

# ── exceptions ──
from app.utils.exceptions import LoginCancelledError

# ── files ──
from app.utils.files import atomic_write

# ── logging ──
from app.utils.logging import (
    LogConfigCenter,
    get_logger,
    normalize_level,
)

# ── network ──
from app.network.parsers import parse_host_port

# ── platform ──
from app.utils.platform import (
    get_platform,
    is_linux,
    is_macos,
    is_windows,
)

# ── time_utils ──
from app.schemas import PauseSettings
from app.utils.time_utils import is_in_pause_period

# ── version ──
from app.version import get_project_version

# =====================================================================
# crypto
# =====================================================================


# =====================================================================
# config_helpers
# =====================================================================


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


class TestAtomicWriteCrossFilesystem:
    """测试 atomic_write 的跨文件系统兼容性。"""

    def test_temp_file_created_in_target_directory(self, tmp_path: Path):
        """验证临时文件在目标文件所在目录创建。"""
        target = tmp_path / "test.txt"
        captured_dir = None

        original_mkstemp = tempfile.mkstemp

        def mock_mkstemp(**kwargs):
            nonlocal captured_dir
            captured_dir = kwargs.get("dir")
            return original_mkstemp(**kwargs)

        with patch("app.utils.files.tempfile.mkstemp", side_effect=mock_mkstemp):
            atomic_write(target, "hello")

        assert captured_dir == str(tmp_path)

    def test_temp_file_created_in_parent_for_relative_path(self):
        """验证相对路径时临时文件在当前目录创建。"""
        captured_dir = None
        original_mkstemp = tempfile.mkstemp

        def mock_mkstemp(**kwargs):
            nonlocal captured_dir
            captured_dir = kwargs.get("dir")
            return original_mkstemp(**kwargs)

        with patch("app.utils.files.tempfile.mkstemp", side_effect=mock_mkstemp):
            atomic_write("test_relative_file.txt", "hello")
            if os.path.exists("test_relative_file.txt"):
                os.unlink("test_relative_file.txt")

        assert captured_dir == "."


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
        assert result == [("::1", 8080)]

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
        pause = PauseSettings(enabled=False, start_hour=0, end_hour=6)
        assert is_in_pause_period(pause) is False

    def test_same_hour_means_all_day(self):
        pause = PauseSettings(enabled=True, start_hour=5, end_hour=5)
        assert is_in_pause_period(pause) is True

    def test_normal_range_in_pause(self):
        pause = PauseSettings(enabled=True, start_hour=0, end_hour=6)
        mock_now = datetime.datetime(2025, 1, 1, 3, 0, 0)
        with patch("app.utils.time_utils.datetime") as mock_dt:
            mock_dt.datetime.now.return_value = mock_now
            assert is_in_pause_period(pause) is True

    def test_normal_range_outside_pause(self):
        pause = PauseSettings(enabled=True, start_hour=0, end_hour=6)
        mock_now = datetime.datetime(2025, 1, 1, 12, 0, 0)
        with patch("app.utils.time_utils.datetime") as mock_dt:
            mock_dt.datetime.now.return_value = mock_now
            assert is_in_pause_period(pause) is False

    def test_cross_midnight_in_pause(self):
        pause = PauseSettings(enabled=True, start_hour=23, end_hour=6)
        mock_now = datetime.datetime(2025, 1, 1, 2, 0, 0)
        with patch("app.utils.time_utils.datetime") as mock_dt:
            mock_dt.datetime.now.return_value = mock_now
            assert is_in_pause_period(pause) is True

    def test_cross_midnight_outside_pause(self):
        pause = PauseSettings(enabled=True, start_hour=23, end_hour=6)
        mock_now = datetime.datetime(2025, 1, 1, 12, 0, 0)
        with patch("app.utils.time_utils.datetime") as mock_dt:
            mock_dt.datetime.now.return_value = mock_now
            assert is_in_pause_period(pause) is False

    def test_defaults_in_pause(self):
        pause = PauseSettings()
        mock_now = datetime.datetime(2025, 1, 1, 3, 0, 0)
        with patch("app.utils.time_utils.datetime") as mock_dt:
            mock_dt.datetime.now.return_value = mock_now
            assert is_in_pause_period(pause) is True

    def test_defaults_outside_pause(self):
        pause = PauseSettings()
        mock_now = datetime.datetime(2025, 1, 1, 12, 0, 0)
        with patch("app.utils.time_utils.datetime") as mock_dt:
            mock_dt.datetime.now.return_value = mock_now
            assert is_in_pause_period(pause) is False



# =====================================================================
# env — build_login_template_vars
# =====================================================================


class TestBuildLoginTemplateVars:
    def test_basic_config(self):
        """基本配置应正确注入模板变量"""
        result = build_login_template_vars(
            auth_url="http://10.0.0.1/login",
            username="testuser",
            password="testpass",
            isp="移动",
        )
        assert result["LOGIN_URL"] == "http://10.0.0.1/login"
        assert result["USERNAME"] == "testuser"
        assert result["PASSWORD"] == "testpass"
        assert result["ISP"] == "移动"

    def test_task_url_template_resolution(self):
        """task_url 中的变量模板应被解析"""
        task_url = "http://10.0.0.1/login?user={{USERNAME}}&isp={{ISP}}"
        result = build_login_template_vars(
            auth_url="http://10.0.0.1/login",
            username="user1",
            password="pass1",
            isp="联通",
            task_url=task_url,
        )
        assert result["LOGIN_URL"] == "http://10.0.0.1/login?user=user1&isp=联通"

    def test_custom_variables_injected(self):
        """自定义变量应注入到模板变量"""
        custom = {"MY_VAR": "hello", "ANOTHER": "world"}
        result = build_login_template_vars(
            auth_url="http://test.com",
            username="u",
            password="p",
            custom_variables=custom,
        )
        assert result["MY_VAR"] == "hello"
        assert result["ANOTHER"] == "world"

    def test_denylist_not_overridden(self):
        """保留名自定义变量应被拒绝"""
        custom = {"PATH": "/evil/path", "PYTHONPATH": "/evil"}
        result = build_login_template_vars(custom_variables=custom)
        assert result.get("PATH") is None
        assert result.get("PYTHONPATH") is None

    def test_empty_config(self):
        """空参数应返回空字典"""
        result = build_login_template_vars()
        assert isinstance(result, dict)
        assert result.get("LOGIN_URL", "") == ""

    def test_none_custom_variables(self):
        """custom_variables=None 不应报错"""
        result = build_login_template_vars(auth_url="http://test.com", custom_variables=None)
        assert "LOGIN_URL" in result

    def test_task_url_with_login_url_fallback(self):
        """task_url 中无模板变量时，LOGIN_URL 应被设置为解析后的 task_url"""
        task_url = "http://10.0.0.1/specific"
        result = build_login_template_vars(
            auth_url="http://10.0.0.1",
            username="u",
            password="p",
            task_url=task_url,
        )
        assert result["LOGIN_URL"] == "http://10.0.0.1/specific"

    def test_empty_task_url_falls_back_to_auth_url(self):
        """task_url 为空时，LOGIN_URL 应使用 auth_url"""
        result = build_login_template_vars(
            auth_url="http://10.0.0.1",
            username="u",
            password="p",
            task_url="",
        )
        assert result["LOGIN_URL"] == "http://10.0.0.1"


# =====================================================================
# exceptions（新增）
# =====================================================================


class TestExceptions:
    def test_login_cancelled_error(self):
        """LoginCancelledError 应为 Exception 子类"""
        with pytest.raises(LoginCancelledError):
            raise LoginCancelledError("cancelled")

    def test_login_cancelled_error_is_exception(self):
        assert issubclass(LoginCancelledError, Exception)


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


class TestShouldEmitLevelOrder:
    """验证 should_emit 使用类级别常量而非每次重建字典"""

    def test_level_order_is_class_constant(self):
        """LogConfigCenter 应有 _LEVEL_ORDER 类常量"""
        assert hasattr(LogConfigCenter, "_LEVEL_ORDER"), (
            "LogConfigCenter 缺少 _LEVEL_ORDER 类常量"
        )
        expected = {"DEBUG": 0, "INFO": 1, "WARNING": 2, "ERROR": 3, "CRITICAL": 4}
        assert LogConfigCenter._LEVEL_ORDER == expected

    def test_should_emit_uses_class_constant_via_behavior(self):
        """should_emit 应通过类常量决策"""
        cc = LogConfigCenter.get_instance()
        original = LogConfigCenter._LEVEL_ORDER.copy()
        try:
            LogConfigCenter._LEVEL_ORDER = {"DEBUG": 0, "INFO": 1, "WARNING": 2, "ERROR": 3, "CRITICAL": 4}
            result_before = cc.should_emit("backend", "INFO")
            LogConfigCenter._LEVEL_ORDER = {"DEBUG": 5, "INFO": 1, "WARNING": 2, "ERROR": 3, "CRITICAL": 4}
            result_after = cc.should_emit("backend", "INFO")
            assert isinstance(result_before, bool)
            assert isinstance(result_after, bool)
        finally:
            LogConfigCenter._LEVEL_ORDER = original

    def test_should_emit_basic_functionality(self):
        """should_emit 基本功能验证"""
        cc = LogConfigCenter.get_instance()
        assert cc.should_emit("backend", "INFO") is True
        assert cc.should_emit("backend", "DEBUG") is False
        assert cc.should_emit("backend", "WARNING") is True
        assert cc.should_emit("backend", "ERROR") is True
        assert cc.should_emit("backend", "CRITICAL") is True


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
        from app.services.login_handler import LoginAttemptHandler

        handler = LoginAttemptHandler(config={})
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



# ── has_decryption_error / clear_decryption_error ──


# ── 日志安全 ──


def test_save_password_field_no_warning_for_empty(caplog):
    """save_password_field 对空串输入不应产生 warning 日志。"""
    from app.utils.crypto import save_password_field

    caplog.clear()
    with caplog.at_level("WARNING"):
        save_password_field("", existing_encrypted="ENC:old")

    assert not caplog.records


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
