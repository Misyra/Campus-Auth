"""LOGIN_ONCE 模式测试 — 验证 run_login_then_exit 的三种结果。"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from unittest.mock import AsyncMock, MagicMock, patch

from app.schemas import LoginCredentials, LoginResult, RuntimeConfig
from app.services.login_orchestrator import LoginOrchestrator
from app.services.worker_port import WorkerResponse


def _build_container_with_orchestrator(
    runtime_config: RuntimeConfig,
    mock_worker: MagicMock,
    mock_history: MagicMock | None = None,
):
    """构造测试 container，注入真实 LoginOrchestrator + mock worker。

    返回 (container, executor)，调用方负责 executor.shutdown。
    """
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="test-login")
    orchestrator = LoginOrchestrator(
        worker_getter=lambda: mock_worker,
        get_runtime_config=lambda: runtime_config,
        executor=executor,
        login_history=mock_history,
        profile_service=MagicMock(),
    )
    container = MagicMock()
    container.config_service.get_runtime_config.return_value = runtime_config
    container.login_orchestrator = orchestrator
    return container, executor


class TestLoginOnceMode:
    """LOGIN_ONCE 模式测试。"""

    def _make_ctx(self):
        ctx = MagicMock()
        ctx.config.startup_action = "login_once"
        return ctx

    def test_success(self):
        """网络未连接 → 登录成功 → 返回 LoginResult.SUCCESS。"""
        from app.services.login_runner import (
            run_login_then_exit as _run_login_then_exit,
        )

        ctx = self._make_ctx()
        logger = MagicMock()
        container = MagicMock()
        container.config_service.get_runtime_config.return_value = RuntimeConfig()

        with (
            patch(
                "app.network.decision.check_network_status", new_callable=AsyncMock
            ) as mock_net,
            patch("app.services.login_runner.execute_login_with_retries") as mock_login,
        ):
            mock_net.return_value = (False, "network_down", "")
            mock_login.return_value = LoginResult.SUCCESS

            result = _run_login_then_exit(ctx, container, logger)

        assert result == LoginResult.SUCCESS

    def test_temporary_failure(self):
        """网络未连接 → 登录失败 → 返回 LoginResult.TEMPORARY_FAILURE。"""
        from app.services.login_runner import (
            run_login_then_exit as _run_login_then_exit,
        )

        ctx = self._make_ctx()
        logger = MagicMock()
        container = MagicMock()
        container.config_service.get_runtime_config.return_value = RuntimeConfig()

        with (
            patch(
                "app.network.decision.check_network_status", new_callable=AsyncMock
            ) as mock_net,
            patch("app.services.login_runner.execute_login_with_retries") as mock_login,
        ):
            mock_net.return_value = (False, "network_down", "")
            mock_login.return_value = LoginResult.TEMPORARY_FAILURE

            result = _run_login_then_exit(ctx, container, logger)

        assert result == LoginResult.TEMPORARY_FAILURE

    def test_config_error(self):
        """配置加载失败 → 返回 LoginResult.CONFIG_ERROR。"""
        from app.services.login_runner import (
            run_login_then_exit as _run_login_then_exit,
        )

        ctx = self._make_ctx()
        logger = MagicMock()
        container = MagicMock()
        container.config_service.get_runtime_config.side_effect = Exception(
            "配置加载失败"
        )

        result = _run_login_then_exit(ctx, container, logger)

        assert result == LoginResult.CONFIG_ERROR

    def test_login_once_records_history(self):
        """login_once 登录成功后应记录登录历史。"""
        from app.services.login_runner import (
            execute_login_with_retries as _execute_login_with_retries,
        )

        logger = MagicMock()
        _creds = LoginCredentials(
            username="testuser", password="pass", auth_url="http://10.0.0.1"
        )
        runtime_config = RuntimeConfig(credentials=_creds)

        mock_worker = MagicMock()
        mock_worker.submit.return_value = WorkerResponse(success=True, data="登录成功")
        mock_history = MagicMock()

        container, executor = _build_container_with_orchestrator(
            runtime_config, mock_worker, mock_history
        )

        try:
            with patch("app.services.worker_port.cleanup_orphan_browsers"):
                result = _execute_login_with_retries(runtime_config, container, logger)
        finally:
            executor.shutdown(wait=True)

        assert result == LoginResult.SUCCESS
        mock_history.add.assert_called_once()
        call_kwargs = mock_history.add.call_args[1]
        assert call_kwargs["success"] is True
        assert call_kwargs["duration_ms"] >= 0
        assert call_kwargs["error"] == ""

    def test_login_once_records_failure_history(self):
        """login_once 登录失败后应记录失败历史。"""
        from app.schemas import RetrySettings
        from app.services.login_runner import (
            execute_login_with_retries as _execute_login_with_retries,
        )

        logger = MagicMock()
        _creds = LoginCredentials(
            username="testuser", password="pass", auth_url="http://10.0.0.1"
        )
        runtime_config = RuntimeConfig(
            credentials=_creds, retry=RetrySettings(max_retries=1)
        )

        mock_worker = MagicMock()
        mock_worker.submit.return_value = WorkerResponse(
            success=False, error="密码错误"
        )
        mock_history = MagicMock()

        container, executor = _build_container_with_orchestrator(
            runtime_config, mock_worker, mock_history
        )

        try:
            with patch("app.services.worker_port.cleanup_orphan_browsers"):
                result = _execute_login_with_retries(runtime_config, container, logger)
        finally:
            executor.shutdown(wait=True)

        assert result == LoginResult.TEMPORARY_FAILURE
        mock_history.add.assert_called_once()
        call_kwargs = mock_history.add.call_args[1]
        assert call_kwargs["success"] is False
        assert call_kwargs["error"] == "密码错误"
