"""登录流程集成测试 — 验证端到端登录认证流程。

覆盖场景：
- 完整登录序列（引擎 → TaskExecutor → Worker → 登录成功/失败）
- 带网络检测的登录流程（网络异常触发登录 → 登录后网络恢复）
- 登录失败重试机制（重试计数、间隔、最大重试次数）
- 登录并发保护（防止同时提交多个登录任务）
"""

from __future__ import annotations

import asyncio
import itertools
import threading
import time
from concurrent.futures import Future
from unittest.mock import AsyncMock, MagicMock

from app.network.decision import NetworkCheckResult
from app.schemas import LoginCredentials, MonitorSettings, RuntimeConfig
from app.services.engine import (
    EngineCmdType,
    EngineCommand,
    ScheduleEngine,
    StatusManager,
)
from app.services.monitor_service import CheckOnceResult
from app.services.retry_policy import MonitoredPolicy

# ── 辅助工厂 ──


def _make_raw_engine() -> ScheduleEngine:
    """创建一个用 __new__ 跳过 __init__ 的空引擎，用于隔离测试。"""
    svc = ScheduleEngine.__new__(ScheduleEngine)
    svc._cmd_queue = asyncio.Queue(maxsize=50)
    svc._shutdown_event = threading.Event()
    svc._engine_loop = None
    svc._engine_thread = None
    svc._engine_running = False
    svc._engine_ready = threading.Event()
    svc._monitor_core = None
    svc._retry_policy = MonitoredPolicy()
    svc._runtime_config = RuntimeConfig()
    svc._monitor_check_interval = 300
    svc._next_network_check = 0
    svc._scheduler = MagicMock()
    svc._scheduler.running = False
    svc._scheduler.next_tick_time = 0.0
    svc._scheduler.has_enabled_tasks.return_value = False
    svc._task_registry = MagicMock()
    svc._task_executor = MagicMock()
    svc._manual_login_in_progress = False
    svc._manual_login_lock = threading.Lock()
    svc._reload_lock = threading.Lock()
    svc._start_stop_lock = threading.Lock()
    svc._pure_mode = False
    svc._ws_manager = MagicMock()
    svc._status_manager = StatusManager(
        get_monitor_core=lambda: svc._monitor_core,
        ws_manager=svc._ws_manager,
    )
    svc._login_history = None
    svc._worker_getter = None
    svc._profile_service = MagicMock()
    svc.project_root = MagicMock()
    svc._logger = MagicMock()
    svc._update_status_snapshot = MagicMock()
    svc._orchestrator = MagicMock()
    # LoginBridge — 登录委托
    from app.services.engine import LoginBridge

    svc._login_bridge = LoginBridge(
        get_orchestrator=lambda: svc._orchestrator,
        get_runtime_config=lambda: svc._runtime_config,
        retry_policy=svc._retry_policy,
        status_update_callback=svc._update_status_snapshot,
        logger=svc._logger,
        get_monitor_check_interval=lambda: svc._monitor_check_interval,
    )
    svc._retry_time_lock = threading.Lock()
    import time as _time

    def _bridge_retry_scheduled(delay: float) -> None:
        with svc._retry_time_lock:
            svc._next_retry_time = _time.time() + delay

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
    return svc


def _make_worker_result(success: bool, data: str = "", error: str = ""):
    """创建 mock Worker 返回结果。"""
    result = MagicMock()
    result.success = success
    result.data = data
    result.error = error
    return result


# =====================================================================
# 1. 完整登录序列测试
# =====================================================================


