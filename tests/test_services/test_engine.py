"""engine.py — 调度引擎测试

覆盖 ScheduleEngine 的初始化、生命周期、命令派发、网络检测、状态快照等。
目标覆盖率 >= 80%。
"""

from __future__ import annotations

import queue
import threading
import time
from collections import deque
from concurrent.futures import Future
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.engine import (
    EngineCmdType,
    EngineCommand,
    ScheduleEngine,
    StatusSnapshot,
)
from app.services.login_retry import LoginRetryManager



# =====================================================================
# EngineCmdType 枚举
# =====================================================================


class TestEngineCmdType:
    def test_enum_values(self):
        assert EngineCmdType.START == "start"
        assert EngineCmdType.STOP == "stop"
        assert EngineCmdType.LOGIN == "login"
        assert EngineCmdType.SHUTDOWN == "shutdown"
        assert EngineCmdType.RELOAD == "reload"
        assert EngineCmdType.APPLY_PROFILE == "apply_profile"

    def test_enum_members(self):
        assert len(EngineCmdType) == 6


# =====================================================================
# EngineCommand 数据类
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
            type=EngineCmdType.LOGIN,
            data={"key": "value"},
            response_event=event,
        )
        assert cmd.type == "login"
        assert cmd.data["key"] == "value"
        assert cmd.response_event is event


# =====================================================================
# StatusSnapshot 数据类
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
            last_check_time="2025-01-01",
            snapshot_time=200.0,
            status_detail="运行中",
            network_state="connected",
        )
        assert snap.monitoring is True
        assert snap.network_state == "connected"


# =====================================================================
# ScheduleEngine 初始化
# =====================================================================


class TestEngineInit:
    def test_init_defaults(self, engine_factory):
        svc = engine_factory()
        assert svc._dashboard_sink is None
        assert svc._scheduler_running is False
        assert svc._monitor_core is None

    def test_init_with_task_components(self, engine_factory):
        mock_registry = MagicMock()
        mock_executor = MagicMock()
        svc = engine_factory(task_registry=mock_registry, task_executor=mock_executor)
        assert svc._task_registry is mock_registry
        assert svc._task_executor is mock_executor


# =====================================================================
# _enqueue 方法
# =====================================================================


class TestEnqueue:
    def test_enqueue_success(self, engine_factory):
        svc = engine_factory(raw=True)
        cmd = EngineCommand(type=EngineCmdType.START)
        assert svc._enqueue(cmd) is True

    def test_enqueue_full(self, engine_factory):
        svc = engine_factory(raw=True)
        svc._cmd_queue = queue.Queue(maxsize=1)
        svc._cmd_queue.put_nowait(EngineCommand(type=EngineCmdType.START))
        cmd = EngineCommand(type=EngineCmdType.STOP)
        assert svc._enqueue(cmd) is False


# =====================================================================
# _calculate_wakeup
# =====================================================================


class TestCalculateWakeup:
    def test_default_wakeup(self, engine_factory):
        """无监控、无重试、无调度时，默认 60 秒后唤醒。"""
        svc = engine_factory(raw=True)
        # _monitor_core 为 None => _is_monitoring 为 False
        now = time.time()
        wakeup = svc._calculate_wakeup()
        assert wakeup >= now + 59
        assert wakeup <= now + 61

    def test_wakeup_with_monitoring(self, engine_factory):
        svc = engine_factory(raw=True)
        mock_core = MagicMock()
        mock_core.monitoring = True
        svc._monitor_core = mock_core
        svc._next_network_check = time.time() + 10
        wakeup = svc._calculate_wakeup()
        assert wakeup <= time.time() + 11

    def test_wakeup_with_login_retry(self, engine_factory):
        svc = engine_factory(raw=True)
        svc._monitor_core = None
        svc._login_retry = LoginRetryManager(
            count=1,
            last_attempt=time.time() - 100,
            config=(3, [5, 10, 15]),
        )
        wakeup = svc._calculate_wakeup()
        assert wakeup <= time.time() + 60

    def test_wakeup_with_scheduler(self, engine_factory):
        svc = engine_factory(raw=True)
        svc._monitor_core = None
        svc._scheduler_running = True
        svc._next_schedule_tick = time.time() + 5
        wakeup = svc._calculate_wakeup()
        assert wakeup <= time.time() + 6

    def test_wakeup_exception_fallback(self, engine_factory):
        """异常时回退到 now+5。"""
        svc = engine_factory(raw=True)
        svc._monitor_core = None
        # 通过让 next_wakeup 内部计算出错来触发异常
        svc._login_retry = LoginRetryManager(
            count=1,
            last_attempt="not_a_number",  # 会导致 TypeError
            config=(3, [5, 10, 15]),
        )
        svc._scheduler_running = False
        now = time.time()
        wakeup = svc._calculate_wakeup()
        assert wakeup >= now + 4
        assert wakeup <= now + 6


# =====================================================================
# _process_command
# =====================================================================


class TestProcessCommand:
    def _put_and_process(self, svc, cmd):
        """将命令放入队列再取出处理，避免 task_done 多余调用。"""
        svc._cmd_queue.put_nowait(cmd)
        got = svc._cmd_queue.get_nowait()
        svc._process_command(got)

    def test_dispatch_start(self, engine_factory):
        svc = engine_factory(raw=True)
        cmd = EngineCommand(type=EngineCmdType.START, response_event=threading.Event())
        svc._handle_start = MagicMock()
        self._put_and_process(svc, cmd)
        svc._handle_start.assert_called_once()
        assert cmd.response_event.is_set()

    def test_dispatch_stop(self, engine_factory):
        svc = engine_factory(raw=True)
        cmd = EngineCommand(type=EngineCmdType.STOP, response_event=threading.Event())
        svc._handle_stop = MagicMock()
        self._put_and_process(svc, cmd)
        svc._handle_stop.assert_called_once()

    def test_dispatch_login(self, engine_factory):
        svc = engine_factory(raw=True)
        cmd = EngineCommand(type=EngineCmdType.LOGIN, response_event=threading.Event())
        svc._handle_login = MagicMock()
        self._put_and_process(svc, cmd)
        svc._handle_login.assert_called_once()

    def test_dispatch_shutdown(self, engine_factory):
        svc = engine_factory(raw=True)
        cmd = EngineCommand(type=EngineCmdType.SHUTDOWN, response_event=threading.Event())
        svc._handle_shutdown = MagicMock()
        self._put_and_process(svc, cmd)
        svc._handle_shutdown.assert_called_once()

    def test_dispatch_reload(self, engine_factory):
        svc = engine_factory(raw=True)
        cmd = EngineCommand(type=EngineCmdType.RELOAD, response_event=threading.Event())
        svc._handle_reload = MagicMock()
        self._put_and_process(svc, cmd)
        svc._handle_reload.assert_called_once()

    def test_dispatch_apply_profile(self, engine_factory):
        svc = engine_factory(raw=True)
        cmd = EngineCommand(
            type=EngineCmdType.APPLY_PROFILE,
            response_event=threading.Event(),
        )
        svc._handle_apply_profile = MagicMock()
        self._put_and_process(svc, cmd)
        svc._handle_apply_profile.assert_called_once()

    def test_process_sets_response_event(self, engine_factory):
        svc = engine_factory(raw=True)
        event = threading.Event()
        cmd = EngineCommand(type=EngineCmdType.START, response_event=event)
        svc._handle_start = MagicMock()
        self._put_and_process(svc, cmd)
        assert event.is_set()

    def test_process_exception_still_sets_event(self, engine_factory):
        """handler 抛出异常时，response_event 仍被 set。"""
        svc = engine_factory(raw=True)
        event = threading.Event()
        cmd = EngineCommand(type=EngineCmdType.START, response_event=event)
        svc._handle_start = MagicMock(side_effect=RuntimeError("boom"))
        self._put_and_process(svc, cmd)
        assert event.is_set()


