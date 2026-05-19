from __future__ import annotations

from unittest.mock import patch

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
