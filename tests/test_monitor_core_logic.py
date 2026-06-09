"""监控核心逻辑测试 — 覆盖纯逻辑方法。"""

from __future__ import annotations

from unittest.mock import MagicMock

from app.core.monitor_core import NetworkMonitorCore, NetworkState, RecoveryResult

# ── fixtures ──


def _make_core(config=None) -> NetworkMonitorCore:
    """创建测试用 NetworkMonitorCore 实例。"""
    return NetworkMonitorCore(config=config or {})


# ── snapshot ──


class TestSnapshot:
    """状态快照序列化。"""

    def test_initial_snapshot(self):
        """初始状态快照。"""
        core = _make_core()
        snap = core.snapshot()
        assert snap["monitoring"] is False
        assert snap["network_check_count"] == 0
        assert snap["login_attempt_count"] == 0
        assert snap["last_check_time"] is None
        assert snap["start_time"] is None
        assert snap["network_state"] == "unknown"
        assert snap["status_detail"] == "正常"

    def test_with_data(self):
        """有数据时快照正确。"""
        core = _make_core()
        core.monitoring = True
        core.network_check_count = 10
        core.login_attempt_count = 2
        core.start_time = 1000.0
        core.network_state = NetworkState.CONNECTED
        core.status_detail = "正常"
        snap = core.snapshot()
        assert snap["monitoring"] is True
        assert snap["network_check_count"] == 10
        assert snap["login_attempt_count"] == 2
        assert snap["start_time"] == 1000.0
        assert snap["network_state"] == "connected"
        assert snap["status_detail"] == "正常"

    def test_last_check_time_isoformat(self):
        """last_check_time 转换为 ISO 格式。"""
        import datetime

        core = _make_core()
        core.last_check_time = datetime.datetime(2026, 6, 1, 12, 0, 0)
        snap = core.snapshot()
        assert snap["last_check_time"] == "2026-06-01T12:00:00"


# ── _get_monitor_interval ──


class TestGetMonitorInterval:
    """监控间隔获取。"""

    def test_default_interval(self):
        """默认间隔 300 秒。"""
        core = _make_core()
        assert core._get_monitor_interval() == 300

    def test_custom_interval(self):
        """自定义间隔。"""
        core = _make_core({"monitor": {"interval": 60}})
        assert core._get_monitor_interval() == 60

    def test_zero_interval(self):
        """零间隔。"""
        core = _make_core({"monitor": {"interval": 0}})
        assert core._get_monitor_interval() == 0


# ── _get_retry_config ──


class TestGetRetryConfig:
    """重试配置获取。"""

    def test_default_config(self):
        """默认配置：3 次重试，间隔 5 秒。"""
        core = _make_core()
        max_retries, intervals = core._get_retry_config()
        assert max_retries == 3
        assert intervals == [5, 10, 20]

    def test_custom_retry_count(self):
        """自定义重试次数。"""
        core = _make_core({"retry_settings": {"max_retries": 2, "retry_interval": 10}})
        max_retries, intervals = core._get_retry_config()
        assert max_retries == 2
        assert intervals == [10, 20]

    def test_max_retries_clamped_to_5(self):
        """重试次数限制在 1-5。"""
        core = _make_core({"retry_settings": {"max_retries": 100}})
        max_retries, _ = core._get_retry_config()
        assert max_retries == 5

    def test_min_retries_clamped_to_1(self):
        """重试次数最小为 1。"""
        core = _make_core({"retry_settings": {"max_retries": 0}})
        max_retries, _ = core._get_retry_config()
        assert max_retries == 1

    def test_negative_retries_clamped(self):
        """负数重试次数被钳制。"""
        core = _make_core({"retry_settings": {"max_retries": -5}})
        max_retries, _ = core._get_retry_config()
        assert max_retries == 1

    def test_exponential_backoff(self):
        """间隔呈指数增长。"""
        core = _make_core({"retry_settings": {"max_retries": 4, "retry_interval": 5}})
        _, intervals = core._get_retry_config()
        assert intervals == [5, 10, 20, 40]