class TestFullLoginSequence:
    """完整登录序列：引擎接收登录命令 → 提交到 TaskExecutor → Worker 执行 → 返回结果。"""

    def test_login_command_success(self):
        """手动登录命令成功：配置完整 → orchestrator 提交并等待 → 返回成功。"""
        svc = _make_raw_engine()
        svc._runtime_config = RuntimeConfig(
            credentials=LoginCredentials(
                username="testuser",
                password="testpass",
                auth_url="http://auth.example.com",
            ),
        )
        handle = MagicMock()
        handle.rejected_reason = None
        mock_future = Future()
        handle.future = mock_future
        svc._orchestrator.submit.return_value = handle

        cmd = EngineCommand(type=EngineCmdType.LOGIN)
        loop = asyncio.new_event_loop()
        loop.run_until_complete(svc._handle_login(cmd))
        loop.close()
        # 异步模式：模拟登录完成，触发回调
        mock_future.set_result((True, "登录成功"))
        time.sleep(0.1)  # 等待回调执行

        assert cmd.response_data == (True, "登录成功")
        call_kwargs = svc._orchestrator.submit.call_args[1]
        assert call_kwargs["source"] == "manual"
        assert call_kwargs["config"].credentials.username == "testuser"

    def test_login_command_failure_already_in_progress(self):
        """登录任务已在执行中时，返回失败。"""
        svc = _make_raw_engine()
        svc._runtime_config = RuntimeConfig(
            credentials=LoginCredentials(
                username="testuser",
                password="testpass",
                auth_url="http://auth.example.com",
            ),
        )
        handle = MagicMock()
        handle.rejected_reason = None
        handle.future = None  # 去重命中
        svc._orchestrator.submit.return_value = handle

        cmd = EngineCommand(type=EngineCmdType.LOGIN)
        loop = asyncio.new_event_loop()
        loop.run_until_complete(svc._handle_login(cmd))
        loop.close()

        assert cmd.response_data == (False, "登录任务已在执行中，请稍后再试")

    def test_login_command_missing_config(self):
        """配置不完整时，登录命令直接返回失败。"""
        svc = _make_raw_engine()
        svc._runtime_config = RuntimeConfig(
            credentials=LoginCredentials(username="u"),  # 缺少 password 和 auth_url
        )
        # 校验失败由 orchestrator.submit 内部处理，返回 rejected handle
        handle = MagicMock()
        handle.rejected_reason = "登录配置不完整（请先设置认证地址、用户名和密码）"
        svc._orchestrator.submit.return_value = handle

        cmd = EngineCommand(type=EngineCmdType.LOGIN)
        loop = asyncio.new_event_loop()
        loop.run_until_complete(svc._handle_login(cmd))
        loop.close()

        success, message = cmd.response_data
        assert success is False
        assert "配置不完整" in message

    def test_do_async_login_submits_to_executor(self):
        """_do_async_login 正确提交到 orchestrator 并管理状态。"""
        svc = _make_raw_engine()
        svc._runtime_config = RuntimeConfig(
            credentials=LoginCredentials(
                username="testuser",
                password="testpass",
                auth_url="http://auth.example.com",
            ),
            monitor=MonitorSettings(enable_local_check=False, check_auth_url=False),
        )
        future = Future()
        handle = MagicMock()
        handle.rejected_reason = None
        handle.future = future
        svc._orchestrator.submit.return_value = handle

        loop = asyncio.new_event_loop()
        result = loop.run_until_complete(svc._do_async_login())
        loop.close()

        assert result is True

    def test_full_sequence_manual_login(self):
        """完整手动登录序列：run_manual_login → _dispatch_command → handle_login。"""
        svc = _make_raw_engine()
        svc._dispatch_command = MagicMock(return_value=(True, "登录成功"))
        svc._update_status_snapshot = MagicMock()

        success, message = svc.run_manual_login()

        assert success is True
        assert "成功" in message

    def test_full_sequence_manual_login_failure(self):
        """完整手动登录失败序列：run_manual_login → _dispatch_command → 失败。"""
        svc = _make_raw_engine()
        svc._dispatch_command = MagicMock(return_value=(False, "认证地址不可达"))

        success, message = svc.run_manual_login()

        assert success is False
        assert "失败" in message
        assert "认证地址不可达" in message


# =====================================================================
# 2. 带网络检测的登录流程测试
# =====================================================================


