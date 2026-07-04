"""LoginSession 单元测试 — 重试循环、取消响应、浏览器关闭。"""

from __future__ import annotations

import threading
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.login_models import (
    AttemptOutcome,
    AttemptOutcomeType,
    LoginRetryPolicy,
)
from app.services.login_session import LoginSession


def _make_config() -> dict:
    """构造最小 worker config dict。"""
    return {
        "username": "u",
        "password": "p",
        "auth_url": "http://x",
        "browser_settings": {},
        "retry_settings": {"max_retries": 3, "retry_interval": 5},
    }


def _outcome(t: AttemptOutcomeType, msg: str = "") -> AttemptOutcome:
    return AttemptOutcome(t, msg)


@pytest.fixture
def mock_browser_ctx():
    """mock BrowserContextManager，记录 __aenter__/__aexit__ 调用次数。"""
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=ctx)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx


@pytest.fixture
def mock_attempt_factory():
    """返回一个工厂，可配置 LoginAttempt.execute 的副作用序列。"""
    created = []

    def _factory(outcomes: list[AttemptOutcome]):
        """outcomes: 每次 execute 返回的结果序列。"""
        execute_mock = AsyncMock(side_effect=outcomes)

        class _FakeAttempt:
            def __init__(self, config, cancel_event, browser=None):
                self.execute = execute_mock
                created.append(self)

        return _FakeAttempt, execute_mock, created

    return _factory


class TestLoginSessionRetryLoop:
    async def test_first_attempt_success(self, mock_browser_ctx, mock_attempt_factory):
        """首试成功：execute 调用 1 次，__aexit__ 调用 1 次。"""
        FakeAttempt, execute_mock, _ = mock_attempt_factory(
            [_outcome(AttemptOutcomeType.SUCCESS, "ok")]
        )

        with (
            patch(
                "app.services.login_session.BrowserContextManager",
                return_value=mock_browser_ctx,
            ),
            patch("app.services.login_session.LoginAttempt", FakeAttempt),
        ):
            session = LoginSession(_make_config(), threading.Event())
            result = await session.run()

        assert result.type == AttemptOutcomeType.SUCCESS
        assert result.message == "ok"
        assert execute_mock.await_count == 1
        assert mock_browser_ctx.__aexit__.await_count == 1

    async def test_retry_then_success(self, mock_browser_ctx, mock_attempt_factory):
        """前两次 RETRYABLE，第三次 SUCCESS：execute 3 次，interruptible_sleep 2 次。"""
        FakeAttempt, execute_mock, _ = mock_attempt_factory(
            [
                _outcome(AttemptOutcomeType.RETRYABLE, "e1"),
                _outcome(AttemptOutcomeType.RETRYABLE, "e2"),
                _outcome(AttemptOutcomeType.SUCCESS, "ok"),
            ]
        )

        sleep_mock = AsyncMock(return_value=True)

        with (
            patch(
                "app.services.login_session.BrowserContextManager",
                return_value=mock_browser_ctx,
            ),
            patch("app.services.login_session.LoginAttempt", FakeAttempt),
            patch("app.services.login_session.interruptible_sleep", sleep_mock),
        ):
            session = LoginSession(_make_config(), threading.Event())
            result = await session.run()

        assert result.type == AttemptOutcomeType.SUCCESS
        assert execute_mock.await_count == 3
        assert sleep_mock.await_count == 2

    async def test_all_retryable_returns_exhausted(
        self, mock_browser_ctx, mock_attempt_factory
    ):
        """全部 RETRYABLE，max_retries=3 → EXHAUSTED，execute 3 次。"""
        FakeAttempt, execute_mock, _ = mock_attempt_factory(
            [_outcome(AttemptOutcomeType.RETRYABLE, "e")] * 3
        )

        sleep_mock = AsyncMock(return_value=True)

        with (
            patch(
                "app.services.login_session.BrowserContextManager",
                return_value=mock_browser_ctx,
            ),
            patch("app.services.login_session.LoginAttempt", FakeAttempt),
            patch("app.services.login_session.interruptible_sleep", sleep_mock),
        ):
            session = LoginSession(
                _make_config(),
                threading.Event(),
                retry_policy=LoginRetryPolicy(max_retries=3, interval_seconds=0.01),
            )
            result = await session.run()

        assert result.type == AttemptOutcomeType.EXHAUSTED
        assert execute_mock.await_count == 3
        assert sleep_mock.await_count == 2  # 最后一次失败后不再 sleep

    async def test_invalid_credential_no_retry(
        self, mock_browser_ctx, mock_attempt_factory
    ):
        """首试 INVALID_CREDENTIAL：不重试，execute 1 次。"""
        FakeAttempt, execute_mock, _ = mock_attempt_factory(
            [_outcome(AttemptOutcomeType.INVALID_CREDENTIAL, "密码错误")]
        )

        with (
            patch(
                "app.services.login_session.BrowserContextManager",
                return_value=mock_browser_ctx,
            ),
            patch("app.services.login_session.LoginAttempt", FakeAttempt),
        ):
            session = LoginSession(_make_config(), threading.Event())
            result = await session.run()

        assert result.type == AttemptOutcomeType.INVALID_CREDENTIAL
        assert execute_mock.await_count == 1

    async def test_cancelled_from_attempt_no_retry(
        self, mock_browser_ctx, mock_attempt_factory
    ):
        """首试返回 CANCELLED：不重试。"""
        FakeAttempt, execute_mock, _ = mock_attempt_factory(
            [_outcome(AttemptOutcomeType.CANCELLED, "已取消")]
        )

        with (
            patch(
                "app.services.login_session.BrowserContextManager",
                return_value=mock_browser_ctx,
            ),
            patch("app.services.login_session.LoginAttempt", FakeAttempt),
        ):
            session = LoginSession(_make_config(), threading.Event())
            result = await session.run()

        assert result.type == AttemptOutcomeType.CANCELLED
        assert execute_mock.await_count == 1


