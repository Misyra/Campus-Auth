from __future__ import annotations

import asyncio
import threading
import time
import warnings
from unittest.mock import MagicMock, patch

from src.monitor_core import NetworkMonitorCore


class TestNetworkMonitorCoreInit:

    def test_default_config(self):
        core = NetworkMonitorCore()
        assert core.monitoring is False
        assert core.network_check_count == 0
        assert core.login_attempt_count == 0

    def test_custom_config(self):
        config = {"monitor": {"interval": 60}}
        core = NetworkMonitorCore(config=config)
        assert core.config["monitor"]["interval"] == 60

    def test_snapshot(self):
        core = NetworkMonitorCore()
        snap = core.snapshot()
        assert "monitoring" in snap
        assert "network_check_count" in snap


class TestRetryConfig:

    def test_default_retry(self):
        core = NetworkMonitorCore()
        max_retries, intervals = core._get_retry_config()
        assert max_retries >= 1
        assert len(intervals) == max_retries

    def test_custom_retry(self):
        config = {"retry_settings": {"max_retries": 2, "retry_interval": 10}}
        core = NetworkMonitorCore(config=config)
        max_retries, intervals = core._get_retry_config()
        assert max_retries == 2
        assert intervals[0] == 10


class TestBuildTestSites:

    def test_default_targets(self):
        core = NetworkMonitorCore()
        sites = core._build_test_sites()
        assert len(sites) > 0
        assert all(isinstance(s, tuple) and len(s) == 2 for s in sites)

    def test_custom_targets_string(self):
        config = {"monitor": {"ping_targets": "8.8.8.8:53,1.1.1.1:443"}}
        core = NetworkMonitorCore(config=config)
        sites = core._build_test_sites()
        assert len(sites) == 2
        assert sites[0] == ("8.8.8.8", 53)
        assert sites[1] == ("1.1.1.1", 443)

    def test_custom_targets_list(self):
        config = {"monitor": {"ping_targets": ["10.0.0.1:80"]}}
        core = NetworkMonitorCore(config=config)
        sites = core._build_test_sites()
        assert sites[0] == ("10.0.0.1", 80)

    def test_empty_targets_uses_default(self):
        config = {"monitor": {"ping_targets": []}}
        core = NetworkMonitorCore(config=config)
        sites = core._build_test_sites()
        assert len(sites) > 0

    def test_port_inference_ipv4(self):
        config = {"monitor": {"ping_targets": ["8.8.8.8"]}}
        core = NetworkMonitorCore(config=config)
        sites = core._build_test_sites()
        assert sites[0][1] == 53

    def test_port_inference_hostname(self):
        config = {"monitor": {"ping_targets": ["www.baidu.com"]}}
        core = NetworkMonitorCore(config=config)
        sites = core._build_test_sites()
        assert sites[0][1] == 443


class TestCache:

    def test_get_test_sites_caches(self):
        core = NetworkMonitorCore()
        sites1 = core._get_test_sites()
        sites2 = core._get_test_sites()
        assert sites1 is sites2

    def test_update_config_clears_cache(self):
        core = NetworkMonitorCore()
        core._get_test_sites()
        assert core._test_sites_cache is not None
        core.update_config({"monitor": {"interval": 60}})
        assert core._test_sites_cache is None


class TestStartStop:

    def test_stop_when_not_monitoring(self):
        core = NetworkMonitorCore()
        core.stop_monitoring()
        assert core.monitoring is False

    def test_start_sets_monitoring(self):
        core = NetworkMonitorCore()
        with patch.object(core, "monitor_network"):
            core.start_monitoring()
            core.stop_monitoring()
            assert core.monitoring is False


class TestEventLoopSetup:

    def test_stop_monitoring_sets_event_loop(self):
        core = NetworkMonitorCore()
        core._login_handler = MagicMock()
        core._login_handler.close_browser = MagicMock(
            return_value=asyncio.coroutine(lambda: None)()
        )
        core.monitoring = True
        core.start_time = time.time()

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            core.stop_monitoring()
            deprecation_warnings = [
                x for x in w if issubclass(x.category, DeprecationWarning)
            ]
            assert len(deprecation_warnings) == 0, (
                f"Unexpected DeprecationWarning: {deprecation_warnings}"
            )

    def test_attempt_login_sets_event_loop(self):
        config = {
            "active_task": "default",
            "auth_url": "http://test",
            "username": "test",
            "isp": "",
        }
        core = NetworkMonitorCore(config=config)

        mock_handler = MagicMock()
        mock_attempt = MagicMock()
        mock_attempt.return_value = asyncio.coroutine(
            lambda: (True, "success")
        )()
        mock_handler.attempt_login = mock_attempt
        core._login_handler = mock_handler

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            core.attempt_login()
            deprecation_warnings = [
                x for x in w if issubclass(x.category, DeprecationWarning)
            ]
            assert len(deprecation_warnings) == 0, (
                f"Unexpected DeprecationWarning: {deprecation_warnings}"
            )