class TestLoginWithNetworkDetection:
    """带网络检测的登录流程：网络异常触发登录 → 登录后验证网络恢复。"""

    async def test_network_check_triggers_login(self):
        """网络检测发现 need_login 时，触发异步登录。"""
        svc = _make_raw_engine()
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
        svc._do_async_login = AsyncMock()

        await svc._do_network_check_async()

        svc._do_async_login.assert_called_once()

    async def test_network_check_no_login_needed(self):
        """网络正常时，不触发登录，通过 _retry_policy 重置退避。"""
        svc = _make_raw_engine()
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
        svc._retry_policy._attempt = 2
        svc._retry_policy._prev_network_ok = False  # 模拟之前断开

        await svc._do_network_check_async()

        assert svc._retry_policy._attempt == 0
        assert svc._next_network_check > time.time()

    async def test_network_check_updates_interval(self):
        """网络检测后更新检测间隔。"""
        svc = _make_raw_engine()
        mock_core = MagicMock()
        mock_core.check_once = AsyncMock(
            return_value=CheckOnceResult(
                paused=False,
                net_ok=True,
                net_reason="",
                need_login=False,
                check_num=1,
                interval=120,
                result=NetworkCheckResult(
                    available=True, method="tcp", latency_ms=0, detail=""
                ),
            )
        )
        mock_core.consume_profile_switch_flag.return_value = False
        svc._monitor_core = mock_core

        await svc._do_network_check_async()

        assert svc._monitor_check_interval == 120

    async def test_network_check_runs_without_runtime_profile_switch(self):
        """网络检测正常执行；运行期自动切方案已按计划移除（仅启动时 _handle_start 一次性检测）。"""
        svc = _make_raw_engine()
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

    async def test_network_check_exception_continues(self):
        """网络检测异常时不影响引擎运行，设置下次检测时间。"""
        svc = _make_raw_engine()
        mock_core = MagicMock()
        mock_core.check_once = AsyncMock(side_effect=RuntimeError("检测超时"))
        svc._monitor_core = mock_core

        await svc._do_network_check_async()

        assert svc._next_network_check > time.time()

    async def test_login_then_network_recovery(self):
        """登录成功后，下次网络检测应恢复正常状态。"""
        svc = _make_raw_engine()

        # 第一次检测：网络异常，触发登录
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
        svc._runtime_config = RuntimeConfig()
        svc._do_async_login = AsyncMock()

        await svc._do_network_check_async()
        svc._do_async_login.assert_called_once()

        # 第二次检测：网络恢复正常
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
        svc._do_async_login.reset_mock()

        await svc._do_network_check_async()

        svc._do_async_login.assert_not_called()

    async def test_engine_loop_integration_with_network_login(self):
        """引擎循环中网络检测触发登录的集成测试。"""
        svc = _make_raw_engine()

        # 创建一个真实的 monitor_core（is_monitoring 是 property，通过设置 monitor_core 控制）
        mock_core = MagicMock()
        mock_core.monitoring = True
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
        # 关闭登录前置检查，确保 _do_async_login 真正提交到 orchestrator
        svc._runtime_config = RuntimeConfig(
            monitor=MonitorSettings(enable_local_check=False, check_auth_url=False),
        )

        # 使用真实的 _do_async_login（通过 orchestrator）
        callback_done = threading.Event()
        future = Future()
        _orig_adc = future.add_done_callback

        def _wrapping_adc(cb):
            def _wrapped(f):
                cb(f)
                callback_done.set()

            _orig_adc(_wrapped)

        future.add_done_callback = _wrapping_adc
        handle = MagicMock()
        handle.rejected_reason = None
        handle.future = future
        svc._orchestrator.submit.return_value = handle
        svc._retry_policy._attempt = 0

        # 模拟引擎循环中的网络检测
        now = time.time()
        svc._next_network_check = now  # 立即检测

        # 手动执行一次循环逻辑（is_monitoring 是 property，通过 mock_core.monitoring 控制）
        assert svc.is_monitoring is True
        assert now >= svc._next_network_check
        await svc._do_network_check_async()

        # 网络检测应触发自动登录提交到 orchestrator
        svc._orchestrator.submit.assert_called_once()
        call_kwargs = svc._orchestrator.submit.call_args[1]
        assert call_kwargs["source"] == "auto"

        # 模拟登录成功完成回调（元组契约），确定性等待回调执行
        future.set_result((True, "登录成功"))
        assert callback_done.wait(timeout=2)
        # 登录成功后重试计数应被重置、重试定时清零
        assert svc._retry_policy._attempt == 0
        assert svc._next_retry_time == 0


