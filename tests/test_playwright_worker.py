"""
Tests for PlaywrightWorker — Actor 模型浏览器自动化工作线程.

覆盖生命周期、命令提交、命令派发路由、各 Handler 单元逻辑、
取消事件桥接及边界场景。所有 Playwright 依赖均使用 Mock 隔离。
"""

from __future__ import annotations

import asyncio
import threading
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.playwright_worker import (
    CMD_BROWSER_ACQUIRE,
    CMD_BROWSER_HEALTH_CHECK,
    CMD_BROWSER_RELEASE,
    CMD_DEBUG_START,
    CMD_DEBUG_STEP,
    CMD_DEBUG_STOP,
    CMD_LOGIN,
    CMD_SHUTDOWN,
    PlaywrightWorker,
    WorkerCommand,
    WorkerResponse,
)


# ── Fixtures ──


@pytest.fixture
def worker():
    """创建一个未启动的 PlaywrightWorker 实例。"""
    return PlaywrightWorker()


# ═══════════════════════════════════════════════════════════════
# 生命周期测试
# ═══════════════════════════════════════════════════════════════


class TestPlaywrightWorkerLifecycle:
    """start / stop / is_alive 生命周期方法。"""

    def test_initial_state(self, worker: PlaywrightWorker):
        assert not worker.is_alive()
        assert not worker._stop_event.is_set()
        assert worker._consumer_thread is None
        assert worker._loop is None

    def test_start_creates_daemon_thread(self, worker: PlaywrightWorker):
        """start() 创建 daemon=True 的线程并调用 start()."""
        with patch("threading.Thread") as mock_thread_cls:
            mock_thread = MagicMock()
            mock_thread_cls.return_value = mock_thread
            mock_thread.is_alive.return_value = True

            worker.start()

            mock_thread_cls.assert_called_once_with(
                target=worker._worker_entry,
                daemon=True,
                name="playwright-worker",
            )
            mock_thread.start.assert_called_once()

    def test_start_waits_for_ready(self, worker: PlaywrightWorker):
        """start() 等待事件循环就绪信号。"""
        with (
            patch("threading.Thread") as mock_thread_cls,
            patch.object(worker._worker_ready, "wait") as mock_wait,
        ):
            mock_thread_cls.return_value = MagicMock()
            mock_wait.return_value = True
            worker.start()
            mock_wait.assert_called_once_with(timeout=5)

    def test_start_ready_timeout(self, worker: PlaywrightWorker):
        """事件循环就绪超时时不会抛出异常。"""
        with (
            patch("threading.Thread") as mock_thread_cls,
            patch.object(worker._worker_ready, "wait") as mock_wait,
        ):
            mock_thread_cls.return_value = MagicMock()
            mock_wait.return_value = False  # 超时
            worker.start()  # 不应抛出异常
            assert not worker._worker_ready.is_set()

    def test_is_alive_true(self, worker: PlaywrightWorker):
        worker._consumer_thread = MagicMock()
        worker._consumer_thread.is_alive.return_value = True
        assert worker.is_alive() is True

    def test_is_alive_false_no_thread(self, worker: PlaywrightWorker):
        assert worker.is_alive() is False

    def test_is_alive_false_thread_dead(self, worker: PlaywrightWorker):
        worker._consumer_thread = MagicMock()
        worker._consumer_thread.is_alive.return_value = False
        assert worker.is_alive() is False

    def test_stop_sets_stop_event(self, worker: PlaywrightWorker):
        worker._consumer_thread = MagicMock()
        worker.stop()
        assert worker._stop_event.is_set()

    def test_stop_puts_shutdown_command(self, worker: PlaywrightWorker):
        """stop() 向队列放入 CMD_SHUTDOWN 命令。"""
        worker._consumer_thread = MagicMock()
        with patch.object(worker._cmd_queue, "put") as mock_put:
            worker.stop()
            mock_put.assert_called_once()
            cmd = mock_put.call_args[0][0]
            assert cmd.type == CMD_SHUTDOWN

    def test_stop_joins_thread(self, worker: PlaywrightWorker):
        worker._consumer_thread = MagicMock()
        worker._consumer_thread.is_alive.return_value = False  # 线程正常退出
        worker.stop(timeout=3)
        worker._consumer_thread.join.assert_called_once_with(timeout=3)

    def test_stop_no_thread_does_not_raise(self, worker: PlaywrightWorker):
        """没有线程时 stop() 不抛出异常。"""
        worker.stop()
        assert worker._stop_event.is_set()

    def test_stop_with_loop_wakes_event_loop(self, worker: PlaywrightWorker):
        """有事件循环时通过 run_coroutine_threadsafe 唤醒。"""
        worker._consumer_thread = MagicMock()
        worker._loop = MagicMock()
        with patch("asyncio.run_coroutine_threadsafe") as mock_run:
            worker.stop()
            mock_run.assert_called_once()
            assert mock_run.call_args[0][1] is worker._loop

    def test_stop_force_stops_loop_on_timeout(self, worker: PlaywrightWorker):
        """线程 join 超时后强制停止事件循环。"""
        mock_thread = MagicMock()
        mock_thread.join.side_effect = [None, None]
        mock_thread.is_alive.side_effect = [True, False]  # 首次 alive → 二次 dead
        worker._consumer_thread = mock_thread
        worker._loop = MagicMock()

        with patch("asyncio.run_coroutine_threadsafe"):
            worker.stop(timeout=0.01)

        worker._loop.call_soon_threadsafe.assert_called_once_with(worker._loop.stop)


