from __future__ import annotations

import logging
import os
import tempfile
import threading
import time
from pathlib import Path

from src.utils.logging import (
    ColoredFormatter,
    SideFilter,
    _DateRotatingFileHandler,
    _normalize_level,
    _level_value,
    LogConfigCenter,
    cleanup_debug_screenshots,
)


class TestDateRotatingFileHandlerFlush:
    """Tests for buffered flush behavior: count threshold (10) and time threshold (5s)."""

    def _make_handler(self, log_dir: str) -> _DateRotatingFileHandler:
        """Create a handler with a simple formatter."""
        formatter = logging.Formatter("%(message)s")
        return _DateRotatingFileHandler(
            log_dir=log_dir,
            retention_days=7,
            level=logging.DEBUG,
            formatter=formatter,
        )

    def _make_record(self, msg: str) -> logging.LogRecord:
        """Create a minimal LogRecord."""
        return logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg=msg, args=(), exc_info=None,
        )

    def test_write_9_lines_no_flush(self):
        """Writing 9 log lines — file is created immediately, all 9 lines present."""
        with tempfile.TemporaryDirectory() as tmpdir:
            handler = self._make_handler(tmpdir)
            log_path = os.path.join(tmpdir, f"{time.strftime('%Y-%m-%d')}.log")

            for i in range(9):
                handler.emit(self._make_record(f"line {i}"))

            assert os.path.exists(log_path), \
                "Expected file after 1st write (immediate-open)"

            content = Path(log_path).read_text(encoding="utf-8")
            lines = [line for line in content.strip().splitlines() if line]
            assert len(lines) == 9, f"Expected 9 lines, got {len(lines)}"

            handler.close()

    def test_write_10_lines_triggers_flush(self):
        """Writing the 10th log line should trigger flush to disk."""
        with tempfile.TemporaryDirectory() as tmpdir:
            handler = self._make_handler(tmpdir)
            log_path = os.path.join(tmpdir, f"{time.strftime('%Y-%m-%d')}.log")

            for i in range(10):
                handler.emit(self._make_record(f"line {i}"))

            # File should exist after 10th write
            assert os.path.exists(log_path), \
                "Expected file after 10 writes (flush threshold reached)"

            content = Path(log_path).read_text(encoding="utf-8")
            lines = [line for line in content.strip().splitlines() if line]
            assert len(lines) == 10, f"Expected 10 lines, got {len(lines)}"
            for i in range(10):
                assert f"line {i}" in lines[i], f"Line {i} mismatch: {lines[i]}"

            handler.close()

    def test_time_threshold_triggers_flush(self):
        """Multiple writes across time — all lines written immediately."""
        with tempfile.TemporaryDirectory() as tmpdir:
            handler = self._make_handler(tmpdir)
            log_path = os.path.join(tmpdir, f"{time.strftime('%Y-%m-%d')}.log")

            for i in range(3):
                handler.emit(self._make_record(f"line {i}"))

            assert os.path.exists(log_path), \
                "Expected file after 1st write (immediate-open)"

            handler.emit(self._make_record("line 3"))

            content = Path(log_path).read_text(encoding="utf-8")
            lines = [line for line in content.strip().splitlines() if line]
            assert len(lines) == 4, f"Expected 4 lines, got {len(lines)}"

            handler.close()

    def test_close_flushes_remaining_buffer(self):
        """close() writes all buffered content and closes the stream."""
        with tempfile.TemporaryDirectory() as tmpdir:
            handler = self._make_handler(tmpdir)
            log_path = os.path.join(tmpdir, f"{time.strftime('%Y-%m-%d')}.log")

            for i in range(3):
                handler.emit(self._make_record(f"line {i}"))

            # File exists immediately after first write
            assert os.path.exists(log_path), \
                "Expected file after first emit (immediate-open)"

            handler.close()

            content = Path(log_path).read_text(encoding="utf-8")
            lines = [line for line in content.strip().splitlines() if line]
            assert len(lines) == 3, f"Expected 3 lines after close, got {len(lines)}"

    def test_concurrent_writes_no_data_loss(self):
        """Multiple threads writing concurrently should not lose data."""
        with tempfile.TemporaryDirectory() as tmpdir:
            handler = self._make_handler(tmpdir)
            log_path = os.path.join(tmpdir, f"{time.strftime('%Y-%m-%d')}.log")

            num_threads = 5
            lines_per_thread = 10
            total_lines = num_threads * lines_per_thread

            def writer(thread_id: int):
                for i in range(lines_per_thread):
                    handler.emit(self._make_record(f"t{thread_id}-line{i}"))

            threads = [threading.Thread(target=writer, args=(tid,)) for tid in range(num_threads)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            handler.close()

            assert os.path.exists(log_path), "Expected file after concurrent writes"

            content = Path(log_path).read_text(encoding="utf-8")
            lines = [line for line in content.strip().splitlines() if line]
            assert len(lines) == total_lines, \
                f"Expected {total_lines} lines, got {len(lines)}"

            # Verify all threads' lines are present
            for tid in range(num_threads):
                thread_lines = [line for line in lines if f"t{tid}-" in line]
                assert len(thread_lines) == lines_per_thread, \
                    f"Thread {tid} lost data: expected {lines_per_thread}, got {len(thread_lines)}"

    def test_flush_resets_count_and_timer(self):
        """All lines are written immediately — file has all 15 lines."""
        with tempfile.TemporaryDirectory() as tmpdir:
            handler = self._make_handler(tmpdir)
            log_path = os.path.join(tmpdir, f"{time.strftime('%Y-%m-%d')}.log")

            for i in range(10):
                handler.emit(self._make_record(f"batch1-line{i}"))

            assert os.path.exists(log_path)
            for i in range(5):
                handler.emit(self._make_record(f"batch2-line{i}"))

            content = Path(log_path).read_text(encoding="utf-8")
            lines = [line for line in content.strip().splitlines() if line]
            assert len(lines) == 15, \
                f"Expected 15 lines (all written immediately), got {len(lines)}"

            handler.close()


# ==================== Original tests (restored) ====================


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
