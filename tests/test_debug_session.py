"""Tests for DebugSession auto-timeout mechanism."""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestDebugTimeoutWatcher:
    """_debug_timeout_watcher 超时关闭浏览器"""

    @pytest.mark.asyncio
    async def test_timeout_closes_session(self):
        """超时后自动关闭浏览器会话"""
        session_mock = AsyncMock()
        gen = 42

        state: dict = {
            "session": session_mock,
            "task_id": "test-task",
            "executor": MagicMock(),
            "current_step": 0,
            "steps": [],
            "results": [],
            "screenshot_url": None,
            "running": True,
            "_last_activity": time.monotonic() - 10,
            "_debug_gen": gen,
            "_timer_task": None,
        }

        lock = asyncio.Lock()

        with (
            patch("backend.main._debug", state),
            patch("backend.main._debug_lock", lock),
        ):
            from backend.main import _debug_timeout_watcher

            watcher = asyncio.create_task(
                _debug_timeout_watcher(gen, timeout_seconds=0.3)
            )
            await asyncio.sleep(0.5)

            session_mock.close.assert_called_once()
            assert state["running"] is False
            assert state["session"] is None

            watcher.cancel()
            try:
                await watcher
            except asyncio.CancelledError:
                pass

    @pytest.mark.asyncio
    async def test_generation_prevents_wrong_session(self):
        """旧 generation 的定时器不关闭新会话"""
        session_mock = AsyncMock()

        state: dict = {
            "session": session_mock,
            "task_id": "test-task",
            "executor": MagicMock(),
            "current_step": 0,
            "steps": [],
            "results": [],
            "screenshot_url": None,
            "running": True,
            "_last_activity": time.monotonic() - 10,
            "_debug_gen": 2,
            "_timer_task": None,
        }

        lock = asyncio.Lock()

        with (
            patch("backend.main._debug", state),
            patch("backend.main._debug_lock", lock),
        ):
            from backend.main import _debug_timeout_watcher

            watcher = asyncio.create_task(
                _debug_timeout_watcher(1, timeout_seconds=0.1)
            )
            await asyncio.sleep(0.25)

            session_mock.close.assert_not_called()
            assert state["running"] is True

            watcher.cancel()
            try:
                await watcher
            except asyncio.CancelledError:
                pass

    @pytest.mark.asyncio
    async def test_stop_cancels_timer(self):
        """debug_stop() 取消定时器"""
        timer_task = asyncio.create_task(asyncio.sleep(9999))

        state: dict = {
            "session": AsyncMock(),
            "task_id": "test-task",
            "executor": MagicMock(),
            "current_step": 0,
            "steps": [],
            "results": [],
            "screenshot_url": None,
            "running": True,
            "_last_activity": time.monotonic(),
            "_debug_gen": 1,
            "_timer_task": timer_task,
        }

        with (
            patch("backend.main._debug", state),
            patch("backend.main._debug_lock", asyncio.Lock()),
            patch("backend.main._debug_exec_sem", asyncio.Semaphore(1)),
            patch("backend.main.TEMP_DIR", MagicMock()),
            patch("backend.main.api_logger", MagicMock()),
        ):
            from backend.main import debug_stop

            result = await debug_stop()

            assert timer_task.cancelled() or timer_task.done()
            assert result["running"] is False

    @pytest.mark.asyncio
    async def test_consecutive_start_stop_cleanup(self):
        """连续 start/stop 不残留定时器"""
        timer_task = asyncio.create_task(asyncio.sleep(9999))

        state: dict = {
            "session": AsyncMock(),
            "task_id": "test-task",
            "executor": MagicMock(),
            "current_step": 0,
            "steps": [],
            "results": [],
            "screenshot_url": None,
            "running": True,
            "_last_activity": time.monotonic(),
            "_debug_gen": 1,
            "_timer_task": timer_task,
        }

        with (
            patch("backend.main._debug", state),
            patch("backend.main._debug_lock", asyncio.Lock()),
            patch("backend.main._debug_exec_sem", asyncio.Semaphore(1)),
            patch("backend.main.TEMP_DIR", MagicMock()),
            patch("backend.main.api_logger", MagicMock()),
        ):
            from backend.main import debug_stop

            await debug_stop()

            state2: dict = {
                "session": None,
                "task_id": None,
                "executor": None,
                "current_step": 0,
                "steps": [],
                "results": [],
                "screenshot_url": None,
                "running": False,
                "_last_activity": 0.0,
                "_debug_gen": 0,
                "_timer_task": None,
            }
            with patch("backend.main._debug", state2):
                await debug_stop()

        assert timer_task.cancelled() or timer_task.done()

    @pytest.mark.asyncio
    async def test_status_does_not_reset_timer(self):
        """/api/debug/status 不重置计时器"""
        initial_activity = time.monotonic() - 100

        state: dict = {
            "session": MagicMock(),
            "task_id": "test",
            "executor": MagicMock(),
            "current_step": 0,
            "steps": [],
            "results": [],
            "screenshot_url": None,
            "running": True,
            "_last_activity": initial_activity,
            "_debug_gen": 1,
            "_timer_task": None,
        }

        with (
            patch("backend.main._debug", state),
            patch("backend.main._debug_lock", asyncio.Lock()),
        ):
            from backend.main import debug_status

            await debug_status()

            assert state["_last_activity"] == initial_activity

    @pytest.mark.asyncio
    async def test_next_after_timeout_returns_400(self):
        """超时后 /api/debug/next 返回 400"""
        from fastapi import HTTPException

        state: dict = {
            "session": None,
            "task_id": None,
            "executor": None,
            "current_step": 0,
            "steps": [],
            "results": [],
            "screenshot_url": None,
            "running": False,
            "_last_activity": 0.0,
            "_debug_gen": 0,
            "_timer_task": None,
        }

        with (
            patch("backend.main._debug", state),
            patch("backend.main._debug_lock", asyncio.Lock()),
            patch("backend.main._debug_exec_sem", asyncio.Semaphore(1)),
        ):
            from backend.main import debug_next

            with pytest.raises(HTTPException) as exc_info:
                await debug_next()
            assert exc_info.value.status_code == 400
            assert "没有活跃的调试会话" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_start_after_timeout_creates_new_session(self):
        """超时后可创建新会话"""
        state: dict = {
            "session": None,
            "task_id": None,
            "executor": None,
            "current_step": 0,
            "steps": [],
            "results": [],
            "screenshot_url": None,
            "running": False,
            "_last_activity": 0.0,
            "_debug_gen": 0,
            "_timer_task": None,
        }

        session_instance = AsyncMock()
        session_instance.page = AsyncMock()
        session_instance.page.screenshot = AsyncMock(return_value=None)

        with (
            patch("backend.main._debug", state),
            patch("backend.main._debug_lock", asyncio.Lock()),
            patch("backend.main.DebugSession", return_value=session_instance),
            patch("src.task_executor.TaskManager") as tm_mock,
            patch("src.task_executor.TaskExecutor") as te_mock,
            patch("backend.main.build_login_env_vars", return_value={}),
            patch("backend.main._take_debug_screenshot", AsyncMock(return_value=None)),
            patch("backend.main.service") as svc_mock,
            patch("backend.main.api_logger", MagicMock()),
        ):
            from backend.main import debug_start
            from fastapi import Request

            tm_instance = MagicMock()
            tm_mock.return_value = tm_instance
            task_mock = MagicMock()
            task_mock.steps = []
            task_mock.url = None
            tm_instance.load_task.return_value = task_mock

            te_mock.return_value = MagicMock()

            svc_mock.get_runtime_config.return_value = {}
            svc_mock.safe_mode = False

            mock_request = MagicMock(spec=Request)
            mock_request.json = AsyncMock(return_value={"task_id": "test-task"})

            result = await debug_start(mock_request)

            assert result["running"] is True
            assert result["task_id"] == "test-task"
            session_instance.start.assert_called_once()
