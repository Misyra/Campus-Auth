"""Playwright Worker 测试."""

from __future__ import annotations

import asyncio
import contextlib
import threading
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import psutil
import pytest

import app.workers.playwright_worker as pw_module
from app.workers.playwright_worker import (
    CMD_BROWSER,
    CMD_LOGIN,
    cleanup_orphan_browsers,
)

# ── cleanup_orphan_browsers ──


@pytest.fixture(autouse=True)
def _reset_cleanup_cooldown():
    """每个测试前重置清理冷却时间，确保扫描逻辑被执行。"""
    pw_module._last_cleanup_time = 0.0
    yield
    pw_module._last_cleanup_time = 0.0


def _make_proc(pid, exe, cmdline, orphan=True):
    """构造 mock 进程对象。orphan=True 模拟父进程已死。"""
    proc = MagicMock(spec=psutil.Process)
    # name 用于快速过滤；从 exe 路径推导 basename
    name = Path(exe).name if exe else ""
    proc.info = {"pid": pid, "name": name}
    proc.pid = pid
    proc.exe.return_value = exe
    proc.cmdline.return_value = cmdline
    if orphan:
        proc.parent.return_value = None
    else:
        parent = MagicMock(spec=psutil.Process)
        parent.is_running.return_value = True
        proc.parent.return_value = parent
    return proc


class TestCleanupOrphanBrowsers:
    """孤儿浏览器清理。"""

    def test_kills_orphan_playwright_browser(self):
        """Playwright 浏览器 + 父进程已死 → 被清理。"""
        proc = _make_proc(
            100,
            "C:\\ms-playwright\\chromium-123\\chrome.exe",
            ["chrome.exe", "--ms-playwright"],
            orphan=True,
        )

        with patch("psutil.process_iter", return_value=[proc]):
            cleanup_orphan_browsers()

        proc.kill.assert_called_once()

    def test_skips_alive_parent(self):
        """Playwright 浏览器 + 父进程存活 → 不清理。"""
        proc = _make_proc(
            100,
            "C:\\ms-playwright\\chromium-123\\chrome.exe",
            ["chrome.exe", "--ms-playwright"],
            orphan=False,
        )

        with patch("psutil.process_iter", return_value=[proc]):
            cleanup_orphan_browsers()

        proc.kill.assert_not_called()

    def test_skips_non_playwright_browser(self):
        """非 Playwright 管理的浏览器 → 不清理。"""
        proc = _make_proc(
            200,
            "C:\\Program Files\\Google\\Chrome\\chrome.exe",
            ["chrome.exe"],
        )

        with patch("psutil.process_iter", return_value=[proc]):
            cleanup_orphan_browsers()

        proc.kill.assert_not_called()

    def test_skips_non_browser_process(self):
        """非浏览器的 Playwright 进程 → 不清理。"""
        proc = _make_proc(
            300,
            "C:\\ms-playwright\\node-123\\node.exe",
            ["node.exe", "--ms-playwright"],
        )

        with patch("psutil.process_iter", return_value=[proc]):
            cleanup_orphan_browsers()

        proc.kill.assert_not_called()

    def test_handles_access_denied(self):
        """AccessDenied 异常被静默处理。"""
        proc = _make_proc(
            400,
            "C:\\ms-playwright\\chromium-123\\chrome.exe",
            ["chrome.exe", "--ms-playwright"],
            orphan=True,
        )
        proc.kill.side_effect = psutil.AccessDenied(400)

        with patch("psutil.process_iter", return_value=[proc]):
            cleanup_orphan_browsers()  # 不应抛异常

    def test_kills_multiple_orphans(self):
        """多个孤儿浏览器进程 → 全部清理。"""
        proc1 = _make_proc(
            101,
            "C:\\ms-playwright\\chromium-123\\chrome.exe",
            ["chrome.exe", "--ms-playwright"],
            orphan=True,
        )
        proc2 = _make_proc(
            102,
            "C:\\ms-playwright\\firefox-123\\firefox.exe",
            ["firefox.exe", "--ms-playwright"],
            orphan=True,
        )

        with patch("psutil.process_iter", return_value=[proc1, proc2]):
            cleanup_orphan_browsers()

        proc1.kill.assert_called_once()
        proc2.kill.assert_called_once()

    def test_skips_alive_parent_among_mix(self):
        """混合场景：一个孤儿 + 一个有父进程 → 只清理孤儿。"""
        orphan = _make_proc(
            101,
            "C:\\ms-playwright\\chromium-123\\chrome.exe",
            ["chrome.exe", "--ms-playwright"],
            orphan=True,
        )
        alive = _make_proc(
            102,
            "C:\\ms-playwright\\chromium-124\\chrome.exe",
            ["chrome.exe", "--ms-playwright"],
            orphan=False,
        )

        with patch("psutil.process_iter", return_value=[orphan, alive]):
            cleanup_orphan_browsers()

        orphan.kill.assert_called_once()
        alive.kill.assert_not_called()


