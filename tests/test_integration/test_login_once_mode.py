"""LOGIN_ONCE 模式测试 — 验证 main.py::_run_login_then_exit 的三种结果。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.schemas import LoginCredentials, LoginResult, RuntimeConfig


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
            patch("app.services.login_runner.load_login_config") as mock_load,
            patch("app.network.decision.check_network_status") as mock_net,
            patch("app.services.login_runner.execute_login_with_retries") as mock_login,
        ):
            mock_load.return_value = (
                RuntimeConfig(), None,
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
            patch("app.services.login_runner.load_login_config") as mock_load,
            patch("app.network.decision.check_network_status") as mock_net,
            patch("app.services.login_runner.execute_login_with_retries") as mock_login,
        ):
            mock_load.return_value = (
                RuntimeConfig(), None,
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

        with patch("app.services.login_runner.load_login_config") as mock_load:
            mock_load.return_value = (None, LoginResult.CONFIG_ERROR)

            result = _run_login_then_exit(ctx, logger)

        assert result == LoginResult.CONFIG_ERROR

    def test_login_once_records_history(self):
        """login_once 登录成功后应记录登录历史。"""
        from main import _execute_login_with_retries

        logger = MagicMock()
        _creds = LoginCredentials(username="testuser", password="pass", auth_url="http://10.0.0.1")
        runtime_config = RuntimeConfig(credentials=_creds)

        mock_result = MagicMock()
        mock_result.success = True
        mock_result.data = "登录成功"

        with (
            patch("app.services.profile_service.create_profile_service") as mock_profile_factory,
            patch("app.services.login_history_service.LoginHistoryService") as mock_history_cls,
            patch("app.workers.playwright_worker.get_worker") as mock_get_worker,
            patch("app.workers.playwright_worker.cleanup_orphan_browsers"),
        ):
            mock_history = MagicMock()
            mock_history_cls.return_value = mock_history
            mock_get_worker.return_value.submit.return_value = mock_result

            result = _execute_login_with_retries(runtime_config, logger)

        assert result == LoginResult.SUCCESS
        mock_history.add.assert_called_once()
        call_kwargs = mock_history.add.call_args[1]
        assert call_kwargs["success"] is True
        assert call_kwargs["duration_ms"] >= 0
        assert call_kwargs["error"] == ""

    def test_login_once_records_failure_history(self):
        """login_once 登录失败后应记录失败历史。"""
        from main import _execute_login_with_retries
        from app.schemas import RetrySettings

        logger = MagicMock()
        _creds = LoginCredentials(username="testuser", password="pass", auth_url="http://10.0.0.1")
        runtime_config = RuntimeConfig(credentials=_creds, retry=RetrySettings(max_retries=1))

        mock_result = MagicMock()
        mock_result.success = False
        mock_result.error = "密码错误"

        with (
            patch("app.services.profile_service.create_profile_service") as mock_profile_factory,
            patch("app.services.login_history_service.LoginHistoryService") as mock_history_cls,
            patch("app.workers.playwright_worker.get_worker") as mock_get_worker,
            patch("app.workers.playwright_worker.cleanup_orphan_browsers"),
        ):
            mock_history = MagicMock()
            mock_history_cls.return_value = mock_history
            mock_get_worker.return_value.submit.return_value = mock_result

            result = _execute_login_with_retries(runtime_config, logger)

        assert result == LoginResult.TEMPORARY_FAILURE
        mock_history.add.assert_called_once()
        call_kwargs = mock_history.add.call_args[1]
        assert call_kwargs["success"] is False
        assert call_kwargs["error"] == "密码错误"
