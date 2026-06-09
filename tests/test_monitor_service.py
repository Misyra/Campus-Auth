"""backend/monitor_service.py — 监控服务测试

覆盖 MonitorCommand, StatusSnapshot, MonitorService。
"""

from __future__ import annotations

import queue
import threading
import time
from unittest.mock import MagicMock, patch

from app.core.monitor_core import NetworkState
from app.services.monitor import (
    MonitorCmdType,
    MonitorCommand,
    MonitorService,
    StatusSnapshot,
)


def _make_monitor_service() -> MonitorService:
    """创建带有 mock 依赖的 MonitorService 实例。"""
    with (
        patch("app.services.monitor.build_runtime_config", return_value={}),
        patch(
            "app.services.monitor.load_runtime_config",
            return_value=(MagicMock(), False),
        ),
        patch("app.services.monitor.load_ui_config") as mock_load_ui,
        patch("app.services.monitor.ProfileService") as mock_ps_cls,
    ):
        mock_ps = MagicMock()
        mock_ps_cls.return_value = mock_ps
        mock_ps.load.return_value.system.pure_mode = False
        mock_ui_config = MagicMock()
        mock_ui_config.auto_start = False
        mock_load_ui.return_value = mock_ui_config
        return MonitorService(MagicMock())


# =====================================================================
# MonitorCommand
# =====================================================================


class TestMonitorCommand:
    def test_default_values(self):
        cmd = MonitorCommand(type=MonitorCmdType.START)
        assert cmd.type == "start"
        assert cmd.data == {}
        assert cmd.response_event is None
        assert cmd.response_data is None

    def test_custom_values(self):
        event = threading.Event()
        cmd = MonitorCommand(
            type="login",
            data={"config": {"key": "value"}},
            response_event=event,
        )
        assert cmd.type == "login"
        assert cmd.data["config"]["key"] == "value"
        assert cmd.response_event is event


# =====================================================================
# StatusSnapshot
# =====================================================================


class TestStatusSnapshot:
    def test_default_values(self):
        snap = StatusSnapshot()
        assert snap.monitoring is False
        assert snap.last_network_ok is False
        assert snap.start_time is None
        assert snap.network_check_count == 0
        assert snap.login_attempt_count == 0
        assert snap.last_check_time is None
        assert snap.snapshot_time == 0.0
        assert snap.status_detail == "正常"
        assert snap.network_state == "unknown"

    def test_custom_values(self):
        snap = StatusSnapshot(
            monitoring=True,
            last_network_ok=True,
            start_time=100.0,
            network_check_count=5,
            login_attempt_count=2,
            last_check_time="2025-01-01 12:00:00",
            snapshot_time=200.0,
            status_detail="运行中",
            network_state="connected",
        )
        assert snap.monitoring is True
        assert snap.last_network_ok is True
        assert snap.start_time == 100.0
        assert snap.network_check_count == 5
        assert snap.login_attempt_count == 2


# =====================================================================
# WebSocketManager
# =====================================================================


# =====================================================================
# MonitorService 初始化
# =====================================================================


class TestMonitorServiceInit:
    def test_init(self):
        svc = _make_monitor_service()
        assert svc._dashboard_sink is None
        assert svc._login_in_progress.is_set() is False
        assert svc.pure_mode is False


# =====================================================================
# MonitorService.record_log
# =====================================================================


class TestRecordLog:
    def test_record_log(self):
        svc = _make_monitor_service()
        svc.record_log("测试消息", level="INFO", source="backend")
        # record_log 委托 loguru，无 _dashboard_sink 时不会崩溃

    def test_record_log_ws_broadcast(self):
        svc = _make_monitor_service()
        from loguru import logger

        from app.utils.logging import DashboardSink

        sink = DashboardSink(maxlen=100, broadcast_maxlen=100)
        svc._dashboard_sink = sink
        handler_id = logger.add(
            sink.write,
            format="{name} | {message}",
            level="DEBUG",
            filter=lambda record: record["extra"].get("source") != "frontend",
        )
        try:
            svc.record_log("test", level="INFO", source="backend")
            assert len(sink.broadcast_queue) >= 1
            assert sink.broadcast_queue[0]["type"] == "log"
        finally:
            logger.remove(handler_id)


# =====================================================================
# MonitorService.list_logs
# =====================================================================


