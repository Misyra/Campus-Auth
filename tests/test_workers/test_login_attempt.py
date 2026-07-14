"""LoginAttempt 单元测试。"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.utils.exceptions import LoginCancelledError
from app.workers.login_attempt import LoginAttempt
from app.workers.login_models import AttemptOutcomeType


def _make_attempt(config: dict | None = None):
    """构造最小可用的 LoginAttempt 实例。"""
    cfg = config or {
        "username": "u",
        "password": "p",
        "auth_url": "http://example.com",
        "isp": "",
        "browser_settings": {},
        "monitor": {"post_login_delay": 0},
        "active_task": "",
    }
    # cancel_event.is_set() 必须返回 False，否则会触发"登录已取消"分支
    cancel_event = MagicMock()
    cancel_event.is_set = MagicMock(return_value=False)
    return LoginAttempt(cfg, cancel_event)


class TestExecuteOutcomeMapping:
    """execute() 的 outcome 映射测试。"""

    @pytest.mark.asyncio
    async def test_success_returns_success(self):
        """attempt_login 成功 → SUCCESS。"""
        attempt = _make_attempt()
        with patch.object(
            attempt, "attempt_login", new=AsyncMock(return_value=(True, "ok"))
        ):
            outcome = await attempt.execute()
        assert outcome.type == AttemptOutcomeType.SUCCESS
        assert outcome.message == "ok"

    @pytest.mark.asyncio
    async def test_failure_signal_returns_invalid_credential(self):
        """命中失败信号 → INVALID_CREDENTIAL（终态，不重试）。"""
        attempt = _make_attempt()
        with patch.object(
            attempt,
            "attempt_login",
            new=AsyncMock(return_value=(False, "命中失败信号: 密码错误")),
        ):
            outcome = await attempt.execute()
        assert outcome.type == AttemptOutcomeType.INVALID_CREDENTIAL
        assert "密码错误" in outcome.message
        assert outcome.should_retry is False

    @pytest.mark.asyncio
    async def test_generic_failure_returns_retryable(self):
        """attempt_login 普通失败（非失败信号）→ RETRYABLE。"""
        attempt = _make_attempt()
        with patch.object(
            attempt,
            "attempt_login",
            new=AsyncMock(return_value=(False, "网络未通")),
        ):
            outcome = await attempt.execute()
        assert outcome.type == AttemptOutcomeType.RETRYABLE
        assert outcome.should_retry is True

    @pytest.mark.asyncio
    async def test_cancelled_returns_cancelled(self):
        """LoginCancelledError → CANCELLED。"""
        attempt = _make_attempt()
        with patch.object(
            attempt,
            "attempt_login",
            new=AsyncMock(side_effect=LoginCancelledError()),
        ):
            outcome = await attempt.execute()
        assert outcome.type == AttemptOutcomeType.CANCELLED


class TestRedundantBranchesRemoved:
    """验证冗余异常分支被删除。"""

    @pytest.mark.asyncio
    async def test_settle_seconds_constant_removed(self):
        """LOGIN_SUCCESS_SETTLE_SECONDS 常量已移除。"""
        import app.workers.login_attempt as mod

        assert not hasattr(mod, "LOGIN_SUCCESS_SETTLE_SECONDS")

    @pytest.mark.asyncio
    async def test_internal_exception_caught_by_attempt_login(self):
        """attempt_login 内部 catch 异常返回 (False, str(exc))，
        execute 不会再 catch PlaywrightError 等异常。"""
        attempt = _make_attempt()
        # attempt_login 内部已 catch 异常返回 (False, str(exc))，
        # execute 看不到原始异常
        with patch.object(
            attempt,
            "attempt_login",
            new=AsyncMock(return_value=(False, "ConnectionRefusedError: x")),
        ):
            outcome = await attempt.execute()
        assert outcome.type == AttemptOutcomeType.RETRYABLE


class TestVerifyNetworkAfterLogin:
    """_verify_network_after_login 方法测试。"""

    @pytest.mark.asyncio
    async def test_all_disabled_returns_true(self):
        """所有检测禁用 → 信任步骤 → (True, 'all_disabled')。"""
        attempt = _make_attempt(
            {
                "username": "u",
                "password": "p",
                "auth_url": "http://example.com",
                "isp": "",
                "browser_settings": {},
                "monitor": {
                    "post_login_delay": 0,
                    "enable_tcp_check": False,
                    "enable_http_check": False,
                    "enable_local_check": False,
                },
                "active_task": "",
            }
        )
        with patch(
            "app.network.decision.check_network_status",
            new=AsyncMock(return_value=(False, "all_disabled", "none")),
        ):
            ok, msg = await attempt._verify_network_after_login()
        assert ok is True
        assert msg == "all_disabled"

    @pytest.mark.asyncio
    async def test_network_ok_returns_true(self):
        """网络恢复 → (True, 'network_ok (...)')。"""
        attempt = _make_attempt(
            {
                "username": "u",
                "password": "p",
                "auth_url": "http://example.com",
                "isp": "",
                "browser_settings": {},
                "monitor": {
                    "post_login_delay": 0,
                    "enable_tcp_check": True,
                },
                "active_task": "",
            }
        )
        # check_network_status 是在方法内部 import 的，需要 patch 正确路径
        with patch(
            "app.network.decision.check_network_status",
            new=AsyncMock(return_value=(True, "ok", "tcp")),
        ):
            ok, msg = await attempt._verify_network_after_login()
        assert ok is True
        assert "network_ok" in msg

    @pytest.mark.asyncio
    async def test_network_down_returns_false(self):
        """网络未恢复 → (False, 状态描述)。"""
        attempt = _make_attempt(
            {
                "username": "u",
                "password": "p",
                "auth_url": "http://example.com",
                "isp": "",
                "browser_settings": {},
                "monitor": {
                    "post_login_delay": 0,
                    "enable_tcp_check": True,
                },
                "active_task": "",
            }
        )
        with patch(
            "app.network.decision.check_network_status",
            new=AsyncMock(return_value=(False, "tcp_failed", "tcp")),
        ):
            ok, msg = await attempt._verify_network_after_login()
        assert ok is False
        assert msg == "tcp_failed"


class TestExecuteBrowserTaskExplicitChecks:
    """_execute_browser_task 的 has_explicit_checks 分支测试。"""

    @pytest.mark.asyncio
    async def test_declared_checks_skips_network_detection(self):
        """任务声明 failure_checks → has_explicit_checks=True → 跳过网络检测直接 SUCCESS。"""
        attempt = _make_attempt()

        # 构造带 failure_checks 的 task
        task = MagicMock()
        task.task_id = "t1"
        task.url = "http://example.com"
        task.steps = []
        task.success_checks = []
        task.failure_checks = [MagicMock()]  # 非空 → has_explicit_checks=True
        type(task).__name__ = "TaskConfig"

        # mock executor.execute 返回成功
        mock_executor = MagicMock()
        mock_executor.execute = AsyncMock(return_value=(True, "步骤通过"))

        # mock 浏览器
        mock_page = MagicMock()
        mock_page.on = MagicMock()
        mock_page.remove_listener = MagicMock()
        mock_browser_mgr = MagicMock()
        mock_browser_mgr.page = mock_page
        mock_browser_mgr.__aenter__ = AsyncMock(return_value=mock_browser_mgr)
        mock_browser_mgr.__aexit__ = AsyncMock()

        verify_mock = AsyncMock(return_value=(True, "should_not_be_called"))

        with (
            patch(
                "app.workers.login_attempt.BrowserContextManager",
                return_value=mock_browser_mgr,
            ),
            patch(
                "app.workers.login_attempt.build_login_template_vars", return_value={}
            ),
            patch("app.tasks.BrowserTaskRunner", return_value=mock_executor),
            patch.object(
                attempt, "_verify_network_after_login", verify_mock
            ),
        ):
            ok, msg = await attempt._execute_browser_task(
                task, "default", time.perf_counter()
            )

        assert ok is True
        # _verify_network_after_login 不应被调用（声明了 checks）
        verify_mock.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_checks_runs_network_detection(self):
        """任务未声明 checks → has_explicit_checks=False → 走网络检测。"""
        attempt = _make_attempt()

        task = MagicMock()
        task.task_id = "t1"
        task.url = "http://example.com"
        task.steps = []
        task.success_checks = []  # 空
        task.failure_checks = []  # 空 → has_explicit_checks=False
        type(task).__name__ = "TaskConfig"

        mock_executor = MagicMock()
        mock_executor.execute = AsyncMock(return_value=(True, "步骤通过"))

        mock_page = MagicMock()
        mock_page.on = MagicMock()
        mock_page.remove_listener = MagicMock()
        mock_browser_mgr = MagicMock()
        mock_browser_mgr.page = mock_page
        mock_browser_mgr.__aenter__ = AsyncMock(return_value=mock_browser_mgr)
        mock_browser_mgr.__aexit__ = AsyncMock()

        verify_mock = AsyncMock(return_value=(True, "network_ok"))

        with (
            patch(
                "app.workers.login_attempt.BrowserContextManager",
                return_value=mock_browser_mgr,
            ),
            patch(
                "app.workers.login_attempt.build_login_template_vars", return_value={}
            ),
            patch("app.tasks.BrowserTaskRunner", return_value=mock_executor),
            patch.object(
                attempt, "_verify_network_after_login", verify_mock
            ),
        ):
            ok, msg = await attempt._execute_browser_task(
                task, "default", time.perf_counter()
            )

        assert ok is True
        # _verify_network_after_login 应被调用一次
        verify_mock.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_no_checks_network_down_returns_failure(self):
        """任务未声明 checks + 网络检测失败 → 返回失败（可重试）。"""
        attempt = _make_attempt()

        task = MagicMock()
        task.task_id = "t1"
        task.url = "http://example.com"
        task.steps = []
        task.success_checks = []
        task.failure_checks = []
        type(task).__name__ = "TaskConfig"

        mock_executor = MagicMock()
        mock_executor.execute = AsyncMock(return_value=(True, "步骤通过"))

        mock_page = MagicMock()
        mock_page.on = MagicMock()
        mock_page.remove_listener = MagicMock()
        mock_browser_mgr = MagicMock()
        mock_browser_mgr.page = mock_page
        mock_browser_mgr.__aenter__ = AsyncMock(return_value=mock_browser_mgr)
        mock_browser_mgr.__aexit__ = AsyncMock()

        verify_mock = AsyncMock(return_value=(False, "network_down"))

        with (
            patch(
                "app.workers.login_attempt.BrowserContextManager",
                return_value=mock_browser_mgr,
            ),
            patch(
                "app.workers.login_attempt.build_login_template_vars", return_value={}
            ),
            patch("app.tasks.BrowserTaskRunner", return_value=mock_executor),
            patch.object(
                attempt, "_verify_network_after_login", verify_mock
            ),
        ):
            ok, msg = await attempt._execute_browser_task(
                task, "default", time.perf_counter()
            )

        assert ok is False
        assert "步骤通过但网络未恢复" in msg
