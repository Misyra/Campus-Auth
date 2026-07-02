"""Playwright Worker 测试。"""

from __future__ import annotations

import queue
import threading
from unittest.mock import MagicMock, patch

import psutil

from app.workers.playwright_worker import (
    _is_orphan,
    cleanup_orphan_browsers,
)

# ── _is_orphan ──


class TestIsOrphan:
    """孤儿进程判断。"""

    def test_parent_is_none(self):
        """父进程为 None → 孤儿。"""
        proc = MagicMock(spec=psutil.Process)
        proc.parent.return_value = None
        assert _is_orphan(proc) is True

    def test_parent_not_running(self):
        """父进程存在但已退出 → 孤儿。"""
        parent = MagicMock(spec=psutil.Process)
        parent.is_running.return_value = False
        proc = MagicMock(spec=psutil.Process)
        proc.parent.return_value = parent
        assert _is_orphan(proc) is True

    def test_parent_running(self):
        """父进程存活 → 非孤儿。"""
        parent = MagicMock(spec=psutil.Process)
        parent.is_running.return_value = True
        proc = MagicMock(spec=psutil.Process)
        proc.parent.return_value = parent
        assert _is_orphan(proc) is False

    def test_no_such_process(self):
        """进程已消失 → 孤儿（安全清理）。"""
        proc = MagicMock(spec=psutil.Process)
        proc.parent.side_effect = psutil.NoSuchProcess(123)
        assert _is_orphan(proc) is True


# ── cleanup_orphan_browsers ──


def _make_proc(pid, exe, cmdline):
    """构造 mock 进程对象。"""
    proc = MagicMock(spec=psutil.Process)
    proc.info = {"pid": pid, "exe": exe, "cmdline": cmdline}
    return proc


class TestCleanupOrphanBrowsers:
    """孤儿浏览器清理。"""

    def test_kills_orphan_playwright_browser(self):
        """Playwright 浏览器 + 父进程已死 → 被清理。"""
        proc = _make_proc(
            100,
            "C:\\ms-playwright\\chromium-123\\chrome.exe",
            ["chrome.exe", "--ms-playwright"],
        )

        with (
            patch("psutil.process_iter", return_value=[proc]),
            patch("app.workers.playwright_worker._is_orphan", return_value=True),
        ):
            cleanup_orphan_browsers()

        proc.kill.assert_called_once()

    def test_skips_alive_parent(self):
        """Playwright 浏览器 + 父进程存活 → 不清理。"""
        proc = _make_proc(
            100,
            "C:\\ms-playwright\\chromium-123\\chrome.exe",
            ["chrome.exe", "--ms-playwright"],
        )

        with (
            patch("psutil.process_iter", return_value=[proc]),
            patch("app.workers.playwright_worker._is_orphan", return_value=False),
        ):
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
        )
        proc.kill.side_effect = psutil.AccessDenied(400)

        with (
            patch("psutil.process_iter", return_value=[proc]),
            patch("app.workers.playwright_worker._is_orphan", return_value=True),
        ):
            cleanup_orphan_browsers()  # 不应抛异常

    def test_kills_multiple_orphans(self):
        """多个孤儿浏览器进程 → 全部清理。"""
        proc1 = _make_proc(
            101,
            "C:\\ms-playwright\\chromium-123\\chrome.exe",
            ["chrome.exe", "--ms-playwright"],
        )
        proc2 = _make_proc(
            102,
            "C:\\ms-playwright\\firefox-123\\firefox.exe",
            ["firefox.exe", "--ms-playwright"],
        )

        with (
            patch("psutil.process_iter", return_value=[proc1, proc2]),
            patch("app.workers.playwright_worker._is_orphan", return_value=True),
        ):
            cleanup_orphan_browsers()

        proc1.kill.assert_called_once()
        proc2.kill.assert_called_once()

    def test_skips_alive_parent_among_mix(self):
        """混合场景：一个孤儿 + 一个有父进程 → 只清理孤儿。"""
        orphan = _make_proc(
            101,
            "C:\\ms-playwright\\chromium-123\\chrome.exe",
            ["chrome.exe", "--ms-playwright"],
        )
        alive = _make_proc(
            102,
            "C:\\ms-playwright\\chromium-124\\chrome.exe",
            ["chrome.exe", "--ms-playwright"],
        )

        with (
            patch("psutil.process_iter", return_value=[orphan, alive]),
            patch("app.workers.playwright_worker._is_orphan") as mock_orphan,
        ):
            mock_orphan.side_effect = [True, False]
            cleanup_orphan_browsers()

        orphan.kill.assert_called_once()
        alive.kill.assert_not_called()


