"""LOGIN_ONCE 模式测试 — 验证 main.py::_run_login_then_exit 的三种结果。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.schemas import LoginResult


class TestLoginOnceMode:
    """LOGIN_ONCE 模式测试。"""

    def _make_ctx(self):
        ctx = MagicMock()
        ctx.config.startup_action = "login_once"
        return ctx

    def test_success(self):
        """网络未连接 → 登录成功 → 返回 LoginResult.SUCCESS。"""
        from main import _run_login_then_exit

        ctx = self._make_ctx()
        logger = MagicMock()

        with (
            patch("main._load_login_config") as mock_load,
            patch("app.network.decision.check_network_status") as mock_net,
            patch("main._execute_login_with_retries") as mock_login,
        ):
            mock_load.return_value = (
                {"username": "testuser", "password": "pass", "auth_url": "http://10.0.0.1"},
                None,
            )
            mock_net.return_value = (False, "network_down", "")
            mock_login.return_value = LoginResult.SUCCESS

            result = _run_login_then_exit(ctx, logger)

        assert result == LoginResult.SUCCESS

    def test_temporary_failure(self):
        """网络未连接 → 登录失败 → 返回 LoginResult.TEMPORARY_FAILURE。"""
        from main import _run_login_then_exit

        ctx = self._make_ctx()
        logger = MagicMock()

        with (
            patch("main._load_login_config") as mock_load,
            patch("app.network.decision.check_network_status") as mock_net,
            patch("main._execute_login_with_retries") as mock_login,
        ):
            mock_load.return_value = (
                {"username": "testuser", "password": "pass", "auth_url": "http://10.0.0.1"},
                None,
            )
            mock_net.return_value = (False, "network_down", "")
            mock_login.return_value = LoginResult.TEMPORARY_FAILURE

            result = _run_login_then_exit(ctx, logger)

        assert result == LoginResult.TEMPORARY_FAILURE

    def test_config_error(self):
        """配置加载失败 → 返回 LoginResult.CONFIG_ERROR。"""
        from main import _run_login_then_exit

        ctx = self._make_ctx()
        logger = MagicMock()

        with patch("main._load_login_config") as mock_load:
            mock_load.return_value = (None, LoginResult.CONFIG_ERROR)

            result = _run_login_then_exit(ctx, logger)

        assert result == LoginResult.CONFIG_ERROR
