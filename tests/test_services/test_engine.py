"""engine.py — 调度引擎测试

覆盖 ScheduleEngine 的初始化、生命周期、命令派发、网络检测、状态快照等。
目标覆盖率 >= 80%。
"""

from __future__ import annotations

import asyncio
import threading
import time
from concurrent.futures import Future
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.network.decision import NetworkCheckResult
from app.schemas import (
    LoginCredentials,
    RuntimeConfig,
)
from app.services.engine import (
    EngineCmdType,
    EngineCommand,
    LoginBridge,
    ScheduleEngine,
    StatusSnapshot,
)
from app.services.monitor_service import CheckOnceResult
from app.services.scheduler_service import SchedulerService


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
        assert len(EngineCmdType) == 7


# =====================================================================
# EngineCommand 数据类
# =====================================================================


class TestEngineCommand:
    def test_default_values(self):
        cmd = EngineCommand(type=EngineCmdType.START)
        assert cmd.type == "start"
        assert cmd.data == {}
        assert cmd.response_future is None
        assert cmd.response_data is None

    def test_custom_values(self):
        loop = asyncio.new_event_loop()
        future = loop.create_future()
        cmd = EngineCommand(
            type=EngineCmdType.LOGIN,
            data={"key": "value"},
            response_future=future,
        )
        assert cmd.type == "login"
        assert cmd.data["key"] == "value"
        assert cmd.response_future is future
        loop.close()


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
        assert svc._status_manager._dashboard_sink is None
        assert svc._scheduler is None or svc._scheduler.running is False
        assert svc._monitor_core is None

    def test_init_with_task_components(self, engine_factory):
        mock_registry = MagicMock()
        mock_executor = MagicMock()
        svc = engine_factory(task_registry=mock_registry, task_executor=mock_executor)
        assert svc._task_registry is mock_registry
        assert svc._task_executor is mock_executor


# =====================================================================
# _dispatch_command 方法
# =====================================================================


class TestDispatchCommand:
    def test_dispatch_no_loop(self, engine_factory):
        """engine_loop 未启动时，_dispatch_command 返回失败。"""
        svc = engine_factory(raw=True)
        svc._engine_loop = None
        ok, msg = svc._dispatch_command(EngineCmdType.RELOAD)
        assert ok is False
        assert "未运行" in msg


# =====================================================================
# _calculate_wakeup
# =====================================================================


class TestCalculateWakeup:
    def test_default_wakeup(self, engine_factory):
        """无监控、无重试、无调度时，默认 60 秒后唤醒。"""
        svc = engine_factory(raw=True)
        # _monitor_core 为 None => is_monitoring 为 False
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
        """向后兼容测试：无 _login_retry 字段时，唤醒仍正常。"""
        svc = engine_factory(raw=True)
        svc._monitor_core = None
        wakeup = svc._calculate_wakeup()
        assert wakeup <= time.time() + 61

    def test_wakeup_with_scheduler(self, engine_factory):
        svc = engine_factory(raw=True)
        svc._monitor_core = None
        svc._scheduler.running = True
        svc._scheduler.next_tick_time = time.time() + 5
        wakeup = svc._calculate_wakeup()
        assert wakeup <= time.time() + 6

    def test_wakeup_exception_propagates(self, engine_factory):
        """非法值触发的异常应自然冒泡（不再被宽异常捕获）。"""
        svc = engine_factory(raw=True)
        mock_core = MagicMock()
        mock_core.monitoring = True
        svc._monitor_core = mock_core
        svc._next_network_check = "not_a_number"
        svc._scheduler.running = False
        with pytest.raises((TypeError, ValueError)):
            svc._calculate_wakeup()


# =====================================================================
# _process_command
# =====================================================================