# =====================================================================
# _handle_start
# =====================================================================


class TestHandleStart:
    def test_handle_start_duplicate(self, engine_factory):
        """监控已在运行时，_handle_start 不创建新核心。"""
        svc = engine_factory(raw=True)
        mock_core = MagicMock()
        mock_core.monitoring = True
        svc._monitor_core = mock_core
        cmd = EngineCommand(type=EngineCmdType.START)
        svc._handle_start(cmd)
        assert svc._monitor_core is mock_core

    @patch("app.services.engine.NetworkMonitorCore")
    def test_handle_start_creates_core(self, mock_core_cls, engine_factory):
        """正常启动时创建 NetworkMonitorCore。"""
        svc = engine_factory(raw=True)
        svc._profile_service = MagicMock()
        svc._copy_runtime_config = MagicMock(return_value={})
        mock_core = MagicMock()
        mock_core_cls.return_value = mock_core
        cmd = EngineCommand(type=EngineCmdType.START, data={"pure_mode": False})
        svc._handle_start(cmd)
        assert svc._monitor_core is mock_core
        mock_core.init_monitoring.assert_called_once()

    @patch("app.services.engine.NetworkMonitorCore")
    def test_handle_start_pure_mode(self, mock_core_cls, engine_factory):
        """纯净模式标志传递给 config。"""
        svc = engine_factory(raw=True)
        svc._profile_service = MagicMock()
        svc._copy_runtime_config = MagicMock(return_value={})
        svc._pure_mode = True
        mock_core = MagicMock()
        mock_core_cls.return_value = mock_core
        cmd = EngineCommand(type=EngineCmdType.START, data={})
        svc._handle_start(cmd)
        call_config = mock_core_cls.call_args[1]["config"]
        assert call_config.get("browser_settings", {}).get("pure_mode") is True


# =====================================================================
# _handle_stop
# =====================================================================


class TestHandleStop:
    def test_handle_stop_no_core(self, engine_factory):
        svc = engine_factory(raw=True)
        svc._handle_stop()
        assert svc._monitor_core is None

    def test_handle_stop_with_core(self, engine_factory):
        svc = engine_factory(raw=True)
        mock_core = MagicMock()
        svc._monitor_core = mock_core
        svc._handle_stop()
        mock_core.stop_monitoring.assert_called_once()
        assert svc._monitor_core is None
        assert svc._login_retry.count == 0


# =====================================================================
# _handle_shutdown
# =====================================================================


class TestHandleShutdown:
    def test_handle_shutdown_calls_stop(self, engine_factory):
        svc = engine_factory(raw=True)
        svc._handle_stop = MagicMock()
        cmd = EngineCommand(type=EngineCmdType.SHUTDOWN)
        svc._handle_shutdown(cmd)
        svc._handle_stop.assert_called_once()


# =====================================================================
# _handle_login
# =====================================================================


class TestHandleLogin:
    def test_handle_login_no_config(self, engine_factory):
        """无配置时返回 False。"""
        svc = engine_factory(raw=True)
        svc._runtime_config = {}
        svc._copy_runtime_config = MagicMock(return_value={})
        cmd = EngineCommand(type=EngineCmdType.LOGIN, response_event=threading.Event())
        svc._handle_login(cmd)
        success, message = cmd.response_data
        assert success is False
        assert "配置不完整" in message

    def test_handle_login_missing_username(self, engine_factory):
        svc = engine_factory(raw=True)
        config = {"password": "p", "auth_url": "http://test.com"}
        svc._copy_runtime_config = MagicMock(return_value=config)
        cmd = EngineCommand(type=EngineCmdType.LOGIN, response_event=threading.Event())
        svc._handle_login(cmd)
        success, message = cmd.response_data
        assert success is False
        assert "配置不完整" in message

    def test_handle_login_missing_password(self, engine_factory):
        svc = engine_factory(raw=True)
        config = {"username": "u", "auth_url": "http://test.com"}
        svc._copy_runtime_config = MagicMock(return_value=config)
        cmd = EngineCommand(type=EngineCmdType.LOGIN, response_event=threading.Event())
        svc._handle_login(cmd)
        success, message = cmd.response_data
        assert success is False

    def test_handle_login_missing_auth_url(self, engine_factory):
        svc = engine_factory(raw=True)
        config = {"username": "u", "password": "p"}
        svc._copy_runtime_config = MagicMock(return_value=config)
        cmd = EngineCommand(type=EngineCmdType.LOGIN, response_event=threading.Event())
        svc._handle_login(cmd)
        success, message = cmd.response_data
        assert success is False

    def test_handle_login_async_success(self, engine_factory):
        svc = engine_factory(raw=True)
        config = {
            "username": "u",
            "password": "p",
            "auth_url": "http://test.com",
        }
        svc._copy_runtime_config = MagicMock(return_value=config)
        svc._do_async_login = MagicMock(return_value=True)
        cmd = EngineCommand(type=EngineCmdType.LOGIN, response_event=threading.Event())
        svc._handle_login(cmd)
        assert cmd.response_data == (True, "登录已提交")

    def test_handle_login_already_in_progress(self, engine_factory):
        svc = engine_factory(raw=True)
        config = {
            "username": "u",
            "password": "p",
            "auth_url": "http://test.com",
        }
        svc._copy_runtime_config = MagicMock(return_value=config)
        svc._do_async_login = MagicMock(return_value=False)
        cmd = EngineCommand(type=EngineCmdType.LOGIN, response_event=threading.Event())
        svc._handle_login(cmd)
        assert cmd.response_data == (False, "登录任务已在执行中，请稍后再试")