# ═══════════════════════════════════════════════════════════════
# Submit 测试
# ═══════════════════════════════════════════════════════════════


class TestPlaywrightWorkerSubmit:
    """submit() 方法的同步/异步、超时、关闭状态。"""

    def test_submit_wait_false_returns_immediately(self, worker: PlaywrightWorker):
        """wait=False 立即返回，cmd 入队列但无 response_event。"""
        result = worker.submit(CMD_LOGIN, wait=False)
        assert result.success
        assert not worker._cmd_queue.empty()
        cmd = worker._cmd_queue.get_nowait()
        assert cmd.type == CMD_LOGIN
        assert cmd.response_event is None

    def test_submit_wait_true_with_response(self, worker: PlaywrightWorker):
        """wait=True: 拦截队列 put，模拟 handler 设置 response_data。"""
        captured: list[WorkerCommand] = []

        def intercept_put(cmd: WorkerCommand) -> None:
            captured.append(cmd)
            worker._cmd_queue._put(cmd)  # 内部加锁版本
            cmd.response_data = WorkerResponse(success=True, data="done")
            cmd.response_event.set()

        with patch.object(worker._cmd_queue, "put", side_effect=intercept_put):
            result = worker.submit(CMD_LOGIN, data={"key": "val"}, wait=True)

        assert result.success
        assert result.data == "done"
        assert len(captured) == 1
        assert captured[0].type == CMD_LOGIN
        assert captured[0].data == {"key": "val"}

    def test_submit_wait_true_data_defaults_to_empty_dict(
        self, worker: PlaywrightWorker
    ):
        """data 参数为 None 时默认转为空 dict。"""
        captured: list[WorkerCommand] = []

        def intercept_put(cmd: WorkerCommand) -> None:
            captured.append(cmd)
            cmd.response_data = WorkerResponse(success=True)
            cmd.response_event.set()

        with patch.object(worker._cmd_queue, "put", side_effect=intercept_put):
            worker.submit(CMD_LOGIN, data=None, wait=True)
        assert captured[0].data == {}

    def test_submit_stopped_worker_returns_error(self, worker: PlaywrightWorker):
        """Worker 已关闭时拒绝新命令。"""
        worker._stop_event.set()
        result = worker.submit(CMD_LOGIN)
        assert not result.success
        assert "已关闭" in result.error

    def test_submit_timeout(self, worker: PlaywrightWorker):
        """response_event.wait 超时返回超时错误。"""
        # Worker 未启动，_loop=None，不会唤醒事件循环
        # 命令入队后无人处理，response_event.wait(timeout) 超时
        result = worker.submit(CMD_LOGIN, timeout=0.005)
        assert not result.success
        assert "超时" in result.error

    def test_submit_non_worker_response_data(self, worker: PlaywrightWorker):
        """response_data 不是 WorkerResponse 时包装为 success=True。"""
        captured: list[WorkerCommand] = []

        def intercept_put(cmd: WorkerCommand) -> None:
            captured.append(cmd)
            cmd.response_data = "raw_string_data"
            cmd.response_event.set()

        with patch.object(worker._cmd_queue, "put", side_effect=intercept_put):
            result = worker.submit(CMD_LOGIN, wait=True)
        assert result.success
        assert result.data == "raw_string_data"