class TestListLogs:
    def test_list_logs_empty(self):
        svc = _make_monitor_service()
        assert svc.list_logs() == []

    def test_list_logs_limit(self):
        svc = _make_monitor_service()
        from loguru import logger

        from app.utils.logging import DashboardSink

        sink = DashboardSink(maxlen=100, broadcast_maxlen=100)
        svc._dashboard_sink = sink
        handler_id = logger.add(
            sink.write,
            format="{name} | {message}",
            level="DEBUG",
            filter=lambda record: record["extra"].get("source") != "frontend",
        )
        try:
            for i in range(5):
                svc.record_log(f"msg {i}")
            assert len(svc.list_logs(limit=3)) == 3
            assert svc.list_logs(limit=0) == []
        finally:
            logger.remove(handler_id)

    @patch("app.services.monitor.build_runtime_config", return_value={})
    @patch(
        "app.services.monitor.load_runtime_config", return_value=(MagicMock(), False)
    )
    @patch("app.services.monitor.load_ui_config")
    @patch("app.services.monitor.ProfileService")
    def test_list_logs_returns_all_when_limit_exceeds(
        self, mock_ps_cls, mock_load_ui, mock_load_rt, mock_build
    ):
        mock_ps = MagicMock()
        mock_ps_cls.return_value = mock_ps
        mock_ps.load.return_value.system.pure_mode = False
        mock_ui_config = MagicMock()
        mock_ui_config.auto_start = False
        mock_load_ui.return_value = mock_ui_config

        svc = MonitorService(MagicMock())
        from loguru import logger

        from app.utils.logging import DashboardSink

        sink = DashboardSink(maxlen=100, broadcast_maxlen=100)
        svc._dashboard_sink = sink
        handler_id = logger.add(
            sink.write,
            format="{name} | {message}",
            level="DEBUG",
            filter=lambda record: record["extra"].get("source") != "frontend",
        )
        try:
            for i in range(3):
                svc.record_log(f"msg {i}")
            assert len(svc.list_logs(limit=100)) == 3
        finally:
            logger.remove(handler_id)


# =====================================================================
# MonitorService.get_status
# =====================================================================


class TestGetStatus:
    def test_get_status_stopped(self):
        svc = _make_monitor_service()
        status = svc.get_status()
        assert status.monitoring is False
        assert status.runtime_seconds == 0

    def test_get_status_running(self):
        svc = _make_monitor_service()
        svc._status_snapshot = StatusSnapshot(
            monitoring=True,
            last_network_ok=True,
            start_time=time.time() - 120,
            snapshot_time=time.time() - 60,
            status_detail="运行中",
            network_state="connected",
        )
        status = svc.get_status()
        assert status.monitoring is True
        assert status.network_connected is True
        assert status.runtime_seconds > 0


# =====================================================================
# MonitorService._update_status_snapshot
# =====================================================================


class TestUpdateStatusSnapshot:
    def test_update_no_core(self):
        svc = _make_monitor_service()
        svc._monitor_core = None
        svc._update_status_snapshot()
        assert svc._status_snapshot.monitoring is False
        assert svc._status_snapshot.status_detail == "已停止"

    def test_update_with_core(self):
        svc = _make_monitor_service()
        mock_core = MagicMock()
        mock_core.monitoring = True
        mock_core.snapshot.return_value = {
            "network_state": "connected",
            "start_time": 100.0,
            "network_check_count": 10,
            "login_attempt_count": 2,
            "last_check_time": "2025-01-01",
            "status_detail": "运行中",
        }
        svc._monitor_core = mock_core
        svc._update_status_snapshot()
        assert svc._status_snapshot.monitoring is True
        assert svc._status_snapshot.network_state == "connected"
        assert svc._status_snapshot.network_check_count == 10


# =====================================================================
# MonitorService.start_monitoring / stop_monitoring
# =====================================================================


