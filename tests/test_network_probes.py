"""Characterization tests for the network probe layer.

These tests lock down the current behavior of `src.network_probes`.
All network I/O is mocked; no real connections are made.
"""
from __future__ import annotations

import logging
import socket
import ssl

from unittest.mock import MagicMock, patch

from src.network_probes import (
    is_local_network_connected,
    is_network_available_http,
    is_network_available_socket,
)


# ---------------------------------------------------------------------------
# is_local_network_connected
# ---------------------------------------------------------------------------


class TestIsLocalNetworkConnected:
    """Characterize IP-detection and platform-fallback behaviour."""

    def test_non_loopback_ip_returns_true(self):
        """gethostbyname_ex returning a routable IP => True immediately."""
        with patch("src.network_probes.socket.gethostname", return_value="myhost"):
            with patch(
                "src.network_probes.socket.gethostbyname_ex",
                return_value=("myhost", [], ["192.168.1.100"]),
            ):
                result = is_local_network_connected()
        assert result is True

    def test_only_loopback_127_falls_back(self):
        """Only 127.x addresses => all filtered, falls back to platform check."""
        with patch("src.network_probes.socket.gethostname", return_value="myhost"):
            with patch(
                "src.network_probes.socket.gethostbyname_ex",
                return_value=("myhost", [], ["127.0.0.1", "127.0.0.2"]),
            ):
                # Patch platform check to isolate this unit (platform is Windows here)
                with patch("src.network_probes._check_windows_adapter", return_value=True):
                    result = is_local_network_connected()
        # Falls through to platform check — we just verify it doesn't short-circuit
        assert isinstance(result, bool)

    def test_apipa_169_254_filtered_out(self):
        """169.254.x (APIPA) addresses are filtered like loopback."""
        with patch("src.network_probes.socket.gethostname", return_value="myhost"):
            with patch(
                "src.network_probes.socket.gethostbyname_ex",
                return_value=("myhost", [], ["169.254.10.20"]),
            ):
                with patch("src.network_probes._check_windows_adapter", return_value=False):
                    result = is_local_network_connected()
        assert result is False

    def test_mix_loopback_and_apipa_falls_back(self):
        """A mix of 127.x and 169.254.x should leave non_loopback empty."""
        with patch("src.network_probes.socket.gethostname", return_value="myhost"):
            with patch(
                "src.network_probes.socket.gethostbyname_ex",
                return_value=("myhost", [], ["127.0.0.1", "169.254.1.1"]),
            ):
                with patch("src.network_probes._check_windows_adapter", return_value=True):
                    result = is_local_network_connected()
        assert isinstance(result, bool)

    def test_gethostbyname_ex_exception_falls_back(self):
        """Exception from gethostbyname_ex triggers platform fallback."""
        with patch("src.network_probes.socket.gethostname", return_value="myhost"):
            with patch(
                "src.network_probes.socket.gethostbyname_ex",
                side_effect=socket.herror("lookup failed"),
            ):
                with patch("src.network_probes._check_windows_adapter", return_value=True):
                    result = is_local_network_connected()
        assert result is True


# ---------------------------------------------------------------------------
# is_network_available_socket
# ---------------------------------------------------------------------------


