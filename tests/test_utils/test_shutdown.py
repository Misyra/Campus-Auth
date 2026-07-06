"""shutdown 工具函数测试。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


class TestForceExit:
    """生产环境路径测试（_is_test_environment=False）。"""

    @patch("app.utils.shutdown._is_test_environment", return_value=False)
    def test_calls_os_exit(self, _mock):
        """force_exit 应调用 os._exit。"""
        from app.utils.shutdown import force_exit

        with patch("app.utils.shutdown.os._exit") as mock_exit:
            with patch("app.utils.shutdown.threading.Timer"):
                force_exit(0)
                mock_exit.assert_called_once_with(0)

    @patch("app.utils.shutdown._is_test_environment", return_value=False)
    def test_runs_exit_handlers(self, _mock):
        """force_exit 应在 os._exit 前执行退出钩子。"""
        from app.utils.shutdown import _exit_handlers, force_exit

        call_order = []
        original_len = len(_exit_handlers)

        handler = MagicMock(side_effect=lambda: call_order.append("handler"))
        _exit_handlers.append((handler, (), {}))
        try:
            with patch(
                "app.utils.shutdown.os._exit",
                side_effect=lambda c: call_order.append("exit"),
            ):
                with patch("app.utils.shutdown.threading.Timer"):
                    force_exit(0)
            assert call_order == ["handler", "exit"]
        finally:
            _exit_handlers.pop()

    @patch("app.utils.shutdown._is_test_environment", return_value=False)
    def test_suppresses_handler_exception(self, _mock):
        """退出钩子抛异常时，os._exit 仍应执行。"""
        from app.utils.shutdown import _exit_handlers, force_exit

        original_len = len(_exit_handlers)
        handler = MagicMock(side_effect=RuntimeError("cleanup failed"))
        _exit_handlers.append((handler, (), {}))
        try:
            with patch("app.utils.shutdown.os._exit") as mock_exit:
                with patch("app.utils.shutdown.threading.Timer"):
                    force_exit(0)
                    mock_exit.assert_called_once_with(0)
        finally:
            _exit_handlers.pop()

    @patch("app.utils.shutdown._is_test_environment", return_value=False)
    def test_default_code_zero(self, _mock):
        from app.utils.shutdown import force_exit

        with patch("app.utils.shutdown.os._exit") as mock_exit:
            with patch("app.utils.shutdown.threading.Timer"):
                force_exit()
                mock_exit.assert_called_once_with(0)


class TestForceExitTestEnv:
    """测试环境路径测试（_is_test_environment=True）。"""

    @patch("app.utils.shutdown._is_test_environment", return_value=True)
    def test_uses_sys_exit_in_test_env(self, _mock):
        """测试环境下应使用 sys.exit 而非 os._exit。"""
        from app.utils.shutdown import force_exit

        with patch("app.utils.shutdown.sys.exit", side_effect=SystemExit) as mock_exit:
            with patch("app.utils.shutdown.os._exit") as mock_os_exit:
                with pytest.raises(SystemExit):
                    force_exit(0)
                mock_exit.assert_called_once_with(0)
                mock_os_exit.assert_not_called()

    @patch("app.utils.shutdown._is_test_environment", return_value=True)
    def test_default_code_zero_test_env(self, _mock):
        from app.utils.shutdown import force_exit

        with patch("app.utils.shutdown.sys.exit", side_effect=SystemExit) as mock_exit:
            with pytest.raises(SystemExit):
                force_exit()
            mock_exit.assert_called_once_with(0)