# =====================================================================
# _handle_reload
# =====================================================================


class TestHandleReload:
    def test_handle_reload_not_monitoring(self, engine_factory):
        svc = engine_factory(raw=True)
        svc._reload_config_internal = MagicMock()
        svc._handle_start = MagicMock()
        cmd = EngineCommand(type=EngineCmdType.RELOAD)
        svc._handle_reload(cmd)
        svc._reload_config_internal.assert_called_once()
        svc._handle_start.assert_not_called()

    def test_handle_reload_monitoring(self, engine_factory):
        svc = engine_factory(raw=True)
        mock_core = MagicMock()
        mock_core.monitoring = True
        svc._monitor_core = mock_core
        svc._reload_config_internal = MagicMock()
        svc._handle_stop = MagicMock()
        svc._handle_start = MagicMock()
        cmd = EngineCommand(type=EngineCmdType.RELOAD)
        svc._handle_reload(cmd)
        svc._handle_stop.assert_called_once()
        svc._reload_config_internal.assert_called_once()
        svc._handle_start.assert_called_once()

    def test_reload_failure_keeps_monitoring(self, engine_factory):
        """重载失败时不应调用 _handle_stop，监控应继续运行。"""
        svc = engine_factory(raw=True)
        mock_core = MagicMock()
        mock_core.monitoring = True
        svc._monitor_core = mock_core
        svc._reload_config_internal = MagicMock(return_value=False)
        svc._handle_stop = MagicMock()
        svc._handle_start = MagicMock()
        cmd = EngineCommand(type=EngineCmdType.RELOAD)
        svc._handle_reload(cmd)
        svc._reload_config_internal.assert_called_once()
        svc._handle_stop.assert_not_called()
        svc._handle_start.assert_not_called()

    def test_reload_success_restarts_monitoring(self, engine_factory):
        """重载成功且之前在监控时，应调用 stop + start。"""
        svc = engine_factory(raw=True)
        mock_core = MagicMock()
        mock_core.monitoring = True
        svc._monitor_core = mock_core
        svc._reload_config_internal = MagicMock(return_value=True)
        svc._handle_stop = MagicMock()
        svc._handle_start = MagicMock()
        cmd = EngineCommand(type=EngineCmdType.RELOAD)
        svc._handle_reload(cmd)
        svc._reload_config_internal.assert_called_once()
        svc._handle_stop.assert_called_once()
        svc._handle_start.assert_called_once()


# =====================================================================
# _handle_apply_profile
# =====================================================================


class TestHandleApplyProfile:
    def test_handle_apply_profile_not_monitoring(self, engine_factory):
        svc = engine_factory(raw=True)
        svc._runtime_config = {"auth_url": "http://test.com", "username": "u"}
        svc._reload_config_internal = MagicMock()
        cmd = EngineCommand(
            type=EngineCmdType.APPLY_PROFILE, data={"profile_id": "p1"}
        )
        svc._handle_apply_profile(cmd)
        svc._reload_config_internal.assert_called_once()

    def test_handle_apply_profile_monitoring(self, engine_factory):
        svc = engine_factory(raw=True)
        mock_core = MagicMock()
        mock_core.monitoring = True
        svc._monitor_core = mock_core
        svc._runtime_config = {"auth_url": "http://test.com", "username": "u"}
        svc._reload_config_internal = MagicMock()
        svc._handle_stop = MagicMock()
        svc._handle_start = MagicMock()
        cmd = EngineCommand(
            type=EngineCmdType.APPLY_PROFILE, data={"profile_id": "p1"}
        )
        svc._handle_apply_profile(cmd)
        svc._handle_stop.assert_called_once()
        svc._reload_config_internal.assert_called_once()
        svc._handle_start.assert_called_once()


# =====================================================================
# _do_network_check
# =====================================================================


class TestDoNetworkCheck:
    def test_do_network_check_no_core(self, engine_factory):
        svc = engine_factory(raw=True)
        svc._do_network_check()

    def test_do_network_check_need_login(self, engine_factory):
        svc = engine_factory(raw=True)
        mock_core = MagicMock()
        mock_core.check_once.return_value = {"need_login": True, "interval": 300}
        mock_core.consume_profile_switch_flag.return_value = False
        svc._monitor_core = mock_core
        svc._copy_runtime_config = MagicMock(return_value={
            "retry_settings": {"max_retries": 3, "retry_interval": 30}
        })
        svc._do_async_login = MagicMock()
        with patch("app.utils.retry.get_retry_intervals", return_value=[30, 30, 30]):
            svc._do_network_check()
        svc._do_async_login.assert_called_once()
        assert svc._login_retry.config == (3, [30, 30, 30])

    def test_do_network_check_no_login_needed(self, engine_factory):
        svc = engine_factory(raw=True)
        mock_core = MagicMock()
        mock_core.check_once.return_value = {"need_login": False, "interval": 600}
        mock_core.consume_profile_switch_flag.return_value = False
        svc._monitor_core = mock_core
        svc._login_retry.count = 2
        svc._do_network_check()
        assert svc._login_retry.count == 0

    def test_do_network_check_profile_switch(self, engine_factory):
        svc = engine_factory(raw=True)
        mock_core = MagicMock()
        mock_core.check_once.return_value = {"need_login": False, "interval": 300}
        mock_core.consume_profile_switch_flag.return_value = True
        svc._monitor_core = mock_core
        svc._handle_stop = MagicMock()
        svc._reload_config_internal = MagicMock()
        svc._handle_start = MagicMock()
        svc._do_network_check()
        svc._handle_stop.assert_called_once()
        svc._reload_config_internal.assert_called_once()

    def test_do_network_check_exception(self, engine_factory):
        svc = engine_factory(raw=True)
        mock_core = MagicMock()
        mock_core.check_once.side_effect = RuntimeError("boom")
        svc._monitor_core = mock_core
        svc._do_network_check()
        assert svc._next_network_check > time.time()


# =====================================================================
# _login_retry_needed
# =====================================================================