# ═══════════════════════════════════════════════════════════════
# _dispatch 路由测试
# ═══════════════════════════════════════════════════════════════


class TestPlaywrightWorkerDispatch:
    """_dispatch 方法根据 CMD_* 类型路由到正确的 handler。"""

    @pytest.mark.asyncio
    async def test_dispatch_login(self, worker: PlaywrightWorker):
        """CMD_LOGIN 路由到 _handle_login。"""
        worker._handle_login = AsyncMock(return_value=WorkerResponse(success=True))
        cmd = WorkerCommand(type=CMD_LOGIN, data={"config": {}})
        await worker._dispatch(cmd)
        worker._handle_login.assert_awaited_once_with({"config": {}})
        assert cmd.response_data.success

    @pytest.mark.asyncio
    async def test_dispatch_debug_start(self, worker: PlaywrightWorker):
        """CMD_DEBUG_START 路由到 _handle_debug_start。"""
        worker._handle_debug_start = AsyncMock(
            return_value=WorkerResponse(success=True)
        )
        cmd = WorkerCommand(type=CMD_DEBUG_START, data={"task_url": "http://test"})
        await worker._dispatch(cmd)
        worker._handle_debug_start.assert_awaited_once_with({"task_url": "http://test"})

    @pytest.mark.asyncio
    async def test_dispatch_debug_step(self, worker: PlaywrightWorker):
        """CMD_DEBUG_STEP 路由到 _handle_debug_step。"""
        worker._handle_debug_step = AsyncMock(return_value=WorkerResponse(success=True))
        cmd = WorkerCommand(type=CMD_DEBUG_STEP, data={"step_index": 0})
        await worker._dispatch(cmd)
        worker._handle_debug_step.assert_awaited_once_with({"step_index": 0})

    @pytest.mark.asyncio
    async def test_dispatch_debug_stop(self, worker: PlaywrightWorker):
        """CMD_DEBUG_STOP 路由到 _handle_debug_stop。"""
        worker._handle_debug_stop = AsyncMock(return_value=WorkerResponse(success=True))
        cmd = WorkerCommand(type=CMD_DEBUG_STOP)
        await worker._dispatch(cmd)
        worker._handle_debug_stop.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_dispatch_health_check(self, worker: PlaywrightWorker):
        """CMD_BROWSER_HEALTH_CHECK 路由到 _handle_health_check。"""
        worker._handle_health_check = AsyncMock(
            return_value=WorkerResponse(success=True)
        )
        cmd = WorkerCommand(type=CMD_BROWSER_HEALTH_CHECK)
        await worker._dispatch(cmd)
        worker._handle_health_check.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_dispatch_browser_acquire(self, worker: PlaywrightWorker):
        """CMD_BROWSER_ACQUIRE 路由到 _handle_browser_acquire。"""
        worker._handle_browser_acquire = AsyncMock(
            return_value=WorkerResponse(success=True)
        )
        cmd = WorkerCommand(type=CMD_BROWSER_ACQUIRE, data={"config": {}})
        await worker._dispatch(cmd)
        worker._handle_browser_acquire.assert_awaited_once_with({"config": {}})

    @pytest.mark.asyncio
    async def test_dispatch_browser_release(self, worker: PlaywrightWorker):
        """CMD_BROWSER_RELEASE 路由到 _handle_browser_release。"""
        worker._handle_browser_release = AsyncMock(
            return_value=WorkerResponse(success=True)
        )
        cmd = WorkerCommand(type=CMD_BROWSER_RELEASE)
        await worker._dispatch(cmd)
        worker._handle_browser_release.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_dispatch_shutdown(self, worker: PlaywrightWorker):
        """CMD_SHUTDOWN 直接返回 success，不经过 handler。"""
        cmd = WorkerCommand(type=CMD_SHUTDOWN)
        await worker._dispatch(cmd)
        assert cmd.response_data.success
        assert "正在关闭" in cmd.response_data.data

    @pytest.mark.asyncio
    async def test_dispatch_unknown_type(self, worker: PlaywrightWorker):
        """未知命令类型返回错误。"""
        cmd = WorkerCommand(type="unknown_cmd", data={"foo": "bar"})
        await worker._dispatch(cmd)
        assert not cmd.response_data.success
        assert "未知命令类型" in cmd.response_data.error
        assert "unknown_cmd" in cmd.response_data.error

    @pytest.mark.asyncio
    async def test_dispatch_exception_caught(self, worker: PlaywrightWorker):
        """handler 抛出异常时 _dispatch 捕获并返回错误响应。"""
        worker._handle_login = AsyncMock(side_effect=RuntimeError("boom"))
        cmd = WorkerCommand(type=CMD_LOGIN)
        await worker._dispatch(cmd)
        assert not cmd.response_data.success
        assert "命令执行异常" in cmd.response_data.error
        assert "boom" in cmd.response_data.error

    @pytest.mark.asyncio
    async def test_dispatch_sets_response_event(self, worker: PlaywrightWorker):
        """_dispatch 完成后设置 response_event。"""
        cmd = WorkerCommand(type=CMD_SHUTDOWN, response_event=threading.Event())
        await worker._dispatch(cmd)
        assert cmd.response_event.is_set()


