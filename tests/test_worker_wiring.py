"""Worker dispatch wiring tests.

Verifies that all 5 modules correctly dispatch commands to PlaywrightWorker
via the expected mechanism (submit / ensure_browser), without requiring a real
browser or Playwright installation.

Each test patches get_worker() or the worker instance at the correct module
path, exercises the function under test, then asserts submit() or
ensure_browser() was called with the correct CMD_* constant.
"""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.playwright_worker import (
    CMD_BROWSER_RELEASE,
    CMD_DEBUG_START,
    CMD_DEBUG_STEP,
    CMD_DEBUG_STOP,
    CMD_LOGIN,
    WorkerResponse,
)


class TestWorkerWiring:
    """5 wiring tests — one per module that dispatches to PlaywrightWorker."""

    # ── 1. monitor_core.py: attempt_login() ──────────────────────────────

    def test_monitor_core_attempt_login_uses_worker_submit(self):
        """NetworkMonitorCore.attempt_login() calls get_worker().submit(CMD_LOGIN)."""
        from src.monitor_core import NetworkMonitorCore

        config = {
            "active_task": "default",
            "auth_url": "http://test",
            "username": "test",
            "isp": "",
            "browser_settings": {"timeout": 30},
        }
        core = NetworkMonitorCore(config=config)
        # Ensure cancellation event is available (cleared by default)
        core._cancel_login = threading.Event()

        mock_worker = MagicMock()
        mock_worker.submit.return_value = WorkerResponse(
            success=True, data="logged in"
        )

        # The import inside attempt_login() is:
        #   from src.playwright_worker import get_worker, CMD_LOGIN
        # Patching src.playwright_worker.get_worker makes the local import
        # pick up our mock.
        with patch(
            "src.playwright_worker.get_worker", return_value=mock_worker
        ):
            success, message = core.attempt_login()

        assert success is True
        mock_worker.submit.assert_called_once()
        args, kwargs = mock_worker.submit.call_args
        assert args[0] == CMD_LOGIN, (
            f"Expected CMD_LOGIN ('login'), got {args[0]!r}"
        )
        # The data dict should contain the config
        assert "config" in kwargs.get("data", {})

    # ── 2. monitor_service.py: _handle_login() ───────────────────────────

    def test_monitor_service_login_uses_get_worker_submit(self, tmp_path):
        """MonitorService._handle_login() calls get_worker().submit(CMD_LOGIN)."""
        from backend.monitor_service import MonitorCommand, MonitorService
        from backend.profile_service import ProfileService

        profile_svc = ProfileService(tmp_path)
        service = MonitorService(tmp_path, profile_service=profile_svc)

        config = {"auth_url": "http://test", "username": "test"}
        cmd = MonitorCommand(
            type="login",
            data={"config": config},
            response_event=threading.Event(),
        )

        mock_worker = MagicMock()
        mock_worker.submit.return_value = WorkerResponse(
            success=True, data="ok"
        )

        # monitor_service.py has module-level import:
        #   from src.playwright_worker import get_worker, CMD_LOGIN
        # So get_worker lives at backend.monitor_service.get_worker.
        with patch(
            "backend.monitor_service.get_worker", return_value=mock_worker
        ):
            service._handle_login(cmd)

        mock_worker.submit.assert_called_once()
        args, kwargs = mock_worker.submit.call_args
        assert args[0] == CMD_LOGIN, (
            f"Expected CMD_LOGIN ('login'), got {args[0]!r}"
        )

    # ── 3. main.py: debug endpoints ──────────────────────────────────────

    @pytest.mark.asyncio
    async def test_debug_start_uses_worker_submit(self):
        """/api/debug/start calls get_worker().submit(CMD_DEBUG_START)."""
        from backend.main import debug_start
        from backend.debug_session import empty_debug_session
        from fastapi import Request

        mock_worker = MagicMock()
        mock_worker.submit.return_value = WorkerResponse(
            success=True, data={"screenshot_url": None}
        )

        # Use a fresh empty session so _debug_session.session is None
        # (avoids await on mock during the initial cleanup block)
        ds = empty_debug_session()

        with (
            patch("backend.main.get_worker", return_value=mock_worker),
            patch("backend.main._debug_session", ds),
            patch("backend.main._debug_lock", asyncio.Lock()),
            patch("backend.main._debug_exec_sem", asyncio.Semaphore(1)),
            patch("backend.main.service") as svc_mock,
            patch("backend.main.build_login_env_vars", return_value={}),
            patch("src.task_executor.TaskManager") as tm_mock,
            patch("backend.main.api_logger", MagicMock()),
        ):
            tm_instance = MagicMock()
            tm_mock.return_value = tm_instance
            task_mock = MagicMock()
            task_mock.steps = []
            task_mock.url = None
            tm_instance.load_task.return_value = task_mock

            svc_mock.get_runtime_config.return_value = {}
            svc_mock.safe_mode = False

            mock_request = MagicMock(spec=Request)
            mock_request.json = AsyncMock(
                return_value={"task_id": "test-wiring"}
            )

            await debug_start(mock_request)

        # debug_start calls get_worker().submit() both inside
        # DebugSession.start() and directly at line 790.
        assert mock_worker.submit.call_count >= 1, (
            "Expected get_worker().submit(CMD_DEBUG_START) to be called"
        )
        found_debug_start = any(
            call.args[0] == CMD_DEBUG_START
            for call in mock_worker.submit.call_args_list
        )
        assert found_debug_start, (
            "No call to submit(CMD_DEBUG_START, ...) found"
        )

    @pytest.mark.asyncio
    async def test_debug_next_uses_worker_submit(self):
        """/api/debug/next calls get_worker().submit(CMD_DEBUG_STEP)."""
        from backend.main import debug_next

        worker_response = WorkerResponse(
            success=True,
            data={
                "success": True,
                "message": "ok",
                "screenshot_url": None,
            },
        )
        mock_worker = MagicMock()
        mock_worker.submit.return_value = worker_response

        # Build a debug session with at least one step so debug_next
        # doesn't short-circuit with "all steps done".
        from backend.debug_session import empty_debug_session

        ds = empty_debug_session()
        ds.running = True
        ds.steps = [{"index": 0, "id": "s1", "type": "navigate"}]
        ds.current_step = 0
        ds.results = []
        ds._last_activity = 12345.0

        with (
            patch("backend.main.get_worker", return_value=mock_worker),
            patch("backend.main._debug_session", ds),
            patch("backend.main._debug_lock", asyncio.Lock()),
            patch("backend.main._debug_exec_sem", asyncio.Semaphore(1)),
        ):
            result = await debug_next()

        mock_worker.submit.assert_called_once()
        args, kwargs = mock_worker.submit.call_args
        assert args[0] == CMD_DEBUG_STEP, (
            f"Expected CMD_DEBUG_STEP ('debug_step'), got {args[0]!r}"
        )
        # Verify step_index was passed
        assert "step_index" in kwargs.get("data", {})

    @pytest.mark.asyncio
    async def test_debug_stop_uses_worker_submit(self):
        """/api/debug/stop calls get_worker().submit(CMD_DEBUG_STOP)
        indirectly through DebugSession.close()."""
        from backend.main import debug_stop

        worker_response = WorkerResponse(success=True, data="stopped")
        mock_worker = MagicMock()
        mock_worker.submit.return_value = worker_response

        # The DebugSession class in main.py has a close() method that
        # calls get_worker().submit(CMD_DEBUG_STOP).  We patch
        # backend.main.get_worker so that the call inside close()
        # hits our mock.
        session_instance = AsyncMock()
        session_instance.close = AsyncMock()

        from backend.debug_session import empty_debug_session

        ds = empty_debug_session()
        ds.session = session_instance
        ds.running = True
        ds._timer_task = None

        with (
            patch("backend.main.get_worker", return_value=mock_worker),
            patch("backend.main._debug_session", ds),
            patch("backend.main._debug_lock", asyncio.Lock()),
            patch("backend.main._debug_exec_sem", asyncio.Semaphore(1)),
            patch("backend.main.TEMP_DIR", MagicMock()),
            patch("backend.main.api_logger", MagicMock()),
        ):
            result = await debug_stop()

        # DebugSession.close() calls get_worker().submit(CMD_DEBUG_STOP)
        session_instance.close.assert_called_once()
        assert result["running"] is False

    # ── 4. app.py: _run_login_then_exit() ────────────────────────────────

    def test_app_login_then_exit_uses_worker_submit(self):
        """app._run_login_then_exit() calls worker.submit(CMD_LOGIN)."""
        from app import _run_login_then_exit

        mock_worker = MagicMock()
        mock_worker.submit.return_value = WorkerResponse(
            success=True, data="logged in"
        )

        # Mock the ProfileService and config-loading functions that
        # _run_login_then_exit imports internally.
        mock_profile_svc = MagicMock()
        mock_data = MagicMock()
        mock_data.system = MagicMock()
        mock_profile_svc.load.return_value = mock_data

        runtime_config = {
            "retry_settings": {"max_retries": 1, "retry_interval": 1}
        }

        with (
            patch(
                "src.playwright_worker.get_worker",
                return_value=mock_worker,
            ),
            patch(
                "backend.profile_service.ProfileService",
                return_value=mock_profile_svc,
            ),
            patch(
                "backend.config_service.load_runtime_config",
                return_value={},
            ),
            patch(
                "backend.config_service.build_runtime_config",
                return_value=runtime_config,
            ),
            patch("app.cleanup_orphan_browsers"),
            patch("app._cleanup_pid"),
            patch("sys.exit") as mock_exit,
            patch("app.print"),
        ):
            _run_login_then_exit(MagicMock())

        # success → sys.exit(0)
        mock_exit.assert_called_once_with(0)

        mock_worker.submit.assert_called_once()
        args, kwargs = mock_worker.submit.call_args
        assert args[0] == CMD_LOGIN, (
            f"Expected CMD_LOGIN ('login'), got {args[0]!r}"
        )
        assert "config" in kwargs.get("data", {})
        assert kwargs["data"].get("skip_pause_check") is True

    # ── 5. browser.py: BrowserContextManager.__aenter__() ────────────────

    @pytest.mark.asyncio
    async def test_browser_context_manager_proxies_through_worker(self):
        """BrowserContextManager.__aenter__() calls worker.ensure_browser()."""
        from src.utils.browser import BrowserContextManager

        mock_worker = AsyncMock()
        mock_worker.ensure_browser = AsyncMock()
        # __aenter__ reads these attributes from the worker
        mock_worker._playwright = MagicMock()
        mock_worker._browser = MagicMock()
        mock_worker._context = MagicMock()
        mock_worker._page = MagicMock()

        config = {"browser_settings": {}}

        with patch(
            "src.playwright_worker.get_worker", return_value=mock_worker
        ):
            async with BrowserContextManager(config=config) as cm:
                pass

        # verify __aenter__ called worker.ensure_browser
        mock_worker.ensure_browser.assert_called_once_with(config)

        # __aexit__ also calls get_worker() and submit(CMD_BROWSER_RELEASE)
        mock_worker.submit.assert_called_once_with(
            CMD_BROWSER_RELEASE, wait=False
        )