class TestLoginRetryNeeded:
    def test_no_retry_needed_when_count_zero(self, engine_factory):
        svc = engine_factory(raw=True)
        assert svc._login_retry_needed(time.time()) is False

    def test_no_retry_needed_when_no_config(self, engine_factory):
        svc = engine_factory(raw=True)
        svc._login_retry.count = 1
        svc._login_retry.config = None
        assert svc._login_retry_needed(time.time()) is False

    def test_no_retry_needed_when_login_in_progress(self, engine_factory):
        svc = engine_factory(raw=True)
        svc._login_retry.count = 1
        svc._login_retry.config = (3, [10, 20, 30])
        svc._task_executor.is_login_running.return_value = True
        assert svc._login_retry_needed(time.time()) is False

    def test_no_retry_needed_when_max_retries_reached(self, engine_factory):
        svc = engine_factory(raw=True)
        svc._login_retry.count = 3
        svc._login_retry.config = (3, [10, 20, 30])
        assert svc._login_retry_needed(time.time()) is False

    def test_no_retry_needed_when_index_out_of_range(self, engine_factory):
        svc = engine_factory(raw=True)
        svc._login_retry.count = 4
        svc._login_retry.config = (5, [10])
        assert svc._login_retry_needed(time.time()) is False

    def test_no_retry_needed_when_too_early(self, engine_factory):
        svc = engine_factory(raw=True)
        svc._login_retry.count = 1
        svc._login_retry.last_attempt = time.time()
        svc._login_retry.config = (3, [60, 60, 60])
        assert svc._login_retry_needed(time.time()) is False

    def test_retry_needed(self, engine_factory):
        svc = engine_factory(raw=True)
        svc._login_retry.count = 1
        svc._login_retry.last_attempt = time.time() - 100
        svc._login_retry.config = (3, [10, 20, 30])
        svc._task_executor.is_login_running.return_value = False
        assert svc._login_retry_needed(time.time()) is True


# =====================================================================
# _do_async_login
# =====================================================================


# =====================================================================
# F04: 网络检测不再无条件 reset 重试计数
# =====================================================================


class TestNetworkCheckBackoff:
    def test_need_login_count_zero_resets_and_configures(self, engine_factory):
        """count==0 时 need_login 应 reset+configure。"""
        svc = engine_factory(raw=True)
        mock_core = MagicMock()
        mock_core.check_once.return_value = {"need_login": True, "interval": 300}
        mock_core.consume_profile_switch_flag.return_value = False
        svc._monitor_core = mock_core
        svc._copy_runtime_config = MagicMock(return_value={
            "retry_settings": {"max_retries": 3, "retry_interval": 30}
        })
        svc._do_async_login = MagicMock()
        svc._login_retry.count = 0
        with patch("app.utils.retry.get_retry_intervals", return_value=[30, 30, 30]):
            svc._do_network_check()
        svc._do_async_login.assert_called_once()
        assert svc._login_retry.config == (3, [30, 30, 30])

    def test_need_login_count_nonzero_skips_reset(self, engine_factory):
        """count>0 时 need_login 应跳过 reset+configure，仅调用 _do_async_login。"""
        svc = engine_factory(raw=True)
        mock_core = MagicMock()
        mock_core.check_once.return_value = {"need_login": True, "interval": 300}
        mock_core.consume_profile_switch_flag.return_value = False
        svc._monitor_core = mock_core
        svc._do_async_login = MagicMock()
        svc._login_retry.count = 2
        svc._login_retry.config = (3, [5, 5, 5])
        svc._do_network_check()
        svc._do_async_login.assert_called_once()
        # config 不应被覆盖
        assert svc._login_retry.config == (3, [5, 5, 5])
        # count 不应被 reset
        assert svc._login_retry.count == 2

    def test_no_login_needed_resets_failure_counters(self, engine_factory):
        """need_login=False 应清空连续失败计数和退避乘数。"""
        svc = engine_factory(raw=True)
        mock_core = MagicMock()
        mock_core.check_once.return_value = {"need_login": False, "interval": 600}
        mock_core.consume_profile_switch_flag.return_value = False
        svc._monitor_core = mock_core
        svc._consecutive_login_failures = 5
        svc._backoff_check_multiplier = 4
        svc._do_network_check()
        assert svc._consecutive_login_failures == 0
        assert svc._backoff_check_multiplier == 1
        assert svc._login_retry.count == 0

    def test_on_done_auto_success_clears_failure_count(self, engine_factory):
        """自动登录成功应清空连续失败计数。"""
        svc = engine_factory(raw=True)
        svc._consecutive_login_failures = 3
        future = Future()
        svc._task_executor.execute_login_async.return_value = future
        svc._task_executor.is_login_running.return_value = False
        svc._do_async_login()
        future.set_result((True, "登录成功"))
        assert svc._consecutive_login_failures == 0

    def test_on_done_auto_failure_increments_count(self, engine_factory):
        """自动登录失败应递增连续失败计数。"""
        svc = engine_factory(raw=True)
        svc._consecutive_login_failures = 0
        future = Future()
        svc._task_executor.execute_login_async.return_value = future
        svc._task_executor.is_login_running.return_value = False
        svc._do_async_login()
        future.set_result((False, "登录失败"))
        assert svc._consecutive_login_failures == 1

    def test_on_done_auto_failure_triggers_backoff(self, engine_factory):
        """连续失败达到阈值后应触发降频。"""
        svc = engine_factory(raw=True)
        svc._consecutive_login_failures = 2  # 再失败一次就达到阈值 3
        svc._backoff_check_multiplier = 1
        svc._monitor_check_interval = 300
        future = Future()
        svc._task_executor.execute_login_async.return_value = future
        svc._task_executor.is_login_running.return_value = False
        svc._do_async_login()
        future.set_result((False, "登录失败"))
        assert svc._consecutive_login_failures == 3
        # 乘数应从 1 升至 2
        assert svc._backoff_check_multiplier == 2

    def test_on_done_manual_login_does_not_affect_failure_count(self, engine_factory):
        """手动登录结果不应影响连续失败计数。"""
        svc = engine_factory(raw=True)
        svc._consecutive_login_failures = 2
        future = Future()
        svc._task_executor.execute_login_async.return_value = future
        svc._task_executor.is_login_running.return_value = False
        svc._do_async_login(is_manual=True)
        future.set_result((False, "登录失败"))
        # 手动登录不应递增
        assert svc._consecutive_login_failures == 2

    def test_on_done_manual_success_does_not_clear_failure_count(self, engine_factory):
        """手动登录成功不应清空自动登录的连续失败计数。"""
        svc = engine_factory(raw=True)
        svc._consecutive_login_failures = 2
        future = Future()
        svc._task_executor.execute_login_async.return_value = future
        svc._task_executor.is_login_running.return_value = False
        svc._do_async_login(is_manual=True)
        future.set_result((True, "登录成功"))
        assert svc._consecutive_login_failures == 2

    def test_login_retry_max_cycles(self, engine_factory):
        svc = engine_factory(raw=True)
        assert svc._login_retry_max_cycles() == 3

    def test_apply_backoff_interval_caps_multiplier(self, engine_factory):
        """退避乘数不应超过 6。"""
        svc = engine_factory(raw=True)
        svc._backoff_check_multiplier = 6
        svc._monitor_check_interval = 300
        svc._consecutive_login_failures = 10
        svc._apply_backoff_interval()
        assert svc._backoff_check_multiplier == 6

    def test_apply_backoff_interval_increases_multiplier(self, engine_factory):
        svc = engine_factory(raw=True)
        svc._backoff_check_multiplier = 1
        svc._monitor_check_interval = 300
        svc._consecutive_login_failures = 3
        svc._apply_backoff_interval()
        assert svc._backoff_check_multiplier == 2
        # extra = (2-1) * 300 = 300
        assert svc._next_network_check > time.time() + 299

    def test_apply_backoff_interval_doubles_each_time(self, engine_factory):
        """连续触发退避应指数增长。"""
        svc = engine_factory(raw=True)
        svc._monitor_check_interval = 300
        svc._consecutive_login_failures = 3

        svc._backoff_check_multiplier = 1
        svc._apply_backoff_interval()
        assert svc._backoff_check_multiplier == 2  # extra = 300s

        svc._apply_backoff_interval()
        assert svc._backoff_check_multiplier == 4  # extra = 900s

        svc._apply_backoff_interval()
        assert svc._backoff_check_multiplier == 6  # extra = 1500s (cap)

        svc._apply_backoff_interval()
        assert svc._backoff_check_multiplier == 6  # 保持 cap

    def test_init_fields_exist(self, engine_factory):
        """__init__ 中应初始化降频相关字段。"""
        svc = engine_factory(raw=True)
        assert svc._consecutive_login_failures == 0
        assert svc._backoff_check_multiplier == 1


