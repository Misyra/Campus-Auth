"""shutdown 工具函数测试。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


class TestRegisterExitHandler:
    """register_exit_handler 注册与执行测试。"""

    def test_register_and_run_handler(self):
        """注册的钩子应在 _run_exit_handlers 中被调用。"""
        from app.utils.shutdown import (
            _exit_handlers,
            _run_exit_handlers,
            register_exit_handler,
        )

        handler = MagicMock()
        register_exit_handler(handler)
        try:
            _run_exit_handlers()
            handler.assert_called_once()
        finally:
            _exit_handlers.pop()

    def test_register_with_args_and_kwargs(self):
        """注册时传递的参数应被正确传递。"""
        from app.utils.shutdown import (
            _exit_handlers,
            _run_exit_handlers,
            register_exit_handler,
        )

        handler = MagicMock()
        register_exit_handler(handler, 1, 2, key="value")
        try:
            _run_exit_handlers()
            handler.assert_called_once_with(1, 2, key="value")
        finally:
            _exit_handlers.pop()

    def test_multiple_handlers_run_in_order(self):
        """多个钩子应按注册顺序执行。"""
        from app.utils.shutdown import (
            _exit_handlers,
            _run_exit_handlers,
            register_exit_handler,
        )

        call_order = []
        handler1 = MagicMock(side_effect=lambda: call_order.append(1))
        handler2 = MagicMock(side_effect=lambda: call_order.append(2))
        register_exit_handler(handler1)
        register_exit_handler(handler2)
        try:
            _run_exit_handlers()
            assert call_order == [1, 2]
        finally:
            _exit_handlers.pop()
            _exit_handlers.pop()

    def test_handler_exception_does_not_stop_others(self):
        """某个钩子抛异常不应阻止后续钩子执行。"""
        from app.utils.shutdown import (
            _exit_handlers,
            _run_exit_handlers,
            register_exit_handler,
        )

        handler1 = MagicMock(side_effect=RuntimeError("fail"))
        handler2 = MagicMock()
        register_exit_handler(handler1)
        register_exit_handler(handler2)
        try:
            # 异常被抑制，不传播
            _run_exit_handlers()
            handler2.assert_called_once()
        finally:
            _exit_handlers.pop()
            _exit_handlers.pop()


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
