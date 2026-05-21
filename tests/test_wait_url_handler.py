from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

from src.task_executor import StepConfig, TaskConfig, VariableResolver, WaitUrlHandler


def _make_resolver() -> VariableResolver:
    config = TaskConfig(name="test", url="http://example.com", steps=[])
    return VariableResolver(config=config, env_vars={})


def _make_step(pattern: str | None = None, timeout: int | None = None) -> StepConfig:
    extra = {}
    if pattern is not None:
        extra["pattern"] = pattern
    return StepConfig(id="s1", type="wait_url", timeout=timeout, extra=extra)


def _make_page(url: str) -> MagicMock:
    page = MagicMock()
    page.url = url
    return page


def test_invalid_regex_returns_clear_error() -> None:
    handler = WaitUrlHandler()
    resolver = _make_resolver()
    step = _make_step(pattern="[invalid(", timeout=1000)
    page = _make_page("http://example.com")

    async def _run():
        return await handler.execute(page, step, resolver)

    success, message = asyncio.run(_run())

    assert success is False
    assert "wait_url 步骤的 pattern 不是有效的正则表达式" in message
    assert "[invalid(" in message


def test_empty_pattern_returns_error() -> None:
    handler = WaitUrlHandler()
    resolver = _make_resolver()
    step = _make_step(pattern="", timeout=1000)
    page = _make_page("http://example.com")

    async def _run():
        return await handler.execute(page, step, resolver)

    success, message = asyncio.run(_run())

    assert success is False
    assert "wait_url 步骤需要 pattern" in message


def test_missing_pattern_returns_error() -> None:
    handler = WaitUrlHandler()
    resolver = _make_resolver()
    step = _make_step(timeout=1000)
    page = _make_page("http://example.com")

    async def _run():
        return await handler.execute(page, step, resolver)

    success, message = asyncio.run(_run())

    assert success is False
    assert "wait_url 步骤需要 pattern" in message


def test_valid_regex_matches_url() -> None:
    handler = WaitUrlHandler()
    resolver = _make_resolver()
    step = _make_step(pattern=r"example\.com", timeout=5000)
    page = _make_page("http://example.com/login")

    async def _run():
        return await handler.execute(page, step, resolver)

    success, message = asyncio.run(_run())

    assert success is True
    assert message == ""


def test_valid_regex_no_match_times_out() -> None:
    handler = WaitUrlHandler()
    resolver = _make_resolver()
    step = _make_step(pattern=r"nomatch\.example\.com", timeout=500)
    page = _make_page("http://example.com/login")

    async def _run():
        return await handler.execute(page, step, resolver)

    success, message = asyncio.run(_run())

    assert success is False
    assert "超时" in message
    assert "nomatch" in message


def test_complex_regex_pattern() -> None:
    handler = WaitUrlHandler()
    resolver = _make_resolver()
    step = _make_step(pattern=r"https?://[^/]+/auth/callback\?code=\w+", timeout=5000)
    page = _make_page("https://auth.example.com/auth/callback?code=abc123")

    async def _run():
        return await handler.execute(page, step, resolver)

    success, message = asyncio.run(_run())

    assert success is True
    assert message == ""


def test_another_invalid_regex_unmatched_bracket() -> None:
    handler = WaitUrlHandler()
    resolver = _make_resolver()
    step = _make_step(pattern="(group", timeout=1000)
    page = _make_page("http://example.com")

    async def _run():
        return await handler.execute(page, step, resolver)

    success, message = asyncio.run(_run())

    assert success is False
    assert "不是有效的正则表达式" in message
