"""debug_service.py 补充单元测试 — 覆盖 test_debug_session_manager.py 中未触及的分支。"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.debug_service import DebugSessionManager, _rm
from app.services.debug_session import DebugSession
from app.workers.playwright_worker import WorkerResponse


# ---------------------------------------------------------------------------
# 辅助工具
# ---------------------------------------------------------------------------


def _make_manager(tmp_path: Path) -> DebugSessionManager:
    return DebugSessionManager(project_root=tmp_path)


def _ok_response(data=None) -> WorkerResponse:
    return WorkerResponse(success=True, data=data or {})


def _fail_response(error="失败") -> WorkerResponse:
    return WorkerResponse(success=False, error=error)


def _set_session_running(manager: DebugSessionManager, task_id="t1", steps=None):
    session = DebugSession()
    session.running = True
    session._browser_active = True
    session.task_id = task_id
    session.steps = steps or [
        {"index": 0, "id": "s1", "type": "click", "description": "点击按钮"},
        {"index": 1, "id": "s2", "type": "input", "description": "输入文本"},
    ]
    session.current_step = 0
    session._last_activity = time.monotonic()
    manager._session = session
    return session


# =====================================================================
# _debug_timeout_watcher: 实际超时触发路径 (lines 80-92)
# =====================================================================


class TestDebugTimeoutWatcherActualTimeout:
    """覆盖超时监控中实际触发超时关闭浏览器的分支。"""

    @pytest.mark.asyncio
    async def test_timeout_triggers_close_and_reset(self, tmp_path):
        """超时后应关闭浏览器并重置会话。"""
        manager = _make_manager(tmp_path)
        session = _set_session_running(manager)
        # 设置 _last_activity 为很久以前
        session._last_activity = time.monotonic() - 999999

        close_mock = AsyncMock()

        # 获取当前 gen 以便 watcher 内的 gen 检查通过
        from app.services.debug_service import _current_gen

        with (
            patch.object(manager, "_close_debug_browser", close_mock),
            patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
        ):
            # sleep 一次后触发超时，然后被取消
            mock_sleep.side_effect = [None, asyncio.CancelledError]
            await manager._debug_timeout_watcher(_current_gen, timeout_seconds=0.001)

        close_mock.assert_awaited_once()
        assert manager._session.running is False

    @pytest.mark.asyncio
    async def test_timeout_browser_not_active_skips_close(self, tmp_path):
        """超时时浏览器已关闭，跳过关闭但仍重置会话。"""
        manager = _make_manager(tmp_path)
        session = _set_session_running(manager)
        session._browser_active = False
        session._last_activity = time.monotonic() - 999999

        from app.services.debug_service import _current_gen

        close_mock = AsyncMock()

        with (
            patch.object(manager, "_close_debug_browser", close_mock),
            patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
        ):
            mock_sleep.side_effect = [None, asyncio.CancelledError]
            await manager._debug_timeout_watcher(_current_gen, timeout_seconds=0.001)

        close_mock.assert_not_awaited()
        assert manager._session.running is False

    @pytest.mark.asyncio
    async def test_timeout_stale_gen_inside_lock(self, tmp_path):
        """获取锁后发现代数已变，跳过超时处理。"""
        manager = _make_manager(tmp_path)
        session = _set_session_running(manager)
        session._last_activity = time.monotonic() - 999999

        original_gen = 999999

        close_mock = AsyncMock()

        with (
            patch.object(manager, "_close_debug_browser", close_mock),
            patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
            patch("app.services.debug_service._current_gen", -1),
        ):
            mock_sleep.side_effect = [None, asyncio.CancelledError]
            await manager._debug_timeout_watcher(original_gen, timeout_seconds=0.001)

        close_mock.assert_not_awaited()


# =====================================================================
# start: 模板变量替换 URL (line 121)
# =====================================================================


class TestStartTemplateVarReplacement:
    """覆盖 start 中 URL 模板变量替换的分支。"""

    @pytest.mark.asyncio
    async def test_start_url_with_template_vars(self, tmp_path):
        """URL 中的模板变量应被正确替换。"""
        manager = _make_manager(tmp_path)

        mock_task = MagicMock()
        mock_task.url = "http://{{domain}}/login"
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
        mock_runtime.credentials.auth_url = ""
        mock_runtime.credentials.isp = ""
        mock_runtime.credentials.username = ""
        mock_runtime.credentials.password = ""
        mock_monitor.get_runtime_config.return_value = mock_runtime

        with (
            patch("app.workers.playwright_worker.get_worker") as mock_get_worker,
            patch(
                "app.services.debug_service.build_login_template_vars",
                return_value={"domain": "example.com"},
            ),
            patch(
                "app.services.debug_service.runtime_config_to_worker_dict",
                return_value={},
            ),
        ):
            mock_worker = MagicMock()
            mock_worker.submit.return_value = _ok_response()
            mock_get_worker.return_value = mock_worker

            await manager.start(mock_request, mock_monitor)

        # 验证 Worker 收到的 URL 已替换
        call_args = mock_worker.submit.call_args
        worker_data = call_args[1]["data"] if call_args[1] else call_args[0][1]
        assert worker_data["task_url"] == "http://example.com/login"


# =====================================================================
# next_step: 会话被替换的分支 (lines 199, 216)
# =====================================================================


class TestNextStepSessionReplaced:
    """覆盖 next_step 中执行期间会话被替换的分支。"""

    @pytest.mark.asyncio
    async def test_next_step_session_replaced_on_failure(self, tmp_path):
        """Worker 失败后发现会话已替换，直接返回当前状态。"""
        manager = _make_manager(tmp_path)
        _set_session_running(manager)

        with patch("app.workers.playwright_worker.get_worker") as mock_get_worker:
            mock_worker = MagicMock()
            mock_get_worker.return_value = mock_worker

            # submit 是同步方法，在 to_thread 中运行
            # 在 submit 内部替换会话，模拟异步竞态
            original_submit = mock_worker.submit

            def _submit_and_replace(*args, **kwargs):
                manager._session = DebugSession()
                return WorkerResponse(success=False, error="失败")

            mock_worker.submit.side_effect = _submit_and_replace

            result = await manager.next_step()

        # 会话被替换后直接返回当前（已替换的）会话状态
        assert result["running"] is False

    @pytest.mark.asyncio
    async def test_next_step_session_replaced_on_success(self, tmp_path):
        """Worker 成功后发现会话已替换，直接返回当前状态。"""
        manager = _make_manager(tmp_path)
        _set_session_running(manager)

        with patch("app.workers.playwright_worker.get_worker") as mock_get_worker:
            mock_worker = MagicMock()
            mock_get_worker.return_value = mock_worker

            def _submit_and_replace(*args, **kwargs):
                manager._session = DebugSession()
                return WorkerResponse(
                    success=True,
                    data={
                        "step_index": 0,
                        "success": True,
                        "screenshot_url": "/s.png",
                    },
                )

            mock_worker.submit.side_effect = _submit_and_replace

            result = await manager.next_step()

        assert result["running"] is False


# =====================================================================
# run_all: 会话被替换的分支 (lines 243-244, 253-254, 276)
# =====================================================================


class TestRunAllSessionReplaced:
    """覆盖 run_all 中会话被替换的分支。"""

    @pytest.mark.asyncio
    async def test_run_all_session_replaced_inside_loop(self, tmp_path):
        """循环内会话被替换时应停止执行。"""
        manager = _make_manager(tmp_path)
        _set_session_running(
            manager,
            steps=[
                {"index": 0, "id": "s1", "type": "click", "description": "步骤1"},
                {"index": 1, "id": "s2", "type": "input", "description": "步骤2"},
            ],
        )

        with patch("app.workers.playwright_worker.get_worker") as mock_get_worker:
            mock_worker = MagicMock()
            mock_get_worker.return_value = mock_worker

            call_count = 0

            def _submit_and_replace(*args, **kwargs):
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    # 第一步成功后替换会话
                    manager._session = DebugSession()
                    return WorkerResponse(
                        success=True,
                        data={
                            "step_index": 0,
                            "success": True,
                            "screenshot_url": "/s.png",
                        },
                    )
                return WorkerResponse(
                    success=True,
                    data={
                        "step_index": 1,
                        "success": True,
                        "screenshot_url": "/s2.png",
                    },
                )

            mock_worker.submit.side_effect = _submit_and_replace
            result = await manager.run_all()

        # 会话被替换后应停止，不应执行第二步
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_run_all_session_not_running_in_loop(self, tmp_path):
        """循环内会话停止运行时应中断。"""
        manager = _make_manager(tmp_path)
        _set_session_running(
            manager,
            steps=[
                {"index": 0, "id": "s1", "type": "click", "description": "步骤1"},
                {"index": 1, "id": "s2", "type": "input", "description": "步骤2"},
            ],
        )

        with patch("app.workers.playwright_worker.get_worker") as mock_get_worker:
            mock_worker = MagicMock()
            mock_get_worker.return_value = mock_worker

            call_count = 0

            def _submit_and_stop(*args, **kwargs):
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    manager._session.running = False
                    return WorkerResponse(
                        success=True,
                        data={
                            "step_index": 0,
                            "success": True,
                            "screenshot_url": "/s.png",
                        },
                    )
                return WorkerResponse(
                    success=True,
                    data={"step_index": 1, "success": True},
                )

            mock_worker.submit.side_effect = _submit_and_stop
            result = await manager.run_all()

        assert call_count == 1

    @pytest.mark.asyncio
    async def test_run_all_session_replaced_after_step(self, tmp_path):
        """步骤执行完成后发现会话被替换。"""
        manager = _make_manager(tmp_path)
        _set_session_running(
            manager,
            steps=[
                {"index": 0, "id": "s1", "type": "click", "description": "步骤1"},
            ],
        )

        with patch("app.workers.playwright_worker.get_worker") as mock_get_worker:
            mock_worker = MagicMock()
            mock_get_worker.return_value = mock_worker

            def _submit_and_replace(*args, **kwargs):
                manager._session = DebugSession()
                return WorkerResponse(
                    success=True,
                    data={
                        "step_index": 0,
                        "success": True,
                        "screenshot_url": "/s.png",
                    },
                )

            mock_worker.submit.side_effect = _submit_and_replace
            result = await manager.run_all()

        # 应返回当前（已替换的）会话状态
        assert result["running"] is False


# =====================================================================
# stop: 临时目录清理异常 (lines 299-300)
# =====================================================================


class TestStopTempDirCleanupError:
    """覆盖 stop 中临时目录清理异常的分支。"""

    @pytest.mark.asyncio
    async def test_stop_cleanup_error_is_handled(self, tmp_path):
        """临时目录清理异常不应抛出。"""
        manager = _make_manager(tmp_path)
        debug_dir = tmp_path / "temp" / "debug"
        debug_dir.mkdir(parents=True)
        (debug_dir / "file.txt").write_text("data")

        with patch.object(type(debug_dir), "iterdir", side_effect=OSError("权限不足")):
            result = await manager.stop()

        assert result["running"] is False

    @pytest.mark.asyncio
    async def test_stop_file_unlink_error_is_handled(self, tmp_path):
        """文件删除失败不应抛出。"""
        manager = _make_manager(tmp_path)
        debug_dir = tmp_path / "temp" / "debug"
        debug_dir.mkdir(parents=True)
        (debug_dir / "file.txt").write_text("data")

        with patch("pathlib.Path.unlink", side_effect=PermissionError("占用")):
            result = await manager.stop()

        assert result["running"] is False


# =====================================================================
# _rm: Windows 文件占用重试删除
# =====================================================================


class TestRmRetryDelete:
    """覆盖 _rm 函数的重试删除逻辑。"""

    def test_rm_success_on_first_try(self, tmp_path):
        """文件可正常删除时直接成功。"""
        f = tmp_path / "test.txt"
        f.write_text("data")

        _rm(f)
        assert not f.exists()

    def test_rm_success_after_permission_errors(self, tmp_path):
        """前几次 PermissionError 后成功删除。"""
        f = tmp_path / "test.txt"
        f.write_text("data")

        call_count = 0

        original_unlink = f.unlink

        def _mock_unlink(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise PermissionError("文件被占用")
            # 第三次调用时真正删除
            return original_unlink(*args, **kwargs)

        with patch.object(type(f), "unlink", _mock_unlink):
            _rm(f)

        assert call_count == 3

    def test_rm_raises_after_all_retries_exhausted(self, tmp_path):
        """5 次重试全部失败后抛出 OSError。"""
        f = tmp_path / "test.txt"
        f.write_text("data")

        with (
            patch("pathlib.Path.unlink", side_effect=PermissionError("占用")),
            pytest.raises(OSError, match="无法删除被占用文件"),
        ):
            _rm(f)

    def test_rm_file_not_found_is_not_retried(self, tmp_path):
        """FileNotFoundError 不触发重试，直接抛出。"""
        f = tmp_path / "nonexistent.txt"

        with (
            patch("pathlib.Path.unlink", side_effect=FileNotFoundError),
            pytest.raises(FileNotFoundError),
        ):
            _rm(f)