# ── _login_retry_or_break ──


class TestLoginRetryOrBreak:
    """登录重试决策。"""

    def test_first_attempt_returns_retry(self):
        """首次失败返回 retry。"""
        core = _make_core()
        core.login_attempt_count = 1
        # mock _wait_interruptible 避免真实等待
        core._wait_interruptible = MagicMock(return_value=True)
        result = core._login_retry_or_break(max_retries=3, intervals=[5, 10, 20])
        assert result == "retry"

    def test_within_retries_returns_retry(self):
        """在重试次数内返回 retry。"""
        core = _make_core()
        core.login_attempt_count = 2
        core._wait_interruptible = MagicMock(return_value=True)
        result = core._login_retry_or_break(max_retries=3, intervals=[5, 10, 20])
        assert result == "retry"

    def test_exceed_retries_returns_give_up(self):
        """超过重试次数返回 give_up。"""
        core = _make_core()
        core.login_attempt_count = 4
        result = core._login_retry_or_break(max_retries=3, intervals=[5, 10, 20])
        assert result == "give_up"

    def test_stop_during_wait_returns_break(self):
        """等待期间停止返回 break。"""
        core = _make_core()
        core.login_attempt_count = 1
        core._wait_interruptible = MagicMock(return_value=False)
        result = core._login_retry_or_break(max_retries=3, intervals=[5, 10, 20])
        assert result == "break"

    def test_resets_attempt_count_on_give_up(self):
        """give_up 时重置登录尝试计数。"""
        core = _make_core()
        core.login_attempt_count = 4
        core._login_retry_or_break(max_retries=3, intervals=[5, 10, 20])
        assert core.login_attempt_count == 0


# ── _wait_interruptible ──


class TestWaitInterruptible:
    """可中断等待。"""

    def test_returns_true_when_not_stopped(self):
        """未停止时返回 True。"""
        core = _make_core()
        core.monitoring = True
        result = core._wait_interruptible(0)
        assert result is True

    def test_returns_false_when_stopped(self):
        """停止时返回 False。"""
        core = _make_core()
        core.monitoring = False
        result = core._wait_interruptible(0)
        assert result is False

    def test_returns_false_when_stop_event_set(self):
        """stop_event 触发时返回 False。"""
        core = _make_core()
        core.monitoring = True
        core._stop_event.set()
        result = core._wait_interruptible(10, step=1)
        assert result is False


# ── log_message ──


class TestLogMessage:
    """日志消息分发。"""

    def test_uses_callback_when_set(self):
        """有 callback 时使用 callback。"""
        core = _make_core()
        callback = MagicMock()
        core.log_callback = callback
        core.log_message("test message", "INFO")
        callback.assert_called_once_with(
            "test message", "INFO", source="network", name="monitor_core"
        )

    def test_uses_logger_when_no_callback(self):
        """无 callback 时使用 logger。"""
        core = _make_core()
        core.log_callback = None
        # 不应抛异常
        core.log_message("test message", "INFO")


# ── NetworkState 枚举 ──


class TestNetworkState:
    """网络状态枚举。"""

    def test_values(self):
        """枚举值正确。"""
        assert NetworkState.UNKNOWN.value == "unknown"
        assert NetworkState.CONNECTED.value == "connected"
        assert NetworkState.DISCONNECTED.value == "disconnected"


# ── RecoveryResult 枚举 ──


class TestRecoveryResult:
    """恢复结果枚举。"""

    def test_values(self):
        """枚举值正确。"""
        assert RecoveryResult.LOGIN_OK.value == "login_ok"
        assert RecoveryResult.GIVE_UP.value == "give_up"
        assert RecoveryResult.BREAK.value == "break"
        assert RecoveryResult.NET_DISCONNECT.value == "net_disconnect"
        assert RecoveryResult.PAUSED.value == "paused"
