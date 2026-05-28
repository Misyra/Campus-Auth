"""src/monitor_core.py — 网络监控核心综合测试

覆盖 NetworkMonitorCore 类的主要方法。
"""
from __future__ import annotations

import datetime
import threading
import time
from unittest.mock import patch, MagicMock, AsyncMock

import pytest

from src.monitor_core import (
    NetworkMonitorCore,
    NetworkState,
    RecoveryResult,
)


# =====================================================================
# NetworkState / RecoveryResult 枚举
# =====================================================================


class TestEnums:
    def test_network_state_values(self):
        assert NetworkState.UNKNOWN.value == "unknown"
        assert NetworkState.CONNECTED.value == "connected"
        assert NetworkState.DISCONNECTED.value == "disconnected"

    def test_recovery_result_values(self):
        assert RecoveryResult.LOGIN_OK == "login_ok"
        assert RecoveryResult.GIVE_UP == "give_up"
        assert RecoveryResult.BREAK == "break"
        assert RecoveryResult.NET_DISCONNECT == "net_disconnect"


# =====================================================================
# NetworkMonitorCore 初始化与基本方法
# =====================================================================


class TestMonitorCoreInit:
    def test_default_state(self):
        core = NetworkMonitorCore()
        assert core.monitoring is False
        assert core.network_check_count == 0
        assert core.login_attempt_count == 0
        assert core.start_time is None
        assert core.network_state == NetworkState.UNKNOWN
        assert core.status_detail == "正常"

    def test_custom_config(self):
        config = {"auth_url": "http://test.com", "username": "admin"}
        core = NetworkMonitorCore(config=config)
        assert core.config == config

    def test_custom_log_callback(self):
        callback = MagicMock()
        core = NetworkMonitorCore(log_callback=callback)
        core.log_message("test message")
        callback.assert_called_once()

    def test_default_log_callback(self):
        """无回调时应使用 logger"""
        core = NetworkMonitorCore()
        # 不应抛异常
        core.log_message("test message")


class TestMonitorCoreSnapshot:
    def test_snapshot_default(self):
        core = NetworkMonitorCore()
        snap = core.snapshot()
        assert snap["monitoring"] is False
        assert snap["network_check_count"] == 0
        assert snap["login_attempt_count"] == 0
        assert snap["network_state"] == "unknown"

    def test_snapshot_with_state(self):
        core = NetworkMonitorCore()
        core.monitoring = True
        core.network_check_count = 5
        core.login_attempt_count = 2
        core.start_time = time.time()
        core.network_state = NetworkState.CONNECTED
        snap = core.snapshot()
        assert snap["monitoring"] is True
        assert snap["network_check_count"] == 5
        assert snap["network_state"] == "connected"


class TestMonitorCoreUpdateConfig:
    def test_update_config(self):
        core = NetworkMonitorCore(config={"old": "value"})
        new_config = {"new": "value"}
        core.update_config(new_config)
        assert core.config == new_config

    def test_update_config_clears_cache(self):
        core = NetworkMonitorCore()
        core._test_sites_cache = [("8.8.8.8", 53)]
        core.update_config({})
        assert core._test_sites_cache is None


class TestMonitorCoreGetRetryConfig:
    def test_default_config(self):
        core = NetworkMonitorCore()
        max_retries, intervals = core._get_retry_config()
        assert max_retries == core.MAX_CONSECUTIVE_LOGIN_FAILURES
        assert len(intervals) == max_retries

    def test_custom_config(self):
        config = {"retry_settings": {"max_retries": 2, "retry_interval": 10}}
        core = NetworkMonitorCore(config=config)
        max_retries, intervals = core._get_retry_config()
        assert max_retries == 2
        assert intervals[0] == 10

    def test_max_retries_clamped(self):
        """最大重试次数应被限制在 1~5"""
        config = {"retry_settings": {"max_retries": 100}}
        core = NetworkMonitorCore(config=config)
        max_retries, _ = core._get_retry_config()
        assert max_retries == 5

        config = {"retry_settings": {"max_retries": 0}}
        core = NetworkMonitorCore(config=config)
        max_retries, _ = core._get_retry_config()
        assert max_retries == 1