# ── stop() 队列满时仍 join 消费者线程 ──


class TestStopJoinsOnQueueFull:
    """stop() 在命令队列满时仍应等待消费者线程退出。"""

    def test_stop_joins_consumer_when_queue_full(self):
        """队列满 → call_soon_threadsafe(put_nowait) 抛 QueueFull → 仍调用 join。"""
        from app.workers.playwright_worker import PlaywrightWorker

        worker = PlaywrightWorker()

        fake_thread = MagicMock(spec=threading.Thread)
        fake_thread.is_alive.return_value = False
        worker._consumer_thread = fake_thread

        fake_loop = MagicMock()
        fake_loop.is_running.return_value = True

        # call_soon_threadsafe 同步执行 fn，put_nowait 抛 QueueFull
        def fake_call_soon(fn, *args):
            with contextlib.suppress(asyncio.QueueFull):
                fn(*args)

        fake_loop.call_soon_threadsafe.side_effect = fake_call_soon
        worker._loop = fake_loop

        with patch.object(
            worker._cmd_queue, "put_nowait", side_effect=asyncio.QueueFull
        ):
            worker.stop(timeout=1)

        fake_thread.join.assert_called()

    def test_stop_reaches_join_even_when_loop_stop_called(self):
        """队列满 → call_soon_threadsafe(put_nowait) 抛 QueueFull（被 fake_call_soon 吞）→ 仍 join。"""
        from app.workers.playwright_worker import PlaywrightWorker

        worker = PlaywrightWorker()

        fake_thread = MagicMock(spec=threading.Thread)
        fake_thread.is_alive.return_value = False
        worker._consumer_thread = fake_thread

        fake_loop = MagicMock()
        fake_loop.is_running.return_value = True

        # call_soon_threadsafe 同步执行 fn，put_nowait 抛 QueueFull
        def fake_call_soon(fn, *args):
            with contextlib.suppress(asyncio.QueueFull):
                fn(*args)

        fake_loop.call_soon_threadsafe.side_effect = fake_call_soon
        worker._loop = fake_loop

        with patch.object(
            worker._cmd_queue, "put_nowait", side_effect=asyncio.QueueFull
        ):
            worker.stop(timeout=2)

        fake_thread.join.assert_called()

    def test_stop_joins_when_loop_not_running(self):
        """队列满 + 事件循环未运行 → 直接 put_nowait 抛 QueueFull → 仍 join。"""
        from app.workers.playwright_worker import PlaywrightWorker

        worker = PlaywrightWorker()

        fake_thread = MagicMock(spec=threading.Thread)
        fake_thread.is_alive.return_value = False
        worker._consumer_thread = fake_thread

        fake_loop = MagicMock()
        fake_loop.is_running.return_value = False
        worker._loop = fake_loop

        # loop 未运行 → stop() 用 put_nowait（不走 call_soon_threadsafe）
        with patch.object(
            worker._cmd_queue, "put_nowait", side_effect=asyncio.QueueFull
        ):
            worker.stop(timeout=1)

        fake_thread.join.assert_called()

    def test_stop_joins_when_loop_is_none(self):
        """队列满 + 无事件循环 → 仍 join。"""
        from app.workers.playwright_worker import PlaywrightWorker

        worker = PlaywrightWorker()

        fake_thread = MagicMock(spec=threading.Thread)
        fake_thread.is_alive.return_value = False
        worker._consumer_thread = fake_thread
        worker._loop = None

        # loop 为 None → stop() 用 put_nowait（不走 call_soon_threadsafe）
        with patch.object(
            worker._cmd_queue, "put_nowait", side_effect=asyncio.QueueFull
        ):
            worker.stop(timeout=1)

        fake_thread.join.assert_called()

    def test_stop_logs_warning_on_queue_full(self):
        """队列满时，lambda 包装器捕获 QueueFull 并记录 warning + 调用 loop.stop。"""
        from app.workers.playwright_worker import PlaywrightWorker

        worker = PlaywrightWorker()

        fake_thread = MagicMock(spec=threading.Thread)
        fake_thread.is_alive.return_value = False
        worker._consumer_thread = fake_thread

        fake_loop = MagicMock()
        fake_loop.is_running.return_value = True
        # call_soon_threadsafe 同步执行 fn（模拟 loop 线程行为）
        fake_loop.call_soon_threadsafe.side_effect = lambda fn, *args: fn(*args)
        worker._loop = fake_loop

        with patch.object(
            worker._cmd_queue, "put_nowait", side_effect=asyncio.QueueFull
        ):
            worker.stop(timeout=1)

        # lambda 包装器捕获 QueueFull → 调用 loop.call_soon_threadsafe(loop.stop)
        fake_loop.stop.assert_called()
        fake_thread.join.assert_called()