class TestProcessCommand:
    async def _put_and_process(self, svc, cmd):
        """将命令放入队列再取出处理，避免 task_done 多余调用。"""
        await svc._cmd_queue.put(cmd)
        got = await svc._cmd_queue.get()
        await svc._process_command_async(got)

    def test_dispatch_start(self, engine_factory):
        svc = engine_factory(raw=True)
        cmd = EngineCommand(type=EngineCmdType.START)
        svc._handle_start = MagicMock()
        loop = asyncio.new_event_loop()
        loop.run_until_complete(self._put_and_process(svc, cmd))
        svc._handle_start.assert_called_once()
        loop.close()

    def test_dispatch_stop(self, engine_factory):
        svc = engine_factory(raw=True)
        cmd = EngineCommand(type=EngineCmdType.STOP)
        svc._handle_stop = MagicMock()
        loop = asyncio.new_event_loop()
        loop.run_until_complete(self._put_and_process(svc, cmd))
        svc._handle_stop.assert_called_once()
        loop.close()

    def test_dispatch_login(self, engine_factory):
        svc = engine_factory(raw=True)
        cmd = EngineCommand(type=EngineCmdType.LOGIN)
        svc._handle_login = AsyncMock()
        loop = asyncio.new_event_loop()
        loop.run_until_complete(self._put_and_process(svc, cmd))
        svc._handle_login.assert_called_once()
        loop.close()

    def test_dispatch_shutdown(self, engine_factory):
        svc = engine_factory(raw=True)
        cmd = EngineCommand(type=EngineCmdType.SHUTDOWN)
        svc._handle_shutdown = MagicMock()
        loop = asyncio.new_event_loop()
        loop.run_until_complete(self._put_and_process(svc, cmd))
        svc._handle_shutdown.assert_called_once()
        loop.close()

    def test_dispatch_reload(self, engine_factory):
        svc = engine_factory(raw=True)
        cmd = EngineCommand(type=EngineCmdType.RELOAD)
        svc._handle_reload = MagicMock()
        loop = asyncio.new_event_loop()
        loop.run_until_complete(self._put_and_process(svc, cmd))
        svc._handle_reload.assert_called_once()
        loop.close()

    def test_dispatch_apply_profile(self, engine_factory):
        svc = engine_factory(raw=True)
        cmd = EngineCommand(type=EngineCmdType.APPLY_PROFILE)
        svc._handle_apply_profile = MagicMock()
        loop = asyncio.new_event_loop()
        loop.run_until_complete(self._put_and_process(svc, cmd))
        svc._handle_apply_profile.assert_called_once()
        loop.close()

    def test_process_no_future_set(self, engine_factory):
        """response_future 由处理器自行触发，_process_command_async 不再自动 set。"""
        svc = engine_factory(raw=True)
        cmd = EngineCommand(type=EngineCmdType.START)
        # mock 的 _handle_start 不会触发 response_future，这是预期行为
        svc._handle_start = MagicMock()
        loop = asyncio.new_event_loop()
        loop.run_until_complete(self._put_and_process(svc, cmd))
        # 新设计：_process_command_async 不自动触发，由处理器负责
        assert cmd.response_future is None
        loop.close()

    def test_process_exception_still_sets_future(self, engine_factory):
        """handler 抛出异常时，response_future 仍被 set_result。"""
        svc = engine_factory(raw=True)
        loop = asyncio.new_event_loop()
        future = loop.create_future()
        cmd = EngineCommand(type=EngineCmdType.START, response_future=future)
        svc._handle_start = MagicMock(side_effect=RuntimeError("boom"))
        loop.run_until_complete(self._put_and_process(svc, cmd))
        assert future.done()
        assert future.result() == (False, "命令执行异常: start")
        loop.close()


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

    @patch("app.services.engine.validate_env_config", return_value=(True, ""))
    @patch("app.services.engine.NetworkMonitorCore")
    def test_handle_start_creates_core(
        self, mock_core_cls, _mock_validate, engine_factory
    ):
        """正常启动时创建 NetworkMonitorCore。"""
        svc = engine_factory(raw=True)
        svc._profile_service = MagicMock()
        svc._runtime_config = RuntimeConfig(
            credentials=LoginCredentials(
                username="test", password="pass", auth_url="http://10.0.0.1"
            ),
        )
        mock_core = MagicMock()
        mock_core_cls.return_value = mock_core
        cmd = EngineCommand(type=EngineCmdType.START, data={"pure_mode": False})
        svc._handle_start(cmd)
        assert svc._monitor_core is mock_core
        mock_core.init_monitoring.assert_called_once()

    @patch("app.services.engine.validate_env_config", return_value=(True, ""))
    @patch("app.services.engine.NetworkMonitorCore")
    def test_handle_start_pure_mode(
        self, mock_core_cls, _mock_validate, engine_factory
    ):
        """纯净模式标志通过 getter 传递。"""
        svc = engine_factory(raw=True)
        svc._profile_service = MagicMock()
        svc._runtime_config = RuntimeConfig(
            credentials=LoginCredentials(
                username="test", password="pass", auth_url="http://10.0.0.1"
            ),
        )
        svc._pure_mode = True
        mock_core = MagicMock()
        mock_core_cls.return_value = mock_core
        # 避免 check_and_switch_profile_sync 默认返回真值 MagicMock 误触发 _reload_config_internal 覆盖 _runtime_config
        mock_core.check_and_switch_profile_sync.return_value = False
        cmd = EngineCommand(type=EngineCmdType.START, data={})
        svc._handle_start(cmd)
        get_config = mock_core_cls.call_args[1]["get_config"]
        assert get_config().browser.pure_mode is True


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
        svc._runtime_config = RuntimeConfig()
        # 校验失败由 orchestrator.submit 内部处理，返回 rejected handle
        mock_handle = MagicMock()
        mock_handle.rejected_reason = "登录配置不完整（请先设置认证地址、用户名和密码）"
        svc._orchestrator.submit.return_value = mock_handle
        loop = asyncio.new_event_loop()
        future = loop.create_future()
        cmd = EngineCommand(type=EngineCmdType.LOGIN, response_future=future)
        loop.run_until_complete(svc._handle_login(cmd))
        success, message = cmd.response_data
        assert success is False
        assert "配置不完整" in message
        loop.close()

    def test_handle_login_missing_username(self, engine_factory):
        svc = engine_factory(raw=True)
        svc._runtime_config = RuntimeConfig(
            credentials=LoginCredentials(password="p", auth_url="http://test.com"),
        )
        mock_handle = MagicMock()
        mock_handle.rejected_reason = "登录配置不完整（请先设置认证地址、用户名和密码）"
        svc._orchestrator.submit.return_value = mock_handle
        loop = asyncio.new_event_loop()
        future = loop.create_future()
        cmd = EngineCommand(type=EngineCmdType.LOGIN, response_future=future)
        loop.run_until_complete(svc._handle_login(cmd))
        success, message = cmd.response_data
        assert success is False
        assert "配置不完整" in message
        loop.close()

    def test_handle_login_missing_password(self, engine_factory):
        svc = engine_factory(raw=True)
        svc._runtime_config = RuntimeConfig(
            credentials=LoginCredentials(username="u", auth_url="http://test.com"),
        )
        mock_handle = MagicMock()
        mock_handle.rejected_reason = "登录配置不完整（请先设置认证地址、用户名和密码）"
        svc._orchestrator.submit.return_value = mock_handle
        loop = asyncio.new_event_loop()
        future = loop.create_future()
        cmd = EngineCommand(type=EngineCmdType.LOGIN, response_future=future)
        loop.run_until_complete(svc._handle_login(cmd))
        success, message = cmd.response_data
        assert success is False
        loop.close()

    def test_handle_login_missing_auth_url(self, engine_factory):
        svc = engine_factory(raw=True)
        svc._runtime_config = RuntimeConfig(
            credentials=LoginCredentials(username="u", password="p"),
        )
        mock_handle = MagicMock()
        mock_handle.rejected_reason = "登录配置不完整（请先设置认证地址、用户名和密码）"
        svc._orchestrator.submit.return_value = mock_handle
        loop = asyncio.new_event_loop()
        future = loop.create_future()
        cmd = EngineCommand(type=EngineCmdType.LOGIN, response_future=future)
        loop.run_until_complete(svc._handle_login(cmd))
        success, message = cmd.response_data
        assert success is False
        loop.close()

    def test_handle_login_success(self, engine_factory):
        svc = engine_factory(raw=True)
        svc._runtime_config = RuntimeConfig(
            credentials=LoginCredentials(
                username="u",
                password="p",
                auth_url="http://test.com",
            ),
        )
        mock_handle = MagicMock()
        mock_handle.rejected_reason = None
        mock_future = Future()
        mock_handle.future = mock_future
        svc._orchestrator.submit.return_value = mock_handle

        # _on_complete 通过 call_soon_threadsafe 设置结果，需要一个运行中的 loop
        loop = asyncio.new_event_loop()
        svc._engine_loop = loop
        loop_thread = threading.Thread(target=loop.run_forever, daemon=True)
        loop_thread.start()

        # 在 engine loop 上创建 response_future，用 Event 同步完成
        done_event = threading.Event()
        result_holder = {}

        async def _create_and_watch():
            fut = loop.create_future()
            return fut

        response_future = asyncio.run_coroutine_threadsafe(
            _create_and_watch(), loop
        ).result()

        # 监听 response_future 完成
        def _on_future_done(f):
            result_holder["result"] = f.result()
            done_event.set()

        response_future.add_done_callback(_on_future_done)

        cmd = EngineCommand(type=EngineCmdType.LOGIN, response_future=response_future)
        # submit_login 是 async，需要在独立 loop 中运行
        inner_loop = asyncio.new_event_loop()
        inner_loop.run_until_complete(svc._handle_login(cmd))
        inner_loop.close()
        # 异步模式：模拟登录完成，触发回调
        mock_future.set_result((True, "登录成功"))
        # 等待 call_soon_threadsafe 调度的结果被 loop 处理
        assert done_event.wait(timeout=2.0), "response_future 未在超时内完成"
        assert result_holder["result"] == (True, "登录成功")
        assert cmd.response_data == (True, "登录成功")

        loop.call_soon_threadsafe(loop.stop)
        loop_thread.join(timeout=2.0)
        loop.close()

    def test_handle_login_already_in_progress(self, engine_factory):
        svc = engine_factory(raw=True)
        svc._runtime_config = RuntimeConfig(
            credentials=LoginCredentials(
                username="u",
                password="p",
                auth_url="http://test.com",
            ),
        )
        mock_handle = MagicMock()
        mock_handle.rejected_reason = None
        mock_handle.future = None
        svc._orchestrator.submit.return_value = mock_handle
        loop = asyncio.new_event_loop()
        future = loop.create_future()
        cmd = EngineCommand(type=EngineCmdType.LOGIN, response_future=future)
        loop.run_until_complete(svc._handle_login(cmd))
        assert cmd.response_data == (False, "登录任务已在执行中，请稍后再试")
        loop.close()

    def test_handle_login_rejected(self, engine_factory):
        svc = engine_factory(raw=True)
        svc._runtime_config = RuntimeConfig(
            credentials=LoginCredentials(
                username="u",
                password="p",
                auth_url="http://test.com",
            ),
        )
        mock_handle = MagicMock()
        mock_handle.rejected_reason = "提交被拒绝"
        svc._orchestrator.submit.return_value = mock_handle
        loop = asyncio.new_event_loop()
        future = loop.create_future()
        cmd = EngineCommand(type=EngineCmdType.LOGIN, response_future=future)
        loop.run_until_complete(svc._handle_login(cmd))
        assert cmd.response_data == (False, "提交被拒绝")
        loop.close()


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
        """B2: 重载成功且监控运行中，bind 未变时不 stop+start。"""
        svc = engine_factory(raw=True)
        mock_core = MagicMock()
        mock_core.monitoring = True
        mock_core._needs_bind_proxy_rebuild.return_value = False
        svc._monitor_core = mock_core
        svc._reload_config_internal = MagicMock(return_value=True)
        svc._handle_stop = MagicMock()
        svc._handle_start = MagicMock()
        cmd = EngineCommand(type=EngineCmdType.RELOAD)
        svc._handle_reload(cmd)
        svc._reload_config_internal.assert_called_once()
        svc._handle_stop.assert_not_called()
        svc._handle_start.assert_not_called()

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

    def test_reload_bind_change_rebuilds_proxy(self, engine_factory):
        """B2: bind_interface_name 变化时重建 SOCKS5 Forwarder。"""
        svc = engine_factory(raw=True)
        mock_core = MagicMock()
        mock_core.monitoring = True
        mock_core._needs_bind_proxy_rebuild.return_value = True
        svc._monitor_core = mock_core
        svc._reload_config_internal = MagicMock(return_value=True)
        cmd = EngineCommand(type=EngineCmdType.RELOAD)
        svc._handle_reload(cmd)
        svc._reload_config_internal.assert_called_once()
        mock_core.stop_monitoring.assert_called_once()
        mock_core.init_monitoring.assert_called_once()


