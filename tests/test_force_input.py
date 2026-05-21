"""Tests for InputHandler._force_input multi-candidate fallback."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

from src.task_executor import InputHandler


def _make_mock_locator(attached_ok: bool, evaluate_ok: bool):
    element = AsyncMock()
    element.wait_for = AsyncMock()
    if not attached_ok:
        element.wait_for.side_effect = Exception("element not attached")
    element.evaluate = AsyncMock()
    if not evaluate_ok:
        element.evaluate.side_effect = Exception("evaluate failed")

    locator = MagicMock()
    locator.first = element
    return locator, element


def _make_mock_ctx_with_map(selector_results: list[tuple[str, bool, bool]]):
    ctx = MagicMock()
    locator_mocks = {}
    for selector, attached_ok, evaluate_ok in selector_results:
        loc, el = _make_mock_locator(attached_ok, evaluate_ok)
        locator_mocks[selector] = loc

    def locator_side_effect(selector):
        for key, loc in locator_mocks.items():
            if key in selector or selector in key:
                return loc
        loc, _ = _make_mock_locator(False, False)
        return loc

    ctx.locator.side_effect = locator_side_effect
    return ctx


def test_force_input_tries_second_candidate_when_first_fails():
    async def _run():
        handler = InputHandler()
        ctx = _make_mock_ctx_with_map([
            ("#non-input-div", True, False),
            ("#real-input", True, True),
        ])
        return await handler._force_input(
            ctx, "#non-input-div, #real-input", "test_value", True, 5000
        )

    success, message = asyncio.run(_run())

    assert success is True
    assert message == ""


def test_force_input_returns_failure_when_all_candidates_fail():
    async def _run():
        handler = InputHandler()
        ctx = _make_mock_ctx_with_map([
            ("#bad-div", True, False),
            ("#also-bad", False, False),
        ])
        return await handler._force_input(
            ctx, "#bad-div, #also-bad", "test_value", True, 5000
        )

    success, message = asyncio.run(_run())

    assert success is False
    assert "未找到可用的输入元素" in message


def test_force_input_succeeds_on_first_candidate():
    async def _run():
        handler = InputHandler()
        ctx = _make_mock_ctx_with_map([
            ("#good-input", True, True),
            ("#backup-input", True, True),
        ])
        return await handler._force_input(
            ctx, "#good-input, #backup-input", "test_value", True, 5000
        )

    success, message = asyncio.run(_run())

    assert success is True
    assert message == ""