class TestDoAsyncLogin:
    def test_already_in_progress(self, engine_factory):
        svc = engine_factory(raw=True)
        svc._task_executor.is_login_running.return_value = True
        assert svc._do_async_login() is False

    def test_future_none(self, engine_factory):
        svc = engine_factory(raw=True)
        svc._task_executor.execute_login_async.return_value = None
        assert svc._do_async_login() is False

    def test_future_success(self, engine_factory):
        svc = engine_factory(raw=True)
        # 使用一个未完成的 Future，避免 done_callback 立即执行
        future = Future()
        svc._task_executor.execute_login_async.return_value = future
        svc._task_executor.is_login_running.return_value = False
        result = svc._do_async_login()
        assert result is True

    def test_exception_propagates(self, engine_factory):
        svc = engine_factory(raw=True)
        svc._task_executor.is_login_running.return_value = False
        svc._task_executor.execute_login_async.side_effect = RuntimeError("boom")
        with pytest.raises(RuntimeError):
            svc._do_async_login()

    def test_exception_does_not_consume_retry(self, engine_factory):
        """execute_login_async 抛异常时不应递增重试计数（F03）。"""
        svc = engine_factory(raw=True)
        svc._task_executor.is_login_running.return_value = False
        svc._task_executor.execute_login_async.side_effect = RuntimeError("pool closed")
        svc._login_retry.count = 0
        with pytest.raises(RuntimeError):
            svc._do_async_login()
        assert svc._login_retry.count == 0

    def test_success_increments_retry_count(self, engine_factory):
        """execute_login_async 成功后应递增重试计数。"""
        svc = engine_factory(raw=True)
        future = Future()
        svc._task_executor.execute_login_async.return_value = future
        svc._task_executor.is_login_running.return_value = False
        svc._login_retry.count = 0
        svc._do_async_login()
        assert svc._login_retry.count == 1



# =====================================================================
# _run_schedule_tick
# =====================================================================


class TestRunScheduleTick:
    def test_run_schedule_tick(self, engine_factory):
        svc = engine_factory(raw=True)
        svc._task_registry.get_due_tasks.return_value = ["task1", "task2"]
        svc._run_schedule_tick()
        svc._task_executor.execute_task_async.assert_any_call("task1")
        svc._task_executor.execute_task_async.assert_any_call("task2")
        assert svc._next_schedule_tick > time.time()

    def test_run_schedule_tick_no_due_tasks(self, engine_factory):
        svc = engine_factory(raw=True)
        svc._task_registry.get_due_tasks.return_value = []
        svc._run_schedule_tick()
        svc._task_executor.execute_task_async.assert_not_called()

    def test_run_schedule_tick_no_registry(self, engine_factory):
        svc = engine_factory(raw=True)
        svc._task_registry = None
        svc._run_schedule_tick()
        assert svc._next_schedule_tick > time.time()


# =====================================================================
# _update_status_snapshot
# =====================================================================


class TestUpdateStatusSnapshot:
    def test_update_no_core(self, engine_factory):
        svc = engine_factory(raw=True)
        svc._update_status_snapshot = ScheduleEngine._update_status_snapshot.__get__(svc)
        svc._queue_status_broadcast = MagicMock()
        svc._monitor_core = None
        svc._update_status_snapshot(force=True)
        assert svc._status_snapshot.monitoring is False
        assert svc._status_snapshot.status_detail == "已停止"

    def test_update_with_core_connected(self, engine_factory):
        svc = engine_factory(raw=True)
        svc._update_status_snapshot = ScheduleEngine._update_status_snapshot.__get__(svc)
        svc._queue_status_broadcast = MagicMock()
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
        svc._update_status_snapshot(force=True)
        assert svc._status_snapshot.monitoring is True
        assert svc._status_snapshot.last_network_ok is True
        assert svc._status_snapshot.network_state == "connected"
        assert svc._status_snapshot.network_check_count == 10

    def test_update_with_core_disconnected(self, engine_factory):
        svc = engine_factory(raw=True)
        svc._update_status_snapshot = ScheduleEngine._update_status_snapshot.__get__(svc)
        svc._queue_status_broadcast = MagicMock()
        mock_core = MagicMock()
        mock_core.monitoring = True
        mock_core.snapshot.return_value = {
            "network_state": "disconnected",
            "start_time": 100.0,
            "network_check_count": 5,
            "login_attempt_count": 1,
            "last_check_time": "2025-01-01",
            "status_detail": "网络异常",
        }
        svc._monitor_core = mock_core
        svc._update_status_snapshot(force=True)
        assert svc._status_snapshot.last_network_ok is False

    def test_update_throttled(self, engine_factory):
        svc = engine_factory(raw=True)
        svc._update_status_snapshot = ScheduleEngine._update_status_snapshot.__get__(svc)
        svc._queue_status_broadcast = MagicMock()
        svc._last_snapshot_time = time.time()
        svc._monitor_core = MagicMock()
        svc._monitor_core.monitoring = True
        svc._monitor_core.snapshot.return_value = {"network_state": "connected"}
        svc._update_status_snapshot(force=False)
        assert svc._status_snapshot.monitoring is False

    def test_update_force_skips_throttle(self, engine_factory):
        svc = engine_factory(raw=True)
        svc._update_status_snapshot = ScheduleEngine._update_status_snapshot.__get__(svc)
        svc._queue_status_broadcast = MagicMock()
        svc._last_snapshot_time = time.time()
        mock_core = MagicMock()
        mock_core.monitoring = True
        mock_core.snapshot.return_value = {
            "network_state": "connected",
            "start_time": 100.0,
            "network_check_count": 0,
            "login_attempt_count": 0,
            "last_check_time": None,
            "status_detail": "正常",
        }
        svc._monitor_core = mock_core
        svc._update_status_snapshot(force=True)
        assert svc._status_snapshot.monitoring is True

    def test_update_core_exception(self, engine_factory):
        svc = engine_factory(raw=True)
        svc._update_status_snapshot = ScheduleEngine._update_status_snapshot.__get__(svc)
        svc._queue_status_broadcast = MagicMock()
        mock_core = MagicMock()
        mock_core.monitoring = True
        mock_core.snapshot.side_effect = RuntimeError("boom")
        svc._monitor_core = mock_core
        svc._update_status_snapshot(force=True)


