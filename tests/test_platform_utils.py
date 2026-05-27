"""src/utils/platform_utils.py 测试"""
from __future__ import annotations

from unittest.mock import patch
from src.utils.platform_utils import get_platform, is_windows, is_macos, is_linux, get_default_ua


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
        with patch("src.utils.platform_utils.sys") as mock_sys:
            mock_sys.platform = "linux2"
            assert is_linux() is True

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