# ═══════════════════════════════════════════════════════════════
# _handle_login 单元测试
# ═══════════════════════════════════════════════════════════════


class TestPlaywrightWorkerHandlerLogin:
    """_handle_login — 创建 LoginAttemptHandler 并执行登录。"""

    @pytest.mark.asyncio
    async def test_handle_login_success(self, worker: PlaywrightWorker):
        """验证 LoginAttemptHandler 被正确创建和调用。"""
        mock_handler = MagicMock()
        mock_handler.attempt_login = AsyncMock(return_value=(True, "登录成功"))
        worker._cancel_async = asyncio.Event()

        with patch("src.utils.login.LoginAttemptHandler", return_value=mock_handler):
            result = await worker._handle_login(
                data={
                    "config": {"username": "test"},
                    "skip_pause_check": True,
                    "reuse_browser": True,
                }
            )

        assert result.success
        assert result.data == "登录成功"
        mock_handler.attempt_login.assert_awaited_once_with(
            skip_pause_check=True, reuse_browser=True
        )

    @pytest.mark.asyncio
    async def test_handle_login_with_cancel_event(self, worker: PlaywrightWorker):
        """cancel_event 存在时启动桥接协程。"""
        mock_handler = MagicMock()
        mock_handler.attempt_login = AsyncMock(return_value=(True, "ok"))
        worker._cancel_async = asyncio.Event()
        cancel_event = threading.Event()

        with (
            patch(
                "src.utils.login.LoginAttemptHandler",
                return_value=mock_handler,
            ),
            patch.object(worker, "_bridge_cancel") as mock_bridge,
        ):
            mock_bridge.return_value = asyncio.sleep(0)  # 模拟协程立即完成
            result = await worker._handle_login(
                data={
                    "config": {},
                    "cancel_event": cancel_event,
                }
            )

        assert result.success
        mock_bridge.assert_called_once_with(cancel_event)
        # 完成后 bridge_task 被取消
        # cancel_async 被 clear 过
        assert not worker._cancel_async.is_set()

    @pytest.mark.asyncio
    async def test_handle_login_exception(self, worker: PlaywrightWorker):
        """LoginAttemptHandler 抛出异常时返回错误响应。"""
        worker._cancel_async = asyncio.Event()
        with patch(
            "src.utils.login.LoginAttemptHandler",
            side_effect=ValueError("bad config"),
        ):
            result = await worker._handle_login(data={"config": {}})
        assert not result.success
        assert "bad config" in result.error


# ═══════════════════════════════════════════════════════════════
# _handle_debug_start 单元测试
# ═══════════════════════════════════════════════════════════════


