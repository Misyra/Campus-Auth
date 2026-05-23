from __future__ import annotations

import sys
from unittest.mock import patch

from src.utils.platform_utils import (
    __all__,
    get_default_ua,
    get_platform,
    is_fallback,
    is_linux,
    is_macos,
    is_windows,
)


class TestGetPlatform:
    """测试 get_platform() 各平台返回值"""

    def test_win32_returns_windows(self):
        with patch.object(sys, "platform", "win32"):
            assert get_platform() == "windows"

    def test_darwin_returns_darwin(self):
        with patch.object(sys, "platform", "darwin"):
            assert get_platform() == "darwin"

    def test_linux_returns_linux(self):
        with patch.object(sys, "platform", "linux"):
            assert get_platform() == "linux"


class TestIsWindows:
    """测试 is_windows() 平台判定"""

    def test_win32_returns_true(self):
        with patch.object(sys, "platform", "win32"):
            assert is_windows() is True

    def test_darwin_returns_false(self):
        with patch.object(sys, "platform", "darwin"):
            assert is_windows() is False

    def test_linux_returns_false(self):
        with patch.object(sys, "platform", "linux"):
            assert is_windows() is False


class TestIsMacos:
    """测试 is_macos() 平台判定"""

    def test_darwin_returns_true(self):
        with patch.object(sys, "platform", "darwin"):
            assert is_macos() is True

    def test_win32_returns_false(self):
        with patch.object(sys, "platform", "win32"):
            assert is_macos() is False

    def test_linux_returns_false(self):
        with patch.object(sys, "platform", "linux"):
            assert is_macos() is False


class TestIsLinux:
    """测试 is_linux() 平台判定，包含 linux2 兼容"""

    def test_linux_returns_true(self):
        with patch.object(sys, "platform", "linux"):
            assert is_linux() is True

    def test_linux2_returns_true(self):
        with patch.object(sys, "platform", "linux2"):
            assert is_linux() is True

    def test_win32_returns_false(self):
        with patch.object(sys, "platform", "win32"):
            assert is_linux() is False

    def test_darwin_returns_false(self):
        with patch.object(sys, "platform", "darwin"):
            assert is_linux() is False


class TestIsFallback:
    """测试 is_fallback() 未知平台兜底"""

    def test_win32_returns_false(self):
        with patch.object(sys, "platform", "win32"):
            assert is_fallback() is False

    def test_darwin_returns_false(self):
        with patch.object(sys, "platform", "darwin"):
            assert is_fallback() is False

    def test_linux_returns_false(self):
        with patch.object(sys, "platform", "linux"):
            assert is_fallback() is False

    def test_unknown_platform_returns_true(self):
        with patch.object(sys, "platform", "freebsd"):
            assert is_fallback() is True


class TestGetDefaultUa:
    """测试 get_default_ua() 返回平台对应的 UA 字符串"""

    def test_windows_ua_prefix(self):
        with patch.object(sys, "platform", "win32"):
            ua = get_default_ua()
            assert ua.startswith("Mozilla/5.0 (Windows NT 10.0")

    def test_macos_ua_prefix(self):
        with patch.object(sys, "platform", "darwin"):
            ua = get_default_ua()
            assert ua.startswith("Mozilla/5.0 (Macintosh; Intel Mac OS X")

    def test_linux_ua_prefix(self):
        with patch.object(sys, "platform", "linux"):
            ua = get_default_ua()
            assert ua.startswith("Mozilla/5.0 (X11; Linux x86_64)")

    def test_fallback_uses_linux_ua(self):
        with patch.object(sys, "platform", "freebsd"):
            ua = get_default_ua()
            assert ua.startswith("Mozilla/5.0 (X11; Linux x86_64)")


class TestAllExports:
    """测试 __all__ 正确导出全部 6 个函数"""

    def test_all_exports_all_functions(self):
        expected = {"get_platform", "is_windows", "is_macos", "is_linux", "is_fallback", "get_default_ua"}
        assert set(__all__) == expected