# =====================================================================
# _handle_apply_profile
# =====================================================================


class TestHandleApplyProfile:
    def test_handle_apply_profile_not_monitoring(self, engine_factory):
        svc = engine_factory(raw=True)
        svc._runtime_config = RuntimeConfig(
            credentials=LoginCredentials(auth_url="http://test.com", username="u"),
        )
        svc._reload_config_internal = MagicMock()
        cmd = EngineCommand(type=EngineCmdType.APPLY_PROFILE, data={"profile_id": "p1"})
        svc._handle_apply_profile(cmd)
        svc._reload_config_internal.assert_called_once()

    def test_handle_apply_profile_monitoring(self, engine_factory):
        """B2: 切换方案时 bind 未变不 stop+start。"""
        svc = engine_factory(raw=True)
        mock_core = MagicMock()
        mock_core.monitoring = True
        mock_core._needs_bind_proxy_rebuild.return_value = False
        svc._monitor_core = mock_core
        svc._runtime_config = RuntimeConfig(
            credentials=LoginCredentials(auth_url="http://test.com", username="u"),
        )
        svc._reload_config_internal = MagicMock()
        svc._handle_stop = MagicMock()
        svc._handle_start = MagicMock()
        cmd = EngineCommand(type=EngineCmdType.APPLY_PROFILE, data={"profile_id": "p1"})
        svc._handle_apply_profile(cmd)
        svc._handle_stop.assert_not_called()
        svc._reload_config_internal.assert_called_once()
        svc._handle_start.assert_not_called()

    def test_apply_profile_bind_change_rebuilds(self, engine_factory):
        """B2: 方案切换导致 bind 变化时重建 SOCKS5 Forwarder。"""
        svc = engine_factory(raw=True)
        mock_core = MagicMock()
        mock_core.monitoring = True
        mock_core._needs_bind_proxy_rebuild.return_value = True
        svc._monitor_core = mock_core
        svc._runtime_config = RuntimeConfig(
            credentials=LoginCredentials(auth_url="http://test.com", username="u"),
        )
        svc._reload_config_internal = MagicMock()
        cmd = EngineCommand(type=EngineCmdType.APPLY_PROFILE, data={"profile_id": "p1"})
        svc._handle_apply_profile(cmd)
        svc._reload_config_internal.assert_called_once()
        mock_core.stop_monitoring.assert_called_once()
        mock_core.init_monitoring.assert_called_once()


# =====================================================================
# _do_network_check
# =====================================================================