# ── _cleanup_debug_session ──


class TestCleanupDebugSession:
    """_cleanup_debug_session 清理调试会话资源。"""

    def test_clears_page_reference(self):
        """清理调试会话时同步释放 _page 引用。"""
        from app.workers.playwright_worker import PlaywrightWorker

        worker = PlaywrightWorker()
        fake_page = MagicMock()
        fake_page.is_closed.return_value = False
        worker._page = fake_page
        worker._debug_page = fake_page
        worker._debug_executor = MagicMock()

        import asyncio

        asyncio.run(worker._cleanup_debug_session())

        assert worker._page is None
        assert worker._debug_page is None
        assert worker._debug_executor is None

    def test_clears_page_even_when_debug_page_is_none(self):
        """_debug_page 为 None 时仍清理 _page。"""
        from app.workers.playwright_worker import PlaywrightWorker

        worker = PlaywrightWorker()
        fake_page = MagicMock()
        worker._page = fake_page
        worker._debug_page = None

        import asyncio

        asyncio.run(worker._cleanup_debug_session())

        assert worker._page is None

    def test_closes_debug_page_before_clearing(self):
        """清理时关闭 _debug_page（若未关闭）。"""
        from app.workers.playwright_worker import PlaywrightWorker

        worker = PlaywrightWorker()
        fake_page = MagicMock()
        fake_page.is_closed.return_value = False
        worker._debug_page = fake_page
        worker._page = MagicMock()

        import asyncio

        asyncio.run(worker._cleanup_debug_session())

        fake_page.close.assert_called_once()
        assert worker._page is None

    def test_skips_close_when_debug_page_already_closed(self):
        """_debug_page 已关闭时不再调用 close。"""
        from app.workers.playwright_worker import PlaywrightWorker

        worker = PlaywrightWorker()
        fake_page = MagicMock()
        fake_page.is_closed.return_value = True
        worker._debug_page = fake_page
        worker._page = MagicMock()

        import asyncio

        asyncio.run(worker._cleanup_debug_session())

        fake_page.close.assert_not_called()
        assert worker._page is None


# ── CMD_BROWSER 常量 ──


def test_cmd_browser_constant_exists():
    """CMD_BROWSER 常量已定义，与 CMD_LOGIN 区分。"""
    assert CMD_BROWSER == "browser"
    assert CMD_BROWSER != CMD_LOGIN


# ── _handle_browser_task 参数校验与错误路径 ──