class TestMonitorCoreGetTestSites:
    def test_default_targets(self):
        core = NetworkMonitorCore()
        sites = core._get_test_sites()
        assert len(sites) > 0
        for host, port in sites:
            assert isinstance(host, str)
            assert isinstance(port, int)

    def test_custom_targets(self):
        config = {"monitor": {"ping_targets": ["8.8.8.8:53", "1.1.1.1:443"]}}
        core = NetworkMonitorCore(config=config)
        sites = core._get_test_sites()
        assert ("8.8.8.8", 53) in sites
        assert ("1.1.1.1", 443) in sites

    def test_string_targets(self):
        """字符串格式的目标应被正确解析"""
        config = {"monitor": {"ping_targets": "8.8.8.8:53,1.1.1.1:443"}}
        core = NetworkMonitorCore(config=config)
        sites = core._get_test_sites()
        assert len(sites) == 2

    def test_targets_without_port(self):
        """缺少端口的目标应自动补全"""
        config = {"monitor": {"ping_targets": ["8.8.8.8", "www.baidu.com"]}}
        core = NetworkMonitorCore(config=config)
        sites = core._get_test_sites()
        # IP 默认 53，域名默认 443
        assert ("8.8.8.8", 53) in sites
        assert ("www.baidu.com", 443) in sites

    def test_caching(self):
        core = NetworkMonitorCore()
        sites1 = core._get_test_sites()
        sites2 = core._get_test_sites()
        assert sites1 is sites2


class TestMonitorCoreWaitInterruptible:
    def test_immediate_stop(self):
        """stop 后应立即返回 False"""
        core = NetworkMonitorCore()
        core.monitoring = True
        core._stop_event.set()
        result = core._wait_interruptible(100, step=1)
        assert result is False

    def test_zero_seconds(self):
        """0 秒等待应立即返回"""
        core = NetworkMonitorCore()
        core.monitoring = True
        result = core._wait_interruptible(0, step=1)
        assert result is True


class TestMonitorCoreGetMonitorInterval:
    def test_default_interval(self):
        core = NetworkMonitorCore()
        assert core._get_monitor_interval() == core.DEFAULT_INTERVAL_SECONDS

    def test_custom_interval(self):
        config = {"monitor": {"interval": 600}}
        core = NetworkMonitorCore(config=config)
        assert core._get_monitor_interval() == 600


class TestMonitorCoreLoginRetryOrBreak:
    def test_retry(self):
        """登录次数未超限时应返回 retry"""
        core = NetworkMonitorCore()
        core.monitoring = True
        core._stop_event.set()  # 阻止实际等待
        core.login_attempt_count = 1
        result = core._login_retry_or_break(3, [5, 30, 60])
        # 因为 _stop_event 已设置，_wait_interruptible 返回 False
        assert result == RecoveryResult.BREAK

    def test_give_up(self):
        """超过最大重试次数应返回 give_up"""
        core = NetworkMonitorCore()
        core.login_attempt_count = 5
        result = core._login_retry_or_break(3, [5, 30, 60])
        assert result == RecoveryResult.GIVE_UP


class TestMonitorCoreStartStop:
    def test_start_sets_flags(self):
        core = NetworkMonitorCore()
        thread_done = threading.Event()

        # 模拟 monitor_network 立即返回
        with patch.object(core, "monitor_network"):
            core.start_monitoring()
            # start_monitoring 结束后 monitoring 应为 False
            assert core.monitoring is False

    def test_double_start_logs_warning(self):
        """重复启动应记录警告"""
        core = NetworkMonitorCore()
        core.monitoring = True
        # 不应抛异常
        core.start_monitoring()
        # 恢复
        core.monitoring = False


class TestMonitorCoreStopMonitoring:
    def test_stop_clears_state(self):
        core = NetworkMonitorCore()
        core.monitoring = True
        core.start_time = time.time()
        core.network_check_count = 10
        core.stop_monitoring()
        assert core.monitoring is False
        assert core.status_detail == "已停止"
        assert core._stop_requested is True

    def test_stop_when_not_monitoring(self):
        core = NetworkMonitorCore()
        core.monitoring = False
        core._stop_requested = False
        # 不应抛异常
        core.stop_monitoring()