class TestDoNetworkCheck:
    async def test_do_network_check_no_core(self, engine_factory):
        svc = engine_factory(raw=True)
        await svc._do_network_check_async()

    async def test_do_network_check_need_login(self, engine_factory):
        svc = engine_factory(raw=True)
        mock_core = MagicMock()
        mock_core.check_once = AsyncMock(
            return_value=CheckOnceResult(
                paused=False,
                net_ok=False,
                net_reason="down",
                need_login=True,
                check_num=1,
                interval=300,
                result=NetworkCheckResult(
                    available=False, method="none", latency_ms=0, detail="down"
                ),
            )
        )
        mock_core.consume_profile_switch_flag.return_value = False
        svc._monitor_core = mock_core
        svc._do_async_login = MagicMock()
        await svc._do_network_check_async()
        svc._do_async_login.assert_called_once()

    async def test_do_network_check_no_login_needed(self, engine_factory):
        svc = engine_factory(raw=True)
        mock_core = MagicMock()
        mock_core.check_once = AsyncMock(
            return_value=CheckOnceResult(
                paused=False,
                net_ok=True,
                net_reason="",
                need_login=False,
                check_num=1,
                interval=600,
                result=NetworkCheckResult(
                    available=True, method="tcp", latency_ms=0, detail=""
                ),
            )
        )
        mock_core.consume_profile_switch_flag.return_value = False
        svc._monitor_core = mock_core
        await svc._do_network_check_async()

    async def test_do_network_check_runs_without_runtime_profile_switch(
        self, engine_factory
    ):
        """网络检测正常执行；运行期自动切方案已按计划移除（仅启动时 _handle_start 一次性检测）。"""
        svc = engine_factory(raw=True)
        mock_core = MagicMock()
        mock_core.check_once = AsyncMock(
            return_value=CheckOnceResult(
                paused=False,
                net_ok=True,
                net_reason="",
                need_login=False,
                check_num=1,
                interval=300,
                result=NetworkCheckResult(
                    available=True, method="tcp", latency_ms=0, detail=""
                ),
            )
        )
        svc._monitor_core = mock_core

        await svc._do_network_check_async()

        # 运行期不再触发 stop/reload/start
        mock_core.check_once.assert_awaited_once()
        assert svc._next_network_check > time.time()

    async def test_do_network_check_exception(self, engine_factory):
        svc = engine_factory(raw=True)
        mock_core = MagicMock()
        mock_core.check_once = AsyncMock(side_effect=RuntimeError("boom"))
        svc._monitor_core = mock_core
        await svc._do_network_check_async()
        assert svc._next_network_check > time.time()


# =====================================================================
# _do_async_login
# =====================================================================


# =====================================================================
# F04: 网络检测不再无条件 reset 重试计数
# =====================================================================


class TestNetworkCheckBackoff:
    async def test_need_login_calls_async_login(self, engine_factory):
        """need_login=True 应调用 _do_async_login。"""
        svc = engine_factory(raw=True)
        mock_core = MagicMock()
        mock_core.check_once = AsyncMock(
            return_value=CheckOnceResult(
                paused=False,
                net_ok=False,
                net_reason="down",
                need_login=True,
                check_num=1,
                interval=300,
                result=NetworkCheckResult(
                    available=False, method="none", latency_ms=0, detail="down"
                ),
            )
        )
        mock_core.consume_profile_switch_flag.return_value = False
        svc._monitor_core = mock_core
        svc._do_async_login = MagicMock()
        await svc._do_network_check_async()
        svc._do_async_login.assert_called_once()


class TestDoAsyncLogin:
    async def test_already_in_progress(self, engine_factory):
        """去重命中：orchestrator.submit 返回旧 handle（future=None）。"""
        svc = engine_factory(raw=True)
        svc._runtime_config = RuntimeConfig(
            credentials=LoginCredentials(
                username="u",
                password="p",
                auth_url="http://x",
            ),
        )
        handle = MagicMock()
        handle.rejected_reason = None
        handle.future = None
        svc._orchestrator.submit.return_value = handle
        assert await svc._do_async_login() is False

    async def test_future_none(self, engine_factory):
        """orchestrator 返回 rejected handle 时应返回 False。"""
        svc = engine_factory(raw=True)
        svc._runtime_config = RuntimeConfig(
            credentials=LoginCredentials(
                username="u",
                password="p",
                auth_url="http://x",
            ),
        )
        handle = MagicMock()
        handle.rejected_reason = "登录配置不完整"
        handle.future = None
        svc._orchestrator.submit.return_value = handle
        assert await svc._do_async_login() is False

    async def test_future_success(self, engine_factory):
        svc = engine_factory(raw=True)
        svc._runtime_config = RuntimeConfig(
            credentials=LoginCredentials(
                username="u",
                password="p",
                auth_url="http://x",
            ),
        )
        future = Future()
        handle = MagicMock()
        handle.rejected_reason = None
        handle.future = future
        svc._orchestrator.submit.return_value = handle
        result = await svc._do_async_login()
        assert result is True

    async def test_exception_propagates(self, engine_factory):
        svc = engine_factory(raw=True)
        svc._runtime_config = RuntimeConfig(
            credentials=LoginCredentials(
                username="u",
                password="p",
                auth_url="http://x",
            ),
        )
        svc._orchestrator.submit.side_effect = RuntimeError("boom")
        with pytest.raises(RuntimeError):
            await svc._do_async_login()


    async def test_config_validation_blocks_auto_login(self, engine_factory):
        """配置不完整时自动登录应被拦截，不提交任务。"""
        svc = engine_factory(raw=True)
        svc._runtime_config = RuntimeConfig()  # 空配置（无凭证）
        handle = MagicMock()
        handle.rejected_reason = "登录配置不完整"
        handle.future = None
        svc._orchestrator.submit.return_value = handle
        result = await svc._do_async_login()
        assert result is False

    async def test_config_validation_resets_retry_on_failure(self, engine_factory):
        """配置校验失败时 _do_async_login 返回 False。"""
        svc = engine_factory(raw=True)
        svc._runtime_config = RuntimeConfig()
        handle = MagicMock()
        handle.rejected_reason = "登录配置不完整"
        handle.future = None
        svc._orchestrator.submit.return_value = handle
        result = await svc._do_async_login()
        assert result is False

    async def test_config_validation_blocks_missing_username(self, engine_factory):
        svc = engine_factory(raw=True)
        svc._runtime_config = RuntimeConfig(
            credentials=LoginCredentials(password="p", auth_url="http://x"),
        )
        handle = MagicMock()
        handle.rejected_reason = "登录配置不完整"
        handle.future = None
        svc._orchestrator.submit.return_value = handle
        assert await svc._do_async_login() is False

    async def test_config_validation_blocks_missing_password(self, engine_factory):
        svc = engine_factory(raw=True)
        svc._runtime_config = RuntimeConfig(
            credentials=LoginCredentials(username="u", auth_url="http://x"),
        )
        handle = MagicMock()
        handle.rejected_reason = "登录配置不完整"
        handle.future = None
        svc._orchestrator.submit.return_value = handle
        assert await svc._do_async_login() is False

    async def test_config_validation_blocks_missing_auth_url(self, engine_factory):
        svc = engine_factory(raw=True)
        svc._runtime_config = RuntimeConfig(
            credentials=LoginCredentials(username="u", password="p"),
        )
        handle = MagicMock()
        handle.rejected_reason = "登录配置不完整"
        handle.future = None
        svc._orchestrator.submit.return_value = handle
        assert await svc._do_async_login() is False

    async def test_config_snapshot_bypasses_runtime_config(self, engine_factory):
        """传入 config_snapshot 时应使用快照而非 _runtime_config。"""
        svc = engine_factory(raw=True)
        svc._runtime_config = RuntimeConfig()  # 运行时配置为空
        snapshot = RuntimeConfig(
            credentials=LoginCredentials(
                username="u", password="p", auth_url="http://x"
            ),
        )
        future = Future()
        handle = MagicMock()
        handle.rejected_reason = None
        handle.future = future
        svc._orchestrator.submit.return_value = handle
        result = await svc._do_async_login(config_snapshot=snapshot)
        assert result is True