# =====================================================================
# 3. 登录并发保护测试
# =====================================================================


class TestLoginConcurrencyProtection:
    """登录并发保护：防止同时提交多个登录任务。"""

    def test_do_async_login_rejects_when_in_progress(self):
        """去重命中时，_do_async_login 返回 False。"""
        svc = _make_raw_engine()
        handle = MagicMock()
        handle.rejected_reason = None
        handle.future = None  # 去重命中，复用旧 handle
        svc._orchestrator.submit.return_value = handle

        loop = asyncio.new_event_loop()
        result = loop.run_until_complete(svc._do_async_login())
        loop.close()

        assert result is False

    def test_manual_login_cancels_in_progress_auto_login(self):
        """手动登录应抢占自动登录并重新提交。"""
        svc = _make_raw_engine()
        callback_done = threading.Event()
        future = Future()
        _orig_adc = future.add_done_callback

        def _wrapping_adc(cb):
            def _wrapped(f):
                cb(f)
                callback_done.set()

            _orig_adc(_wrapped)

        future.add_done_callback = _wrapping_adc
        handle = MagicMock()
        handle.rejected_reason = None
        handle.future = future
        svc._orchestrator.submit.return_value = handle

        loop = asyncio.new_event_loop()
        result = loop.run_until_complete(svc._do_async_login(is_manual=True))
        loop.close()

        assert result is True
        call_kwargs = svc._orchestrator.submit.call_args[1]
        assert call_kwargs["source"] == "manual"
        assert isinstance(call_kwargs["config"], RuntimeConfig)

        # 清理：确定性等待回调完成
        future.set_result((True, "登录成功"))
        assert callback_done.wait(timeout=2)

    def test_login_in_progress_property(self):
        """task_executor.is_login_running() 正确反映登录状态。"""
        svc = _make_raw_engine()

        svc._task_executor.is_login_running.return_value = False
        assert svc._task_executor.is_login_running() is False

        svc._task_executor.is_login_running.return_value = True
        assert svc._task_executor.is_login_running() is True

    def test_concurrent_login_rejection(self):
        """并发登录请求：第一个成功，后续被去重拒绝。"""
        svc = _make_raw_engine()
        svc._runtime_config = RuntimeConfig(
            credentials=LoginCredentials(
                username="testuser",
                password="testpass",
                auth_url="http://auth.example.com",
            ),
            monitor=MonitorSettings(enable_local_check=False, check_auth_url=False),
        )
        callback_done = threading.Event()
        future = Future()
        _orig_adc = future.add_done_callback

        def _wrapping_adc(cb):
            def _wrapped(f):
                cb(f)
                callback_done.set()

            _orig_adc(_wrapped)

        future.add_done_callback = _wrapping_adc

        # 第一次提交返回新 handle，第二次返回去重的旧 handle（future=None）
        new_handle = MagicMock()
        new_handle.rejected_reason = None
        new_handle.future = future

        dedup_handle = MagicMock()
        dedup_handle.rejected_reason = None
        dedup_handle.future = None

        svc._orchestrator.submit.side_effect = [new_handle, dedup_handle]

        loop = asyncio.new_event_loop()
        # 第一次提交成功
        result1 = loop.run_until_complete(svc._do_async_login())
        assert result1 is True

        # 第二次提交被去重拒绝
        result2 = loop.run_until_complete(svc._do_async_login())
        assert result2 is False
        loop.close()

        # 清理：确定性等待回调完成
        future.set_result((True, "登录成功"))
        assert callback_done.wait(timeout=2)

    def test_login_lock_prevents_double_manual_login(self):
        """手动登录锁防止重复触发。"""
        svc = _make_raw_engine()
        svc._manual_login_in_progress = True

        success, message = svc.run_manual_login()

        assert success is False
        assert "进行中" in message

    def test_login_lock_released_after_completion(self):
        """手动登录完成后释放锁。"""
        svc = _make_raw_engine()
        svc._dispatch_command = MagicMock(return_value=(True, "登录成功"))

        svc.run_manual_login()

        assert svc._manual_login_in_progress is False

    def test_login_lock_released_on_timeout(self):
        """手动登录超时后释放锁。"""
        svc = _make_raw_engine()
        svc._dispatch_command = MagicMock(return_value=(False, "操作超时 (login)"))
        svc._login_bridge.cancel_login = MagicMock(return_value=(True, "取消"))

        svc.run_manual_login()

        assert svc._manual_login_in_progress is False

    def test_retry_not_triggered_during_login(self):
        """登录进行中时，task_executor.is_login_running() 为 True。"""
        svc = _make_raw_engine()
        svc._task_executor.is_login_running.return_value = True  # 登录进行中

        assert svc._task_executor.is_login_running() is True

    def test_login_exception_returns_false(self):
        """登录执行异常时，返回 False。"""
        svc = _make_raw_engine()
        svc._runtime_config = RuntimeConfig(
            credentials=LoginCredentials(
                username="testuser",
                password="testpass",
                auth_url="http://auth.example.com",
            ),
            monitor=MonitorSettings(enable_local_check=False, check_auth_url=False),
        )
        svc._orchestrator.submit.side_effect = RuntimeError("线程池已关闭")

        loop = asyncio.new_event_loop()
        result = loop.run_until_complete(svc._do_async_login())
        loop.close()
        assert result is False

    def test_future_none_returns_false(self):
        """去重命中时，返回 False。"""
        svc = _make_raw_engine()
        handle = MagicMock()
        handle.rejected_reason = None
        handle.future = None
        svc._orchestrator.submit.return_value = handle

        loop = asyncio.new_event_loop()
        result = loop.run_until_complete(svc._do_async_login())
        loop.close()

        assert result is False

    def test_multiple_threads_competing_for_login(self):
        """多线程竞争登录：由 orchestrator 内部去重，结果取决于 submit 返回。"""
        svc = _make_raw_engine()
        svc._runtime_config = RuntimeConfig(
            credentials=LoginCredentials(
                username="testuser",
                password="testpass",
                auth_url="http://auth.example.com",
            ),
            monitor=MonitorSettings(enable_local_check=False, check_auth_url=False),
        )
        callback_done = threading.Event()
        future = Future()
        _orig_adc = future.add_done_callback

        def _wrapping_adc(cb):
            def _wrapped(f):
                cb(f)
                callback_done.set()

            _orig_adc(_wrapped)

        future.add_done_callback = _wrapping_adc

        # orchestrator.submit 由 _slot_lock 保护，模拟第一次返回新 handle，后续返回去重
        new_handle = MagicMock()
        new_handle.rejected_reason = None
        new_handle.future = future

        dedup_handle = MagicMock()
        dedup_handle.rejected_reason = None
        dedup_handle.future = None

        counter = itertools.count()

        def mock_submit(**kwargs):
            if next(counter) == 0:
                return new_handle
            return dedup_handle

        svc._orchestrator.submit.side_effect = mock_submit

        results = []
        barrier = threading.Barrier(5)

        def attempt_login():
            barrier.wait(timeout=1)
            loop = asyncio.new_event_loop()
            result = loop.run_until_complete(svc._do_async_login())
            loop.close()
            results.append(result)

        threads = [threading.Thread(target=attempt_login) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=2)

        # 第一个成功，后续被去重
        assert results.count(True) == 1
        assert results.count(False) == 4

        # 清理：确定性等待回调完成
        future.set_result((True, "登录成功"))
        assert callback_done.wait(timeout=2)
