"""平台工具测试 — 覆盖平台检测函数。"""

from __future__ import annotations

import sys

from app.utils.platform_utils import (
    CREATE_NO_WINDOW_FLAG,
    get_default_ua,
    get_platform,
    is_linux,
    is_macos,
    is_windows,
)

# ── 平台检测 ──


class TestPlatformDetection:
    """平台检测函数。"""

    def test_one_platform_true(self):
        """当前平台只有一个为 True。"""
        results = [is_windows(), is_macos(), is_linux()]
        assert sum(results) == 1

    def test_current_platform(self):
        """当前平台检测。"""
        if sys.platform == "win32":
            assert is_windows() is True
            assert is_macos() is False
            assert is_linux() is False
        elif sys.platform == "darwin":
            assert is_windows() is False
            assert is_macos() is True
            assert is_linux() is False
        else:
            assert is_windows() is False
            assert is_macos() is False
            assert is_linux() is True


# ── get_platform ──


class TestGetPlatform:
    """平台标识。"""

    def test_returns_string(self):
        """返回字符串。"""
        result = get_platform()
        assert isinstance(result, str)

    def test_valid_values(self):
        """有效值。"""
        result = get_platform()
        assert result in ("windows", "darwin", "linux")

    def test_matches_sys_platform(self):
        """与 sys.platform 一致。"""
        result = get_platform()
        if sys.platform == "win32":
            assert result == "windows"
        elif sys.platform == "darwin":
            assert result == "darwin"
        else:
            assert result == "linux"


# ── get_default_ua ──


class TestGetDefaultUa:
    """默认 User-Agent。"""

    def test_returns_string(self):
        """返回字符串。"""
        result = get_default_ua()
        assert isinstance(result, str)

    def test_contains_mozilla(self):
        """包含 Mozilla。"""
        result = get_default_ua()
        assert "Mozilla" in result

    def test_not_empty(self):
        """非空。"""
        result = get_default_ua()
        assert len(result) > 0


# ── CREATE_NO_WINDOW_FLAG ──


class TestCreateNoWindowFlag:
    """CREATE_NO_WINDOW 标志。"""

    def test_on_windows(self):
        """Windows 上应有值。"""
        if sys.platform == "win32":
            assert CREATE_NO_WINDOW_FLAG is not None
            assert CREATE_NO_WINDOW_FLAG > 0

    def test_on_other_platforms(self):
        """其他平台为 0。"""
        if sys.platform != "win32":
            assert CREATE_NO_WINDOW_FLAG == 0