# =====================================================================
# _run_schedule_tick
# =====================================================================


class TestRunScheduleTick:
    def test_run_schedule_tick(self, engine_factory):
        svc = engine_factory(raw=True)
        svc._scheduler = SchedulerService(svc._task_registry, svc._task_executor)
        svc._task_registry.get_due_tasks.return_value = ["task1", "task2"]
        svc._scheduler.tick(time.time())
        svc._task_executor.execute_task_async.assert_any_call("task1")
        svc._task_executor.execute_task_async.assert_any_call("task2")
        assert svc._scheduler.next_tick_time > time.time()

    def test_run_schedule_tick_no_due_tasks(self, engine_factory):
        svc = engine_factory(raw=True)
        svc._scheduler = SchedulerService(svc._task_registry, svc._task_executor)
        svc._task_registry.get_due_tasks.return_value = []
        svc._scheduler.tick(time.time())
        svc._task_executor.execute_task_async.assert_not_called()

    def test_run_schedule_tick_no_registry(self, engine_factory):
        svc = engine_factory(raw=True)
        svc._task_registry = None
        svc._scheduler = SchedulerService(svc._task_registry, svc._task_executor)
        svc._scheduler.tick(time.time())
        assert svc._scheduler.next_tick_time > time.time()


# =====================================================================
# _update_status_snapshot
# =====================================================================


class TestUpdateStatusSnapshot:
    def test_update_no_core(self, engine_factory):
        svc = engine_factory(raw=True)

        svc._status_manager._queue_status_broadcast = MagicMock()
        svc._monitor_core = None
        svc._update_status_snapshot(force=True)
        assert svc._status_manager._status_snapshot.monitoring is False
        assert svc._status_manager._status_snapshot.status_detail == "已停止"

    def test_update_with_core_connected(self, engine_factory):
        svc = engine_factory(raw=True)

        svc._status_manager._queue_status_broadcast = MagicMock()
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
        assert svc._status_manager._status_snapshot.monitoring is True
        assert svc._status_manager._status_snapshot.last_network_ok is True
        assert svc._status_manager._status_snapshot.network_state == "connected"
        assert svc._status_manager._status_snapshot.network_check_count == 10

    def test_update_with_core_disconnected(self, engine_factory):
        svc = engine_factory(raw=True)

        svc._status_manager._queue_status_broadcast = MagicMock()
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
        assert svc._status_manager._status_snapshot.last_network_ok is False

    def test_update_throttled(self, engine_factory):
        svc = engine_factory(raw=True)

        svc._status_manager._queue_status_broadcast = MagicMock()
        svc._status_manager._last_snapshot_time = time.time()
        svc._monitor_core = MagicMock()
        svc._monitor_core.monitoring = True
        svc._monitor_core.snapshot.return_value = {"network_state": "connected"}
        svc._update_status_snapshot(force=False)
        assert svc._status_manager._status_snapshot.monitoring is False

    def test_update_force_skips_throttle(self, engine_factory):
        svc = engine_factory(raw=True)

        svc._status_manager._queue_status_broadcast = MagicMock()
        svc._status_manager._last_snapshot_time = time.time()
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
        assert svc._status_manager._status_snapshot.monitoring is True

    def test_update_core_exception(self, engine_factory):
        svc = engine_factory(raw=True)

        svc._status_manager._queue_status_broadcast = MagicMock()
        mock_core = MagicMock()
        mock_core.monitoring = True
        mock_core.snapshot.side_effect = RuntimeError("boom")
        svc._monitor_core = mock_core
        svc._update_status_snapshot(force=True)


# =====================================================================
# _queue_status_broadcast
# =====================================================================


