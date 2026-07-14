"""LoginAttempt 单元测试。"""

from __future__ import annotations

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
    return LoginAttempt(cfg, MagicMock())


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