# ── stop() 队列满时仍 join 消费者线程 ──


class TestStopJoinsOnQueueFull:
    """stop() 在命令队列满时仍应等待消费者线程退出。"""

    def test_stop_joins_consumer_when_queue_full(self):
        """队列满 → put_nowait 抛 queue.Full → 仍调用 join 等待消费者线程。"""
        from app.workers.playwright_worker import PlaywrightWorker

        worker = PlaywrightWorker()

        # 构造一个伪消费者线程，join() 立即返回
        fake_thread = MagicMock(spec=threading.Thread)
        fake_thread.is_alive.return_value = False
        worker._consumer_thread = fake_thread

        # 构造伪事件循环，is_running → True
        fake_loop = MagicMock()
        fake_loop.is_running.return_value = True
        worker._loop = fake_loop

        # 让 put_nowait 抛 queue.Full
        with patch.object(
            worker._cmd_queue, "put_nowait", side_effect=queue.Full
        ):
            worker.stop(timeout=1)

        # 核心断言：join 必须被调用
        fake_thread.join.assert_called()

    def test_stop_reaches_join_even_when_loop_stop_called(self):
        """队列满 → loop.stop 被调用 → 仍走到 join 分支。"""
        from app.workers.playwright_worker import PlaywrightWorker

        worker = PlaywrightWorker()

        fake_thread = MagicMock(spec=threading.Thread)
        fake_thread.is_alive.return_value = False
        worker._consumer_thread = fake_thread

        fake_loop = MagicMock()
        fake_loop.is_running.return_value = True
        worker._loop = fake_loop

        with patch.object(
            worker._cmd_queue, "put_nowait", side_effect=queue.Full
        ):
            worker.stop(timeout=2)

        # loop.stop 被调用（queue.Full 分支）
        fake_loop.call_soon_threadsafe.assert_any_call(fake_loop.stop)
        # 但 join 仍然被调用
        fake_thread.join.assert_called()

    def test_stop_joins_when_loop_not_running(self):
        """队列满 + 事件循环未运行 → 不调用 loop.stop → 仍 join。"""
        from app.workers.playwright_worker import PlaywrightWorker

        worker = PlaywrightWorker()

        fake_thread = MagicMock(spec=threading.Thread)
        fake_thread.is_alive.return_value = False
        worker._consumer_thread = fake_thread

        fake_loop = MagicMock()
        fake_loop.is_running.return_value = False
        worker._loop = fake_loop

        with patch.object(
            worker._cmd_queue, "put_nowait", side_effect=queue.Full
        ):
            worker.stop(timeout=1)

        # queue.Full 分支中 loop.stop 不应被直接调用（循环未运行）
        for c in fake_loop.call_soon_threadsafe.call_args_list:
            assert c.args[0] is not fake_loop.stop, (
                "queue.Full 分支不应在循环未运行时调用 loop.stop"
            )
        # join 仍被调用
        fake_thread.join.assert_called()

    def test_stop_joins_when_loop_is_none(self):
        """队列满 + 无事件循环 → 仍 join。"""
        from app.workers.playwright_worker import PlaywrightWorker

        worker = PlaywrightWorker()

        fake_thread = MagicMock(spec=threading.Thread)
        fake_thread.is_alive.return_value = False
        worker._consumer_thread = fake_thread
        worker._loop = None

        with patch.object(
            worker._cmd_queue, "put_nowait", side_effect=queue.Full
        ):
            worker.stop(timeout=1)

        # join 仍被调用
        fake_thread.join.assert_called()

    def test_stop_logs_warning_on_queue_full(self):
        """队列满时记录 warning 日志。"""
        from app.workers.playwright_worker import PlaywrightWorker

        worker = PlaywrightWorker()

        fake_thread = MagicMock(spec=threading.Thread)
        fake_thread.is_alive.return_value = False
        worker._consumer_thread = fake_thread

        fake_loop = MagicMock()
        fake_loop.is_running.return_value = True
        worker._loop = fake_loop

        with (
            patch.object(
                worker._cmd_queue, "put_nowait", side_effect=queue.Full
            ),
            patch("app.workers.playwright_worker.logger") as mock_logger,
        ):
            worker.stop(timeout=1)

        mock_logger.warning.assert_any_call("Worker 命令队列已满，强制停止事件循环")


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