# =====================================================================
# _queue_status_broadcast
# =====================================================================


class TestQueueStatusBroadcast:
    def test_queue_status_broadcast_default_queue(self, engine_factory):
        svc = engine_factory(raw=True)
        svc._queue_status_broadcast = ScheduleEngine._queue_status_broadcast.__get__(svc)
        svc.get_status = MagicMock(return_value=MagicMock(model_dump=lambda: {"monitoring": False}))
        svc._queue_status_broadcast()
        assert len(svc._empty_broadcast_queue) == 1
        assert svc._empty_broadcast_queue[0]["type"] == "status"

    def test_queue_status_broadcast_with_dashboard_sink(self, engine_factory):
        svc = engine_factory(raw=True)
        svc._queue_status_broadcast = ScheduleEngine._queue_status_broadcast.__get__(svc)
        mock_sink = MagicMock()
        mock_sink.broadcast_queue = deque()
        svc._dashboard_sink = mock_sink
        svc.get_status = MagicMock(return_value=MagicMock(model_dump=lambda: {"monitoring": True}))
        svc._queue_status_broadcast()
        assert len(mock_sink.broadcast_queue) == 1

    def test_queue_status_broadcast_exception(self, engine_factory):
        svc = engine_factory(raw=True)
        svc._queue_status_broadcast = ScheduleEngine._queue_status_broadcast.__get__(svc)
        svc.get_status = MagicMock(side_effect=RuntimeError("boom"))
        svc._queue_status_broadcast()


# =====================================================================
# get_status
# =====================================================================


class TestGetStatus:
    def test_get_status_stopped(self, engine_factory):
        svc = engine_factory(raw=True)
        status = svc.get_status()
        assert status.monitoring is False
        assert status.runtime_seconds == 0
        assert status.network_connected is False

    def test_get_status_running(self, engine_factory):
        svc = engine_factory(raw=True)
        svc._status_snapshot = StatusSnapshot(
            monitoring=True,
            last_network_ok=True,
            start_time=time.time() - 120,
            network_check_count=10,
            login_attempt_count=2,
            last_check_time="2025-01-01",
            network_state="connected",
        )
        status = svc.get_status()
        assert status.monitoring is True
        assert status.network_connected is True
        assert status.runtime_seconds > 0


# =====================================================================
# shutdown
# =====================================================================


class TestShutdown:
    def test_shutdown_sets_event_and_clears_core(self, engine_factory):
        svc = engine_factory(raw=True)
        svc._monitor_core = MagicMock()
        svc.shutdown()
        assert svc._shutdown_event.is_set()
        assert svc._monitor_core is None

    def test_shutdown_idempotent(self, engine_factory):
        svc = engine_factory(raw=True)
        svc.shutdown()
        svc.shutdown()
        svc.shutdown()
        assert svc._shutdown_event.is_set()

    def test_shutdown_stops_scheduler(self, engine_factory):
        svc = engine_factory(raw=True)
        svc._scheduler_running = True
        svc.shutdown()
        assert svc._scheduler_running is False


# =====================================================================
# start_monitoring / stop_monitoring
# =====================================================================


class TestStartStopMonitoring:
    def test_start_monitoring_already_running(self, engine_factory):
        svc = engine_factory(raw=True)
        mock_core = MagicMock()
        mock_core.monitoring = True
        svc._monitor_core = mock_core
        ok, msg = svc.start_monitoring()
        assert ok is False
        assert "已在运行" in msg

    def test_start_monitoring_invalid_config(self, engine_factory):
        svc = engine_factory(raw=True)
        with patch(
            "app.services.engine.ConfigValidator.validate_env_config",
            return_value=(False, "缺少认证地址"),
        ):
            ok, msg = svc.start_monitoring()
        assert ok is False
        assert "配置无效" in msg

    def test_start_monitoring_queue_full(self, engine_factory):
        svc = engine_factory(raw=True)
        svc._cmd_queue = queue.Queue(maxsize=1)
        svc._cmd_queue.put_nowait(EngineCommand(type=EngineCmdType.START))
        with patch(
            "app.services.engine.ConfigValidator.validate_env_config",
            return_value=(True, ""),
        ):
            ok, msg = svc.start_monitoring()
        assert ok is False
        assert "队列已满" in msg

    def test_start_monitoring_success(self, engine_factory):
        svc = engine_factory(raw=True)
        with patch(
            "app.services.engine.ConfigValidator.validate_env_config",
            return_value=(True, ""),
        ):
            ok, msg = svc.start_monitoring()
        assert ok is True
        assert "已启动" in msg

    def test_stop_monitoring_not_running(self, engine_factory):
        svc = engine_factory(raw=True)
        ok, msg = svc.stop_monitoring()
        assert ok is False
        assert "未运行" in msg

    def test_stop_monitoring_running(self, engine_factory):
        svc = engine_factory(raw=True)
        mock_core = MagicMock()
        mock_core.monitoring = True
        svc._monitor_core = mock_core
        ok, msg = svc.stop_monitoring()
        assert ok is True
        assert "已停止" in msg

    def test_stop_monitoring_queue_full(self, engine_factory):
        svc = engine_factory(raw=True)
        svc._cmd_queue = queue.Queue(maxsize=1)
        mock_core = MagicMock()
        mock_core.monitoring = True
        svc._monitor_core = mock_core
        svc._cmd_queue.put_nowait(EngineCommand(type=EngineCmdType.START))
        ok, msg = svc.stop_monitoring()
        assert ok is False
        assert "队列已满" in msg


