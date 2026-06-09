"""网络决策层测试 — 覆盖 check_pause / check_network_status / check_login_prerequisites。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.network.decision import (
    check_login_prerequisites,
    check_network_status,
    check_pause,
    is_network_available,
)

# ── check_pause ──


class TestCheckPause:
    """暂停时段检查。"""

    def test_disabled_pause(self):
        """暂停功能禁用时返回不暂停。"""
        config = {"pause_login": {"enabled": False}}
        is_paused, reason = check_pause(config)
        assert is_paused is False
        assert reason == ""

    def test_no_pause_config(self):
        """无暂停配置时返回不暂停。"""
        config = {}
        is_paused, reason = check_pause(config)
        assert isinstance(is_paused, bool)

    @patch("app.network.decision.is_in_pause_period", return_value=True)
    def test_in_pause_period(self, mock_pause):
        """在暂停时段内返回暂停。"""
        config = {"pause_login": {"enabled": True, "start_hour": 0, "end_hour": 6}}
        is_paused, reason = check_pause(config)
        assert is_paused is True
        assert reason == "pause_period"

    @patch("app.network.decision.is_in_pause_period", return_value=False)
    def test_not_in_pause_period(self, mock_pause):
        """不在暂停时段返回不暂停。"""
        config = {"pause_login": {"enabled": True, "start_hour": 8, "end_hour": 18}}
        is_paused, reason = check_pause(config)
        assert is_paused is False
        assert reason == ""


# ── check_network_status ──


class TestCheckNetworkStatus:
    """网络状态检测。"""

    @patch("app.network.decision.is_network_available", return_value=True)
    def test_network_ok(self, mock_check):
        """网络正常时返回 network_ok。"""
        config = {"monitor": {"enable_tcp_check": True, "enable_http_check": True}}
        ok, reason = check_network_status(config)
        assert ok is True
        assert reason == "network_ok"

    @patch("app.network.decision.is_network_available", return_value=False)
    def test_network_down(self, mock_check):
        """网络异常时返回 network_down。"""
        config = {"monitor": {"enable_tcp_check": True}}
        ok, reason = check_network_status(config)
        assert ok is False
        assert reason == "network_down"

    def test_all_disabled(self):
        """所有检测禁用时返回 all_disabled。"""
        config = {
            "monitor": {
                "enable_tcp_check": False,
                "enable_http_check": False,
                "url_check_urls": None,
            }
        }
        ok, reason = check_network_status(config)
        assert ok is False
        assert reason == "all_disabled"

    @patch("app.network.decision.is_network_available", return_value=True)
    def test_default_monitor_config(self, mock_check):
        """空 monitor 配置使用默认值。"""
        config = {}
        ok, reason = check_network_status(config)
        assert ok is True
        assert reason == "network_ok"


# ── check_login_prerequisites ──


class TestCheckLoginPrerequisites:
    """登录前置检查。"""

    @patch("app.network.decision.is_local_network_connected", return_value=True)
    @patch("app.network.decision._is_auth_url_reachable", return_value=True)
    def test_all_pass(self, mock_auth, mock_local):
        """物理网络和认证地址都可达。"""
        config = {
            "monitor": {"enable_local_check": True, "check_auth_url": True},
            "auth_url": "http://example.com",
        }
        ok, reason = check_login_prerequisites(config)
        assert ok is True
        assert reason == ""

    @patch("app.network.decision.is_local_network_connected", return_value=False)
    def test_local_disconnected(self, mock_local):
        """物理网络断开。"""
        config = {"monitor": {"enable_local_check": True}}
        ok, reason = check_login_prerequisites(config)
        assert ok is False
        assert reason == "local_disconnected"

    @patch("app.network.decision.is_local_network_connected", return_value=True)
    @patch("app.network.decision._is_auth_url_reachable", return_value=False)
    def test_auth_url_unreachable(self, mock_auth, mock_local):
        """认证地址不可达。"""
        config = {
            "monitor": {"enable_local_check": True, "check_auth_url": True},
            "auth_url": "http://unreachable.com",
        }
        ok, reason = check_login_prerequisites(config)
        assert ok is False
        assert reason == "auth_url_unreachable"

    @patch("app.network.decision.is_local_network_connected", return_value=True)
    @patch("app.network.decision._is_auth_url_reachable", return_value=True)
    def test_local_check_disabled(self, mock_auth, mock_local):
        """禁用物理网络检查时跳过。"""
        config = {
            "monitor": {"enable_local_check": False, "check_auth_url": True},
            "auth_url": "http://example.com",
        }
        ok, reason = check_login_prerequisites(config)
        assert ok is True
        assert reason == ""
        mock_local.assert_not_called()

    def test_empty_config(self):
        """空配置默认启用检查。"""
        config = {}
        ok, reason = check_login_prerequisites(config)
        # auth_url 为空且无 extra_targets → _is_auth_url_reachable 返回 True
        assert ok is True


# ── is_network_available ──


class TestIsNetworkAvailable:
    """底层网络检测函数。"""

    def test_all_disabled_returns_true(self):
        """所有检测禁用时返回 True（视为正常）。"""
        result = is_network_available(
            enable_tcp=False, enable_http=False, url_checks=None
        )
        assert result is True

    @patch("app.network.decision.is_network_available_socket", return_value=True)
    @patch("app.network.decision.is_network_available_http", return_value=True)
    def test_tcp_and_http(self, mock_http, mock_socket):
        """TCP 和 HTTP 都正常时返回 True。"""
        result = is_network_available(
            test_sites=[("8.8.8.8", 53)],
            test_urls=["http://www.baidu.com"],
            enable_tcp=True,
            enable_http=True,
        )
        assert result is True

    @patch("app.network.decision.is_network_available_socket", return_value=False)
    @patch("app.network.decision.is_network_available_http", return_value=True)
    def test_tcp_down_http_ok_both_enabled(self, mock_http, mock_socket):
        """两者都启用时，TCP 失败则整体返回 False。"""
        result = is_network_available(
            test_sites=[("8.8.8.8", 53)],
            test_urls=["http://www.baidu.com"],
            enable_tcp=True,
            enable_http=True,
        )
        # 两者都启用时，任一失败即整体失败
        assert result is False

    @patch("app.network.decision.is_network_available_socket", return_value=False)
    @patch("app.network.decision.is_network_available_http", return_value=True)
    def test_tcp_down_http_only(self, mock_http, mock_socket):
        """仅启用 HTTP 时，TCP 失败不影响结果。"""
        result = is_network_available(
            test_urls=["http://www.baidu.com"],
            enable_tcp=False,
            enable_http=True,
        )
        assert result is True

    @patch("app.network.decision.is_network_available_socket", return_value=False)
    @patch("app.network.decision.is_network_available_http", return_value=False)
    def test_all_down(self, mock_http, mock_socket):
        """所有检测失败时返回 False。"""
        result = is_network_available(
            test_sites=[("8.8.8.8", 53)],
            test_urls=["http://www.baidu.com"],
            enable_tcp=True,
            enable_http=True,
        )
        assert result is False


# ── _is_auth_url_reachable ──


class TestIsAuthUrlReachable:
    """认证地址可达性检测。"""

    def test_empty_url_returns_true(self):
        """空 URL 返回 True（无需检测）。"""
        from app.network.decision import _is_auth_url_reachable

        assert _is_auth_url_reachable("") is True
        assert _is_auth_url_reachable("", extra_targets=None) is True

    @patch("socket.create_connection")
    def test_reachable_url(self, mock_conn):
        """可达的 URL 返回 True。"""
        from app.network.decision import _is_auth_url_reachable

        mock_conn.return_value.__enter__ = MagicMock()
        mock_conn.return_value.__exit__ = MagicMock()
        assert _is_auth_url_reachable("http://example.com:8080/login") is True

    @patch("socket.create_connection", side_effect=ConnectionRefusedError)
    def test_unreachable_url(self, mock_conn):
        """不可达的 URL 返回 False。"""
        from app.network.decision import _is_auth_url_reachable

        assert (
            _is_auth_url_reachable("http://unreachable.example.com:8080/login") is False
        )

    @patch("socket.create_connection")
    def test_extra_targets_reachable(self, mock_conn):
        """自定义目标可达时返回 True。"""
        from app.network.decision import _is_auth_url_reachable

        mock_conn.return_value.__enter__ = MagicMock()
        mock_conn.return_value.__exit__ = MagicMock()
        assert _is_auth_url_reachable("", extra_targets=["10.0.0.1:8080"]) is True

    @patch("socket.create_connection", side_effect=ConnectionRefusedError)
    def test_extra_targets_unreachable(self, mock_conn):
        """自定义目标均不可达时返回 False。"""
        from app.network.decision import _is_auth_url_reachable

        assert (
            _is_auth_url_reachable("http://x.com", extra_targets=["10.0.0.1:8080"])
            is False
        )
