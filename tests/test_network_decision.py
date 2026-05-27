"""Characterization tests for the network decision layer.

These tests lock down the behavior of network check logic in
`src.network_decision.py`.  They import from the new decision module
and from `src.monitor_core` (for the existing private method tests).

Test layout:
  - TestIsNetworkAvailableOrchestration : is_network_available decision matrix
  - TestIsAuthUrlReachable              : is_auth_url_reachable from network_decision
  - TestShouldAttemptLogin              : should_attempt_login decision tree
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.network_decision import is_auth_url_reachable, is_network_available


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


# ===========================================================================
# 1. is_network_available orchestration
# ===========================================================================


class TestIsNetworkAvailableOrchestration:
    """Characterize the decision tree in is_network_available (lines 293-340).

    Decision matrix:
        physical_down        -> False (always)
        strict + TCP fail    -> False (skip HTTP)
        strict + TCP pass + HTTP pass -> True
        strict + TCP pass + HTTP fail -> False
        normal + TCP pass    -> True  (skip HTTP)
        normal + TCP fail + HTTP pass -> True
        normal + TCP fail + HTTP fail -> False
    """

    # -- physical network down -------------------------------------------------

    def test_physical_down_returns_false_immediately(self):
        """Physical network down -> False, no TCP/HTTP probes attempted."""
        with patch("src.network_decision.is_local_network_connected", return_value=False):
            result = is_network_available()
        assert result is False

    # -- strict mode (require_both=True) ---------------------------------------

    def test_strict_tcp_fail_skips_http_returns_false(self):
        """Strict mode: TCP fail -> skip HTTP -> False."""
        with patch("src.network_decision.is_local_network_connected", return_value=True), \
             patch("src.network_decision.is_network_available_socket", return_value=False), \
             patch("src.network_decision.is_network_available_http") as mock_http:
            result = is_network_available(require_both=True)
        assert result is False
        mock_http.assert_not_called()

    def test_strict_tcp_pass_http_pass_returns_true(self):
        """Strict mode: TCP pass + HTTP pass -> True."""
        with patch("src.network_decision.is_local_network_connected", return_value=True), \
             patch("src.network_decision.is_network_available_socket", return_value=True), \
             patch("src.network_decision.is_network_available_http", return_value=True):
            result = is_network_available(require_both=True)
        assert result is True

    def test_strict_tcp_pass_http_fail_returns_false(self):
        """Strict mode: TCP pass + HTTP fail -> False."""
        with patch("src.network_decision.is_local_network_connected", return_value=True), \
             patch("src.network_decision.is_network_available_socket", return_value=True), \
             patch("src.network_decision.is_network_available_http", return_value=False):
            result = is_network_available(require_both=True)
        assert result is False

    # -- normal mode (require_both=False) --------------------------------------

    def test_normal_tcp_pass_skips_http_returns_true(self):
        """Normal mode: TCP pass -> skip HTTP -> True."""
        with patch("src.network_decision.is_local_network_connected", return_value=True), \
             patch("src.network_decision.is_network_available_socket", return_value=True), \
             patch("src.network_decision.is_network_available_http") as mock_http:
            result = is_network_available(require_both=False)
        assert result is True
        mock_http.assert_not_called()

    def test_normal_tcp_fail_http_pass_returns_true(self):
        """Normal mode: TCP fail + HTTP pass -> True."""
        with patch("src.network_decision.is_local_network_connected", return_value=True), \
             patch("src.network_decision.is_network_available_socket", return_value=False), \
             patch("src.network_decision.is_network_available_http", return_value=True):
            result = is_network_available(require_both=False)
        assert result is True

    def test_normal_tcp_fail_http_fail_returns_false(self):
        """Normal mode: TCP fail + HTTP fail -> False."""
        with patch("src.network_decision.is_local_network_connected", return_value=True), \
             patch("src.network_decision.is_network_available_socket", return_value=False), \
             patch("src.network_decision.is_network_available_http", return_value=False):
            result = is_network_available(require_both=False)
        assert result is False


# ===========================================================================
# 2. is_auth_url_reachable (from network_decision)
# ===========================================================================


class TestIsAuthUrlReachable:
    """Characterize is_auth_url_reachable (src.network_decision).

    Behavior:
        empty auth_url -> True  (safe default, no URL to check)
        no hostname    -> True  (safe default, malformed URL)
        TCP connect OK -> True
        TCP connect fail -> False
    """

    def test_reachable_returns_true(self):
        """TCP connect succeeds -> True."""
        with patch("src.network_decision.socket.create_connection") as mock_conn:
            mock_conn.return_value = MagicMock()
            result = is_auth_url_reachable("http://10.0.0.1:801/eportal")
        assert result is True

    def test_unreachable_returns_false(self):
        """TCP connect raises -> False."""
        with patch("src.network_decision.socket.create_connection", side_effect=OSError):
            result = is_auth_url_reachable("http://10.0.0.1:801/eportal")
        assert result is False

    def test_no_auth_url_returns_true(self):
        """Empty auth_url -> True (safe default, nothing to check)."""
        result = is_auth_url_reachable("")
        assert result is True

    def test_missing_auth_url_config_returns_true(self):
        """None/empty auth_url -> True (safe default)."""
        result = is_auth_url_reachable("")
        assert result is True

    def test_no_hostname_returns_true(self):
        """URL with no parseable hostname -> True (safe default)."""
        result = is_auth_url_reachable("http://")
        assert result is True

    def test_https_default_port_443(self):
        """HTTPS URL without explicit port should use 443."""
        with patch("src.network_decision.socket.create_connection") as mock_conn:
            mock_conn.return_value = MagicMock()
            is_auth_url_reachable("https://auth.example.com/login")
        mock_conn.assert_called_once_with(("auth.example.com", 443), timeout=3)

    def test_http_default_port_80(self):
        """HTTP URL without explicit port should use 80."""
        with patch("src.network_decision.socket.create_connection") as mock_conn:
            mock_conn.return_value = MagicMock()
            is_auth_url_reachable("http://auth.example.com/login")
        mock_conn.assert_called_once_with(("auth.example.com", 80), timeout=3)


# ===========================================================================
# 3. should_attempt_login
# ===========================================================================


class TestShouldAttemptLogin:
    """Characterize should_attempt_login (src.network_decision).

    Decision tree:
        1. In pause period?      -> (False, "pause_period")
        2. Physical net down?    -> (False, "network_disconnected")
        3. Auth URL unreachable? -> (False, "auth_url_unreachable")
        4. Network OK?           -> (False, "network_ok")
        5. Otherwise             -> (True, "")
    """

    def test_pause_period_returns_no_login(self):
        """In pause period -> (False, 'pause_period')."""
        from src.network_decision import should_attempt_login

        config = {"pause_login": {"start_hour": 0, "end_hour": 6}}
        with patch("src.utils.time_utils.TimeUtils.is_in_pause_period", return_value=True):
            should_login, reason = should_attempt_login(config)
        assert should_login is False
        assert reason == "pause_period"

    def test_physical_network_down_returns_disconnected(self):
        """Physical network down -> (False, 'network_disconnected')."""
        from src.network_decision import should_attempt_login

        config = {"auth_url": "http://10.0.0.1:801/eportal"}
        with patch("src.utils.time_utils.TimeUtils.is_in_pause_period", return_value=False), \
             patch("src.network_decision.is_local_network_connected", return_value=False):
            should_login, reason = should_attempt_login(config)
        assert should_login is False
        assert reason == "network_disconnected"

    def test_auth_url_unreachable_returns_auth_url_unreachable(self):
        """Auth URL TCP check fails -> (False, 'auth_url_unreachable')."""
        from src.network_decision import should_attempt_login

        config = {"auth_url": "http://10.0.0.1:801/eportal"}
        with patch("src.utils.time_utils.TimeUtils.is_in_pause_period", return_value=False), \
             patch("src.network_decision.is_local_network_connected", return_value=True), \
             patch("src.network_decision.is_auth_url_reachable", return_value=False):
            should_login, reason = should_attempt_login(config)
        assert should_login is False
        assert reason == "auth_url_unreachable"

    def test_network_ok_returns_no_login(self):
        """Network fully reachable -> (False, 'network_ok')."""
        from src.network_decision import should_attempt_login

        config = {"auth_url": "http://10.0.0.1:801/eportal"}
        with patch("src.utils.time_utils.TimeUtils.is_in_pause_period", return_value=False), \
             patch("src.network_decision.is_local_network_connected", return_value=True), \
             patch("src.network_decision.is_auth_url_reachable", return_value=True), \
             patch("src.network_decision.is_network_available", return_value=True):
            should_login, reason = should_attempt_login(config)
        assert should_login is False
        assert reason == "network_ok"

    def test_network_down_can_login_returns_true(self):
        """Network down but all prereqs pass -> (True, '')."""
        from src.network_decision import should_attempt_login

        config = {"auth_url": "http://10.0.0.1:801/eportal"}
        with patch("src.utils.time_utils.TimeUtils.is_in_pause_period", return_value=False), \
             patch("src.network_decision.is_local_network_connected", return_value=True), \
             patch("src.network_decision.is_auth_url_reachable", return_value=True), \
             patch("src.network_decision.is_network_available", return_value=False):
            should_login, reason = should_attempt_login(config)
        assert should_login is True
        assert reason == ""
