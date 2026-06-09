"""卸载服务测试 — 覆盖纯逻辑函数。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.services.uninstall import (
    CleanupItem,
    CleanupResult,
    _dir_size_mb,
    _playwright_cache_dir,
)

# ── 数据类 ──


class TestCleanupItem:
    """CleanupItem 数据类。"""

    def test_basic_creation(self):
        """基本创建。"""
        item = CleanupItem(key="test", label="测试", exists=True)
        assert item.key == "test"
        assert item.label == "测试"
        assert item.exists is True
        assert item.path == ""
        assert item.size_mb == 0.0

    def test_with_path_and_size(self):
        """带路径和大小。"""
        item = CleanupItem(
            key="test", label="测试", exists=True, path="/tmp", size_mb=1.5
        )
        assert item.path == "/tmp"
        assert item.size_mb == 1.5


class TestCleanupResult:
    """CleanupResult 数据类。"""

    def test_basic_creation(self):
        """基本创建。"""
        result = CleanupResult(key="test", label="测试", success=True, message="ok")
        assert result.key == "test"
        assert result.success is True
        assert result.message == "ok"

    def test_failure(self):
        """失败结果。"""
        result = CleanupResult(key="test", label="测试", success=False, message="error")
        assert result.success is False


# ── _dir_size_mb ──


class TestDirSizeMb:
    """目录大小计算。"""

    def test_empty_dir(self, tmp_path):
        """空目录返回 0。"""
        assert _dir_size_mb(tmp_path) == 0.0

    def test_with_files(self, tmp_path):
        """有文件时返回正确大小。"""
        (tmp_path / "test.txt").write_text("hello")
        size = _dir_size_mb(tmp_path)
        assert size > 0

    def test_nested_dirs(self, tmp_path):
        """嵌套目录。"""
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "test.txt").write_text("hello world")
        size = _dir_size_mb(tmp_path)
        assert size > 0

    def test_nonexistent_dir(self, tmp_path):
        """不存在的目录返回 0。"""
        assert _dir_size_mb(tmp_path / "nonexistent") == 0.0


# ── _playwright_cache_dir ──


class TestPlaywrightCacheDir:
    """Playwright 缓存目录。"""

    def test_windows_path(self):
        """Windows 路径。"""
        with patch("app.services.uninstall.PLATFORM", "windows"):
            result = _playwright_cache_dir()
            assert result is not None
            assert "ms-playwright" in str(result)

    def test_darwin_path(self):
        """macOS 路径。"""
        with patch("app.services.uninstall.PLATFORM", "darwin"):
            result = _playwright_cache_dir()
            assert result is not None
            assert "ms-playwright" in str(result)

    def test_linux_path(self):
        """Linux 路径。"""
        with patch("app.services.uninstall.PLATFORM", "linux"):
            result = _playwright_cache_dir()
            assert result is not None
            assert "ms-playwright" in str(result)

    def test_unknown_platform(self):
        """未知平台返回 None。"""
        with patch("app.services.uninstall.PLATFORM", "unknown"):
            result = _playwright_cache_dir()
            assert result is None


# ── perform ──


class TestPerform:
    """清理执行。"""

    def test_empty_keys(self):
        """空 keys 返回空结果。"""
        from app.services.uninstall import perform

        result = perform([])
        assert result == []

    def test_unknown_key_ignored(self):
        """未知 key 被忽略。"""
        from app.services.uninstall import perform

        result = perform(["unknown_key"])
        assert result == []

    def test_autostart_key(self):
        """autostart key 触发移除。"""
        from app.services.uninstall import perform

        with patch(
            "app.services.uninstall._remove_autostart", return_value=(True, "ok")
        ):
            result = perform(["autostart"])
            assert len(result) == 1
            assert result[0].key == "autostart"
            assert result[0].success is True

    def test_userdata_key(self):
        """userdata key 触发删除。"""
        from app.services.uninstall import perform

        with patch(
            "app.services.uninstall._remove_user_data", return_value=(True, "ok")
        ):
            result = perform(["userdata"])
            assert len(result) == 1
            assert result[0].key == "userdata"

    def test_playwright_key(self):
        """playwright key 触发删除。"""
        from app.services.uninstall import perform

        mock_cache = MagicMock()
        mock_cache.exists.return_value = True
        with (
            patch(
                "app.services.uninstall._playwright_cache_dir", return_value=mock_cache
            ),
            patch(
                "app.services.uninstall._remove_playwright_cache",
                return_value=(True, "ok"),
            ),
        ):
            result = perform(["playwright"])
            assert len(result) == 1
            assert result[0].key == "playwright"

    def test_multiple_keys(self):
        """多个 key。"""
        from app.services.uninstall import perform

        with (
            patch(
                "app.services.uninstall._remove_autostart", return_value=(True, "ok")
            ),
            patch(
                "app.services.uninstall._remove_user_data", return_value=(True, "ok")
            ),
        ):
            result = perform(["autostart", "userdata"])
            assert len(result) == 2
