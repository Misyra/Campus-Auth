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