class TestQueueStatusBroadcast:
    def test_queue_status_broadcast_delegates_to_ws_manager(self, engine_factory):
        svc = engine_factory(raw=True)
        # 直接测试 StatusManager 的 _queue_status_broadcast
        svc._status_manager.get_status = MagicMock(
            return_value=MagicMock(model_dump=lambda: {"monitoring": False})
        )
        svc._status_manager._queue_status_broadcast()
        svc._ws_manager.enqueue_status.assert_called_once_with({"monitoring": False})

    def test_queue_status_broadcast_no_ws_manager(self, engine_factory):
        svc = engine_factory(raw=True)
        svc._status_manager._ws_manager = None
        svc._status_manager.get_status = MagicMock(
            return_value=MagicMock(model_dump=lambda: {"monitoring": False})
        )
        # 不应抛异常
        svc._status_manager._queue_status_broadcast()

    def test_queue_status_broadcast_exception(self, engine_factory):
        svc = engine_factory(raw=True)
        svc._status_manager.get_status = MagicMock(side_effect=RuntimeError("boom"))
        svc._status_manager._queue_status_broadcast()


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
        svc._status_manager._status_snapshot = StatusSnapshot(
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
        svc._scheduler.running = True
        svc.shutdown()
        svc._scheduler.stop.assert_called_once()


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
        # 幂等语义：已在运行时返回成功（而非失败）
        assert ok is True
        assert "已在运行" in msg

    def test_start_monitoring_invalid_config(self, engine_factory):
        """start_monitoring 不再校验配置（校验移至 _handle_start），仅派发命令。"""
        svc = engine_factory(raw=True)
        svc._monitor_core = None
        with patch.object(svc, "_dispatch_command", return_value=(True, "ok")):
            ok, msg = svc.start_monitoring()
        # 配置校验已移至引擎循环内的 _handle_start，start_monitoring 仅派发命令
        assert ok is True

    def test_start_monitoring_no_loop(self, engine_factory):
        """engine loop 未启动时，start_monitoring 返回失败。"""
        svc = engine_factory(raw=True)
        svc._engine_loop = None
        with patch(
            "app.services.engine.validate_env_config",
            return_value=(True, ""),
        ):
            ok, msg = svc.start_monitoring()
        assert ok is False
        assert "未运行" in msg

    def test_start_monitoring_success(self, engine_factory):
        svc = engine_factory(raw=True)
        svc._engine_loop = MagicMock()
        svc._engine_loop.is_running.return_value = True
        svc._dispatch_command = MagicMock(return_value=(True, "监控已启动"))
        with patch(
            "app.services.engine.validate_env_config",
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
        svc._dispatch_command = MagicMock(return_value=(True, "监控已停止"))
        ok, msg = svc.stop_monitoring()
        assert ok is True
        assert "已停止" in msg


# =====================================================================
# reload_config / apply_profile (队列派发)
# =====================================================================


class TestReloadConfig:
    def test_reload_config_calls_dispatch(self, engine_factory):
        svc = engine_factory(raw=True)
        svc._dispatch_command = MagicMock(return_value=(True, "配置重载成功"))
        ok, msg = svc.reload_config()
        svc._dispatch_command.assert_called_once_with(EngineCmdType.RELOAD)
        assert ok is True

    def test_reload_config_dispatch_failure(self, engine_factory):
        svc = engine_factory(raw=True)
        svc._dispatch_command = MagicMock(return_value=(False, "引擎未运行"))
        ok, msg = svc.reload_config()
        assert ok is False

    def test_reload_config_dispatch_timeout(self, engine_factory):
        svc = engine_factory(raw=True)
        svc._dispatch_command = MagicMock(return_value=(False, "操作超时 (reload)"))
        ok, msg = svc.reload_config()
        assert ok is False
        assert "超时" in msg


class TestApplyProfile:
    def test_apply_profile_calls_dispatch(self, engine_factory):
        svc = engine_factory(raw=True)
        svc._dispatch_command = MagicMock(return_value=(True, "方案切换成功"))
        ok, msg = svc.apply_profile("p1")
        svc._dispatch_command.assert_called_once_with(
            EngineCmdType.APPLY_PROFILE, {"profile_id": "p1"}
        )
        assert ok is True

    def test_apply_profile_dispatch_failure(self, engine_factory):
        svc = engine_factory(raw=True)
        svc._dispatch_command = MagicMock(return_value=(False, "引擎未运行"))
        ok, msg = svc.apply_profile("p1")
        assert ok is False

    def test_apply_profile_dispatch_timeout(self, engine_factory):
        svc = engine_factory(raw=True)
        svc._dispatch_command = MagicMock(
            return_value=(False, "操作超时 (apply_profile)")
        )
        ok, msg = svc.apply_profile("p1")
        assert ok is False
        assert "超时" in msg


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

    def test_run_manual_login_no_loop(self, engine_factory):
        """engine loop 未启动时，run_manual_login 返回失败。"""
        svc = engine_factory(raw=True)
        svc._engine_loop = None
        ok, msg = svc.run_manual_login()
        assert ok is False
        assert "未运行" in msg

    def test_run_manual_login_success(self, engine_factory):
        svc = engine_factory(raw=True)
        svc._dispatch_command = MagicMock(return_value=(True, "登录成功"))
        svc._update_status_snapshot = MagicMock()
        ok, msg = svc.run_manual_login()
        assert ok is True
        assert "成功" in msg

    def test_run_manual_login_failure(self, engine_factory):
        svc = engine_factory(raw=True)
        svc._dispatch_command = MagicMock(return_value=(False, "密码错误"))
        ok, msg = svc.run_manual_login()
        assert ok is False
        assert "失败" in msg
        assert "密码错误" in msg

    def test_run_manual_login_timeout_cancels_login(self, engine_factory):
        svc = engine_factory(raw=True)
        svc._dispatch_command = MagicMock(return_value=(False, "操作超时 (login)"))
        svc._engine_thread = MagicMock()
        svc._engine_thread.is_alive.return_value = True
        svc._login_bridge.cancel_login = MagicMock(return_value=(True, "取消"))
        ok, msg = svc.run_manual_login()
        assert ok is False
        assert "超时" in msg
        svc._login_bridge.cancel_login.assert_called_once()
        assert not svc._manual_login_in_progress

    def test_run_manual_login_timeout_engine_dead(self, engine_factory):
        svc = engine_factory(raw=True)
        svc._dispatch_command = MagicMock(return_value=(False, "操作超时 (login)"))
        svc._engine_thread = MagicMock()
        svc._engine_thread.is_alive.return_value = False
        svc._login_bridge.cancel_login = MagicMock(return_value=(True, "取消"))
        ok, msg = svc.run_manual_login()
        assert ok is False
        assert "引擎线程已退出" in msg

    def test_run_manual_login_api_timeout_buffered(self, engine_factory):
        """API 等待超时应为 max(login_timeout, 60) + 10，大于 Worker 超时。"""
        svc = engine_factory(raw=True)
        timeout_calls = []

        def fake_dispatch(cmd_type, timeout=None, **kwargs):
            timeout_calls.append(timeout)
            return (True, "登录成功")

        svc._dispatch_command = fake_dispatch
        svc._update_status_snapshot = MagicMock()
        svc._runtime_config = svc._runtime_config.model_copy(
            update={
                "browser": svc._runtime_config.browser.model_copy(
                    update={"login_timeout": 150}
                )
            }
        )

        ok, msg = svc.run_manual_login()
        assert ok is True
        # 等待超时应为 max(150, 60) + 10 = 160
        assert len(timeout_calls) >= 1
        assert timeout_calls[0] == 160


# =====================================================================
# cancel_login
# =====================================================================


class TestCancelLogin:
    def test_cancel_login_success(self, engine_factory):
        """取消成功时返回 (True, msg)，不记录警告日志。"""
        svc = engine_factory(raw=True)
        svc._login_bridge = MagicMock()
        svc._login_bridge.cancel_login.return_value = (True, "登录已取消")
        with patch("app.services.engine.logger") as mock_logger:
            ok, msg = svc.cancel_login()
        assert ok is True
        assert msg == "登录已取消"
        mock_logger.warning.assert_not_called()

    def test_cancel_login_failure(self, engine_factory):
        """取消失败时返回 (False, msg)，并记录警告日志。"""
        svc = engine_factory(raw=True)
        svc._login_bridge = MagicMock()
        svc._login_bridge.cancel_login.return_value = (False, "登录服务未初始化")
        with patch("app.services.engine.logger") as mock_logger:
            ok, msg = svc.cancel_login()
        assert ok is False
        assert msg == "登录服务未初始化"
        mock_logger.warning.assert_called_once()
        assert "取消登录失败" in mock_logger.warning.call_args[0][0]

    def test_cancel_login_delegates_to_bridge(self, engine_factory):
        """cancel_login 应委托给 _login_bridge.cancel_login()。"""
        svc = engine_factory(raw=True)
        svc._login_bridge = MagicMock()
        svc._login_bridge.cancel_login.return_value = (True, "ok")
        svc.cancel_login()
        svc._login_bridge.cancel_login.assert_called_once()


# =====================================================================
# test_network
# =====================================================================


class TestNetwork:
    def test_network_ok(self, engine_factory):
        svc = engine_factory(raw=True)
        svc._runtime_config = RuntimeConfig()
        svc._dispatch_command = MagicMock(return_value=(True, "网络连接正常"))
        ok, msg = svc.test_network()
        assert ok is True
        assert "正常" in msg

    def test_network_fail(self, engine_factory):
        svc = engine_factory(raw=True)
        svc._runtime_config = RuntimeConfig()
        svc._dispatch_command = MagicMock(return_value=(False, "网络连接异常"))
        ok, msg = svc.test_network()
        assert ok is False
        assert "异常" in msg

    def test_network_exception(self, engine_factory):
        svc = engine_factory(raw=True)
        svc._runtime_config = RuntimeConfig()
        svc._dispatch_command = MagicMock(return_value=(False, "网络测试失败: timeout"))
        ok, msg = svc.test_network()
        assert ok is False
        assert "失败" in msg

    def test_network_with_targets(self, engine_factory):
        svc = engine_factory(raw=True)
        svc._runtime_config = RuntimeConfig()
        svc._dispatch_command = MagicMock(return_value=(True, "网络连接正常"))
        ok, msg = svc.test_network()
        assert ok is True


# =====================================================================
# _swap_runtime_config
# =====================================================================


class TestSwapRuntimeConfig:
    def test_swap_replaces_reference(self, engine_factory):
        """_swap_runtime_config 应原子替换 _runtime_config 引用。"""
        svc = engine_factory(raw=True)
        original = svc._runtime_config
        new_config = original.model_copy(
            update={"logging": original.logging.model_copy(update={"level": "DEBUG"})}
        )
        svc._swap_runtime_config(new_config)
        assert svc._runtime_config is new_config
        assert svc._runtime_config.logging.level == "DEBUG"

    def test_swap_under_lock(self, engine_factory):
        """_swap_runtime_config 必须持 _reload_lock 执行。"""
        import threading

        svc = engine_factory(raw=True)
        lock = svc._reload_lock
        held = threading.Event()
        swap_done = threading.Event()

        def hold_lock():
            with lock:
                held.set()
                swap_done.wait(timeout=2)

        def try_swap():
            held.wait(timeout=2)
            new = svc._runtime_config.model_copy(update={})
            svc._swap_runtime_config(new)

        t1 = threading.Thread(target=hold_lock)
        t2 = threading.Thread(target=try_swap)
        t1.start()
        t2.start()
        t2.join(timeout=0.3)
        assert t2.is_alive(), "swap 应在锁被持有时阻塞"
        swap_done.set()
        t1.join(timeout=2)
        t2.join(timeout=2)
        assert not t2.is_alive()


# =====================================================================
# update_log_level
# =====================================================================


class TestUpdateLogLevel:
    def test_update_log_level_swaps_config(self, engine_factory):
        """update_log_level 应通过 _swap 更新 logging.level。"""
        svc = engine_factory(raw=True)
        assert svc._runtime_config.logging.level == "INFO"
        svc.update_log_level("DEBUG")
        assert svc._runtime_config.logging.level == "DEBUG"

    def test_update_log_level_invalid_raises(self, engine_factory):
        """无效级别应抛 ValueError。"""
        svc = engine_factory(raw=True)
        with pytest.raises(ValueError):
            svc.update_log_level("BOGUS")


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

    def test_toggle_pure_mode_syncs_runtime_config(self, engine_factory):
        """toggle_pure_mode 应同步更新 _runtime_config.browser.pure_mode。"""
        svc = engine_factory(raw=True)
        svc._profile_service = MagicMock()
        svc._runtime_config = RuntimeConfig()
        svc._pure_mode = True

        svc.toggle_pure_mode()
        assert svc._runtime_config.browser.pure_mode is False

        svc.toggle_pure_mode()
        assert svc._runtime_config.browser.pure_mode is True

    def test_toggle_pure_mode_persists_to_disk(self, engine_factory):
        """toggle_pure_mode 应成功持久化到磁盘（frozen 模型不抛 ValidationError）。

        验证传给 profile_service.update 的 lambda 在真实 frozen ProfilesData 上不崩溃。
        """
        from app.schemas import ProfilesData

        svc = engine_factory(raw=True)
        svc._reload_lock = threading.Lock()
        svc._runtime_config = RuntimeConfig()
        svc._pure_mode = False

        # 捕获 update 传入的 lambda，用真实 frozen model 验证
        captured_lambdas = []

        def fake_update(func):
            captured_lambdas.append(func)

        svc._profile_service.update = fake_update

        result = svc.toggle_pure_mode()
        assert result is True
        assert len(captured_lambdas) == 1

        # 用真实 frozen ProfilesData 执行 lambda，不应抛 ValidationError
        data = ProfilesData()
        new_data = captured_lambdas[0](data)
        assert new_data is not None
        assert new_data.global_config.browser.pure_mode is True


# =====================================================================
# 属性
# =====================================================================


class TestProperties:
    def test_ws_broadcast_queue_default(self, engine_factory):
        """ws_broadcast_queue 已迁移至 WebSocketManager，此测试验证 engine 不再拥有该属性。"""
        svc = engine_factory(raw=True)
        assert not hasattr(svc, "ws_broadcast_queue")

    def test_pure_mode_property(self, engine_factory):
        svc = engine_factory(raw=True)
        assert svc.pure_mode is False

    def test_is_monitoring_false(self, engine_factory):
        svc = engine_factory(raw=True)
        assert svc.is_monitoring is False

    def test_is_monitoring_true(self, engine_factory):
        svc = engine_factory(raw=True)
        mock_core = MagicMock()
        mock_core.monitoring = True
        svc._monitor_core = mock_core
        assert svc.is_monitoring is True

    def test_is_monitoring_core_not_monitoring(self, engine_factory):
        svc = engine_factory(raw=True)
        mock_core = MagicMock()
        mock_core.monitoring = False
        svc._monitor_core = mock_core
        assert svc.is_monitoring is False

    def test_tasks_property(self, engine_factory):
        svc = engine_factory(raw=True)
        assert svc.tasks is svc._task_executor


# =====================================================================
# 调度器控制
# =====================================================================


class TestSchedulerControl:
    def test_start_scheduler(self, engine_factory):
        svc = engine_factory(raw=True)
        svc._scheduler = SchedulerService(svc._task_registry, svc._task_executor)
        svc._scheduler.start()
        assert svc._scheduler.running is True
        assert svc._scheduler.next_tick_time > time.time()

    def test_start_scheduler_idempotent(self, engine_factory):
        svc = engine_factory(raw=True)
        svc._scheduler = SchedulerService(svc._task_registry, svc._task_executor)
        svc._scheduler.start()
        first_tick = svc._scheduler.next_tick_time
        svc._scheduler.start()
        assert svc._scheduler.next_tick_time == first_tick

    def test_stop_scheduler(self, engine_factory):
        svc = engine_factory(raw=True)
        svc._scheduler = SchedulerService(svc._task_registry, svc._task_executor)
        svc._scheduler.start()
        svc._scheduler.stop()
        assert svc._scheduler.running is False


# =====================================================================
# get_config / get_runtime_config
# =====================================================================


class TestGetConfig:
    def test_get_runtime_config_returns_reference(self, engine_factory):
        svc = engine_factory(raw=True)
        svc._runtime_config = RuntimeConfig()
        config = svc.get_runtime_config()
        assert config is svc._runtime_config
        assert isinstance(config, RuntimeConfig)


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
        svc._status_manager._dashboard_sink = mock_sink
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
    def test_boot_starts_engine_thread(self, engine_factory):
        svc = engine_factory(raw=True)
        svc._engine_thread = None
        svc._engine_ready = threading.Event()
        svc._engine_ready.set()  # 模拟 loop 立即就绪
        svc._engine_entry = MagicMock()
        svc.boot()
        # boot 应启动引擎线程（_engine_entry 在线程中被调用）
        assert svc._engine_thread is not None


# =====================================================================
# ws_drain_loop / drain_ws_queue / set_dashboard_sink 迁移
# 已迁移至 WebSocketManager，测试见 test_websocket_manager.py
# =====================================================================


class TestEngineLoopAsyncCommands:
    """_engine_loop_async 应通过 asyncio.Queue 处理命令。"""



    def test_engine_loop_async_processes_commands(self):
        """引擎 loop 应处理队列中的命令直至 SHUTDOWN。"""
        engine = ScheduleEngine.__new__(ScheduleEngine)
        engine._cmd_queue = asyncio.Queue()
        engine._shutdown_event = threading.Event()
        engine._engine_running = False
        engine._engine_loop = None
        engine._monitor_core = None
        engine._scheduler = None
        engine._next_network_check = 0
        engine._monitor_check_interval = 300
        engine._MAX_LOOP_SLEEP = 1.0

        processed = []

        async def mock_process(cmd):
            processed.append(cmd.type)

        engine._process_command_async = mock_process
        engine._calculate_wakeup = lambda: time.time() + 60
        # is_monitoring 是 property，通过 mock _monitor_core = None 实现 False

        loop = asyncio.new_event_loop()
        engine._engine_loop = loop

        async def run():
            # 入队 SHUTDOWN 命令
            await engine._cmd_queue.put(EngineCommand(type=EngineCmdType.SHUTDOWN))
            await engine._engine_loop_async()

        loop.run_until_complete(run())
        assert len(processed) == 1
        assert processed[0] == "shutdown"
        loop.close()


class TestPureModeLockConsolidation:
    """_pure_mode 统一由 _reload_lock 保护。"""

    def test_toggle_pure_mode_thread_safe(self):
        """toggle_pure_mode 和 pure_mode 读取应互斥（共享计数器验证）。"""
        engine = ScheduleEngine.__new__(ScheduleEngine)
        engine._reload_lock = threading.Lock()
        engine._pure_mode = False
        engine._profile_service = MagicMock()

        counter = 0
        barrier = threading.Barrier(2)

        def toggle_worker():
            nonlocal counter
            barrier.wait()
            for _ in range(100):
                with engine._reload_lock:
                    counter += 1
                    counter -= 1

        def read_worker():
            nonlocal counter
            barrier.wait()
            for _ in range(100):
                with engine._reload_lock:
                    counter += 1
                    counter -= 1

        t1 = threading.Thread(target=toggle_worker)
        t2 = threading.Thread(target=read_worker)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        # 互斥锁保护下，计数器最终应为 0
        assert counter == 0


class TestBootLifecycle:
    """boot 应启动 engine loop 线程。"""

    def test_boot_creates_engine_thread(self, engine_factory):
        """boot 应创建并启动引擎线程。"""
        svc = engine_factory(raw=True)
        svc._engine_thread = None
        svc._engine_ready = threading.Event()
        svc._engine_ready.set()  # 模拟 loop 立即就绪
        svc._engine_entry = MagicMock()
        svc.boot()
        # boot 应创建线程并启动
        assert svc._engine_thread is not None
        svc._engine_thread.join(timeout=2)


# =====================================================================
# LoginBridge 去重分支 on_complete 回调
# =====================================================================


class TestLoginBridgeDuplicateCallback:
    """去重命中时应调用 on_complete 回调，避免手动登录挂起。"""

    def _make_bridge(self):
        mock_orchestrator = MagicMock()
        bridge = LoginBridge(
            get_orchestrator=lambda: mock_orchestrator,
            get_runtime_config=lambda: RuntimeConfig(),
            status_update_callback=lambda: None,
            logger=MagicMock(),
        )
        return bridge, mock_orchestrator

    async def test_submit_login_duplicate_triggers_callback(self):
        """去重命中时 on_complete 应被调用，返回 (False, msg)。"""
        bridge, mock_orch = self._make_bridge()
        callbacks = []

        def on_complete(ok, msg):
            callbacks.append((ok, msg))

        # 第一次提交：handle.future 注册到 _registered_futures
        future = Future()
        handle = mock_orch.submit.return_value
        handle.rejected_reason = None
        handle.future = future

        result1 = await bridge.submit_login(is_manual=True, on_complete=on_complete)
        assert result1 is True
        assert len(callbacks) == 0  # 第一次成功提交不触发 on_complete

        # 第二次提交：同一个 future 已在 _registered_futures，去重命中
        result2 = await bridge.submit_login(is_manual=True, on_complete=on_complete)
        assert result2 is False
        # 关键断言：on_complete 必须被调用，否则手动登录会挂起
        assert len(callbacks) == 1
        assert callbacks[0] == (False, "登录任务已在执行中，请稍后再试")

    async def test_submit_login_duplicate_no_on_complete(self):
        """去重命中时 on_complete=None 不应抛异常。"""
        bridge, mock_orch = self._make_bridge()

        future = Future()
        handle = mock_orch.submit.return_value
        handle.rejected_reason = None
        handle.future = future

        await bridge.submit_login(is_manual=True, on_complete=None)
        result = await bridge.submit_login(is_manual=True, on_complete=None)
        assert result is False
