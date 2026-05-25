from __future__ import annotations

import asyncio
import threading
from unittest.mock import AsyncMock, MagicMock, patch

from src.utils.login import LoginAttemptHandler


def _mock_page_expect_dialog(page):
    """Mock page.expect_dialog as async context manager raising timeout."""
    from playwright.async_api import TimeoutError as PlaywrightTimeoutError

    async def _raise():
        raise PlaywrightTimeoutError("")

    dialog_info = AsyncMock()
    dialog_info.value = _raise()
    cm = AsyncMock()
    cm.__aenter__.return_value = dialog_info
    cm.__aexit__.return_value = None
    page.expect_dialog.return_value = cm


def _setup_for_reuse(handler, page_evaluate_side_effect=None):
    """Set up handler state for reuse_browser path to reach evaluate line."""
    # Mock task manager with a valid loadable task
    mock_task = MagicMock()
    mock_task.url = "http://example.com"
    mock_task.steps = []

    mock_tm = MagicMock()
    mock_tm.load_task.return_value = mock_task
    mock_tm.get_active_task.return_value = "default"
    handler._task_manager = mock_tm

    # Mock browser context for reuse
    # page.is_closed() is sync (no await), but page.evaluate() is async
    mock_page = MagicMock()
    mock_page.is_closed.return_value = False
    mock_page.evaluate = AsyncMock(side_effect=page_evaluate_side_effect)
    _mock_page_expect_dialog(mock_page)

    mock_browser = MagicMock()
    mock_browser.is_connected.return_value = True

    mock_ctx = MagicMock()
    mock_ctx.browser = mock_browser
    mock_ctx.page = mock_page
    handler._browser_ctx = mock_ctx

    return mock_page, mock_ctx


class TestBrowserHealthCheckEvaluate:

    def test_evaluate_passes_timeout(self):
        """Verify page.evaluate is called with timeout=5000."""
        handler = LoginAttemptHandler({"active_task": "default"})

        async def run():
            mock_page, _ = _setup_for_reuse(handler)

            mock_executor = AsyncMock()
            mock_executor.execute.return_value = (True, "success")

            with patch("src.utils.login.build_login_env_vars", return_value={}):
                with patch(
                    "src.task_executor.TaskExecutor", return_value=mock_executor
                ):
                    result = await handler.attempt_login(
                        skip_pause_check=True, reuse_browser=True
                    )

            mock_page.evaluate.assert_awaited_with("1", timeout=5000)
            assert result == (True, "success")

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(run())
        finally:
            loop.close()

    def test_evaluate_timeout_triggers_recreate(self):
        """Verify evaluate failure triggers close_browser and _create_new_browser."""
        handler = LoginAttemptHandler({"active_task": "default"})

        async def run():
            _setup_for_reuse(handler, page_evaluate_side_effect=Exception("timeout"))

            new_page = MagicMock()
            new_page.is_closed = MagicMock(return_value=False)
            new_page.evaluate = AsyncMock()
            _mock_page_expect_dialog(new_page)
            new_ctx = MagicMock()
            new_ctx.page = new_page

            mock_executor = AsyncMock()
            mock_executor.execute.return_value = (True, "success")

            with patch("src.utils.login.build_login_env_vars", return_value={}):
                with patch.object(
                    handler, "close_browser", new_callable=AsyncMock
                ) as mock_close:
                    with patch.object(
                        handler, "_create_new_browser", new_callable=AsyncMock
                    ) as mock_create:
                        mock_create.return_value = new_ctx
                        with patch(
                            "src.task_executor.TaskExecutor", return_value=mock_executor
                        ):
                            result = await handler.attempt_login(
                                skip_pause_check=True, reuse_browser=True
                            )

            # close_browser called in except handler (line 177) + by success path (line 212)
            mock_close.assert_called()
            mock_create.assert_called_once()
            assert result == (True, "success")

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(run())
        finally:
            loop.close()

    def test_cancel_event_skips_recreate(self):
        """Verify cancel_event being set during evaluate skips browser recreation."""
        cancel_event = threading.Event()
        handler = LoginAttemptHandler(
            {"active_task": "default"}, cancel_event=cancel_event
        )

        def set_cancel_then_raise(*args, **kwargs):
            cancel_event.set()
            raise Exception("browser disconnected")

        async def run():
            _setup_for_reuse(handler, page_evaluate_side_effect=set_cancel_then_raise)

            with patch("src.utils.login.build_login_env_vars", return_value={}):
                with patch.object(
                    handler, "close_browser", new_callable=AsyncMock
                ) as mock_close:
                    with patch.object(
                        handler, "_create_new_browser", new_callable=AsyncMock
                    ) as mock_create:
                        result = await handler.attempt_login(
                            skip_pause_check=True, reuse_browser=True
                        )

            mock_close.assert_called()
            mock_create.assert_not_called()
            assert result[0] is False
            assert result[1] == "任务执行异常: 登录已被取消"

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(run())
        finally:
            loop.close()
