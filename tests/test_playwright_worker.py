"""PlaywrightWorker submit alive 预检测试"""

from __future__ import annotations

import threading
from unittest.mock import MagicMock, patch

from app.workers.playwright_worker import PlaywrightWorker


class TestSubmitAliveCheck:
    """submit() 方法的 worker alive 预检测试"""

    def test_submit_recovers_dead_worker(self):
        """测试 submit 检测到消费者线程死亡后自动重启"""
        worker = PlaywrightWorker()

        # 模拟 start() 方法，避免实际启动线程
        start_called = threading.Event()

        def mock_start():
            start_called.set()
            # 模拟线程启动成功
            worker._consumer_thread = MagicMock()
            worker._consumer_thread.is_alive.return_value = True
            worker._stop_event.clear()

        worker.start = mock_start

        # 模拟线程已死亡的状态
        worker._consumer_thread = MagicMock()
        worker._consumer_thread.is_alive.return_value = False
        worker._stop_event.clear()

        # 调用 submit，应该检测到线程死亡并重启
        result = worker.submit("test_cmd", wait=False)

        # 验证 start() 被调用
        assert start_called.is_set(), "submit 应该调用 start() 重启线程"
        # 验证 submit 成功（重启后命令入队）
        assert result.success

    def test_submit_normal_path_no_restart(self):
        """测试正常路径不触发重启"""
        worker = PlaywrightWorker()

        # 模拟线程正常运行
        worker._consumer_thread = MagicMock()
        worker._consumer_thread.is_alive.return_value = True
        worker._stop_event.clear()

        # 记录 start 是否被调用
        start_called = False

        def mock_start():
            nonlocal start_called
            start_called = True

        worker.start = mock_start

        # 模拟队列操作
        with patch.object(worker._cmd_queue, "put"), patch.object(worker, "_loop") as mock_loop:
            mock_loop.is_running.return_value = False
            worker.submit("test_cmd", wait=False)

        # 验证 start() 未被调用
        assert not start_called, "正常路径不应调用 start()"

    def test_submit_stopped_worker_rejects(self):
        """测试已停止的 worker 拒绝新命令"""
        worker = PlaywrightWorker()
        worker._stop_event.set()

        result = worker.submit("test_cmd", wait=False)

        assert not result.success
        assert "已关闭" in result.error

    def test_submit_restart_failure_returns_error(self):
        """测试重启失败时返回错误"""
        worker = PlaywrightWorker()

        # 模拟线程已死亡
        worker._consumer_thread = MagicMock()
        worker._consumer_thread.is_alive.return_value = False
        worker._stop_event.clear()

        # 模拟 start() 抛出异常
        def mock_start():
            raise RuntimeError("重启失败")

        worker.start = mock_start

        result = worker.submit("test_cmd", wait=False)

        assert not result.success
        assert "重启失败" in result.error

    def test_submit_concurrent_restart_only_one(self):
        """测试并发 submit 只有一个执行重启"""
        worker = PlaywrightWorker()

        # 模拟线程已死亡
        worker._consumer_thread = MagicMock()
        worker._consumer_thread.is_alive.return_value = False
        worker._stop_event.clear()

        restart_count = 0
        restart_lock = threading.Lock()

        def mock_start():
            nonlocal restart_count
            with restart_lock:
                restart_count += 1
            # 模拟重启后线程存活
            worker._consumer_thread.is_alive.return_value = True

        worker.start = mock_start

        # 并发调用 submit
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = []
            for _ in range(5):
                futures.append(
                    executor.submit(lambda: worker.submit("test_cmd", wait=False))
                )
            # 等待所有完成
            concurrent.futures.wait(futures)

        # 验证只重启了一次（有锁保护，严格等于 1）
        assert restart_count == 1, f"重启次数应为 1，实际: {restart_count}"