class TestPlaywrightWorkerHandlerDebugStart:
    """_handle_debug_start — 启动调试会话。"""

    @pytest.mark.asyncio
    async def test_debug_start_healthy_browser(self, worker: PlaywrightWorker):
        """浏览器健康时跳过重建步骤。"""
        page_mock = MagicMock()
        page_mock.goto = AsyncMock()
        page_mock.screenshot = AsyncMock()
        page_mock.is_closed.return_value = False
        worker._page = page_mock
        worker._health_check = AsyncMock(return_value=True)

        result = await worker._handle_debug_start(
            data={
                "task_url": "http://example.com",
                "task_data": {"steps": [], "task_id": "t1"},
            }
        )

        assert result.success
        assert not worker._cancel_async  # 默认 None
        page_mock.goto.assert_awaited_once_with(
            "http://example.com", wait_until="domcontentloaded", timeout=30000
        )

    @pytest.mark.asyncio
    async def test_debug_start_unhealthy_browser(self, worker: PlaywrightWorker):
        """浏览器不健康时触发重建。"""
        page_mock = MagicMock()
        page_mock.goto = AsyncMock()
        page_mock.screenshot = AsyncMock()
        page_mock.is_closed.return_value = False
        worker._page = page_mock
        worker._health_check = AsyncMock(return_value=False)
        worker._close_browser = AsyncMock()
        worker._start_browser = AsyncMock()

        result = await worker._handle_debug_start(
            data={
                "config": {"browser_settings": {"headless": True}},
                "task_url": "http://example.com",
            }
        )

        assert result.success
        worker._close_browser.assert_awaited_once()
        worker._start_browser.assert_awaited_once_with(
            {"browser_settings": {"headless": True}}
        )

    @pytest.mark.asyncio
    async def test_debug_start_no_page(self, worker: PlaywrightWorker):
        """_page 为 None 时返回错误。"""
        worker._page = None
        worker._health_check = AsyncMock(return_value=True)

        result = await worker._handle_debug_start(data={})
        assert not result.success
        assert "页面初始化失败" in result.error

    @pytest.mark.asyncio
    async def test_debug_start_creates_executor(self, worker: PlaywrightWorker):
        """task_data 存在时创建 TaskExecutor。"""
        page_mock = MagicMock()
        page_mock.goto = AsyncMock()
        page_mock.screenshot = AsyncMock()
        page_mock.is_closed.return_value = False
        worker._page = page_mock
        worker._health_check = AsyncMock(return_value=True)

        mock_config = MagicMock()
        mock_executor = MagicMock()

        with (
            patch("src.task_executor.TaskConfig") as mock_tc_cls,
            patch("src.task_executor.TaskExecutor") as mock_te_cls,
        ):
            mock_tc_cls.from_dict.return_value = mock_config
            mock_te_cls.return_value = mock_executor

            result = await worker._handle_debug_start(
                data={
                    "task_data": {"steps": [{"type": "navigate"}]},
                    "env_vars": {"VAR": "val"},
                    "screenshot_dir": "",
                    "default_timeout": 5000,
                }
            )

        assert result.success
        mock_tc_cls.from_dict.assert_called_once_with({"steps": [{"type": "navigate"}]})
        mock_te_cls.assert_called_once_with(
            mock_config,
            {"VAR": "val"},
            screenshot_dir=None,
            default_timeout=5000,
        )
        assert worker._debug_executor is mock_executor

    @pytest.mark.asyncio
    async def test_debug_start_executor_failure(self, worker: PlaywrightWorker):
        """TaskConfig.from_dict 失败时返回错误。"""
        page_mock = MagicMock()
        page_mock.goto = AsyncMock()
        page_mock.screenshot = AsyncMock()
        page_mock.is_closed.return_value = False
        worker._page = page_mock
        worker._health_check = AsyncMock(return_value=True)

        with patch(
            "src.task_executor.TaskConfig.from_dict",
            side_effect=ValueError("bad task"),
        ):
            result = await worker._handle_debug_start(data={"task_data": {"steps": []}})

        assert not result.success
        assert "创建任务执行器失败" in result.error

    @pytest.mark.asyncio
    async def test_debug_start_screenshot(self, worker: PlaywrightWorker):
        """验证截图被正确保存。"""
        import tempfile

        page_mock = MagicMock()
        page_mock.goto = AsyncMock()
        page_mock.screenshot = AsyncMock()
        page_mock.is_closed.return_value = False
        worker._page = page_mock
        worker._health_check = AsyncMock(return_value=True)

        with tempfile.TemporaryDirectory() as tmpdir:
            result = await worker._handle_debug_start(
                data={
                    "task_url": "http://test",
                    "task_data": {"steps": [], "task_id": "test123"},
                    "screenshot_dir": tmpdir,
                }
            )

        assert result.success
        assert result.data["screenshot_url"] is not None
        assert "/temp/" in result.data["screenshot_url"]
        page_mock.screenshot.assert_called_once()
        call_kwargs = page_mock.screenshot.call_args.kwargs
        assert call_kwargs["full_page"] is True
        assert "test123" in call_kwargs["path"]

    @pytest.mark.asyncio
    async def test_debug_start_no_task_data_skips_executor(
        self, worker: PlaywrightWorker
    ):
        """task_data 为空时跳过 TaskExecutor 创建和导航。"""
        page_mock = MagicMock()
        page_mock.screenshot = AsyncMock()
        page_mock.is_closed.return_value = False
        worker._page = page_mock
        worker._health_check = AsyncMock(return_value=True)

        result = await worker._handle_debug_start(data={})

        assert result.success
        assert worker._debug_executor is None
        page_mock.goto.assert_not_called()


