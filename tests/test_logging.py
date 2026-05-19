from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path

from src.utils.logging import (
    ColoredFormatter,
    SideFilter,
    _normalize_level,
    _level_value,
    LogConfigCenter,
    cleanup_debug_screenshots,
)


class TestNormalizeLevel:

    def test_valid_levels(self):
        for level in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
            assert _normalize_level(level) == level

    def test_none_defaults_to_info(self):
        assert _normalize_level(None) == "INFO"

    def test_invalid_returns_default(self):
        assert _normalize_level("INVALID") == "INFO"

    def test_lowercase_converted(self):
        assert _normalize_level("debug") == "DEBUG"


class TestLevelValue:

    def test_info_value(self):
        assert _level_value("INFO") == logging.INFO

    def test_debug_value(self):
        assert _level_value("DEBUG") == logging.DEBUG

    def test_none_defaults(self):
        assert _level_value(None) == logging.INFO


class TestSideFilter:

    def test_sets_side_attribute(self):
        filt = SideFilter(side="BACKEND")
        record = logging.LogRecord("test", logging.INFO, "", 0, "msg", (), None)
        assert filt.filter(record) is True
        assert record.side == "BACKEND"

    def test_does_not_override_existing(self):
        filt = SideFilter(side="BACKEND")
        record = logging.LogRecord("test", logging.INFO, "", 0, "msg", (), None)
        record.side = "FRONTEND"
        filt.filter(record)
        assert record.side == "FRONTEND"


class TestColoredFormatter:

    def test_colors_levelname(self):
        fmt = ColoredFormatter("%(levelname)s - %(message)s")
        record = logging.LogRecord("test", logging.INFO, "", 0, "hello", (), None)
        output = fmt.format(record)
        assert "INFO" in output
        assert record.levelname == "INFO"  # restored after format


class TestLogConfigCenter:

    def test_singleton(self):
        a = LogConfigCenter()
        b = LogConfigCenter()
        assert a is b

    def test_get_config(self):
        center = LogConfigCenter()
        cfg = center.get_config()
        assert "level" in cfg


class TestCleanupDebugScreenshots:

    def test_nonexistent_dir(self):
        assert cleanup_debug_screenshots("/nonexistent/path", 7) == 0

    def test_deletes_old_screenshots(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            date_dir = Path(tmpdir) / "2020-01-01"
            date_dir.mkdir()
            old_file = date_dir / "screenshot.png"
            old_file.touch()
            # Set mtime to 30 days ago
            old_time = os.path.getmtime(old_file) - 30 * 86400
            os.utime(old_file, (old_time, old_time))

            result = cleanup_debug_screenshots(tmpdir, 7)
            assert result == 1
            assert not old_file.exists()
