"""Tests for SelectHandler required=True behavior."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

from src.task_executor import (
    SelectHandler,
    StepConfig,
    StepType,
    TaskConfig,
    VariableResolver,
)


def _make_resolver() -> VariableResolver:
    config = TaskConfig(name="test", url="http://example.com")
    return VariableResolver(config, {})


class TestSelectHandlerRequired:
    """Verify SelectHandler honors the required parameter."""

    def test_element_not_found_required_false_returns_ok(self):
        """required=False (default): element not found returns (True, '')."""
        async def _run():
            handler = SelectHandler()
            step = StepConfig(
                id="s1",
                type=StepType.SELECT,
                selector="#missing",
                value="option1",
                required=False,
            )
            mock_ctx = MagicMock()
            handler._resolve_frame = AsyncMock(return_value=mock_ctx)
            handler._find_element = AsyncMock(return_value=None)

            success, msg = await handler.execute(
                MagicMock(), step, _make_resolver()
            )

            assert success is True
            assert msg == ""

        asyncio.run(_run())

    def test_element_not_found_required_true_returns_fail(self):
        """required=True: element not found returns (False, error_msg)."""
        async def _run():
            handler = SelectHandler()
            step = StepConfig(
                id="s1",
                type=StepType.SELECT,
                selector="#missing",
                value="option1",
                required=True,
            )
            mock_ctx = MagicMock()
            handler._resolve_frame = AsyncMock(return_value=mock_ctx)
            handler._find_element = AsyncMock(return_value=None)

            success, msg = await handler.execute(
                MagicMock(), step, _make_resolver()
            )

            assert success is False
            assert "未找到" in msg

        asyncio.run(_run())

    def test_option_not_found_required_false_returns_ok(self):
        """required=False: element found but option not found returns (True, '')."""
        async def _run():
            handler = SelectHandler()
            step = StepConfig(
                id="s1",
                type=StepType.SELECT,
                selector="#sel",
                value="missing-option",
                required=False,
            )
            mock_element = MagicMock()
            handler._resolve_frame = AsyncMock(return_value=MagicMock())
            handler._find_element = AsyncMock(return_value=mock_element)
            handler._select_with_fallback = AsyncMock(return_value=False)

            success, msg = await handler.execute(
                MagicMock(), step, _make_resolver()
            )

            assert success is True
            assert msg == ""

        asyncio.run(_run())

    def test_option_not_found_required_true_returns_fail(self):
        """required=True: element found but option not found returns (False, error_msg)."""
        async def _run():
            handler = SelectHandler()
            step = StepConfig(
                id="s1",
                type=StepType.SELECT,
                selector="#sel",
                value="missing-option",
                required=True,
            )
            mock_element = MagicMock()
            handler._resolve_frame = AsyncMock(return_value=MagicMock())
            handler._find_element = AsyncMock(return_value=mock_element)
            handler._select_with_fallback = AsyncMock(return_value=False)

            success, msg = await handler.execute(
                MagicMock(), step, _make_resolver()
            )

            assert success is False
            assert "未匹配" in msg

        asyncio.run(_run())

    def test_required_default_is_false(self):
        """Default value of required must be False for backward compatibility."""
        step = StepConfig(id="s1", type=StepType.SELECT)
        assert step.required is False
