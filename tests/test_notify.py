"""桌面通知测试 — 覆盖 send_notification 平台分发。"""

from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest

from app.utils.notify import send_notification


# ── send_notification ──


class TestSendNotification:
    """通知发送。"""

    def test_unsupported_platform(self):
        """不支持的平台返回 False。"""
        with patch("app.utils.notify.is_windows", return_value=False), \
             patch("app.utils.notify.is_macos", return_value=False), \
             patch("app.utils.notify.is_linux", return_value=False):
            result = send_notification("Test", "Message")
            assert result is False

    def test_windows_success(self):
        """Windows 通知成功。"""
        mock_result = MagicMock(returncode=0)
        with patch("app.utils.notify.is_windows", return_value=True), \
             patch("app.utils.notify.subprocess.run", return_value=mock_result):
            result = send_notification("Test", "Message")
            assert result is True

    def test_windows_failure(self):
        """Windows 通知失败。"""
        mock_result = MagicMock(returncode=1)
        with patch("app.utils.notify.is_windows", return_value=True), \
             patch("app.utils.notify.subprocess.run", return_value=mock_result), \
             patch("app.utils.notify.os.environ", {"USERNAME": "test"}):
            result = send_notification("Test", "Message")
            assert result is False

    def test_macos_success(self):
        """macOS 通知成功。"""
        mock_result = MagicMock(returncode=0)
        with patch("app.utils.notify.is_windows", return_value=False), \
             patch("app.utils.notify.is_macos", return_value=True), \
             patch("app.utils.notify.subprocess.run", return_value=mock_result):
            result = send_notification("Test", "Message")
            assert result is True

    def test_linux_success(self):
        """Linux 通知成功。"""
        mock_result = MagicMock(returncode=0)
        with patch("app.utils.notify.is_windows", return_value=False), \
             patch("app.utils.notify.is_macos", return_value=False), \
             patch("app.utils.notify.is_linux", return_value=True), \
             patch("app.utils.notify.shutil.which", return_value="/usr/bin/notify-send"), \
             patch("app.utils.notify.subprocess.run", return_value=mock_result):
            result = send_notification("Test", "Message")
            assert result is True

    def test_linux_no_notify_send(self):
        """Linux 无 notify-send 返回 False。"""
        with patch("app.utils.notify.is_windows", return_value=False), \
             patch("app.utils.notify.is_macos", return_value=False), \
             patch("app.utils.notify.is_linux", return_value=True), \
             patch("app.utils.notify.shutil.which", return_value=None):
            result = send_notification("Test", "Message")
            assert result is False

    def test_exception_caught(self):
        """异常被捕获返回 False。"""
        with patch("app.utils.notify.is_windows", side_effect=Exception("test")):
            result = send_notification("Test", "Message")
            assert result is False