class TestHandleBrowserTask:
    """_handle_browser_task 早返回路径（无需真实浏览器）。"""

    async def test_missing_cancel_event(self):
        """缺 cancel_event → 返回 cancel_event 缺失。"""
        from app.workers.playwright_worker import PlaywrightWorker

        worker = PlaywrightWorker()
        data = {"config": {"active_task": "some_task"}}

        resp = await worker._handle_browser_task(data)

        assert resp.success is False
        assert resp.error == "cancel_event 缺失"

    async def test_missing_active_task(self):
        """active_task 为空 → 返回未指定任务。"""
        from app.workers.playwright_worker import PlaywrightWorker

        worker = PlaywrightWorker()
        cancel_event = threading.Event()
        data = {"config": {}, "cancel_event": cancel_event}

        resp = await worker._handle_browser_task(data)

        assert resp.success is False
        assert resp.error == "未指定任务"

    async def test_task_not_found(self):
        """TaskManager 返回 None → 返回浏览器任务不存在。"""
        from app.workers.playwright_worker import PlaywrightWorker

        worker = PlaywrightWorker()
        cancel_event = threading.Event()
        data = {
            "config": {"active_task": "nonexistent"},
            "cancel_event": cancel_event,
        }

        with patch("app.tasks.TaskManager") as MockTaskManager:
            mock_instance = MockTaskManager.return_value
            mock_instance.get_task_detail.return_value = None

            resp = await worker._handle_browser_task(data)

        assert resp.success is False
        assert resp.error == "浏览器任务不存在: nonexistent"

    async def test_wrong_task_type(self):
        """任务类型不是 browser → 返回浏览器任务不存在。"""
        from app.workers.playwright_worker import PlaywrightWorker

        worker = PlaywrightWorker()
        cancel_event = threading.Event()
        data = {
            "config": {"active_task": "script_task"},
            "cancel_event": cancel_event,
        }

        with patch("app.tasks.TaskManager") as MockTaskManager:
            mock_instance = MockTaskManager.return_value
            mock_instance.get_task_detail.return_value = {
                "id": "script_task",
                "type": "script",
            }

            resp = await worker._handle_browser_task(data)

        assert resp.success is False
        assert resp.error == "浏览器任务不存在: script_task"

    async def test_template_vars_built_from_runtime_config(self):
        """_handle_browser_task 应从 worker config 构建 template_vars 传入 BrowserTaskRunner。

        回归测试：原 template_vars=config.get("template_vars", {}) 永远为空 dict，
        因 runtime_config_to_worker_dict 不生成该字段，导致 {{USERNAME}} 等无法解析。
        """
        from app.workers.playwright_worker import PlaywrightWorker

        worker = PlaywrightWorker()
        cancel_event = threading.Event()
        data = {
            "config": {
                "active_task": "test_task",
                "auth_url": "http://auth.example.com",
                "username": "testuser",
                "password": "testpass",
                "isp": "@cmcc",
            },
            "cancel_event": cancel_event,
        }
        task_detail = {
            "id": "test_task",
            "type": "browser",
            "name": "测试任务",
            "url": "",
            "steps": [],
        }

        captured_runner = MagicMock()
        captured_runner.execute = AsyncMock(return_value=(True, "成功"))

        with (
            patch("app.tasks.TaskManager") as MockTaskManager,
            patch("app.tasks.BrowserTaskRunner") as MockRunner,
            patch.object(worker, "ensure_browser", new_callable=AsyncMock),
            patch.object(worker, "_close_browser", new_callable=AsyncMock),
        ):
            MockTaskManager.return_value.get_task_detail.return_value = task_detail
            MockRunner.return_value = captured_runner
            worker._page = MagicMock()
            worker._page.is_closed.return_value = False

            resp = await worker._handle_browser_task(data)

        assert resp.success is True
        # 验证 BrowserTaskRunner 构造时收到正确的 template_vars
        MockRunner.assert_called_once()
        _, kwargs = MockRunner.call_args
        template_vars = kwargs["template_vars"]
        assert template_vars["LOGIN_URL"] == "http://auth.example.com"
        assert template_vars["USERNAME"] == "testuser"
        assert template_vars["PASSWORD"] == "testpass"
        assert template_vars["ISP"] == "@cmcc"