class TestInterruptibleWait:

    def test_stop_event_exists(self):
        core = NetworkMonitorCore()
        assert isinstance(core._stop_event, threading.Event)

    def test_stop_event_set_on_stop_monitoring(self):
        core = NetworkMonitorCore()
        core.monitoring = True
        core.stop_monitoring()
        assert core._stop_event.is_set()

    def test_wait_responds_quickly_to_stop(self):
        core = NetworkMonitorCore()
        core.monitoring = True

        def stop_after_delay():
            time.sleep(0.5)
            core._stop_event.set()
            core.monitoring = False

        stopper = threading.Thread(target=stop_after_delay)
        stopper.start()

        start = time.monotonic()
        result = core._wait_interruptible(300, step=15)
        elapsed = time.monotonic() - start

        stopper.join(timeout=5)
        assert result is False
        assert elapsed < 2.0, (
            f"_wait_interruptible took {elapsed:.2f}s, expected < 2s"
        )

    def test_wait_returns_true_when_not_stopped(self):
        core = NetworkMonitorCore()
        core.monitoring = True
        result = core._wait_interruptible(1, step=1)
        assert result is True
        assert core.monitoring is True


class TestProfileSwitchTrigger:

    def test_profile_switch_not_called_when_network_ok(self):
        config = {"monitor": {"interval": 60}}
        core = NetworkMonitorCore(config=config)
        core.monitoring = True

        with (
            patch("src.monitor_core.is_network_available", return_value=True),
            patch("src.monitor_core.is_local_network_connected", return_value=True),
            patch.object(core, "_wait_interruptible", return_value=False),
            patch.object(core, "_check_profile_switch", wraps=core._check_profile_switch) as mock_check,
        ):
            core.monitor_network()

        mock_check.assert_not_called()

    def test_profile_switch_called_when_network_not_ok(self):
        config = {"monitor": {"interval": 60}}
        core = NetworkMonitorCore(config=config)
        core.monitoring = True

        with (
            patch("src.monitor_core.is_network_available", return_value=False),
            patch("src.monitor_core.is_local_network_connected", return_value=True),
            patch.object(core, "attempt_login", return_value=(True, "success")),
            patch.object(core, "_wait_interruptible", return_value=False),
            patch.object(core, "_check_profile_switch", wraps=core._check_profile_switch) as mock_check,
        ):
            core.monitor_network()

        mock_check.assert_called_once()

    def test_profile_switch_cooldown_on_consecutive_failures(self):
        config = {"monitor": {"interval": 60}}
        core = NetworkMonitorCore(config=config)
        core.monitoring = True
        core._last_gateway_check_time = time.time()

        call_count = 0

        def track_calls():
            nonlocal call_count
            call_count += 1

        with (
            patch("src.monitor_core.is_network_available", return_value=False),
            patch("src.monitor_core.is_local_network_connected", return_value=True),
            patch.object(core, "attempt_login", return_value=(True, "success")),
            patch.object(core, "_wait_interruptible", return_value=False),
            patch.object(core, "_check_profile_switch", side_effect=track_calls),
        ):
            core.monitor_network()

        assert call_count == 1

    def test_profile_switch_called_each_iteration_when_cooldown_expired(self):
        config = {"monitor": {"interval": 60}}
        core = NetworkMonitorCore(config=config)
        core.monitoring = True
        core._last_gateway_check_time = 0

        call_times = []

        def track_call():
            call_times.append(time.time())

        with (
            patch("src.monitor_core.is_network_available", return_value=False),
            patch("src.monitor_core.is_local_network_connected", return_value=True),
            patch.object(core, "attempt_login", return_value=(True, "success")),
            patch.object(core, "_wait_interruptible", return_value=False),
            patch.object(core, "_check_profile_switch", side_effect=lambda: track_call()),
        ):
            core.monitor_network()

        assert len(call_times) == 1


