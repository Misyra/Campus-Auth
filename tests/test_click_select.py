"""Tests for ClickSelectHandler frame context fix.

Verifies that _click_option() uses ctx (resolved frame context) instead of page,
so that click_select steps work correctly inside iframes/frames.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

from src.task_executor import (
    ClickSelectHandler,
    StepConfig,
    StepType,
    TaskConfig,
    VariableResolver,
)


def _make_step(
    selector: str = "",
    value: str = "mobile",
    option_selector: str = "",
    frame: str | None = None,
    timeout: int | None = None,
) -> StepConfig:
    extra = {}
    if option_selector:
        extra["option_selector"] = option_selector
    return StepConfig(
        id="s1",
        type=StepType.CLICK_SELECT,
        selector=selector,
        value=value,
        frame=frame,
        timeout=timeout,
        extra=extra,
    )


def _make_resolver() -> VariableResolver:
    config = TaskConfig(name="test", url="http://example.com")
    return VariableResolver(config, {})


class TestClickOptionUsesCtx:
    """Verify _click_option uses ctx parameter, not page."""

    def test_click_option_with_option_selector_uses_ctx_locator(self):
        """When option_selector is provided, _click_option must use ctx.locator()."""
        async def _run():
            handler = ClickSelectHandler()

            mock_ctx = MagicMock()
            mock_container_locator = MagicMock()
            mock_container_first = MagicMock()
            mock_option_locator = MagicMock()
            mock_option = MagicMock()
            mock_option.wait_for = AsyncMock()
            mock_option.click = AsyncMock()

            mock_option_locator.first = mock_option
            mock_container_first.get_by_text.return_value = mock_option_locator
            mock_container_locator.first = mock_container_first
            mock_ctx.locator.return_value = mock_container_locator

            result = await handler._click_option(
                mock_ctx, "mobile", ".dropdown-menu", 10000
            )

            assert result is True
            mock_ctx.locator.assert_called_once_with(".dropdown-menu")
            mock_container_first.get_by_text.assert_called_once_with(
                "mobile", exact=False
            )
            mock_option.wait_for.assert_called_once()
            mock_option.click.assert_called_once()

        asyncio.run(_run())

    def test_click_option_without_option_selector_uses_ctx_get_by_text(self):
        """When no option_selector, _click_option must use ctx.get_by_text()."""
        async def _run():
            handler = ClickSelectHandler()

            mock_ctx = MagicMock()
            mock_option_locator = MagicMock()
            mock_option = MagicMock()
            mock_option.wait_for = AsyncMock()
            mock_option.click = AsyncMock()

            mock_option_locator.first = mock_option
            mock_ctx.get_by_text.return_value = mock_option_locator

            result = await handler._click_option(mock_ctx, "unicom", "", 10000)

            assert result is True
            mock_ctx.get_by_text.assert_called_once_with("unicom", exact=False)
            mock_option.wait_for.assert_called_once()
            mock_option.click.assert_called_once()

        asyncio.run(_run())

    def test_click_option_returns_false_on_exception(self):
        """_click_option returns False when element not found or click fails."""
        async def _run():
            handler = ClickSelectHandler()

            mock_ctx = MagicMock()
            mock_option_locator = MagicMock()
            mock_option_locator.first.wait_for = AsyncMock(
                side_effect=Exception("timeout")
            )
            mock_ctx.get_by_text.return_value = mock_option_locator

            result = await handler._click_option(mock_ctx, "telecom", "", 10000)

            assert result is False

        asyncio.run(_run())

    def test_click_option_does_not_use_page(self):
        """Verify _click_option never calls methods on a separate page object."""
        async def _run():
            handler = ClickSelectHandler()

            mock_ctx = MagicMock()
            mock_option_locator = MagicMock()
            mock_option = MagicMock()
            mock_option.wait_for = AsyncMock()
            mock_option.click = AsyncMock()
            mock_option_locator.first = mock_option
            mock_ctx.get_by_text.return_value = mock_option_locator

            mock_page = MagicMock()

            result = await handler._click_option(mock_ctx, "mobile", "", 10000)

            assert result is True
            mock_page.locator.assert_not_called()
            mock_page.get_by_text.assert_not_called()
            mock_ctx.get_by_text.assert_called_once()

        asyncio.run(_run())


class TestClickSelectExecutePassesCtx:
    """Verify execute() passes ctx (not page) to _click_option()."""

    def test_execute_passes_ctx_to_click_option(self):
        """execute() must resolve frame and pass ctx to _click_option."""
        async def _run():
            handler = ClickSelectHandler()

            # Mock frame context (different from page)
            mock_ctx = MagicMock()
            mock_page = MagicMock()
            mock_page.wait_for_timeout = AsyncMock()

            # _resolve_frame returns mock_ctx (simulating frame match)
            handler._resolve_frame = AsyncMock(return_value=mock_ctx)

            # _find_element returns a mock trigger
            mock_trigger = MagicMock()
            mock_trigger.click = AsyncMock()
            handler._find_element = AsyncMock(return_value=mock_trigger)

            # _click_option should receive ctx, not page
            click_option_calls = []

            async def spy_click_option(ctx, text, option_selector, timeout):
                click_option_calls.append((ctx, text, option_selector, timeout))
                return True

            handler._click_option = spy_click_option

            step = _make_step(selector="#trigger", value="mobile")
            resolver = _make_resolver()

            success, msg = await handler.execute(mock_page, step, resolver)

            assert success is True
            assert len(click_option_calls) == 1
            ctx_arg = click_option_calls[0][0]
            assert ctx_arg is mock_ctx
            assert ctx_arg is not mock_page

        asyncio.run(_run())

    def test_execute_skips_when_selector_missing(self):
        """execute() returns early when selector is empty."""
        async def _run():
            handler = ClickSelectHandler()
            step = _make_step(selector="")
            resolver = _make_resolver()

            success, msg = await handler.execute(MagicMock(), step, resolver)

            assert success is False
            assert "selector" in msg.lower()

        asyncio.run(_run())

    def test_execute_skips_when_value_empty(self):
        """execute() returns early when value is empty."""
        async def _run():
            handler = ClickSelectHandler()
            step = _make_step(selector="#trigger", value="")
            resolver = _make_resolver()

            success, msg = await handler.execute(MagicMock(), step, resolver)

            assert success is True

        asyncio.run(_run())

    def test_execute_skips_when_trigger_not_found(self):
        """execute() skips click_option when trigger element not found."""
        async def _run():
            handler = ClickSelectHandler()
            mock_page = MagicMock()
            mock_ctx = MagicMock()

            handler._resolve_frame = AsyncMock(return_value=mock_ctx)
            handler._find_element = AsyncMock(return_value=None)

            click_option_called = False
            async def spy_click_option(*args):
                nonlocal click_option_called
                click_option_called = True
                return True
            handler._click_option = spy_click_option

            step = _make_step(selector="#nonexistent", value="mobile")
            resolver = _make_resolver()

            success, msg = await handler.execute(mock_page, step, resolver)

            assert success is True
            assert not click_option_called

        asyncio.run(_run())
