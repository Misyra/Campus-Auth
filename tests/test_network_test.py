from __future__ import annotations

from src.network_test import is_network_available, is_local_network_connected


class TestIsLocalNetworkConnected:

    def test_returns_bool(self):
        result = is_local_network_connected()
        assert isinstance(result, bool)


class TestIsNetworkAvailable:

    def test_returns_bool(self):
        result = is_network_available()
        assert isinstance(result, bool)

    def test_with_empty_sites_uses_defaults(self):
        result = is_network_available(test_sites=[])
        assert isinstance(result, bool)

    def test_with_invalid_site(self):
        result = is_network_available(
            test_sites=[("192.0.2.1", 53)],
            timeout=0.5,
        )
        assert isinstance(result, bool)
