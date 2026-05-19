from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import backend.uninstall_service as uninstall


class TestDetect:

    def test_detect_returns_list(self):
        items = uninstall.detect()
        assert isinstance(items, list)
        assert len(items) > 0

    def test_detect_items_have_keys(self):
        items = uninstall.detect()
        keys = [item.key for item in items]
        assert "autostart" in keys
        assert "userdata" in keys
        assert "playwright" in keys


class TestPerform:

    def test_perform_empty_keys(self):
        results = uninstall.perform([])
        assert results == []

    def test_perform_userdata_not_exists(self):
        with patch.object(uninstall, "USER_DATA_DIR", Path("/nonexistent/path")):
            results = uninstall.perform(["userdata"])
            assert len(results) == 1
            assert results[0].key == "userdata"
            assert results[0].success is True

    def test_perform_playwright_not_exists(self):
        with patch.object(uninstall, "_playwright_cache_dir", return_value=Path("/nonexistent")):
            results = uninstall.perform(["playwright"])
            assert len(results) == 1
            assert results[0].key == "playwright"
            assert results[0].success is True


class TestPlaywrightCacheDir:

    def test_windows(self):
        with patch.object(uninstall, "PLATFORM", "win32"):
            result = uninstall._playwright_cache_dir()
            assert result is not None
            assert "ms-playwright" in str(result)

    def test_darwin(self):
        with patch.object(uninstall, "PLATFORM", "darwin"):
            result = uninstall._playwright_cache_dir()
            assert result is not None
            assert "Caches" in str(result)

    def test_linux(self):
        with patch.object(uninstall, "PLATFORM", "linux"):
            result = uninstall._playwright_cache_dir()
            assert result is not None
            assert ".cache" in str(result)

    def test_unknown(self):
        with patch.object(uninstall, "PLATFORM", "freebsd"):
            result = uninstall._playwright_cache_dir()
            assert result is None


class TestDirSizeMb:

    def test_empty_dir(self, tmp_path):
        size = uninstall._dir_size_mb(tmp_path)
        assert size == 0.0

    def test_nonexistent_dir(self):
        size = uninstall._dir_size_mb(Path("/nonexistent"))
        assert size == 0.0


class TestCheckAutostart:

    def test_returns_dict(self):
        result = uninstall._check_autostart()
        assert isinstance(result, dict)
        assert "enabled" in result
        assert "platform" in result


class TestRemoveAutostart:

    def test_returns_tuple(self):
        ok, msg = uninstall._remove_autostart()
        assert isinstance(ok, bool)
        assert isinstance(msg, str)