# ── Task 2.3: PlaywrightWorker 显式实现 WorkerPort 协议 ──


class TestWorkerPortCompliance:
    """Task 2.3: PlaywrightWorker 显式实现 WorkerPort 协议。"""

    def test_playwright_worker_is_worker_port_instance(self):
        """PlaywrightWorker 实例是 WorkerPort 的 runtime_checkable 实例。"""
        from app.services.worker_port import WorkerPort
        from app.workers.playwright_worker import PlaywrightWorker

        worker = PlaywrightWorker()
        assert isinstance(worker, WorkerPort)

    def test_playwright_worker_inherits_worker_port(self):
        """PlaywrightWorker 显式继承 WorkerPort。"""
        from app.services.worker_port import WorkerPort
        from app.workers.playwright_worker import PlaywrightWorker

        # 显式继承（不仅是结构化子类型）
        assert issubclass(PlaywrightWorker, WorkerPort)

    def test_cmd_constants_single_source(self):
        """CMD_* 常量单一来源：playwright_worker 从 worker_port 导入。"""
        from app.services import worker_port as wp
        from app.workers import playwright_worker as pw

        # 所有 CMD_* 应是同一个对象（同一内存地址）
        for name in (
            "CMD_LOGIN",
            "CMD_BROWSER",
            "CMD_DEBUG_START",
            "CMD_DEBUG_STEP",
            "CMD_DEBUG_STOP",
            "CMD_SHUTDOWN",
        ):
            wp_const = getattr(wp, name)
            pw_const = getattr(pw, name)
            assert wp_const is pw_const, (
                f"{name} 应从 worker_port 导入（同一对象），实际是独立定义"
            )

    def test_worker_response_single_source(self):
        """WorkerResponse 单一来源：playwright_worker 从 worker_port 导入。"""
        from app.services.worker_port import WorkerResponse as WP_Response
        from app.workers.playwright_worker import WorkerResponse as PW_Response

        assert WP_Response is PW_Response, "WorkerResponse 应是同一个类对象"

    def test_worker_response_is_dataclass(self):
        """统一后的 WorkerResponse 应是 @dataclass（保持原 playwright_worker 行为）。"""
        import dataclasses

        from app.services.worker_port import WorkerResponse

        assert dataclasses.is_dataclass(WorkerResponse), (
            "WorkerResponse 应是 @dataclass 以保持 PlaywrightWorker 原有行为"
        )

    def test_worker_response_fields_preserved(self):
        """统一后的 WorkerResponse 保持原有字段：success/data/error。"""
        from app.services.worker_port import WorkerResponse

        resp = WorkerResponse(success=True, data="ok", error=None)
        assert resp.success is True
        assert resp.data == "ok"
        assert resp.error is None

        resp2 = WorkerResponse(success=False, error="失败")
        assert resp2.success is False
        assert resp2.data is None
        assert resp2.error == "失败"

    def test_submit_signature_matches_protocol(self):
        """submit 方法签名与 WorkerPort 协议一致：timeout 默认值为 None。"""
        import inspect

        from app.workers.playwright_worker import PlaywrightWorker

        sig = inspect.signature(PlaywrightWorker.submit)
        timeout_param = sig.parameters.get("timeout")
        assert timeout_param is not None
        assert timeout_param.default is None, (
            f"submit timeout 默认值应为 None（与 Protocol 一致），实际为 {timeout_param.default}"
        )

    def test_submit_default_timeout_uses_worker_submit_timeout(self):
        """submit 不传 timeout 时，内部使用 WORKER_SUBMIT_TIMEOUT（行为保持）。"""
        import app.workers.playwright_worker as pw

        # _DEFAULT_SUBMIT_TIMEOUT 别名常量应已移除，submit 内部直接使用 WORKER_SUBMIT_TIMEOUT
        assert not hasattr(pw, "_DEFAULT_SUBMIT_TIMEOUT"), (
            "_DEFAULT_SUBMIT_TIMEOUT 常量应已移除，submit 内部直接使用 WORKER_SUBMIT_TIMEOUT"
        )
