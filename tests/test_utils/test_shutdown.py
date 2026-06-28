"""shutdown 工具函数测试。"""

from __future__ import annotations

from unittest.mock import patch

import pytest


class TestForceExit:
    def test_calls_os_exit(self):
        """force_exit 应调用 os._exit。"""
        from app.utils.shutdown import force_exit

        with patch("app.utils.shutdown.os._exit") as mock_exit:
            with patch("app.utils.shutdown.atexit._run_exitfuncs"):
                force_exit(0)
                mock_exit.assert_called_once_with(0)

    def test_runs_atexit_hooks(self):
        """force_exit 应在 os._exit 前执行 atexit 钩子。"""
        from app.utils.shutdown import force_exit

        call_order = []

        with patch("app.utils.shutdown.atexit._run_exitfuncs", side_effect=lambda: call_order.append("atexit")):
            with patch("app.utils.shutdown.os._exit", side_effect=lambda c: call_order.append("exit")):
                force_exit(0)

        assert call_order == ["atexit", "exit"]

    def test_suppresses_atexit_exception(self):
        """atexit 钩子抛异常时，os._exit 仍应执行。"""
        from app.utils.shutdown import force_exit

        with patch("app.utils.shutdown.atexit._run_exitfuncs", side_effect=RuntimeError("cleanup failed")):
            with patch("app.utils.shutdown.os._exit") as mock_exit:
                force_exit(0)
                mock_exit.assert_called_once_with(0)

    def test_default_code_zero(self):
        from app.utils.shutdown import force_exit

        with patch("app.utils.shutdown.os._exit") as mock_exit:
            with patch("app.utils.shutdown.atexit._run_exitfuncs"):
                force_exit()
                mock_exit.assert_called_once_with(0)