class TestLoginRecoveryLoop:
    """验证 _login_recovery_loop() 的行为。

    测试覆盖：
    - 重试路径中不调用 is_network_available()（关键 Bug fix 验证，Bug:
       原单层循环 via continue 导致重试时重复执行 TCP 探测）
    - 物理网络断开时内层循环正常退出，不执行登录
    - 第 2 次失败和 give_up 时触发桌面通知
    - 重试成功后计数器正确重置（login_attempt_count=0, last_network_ok=True）
    """

    def test_retry_does_not_call_network_check(self):
        """验证登录重试期间 is_network_available() 只被调用 1 次（外层初始检测）。

        mock 设计：attempt_login 连续失败 4 次 → _login_retry_or_bread 返回
        retry×3 → give_up。如果内层循环错误地调用了 is_network_available，
        network_call_count 会 > 1。
        """
        network_call_count = 0

        def mock_network_available(*args, **kwargs):
            nonlocal network_call_count
            network_call_count += 1
            return False

        login_attempts = iter([
            (False, "err"),
            (False, "err"),
            (False, "err"),
            (False, "err"),
        ])

        retry_decisions = iter(["retry", "retry", "retry", "give_up"])

        config = {
            "monitor": {"interval": 60, "ping_targets": ["8.8.8.8:53"]},
            "pause_login": {"enabled": False},
        }
        core = NetworkMonitorCore(config=config, log_callback=lambda *a: None)
        core.monitoring = True

        with (
            patch("src.monitor_core.is_network_available", mock_network_available),
            patch("src.monitor_core.is_local_network_connected", return_value=True),
            patch.object(core, "attempt_login", side_effect=lambda: next(login_attempts)),
            patch.object(core, "_login_retry_or_break", side_effect=lambda: next(retry_decisions)),
            patch.object(core, "_wait_interruptible", return_value=False),
        ):
            core.monitor_network()

        assert network_call_count == 1, (
            f"Expected 1 network check, got {network_call_count}"
        )

    def test_recovery_loop_physical_disconnect(self):
        """验证物理网络断开时登录恢复循环不执行登录重试。

        当 is_local_network_connected() 返回 False 时，_login_recovery_loop()
        应直接返回 "net_disconnect"，不调用 attempt_login()。验证断言：
        login_attempt_count 保持为 0。
        """
        config = {
            "monitor": {"interval": 60, "ping_targets": ["8.8.8.8:53"]},
            "pause_login": {"enabled": False},
        }
        core = NetworkMonitorCore(config=config, log_callback=lambda *a: None)
        core.monitoring = True

        with (
            patch("src.monitor_core.is_network_available", return_value=False),
            patch("src.monitor_core.is_local_network_connected", return_value=False),
            patch.object(core, "_wait_interruptible", return_value=False),
        ):
            core.monitor_network()

        assert core.login_attempt_count == 0
        assert core.last_network_ok is False

    def test_retry_notification_timing(self):
        """验证桌面通知在正确时机触发：第 2 次登录失败 + give_up 时各一次。

        mock 设计：模拟 4 次失败，_login_retry_or_bread 返回 retry×3 → give_up。
        预期触发 2 次通知，且首次通知包含 "2 次"。
        """
        notifications = []

        def mock_notification(title, message):
            notifications.append((title, message))

        login_attempts = iter([
            (False, "err"),
            (False, "err"),
            (False, "err"),
            (False, "err"),
        ])

        retry_decisions = iter(["retry", "retry", "retry", "give_up"])

        config = {
            "monitor": {"interval": 60, "ping_targets": ["8.8.8.8:53"]},
            "pause_login": {"enabled": False},
        }
        core = NetworkMonitorCore(config=config, log_callback=lambda *a: None)
        core.monitoring = True

        with (
            patch("src.monitor_core.is_network_available", return_value=False),
            patch("src.monitor_core.is_local_network_connected", return_value=True),
            patch.object(core, "attempt_login", side_effect=lambda: next(login_attempts)),
            patch.object(core, "_login_retry_or_break", side_effect=lambda: next(retry_decisions)),
            patch.object(core, "_wait_interruptible", return_value=False),
            patch("src.monitor_core.send_notification", mock_notification),
        ):
            core.monitor_network()

        assert len(notifications) == 2
        assert "2 次" in notifications[0][1]

    def test_recovery_success_after_retry(self):
        """验证重试成功后计数器正确重置。

        mock 设计：前 2 次登录失败（retry），第 3 次成功 → _login_recovery_loop
        返回 "login_ok"。外层应设置 login_attempt_count=0, last_network_ok=True。
        """
        login_attempts = iter([
            (False, "err"),
            (False, "err"),
            (True, "ok"),
        ])

        retry_decisions = iter(["retry", "retry"])

        config = {
            "monitor": {"interval": 60, "ping_targets": ["8.8.8.8:53"]},
            "pause_login": {"enabled": False},
        }
        core = NetworkMonitorCore(config=config, log_callback=lambda *a: None)
        core.monitoring = True

        with (
            patch("src.monitor_core.is_network_available", return_value=False),
            patch("src.monitor_core.is_local_network_connected", return_value=True),
            patch.object(core, "attempt_login", side_effect=lambda: next(login_attempts)),
            patch.object(core, "_login_retry_or_break", side_effect=lambda: next(retry_decisions)),
            patch.object(core, "_wait_interruptible", return_value=False),
        ):
            core.monitor_network()

        assert core.login_attempt_count == 0
        assert core.last_network_ok is True