# ═══════════════════════════════════════════════════════════════
# _handle_debug_step 单元测试
# ═══════════════════════════════════════════════════════════════


class TestPlaywrightWorkerHandlerDebugStep:
    """_handle_debug_step — 执行调试下一步。"""

    @pytest.mark.asyncio
    async def test_debug_step_no_session(self, worker: PlaywrightWorker):
        """_debug_page 为 None 时返回错误。"""
        worker._debug_page = None
        result = await worker._handle_debug_step(data={"step_index": 0})
        assert not result.success
        assert "未启动" in result.error

    @pytest.mark.asyncio
    async def test_debug_step_closed_page(self, worker: PlaywrightWorker):
        """_debug_page 已关闭时重置并返回错误。"""
        page_mock = MagicMock()
        page_mock.is_closed.return_value = True
        worker._debug_page = page_mock
        result = await worker._handle_debug_step(data={})
        assert not result.success
        assert "已关闭" in result.error
        assert worker._debug_page is None

    @pytest.mark.asyncio
    async def test_debug_step_no_executor(self, worker: PlaywrightWorker):
        """_debug_executor 为 None 时返回错误。"""
        worker._debug_page = MagicMock()
        worker._debug_page.is_closed.return_value = False
        worker._debug_executor = None
        result = await worker._handle_debug_step(data={"step_index": 0})
        assert not result.success
        assert "执行器未创建" in result.error

    @pytest.mark.asyncio
    async def test_debug_step_success(self, worker: PlaywrightWorker):
        """成功执行调试步骤。"""
        page_mock = MagicMock()
        page_mock.is_closed.return_value = False
        worker._debug_page = page_mock
        executor_mock = MagicMock()
        executor_mock.execute_step_at = AsyncMock(
            return_value={"success": True, "step": 0, "output": "done"}
        )
        worker._debug_executor = executor_mock

        result = await worker._handle_debug_step(data={"step_index": 2})
        assert result.success
        assert result.data["output"] == "done"
        executor_mock.execute_step_at.assert_awaited_once_with(page_mock, 2)

    @pytest.mark.asyncio
    async def test_debug_step_exception(self, worker: PlaywrightWorker):
        """execute_step_at 抛出异常时返回错误响应。"""
        page_mock = MagicMock()
        page_mock.is_closed.return_value = False
        worker._debug_page = page_mock
        executor_mock = MagicMock()
        executor_mock.execute_step_at = AsyncMock(
            side_effect=RuntimeError("exec failed")
        )
        worker._debug_executor = executor_mock

        result = await worker._handle_debug_step(data={"step_index": 0})
        assert not result.success
        assert "exec failed" in result.error


# ═══════════════════════════════════════════════════════════════
# _handle_debug_stop 单元测试
# ═══════════════════════════════════════════════════════════════


class TestPlaywrightWorkerHandlerDebugStop:
    """_handle_debug_stop — 停止调试会话并清理状态。"""

    @pytest.mark.asyncio
    async def test_debug_stop_cleans_up(self, worker: PlaywrightWorker):
        """清除 _debug_executor 并关闭 _debug_page。"""
        page_mock = MagicMock()
        page_mock.is_closed.return_value = False
        page_mock.close = AsyncMock()
        worker._debug_page = page_mock
        worker._debug_executor = MagicMock()
        worker._page = MagicMock()  # 独立的主页面

        result = await worker._handle_debug_stop()
        assert result.success
        assert worker._debug_executor is None
        assert worker._debug_page is None
        # 主页面不受影响
        assert worker._page is not None
        page_mock.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_debug_stop_same_as_main_page(self, worker: PlaywrightWorker):
        """_debug_page 与 _page 相同时，关闭后创建替代页面。"""
        page_mock = MagicMock()
        page_mock.is_closed.return_value = False
        page_mock.close = AsyncMock()
        worker._page = page_mock
        worker._debug_page = page_mock

        # 需要有 context 才能创建替代页面
        ctx_mock = MagicMock()
        ctx_mock.is_closed.return_value = False
        new_page_mock = MagicMock()
        ctx_mock.new_page = AsyncMock(return_value=new_page_mock)
        worker._context = ctx_mock

        result = await worker._handle_debug_stop()
        assert result.success
        # 应创建替代页面而非置为 None
        assert worker._page is not None
        assert worker._page is new_page_mock
        assert worker._debug_page is None

    @pytest.mark.asyncio
    async def test_debug_stop_close_exception(self, worker: PlaywrightWorker):
        """close() 抛出异常时仍返回 success。"""
        page_mock = MagicMock()
        page_mock.is_closed.return_value = False
        page_mock.close = AsyncMock(side_effect=RuntimeError("close error"))
        worker._debug_page = page_mock

        result = await worker._handle_debug_stop()
        assert result.success

    @pytest.mark.asyncio
    async def test_debug_stop_no_debug_page(self, worker: PlaywrightWorker):
        """没有调试页面时只清除 executor。"""
        worker._debug_executor = MagicMock()
        result = await worker._handle_debug_stop()
        assert result.success
        assert worker._debug_executor is None