# =====================================================================
# reload_config / apply_profile (队列派发)
# =====================================================================


class TestReloadConfig:
    def test_reload_config_enqueues(self, engine_factory):
        svc = engine_factory(raw=True)
        enqueued = []
        def fake_enqueue(cmd):
            enqueued.append(cmd.type)
            if cmd.response_event:
                cmd.response_event.set()
            return True
        svc._enqueue = fake_enqueue
        svc.reload_config()
        assert EngineCmdType.RELOAD in enqueued

    def test_reload_config_queue_full(self, engine_factory):
        svc = engine_factory(raw=True)
        svc._enqueue = MagicMock(return_value=False)
        svc.reload_config()

    def test_reload_config_timeout(self, engine_factory):
        svc = engine_factory(raw=True)
        real_event = threading.Event()
        def fake_enqueue(cmd):
            cmd.response_event = real_event
            return True
        svc._enqueue = fake_enqueue
        with patch.object(real_event, "wait", return_value=False):
            svc.reload_config()


class TestApplyProfile:
    def test_apply_profile_enqueues(self, engine_factory):
        svc = engine_factory(raw=True)
        enqueued = []
        def fake_enqueue(cmd):
            enqueued.append((cmd.type, cmd.data))
            if cmd.response_event:
                cmd.response_event.set()
            return True
        svc._enqueue = fake_enqueue
        svc.apply_profile("p1")
        assert any(
            t == EngineCmdType.APPLY_PROFILE and d.get("profile_id") == "p1"
            for t, d in enqueued
        )

    def test_apply_profile_queue_full(self, engine_factory):
        svc = engine_factory(raw=True)
        svc._enqueue = MagicMock(return_value=False)
        svc.apply_profile("p1")

    def test_apply_profile_timeout(self, engine_factory):
        svc = engine_factory(raw=True)
        real_event = threading.Event()
        def fake_enqueue(cmd):
            cmd.response_event = real_event
            return True
        svc._enqueue = fake_enqueue
        with patch.object(real_event, "wait", return_value=False):
            svc.apply_profile("p1")


# =====================================================================
# run_manual_login
# =====================================================================


class TestRunManualLogin:
    def test_run_manual_login_in_progress(self, engine_factory):
        svc = engine_factory(raw=True)
        svc._manual_login_in_progress = True
        ok, msg = svc.run_manual_login()
        assert ok is False
        assert "进行中" in msg

    def test_run_manual_login_queue_full(self, engine_factory):
        svc = engine_factory(raw=True)
        svc._cmd_queue = queue.Queue(maxsize=1)
        svc._cmd_queue.put_nowait(EngineCommand(type=EngineCmdType.START))
        ok, msg = svc.run_manual_login()
        assert ok is False
        assert "队列已满" in msg

    def test_run_manual_login_success(self, engine_factory):
        svc = engine_factory(raw=True)
        def fake_enqueue(cmd):
            cmd.response_data = (True, "登录成功")
            if cmd.response_event:
                cmd.response_event.set()
            return True
        svc._enqueue = fake_enqueue
        svc._update_status_snapshot = MagicMock()
        ok, msg = svc.run_manual_login()
        assert ok is True
        assert "已提交" in msg

    def test_run_manual_login_failure(self, engine_factory):
        svc = engine_factory(raw=True)
        def fake_enqueue(cmd):
            cmd.response_data = (False, "密码错误")
            if cmd.response_event:
                cmd.response_event.set()
            return True
        svc._enqueue = fake_enqueue
        ok, msg = svc.run_manual_login()
        assert ok is False
        assert "失败" in msg
        assert "密码错误" in msg

    def test_run_manual_login_timeout_engine_alive(self, engine_factory):
        svc = engine_factory(raw=True)
        def fake_enqueue(cmd):
            return True
        svc._enqueue = fake_enqueue
        svc._engine_thread = MagicMock()
        svc._engine_thread.is_alive.return_value = True
        svc._ui_config.login_timeout = 0.01
        ok, msg = svc.run_manual_login()
        assert ok is False
        assert "超时" in msg
        assert not svc._manual_login_in_progress

    def test_run_manual_login_timeout_engine_dead(self, engine_factory):
        svc = engine_factory(raw=True)
        def fake_enqueue(cmd):
            return True
        svc._enqueue = fake_enqueue
        svc._engine_thread = MagicMock()
        svc._engine_thread.is_alive.return_value = False
        svc._ui_config.login_timeout = 0.01
        ok, msg = svc.run_manual_login()
        assert ok is False
        assert "引擎线程已退出" in msg


# =====================================================================
# test_network
# =====================================================================


class TestNetwork:
    def test_network_ok(self, engine_factory):
        svc = engine_factory(raw=True)
        svc._copy_runtime_config = MagicMock(return_value={"monitor": {}})
        with patch("app.services.engine.is_network_available", return_value=True):
            ok, msg = svc.test_network()
        assert ok is True
        assert "正常" in msg

    def test_network_fail(self, engine_factory):
        svc = engine_factory(raw=True)
        svc._copy_runtime_config = MagicMock(return_value={"monitor": {}})
        with patch("app.services.engine.is_network_available", return_value=False):
            ok, msg = svc.test_network()
        assert ok is False
        assert "异常" in msg

    def test_network_exception(self, engine_factory):
        svc = engine_factory(raw=True)
        svc._copy_runtime_config = MagicMock(return_value={"monitor": {}})
        with patch("app.services.engine.is_network_available", side_effect=RuntimeError("timeout")):
            ok, msg = svc.test_network()
        assert ok is False
        assert "失败" in msg

    def test_network_with_targets(self, engine_factory):
        svc = engine_factory(raw=True)
        svc._copy_runtime_config = MagicMock(return_value={
            "monitor": {
                "ping_targets": "8.8.8.8,1.1.1.1",
                "enable_tcp_check": True,
                "enable_http_check": False,
                "url_check_urls": ["http://example.com"],
            }
        })
        with patch("app.services.engine.is_network_available", return_value=True):
            ok, msg = svc.test_network()
        assert ok is True


# =====================================================================
# toggle_pure_mode
# =====================================================================


class TestTogglePureMode:
    def test_toggle_pure_mode(self, engine_factory):
        svc = engine_factory(raw=True)
        svc._profile_service = MagicMock()
        assert svc.pure_mode is False
        new_value = svc.toggle_pure_mode()
        assert new_value is True
        assert svc.pure_mode is True
        svc._profile_service.update.assert_called_once()


# =====================================================================
# 属性
# =====================================================================


