"""Tests for DebugSession auto-timeout mechanism."""

from __future__ import annotations

import asyncio
import time
from collections import deque
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_session(**kwargs):
    """Build a DebugSession dataclass, filling defaults that match old _debug dict."""
    from backend.debug_session import DebugSession as DSession

    defaults = dict(
        session=None,
        task_id=None,
        executor=None,
        current_step=0,
        steps=None,
        results=None,
        screenshot_url=None,
        running=False,
        _last_activity=0.0,
        _timer_task=None,
    )
    defaults.update(kwargs)
    if defaults["steps"] is None:
        defaults["steps"] = []
    if defaults["results"] is None:
        defaults["results"] = deque(maxlen=1000)
    return DSession(**defaults)


class TestDebugTimeoutWatcher:
    """_debug_timeout_watcher 超时关闭浏览器"""

    @pytest.mark.asyncio
    async def test_timeout_closes_session(self):
        """超时后自动关闭浏览器会话"""
        session_mock = AsyncMock()
        gen = 42

        ds = _make_session(
            session=session_mock,
            task_id="test-task",
            executor=MagicMock(),
            running=True,
            _last_activity=time.monotonic() - 10,
        )

        lock = asyncio.Lock()

        with (
            patch("backend.main._debug_session", ds),
            patch("backend.main._debug_gen", gen),
            patch("backend.main._debug_lock", lock),
        ):
            from backend.main import _debug_timeout_watcher

            watcher = asyncio.create_task(
                _debug_timeout_watcher(gen, timeout_seconds=0.3)
            )
            await asyncio.sleep(0.5)

            session_mock.close.assert_called_once()
            assert ds.running is False
            assert ds.session is None

            watcher.cancel()
            try:
                await watcher
            except asyncio.CancelledError:
                pass

    @pytest.mark.asyncio
    async def test_generation_prevents_wrong_session(self):
        """旧 generation 的定时器不关闭新会话"""
        session_mock = AsyncMock()

        ds = _make_session(
            session=session_mock,
            task_id="test-task",
            executor=MagicMock(),
            running=True,
            _last_activity=time.monotonic() - 10,
        )

        lock = asyncio.Lock()

        with (
            patch("backend.main._debug_session", ds),
            patch("backend.main._debug_gen", 2),
            patch("backend.main._debug_lock", lock),
        ):
            from backend.main import _debug_timeout_watcher

            watcher = asyncio.create_task(
                _debug_timeout_watcher(1, timeout_seconds=0.1)
            )
            await asyncio.sleep(0.25)

            session_mock.close.assert_not_called()
            assert ds.running is True

            watcher.cancel()
            try:
                await watcher
            except asyncio.CancelledError:
                pass

    @pytest.mark.asyncio
    async def test_stop_cancels_timer(self):
        """debug_stop() 取消定时器"""
        timer_task = asyncio.create_task(asyncio.sleep(9999))

        ds = _make_session(
            session=AsyncMock(),
            task_id="test-task",
            executor=MagicMock(),
            running=True,
            _last_activity=time.monotonic(),
            _timer_task=timer_task,
        )

        with (
            patch("backend.main._debug_session", ds),
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

        ds = _make_session(
            session=AsyncMock(),
            task_id="test-task",
            executor=MagicMock(),
            running=True,
            _last_activity=time.monotonic(),
            _timer_task=timer_task,
        )

        with (
            patch("backend.main._debug_session", ds),
            patch("backend.main._debug_lock", asyncio.Lock()),
            patch("backend.main._debug_exec_sem", asyncio.Semaphore(1)),
            patch("backend.main.TEMP_DIR", MagicMock()),
            patch("backend.main.api_logger", MagicMock()),
        ):
            from backend.main import debug_stop

            await debug_stop()

            ds2 = _make_session()

            with patch("backend.main._debug_session", ds2):
                await debug_stop()

        assert timer_task.cancelled() or timer_task.done()

    @pytest.mark.asyncio
    async def test_status_does_not_reset_timer(self):
        """/api/debug/status 不重置计时器"""
        initial_activity = time.monotonic() - 100

        ds = _make_session(
            session=MagicMock(),
            task_id="test",
            executor=MagicMock(),
            running=True,
            _last_activity=initial_activity,
        )

        with (
            patch("backend.main._debug_session", ds),
            patch("backend.main._debug_lock", asyncio.Lock()),
        ):
            from backend.main import debug_status

            await debug_status()

            assert ds._last_activity == initial_activity

    @pytest.mark.asyncio
    async def test_next_after_timeout_returns_400(self):
        """超时后 /api/debug/next 返回 400"""
        from fastapi import HTTPException

        ds = _make_session()

        with (
            patch("backend.main._debug_session", ds),
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
        ds = _make_session()

        session_instance = AsyncMock()
        session_instance.page = AsyncMock()
        session_instance.page.screenshot = AsyncMock(return_value=None)

        # PlaywrightWorker 的 submit 返回值模拟
        worker_response = MagicMock()
        worker_response.success = True
        worker_response.data = {"screenshot_url": None}
        worker_mock = MagicMock()
        worker_mock.submit.return_value = worker_response

        with (
            patch("backend.main._debug_session", ds),
            patch("backend.main._debug_lock", asyncio.Lock()),
            patch("backend.main.DebugSession", return_value=session_instance),
            patch("src.task_executor.TaskManager") as tm_mock,
            patch("src.task_executor.TaskExecutor") as te_mock,
            patch("backend.main.build_login_env_vars", return_value={}),
            patch("backend.main.get_worker", return_value=worker_mock),
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


# ==================== DebugSession dataclass tests ====================


class TestDebugSessionDataclass:
    """DebugSession dataclass, factory & serializer."""

    def test_empty_session_defaults(self):
        """empty_debug_session() returns DebugSession with correct defaults."""
        from backend.debug_session import DebugSession, empty_debug_session

        s = empty_debug_session()
        assert isinstance(s, DebugSession)
        assert s.session is None
        assert s.task_id is None
        assert s.executor is None
        assert s.current_step == 0
        assert s.steps == []
        assert isinstance(s.results, type(deque(maxlen=1)))
        assert len(s.results) == 0
        assert s.screenshot_url is None
        assert s.running is False
        assert s._last_activity == 0.0
        assert s._timer_task is None

    def test_empty_session_creates_fresh_instance(self):
        """Each call to empty_debug_session() returns a distinct instance."""
        from backend.debug_session import empty_debug_session

        s1 = empty_debug_session()
        s2 = empty_debug_session()
        assert s1 is not s2
        s1.task_id = "foo"
        assert s2.task_id is None

    def test_results_is_deque_with_maxlen(self):
        """results field is a deque limited to 1000 entries."""
        from backend.debug_session import empty_debug_session

        s = empty_debug_session()
        for i in range(1010):
            s.results.append(i)
        assert len(s.results) == 1000

    def test_debug_to_response_structure(self):
        """debug_to_response() returns expected dict keys."""
        from backend.debug_session import debug_to_response, empty_debug_session

        s = empty_debug_session()
        r = debug_to_response(s)
        assert isinstance(r, dict)
        assert set(r.keys()) == {
            "running",
            "task_id",
            "current_step",
            "total_steps",
            "steps",
            "results",
            "screenshot_url",
        }

    def test_debug_to_response_values(self):
        """debug_to_response() reflects modified session state."""
        from backend.debug_session import debug_to_response, DebugSession

        s = DebugSession(
            task_id="my-task",
            current_step=3,
            steps=[{"index": 0}, {"index": 1}],
            results=deque(["ok", "ok"]),
            running=True,
        )
        r = debug_to_response(s)
        assert r["running"] is True
        assert r["task_id"] == "my-task"
        assert r["current_step"] == 3
        assert r["total_steps"] == 2
        assert r["steps"] == [{"index": 0}, {"index": 1}]
        assert r["results"] == ["ok", "ok"]
        assert r["screenshot_url"] is None

    def test_debug_to_response_results_is_list(self):
        """results in response is a plain list (not deque)."""
        from backend.debug_session import debug_to_response, empty_debug_session

        s = empty_debug_session()
        s.results.append({"step": 1})
        r = debug_to_response(s)
        assert isinstance(r["results"], list)

    def test_debug_to_response_strips_internal_fields(self):
        """Internal fields (executor, _last_activity, _timer_task) are excluded."""
        from backend.debug_session import debug_to_response, empty_debug_session

        s = empty_debug_session()
        r = debug_to_response(s)
        assert "executor" not in r
        assert "_last_activity" not in r
        assert "_timer_task" not in r

    def test_debug_gen_is_standalone(self):
        """_debug_gen is a module-level counter, not a dataclass field."""
        from backend.debug_session import DebugSession

        assert "_debug_gen" not in DebugSession.__dataclass_fields__
        assert not hasattr(DebugSession(), "_debug_gen")
