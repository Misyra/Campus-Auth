from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.utils.notify import send_notification


class TestSendNotificationWindows:
    """测试 Windows 平台通知路径"""

    def test_windows_calls_powershell(self):
        with patch("src.utils.notify.is_windows", return_value=True):
            with patch("src.utils.notify.is_macos", return_value=False):
                with patch("src.utils.notify.is_linux", return_value=False):
                    with patch("src.utils.notify.subprocess.run") as mock_run:
                        mock_run.return_value = MagicMock(returncode=0)
                        result = send_notification("Title", "Message", 5000)
                        assert result is True
                        # 验证 PowerShell 被调用
                        cmd = mock_run.call_args[0][0]
                        assert cmd[0] == "powershell"

    def test_windows_powershell_failure_falls_back_to_msg(self):
        with patch("src.utils.notify.is_windows", return_value=True):
            with patch("src.utils.notify.is_macos", return_value=False):
                with patch("src.utils.notify.is_linux", return_value=False):
                    with patch("src.utils.notify.subprocess.run") as mock_run:
                        # 第一次调用（PowerShell）失败，第二次（msg）成功
                        mock_run.side_effect = [
                            MagicMock(returncode=1),
                            MagicMock(returncode=0),
                        ]
                        result = send_notification("Title", "Message", 5000)
                        assert result is True
                        # 第二次调用应该是 msg
                        assert mock_run.call_count == 2
                        assert mock_run.call_args_list[1][0][0][0] == "msg"


class TestSendNotificationMacos:
    """测试 macOS 平台通知路径"""

    def test_macos_calls_osascript(self):
        with patch("src.utils.notify.is_windows", return_value=False):
            with patch("src.utils.notify.is_macos", return_value=True):
                with patch("src.utils.notify.is_linux", return_value=False):
                    with patch("src.utils.notify.subprocess.run") as mock_run:
                        mock_run.return_value = MagicMock(returncode=0)
                        result = send_notification("Title", "Message")
                        assert result is True
                        cmd = mock_run.call_args[0][0]
                        assert cmd[0] == "osascript"

    def test_macos_escapes_backslash_in_message(self):
        """macOS 通知中反斜杠应被转义"""
        with patch("src.utils.notify.is_windows", return_value=False):
            with patch("src.utils.notify.is_macos", return_value=True):
                with patch("src.utils.notify.is_linux", return_value=False):
                    with patch("src.utils.notify.subprocess.run") as mock_run:
                        mock_run.return_value = MagicMock(returncode=0)
                        send_notification("Title", "C:\\path\\to\\file")
                        script = mock_run.call_args[0][0][-1]
                        # 反斜杠应被双转义
                        assert "C:\\\\path\\\\to\\\\file" in script

    def test_macos_replaces_newline_with_space(self):
        """macOS 通知中换行符应被替换为空格"""
        with patch("src.utils.notify.is_windows", return_value=False):
            with patch("src.utils.notify.is_macos", return_value=True):
                with patch("src.utils.notify.is_linux", return_value=False):
                    with patch("src.utils.notify.subprocess.run") as mock_run:
                        mock_run.return_value = MagicMock(returncode=0)
                        send_notification("Title", "line1\nline2\nline3")
                        script = mock_run.call_args[0][0][-1]
                        # 换行符应被替换为空格
                        assert "line1 line2 line3" in script


class TestSendNotificationLinux:
    """测试 Linux 平台通知路径"""

    def test_linux_notify_send_not_found_returns_false(self):
        """notify-send 不存在时应优雅返回 False，不崩溃"""
        with patch("src.utils.notify.is_windows", return_value=False):
            with patch("src.utils.notify.is_macos", return_value=False):
                with patch("src.utils.notify.is_linux", return_value=True):
                    with patch("src.utils.notify.shutil.which", return_value=None):
                        with patch("src.utils.notify.subprocess.run") as mock_run:
                            result = send_notification("Title", "Message")
                            assert result is False
                            # subprocess.run 不应被调用
                            mock_run.assert_not_called()

    def test_linux_notify_send_found_calls_subprocess(self):
        """notify-send 存在时应调用 subprocess.run"""
        with patch("src.utils.notify.is_windows", return_value=False):
            with patch("src.utils.notify.is_macos", return_value=False):
                with patch("src.utils.notify.is_linux", return_value=True):
                    with patch("src.utils.notify.shutil.which", return_value="/usr/bin/notify-send"):
                        with patch("src.utils.notify.subprocess.run") as mock_run:
                            mock_run.return_value = MagicMock(returncode=0)
                            result = send_notification("Title", "Message", 3000)
                            assert result is True
                            mock_run.assert_called_once()
                            cmd = mock_run.call_args[0][0]
                            assert cmd[0] == "notify-send"
                            assert cmd[1] == "Title"
                            assert cmd[2] == "Message"

    def test_linux_notify_send_failed_returns_false(self):
        """notify-send 执行失败时应返回 False"""
        with patch("src.utils.notify.is_windows", return_value=False):
            with patch("src.utils.notify.is_macos", return_value=False):
                with patch("src.utils.notify.is_linux", return_value=True):
                    with patch("src.utils.notify.shutil.which", return_value="/usr/bin/notify-send"):
                        with patch("src.utils.notify.subprocess.run") as mock_run:
                            mock_run.return_value = MagicMock(returncode=1)
                            result = send_notification("Title", "Message")
                            assert result is False