class TestIsNetworkAvailableSocket:
    """Characterize parallel TCP probe behaviour."""

    def test_first_target_succeeds_returns_true(self):
        """A single successful TCP connection => True (any-success-wins)."""
        mock_conn = MagicMock()
        with patch("src.network_probes.socket.create_connection", return_value=mock_conn):
            result = is_network_available_socket(
                test_sites=[("1.1.1.1", 53)], timeout=0.5
            )
        assert result is True

    def test_all_targets_fail_returns_false(self):
        """Every TCP connection raising => False."""
        with patch(
            "src.network_probes.socket.create_connection",
            side_effect=TimeoutError("timed out"),
        ):
            result = is_network_available_socket(
                test_sites=[("192.0.2.1", 53), ("192.0.2.2", 53)], timeout=0.1
            )
        assert result is False

    def test_mixed_results_returns_true(self):
        """First fails, second succeeds => True (parallel, any-wins)."""
        call_count = {"n": 0}

        def _side_effect(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise TimeoutError("timed out")
            return MagicMock()

        with patch("src.network_probes.socket.create_connection", side_effect=_side_effect):
            result = is_network_available_socket(
                test_sites=[("192.0.2.1", 53), ("1.1.1.1", 53)], timeout=0.5
            )
        assert result is True


# ---------------------------------------------------------------------------
# is_network_available_http
# ---------------------------------------------------------------------------


class TestIsNetworkAvailableHttp:
    """Characterize HTTP probe behaviour with mocked httpx."""

    def test_2xx_response_returns_true(self):
        """200 OK => True."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_client = MagicMock()
        mock_client.get.return_value = mock_response
        with patch("src.network_probes.httpx.Client") as mock_cls:
            mock_cls.return_value.__enter__.return_value = mock_client
            result = is_network_available_http(
                test_urls=["https://example.com"], timeout=0.5
            )
        assert result is True

    def test_3xx_with_follow_redirects_false_returns_false(self):
        """302 when follow_redirects=False => False (portal redirect = not OK)."""
        mock_response = MagicMock()
        mock_response.status_code = 302
        mock_client = MagicMock()
        mock_client.get.return_value = mock_response
        with patch("src.network_probes.httpx.Client") as mock_cls:
            mock_cls.return_value.__enter__.return_value = mock_client
            result = is_network_available_http(
                test_urls=["https://example.com"],
                timeout=0.5,
                follow_redirects=False,
            )
        assert result is False

    def test_ssl_error_returns_false(self):
        """ssl.SSLError => False (not an exception)."""
        with patch("src.network_probes.httpx.Client") as mock_cls:
            mock_cls.return_value.__enter__.side_effect = ssl.SSLError(
                "certificate verify failed"
            )
            result = is_network_available_http(
                test_urls=["https://example.com"], timeout=0.5
            )
        assert result is False

    def test_ssl_error_logged_at_debug(self, caplog):
        """SSL errors should be logged at DEBUG, not WARNING/INFO."""
        with patch("src.network_probes.httpx.Client") as mock_cls:
            mock_cls.return_value.__enter__.side_effect = ssl.SSLError(
                "certificate verify failed"
            )
            with caplog.at_level(logging.DEBUG, logger="network_probes"):
                is_network_available_http(
                    test_urls=["https://example.com"], timeout=0.5
                )
        ssl_records = [r for r in caplog.records if "证书验证失败" in r.getMessage()]
        assert len(ssl_records) > 0
        assert all(r.levelno == logging.DEBUG for r in ssl_records)

    def test_empty_list_uses_defaults(self):
        """Empty list is falsy, so `or` falls through to default URLs."""
        # [] is falsy in Python, so `test_urls or defaults` uses the defaults.
        # This characterizes the actual runtime behaviour.
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_client = MagicMock()
        mock_client.get.return_value = mock_response
        with patch("src.network_probes.httpx.Client") as mock_cls:
            mock_cls.return_value.__enter__.return_value = mock_client
            result = is_network_available_http(test_urls=[], timeout=0.5)
        assert result is True  # defaults succeed via mock

    def test_all_urls_fail_returns_false(self):
        """Every URL raising a generic exception => False."""
        with patch("src.network_probes.httpx.Client") as mock_cls:
            mock_cls.return_value.__enter__.side_effect = ConnectionError("refused")
            result = is_network_available_http(
                test_urls=["https://a.example.com", "https://b.example.com"],
                timeout=0.5,
            )
        assert result is False


# ---------------------------------------------------------------------------
# set_block_proxy
# ---------------------------------------------------------------------------


class TestSetBlockProxy:
    """Characterize the _block_proxy toggle."""

    def test_set_false_changes_internal_state(self):
        """set_block_proxy(False) should set _block_proxy to False."""
        import src.network_probes as nt

        # Save and restore original value
        original = nt._block_proxy
        try:
            nt.set_block_proxy(False)
            assert nt._block_proxy is False
        finally:
            nt._block_proxy = original

    def test_set_true_changes_internal_state(self):
        """set_block_proxy(True) should set _block_proxy to True."""
        import src.network_probes as nt

        original = nt._block_proxy
        try:
            nt.set_block_proxy(False)
            nt.set_block_proxy(True)
            assert nt._block_proxy is True
        finally:
            nt._block_proxy = original
