"""backend/monitor_service.py — 监控服务测试

覆盖 EngineCommand, StatusSnapshot, ScheduleEngine。
"""

from __future__ import annotations

import queue
import threading
import time
from concurrent.futures import Future
from unittest.mock import MagicMock, patch

from app.schemas import LoginCredentials, RuntimeConfig
from app.services.engine import (
    EngineCmdType,
    EngineCommand,
    ScheduleEngine,
)
from app.services.engine_status import StatusSnapshot


def _fake_reload():
    """模拟 _reload_config_internal 的返回值。__init__ 已初始化 _runtime_config。"""
    return True



# =====================================================================
# EngineCommand
# =====================================================================


class TestEngineCommand:
    def test_default_values(self):
        cmd = EngineCommand(type=EngineCmdType.START)
        assert cmd.type == "start"
        assert cmd.data == {}
        assert cmd.response_event is None
        assert cmd.response_data is None

    def test_custom_values(self):
        event = threading.Event()
        cmd = EngineCommand(
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
# ScheduleEngine 初始化
# =====================================================================


class TestScheduleEngineInit:
    def test_init(self, engine_factory):
        svc = engine_factory()
        assert svc._status_manager._dashboard_sink is None
        assert svc.pure_mode is False


# =====================================================================
# ScheduleEngine.record_log
# =====================================================================


class TestRecordLog:
    def test_record_log(self, engine_factory):
        svc = engine_factory()
        svc.record_log("测试消息", level="INFO", source="backend")
        # record_log 委托 loguru，无 _dashboard_sink 时不会崩溃

    def test_record_log_ws_broadcast(self, engine_factory):
        svc = engine_factory()
        from loguru import logger

        from app.utils.logging import DashboardSink

        sink = DashboardSink(maxlen=100, broadcast_maxlen=100)
        svc._status_manager._dashboard_sink = sink
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
# ScheduleEngine.list_logs
# =====================================================================


class TestListLogs:
    def test_list_logs_empty(self, engine_factory):
        svc = engine_factory()
        assert svc.list_logs() == []

    def test_list_logs_limit(self, engine_factory):
        svc = engine_factory()
        from loguru import logger

        from app.utils.logging import DashboardSink

        sink = DashboardSink(maxlen=100, broadcast_maxlen=100)
        svc._status_manager._dashboard_sink = sink
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

    @patch.object(ScheduleEngine, "_reload_config_internal", side_effect=_fake_reload)
    @patch("app.services.engine.ProfileService")
    def test_list_logs_returns_all_when_limit_exceeds(
        self, mock_ps_cls, mock_reload
    ):
        mock_ps = MagicMock()
        mock_ps_cls.return_value = mock_ps
        mock_ps.load.return_value.global_config.browser.pure_mode = False

        svc = ScheduleEngine(MagicMock(), profile_service=MagicMock())
        from loguru import logger

        from app.utils.logging import DashboardSink

        sink = DashboardSink(maxlen=100, broadcast_maxlen=100)
        svc._status_manager._dashboard_sink = sink
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
# ScheduleEngine.get_status
# =====================================================================


class TestGetStatus:
    def test_get_status_stopped(self, engine_factory):
        svc = engine_factory()
        status = svc.get_status()
        assert status.monitoring is False
        assert status.runtime_seconds == 0

    def test_get_status_running(self, engine_factory):
        svc = engine_factory()
        svc._status_manager._status_snapshot = StatusSnapshot(
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
# ScheduleEngine._update_status_snapshot
# =====================================================================


class TestUpdateStatusSnapshot:
    def test_update_no_core(self, engine_factory):
        svc = engine_factory()
        svc._monitor_core = None
        svc._update_status_snapshot()
        assert svc._status_manager._status_snapshot.monitoring is False
        assert svc._status_manager._status_snapshot.status_detail == "已停止"

    def test_update_with_core(self, engine_factory):
        svc = engine_factory()
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
        assert svc._status_manager._status_snapshot.monitoring is True
        assert svc._status_manager._status_snapshot.network_state == "connected"
        assert svc._status_manager._status_snapshot.network_check_count == 10


# =====================================================================
# ScheduleEngine.start_monitoring / stop_monitoring
# =====================================================================


class TestStartStopMonitoring:
    @patch.object(ScheduleEngine, "_reload_config_internal", side_effect=_fake_reload)
    @patch("app.services.engine.ProfileService")
    @patch(
        "app.services.engine.ConfigValidator.validate_env_config",
        return_value=(True, ""),
    )
    def test_start_monitoring(
        self, mock_validate, mock_ps_cls, mock_reload
    ):
        mock_ps = MagicMock()
        mock_ps_cls.return_value = mock_ps
        mock_ps.load.return_value.global_config.browser.pure_mode = False

        svc = ScheduleEngine(MagicMock(), profile_service=MagicMock())
        ok, msg = svc.start_monitoring()
        assert ok is True
        assert "已启动" in msg

    def test_start_monitoring_already_running(self, engine_factory):
        svc = engine_factory()
        mock_core = MagicMock()
        mock_core.monitoring = True
        mock_core.snapshot.return_value = {
            "network_state": "connected",
            "start_time": 100.0,
            "network_check_count": 0,
            "login_attempt_count": 0,
            "last_check_time": None,
            "status_detail": "运行中",
        }
        svc._monitor_core = mock_core
        ok, msg = svc.start_monitoring()
        assert ok is False
        assert "已在运行" in msg

    def test_stop_monitoring_not_running(self, engine_factory):
        svc = engine_factory()
        ok, msg = svc.stop_monitoring()
        assert ok is False
        assert "未运行" in msg


# =====================================================================
# ScheduleEngine._handle_start / _handle_stop
# =====================================================================


class TestHandleStartStop:
    def test_handle_start_duplicate(self, engine_factory):
        svc = engine_factory()
        mock_core = MagicMock()
        mock_core.monitoring = True
        svc._monitor_core = mock_core
        cmd = EngineCommand(type=EngineCmdType.START)
        svc._handle_start(cmd)
        # 不应创建新监控核心
        assert svc._monitor_core is mock_core

    def test_handle_stop_no_core(self, engine_factory):
        svc = engine_factory()
        svc._monitor_core = None
        svc._handle_stop()
        assert svc._monitor_core is None


# =====================================================================
# ScheduleEngine._handle_login
# =====================================================================


class TestHandleLogin:
    @patch.object(ScheduleEngine, "_reload_config_internal", side_effect=_fake_reload)
    @patch("app.services.engine.ProfileService")
    def test_handle_login_submits_async(
        self, mock_ps_cls, mock_reload
    ):
        """_handle_login 有配置时提交登录并等待完成返回结果。"""
        mock_ps = MagicMock()
        mock_ps_cls.return_value = mock_ps
        mock_ps.load.return_value.global_config.browser.pure_mode = False

        mock_worker = MagicMock()
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.data = "登录成功"
        mock_worker.submit.return_value = mock_result
        mock_get_worker = MagicMock(return_value=mock_worker)

        mock_task_executor = MagicMock()
        future = Future()
        future.set_result((True, "登录成功"))
        mock_task_executor.execute_login_async.return_value = future

        svc = ScheduleEngine(
            MagicMock(), profile_service=MagicMock(), worker_getter=mock_get_worker, task_executor=mock_task_executor
        )
        svc._shutdown_event.set()  # 停止引擎线程，避免干扰
        time.sleep(0.1)

        # 注入 orchestrator mock
        svc._orchestrator = MagicMock()
        svc._orchestrator.validate.return_value = None
        handle = MagicMock()
        handle.rejected_reason = None
        mock_future = Future()
        handle.future = mock_future
        svc._orchestrator.submit.return_value = handle

        # 提供有效配置，否则 _handle_login 会拒绝
        svc._runtime_config = RuntimeConfig(
            credentials=LoginCredentials(
                username="test", password="test", auth_url="http://test.com",
            ),
        )
        cmd = EngineCommand(type=EngineCmdType.LOGIN, response_event=threading.Event())
        svc._handle_login(cmd)
        # 异步模式：模拟登录完成，触发回调
        mock_future.set_result((True, "登录成功"))
        cmd.response_event.wait(timeout=2)
        assert cmd.response_data == (True, "登录成功")

    def test_handle_login_no_config_returns_false(self):
        """_handle_login 无配置时返回 False。"""
        svc = ScheduleEngine.__new__(ScheduleEngine)
        svc._update_status_snapshot = MagicMock()
        svc._task_executor = MagicMock()
        svc._orchestrator = MagicMock()
        svc._orchestrator.validate.return_value = "登录配置不完整（请先设置认证地址、用户名和密码）"
        # 返回空配置
        svc._runtime_config = RuntimeConfig()

        cmd = EngineCommand(type=EngineCmdType.LOGIN, response_event=threading.Event())
        svc._handle_login(cmd)

        success, message = cmd.response_data
        assert success is False
        assert "配置不完整" in message


# =====================================================================
# ScheduleEngine.run_manual_login
# =====================================================================


class TestRunManualLogin:
    def test_run_manual_login_in_progress(self, engine_factory):
        svc = engine_factory()
        svc._manual_login_in_progress = True
        ok, msg = svc.run_manual_login()
        assert ok is False
        assert "进行中" in msg


# =====================================================================
# ScheduleEngine.test_network
# =====================================================================


class TestNetwork:
    @patch.object(ScheduleEngine, "_reload_config_internal", side_effect=_fake_reload)
    @patch("app.services.engine.ProfileService")
    def test_network_ok(
        self, mock_ps_cls, mock_reload
    ):
        mock_ps = MagicMock()
        mock_ps_cls.return_value = mock_ps
        mock_ps.load.return_value.global_config.browser.pure_mode = False

        mock_tester = MagicMock()
        mock_tester.test_network.return_value = (True, "网络连接正常")
        svc = ScheduleEngine(MagicMock(), profile_service=MagicMock(), network_tester=mock_tester)
        ok, msg = svc.test_network()
        assert ok is True
        assert "正常" in msg

    @patch.object(ScheduleEngine, "_reload_config_internal", side_effect=_fake_reload)
    @patch("app.services.engine.ProfileService")
    def test_network_fail(
        self, mock_ps_cls, mock_reload
    ):
        mock_ps = MagicMock()
        mock_ps_cls.return_value = mock_ps
        mock_ps.load.return_value.global_config.browser.pure_mode = False

        mock_tester = MagicMock()
        mock_tester.test_network.return_value = (False, "网络连接异常")
        svc = ScheduleEngine(MagicMock(), profile_service=MagicMock(), network_tester=mock_tester)
        ok, msg = svc.test_network()
        assert ok is False
        assert "异常" in msg

    @patch.object(ScheduleEngine, "_reload_config_internal", side_effect=_fake_reload)
    @patch("app.services.engine.ProfileService")
    def test_network_exception(
        self, mock_ps_cls, mock_reload
    ):
        mock_ps = MagicMock()
        mock_ps_cls.return_value = mock_ps
        mock_ps.load.return_value.global_config.browser.pure_mode = False

        mock_tester = MagicMock()
        mock_tester.test_network.return_value = (False, "网络测试失败: timeout")
        svc = ScheduleEngine(MagicMock(), profile_service=MagicMock(), network_tester=mock_tester)
        ok, msg = svc.test_network()
        assert ok is False
        assert "失败" in msg


# =====================================================================
# ScheduleEngine.toggle_pure_mode
# =====================================================================


class TestTogglePureMode:
    @patch("app.services.engine.ProfileService")
    def test_toggle_pure_mode(
        self, mock_ps_cls
    ):
        mock_ps = MagicMock()
        mock_ps_cls.return_value = mock_ps
        mock_data = MagicMock()
        mock_data.global_config.browser.pure_mode = False
        mock_ps.load.return_value = mock_data

        def _fake_reload(self_inner):
            self_inner._runtime_config = RuntimeConfig()
            self_inner._runtime_snapshot = self_inner._runtime_config
            self_inner._pure_mode = False
            return True

        with patch.object(ScheduleEngine, "_reload_config_internal", _fake_reload):
            svc = ScheduleEngine(MagicMock(), profile_service=mock_ps)
        assert svc.pure_mode is False
        new_value = svc.toggle_pure_mode()
        assert new_value is True
        assert svc.pure_mode is True
        mock_ps.update.assert_called_once()

    @patch("app.services.engine.ProfileService")
    def test_pure_mode_read_write_thread_safe(
        self, mock_ps_cls
    ):
        """读写线程安全：2 线程同时读/写 1000 次，无异常且值始终为 bool。"""
        mock_ps = MagicMock()
        mock_ps_cls.return_value = mock_ps
        mock_data = MagicMock()
        mock_data.global_config.browser.pure_mode = False
        mock_ps.load.return_value = mock_data

        def _fake_reload(self_inner):
            self_inner._runtime_config = RuntimeConfig()
            self_inner._runtime_snapshot = self_inner._runtime_config
            self_inner._pure_mode = False
            return True

        with patch.object(ScheduleEngine, "_reload_config_internal", _fake_reload):
            svc = ScheduleEngine(MagicMock(), profile_service=MagicMock())
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
# ScheduleEngine.login_in_progress
# =====================================================================


class TestLoginInProgress:
    def test_login_in_progress_property(self, engine_factory):
        svc = engine_factory()
        svc._task_executor.is_login_running.return_value = False
        assert svc.login_in_progress is False


# =====================================================================
# ScheduleEngine.get_config / get_runtime_config
# =====================================================================


class TestGetConfig:
    @patch.object(ScheduleEngine, "_reload_config_internal", side_effect=_fake_reload)
    @patch("app.services.engine.ProfileService")
    def test_get_runtime_config(
        self, mock_ps_cls, mock_reload
    ):
        mock_ps = MagicMock()
        mock_ps_cls.return_value = mock_ps
        mock_ps.load.return_value.global_config.browser.pure_mode = False

        svc = ScheduleEngine(MagicMock(), profile_service=MagicMock())
        config = svc.get_runtime_config()
        assert isinstance(config, RuntimeConfig)
        assert config is svc._runtime_config  # frozen 对象，直接返回引用


# =====================================================================
# save_profile 路由 apply_profile 参数验证
# =====================================================================


class TestSaveProfileApplyId:
    """验证 save_profile 路由传递 profile_id 而非 payload.name 给 apply_profile。"""

    def test_apply_profile_uses_id_not_name(self):
        from app.api.profiles import save_profile
        from app.schemas import Profile

        mock_profile_svc = MagicMock()
        mock_monitor_svc = MagicMock()

        # save_profile 返回成功
        mock_profile_svc.save_profile.return_value = (True, "OK")
        # active_profile 等于传入的 profile_id，触发 apply_profile 分支
        mock_data = MagicMock()
        mock_data.active_profile = "my_profile_id"
        mock_profile_svc.load.return_value = mock_data

        # payload.name 与 profile_id 不同 —— 这是 bug 的核心
        payload = Profile(name="完全不同的展示名")
        save_profile(
            profile_id="my_profile_id",
            payload=payload,
            profile_svc=mock_profile_svc,
            monitor_svc=mock_monitor_svc,
        )

        # apply_profile 应该用 profile_id，而非 payload.name
        mock_monitor_svc.apply_profile.assert_called_once_with("my_profile_id")


# ── ScheduleEngine shutdown 和队列行为测试（原 test_monitor_service_shutdown.py）──


class TestShutdownSynchronous:
    """shutdown 同步等待测试"""

    def test_shutdown_sends_stop_through_queue(self):
        """测试 shutdown 通过队列发送 stop 命令"""
        svc = ScheduleEngine.__new__(ScheduleEngine)
        svc._cmd_queue = queue.Queue(maxsize=50)
        svc._wakeup_event = threading.Event()
        svc._shutdown_event = threading.Event()
        svc._monitor_core = MagicMock()
        svc._monitor_thread = MagicMock()
        svc._monitor_thread.is_alive.return_value = False
        svc._thread_done = threading.Event()
        svc._engine_thread = MagicMock()
        svc._engine_thread.is_alive.return_value = False
        svc._scheduler_running = False
        svc._running_task_threads = []
        svc._running_tasks_lock = threading.Lock()

        # 模拟引擎处理 shutdown 命令
        def consume_shutdown():
            cmd = svc._cmd_queue.get(timeout=5)
            assert cmd.type == "shutdown"

        consumer = threading.Thread(target=consume_shutdown)
        consumer.start()

        # 调用 shutdown
        svc.shutdown()

        consumer.join(timeout=5)
        # 验证 shutdown_event 已设置
        assert svc._shutdown_event.is_set(), "shutdown 应设置 _shutdown_event"
        # 验证监控核心已清理
        assert svc._monitor_core is None

    def test_handle_stop_idempotent(self):
        """测试 _handle_stop 幂等性"""
        svc = ScheduleEngine.__new__(ScheduleEngine)
        svc._monitor_core = None
        svc._monitor_thread = None
        svc._thread_done = threading.Event()
        svc.record_log = MagicMock()
        svc._update_status_snapshot = MagicMock()

        # 多次调用不应抛出异常
        svc._handle_stop()
        svc._handle_stop()
        svc._handle_stop()


class TestManualLoginTimeout:
    """P1-BE-3: 手动登录超时后 _manual_login_in_progress 应被清除"""

    def test_manual_login_timeout_clears_flag(self):
        """测试超时后 _manual_login_in_progress 在 finally 中被清除"""
        svc = ScheduleEngine.__new__(ScheduleEngine)
        svc._cmd_queue = queue.Queue(maxsize=50)
        svc._wakeup_event = threading.Event()
        svc._manual_login_in_progress = False
        svc._manual_login_lock = threading.Lock()
        svc._runtime_config = RuntimeConfig().model_copy(update={
            "browser": RuntimeConfig().browser.model_copy(update={"login_timeout": 0.01})
        })
        svc._pure_mode = False
        svc._engine_thread = MagicMock()
        svc._engine_thread.is_alive.return_value = True

        ok, msg = svc.run_manual_login()

        assert not ok
        assert "超时" in msg
        # finally 块应清除标志
        assert not svc._manual_login_in_progress


class TestStartMonitoringPutNowait:
    """P1-BE-5: start_monitoring 使用 put_nowait，队列满时不阻塞"""

    def test_start_monitoring_put_nowait(self):
        """测试队列满时 start_monitoring 不阻塞，返回错误"""
        svc = ScheduleEngine.__new__(ScheduleEngine)
        svc._cmd_queue = queue.Queue(maxsize=1)
        svc._wakeup_event = threading.Event()
        svc._monitor_core = None
        svc._runtime_config = RuntimeConfig(
            credentials=LoginCredentials(
                auth_url="http://test.com", username="test", password="test",
            ),
        )
        svc._pure_mode = False
        svc._start_stop_lock = threading.Lock()

        # 填满队列
        svc._cmd_queue.put_nowait(EngineCommand(type=EngineCmdType.START))

        with (
            patch(
                "app.services.engine.ConfigValidator.validate_env_config",
                return_value=(True, ""),
            ),
        ):
            start = time.time()
            ok, msg = svc.start_monitoring()
            elapsed = time.time() - start

        # 验证不阻塞且返回错误
        assert not ok
        assert "队列已满" in msg
        assert elapsed < 1.0, f"start_monitoring 阻塞了 {elapsed:.2f}s"


class TestNetworkStateSetInConsumer:
    """P1-BE-7: network_state 在异步登录线程中统一赋值"""

    def test_do_async_login_delegates_to_task_executor(self):
        """_do_async_login 应委托给 orchestrator.submit"""
        from app.services.engine_login_bridge import LoginBridge
        from app.services.retry_policy import MonitoredPolicy

        svc = ScheduleEngine.__new__(ScheduleEngine)
        svc._runtime_config = RuntimeConfig()
        svc._update_status_snapshot = MagicMock()
        svc.record_log = MagicMock()
        svc._orchestrator = MagicMock()
        svc._wakeup_event = threading.Event()
        svc._retry_policy = MonitoredPolicy()
        svc._monitor_check_interval = 300
        svc._login_bridge = LoginBridge(
            get_orchestrator=lambda: svc._orchestrator,
            get_runtime_config=lambda: svc._runtime_config,
            retry_policy=svc._retry_policy,
            status_update_callback=svc._update_status_snapshot,
            record_log=svc.record_log,
            wakeup_event=svc._wakeup_event,
            get_monitor_check_interval=lambda: svc._monitor_check_interval,
        )
        svc._retry_time_lock = threading.Lock()
        def _bridge_retry_scheduled(delay: float) -> None:
            with svc._retry_time_lock:
                svc._next_retry_time = time.time() + delay
        def _bridge_login_success() -> None:
            with svc._retry_time_lock:
                svc._next_retry_time = 0
        def _bridge_retry_exhausted() -> None:
            with svc._retry_time_lock:
                svc._next_retry_time = 0
        svc._login_bridge._on_retry_scheduled = _bridge_retry_scheduled
        svc._login_bridge._on_login_success = _bridge_login_success
        svc._login_bridge._on_retry_exhausted = _bridge_retry_exhausted
        svc._next_retry_time = 0

        future = Future()
        handle = MagicMock()
        handle.rejected_reason = None
        handle.future = future
        svc._orchestrator.submit.return_value = handle

        mock_task_executor = MagicMock()
        mock_task_executor.is_login_running.return_value = False
        mock_task_executor.execute_login_async.return_value = None
        svc._task_executor = mock_task_executor

        svc._do_async_login()

        svc._orchestrator.submit.assert_called_once()

        # 清理
        future.set_result(None)
        time.sleep(0.1)


# =====================================================================
# Task 7: 架构修复验证测试
# =====================================================================


class TestReloadConfigQueueDispatch:
    """reload_config 应通过队列派发 RELOAD 命令。"""

    def test_reload_config_enqueues_reload_command(self, engine_factory):
        """测试 reload_config 将 RELOAD 命令放入队列。"""
        svc = engine_factory()
        svc._status_manager._status_snapshot = StatusSnapshot(monitoring=False)

        enqueued = []

        def mock_enqueue(cmd, retries=2):
            enqueued.append(cmd.type)
            # 立即设置 response_event 避免等待超时
            if cmd.response_event:
                cmd.response_event.set()
            return True

        svc._enqueue = mock_enqueue
        svc.reload_config()

        assert EngineCmdType.RELOAD in enqueued, (
            f"reload_config 应派发 RELOAD 命令，实际派发: {enqueued}"
        )


class TestApplyProfileQueueDispatch:
    """apply_profile 应通过队列派发 APPLY_PROFILE 命令。"""

    def test_apply_profile_enqueues_command(self, engine_factory):
        """测试 apply_profile 将 APPLY_PROFILE 命令放入队列。"""
        svc = engine_factory()
        svc._status_manager._status_snapshot = StatusSnapshot(monitoring=False)

        enqueued = []

        def mock_enqueue(cmd, retries=2):
            enqueued.append((cmd.type, cmd.data))
            # 立即设置 response_event 避免等待超时
            if cmd.response_event:
                cmd.response_event.set()
            return True

        svc._enqueue = mock_enqueue
        svc.apply_profile("test_profile")

        assert any(
            t == EngineCmdType.APPLY_PROFILE and d.get("profile_id") == "test_profile"
            for t, d in enqueued
        ), f"apply_profile 应派发 APPLY_PROFILE 命令，实际派发: {enqueued}"


class TestManualLoginConsumerDead:
    """引擎线程死亡时，_manual_login_in_progress 应被 finally 清除。"""

    def test_login_timeout_clears_when_engine_dead(self):
        """测试超时且引擎线程已死时，_manual_login_in_progress 被 finally 清除。"""
        svc = ScheduleEngine.__new__(ScheduleEngine)
        svc._cmd_queue = queue.Queue(maxsize=50)
        svc._wakeup_event = threading.Event()
        svc._manual_login_in_progress = False
        svc._manual_login_lock = threading.Lock()
        svc._runtime_config = RuntimeConfig().model_copy(update={
            "browser": RuntimeConfig().browser.model_copy(update={"login_timeout": 0.01})
        })
        svc._pure_mode = False
        svc._start_stop_lock = threading.Lock()

        # 模拟引擎线程已死亡
        svc._engine_thread = MagicMock()
        svc._engine_thread.is_alive.return_value = False

        ok, msg = svc.run_manual_login()

        assert not svc._manual_login_in_progress, (
            "引擎线程已死时，_manual_login_in_progress 应被 finally 清除"
        )
        assert not ok
        assert "超时" in msg


# =====================================================================
# Task 4: 自动切换方案标志位测试
# =====================================================================


class TestProfileSwitchFlag:
    """测试自动切换方案的标志位逻辑。"""

    def test_check_profile_switch_sets_flag(self):
        """测试自动切换方案设置标志位"""
        from app.services.monitor_service import NetworkMonitorCore

        core = NetworkMonitorCore(config=RuntimeConfig())
        mock_profile_service = MagicMock()
        mock_profile_service.load.return_value.auto_switch = True
        mock_profile_service.detect_matching_profile.return_value = "new_profile"
        mock_profile_service.set_active_profile.return_value = (True, "ok")
        core._profile_service = mock_profile_service
        core._last_profile_id = "old_profile"

        core._check_profile_switch()

        assert core._profile_switch_needed is True
        assert core._last_profile_id == "new_profile"

    def test_check_profile_switch_no_change(self):
        """测试方案未变化时不设置标志位"""
        from app.services.monitor_service import NetworkMonitorCore

        core = NetworkMonitorCore(config=RuntimeConfig())
        mock_profile_service = MagicMock()
        mock_profile_service.load.return_value.auto_switch = True
        mock_profile_service.detect_matching_profile.return_value = "same_profile"
        core._profile_service = mock_profile_service
        core._last_profile_id = "same_profile"

        core._check_profile_switch()

        assert core._profile_switch_needed is False

    def test_consume_profile_switch_flag(self):
        """测试消费标志位"""
        from app.services.monitor_service import NetworkMonitorCore

        core = NetworkMonitorCore(config=RuntimeConfig())
        core._profile_switch_needed = True

        assert core.consume_profile_switch_flag() is True
        assert core._profile_switch_needed is False
        assert core.consume_profile_switch_flag() is False
