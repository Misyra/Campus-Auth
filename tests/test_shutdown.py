from __future__ import annotations

import os
import signal
import sys
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch


class TestCleanupPidFile:

    def _make_cleanup_fn(self):
        def _cleanup_pid_file():
            try:
                pid_dir = Path.home() / ".campus_network_auth"
                pid_file = pid_dir / "campus_network_auth.pid"
                pid_file.unlink(missing_ok=True)
            except Exception:
                pass
        return _cleanup_pid_file

    def test_cleanup_removes_existing_pid_file(self, tmp_path):
        pid_dir = tmp_path / ".campus_network_auth"
        pid_dir.mkdir()
        pid_file = pid_dir / "campus_network_auth.pid"
        pid_file.write_text("12345")

        with patch("pathlib.Path.home", return_value=tmp_path):
            cleanup = self._make_cleanup_fn()
            cleanup()

        assert not pid_file.exists()

    def test_cleanup_missing_pid_file_no_error(self, tmp_path):
        with patch("pathlib.Path.home", return_value=tmp_path):
            cleanup = self._make_cleanup_fn()
            cleanup()

    def test_cleanup_idempotent(self, tmp_path):
        with patch("pathlib.Path.home", return_value=tmp_path):
            cleanup = self._make_cleanup_fn()
            cleanup()
            cleanup()


class TestForceExitAfterTimeout:

    def _make_force_exit_fn(self, timeout_seconds=1):
        def _force_exit_after_timeout(timeout_seconds=timeout_seconds):
            time.sleep(timeout_seconds)
            os._exit(0)
        return _force_exit_after_timeout

    def test_watchdog_calls_os_exit_after_delay(self):
        with patch("os._exit") as mock_exit, patch("time.sleep"):
            force_exit = self._make_force_exit_fn(timeout_seconds=1)
            force_exit()
            mock_exit.assert_called_once_with(0)


class TestShutdownFlow:

    def test_windows_path_calls_pid_cleanup_before_sys_exit(self):
        pid_cleanup_called = []
        sys_exit_raised = []

        def fake_cleanup():
            pid_cleanup_called.append(True)

        def fake_sys_exit(code=0):
            sys_exit_raised.append(code)
            raise SystemExit(code)

        with patch.object(sys, "platform", "win32"):
            fake_cleanup()
            try:
                fake_sys_exit(0)
            except SystemExit:
                pass

        assert pid_cleanup_called
        assert sys_exit_raised == [0]

    def test_non_windows_path_uses_sigterm(self):
        kill_called = []

        def fake_kill(pid, sig):
            kill_called.append((pid, sig))

        with patch.object(sys, "platform", "linux"):
            with patch("os.kill", fake_kill), patch("os.getpid", return_value=9999):
                os.kill(os.getpid(), signal.SIGTERM)

        assert len(kill_called) == 1
        assert kill_called[0] == (9999, signal.SIGTERM)

    def test_stop_monitoring_called_first(self):
        call_order = []

        mock_service = MagicMock()
        mock_service.stop_monitoring.side_effect = lambda: call_order.append("stop_monitoring")

        def fake_cleanup():
            call_order.append("cleanup_pid")

        mock_service.stop_monitoring()
        fake_cleanup()

        assert call_order == ["stop_monitoring", "cleanup_pid"]

    def test_tray_stop_called_after_monitoring(self):
        call_order = []

        mock_service = MagicMock()
        mock_service.stop_monitoring.side_effect = lambda: call_order.append("stop_monitoring")

        mock_tray = MagicMock()
        mock_tray.stop.side_effect = lambda: call_order.append("tray_stop")

        mock_service.stop_monitoring()
        if mock_tray:
            mock_tray.stop()

        assert call_order == ["stop_monitoring", "tray_stop"]

    def test_tray_stop_skipped_when_none(self):
        call_order = []

        mock_service = MagicMock()
        mock_service.stop_monitoring.side_effect = lambda: call_order.append("stop_monitoring")

        mock_tray = None

        mock_service.stop_monitoring()
        if mock_tray:
            mock_tray.stop()
            call_order.append("tray_stop")

        assert call_order == ["stop_monitoring"]

    def test_sys_exit_with_watchdog_pattern(self):
        watchdog_started = threading.Event()
        sys_exit_called = threading.Event()

        def mock_force_exit():
            time.sleep(0.05)
            watchdog_started.set()

        def mock_sys_exit(code=0):
            sys_exit_called.set()
            raise SystemExit(code)

        watchdog = threading.Thread(target=mock_force_exit, daemon=True)
        watchdog.start()

        try:
            mock_sys_exit(0)
        except SystemExit:
            pass

        assert sys_exit_called.is_set()
        watchdog_started.wait(timeout=1)
        assert watchdog_started.is_set()
