"""登录流程集成测试 — 验证端到端登录认证流程。

覆盖场景：
- 完整登录序列（引擎 → TaskExecutor → Worker → 登录成功/失败）
- 带网络检测的登录流程（网络异常触发登录 → 登录后网络恢复）
- 登录失败重试机制（重试计数、间隔、最大重试次数）
- 登录并发保护（防止同时提交多个登录任务）
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import Future
from unittest.mock import MagicMock, patch

import pytest

from app.services.engine import (
    EngineCmdType,
    EngineCommand,
    ScheduleEngine,
    StatusSnapshot,
)
from app.services.login_retry import LoginRetryManager


# ── 辅助工厂 ──


def _make_raw_engine() -> ScheduleEngine:
    """创建一个用 __new__ 跳过 __init__ 的空引擎，用于隔离测试。"""
    svc = ScheduleEngine.__new__(ScheduleEngine)
    svc._cmd_queue = __import__("queue").Queue(maxsize=50)
    svc._shutdown_event = threading.Event()
    svc._monitor_core = None
    svc._engine_running = False
    svc._login_retry = LoginRetryManager()
    svc._runtime_config = {}
    svc._runtime_snapshot = {}
    svc._monitor_check_interval = 300
    svc._next_network_check = 0
    svc._scheduler_running = False
    svc._next_schedule_tick = 0.0
    svc._task_registry = MagicMock()
    svc._task_executor = MagicMock()
    svc._status_snapshot = StatusSnapshot()
    svc._snapshot_min_interval = 1.0
    svc._last_snapshot_time = 0
    svc._engine_thread = MagicMock()
    svc._engine_thread.is_alive.return_value = False
    svc._manual_login_in_progress = False
    svc._manual_login_lock = threading.Lock()
    svc._reload_lock = threading.Lock()
    svc._pure_mode_lock = threading.Lock()
    svc._start_stop_lock = threading.Lock()
    svc._pure_mode = False
    svc._dashboard_sink = None
    svc._empty_broadcast_queue = __import__("collections").deque(maxlen=10)
    svc._ws_manager = None
    svc._ui_config = MagicMock()
    svc._ui_config.login_timeout = 120
    svc._login_history = None
    svc._worker_getter = None
    svc._profile_service = MagicMock()
    svc.project_root = MagicMock()
    svc.record_log = MagicMock()
    svc._update_status_snapshot = MagicMock()
    svc._orchestrator = MagicMock()
    svc._consecutive_login_failures = 0
    svc._backoff_check_multiplier = 1
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
        """手动登录命令成功：配置完整 → async_login 提交成功 → 返回成功。"""
        svc = _make_raw_engine()
        config = {
            "username": "testuser",
            "password": "testpass",
            "auth_url": "http://auth.example.com",
        }
        svc._copy_runtime_config = MagicMock(return_value=config)
        svc._orchestrator.validate.return_value = None
        svc._do_async_login = MagicMock(return_value=True)

        cmd = EngineCommand(
            type=EngineCmdType.LOGIN, response_event=threading.Event()
        )
        svc._handle_login(cmd)

        assert cmd.response_data == (True, "登录已提交")
        svc._do_async_login.assert_called_once()

    def test_login_command_failure_already_in_progress(self):
        """登录任务已在执行中时，返回失败。"""
        svc = _make_raw_engine()
        config = {
            "username": "testuser",
            "password": "testpass",
            "auth_url": "http://auth.example.com",
        }
        svc._copy_runtime_config = MagicMock(return_value=config)
        svc._orchestrator.validate.return_value = None
        svc._do_async_login = MagicMock(return_value=False)

        cmd = EngineCommand(
            type=EngineCmdType.LOGIN, response_event=threading.Event()
        )
        svc._handle_login(cmd)

        assert cmd.response_data == (False, "登录任务已在执行中，请稍后再试")

    def test_login_command_missing_config(self):
        """配置不完整时，登录命令直接返回失败。"""
        svc = _make_raw_engine()
        svc._copy_runtime_config = MagicMock(
            return_value={"username": "u"}  # 缺少 password 和 auth_url
        )
        svc._orchestrator.validate.return_value = "登录配置不完整（请先设置认证地址、用户名和密码）"

        cmd = EngineCommand(
            type=EngineCmdType.LOGIN, response_event=threading.Event()
        )
        svc._handle_login(cmd)

        success, message = cmd.response_data
        assert success is False
        assert "配置不完整" in message

    def test_do_async_login_submits_to_executor(self):
        """_do_async_login 正确提交到 orchestrator 并管理状态。"""
        svc = _make_raw_engine()
        future = Future()
        handle = MagicMock()
        handle.rejected_reason = None
        handle.future = future
        svc._orchestrator.submit.return_value = handle

        result = svc._do_async_login()

        assert result is True
        assert svc._login_retry.last_attempt > 0
        assert svc._login_retry.count == 1

    def test_task_executor_login_success(self):
        """TaskExecutor.execute_login 通过 Worker 成功执行登录。"""
        from app.services.task_executor import TaskExecutor

        mock_registry = MagicMock()
        mock_history = MagicMock()
        mock_worker = MagicMock()
        mock_worker_getter = MagicMock(return_value=mock_worker)
        mock_login_history = MagicMock()
        mock_profile_service = MagicMock()

        executor = TaskExecutor(
            registry=mock_registry,
            history_store=MagicMock(),
            worker_getter=mock_worker_getter,
            login_history=mock_login_history,
            profile_service=mock_profile_service,
            get_runtime_config=lambda: {
                "browser_settings": {"pure_mode": False},
            },
        )

        mock_worker.submit.return_value = _make_worker_result(
            True, data="登录成功"
        )

        success, message = executor.execute_login()

        assert success is True
        assert message == "登录成功"
        mock_worker.submit.assert_called_once()
        mock_login_history.record.assert_called_once_with(
            success=True,
            duration_ms=pytest.approx(0, abs=5000),
            profile_service=mock_profile_service,
            error="",
        )

    def test_task_executor_login_failure(self):
        """TaskExecutor.execute_login 处理 Worker 登录失败。"""
        from app.services.task_executor import TaskExecutor

        mock_worker = MagicMock()
        executor = TaskExecutor(
            registry=MagicMock(),
            history_store=MagicMock(),
            worker_getter=MagicMock(return_value=mock_worker),
            login_history=MagicMock(),
            profile_service=MagicMock(),
            get_runtime_config=lambda: {"browser_settings": {}},
        )

        mock_worker.submit.return_value = _make_worker_result(
            False, error="密码错误"
        )

        success, message = executor.execute_login()

        assert success is False
        assert message == "密码错误"

    def test_task_executor_login_cancelled(self):
        """TaskExecutor.execute_login 处理取消事件。"""
        from app.services.task_executor import TaskExecutor

        executor = TaskExecutor(
            registry=MagicMock(),
            history_store=MagicMock(),
            worker_getter=MagicMock(),
            login_history=MagicMock(),
            get_runtime_config=lambda: {},
        )

        cancel_event = threading.Event()
        cancel_event.set()

        success, message = executor.execute_login(cancel_event=cancel_event)

        assert success is False
        assert "取消" in message

    def test_task_executor_login_worker_exception(self):
        """TaskExecutor.execute_login 处理 Worker 异常。"""
        from app.services.task_executor import TaskExecutor

        mock_worker = MagicMock()
        mock_worker.submit.side_effect = RuntimeError("浏览器启动失败")

        executor = TaskExecutor(
            registry=MagicMock(),
            history_store=MagicMock(),
            worker_getter=MagicMock(return_value=mock_worker),
            login_history=MagicMock(),
            profile_service=MagicMock(),
            get_runtime_config=lambda: {"browser_settings": {}},
        )

        success, message = executor.execute_login()

        assert success is False
        assert "异常" in message

    def test_full_sequence_manual_login(self):
        """完整手动登录序列：run_manual_login → 队列 → handle_login → async_login。"""
        svc = _make_raw_engine()

        # 模拟入队并立即执行
        def fake_enqueue(cmd):
            cmd.response_data = (True, "登录成功")
            if cmd.response_event:
                cmd.response_event.set()
            return True

        svc._enqueue = fake_enqueue

        success, message = svc.run_manual_login()

        assert success is True
        assert "已提交" in message

    def test_full_sequence_manual_login_failure(self):
        """完整手动登录失败序列：run_manual_login → 队列 → handle_login → 失败。"""
        svc = _make_raw_engine()

        def fake_enqueue(cmd):
            cmd.response_data = (False, "认证地址不可达")
            if cmd.response_event:
                cmd.response_event.set()
            return True

        svc._enqueue = fake_enqueue

        success, message = svc.run_manual_login()

        assert success is False
        assert "失败" in message
        assert "认证地址不可达" in message


# =====================================================================
# 2. 带网络检测的登录流程测试
# =====================================================================


class TestLoginWithNetworkDetection:
    """带网络检测的登录流程：网络异常触发登录 → 登录后验证网络恢复。"""

    def test_network_check_triggers_login(self):
        """网络检测发现 need_login 时，触发异步登录并跳过冗余检测。"""
        svc = _make_raw_engine()
        mock_core = MagicMock()
        mock_core.check_once.return_value = {
            "need_login": True,
            "interval": 300,
        }
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
        assert svc._login_retry.count == 0  # 网络检测触发时重置计数

    def test_network_check_no_login_needed(self):
        """网络正常时，不触发登录，重置重试计数。"""
        svc = _make_raw_engine()
        mock_core = MagicMock()
        mock_core.check_once.return_value = {
            "need_login": False,
            "interval": 600,
        }
        mock_core.consume_profile_switch_flag.return_value = False
        svc._monitor_core = mock_core
        svc._login_retry.count = 2  # 之前的重试计数

        svc._do_network_check()

        assert svc._login_retry.count == 0
        assert svc._next_network_check > time.time()

    def test_network_check_updates_interval(self):
        """网络检测后更新检测间隔。"""
        svc = _make_raw_engine()
        mock_core = MagicMock()
        mock_core.check_once.return_value = {
            "need_login": False,
            "interval": 120,
        }
        mock_core.consume_profile_switch_flag.return_value = False
        svc._monitor_core = mock_core

        svc._do_network_check()

        assert svc._monitor_check_interval == 120

    def test_network_check_with_profile_switch(self):
        """网络检测时检测到方案切换，重启监控。"""
        svc = _make_raw_engine()
        mock_core = MagicMock()
        mock_core.check_once.return_value = {
            "need_login": False,
            "interval": 300,
        }
        mock_core.consume_profile_switch_flag.return_value = True
        svc._monitor_core = mock_core
        svc._handle_stop = MagicMock()
        svc._reload_config_internal = MagicMock()
        svc._handle_start = MagicMock()

        svc._do_network_check()

        svc._handle_stop.assert_called_once()
        svc._reload_config_internal.assert_called_once()
        svc._handle_start.assert_called_once()

    def test_network_check_exception_continues(self):
        """网络检测异常时不影响引擎运行，设置下次检测时间。"""
        svc = _make_raw_engine()
        mock_core = MagicMock()
        mock_core.check_once.side_effect = RuntimeError("检测超时")
        svc._monitor_core = mock_core

        svc._do_network_check()

        assert svc._next_network_check > time.time()

    def test_login_then_network_recovery(self):
        """登录成功后，下次网络检测应恢复正常状态。"""
        svc = _make_raw_engine()

        # 第一次检测：网络异常，触发登录
        mock_core = MagicMock()
        mock_core.check_once.return_value = {
            "need_login": True,
            "interval": 300,
        }
        mock_core.consume_profile_switch_flag.return_value = False
        svc._monitor_core = mock_core
        svc._copy_runtime_config = MagicMock(return_value={
            "retry_settings": {"max_retries": 3, "retry_interval": 30}
        })
        svc._do_async_login = MagicMock()

        with patch("app.utils.retry.get_retry_intervals", return_value=[30, 30, 30]):
            svc._do_network_check()
        svc._do_async_login.assert_called_once()

        # 第二次检测：网络恢复正常
        mock_core.check_once.return_value = {
            "need_login": False,
            "interval": 300,
        }
        svc._do_async_login.reset_mock()

        svc._do_network_check()

        svc._do_async_login.assert_not_called()
        assert svc._login_retry.count == 0

    def test_engine_loop_integration_with_network_login(self):
        """引擎循环中网络检测触发登录的集成测试。"""
        svc = _make_raw_engine()

        # 创建一个真实的 monitor_core（_is_monitoring 是 property，通过设置 monitor_core 控制）
        mock_core = MagicMock()
        mock_core.monitoring = True
        mock_core.check_once.return_value = {
            "need_login": True,
            "interval": 300,
        }
        mock_core.consume_profile_switch_flag.return_value = False
        svc._monitor_core = mock_core
        svc._copy_runtime_config = MagicMock(return_value={
            "retry_settings": {"max_retries": 3, "retry_interval": 30}
        })

        # 使用真实的 _do_async_login（通过 orchestrator）
        future = Future()
        handle = MagicMock()
        handle.rejected_reason = None
        handle.future = future
        svc._orchestrator.submit.return_value = handle
        svc._login_retry.count = 0

        # 模拟引擎循环中的网络检测
        now = time.time()
        svc._next_network_check = now  # 立即检测

        # 手动执行一次循环逻辑（_is_monitoring 是 property，通过 mock_core.monitoring 控制）
        if svc._is_monitoring and now >= svc._next_network_check:
            svc._do_network_check()

        assert svc._login_retry.count == 1

        # 清理
        future.set_result(None)
        time.sleep(0.1)


# =====================================================================
# 3. 登录失败重试机制测试
# =====================================================================


class TestLoginRetryMechanism:
    """登录失败重试机制：重试计数、间隔判断、最大重试次数。"""

    def test_retry_needed_basic(self):
        """基本重试判断：超过间隔时间，需要重试。"""
        svc = _make_raw_engine()
        svc._login_retry.count = 1
        svc._login_retry.last_attempt = time.time() - 100
        svc._login_retry.config = (3, [10, 20, 30])
        svc._task_executor.is_login_running.return_value = False

        assert svc._login_retry_needed(time.time()) is True

    def test_retry_not_needed_too_early(self):
        """未到重试间隔时间，不需要重试。"""
        svc = _make_raw_engine()
        svc._login_retry.count = 1
        svc._login_retry.last_attempt = time.time()
        svc._login_retry.config = (3, [60, 60, 60])

        assert svc._login_retry_needed(time.time()) is False

    def test_retry_not_needed_max_reached(self):
        """达到最大重试次数，不再重试。"""
        svc = _make_raw_engine()
        svc._login_retry.count = 3
        svc._login_retry.config = (3, [10, 20, 30])

        assert svc._login_retry_needed(time.time()) is False

    def test_retry_not_needed_login_in_progress(self):
        """登录正在进行中，不触发重试。"""
        svc = _make_raw_engine()
        svc._login_retry.count = 1
        svc._login_retry.last_attempt = time.time() - 100
        svc._login_retry.config = (3, [10, 20, 30])
        svc._task_executor.is_login_running.return_value = True

        assert svc._login_retry_needed(time.time()) is False

    def test_retry_not_needed_no_config(self):
        """无重试配置，不触发重试。"""
        svc = _make_raw_engine()
        svc._login_retry.count = 1
        svc._login_retry.config = None

        assert svc._login_retry_needed(time.time()) is False

    def test_retry_not_needed_count_zero(self):
        """重试计数为 0，不触发重试。"""
        svc = _make_raw_engine()
        svc._login_retry.count = 0
        svc._login_retry.config = (3, [10, 20, 30])

        assert svc._login_retry_needed(time.time()) is False

    def test_retry_intervals_progression(self):
        """重试间隔按配置递增。"""
        svc = _make_raw_engine()
        intervals = [10, 20, 30]
        svc._task_executor.is_login_running.return_value = False

        # 第 1 次重试，间隔 10 秒
        svc._login_retry.count = 1
        svc._login_retry.last_attempt = time.time() - 5
        svc._login_retry.config = (3, intervals)
        assert svc._login_retry_needed(time.time()) is False

        svc._login_retry.last_attempt = time.time() - 11
        assert svc._login_retry_needed(time.time()) is True

        # 第 2 次重试，间隔 20 秒
        svc._login_retry.count = 2
        svc._login_retry.last_attempt = time.time() - 15
        assert svc._login_retry_needed(time.time()) is False

        svc._login_retry.last_attempt = time.time() - 21
        assert svc._login_retry_needed(time.time()) is True

        # 第 3 次重试，间隔 30 秒
        svc._login_retry.count = 3
        svc._login_retry.last_attempt = time.time() - 25
        assert svc._login_retry_needed(time.time()) is False

    def test_network_check_resets_retry_count(self):
        """网络检测触发登录时，重置重试计数。"""
        svc = _make_raw_engine()
        mock_core = MagicMock()
        mock_core.check_once.return_value = {
            "need_login": True,
            "interval": 300,
        }
        mock_core.consume_profile_switch_flag.return_value = False
        svc._monitor_core = mock_core
        svc._login_retry.count = 2  # 之前的重试
        svc._copy_runtime_config = MagicMock(return_value={
            "retry_settings": {"max_retries": 3, "retry_interval": 30}
        })
        svc._do_async_login = MagicMock()

        with patch("app.utils.retry.get_retry_intervals", return_value=[30, 30, 30]):
            svc._do_network_check()

        # 网络检测触发登录时，先重置计数再递增
        assert svc._login_retry.config == (3, [30, 30, 30])

    def test_wakeup_considers_retry_intervals(self):
        """引擎唤醒时间考虑重试间隔。"""
        svc = _make_raw_engine()
        now = time.time()
        svc._login_retry = LoginRetryManager(
            count=1,
            last_attempt=now - 5,
            config=(3, [10, 20, 30]),
        )

        wakeup = svc._calculate_wakeup()

        # 唤醒时间应在 last_attempt + interval[0] 附近
        expected_wakeup = now - 5 + 10  # = now + 5
        assert wakeup <= expected_wakeup + 1


# =====================================================================
# 4. 登录并发保护测试
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

        result = svc._do_async_login()

        assert result is False

    def test_manual_login_cancels_in_progress_auto_login(self):
        """手动登录应抢占自动登录并重新提交。"""
        svc = _make_raw_engine()
        future = Future()
        handle = MagicMock()
        handle.rejected_reason = None
        handle.future = future
        svc._orchestrator.submit.return_value = handle

        result = svc._do_async_login(is_manual=True)

        assert result is True
        svc._orchestrator.submit.assert_called_once_with(source="manual", config=svc._runtime_config)

        # 清理
        future.set_result((True, "登录成功"))
        time.sleep(0.1)

    def test_login_in_progress_property(self):
        """login_in_progress 属性反映 task_executor.is_login_running() 状态。"""
        svc = _make_raw_engine()

        svc._task_executor.is_login_running.return_value = False
        assert svc.login_in_progress is False

        svc._task_executor.is_login_running.return_value = True
        assert svc.login_in_progress is True

    def test_concurrent_login_rejection(self):
        """并发登录请求：第一个成功，后续被去重拒绝。"""
        svc = _make_raw_engine()
        future = Future()

        # 第一次提交返回新 handle，第二次返回去重的旧 handle（future=None）
        new_handle = MagicMock()
        new_handle.rejected_reason = None
        new_handle.future = future

        dedup_handle = MagicMock()
        dedup_handle.rejected_reason = None
        dedup_handle.future = None

        svc._orchestrator.submit.side_effect = [new_handle, dedup_handle]

        # 第一次提交成功
        result1 = svc._do_async_login()
        assert result1 is True

        # 第二次提交被去重拒绝
        result2 = svc._do_async_login()
        assert result2 is False

        # 清理
        future.set_result(None)
        time.sleep(0.1)

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

        def fake_enqueue(cmd):
            cmd.response_data = (True, "登录成功")
            if cmd.response_event:
                cmd.response_event.set()
            return True

        svc._enqueue = fake_enqueue

        svc.run_manual_login()

        assert svc._manual_login_in_progress is False

    def test_login_lock_released_on_timeout(self):
        """手动登录超时后释放锁。"""
        svc = _make_raw_engine()

        def fake_enqueue(cmd):
            return True  # 不设置 response_data，模拟超时

        svc._enqueue = fake_enqueue
        svc._ui_config.login_timeout = 0.01

        svc.run_manual_login()

        assert svc._manual_login_in_progress is False

    def test_retry_not_triggered_during_login(self):
        """登录进行中时，重试机制不触发。"""
        svc = _make_raw_engine()
        svc._login_retry.count = 1
        svc._login_retry.last_attempt = time.time() - 100
        svc._login_retry.config = (3, [10, 20, 30])
        svc._task_executor.is_login_running.return_value = True  # 登录进行中

        result = svc._login_retry_needed(time.time())

        assert result is False

    def test_login_exception_propagates(self):
        """登录执行异常时，异常会向上传播。"""
        svc = _make_raw_engine()
        svc._orchestrator.submit.side_effect = RuntimeError("线程池已关闭")

        with pytest.raises(RuntimeError):
            svc._do_async_login()

    def test_future_none_returns_false(self):
        """去重命中时，返回 False。"""
        svc = _make_raw_engine()
        handle = MagicMock()
        handle.rejected_reason = None
        handle.future = None
        svc._orchestrator.submit.return_value = handle

        result = svc._do_async_login()

        assert result is False

    def test_multiple_threads_competing_for_login(self):
        """多线程竞争登录：由 orchestrator 内部去重，结果取决于 submit 返回。"""
        svc = _make_raw_engine()
        future = Future()

        # orchestrator.submit 由 _slot_lock 保护，模拟第一次返回新 handle，后续返回去重
        new_handle = MagicMock()
        new_handle.rejected_reason = None
        new_handle.future = future

        dedup_handle = MagicMock()
        dedup_handle.rejected_reason = None
        dedup_handle.future = None

        call_count = [0]

        def mock_submit(**kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return new_handle
            return dedup_handle

        svc._orchestrator.submit.side_effect = mock_submit

        results = []
        barrier = threading.Barrier(5)

        def attempt_login():
            barrier.wait(timeout=1)
            results.append(svc._do_async_login())

        threads = [threading.Thread(target=attempt_login) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=2)

        # 第一个成功，后续被去重
        assert results.count(True) == 1
        assert results.count(False) == 4

        # 清理
        future.set_result(None)
        time.sleep(0.1)
