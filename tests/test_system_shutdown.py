"""系统关机路由测试"""
from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from backend.routers.system import router


class TestShutdownUsesExit:
    """shutdown 使用 asyncio.run_coroutine_threadsafe + os._exit"""

    def test_shutdown_uses_exit_not_sigterm(self):
        """验证 _do_shutdown 使用 os._exit(0) 而非 os.kill(SIGTERM)"""
        mock_monitor = MagicMock()
        mock_monitor.stop_monitoring.return_value = (True, "监控已停止")

        done_event = threading.Event()
        mock_loop = MagicMock()

        mock_app = MagicMock()
        with patch('os._exit') as mock_exit, \
             patch('asyncio.get_event_loop', return_value=mock_loop), \
             patch('backend.main.app', mock_app), \
             patch('src.playwright_worker.get_worker') as mock_get_worker, \
             patch('src.playwright_worker.cleanup_orphan_browsers'), \
             patch('logging.shutdown'):

            mock_worker = MagicMock()
            mock_get_worker.return_value = mock_worker

            mock_exit.side_effect = lambda code: done_event.set()

            from backend.routers.system import shutdown_server
            shutdown_server(svc=mock_monitor)

            done_event.wait(timeout=5)

        # 验证 os._exit(0) 被调用
        mock_exit.assert_called_once_with(0)

    def test_shutdown_cleanup_functions_called(self):
        """测试 shutdown 调用清理函数"""
        mock_monitor = MagicMock()
        mock_monitor.stop_monitoring.return_value = (True, "监控已停止")

        done_event = threading.Event()
        mock_loop = MagicMock()

        mock_app = MagicMock()
        with patch('os._exit'), \
             patch('asyncio.get_event_loop', return_value=mock_loop), \
             patch('backend.main.app', mock_app), \
             patch('src.playwright_worker.get_worker') as mock_get_worker, \
             patch('src.playwright_worker.cleanup_orphan_browsers') as mock_cleanup, \
             patch('logging.shutdown'):

            mock_worker = MagicMock()
            mock_get_worker.return_value = mock_worker

            from backend.routers.system import shutdown_server
            shutdown_server(svc=mock_monitor)

            # daemon thread 中 os._exit 被 mock，不会真正退出，等待一小段时间
            import time
            time.sleep(0.5)

        # 验证清理函数被调用
        mock_monitor.stop_monitoring.assert_called_once()
        mock_worker.stop.assert_called_once()
        mock_cleanup.assert_called_once()
