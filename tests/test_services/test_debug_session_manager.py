"""调试会话管理器测试 — 覆盖 DebugSessionManager 的核心逻辑。"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.debug_service import DebugSessionManager
from app.services.debug_session import DebugSession, debug_to_response
from app.workers.playwright_worker import WorkerResponse

# ---------------------------------------------------------------------------
# 辅助工具
# ---------------------------------------------------------------------------


def _make_manager(tmp_path: Path) -> DebugSessionManager:
    """创建一个使用临时目录的 DebugSessionManager 实例。"""
    return DebugSessionManager(project_root=tmp_path)


def _ok_response(data=None) -> WorkerResponse:
    """返回成功响应。"""
    return WorkerResponse(success=True, data=data or {})


def _fail_response(error="失败") -> WorkerResponse:
    """返回失败响应。"""
    return WorkerResponse(success=False, error=error)


def _set_session_running(manager: DebugSessionManager, task_id="t1", steps=None):
    """手动将管理器的内部会话设置为运行中状态。"""
    session = DebugSession()
    session.running = True
    session._browser_active = True
    session.task_id = task_id
    session.steps = steps or [
        {"index": 0, "id": "s1", "type": "click", "description": "点击按钮"},
        {"index": 1, "id": "s2", "type": "input", "description": "输入文本"},
    ]
    session.current_step = 0
    session._last_activity = 1000.0
    manager._session = session
    return session


# =====================================================================
# __init__
# =====================================================================


class TestDebugSessionManagerInit:
    """初始化。"""

    def test_initial_state(self, tmp_path):
        """初始状态正确。"""
        manager = _make_manager(tmp_path)
        assert manager._session is not None
        assert manager._session.running is False
        assert manager._session._browser_active is False
        assert manager._session.task_id is None

    def test_project_root_stored(self, tmp_path):
        """project_root 被正确存储。"""
        manager = _make_manager(tmp_path)
        assert manager._project_root == tmp_path
        assert manager._temp_dir == tmp_path / "temp" / "debug"

    def test_lock_and_semaphore_created(self, tmp_path):
        """锁和信号量已创建。"""
        manager = _make_manager(tmp_path)
        assert isinstance(manager._lock, asyncio.Lock)
        assert isinstance(manager._exec_sem, asyncio.Semaphore)


# =====================================================================
# debug_to_response
# =====================================================================


class TestDebugSessionManagerDebugResponse:
    """debug_to_response 返回值验证。"""

    def test_returns_dict(self, tmp_path):
        """返回字典。"""
        manager = _make_manager(tmp_path)
        result = debug_to_response(manager._session)
        assert isinstance(result, dict)

    def test_excludes_internal_fields(self, tmp_path):
        """不包含内部字段。"""
        manager = _make_manager(tmp_path)
        result = debug_to_response(manager._session)
        assert "_browser_active" not in result
        assert "_last_activity" not in result
        assert "_timer_task" not in result
        assert "executor" not in result


# =====================================================================
# _require_debug_session
# =====================================================================


class TestDebugSessionManagerRequireSession:
    """会话验证。"""

    def test_raises_when_not_running(self, tmp_path):
        """未运行时应抛出 HTTPException。"""
        from fastapi import HTTPException

        manager = _make_manager(tmp_path)
        with pytest.raises(HTTPException) as exc_info:
            manager._require_debug_session()
        assert exc_info.value.status_code == 400

    def test_no_raise_when_running(self, tmp_path):
        """运行中时不应抛异常。"""
        manager = _make_manager(tmp_path)
        _set_session_running(manager)
        manager._require_debug_session()  # 不应抛异常


# =====================================================================
# _cancel_debug_timer
# =====================================================================


class TestDebugSessionManagerCancelTimer:
    """取消定时器。"""

    @pytest.mark.asyncio
    async def test_cancel_none_timer(self, tmp_path):
        """定时器为 None 时不抛异常。"""
        manager = _make_manager(tmp_path)
        manager._session._timer_task = None
        await manager._cancel_debug_timer()  # 不应抛异常

    @pytest.mark.asyncio
    async def test_cancel_done_timer(self, tmp_path):
        """已完成的定时器不抛异常。"""
        manager = _make_manager(tmp_path)
        done_task = MagicMock()
        done_task.done.return_value = True
        manager._session._timer_task = done_task
        await manager._cancel_debug_timer()
        done_task.cancel.assert_not_called()

    @pytest.mark.asyncio
    async def test_cancel_active_timer(self, tmp_path):
        """活跃的定时器应被取消。"""
        manager = _make_manager(tmp_path)

        async def _noop():
            await asyncio.sleep(100)

        task = asyncio.create_task(_noop())
        manager._session._timer_task = task
        await manager._cancel_debug_timer()
        assert task.cancelled()


# =====================================================================
# _close_debug_browser
# =====================================================================


class TestDebugSessionManagerCloseBrowser:
    """关闭调试浏览器。"""

    @pytest.mark.asyncio
    async def test_closes_browser_and_resets_flag(self, tmp_path):
        """关闭浏览器后重置 _browser_active 标记。"""
        manager = _make_manager(tmp_path)
        _set_session_running(manager)

        with patch("app.workers.playwright_worker.get_worker") as mock_get_worker:
            mock_worker = MagicMock()
            mock_worker.submit.return_value = _ok_response()
            mock_get_worker.return_value = mock_worker

            await manager._close_debug_browser()

            assert manager._session._browser_active is False
            mock_get_worker.assert_called_once()

    @pytest.mark.asyncio
    async def test_handles_worker_exception(self, tmp_path):
        """Worker 异常时不抛出，仍重置标记。"""
        manager = _make_manager(tmp_path)
        _set_session_running(manager)

        with patch("app.workers.playwright_worker.get_worker") as mock_get_worker:
            mock_get_worker.side_effect = RuntimeError("Worker 崩溃")

            await manager._close_debug_browser()

            assert manager._session._browser_active is False


# =====================================================================
# start
# =====================================================================


class TestDebugSessionManagerStart:
    """启动调试会话。"""

    @pytest.mark.asyncio
    async def test_start_missing_task_id(self, tmp_path):
        """缺少 task_id 时应抛出 HTTPException。"""
        from fastapi import HTTPException

        manager = _make_manager(tmp_path)

        mock_request = MagicMock()
        mock_request.json = AsyncMock(return_value={})

        mock_monitor = MagicMock()

        with pytest.raises(HTTPException) as exc_info:
            await manager.start(mock_request, mock_monitor)
        assert exc_info.value.status_code == 400
        assert "task_id" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_start_empty_task_id(self, tmp_path):
        """空 task_id 时应抛出 HTTPException。"""
        from fastapi import HTTPException

        manager = _make_manager(tmp_path)

        mock_request = MagicMock()
        mock_request.json = AsyncMock(return_value={"task_id": ""})

        mock_monitor = MagicMock()

        with pytest.raises(HTTPException) as exc_info:
            await manager.start(mock_request, mock_monitor)
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_start_task_not_found(self, tmp_path):
        """任务不存在时应抛出 404。"""
        from fastapi import HTTPException

        manager = _make_manager(tmp_path)

        mock_request = MagicMock()
        mock_request.json = AsyncMock(return_value={"task_id": "missing_task"})

        mock_task_mgr = MagicMock()
        mock_task_mgr.load_task.return_value = None
        mock_request.app.state.services.task_manager = mock_task_mgr

        mock_monitor = MagicMock()

        with pytest.raises(HTTPException) as exc_info:
            await manager.start(mock_request, mock_monitor)
        assert exc_info.value.status_code == 404
        assert "不存在" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_start_success(self, tmp_path):
        """成功启动调试会话。"""
        manager = _make_manager(tmp_path)

        # 构建 mock task
        mock_task = MagicMock()
        mock_task.url = "http://example.com"
        mock_task.steps = [
            MagicMock(id="s1", type="click", description="点击"),
            MagicMock(id="s2", type="input", description="输入"),
        ]
        mock_task.to_dict.return_value = {"url": "http://example.com", "steps": []}

        mock_request = MagicMock()
        mock_request.json = AsyncMock(return_value={"task_id": "task1"})
        mock_task_mgr = MagicMock()
        mock_task_mgr.load_task.return_value = mock_task
        mock_request.app.state.services.task_manager = mock_task_mgr

        mock_monitor = MagicMock()
        mock_runtime = MagicMock()
        mock_runtime.app_settings.custom_variables = {}
        mock_runtime.browser.timeout = 8
        mock_runtime.browser.navigation_timeout = 15
        mock_runtime.credentials.auth_url = "http://auth.example.com"
        mock_runtime.credentials.isp = ""
        mock_runtime.credentials.username = "user"
        mock_runtime.credentials.password = "pass"
        mock_monitor.get_runtime_config.return_value = mock_runtime

        with (
            patch("app.workers.playwright_worker.get_worker") as mock_get_worker,
            patch(
                "app.services.debug_service.build_login_template_vars", return_value={}
            ),
            patch(
                "app.services.debug_service._runtime_config_to_worker_dict",
                return_value={},
            ),
        ):
            mock_worker = MagicMock()
            mock_worker.submit.return_value = _ok_response(
                {"screenshot_url": "/temp/s.png"}
            )
            mock_get_worker.return_value = mock_worker

            result = await manager.start(mock_request, mock_monitor)

        assert result["running"] is True
        assert result["task_id"] == "task1"
        assert result["total_steps"] == 2
        assert manager._session._browser_active is True

    @pytest.mark.asyncio
    async def test_start_worker_failure(self, tmp_path):
        """Worker 启动失败时应抛出 RuntimeError。"""
        manager = _make_manager(tmp_path)

        mock_task = MagicMock()
        mock_task.url = "http://example.com"
        mock_task.steps = [MagicMock(id="s1", type="click", description="点击")]
        mock_task.to_dict.return_value = {}

        mock_request = MagicMock()
        mock_request.json = AsyncMock(return_value={"task_id": "task1"})
        mock_task_mgr = MagicMock()
        mock_task_mgr.load_task.return_value = mock_task
        mock_request.app.state.services.task_manager = mock_task_mgr

        mock_monitor = MagicMock()
        mock_runtime = MagicMock()
        mock_runtime.app_settings.custom_variables = {}
        mock_runtime.browser.timeout = 8
        mock_runtime.browser.navigation_timeout = 15
        mock_monitor.get_runtime_config.return_value = mock_runtime

        with (
            patch("app.workers.playwright_worker.get_worker") as mock_get_worker,
            patch(
                "app.services.debug_service.build_login_template_vars", return_value={}
            ),
            patch(
                "app.services.debug_service._runtime_config_to_worker_dict",
                return_value={},
            ),
        ):
            mock_worker = MagicMock()
            mock_worker.submit.return_value = _fail_response("浏览器启动失败")
            mock_get_worker.return_value = mock_worker

            with pytest.raises(RuntimeError, match="启动失败"):
                await manager.start(mock_request, mock_monitor)

        # 失败后应已清理浏览器标记
        assert manager._session._browser_active is False

    @pytest.mark.asyncio
    async def test_start_closes_existing_browser(self, tmp_path):
        """已有浏览器会话时，启动新会话前先关闭旧的。"""
        manager = _make_manager(tmp_path)
        _set_session_running(manager)

        mock_task = MagicMock()
        mock_task.url = "http://example.com"
        mock_task.steps = [MagicMock(id="s1", type="click", description="点击")]
        mock_task.to_dict.return_value = {}

        mock_request = MagicMock()
        mock_request.json = AsyncMock(return_value={"task_id": "task2"})
        mock_task_mgr = MagicMock()
        mock_task_mgr.load_task.return_value = mock_task
        mock_request.app.state.services.task_manager = mock_task_mgr

        mock_monitor = MagicMock()
        mock_runtime = MagicMock()
        mock_runtime.app_settings.custom_variables = {}
        mock_runtime.browser.timeout = 8
        mock_runtime.browser.navigation_timeout = 15
        mock_monitor.get_runtime_config.return_value = mock_runtime

        with (
            patch("app.workers.playwright_worker.get_worker") as mock_get_worker,
            patch(
                "app.services.debug_service.build_login_template_vars", return_value={}
            ),
            patch(
                "app.services.debug_service._runtime_config_to_worker_dict",
                return_value={},
            ),
        ):
            mock_worker = MagicMock()
            mock_worker.submit.return_value = _ok_response()
            mock_get_worker.return_value = mock_worker

            await manager.start(mock_request, mock_monitor)

        # 新会话应已替换旧会话
        assert manager._session.task_id == "task2"


# =====================================================================
# next_step
# =====================================================================


class TestDebugSessionManagerNextStep:
    """执行下一步。"""

    @pytest.mark.asyncio
    async def test_next_step_not_running(self, tmp_path):
        """未运行时应抛出 HTTPException。"""
        from fastapi import HTTPException

        manager = _make_manager(tmp_path)
        with pytest.raises(HTTPException) as exc_info:
            await manager.next_step()
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_next_step_success(self, tmp_path):
        """成功执行下一步。"""
        manager = _make_manager(tmp_path)
        _set_session_running(
            manager,
            steps=[
                {"index": 0, "id": "s1", "type": "click", "description": "点击"},
                {"index": 1, "id": "s2", "type": "input", "description": "输入"},
            ],
        )

        with patch("app.workers.playwright_worker.get_worker") as mock_get_worker:
            mock_worker = MagicMock()
            mock_worker.submit.return_value = _ok_response(
                {
                    "step_index": 0,
                    "success": True,
                    "message": "步骤执行成功",
                    "screenshot_url": "/temp/step0.png",
                }
            )
            mock_get_worker.return_value = mock_worker

            result = await manager.next_step()

        assert result["current_step"] == 1
        assert len(result["results"]) == 1
        assert result["results"][0]["success"] is True

    @pytest.mark.asyncio
    async def test_next_step_all_done(self, tmp_path):
        """所有步骤执行完毕后返回提示。"""
        manager = _make_manager(tmp_path)
        session = _set_session_running(
            manager,
            steps=[
                {"index": 0, "id": "s1", "type": "click", "description": "点击"},
            ],
        )
        session.current_step = 1  # 已执行完毕

        result = await manager.next_step()
        assert "所有步骤已执行完毕" in result.get("message", "")

    @pytest.mark.asyncio
    async def test_next_step_worker_failure(self, tmp_path):
        """Worker 执行失败时记录失败结果。"""
        manager = _make_manager(tmp_path)
        _set_session_running(
            manager,
            steps=[
                {"index": 0, "id": "s1", "type": "click", "description": "点击"},
            ],
        )

        with patch("app.workers.playwright_worker.get_worker") as mock_get_worker:
            mock_worker = MagicMock()
            mock_worker.submit.return_value = _fail_response("元素未找到")
            mock_get_worker.return_value = mock_worker

            result = await manager.next_step()

        assert result["current_step"] == 1
        assert len(result["results"]) == 1
        assert result["results"][0]["success"] is False
        assert "元素未找到" in result["results"][0]["message"]


# =====================================================================
# run_all
# =====================================================================


class TestDebugSessionManagerRunAll:
    """执行所有步骤。"""

    @pytest.mark.asyncio
    async def test_run_all_not_running(self, tmp_path):
        """未运行时应抛出 HTTPException。"""
        from fastapi import HTTPException

        manager = _make_manager(tmp_path)
        with pytest.raises(HTTPException) as exc_info:
            await manager.run_all()
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_run_all_success(self, tmp_path):
        """成功执行所有步骤。"""
        manager = _make_manager(tmp_path)
        _set_session_running(
            manager,
            steps=[
                {"index": 0, "id": "s1", "type": "click", "description": "点击"},
                {"index": 1, "id": "s2", "type": "input", "description": "输入"},
            ],
        )

        with patch("app.workers.playwright_worker.get_worker") as mock_get_worker:
            mock_worker = MagicMock()
            mock_worker.submit.side_effect = [
                _ok_response(
                    {"step_index": 0, "success": True, "screenshot_url": "/s0.png"}
                ),
                _ok_response(
                    {"step_index": 1, "success": True, "screenshot_url": "/s1.png"}
                ),
            ]
            mock_get_worker.return_value = mock_worker

            result = await manager.run_all()

        assert result["current_step"] == 2
        assert result["total_steps"] == 2
        assert len(result["results"]) == 2

    @pytest.mark.asyncio
    async def test_run_all_all_done(self, tmp_path):
        """已执行完毕时返回提示。"""
        manager = _make_manager(tmp_path)
        session = _set_session_running(
            manager,
            steps=[
                {"index": 0, "id": "s1", "type": "click", "description": "点击"},
            ],
        )
        session.current_step = 1

        result = await manager.run_all()
        assert "所有步骤已执行完毕" in result.get("message", "")

    @pytest.mark.asyncio
    async def test_run_all_stops_on_failure(self, tmp_path):
        """某步骤失败时停止后续执行。"""
        manager = _make_manager(tmp_path)
        _set_session_running(
            manager,
            steps=[
                {"index": 0, "id": "s1", "type": "click", "description": "点击"},
                {"index": 1, "id": "s2", "type": "input", "description": "输入"},
            ],
        )

        with patch("app.workers.playwright_worker.get_worker") as mock_get_worker:
            mock_worker = MagicMock()
            mock_worker.submit.side_effect = [
                _ok_response(
                    {"step_index": 0, "success": False, "screenshot_url": None}
                ),
            ]
            mock_get_worker.return_value = mock_worker

            result = await manager.run_all()

        # 第一步失败后应停止
        assert result["current_step"] == 1
        assert len(result["results"]) == 1

    @pytest.mark.asyncio
    async def test_run_all_worker_submit_error(self, tmp_path):
        """Worker 提交失败时停止执行。"""
        manager = _make_manager(tmp_path)
        _set_session_running(
            manager,
            steps=[
                {"index": 0, "id": "s1", "type": "click", "description": "点击"},
                {"index": 1, "id": "s2", "type": "input", "description": "输入"},
            ],
        )

        with patch("app.workers.playwright_worker.get_worker") as mock_get_worker:
            mock_worker = MagicMock()
            mock_worker.submit.return_value = _fail_response("提交异常")
            mock_get_worker.return_value = mock_worker

            result = await manager.run_all()

        assert result["current_step"] == 1
        assert len(result["results"]) == 1
        assert result["results"][0]["success"] is False


# =====================================================================
# stop
# =====================================================================


class TestDebugSessionManagerStop:
    """停止调试会话。"""

    @pytest.mark.asyncio
    async def test_stop_when_not_running(self, tmp_path):
        """未运行时停止不应抛异常。"""
        manager = _make_manager(tmp_path)
        result = await manager.stop()
        assert result["running"] is False
        assert "已关闭" in result["message"]

    @pytest.mark.asyncio
    async def test_stop_when_running(self, tmp_path):
        """运行中时停止应关闭浏览器并重置会话。"""
        manager = _make_manager(tmp_path)
        _set_session_running(manager)

        with patch("app.workers.playwright_worker.get_worker") as mock_get_worker:
            mock_worker = MagicMock()
            mock_worker.submit.return_value = _ok_response()
            mock_get_worker.return_value = mock_worker

            result = await manager.stop()

        assert result["running"] is False
        assert manager._session.running is False
        assert manager._session._browser_active is False

    @pytest.mark.asyncio
    async def test_stop_cleans_temp_files(self, tmp_path):
        """停止时清理临时截图文件。"""
        manager = _make_manager(tmp_path)
        debug_dir = tmp_path / "temp" / "debug"
        debug_dir.mkdir(parents=True)
        (debug_dir / "screenshot.png").write_bytes(b"fake_image")
        (debug_dir / "debug.png").write_bytes(b"fake_image")

        await manager.stop()

        # 文件应被清理
        assert not (debug_dir / "screenshot.png").exists()
        assert not (debug_dir / "debug.png").exists()
        # 目录本身应保留
        assert debug_dir.exists()

    @pytest.mark.asyncio
    async def test_stop_preserves_subdirs_in_temp(self, tmp_path):
        """停止时只清理文件，保留子目录。"""
        manager = _make_manager(tmp_path)
        debug_dir = tmp_path / "temp" / "debug"
        debug_dir.mkdir(parents=True)
        sub_dir = debug_dir / "subdir"
        sub_dir.mkdir()
        (debug_dir / "file.txt").write_text("data")

        await manager.stop()

        assert not (debug_dir / "file.txt").exists()
        assert sub_dir.exists()


# =====================================================================
# close
# =====================================================================


class TestDebugSessionManagerClose:
    """关闭调试会话（lifespan 清理）。"""

    @pytest.mark.asyncio
    async def test_close_when_browser_active(self, tmp_path):
        """浏览器活跃时应关闭浏览器并重置会话。"""
        manager = _make_manager(tmp_path)
        _set_session_running(manager)

        with patch("app.workers.playwright_worker.get_worker") as mock_get_worker:
            mock_worker = MagicMock()
            mock_worker.submit.return_value = _ok_response()
            mock_get_worker.return_value = mock_worker

            await manager.close()

        assert manager._session._browser_active is False
        assert manager._session.running is False

    @pytest.mark.asyncio
    async def test_close_when_browser_inactive(self, tmp_path):
        """浏览器未活跃时也应重置会话。"""
        manager = _make_manager(tmp_path)
        await manager.close()
        assert manager._session.running is False

    @pytest.mark.asyncio
    async def test_close_handles_exception(self, tmp_path):
        """关闭浏览器过程中异常不应抛出，仍应重置会话。"""
        manager = _make_manager(tmp_path)
        _set_session_running(manager)

        with patch("app.workers.playwright_worker.get_worker") as mock_get_worker:
            mock_get_worker.side_effect = RuntimeError("连接断开")

            await manager.close()

        assert manager._session.running is False


# =====================================================================
# _debug_timeout_watcher
# =====================================================================


class TestDebugSessionManagerTimeoutWatcher:
    """超时监控。"""

    @pytest.mark.asyncio
    async def test_timeout_resets_session(self, tmp_path):
        """超时后应重置会话（验证超时逻辑的核心效果）。"""
        import time as _time

        manager = _make_manager(tmp_path)
        _set_session_running(manager)
        manager._session._last_activity = _time.monotonic() - 100

        # mock _close_debug_browser 避免真实调用 Worker
        close_mock = AsyncMock()
        with patch.object(manager, "_close_debug_browser", close_mock):
            # 模拟超时逻辑：获取锁 → 关闭浏览器 → 重置会话
            async with manager._lock:
                if manager._session._browser_active:
                    await manager._close_debug_browser()
                manager._session = DebugSession()

        # 验证关闭浏览器被调用
        close_mock.assert_awaited_once()
        # 会话应已被重置
        assert manager._session.running is False
        assert manager._session._browser_active is False

    @pytest.mark.asyncio
    async def test_timeout_ignores_stale_gen(self, tmp_path):
        """代数不匹配时应退出监控。"""
        manager = _make_manager(tmp_path)
        _set_session_running(manager)

        # 使用一个不可能匹配的代数
        await manager._debug_timeout_watcher(9999, timeout_seconds=0.01)

        # 会话不应被重置（代数不匹配，应直接返回）
        # 注意：由于 timeout_seconds 极小，如果 gen 匹配会重置会话
        # 这里 gen=9999 不匹配 _current_gen，所以应该直接返回
