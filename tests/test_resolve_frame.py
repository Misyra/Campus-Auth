"""Tests for _resolve_frame FrameLocator type fix."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

from src.task_executor import StepConfig, StepHandler


def _make_step(frame: str | None = None) -> StepConfig:
    return StepConfig(id="s1", type="input", selector="#x", frame=frame)


class _TestHandler(StepHandler):
    @property
    def step_type(self) -> str:
        return "test"

    async def execute(self, page, step, resolver):
        return True, ""


def test_resolve_frame_returns_frame_not_frame_locator_for_css_selector():
    """CSS selector path returns a proper Frame via content_frame(), not FrameLocator."""
    async def _run():
        handler = _TestHandler()
        mock_frame = MagicMock()
        mock_frame.evaluate = AsyncMock(return_value="ok")
        mock_element = MagicMock()
        mock_element.content_frame = AsyncMock(return_value=mock_frame)
        mock_page = MagicMock()
        mock_page.frame = MagicMock(return_value=None)
        mock_page.query_selector = AsyncMock(return_value=mock_element)

        step = _make_step(frame="iframe#myframe")
        result = await handler._resolve_frame(mock_page, step)
        assert result is mock_frame
        assert hasattr(result, "evaluate")

    asyncio.run(_run())


def test_resolve_frame_fallback_to_page_when_content_frame_fails():
    """When content_frame() returns None, falls back to page gracefully."""
    async def _run():
        handler = _TestHandler()
        mock_element = MagicMock()
        mock_element.content_frame = AsyncMock(return_value=None)
        mock_page = MagicMock()
        mock_page.frame = MagicMock(return_value=None)
        mock_page.query_selector = AsyncMock(return_value=mock_element)

        step = _make_step(frame="iframe#broken")
        result = await handler._resolve_frame(mock_page, step)
        assert result is mock_page

    asyncio.run(_run())


def test_resolve_frame_fallback_to_page_when_query_selector_fails():
    """When query_selector raises, falls back to page gracefully."""
    async def _run():
        handler = _TestHandler()
        mock_page = MagicMock()
        mock_page.frame = MagicMock(return_value=None)
        mock_page.query_selector = AsyncMock(side_effect=Exception("selector error"))

        step = _make_step(frame="iframe#bad")
        result = await handler._resolve_frame(mock_page, step)
        assert result is mock_page

    asyncio.run(_run())


def test_resolve_frame_returns_page_when_no_frame_selector():
    """When step.frame is None, returns page directly."""
    async def _run():
        handler = _TestHandler()
        mock_page = MagicMock()
        step = _make_step(frame=None)
        result = await handler._resolve_frame(mock_page, step)
        assert result is mock_page

    asyncio.run(_run())


def test_resolve_frame_matches_by_name_first():
    """Prefers frame(name=) over CSS selector path."""
    async def _run():
        handler = _TestHandler()
        mock_named_frame = MagicMock()
        mock_page = MagicMock()
        mock_page.frame = MagicMock(
            side_effect=lambda **kw: mock_named_frame if "name" in kw else None
        )

        step = _make_step(frame="myframe")
        result = await handler._resolve_frame(mock_page, step)
        assert result is mock_named_frame
        mock_page.query_selector.assert_not_called()

    asyncio.run(_run())


def test_resolve_frame_matches_by_url_second():
    """Tries frame(url=) before CSS selector path."""
    async def _run():
        handler = _TestHandler()
        mock_url_frame = MagicMock()
        mock_page = MagicMock()
        mock_page.frame = MagicMock(
            side_effect=lambda **kw: mock_url_frame if "url" in kw else None
        )

        step = _make_step(frame="http://example.com/frame")
        result = await handler._resolve_frame(mock_page, step)
        assert result is mock_url_frame

    asyncio.run(_run())
