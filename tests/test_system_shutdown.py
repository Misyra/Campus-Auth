"""系统关机路由测试"""
from __future__ import annotations

import signal
import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from backend.routers.system import router


class TestShutdownUsesSigterm:
    """shutdown 使用 SIGTERM 而非 os._exit"""

    def test_shutdown_uses_sigterm_not_exit(self):
        """验证 _do_shutdown 使用 os.kill(SIGTERM) 而非 os._exit"""
        # _do_shutdown 在 daemon thread 中运行，patch 的上下文退出后真实 os.kill 会杀进程
        # 因此改用「抢占 patch + 事件同步」策略：让 daemon thread 用 mock，主线程等它跑完
        mock_monitor = MagicMock()
        mock_monitor.stop_monitoring.return_value = (True, "监控已停止")

        done_event = threading.Event()

        with patch('os.kill') as mock_kill, \
             patch('os._exit') as mock_exit, \
             patch('src.playwright_worker.get_worker') as mock_get_worker, \
             patch('src.playwright_worker.cleanup_orphan_browsers'), \
             patch('logging.shutdown'):

            mock_worker = MagicMock()
            mock_get_worker.return_value = mock_worker

            # 用 side_effect 让 mock os.kill 设置完成事件
            def kill_side_effect(pid, sig):
                done_event.set()

            mock_kill.side_effect = kill_side_effect

            from backend.routers.system import shutdown_server
            shutdown_server(svc=mock_monitor)

            # 等待 daemon thread 完成（最多 5 秒）
            done_event.wait(timeout=5)

        # 验证 os._exit 未被调用
        mock_exit.assert_not_called()
        # 验证 os.kill 被调用且参数正确
        mock_kill.assert_called_once_with(
            __import__('os').getpid(), signal.SIGTERM
        )

    def test_shutdown_cleanup_functions_called(self):
        """测试 shutdown 调用清理函数"""
        mock_monitor = MagicMock()
        mock_monitor.stop_monitoring.return_value = (True, "监控已停止")

        done_event = threading.Event()

        with patch('os.kill') as mock_kill, \
             patch('os._exit'), \
             patch('src.playwright_worker.get_worker') as mock_get_worker, \
             patch('src.playwright_worker.cleanup_orphan_browsers') as mock_cleanup, \
             patch('logging.shutdown'):

            mock_worker = MagicMock()
            mock_get_worker.return_value = mock_worker
            mock_kill.side_effect = lambda pid, sig: done_event.set()

            from backend.routers.system import shutdown_server
            shutdown_server(svc=mock_monitor)

            done_event.wait(timeout=5)

        # 验证清理函数被调用
        mock_monitor.stop_monitoring.assert_called_once()
        mock_worker.stop.assert_called_once()
        mock_cleanup.assert_called_once()