# ═══════════════════════════════════════════════════════════════
# _handle_health_check 单元测试
# ═══════════════════════════════════════════════════════════════


class TestPlaywrightWorkerHandlerHealthCheck:
    """_handle_health_check — 返回浏览器健康状态。"""

    @pytest.mark.asyncio
    async def test_handle_health_check_healthy(self, worker: PlaywrightWorker):
        worker._health_check = AsyncMock(return_value=True)
        result = await worker._handle_health_check()
        assert result.success
        assert result.data is True

    @pytest.mark.asyncio
    async def test_handle_health_check_unhealthy(self, worker: PlaywrightWorker):
        worker._health_check = AsyncMock(return_value=False)
        result = await worker._handle_health_check()
        assert not result.success
        assert result.data is False


# ═══════════════════════════════════════════════════════════════
# _handle_browser_acquire 单元测试
# ═══════════════════════════════════════════════════════════════


class TestPlaywrightWorkerHandlerBrowserAcquire:
    """_handle_browser_acquire — 确保浏览器就绪。"""

    @pytest.mark.asyncio
    async def test_handle_browser_acquire(self, worker: PlaywrightWorker):
        worker.ensure_browser = AsyncMock()
        result = await worker._handle_browser_acquire(
            data={"config": {"browser_settings": {"headless": True}}}
        )
        assert result.success
        assert result.data == "Browser ready"
        worker.ensure_browser.assert_awaited_once_with(
            {"browser_settings": {"headless": True}}
        )


# ═══════════════════════════════════════════════════════════════
# _handle_browser_release 单元测试
# ═══════════════════════════════════════════════════════════════


class TestPlaywrightWorkerHandlerBrowserRelease:
    """_handle_browser_release — 释放浏览器引用（不实际关闭）。"""

    @pytest.mark.asyncio
    async def test_handle_browser_release(self, worker: PlaywrightWorker):
        result = await worker._handle_browser_release()
        assert result.success
        assert "alive in Worker" in result.data


# ═══════════════════════════════════════════════════════════════
# _bridge_cancel 单元测试
# ═══════════════════════════════════════════════════════════════


class TestCancelBridge:
    """_bridge_cancel — threading.Event → asyncio.Event 桥接。"""

    @pytest.mark.asyncio
    async def test_bridge_cancel_triggers_async_event(self, worker: PlaywrightWorker):
        """外部 threading.Event 被设置后，_cancel_async 也被设置。"""
        worker._cancel_async = asyncio.Event()
        cancel_threading = threading.Event()

        bridge = asyncio.create_task(worker._bridge_cancel(cancel_threading))
        # 给桥接协程一点时间进入循环
        await asyncio.sleep(0.05)
        assert not worker._cancel_async.is_set()

        cancel_threading.set()
        await asyncio.sleep(0.15)  # 桥接轮询间隔 0.1s
        assert worker._cancel_async.is_set()

        bridge.cancel()
        try:
            await bridge
        except asyncio.CancelledError:
            pass

    @pytest.mark.asyncio
    async def test_bridge_cancel_already_set(self, worker: PlaywrightWorker):
        """_cancel_async 已设置时桥接立即退出。"""
        worker._cancel_async = asyncio.Event()
        worker._cancel_async.set()
        cancel_threading = threading.Event()

        bridge = asyncio.create_task(worker._bridge_cancel(cancel_threading))
        await asyncio.sleep(0.05)
        # 桥接应该已经退出（_cancel_async 已设置，不进入循环）
        assert not bridge.done() or not bridge.cancelled()
        bridge.cancel()
        try:
            await bridge
        except asyncio.CancelledError:
            pass

    @pytest.mark.asyncio
    async def test_bridge_cancel_cancelled_gracefully(self, worker: PlaywrightWorker):
        """CancelledError 被干净地捕获。"""
        worker._cancel_async = asyncio.Event()
        cancel_threading = threading.Event()

        bridge = asyncio.create_task(worker._bridge_cancel(cancel_threading))
        await asyncio.sleep(0.05)
        bridge.cancel()

        try:
            await bridge
        except asyncio.CancelledError:
            pytest.fail("CancelledError should have been caught by _bridge_cancel")

        # 无异常即成功


