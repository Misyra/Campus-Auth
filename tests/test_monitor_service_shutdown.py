"""MonitorService shutdown 和队列行为测试"""
from __future__ import annotations

import queue
import threading
from unittest.mock import MagicMock, patch

import pytest

from backend.monitor_service import MonitorCommand, MonitorService


class TestProfileReloadNoDeadlock:
    """_handle_profile_reload 队列满时不阻塞测试"""

    def test_profile_reload_no_self_deadlock(self):
        """测试队列满时 _handle_profile_reload 不会阻塞"""
        # 创建 MonitorService 实例
        svc = MonitorService.__new__(MonitorService)
        svc._cmd_queue = queue.Queue(maxsize=2)  # 小队列便于测试
        svc._runtime_config = {"auth_url": "http://test.com", "username": "test"}
        svc._monitor_core = MagicMock()
        svc._monitor_core.monitoring = True

        # 填满队列
        svc._cmd_queue.put_nowait(MonitorCommand(type="dummy1"))
        svc._cmd_queue.put_nowait(MonitorCommand(type="dummy2"))

        # 创建命令
        cmd = MonitorCommand(type="profile_reload", data={"profile_name": "test"})

        # 模拟 _reload_config_internal
        with patch.object(svc, '_reload_config_internal'):
            with patch.object(svc, '_copy_runtime_config', return_value={}):
                with patch.object(svc, '_push_log'):
                    # 调用 _handle_profile_reload，应该不阻塞
                    import time
                    start = time.time()
                    svc._handle_profile_reload(cmd)
                    elapsed = time.time() - start

        # 验证方法在 1 秒内返回（不阻塞）
        assert elapsed < 1.0, f"_handle_profile_reload 阻塞了 {elapsed:.2f}s"

    def test_profile_reload_queue_not_full(self):
        """测试队列未满时正常入队"""
        svc = MonitorService.__new__(MonitorService)
        svc._cmd_queue = queue.Queue(maxsize=50)
        svc._runtime_config = {"auth_url": "http://test.com", "username": "test"}
        svc._monitor_core = MagicMock()
        svc._monitor_core.monitoring = True

        cmd = MonitorCommand(type="profile_reload", data={"profile_name": "test"})

        with patch.object(svc, '_reload_config_internal'):
            with patch.object(svc, '_copy_runtime_config', return_value={}):
                with patch.object(svc, '_push_log'):
                    svc._handle_profile_reload(cmd)

        # 验证 reload 命令已入队
        assert svc._cmd_queue.qsize() == 1
        queued_cmd = svc._cmd_queue.get_nowait()
        assert queued_cmd.type == "reload"


class TestShutdownSynchronous:
    """shutdown 同步等待测试"""

    def test_shutdown_calls_handle_stop_synchronously(self):
        """测试 shutdown 直接同步调用 _handle_stop"""
        svc = MonitorService.__new__(MonitorService)
        svc._cmd_queue = queue.Queue(maxsize=50)
        svc._shutdown_event = threading.Event()
        svc._status_snapshot = MagicMock()
        svc._status_snapshot.monitoring = True
        svc._monitor_core = MagicMock()
        svc._monitor_thread = MagicMock()
        svc._monitor_thread.is_alive.return_value = False
        svc._thread_done = threading.Event()
        svc._consumer_thread = MagicMock()
        svc._consumer_thread.is_alive.return_value = False

        # 记录 _handle_stop 是否被调用
        handle_stop_called = threading.Event()

        def mock_handle_stop():
            handle_stop_called.set()

        svc._handle_stop = mock_handle_stop

        # 调用 shutdown
        svc.shutdown()

        # 验证 _handle_stop 被调用
        assert handle_stop_called.is_set(), "shutdown 应该调用 _handle_stop"

    def test_handle_stop_idempotent(self):
        """测试 _handle_stop 幂等性"""
        svc = MonitorService.__new__(MonitorService)
        svc._monitor_core = None
        svc._monitor_thread = None
        svc._thread_done = threading.Event()
        svc._push_log = MagicMock()
        svc._update_status_snapshot = MagicMock()

        # 多次调用不应抛出异常
        svc._handle_stop()
        svc._handle_stop()
        svc._handle_stop()