class TestProperties:
    def test_login_in_progress_property(self, engine_factory):
        svc = engine_factory(raw=True)
        svc._task_executor.is_login_running.return_value = False
        assert svc.login_in_progress is False
        svc._task_executor.is_login_running.return_value = True
        assert svc.login_in_progress is True

    def test_ws_broadcast_queue_default(self, engine_factory):
        svc = engine_factory(raw=True)
        svc._dashboard_sink = None
        q = svc.ws_broadcast_queue
        assert q is svc._empty_broadcast_queue

    def test_ws_broadcast_queue_with_sink(self, engine_factory):
        svc = engine_factory(raw=True)
        mock_sink = MagicMock()
        mock_sink.broadcast_queue = deque()
        svc._dashboard_sink = mock_sink
        q = svc.ws_broadcast_queue
        assert q is mock_sink.broadcast_queue

    def test_pure_mode_property(self, engine_factory):
        svc = engine_factory(raw=True)
        assert svc.pure_mode is False

    def test_is_monitoring_false(self, engine_factory):
        svc = engine_factory(raw=True)
        assert svc._is_monitoring is False

    def test_is_monitoring_true(self, engine_factory):
        svc = engine_factory(raw=True)
        mock_core = MagicMock()
        mock_core.monitoring = True
        svc._monitor_core = mock_core
        assert svc._is_monitoring is True

    def test_is_monitoring_core_not_monitoring(self, engine_factory):
        svc = engine_factory(raw=True)
        mock_core = MagicMock()
        mock_core.monitoring = False
        svc._monitor_core = mock_core
        assert svc._is_monitoring is False

    def test_tasks_property(self, engine_factory):
        svc = engine_factory(raw=True)
        assert svc.tasks is svc._task_executor

    def test_scheduler_running_property(self, engine_factory):
        svc = engine_factory(raw=True)
        assert svc.scheduler_running is False
        svc._scheduler_running = True
        assert svc.scheduler_running is True


# =====================================================================
# 调度器控制
# =====================================================================


class TestSchedulerControl:
    def test_start_scheduler(self, engine_factory):
        svc = engine_factory(raw=True)
        svc.start_scheduler()
        assert svc._scheduler_running is True
        assert svc._next_schedule_tick > time.time()

    def test_start_scheduler_idempotent(self, engine_factory):
        svc = engine_factory(raw=True)
        svc.start_scheduler()
        first_tick = svc._next_schedule_tick
        svc.start_scheduler()
        assert svc._next_schedule_tick == first_tick

    def test_stop_scheduler(self, engine_factory):
        svc = engine_factory(raw=True)
        svc._scheduler_running = True
        svc.stop_scheduler()
        assert svc._scheduler_running is False

    def test_has_enabled_tasks(self, engine_factory):
        svc = engine_factory(raw=True)
        svc._task_executor.has_enabled_tasks.return_value = True
        assert svc.has_enabled_tasks() is True


# =====================================================================
# get_config / get_runtime_config
# =====================================================================


class TestGetConfig:
    def test_get_config_returns_copy(self, engine_factory):
        svc = engine_factory(raw=True)
        svc._ui_config = MagicMock()
        config = svc.get_config()
        svc._ui_config.model_copy.assert_called_once_with(deep=True)

    def test_get_runtime_config_returns_copy(self, engine_factory):
        svc = engine_factory(raw=True)
        svc._runtime_config = {"key": "value"}
        config = svc.get_runtime_config()
        assert config == {"key": "value"}
        config["key"] = "modified"
        assert svc._runtime_config["key"] == "value"


# =====================================================================
# record_log
# =====================================================================


class TestRecordLog:
    def test_record_log_basic(self, engine_factory):
        svc = engine_factory(raw=True)
        svc.record_log = ScheduleEngine.record_log.__get__(svc)
        svc.record_log("测试消息", level="INFO", source="backend")

    def test_record_log_no_side_effect(self, engine_factory):
        """record_log 不应再触发 _update_status_snapshot。"""
        svc = engine_factory(raw=True)
        svc.record_log = ScheduleEngine.record_log.__get__(svc)
        svc._update_status_snapshot = MagicMock()
        svc.record_log("网络检测", level="INFO", source="network")
        svc._update_status_snapshot.assert_not_called()


class TestNotifyNetworkStateChanged:
    def test_notify_network_state_changed(self, engine_factory):
        svc = engine_factory(raw=True)
        svc.notify_network_state_changed = ScheduleEngine.notify_network_state_changed.__get__(svc)
        svc._update_status_snapshot = MagicMock()
        svc.notify_network_state_changed()
        svc._update_status_snapshot.assert_called_once()


# =====================================================================
# list_logs
# =====================================================================


class TestListLogs:
    def test_list_logs_no_sink(self, engine_factory):
        svc = engine_factory(raw=True)
        assert svc.list_logs() == []

    def test_list_logs_with_sink(self, engine_factory):
        svc = engine_factory(raw=True)
        mock_sink = MagicMock()
        mock_sink.list_logs.return_value = [{"msg": "test"}]
        svc._dashboard_sink = mock_sink
        result = svc.list_logs(limit=10)
        assert result == [{"msg": "test"}]
        mock_sink.list_logs.assert_called_once_with(limit=10)

    def test_list_logs_zero_limit(self, engine_factory):
        svc = engine_factory(raw=True)
        assert svc.list_logs(limit=0) == []


# =====================================================================
# boot
# =====================================================================


class TestBoot:
    def test_boot_calls_start_monitoring(self, engine_factory):
        svc = engine_factory(raw=True)
        svc.start_monitoring = MagicMock(return_value=(True, "已启动"))
        svc.boot()
        svc.start_monitoring.assert_called_once()


# =====================================================================
# ws_drain_loop / drain_ws_queue
# =====================================================================


class TestWsDrain:
    @pytest.mark.asyncio
    async def test_drain_ws_queue_empty(self, engine_factory):
        svc = engine_factory(raw=True)
        svc._ws_manager = AsyncMock()
        await svc.drain_ws_queue()
        svc._ws_manager.broadcast.assert_not_called()

    @pytest.mark.asyncio
    async def test_drain_ws_queue_with_messages(self, engine_factory):
        svc = engine_factory(raw=True)
        svc._ws_manager = AsyncMock()
        svc._empty_broadcast_queue.append({"type": "status", "data": {}})
        svc._empty_broadcast_queue.append({"type": "log", "data": {}})
        await svc.drain_ws_queue()
        assert svc._ws_manager.broadcast.call_count == 2

    @pytest.mark.asyncio
    async def test_drain_ws_queue_broadcast_error(self, engine_factory):
        svc = engine_factory(raw=True)
        svc._ws_manager = AsyncMock()
        svc._ws_manager.broadcast.side_effect = RuntimeError("ws error")
        svc._empty_broadcast_queue.append({"type": "status", "data": {}})
        await svc.drain_ws_queue()