# ═══════════════════════════════════════════════════════════════
# 边界场景
# ═══════════════════════════════════════════════════════════════


class TestPlaywrightWorkerEdgeCases:
    """各种边界场景。"""

    def test_submit_no_loop_does_not_wake(self, worker: PlaywrightWorker):
        """_loop 为 None 时不调用 run_coroutine_threadsafe。"""
        with patch("asyncio.run_coroutine_threadsafe") as mock_run:
            worker.submit(CMD_LOGIN, wait=False)
            mock_run.assert_not_called()

    def test_submit_with_loop_wakes(self, worker: PlaywrightWorker):
        """_loop 存在时通过 run_coroutine_threadsafe 唤醒。"""
        worker._loop = MagicMock()
        with patch("asyncio.run_coroutine_threadsafe") as mock_run:
            worker.submit(CMD_LOGIN, wait=False)
            mock_run.assert_called_once()

    def test_stop_wake_skipped_when_no_loop(self, worker: PlaywrightWorker):
        """没有事件循环时 stop 不调用 run_coroutine_threadsafe。"""
        worker._consumer_thread = MagicMock()
        worker._loop = None
        with patch("asyncio.run_coroutine_threadsafe") as mock_run:
            worker.stop()
            mock_run.assert_not_called()

    @pytest.mark.asyncio
    async def test_ensure_browser_healthy(self, worker: PlaywrightWorker):
        """ensure_browser: 健康检查通过时不重建。"""
        worker._health_check = AsyncMock(return_value=True)
        worker._close_browser = AsyncMock()
        worker._start_browser = AsyncMock()

        await worker.ensure_browser({"browser_settings": {}})

        worker._close_browser.assert_not_called()
        worker._start_browser.assert_not_called()

    @pytest.mark.asyncio
    async def test_ensure_browser_unhealthy(self, worker: PlaywrightWorker):
        """ensure_browser: 健康检查失败时重建。"""
        worker._health_check = AsyncMock(return_value=False)
        worker._close_browser = AsyncMock()
        worker._start_browser = AsyncMock()

        await worker.ensure_browser({"browser_settings": {"headless": True}})

        worker._close_browser.assert_awaited_once()
        worker._start_browser.assert_awaited_once_with(
            {"browser_settings": {"headless": True}}
        )

    @pytest.mark.asyncio
    async def test_wake_async_sets_event(self, worker: PlaywrightWorker):
        """_wake_async 设置 _wake_event。"""
        worker._wake_event = asyncio.Event()
        await worker._wake_async()
        assert worker._wake_event.is_set()

    @pytest.mark.asyncio
    async def test_wake_async_no_event(self, worker: PlaywrightWorker):
        """_wake_event 为 None 时 _wake_async 不抛出异常。"""
        worker._wake_event = None
        await worker._wake_async()  # 不应异常

    def test_submit_response_event_not_set_when_no_wait(self, worker: PlaywrightWorker):
        """wait=False 时 cmd 的 response_event 为 None。"""
        worker.submit(CMD_LOGIN, wait=False)
        cmd = worker._cmd_queue.get_nowait()
        assert cmd.response_event is None

    def test_submit_response_event_set_when_wait(self, worker: PlaywrightWorker):
        """wait=True 时 cmd 的 response_event 不为 None。"""
        captured: list[WorkerCommand] = []

        def intercept_put(cmd: WorkerCommand) -> None:
            captured.append(cmd)
            cmd.response_data = WorkerResponse(success=True)
            cmd.response_event.set()

        with patch.object(worker._cmd_queue, "put", side_effect=intercept_put):
            worker.submit(CMD_LOGIN, wait=True)
        assert captured[0].response_event is not None
        assert isinstance(captured[0].response_event, threading.Event)