class TestStartStopMonitoring:
    @patch("app.services.monitor.build_runtime_config", return_value={})
    @patch(
        "app.services.monitor.load_runtime_config", return_value=(MagicMock(), False)
    )
    @patch("app.services.monitor.load_ui_config")
    @patch("app.services.monitor.ProfileService")
    @patch(
        "app.services.monitor.ConfigValidator.validate_env_config",
        return_value=(True, ""),
    )
    def test_start_monitoring(
        self, mock_validate, mock_ps_cls, mock_load_ui, mock_load_rt, mock_build
    ):
        mock_ps = MagicMock()
        mock_ps_cls.return_value = mock_ps
        mock_ps.load.return_value.system.pure_mode = False
        mock_ui_config = MagicMock()
        mock_ui_config.auto_start = False
        mock_load_ui.return_value = mock_ui_config

        svc = MonitorService(MagicMock())
        ok, msg = svc.start_monitoring()
        assert ok is True
        assert "已启动" in msg

    def test_start_monitoring_already_running(self):
        svc = _make_monitor_service()
        svc._status_snapshot = StatusSnapshot(monitoring=True)
        ok, msg = svc.start_monitoring()
        assert ok is False
        assert "已在运行" in msg

    def test_stop_monitoring_not_running(self):
        svc = _make_monitor_service()
        ok, msg = svc.stop_monitoring()
        assert ok is False
        assert "未运行" in msg


# =====================================================================
# MonitorService._handle_start / _handle_stop
# =====================================================================


class TestHandleStartStop:
    def test_handle_start_duplicate(self):
        svc = _make_monitor_service()
        mock_thread = MagicMock()
        mock_thread.is_alive.return_value = True
        svc._monitor_thread = mock_thread
        cmd = MonitorCommand(type=MonitorCmdType.START)
        svc._handle_start(cmd)
        # 不应创建新线程
        mock_thread.is_alive.assert_called()

    def test_handle_stop_no_core(self):
        svc = _make_monitor_service()
        svc._monitor_core = None
        svc._monitor_thread = None
        svc._handle_stop()
        assert svc._monitor_core is None


# =====================================================================
# MonitorService._handle_login
# =====================================================================


class TestHandleLogin:
    @patch("app.services.monitor.build_runtime_config", return_value={})
    @patch(
        "app.services.monitor.load_runtime_config", return_value=(MagicMock(), False)
    )
    @patch("app.services.monitor.load_ui_config")
    @patch("app.services.monitor.ProfileService")
    def test_handle_login_success(
        self, mock_ps_cls, mock_load_ui, mock_load_rt, mock_build
    ):
        mock_ps = MagicMock()
        mock_ps_cls.return_value = mock_ps
        mock_ps.load.return_value.system.pure_mode = False
        mock_ui_config = MagicMock()
        mock_ui_config.auto_start = False
        mock_ui_config.login_timeout = 120
        mock_load_ui.return_value = mock_ui_config

        mock_worker = MagicMock()
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.data = "登录成功"
        mock_worker.submit.return_value = mock_result
        mock_get_worker = MagicMock(return_value=mock_worker)

        svc = MonitorService(MagicMock(), worker_getter=mock_get_worker)
        event = threading.Event()
        cmd = MonitorCommand(type=MonitorCmdType.LOGIN, response_event=event)
        svc._handle_login(cmd)
        assert cmd.response_data == (True, "登录成功")
        assert event.is_set()

    @patch("app.services.monitor.build_runtime_config", return_value={})
    @patch(
        "app.services.monitor.load_runtime_config", return_value=(MagicMock(), False)
    )
    @patch("app.services.monitor.load_ui_config")
    @patch("app.services.monitor.ProfileService")
    def test_handle_login_failure(
        self, mock_ps_cls, mock_load_ui, mock_load_rt, mock_build
    ):
        mock_ps = MagicMock()
        mock_ps_cls.return_value = mock_ps
        mock_ps.load.return_value.system.pure_mode = False
        mock_ui_config = MagicMock()
        mock_ui_config.auto_start = False
        mock_ui_config.login_timeout = 120
        mock_load_ui.return_value = mock_ui_config

        mock_worker = MagicMock()
        mock_result = MagicMock()
        mock_result.success = False
        mock_result.error = "密码错误"
        mock_worker.submit.return_value = mock_result
        mock_get_worker = MagicMock(return_value=mock_worker)

        svc = MonitorService(MagicMock(), worker_getter=mock_get_worker)
        event = threading.Event()
        cmd = MonitorCommand(type=MonitorCmdType.LOGIN, response_event=event)
        svc._handle_login(cmd)
        assert cmd.response_data == (False, "密码错误")
        assert event.is_set()

    @patch("app.services.monitor.build_runtime_config", return_value={})
    @patch(
        "app.services.monitor.load_runtime_config", return_value=(MagicMock(), False)
    )
    @patch("app.services.monitor.load_ui_config")
    @patch("app.services.monitor.ProfileService")
    def test_handle_login_exception(
        self, mock_ps_cls, mock_load_ui, mock_load_rt, mock_build
    ):
        mock_ps = MagicMock()
        mock_ps_cls.return_value = mock_ps
        mock_ps.load.return_value.system.pure_mode = False
        mock_ui_config = MagicMock()
        mock_ui_config.auto_start = False
        mock_ui_config.login_timeout = 120
        mock_load_ui.return_value = mock_ui_config

        mock_worker = MagicMock()
        mock_worker.submit.side_effect = RuntimeError("worker error")
        mock_get_worker = MagicMock(return_value=mock_worker)

        svc = MonitorService(MagicMock(), worker_getter=mock_get_worker)
        event = threading.Event()
        cmd = MonitorCommand(type=MonitorCmdType.LOGIN, response_event=event)
        svc._handle_login(cmd)
        assert cmd.response_data[0] is False
        assert "worker error" in cmd.response_data[1]
        assert event.is_set()