class TestLoginSessionCancel:
    async def test_cancel_before_first_attempt(
        self, mock_browser_ctx, mock_attempt_factory
    ):
        """cancel_event 在首次 execute 前已 set → CANCELLED，execute 0 次。"""
        FakeAttempt, execute_mock, _ = mock_attempt_factory([])

        cancel_event = threading.Event()
        cancel_event.set()

        with (
            patch(
                "app.services.login_session.BrowserContextManager",
                return_value=mock_browser_ctx,
            ),
            patch("app.services.login_session.LoginAttempt", FakeAttempt),
        ):
            session = LoginSession(_make_config(), cancel_event)
            result = await session.run()

        assert result.type == AttemptOutcomeType.CANCELLED
        assert execute_mock.await_count == 0
        assert mock_browser_ctx.__aexit__.await_count == 1

    async def test_cancel_during_sleep(self, mock_browser_ctx, mock_attempt_factory):
        """等待中 cancel_event set → interruptible_sleep 返回 False → CANCELLED。"""
        FakeAttempt, execute_mock, _ = mock_attempt_factory(
            [_outcome(AttemptOutcomeType.RETRYABLE, "e")]
        )

        sleep_mock = AsyncMock(return_value=False)  # 模拟被取消

        with (
            patch(
                "app.services.login_session.BrowserContextManager",
                return_value=mock_browser_ctx,
            ),
            patch("app.services.login_session.LoginAttempt", FakeAttempt),
            patch("app.services.login_session.interruptible_sleep", sleep_mock),
        ):
            session = LoginSession(_make_config(), threading.Event())
            result = await session.run()

        assert result.type == AttemptOutcomeType.CANCELLED
        assert execute_mock.await_count == 1
        assert sleep_mock.await_count == 1

    async def test_max_retries_1_no_sleep(self, mock_browser_ctx, mock_attempt_factory):
        """max_retries=1：单次尝试，无 interruptible_sleep 调用。"""
        FakeAttempt, execute_mock, _ = mock_attempt_factory(
            [_outcome(AttemptOutcomeType.RETRYABLE, "e")]
        )

        sleep_mock = AsyncMock(return_value=True)

        with (
            patch(
                "app.services.login_session.BrowserContextManager",
                return_value=mock_browser_ctx,
            ),
            patch("app.services.login_session.LoginAttempt", FakeAttempt),
            patch("app.services.login_session.interruptible_sleep", sleep_mock),
        ):
            session = LoginSession(
                _make_config(),
                threading.Event(),
                retry_policy=LoginRetryPolicy(max_retries=1, interval_seconds=0.01),
            )
            result = await session.run()

        assert result.type == AttemptOutcomeType.EXHAUSTED
        assert execute_mock.await_count == 1
        assert sleep_mock.await_count == 0


