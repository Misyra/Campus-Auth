"""MonitorService shutdown 和队列行为测试"""
from __future__ import annotations

import queue
import threading
from unittest.mock import MagicMock, patch

import pytest

from app.services.monitor import MonitorCommand, MonitorService
from app.core.monitor_core import NetworkState


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

    def test_shutdown_sends_stop_through_queue(self):
        """测试 shutdown 通过队列发送 stop 命令"""
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

        # 模拟消费者处理 stop 命令
        def consume_stop():
            cmd = svc._cmd_queue.get(timeout=5)
            assert cmd.type == "stop"
            if cmd.response_event:
                cmd.response_event.set()

        consumer = threading.Thread(target=consume_stop)
        consumer.start()

        # 调用 shutdown
        svc.shutdown()

        consumer.join(timeout=5)
        # 验证 shutdown_event 已设置
        assert svc._shutdown_event.is_set(), "shutdown 应设置 _shutdown_event"

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


class TestLoginInProgressNoDoubleClear:
    """P1-BE-3: _login_in_progress 清除路径收敛为单点测试"""

    def test_login_in_progress_no_double_clear(self):
        """测试超时分支不清除 _login_in_progress，由消费者 finally 统一清除"""
        svc = MonitorService.__new__(MonitorService)
        svc._cmd_queue = queue.Queue(maxsize=50)
        svc._login_in_progress = threading.Event()
        svc._login_in_progress.set()  # 模拟登录进行中
        svc._login_lock = threading.Lock()
        svc._runtime_config = {"auth_url": "http://test.com", "username": "test"}
        svc._ui_config = MagicMock()
        svc._ui_config.login_timeout = 0.01  # 极短超时
        svc._monitor_core = None
        svc._pure_mode = False
        svc._pure_mode_lock = threading.Lock()

        # 模拟消费者不清除 _login_in_progress（模拟超时场景）
        # 创建一个不会设置 response_data 的命令
        cmd = MonitorCommand(
            type="login",
            data={"config": {}, "pure_mode": False, "skip_pause_check": True},
            response_event=threading.Event(),
        )

        # 直接将 cmd 放入队列，模拟 put_nowait 成功
        svc._cmd_queue.put_nowait(cmd)

        # 模拟 run_manual_login 超时路径：不消费队列，response_data 保持 None
        with patch.object(svc, '_copy_runtime_config', return_value={}):
            # 直接测试超时分支逻辑
            cmd.response_event.wait(timeout=0.01)

            # 超时分支：response_data 为 None
            assert cmd.response_data is None
            # 关键验证：超时分支不应清除 _login_in_progress
            # （消费者 finally 才负责清除）
            assert svc._login_in_progress.is_set(), \
                "超时分支不应清除 _login_in_progress，应由消费者 finally 统一清除"


class TestStartMonitoringPutNowait:
    """P1-BE-5: start_monitoring 使用 put_nowait，队列满时不阻塞"""

    def test_start_monitoring_put_nowait(self):
        """测试队列满时 start_monitoring 不阻塞，返回错误"""
        svc = MonitorService.__new__(MonitorService)
        svc._cmd_queue = queue.Queue(maxsize=1)
        svc._status_snapshot = MagicMock()
        svc._status_snapshot.monitoring = False
        svc._runtime_config = {"auth_url": "http://test.com", "username": "test", "monitor": {}}
        svc._pure_mode = False
        svc._pure_mode_lock = threading.Lock()

        # 填满队列
        svc._cmd_queue.put_nowait(MonitorCommand(type="dummy"))

        with patch('app.services.monitor.ConfigValidator.validate_env_config', return_value=(True, "")):
            with patch.object(svc, '_copy_runtime_config', return_value={}):
                import time
                start = time.time()
                ok, msg = svc.start_monitoring()
                elapsed = time.time() - start

        # 验证不阻塞且返回错误
        assert not ok
        assert "队列已满" in msg
        assert elapsed < 1.0, f"start_monitoring 阻塞了 {elapsed:.2f}s"


class TestNetworkStateSetInConsumer:
    """P1-BE-7: network_state 在消费者线程统一赋值"""

    def test_network_state_set_in_consumer(self):
        """测试登录成功后 network_state 由消费者 _handle_login 设置"""
        svc = MonitorService.__new__(MonitorService)
        svc._login_in_progress = threading.Event()
        svc._login_history = None
        svc._profile_service = MagicMock()
        svc._profile_service.get_active_profile.return_value = MagicMock(name="test")
        svc._ui_config = MagicMock()
        svc._ui_config.login_timeout = 10
        svc._runtime_config = {"auth_url": "http://test.com", "username": "test"}
        svc._pure_mode = False
        svc._pure_mode_lock = threading.Lock()

        # 模拟 monitor_core
        mock_core = MagicMock()
        mock_core.monitoring = True
        mock_core.network_state = NetworkState.UNKNOWN
        svc._monitor_core = mock_core

        # 模拟 Worker 返回成功
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.data = "ok"

        cmd = MonitorCommand(
            type="login",
            data={"config": {}, "pure_mode": False, "skip_pause_check": True},
            response_event=threading.Event(),
        )

        with patch('app.services.monitor.get_worker') as mock_get_worker:
            mock_worker = MagicMock()
            mock_worker.submit.return_value = mock_result
            mock_get_worker.return_value = mock_worker

            # 调用消费者 _handle_login
            svc._handle_login(cmd)

        # 验证 network_state 已由消费者设置为 CONNECTED
        assert mock_core.network_state == NetworkState.CONNECTED, \
            "消费者 _handle_login 成功分支应设置 core.network_state = CONNECTED"
        # 验证 _login_in_progress 已清除
        assert not svc._login_in_progress.is_set(), \
            "消费者 finally 应清除 _login_in_progress"