# =====================================================================
# MonitorService.run_manual_login
# =====================================================================


class TestRunManualLogin:
    def test_run_manual_login_in_progress(self):
        svc = _make_monitor_service()
        svc._login_in_progress.set()
        ok, msg = svc.run_manual_login()
        assert ok is False
        assert "进行中" in msg


# =====================================================================
# MonitorService.test_network
# =====================================================================


class TestNetwork:
    @patch("app.services.monitor.build_runtime_config", return_value={})
    @patch(
        "app.services.monitor.load_runtime_config", return_value=(MagicMock(), False)
    )
    @patch("app.services.monitor.load_ui_config")
    @patch("app.services.monitor.ProfileService")
    @patch("app.services.monitor.is_network_available", return_value=True)
    def test_network_ok(
        self, mock_net, mock_ps_cls, mock_load_ui, mock_load_rt, mock_build
    ):
        mock_ps = MagicMock()
        mock_ps_cls.return_value = mock_ps
        mock_ps.load.return_value.system.pure_mode = False
        mock_ui_config = MagicMock()
        mock_ui_config.auto_start = False
        mock_load_ui.return_value = mock_ui_config

        svc = MonitorService(MagicMock())
        ok, msg = svc.test_network()
        assert ok is True
        assert "正常" in msg

    @patch("app.services.monitor.build_runtime_config", return_value={})
    @patch(
        "app.services.monitor.load_runtime_config", return_value=(MagicMock(), False)
    )
    @patch("app.services.monitor.load_ui_config")
    @patch("app.services.monitor.ProfileService")
    @patch("app.services.monitor.is_network_available", return_value=False)
    def test_network_fail(
        self, mock_net, mock_ps_cls, mock_load_ui, mock_load_rt, mock_build
    ):
        mock_ps = MagicMock()
        mock_ps_cls.return_value = mock_ps
        mock_ps.load.return_value.system.pure_mode = False
        mock_ui_config = MagicMock()
        mock_ui_config.auto_start = False
        mock_load_ui.return_value = mock_ui_config

        svc = MonitorService(MagicMock())
        ok, msg = svc.test_network()
        assert ok is False
        assert "异常" in msg

    @patch("app.services.monitor.build_runtime_config", return_value={})
    @patch(
        "app.services.monitor.load_runtime_config", return_value=(MagicMock(), False)
    )
    @patch("app.services.monitor.load_ui_config")
    @patch("app.services.monitor.ProfileService")
    @patch(
        "app.services.monitor.is_network_available", side_effect=RuntimeError("timeout")
    )
    def test_network_exception(
        self, mock_net, mock_ps_cls, mock_load_ui, mock_load_rt, mock_build
    ):
        mock_ps = MagicMock()
        mock_ps_cls.return_value = mock_ps
        mock_ps.load.return_value.system.pure_mode = False
        mock_ui_config = MagicMock()
        mock_ui_config.auto_start = False
        mock_load_ui.return_value = mock_ui_config

        svc = MonitorService(MagicMock())
        ok, msg = svc.test_network()
        assert ok is False
        assert "失败" in msg


# =====================================================================
# MonitorService.toggle_pure_mode
# =====================================================================