class TestLoginSessionBrowserClose:
    async def test_browser_closed_on_success(
        self, mock_browser_ctx, mock_attempt_factory
    ):
        """成功终态：__aexit__ 调用 1 次。"""
        FakeAttempt, _, _ = mock_attempt_factory([_outcome(AttemptOutcomeType.SUCCESS)])

        with (
            patch(
                "app.services.login_session.BrowserContextManager",
                return_value=mock_browser_ctx,
            ),
            patch("app.services.login_session.LoginAttempt", FakeAttempt),
        ):
            session = LoginSession(_make_config(), threading.Event())
            await session.run()

        assert mock_browser_ctx.__aexit__.await_count == 1

    async def test_browser_closed_on_exhausted(
        self, mock_browser_ctx, mock_attempt_factory
    ):
        """重试耗尽：__aexit__ 调用 1 次。"""
        FakeAttempt, _, _ = mock_attempt_factory(
            [_outcome(AttemptOutcomeType.RETRYABLE)] * 2
        )

        sleep_mock = AsyncMock(return_value=True)

        with (
            patch(
                "app.services.login_session.BrowserContextManager",
                return_value=mock_browser_ctx,
            ),
            patch("app.services.login_session.LoginAttempt", FakeAttempt),
            patch("app.services.login_session.interruptible_sleep", sleep_mock),
        ):
            session = LoginSession(
                _make_config(),
                threading.Event(),
                retry_policy=LoginRetryPolicy(max_retries=2, interval_seconds=0.01),
            )
            await session.run()

        assert mock_browser_ctx.__aexit__.await_count == 1

    async def test_browser_closed_on_cancel(
        self, mock_browser_ctx, mock_attempt_factory
    ):
        """取消终态：__aexit__ 调用 1 次。"""
        FakeAttempt, _, _ = mock_attempt_factory([])

        cancel_event = threading.Event()
        cancel_event.set()

        with (
            patch(
                "app.services.login_session.BrowserContextManager",
                return_value=mock_browser_ctx,
            ),
            patch("app.services.login_session.LoginAttempt", FakeAttempt),
        ):
            session = LoginSession(_make_config(), cancel_event)
            await session.run()

        assert mock_browser_ctx.__aexit__.await_count == 1

    async def test_browser_closed_on_attempt_exception(
        self, mock_browser_ctx, mock_attempt_factory
    ):
        """Attempt 抛程序异常：异常向上传播，__aexit__ 仍调用 1 次。"""
        execute_mock = AsyncMock(side_effect=TypeError("bug"))

        class _FakeAttempt:
            def __init__(self, config, cancel_event, browser=None):
                self.execute = execute_mock

        with (
            patch(
                "app.services.login_session.BrowserContextManager",
                return_value=mock_browser_ctx,
            ),
            patch("app.services.login_session.LoginAttempt", _FakeAttempt),
        ):
            session = LoginSession(_make_config(), threading.Event())

            with pytest.raises(TypeError, match="bug"):
                await session.run()

            # async with 语义保证：异常传播时 __aexit__ 仍执行
            assert mock_browser_ctx.__aexit__.await_count == 1