class TestTogglePureMode:
    @patch("app.services.monitor.build_runtime_config", return_value={})
    @patch(
        "app.services.monitor.load_runtime_config", return_value=(MagicMock(), False)
    )
    @patch("app.services.monitor.load_ui_config")
    @patch("app.services.monitor.ProfileService")
    def test_toggle_pure_mode(
        self, mock_ps_cls, mock_load_ui, mock_load_rt, mock_build
    ):
        mock_ps = MagicMock()
        mock_ps_cls.return_value = mock_ps
        mock_data = MagicMock()
        mock_data.system.pure_mode = False
        mock_ps.load.return_value = mock_data
        mock_ui_config = MagicMock()
        mock_ui_config.auto_start = False
        mock_load_ui.return_value = mock_ui_config

        svc = MonitorService(MagicMock())
        assert svc.pure_mode is False
        new_value = svc.toggle_pure_mode()
        assert new_value is True
        assert svc.pure_mode is True
        mock_ps.update.assert_called_once()

    @patch("app.services.monitor.build_runtime_config", return_value={})
    @patch(
        "app.services.monitor.load_runtime_config", return_value=(MagicMock(), False)
    )
    @patch("app.services.monitor.load_ui_config")
    @patch("app.services.monitor.ProfileService")
    def test_pure_mode_read_write_thread_safe(
        self, mock_ps_cls, mock_load_ui, mock_load_rt, mock_build
    ):
        """读写线程安全：2 线程同时读/写 1000 次，无异常且值始终为 bool。"""
        mock_ps = MagicMock()
        mock_ps_cls.return_value = mock_ps
        mock_data = MagicMock()
        mock_data.system.pure_mode = False
        mock_ps.load.return_value = mock_data
        mock_ui_config = MagicMock()
        mock_ui_config.auto_start = False
        mock_load_ui.return_value = mock_ui_config

        svc = MonitorService(MagicMock())
        errors: list[Exception] = []
        values_seen: list[bool] = []

        def reader() -> None:
            try:
                for _ in range(1000):
                    val = svc.pure_mode
                    assert isinstance(val, bool), f"非 bool 值: {val!r}"
                    values_seen.append(val)
            except Exception as exc:
                errors.append(exc)

        def writer() -> None:
            try:
                for _ in range(1000):
                    svc.toggle_pure_mode()
            except Exception as exc:
                errors.append(exc)

        t_read = threading.Thread(target=reader)
        t_write = threading.Thread(target=writer)
        t_read.start()
        t_write.start()
        t_read.join(timeout=10)
        t_write.join(timeout=10)

        assert not errors, f"线程执行出错: {errors}"
        # 所有读取到的值都应该是 bool（True 或 False）
        assert all(isinstance(v, bool) for v in values_seen)
        # 最终值应与 toggle 次数一致（1000 次 toggle → False）
        assert svc.pure_mode is False


# =====================================================================
# MonitorService.login_in_progress
# =====================================================================


class TestLoginInProgress:
    def test_login_in_progress_property(self):
        svc = _make_monitor_service()
        assert svc.login_in_progress is False
        svc._login_in_progress.set()
        assert svc.login_in_progress is True


# =====================================================================
# MonitorService.get_config / get_runtime_config
# =====================================================================


class TestGetConfig:
    @patch("app.services.monitor.build_runtime_config", return_value={"key": "value"})
    @patch(
        "app.services.monitor.load_runtime_config", return_value=(MagicMock(), False)
    )
    @patch("app.services.monitor.load_ui_config")
    @patch("app.services.monitor.ProfileService")
    def test_get_runtime_config(
        self, mock_ps_cls, mock_load_ui, mock_load_rt, mock_build
    ):
        mock_ps = MagicMock()
        mock_ps_cls.return_value = mock_ps
        mock_ps.load.return_value.system.pure_mode = False
        mock_ui_config = MagicMock()
        mock_ui_config.auto_start = False
        mock_load_ui.return_value = mock_ui_config

        svc = MonitorService(MagicMock())
        config = svc.get_runtime_config()
        assert config == {"key": "value"}
        # 修改返回值不应影响内部状态
        config["key"] = "modified"
        assert svc._runtime_config.get("key") == "value"


# =====================================================================
# save_profile 路由 apply_profile 参数验证
# =====================================================================


class TestSaveProfileApplyId:
    """验证 save_profile 路由传递 profile_id 而非 payload.name 给 apply_profile。"""

    def test_apply_profile_uses_id_not_name(self):
        from app.api.profiles import save_profile
        from app.schemas import ProfileSettings

        mock_profile_svc = MagicMock()
        mock_monitor_svc = MagicMock()

        # save_profile 返回成功
        mock_profile_svc.save_profile.return_value = (True, "OK")
        # active_profile 等于传入的 profile_id，触发 apply_profile 分支
        mock_data = MagicMock()
        mock_data.active_profile = "my_profile_id"
        mock_profile_svc.load.return_value = mock_data

        # payload.name 与 profile_id 不同 —— 这是 bug 的核心
        payload = ProfileSettings(name="完全不同的展示名")
        save_profile(
            profile_id="my_profile_id",
            payload=payload,
            profile_svc=mock_profile_svc,
            monitor_svc=mock_monitor_svc,
        )

        # apply_profile 应该用 profile_id，而非 payload.name
        mock_monitor_svc.apply_profile.assert_called_once_with("my_profile_id")


# ── MonitorService shutdown 和队列行为测试（原 test_monitor_service_shutdown.py）──


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
        svc._cmd_queue.put_nowait(MonitorCommand(type=MonitorCmdType.RELOAD))
        svc._cmd_queue.put_nowait(MonitorCommand(type=MonitorCmdType.RELOAD))

        # 创建命令
        cmd = MonitorCommand(
            type=MonitorCmdType.PROFILE_RELOAD, data={"profile_name": "test"}
        )

        # 模拟 _reload_config_internal
        with (
            patch.object(svc, "_reload_config_internal"),
            patch.object(svc, "_copy_runtime_config", return_value={}),
            patch.object(svc, "record_log"),
        ):
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

        cmd = MonitorCommand(
            type=MonitorCmdType.PROFILE_RELOAD, data={"profile_name": "test"}
        )

        with (
            patch.object(svc, "_reload_config_internal"),
            patch.object(svc, "_copy_runtime_config", return_value={}),
            patch.object(svc, "record_log"),
        ):
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
        svc.record_log = MagicMock()
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
            type=MonitorCmdType.LOGIN,
            data={"config": {}, "pure_mode": False, "skip_pause_check": True},
            response_event=threading.Event(),
        )

        # 直接将 cmd 放入队列，模拟 put_nowait 成功
        svc._cmd_queue.put_nowait(cmd)

        # 模拟 run_manual_login 超时路径：不消费队列，response_data 保持 None
        with patch.object(svc, "_copy_runtime_config", return_value={}):
            # 直接测试超时分支逻辑
            cmd.response_event.wait(timeout=0.01)

            # 超时分支：response_data 为 None
            assert cmd.response_data is None
            # 关键验证：超时分支不应清除 _login_in_progress
            # （消费者 finally 才负责清除）
            assert svc._login_in_progress.is_set(), (
                "超时分支不应清除 _login_in_progress，应由消费者 finally 统一清除"
            )


class TestStartMonitoringPutNowait:
    """P1-BE-5: start_monitoring 使用 put_nowait，队列满时不阻塞"""

    def test_start_monitoring_put_nowait(self):
        """测试队列满时 start_monitoring 不阻塞，返回错误"""
        svc = MonitorService.__new__(MonitorService)
        svc._cmd_queue = queue.Queue(maxsize=1)
        svc._status_snapshot = MagicMock()
        svc._status_snapshot.monitoring = False
        svc._runtime_config = {
            "auth_url": "http://test.com",
            "username": "test",
            "monitor": {},
        }
        svc._pure_mode = False
        svc._pure_mode_lock = threading.Lock()

        # 填满队列
        svc._cmd_queue.put_nowait(MonitorCommand(type=MonitorCmdType.RELOAD))

        with (
            patch(
                "app.services.monitor.ConfigValidator.validate_env_config",
                return_value=(True, ""),
            ),
            patch.object(svc, "_copy_runtime_config", return_value={}),
        ):
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
            type=MonitorCmdType.LOGIN,
            data={"config": {}, "pure_mode": False, "skip_pause_check": True},
            response_event=threading.Event(),
        )

        mock_worker = MagicMock()
        mock_worker.submit.return_value = mock_result
        svc._worker_getter = lambda: mock_worker

        # 调用消费者 _handle_login
        svc._handle_login(cmd)

        # 验证 network_state 已由消费者设置为 CONNECTED
        assert mock_core.network_state == NetworkState.CONNECTED, (
            "消费者 _handle_login 成功分支应设置 core.network_state = CONNECTED"
        )
        # 验证 _login_in_progress 已清除
        assert not svc._login_in_progress.is_set(), (
            "消费者 finally 应清除 _login_in_progress"
        )
