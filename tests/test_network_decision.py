"""src/network_decision.py 测试"""
from __future__ import annotations

from unittest.mock import patch, MagicMock

from src.network_decision import is_auth_url_reachable, should_attempt_login


class TestIsAuthUrlReachable:
    def test_empty_url_returns_true(self):
        """空 URL 应返回 True（兼容模式）"""
        assert is_auth_url_reachable("") is True

    def test_no_hostname_returns_true(self):
        """无主机名的 URL 应返回 True"""
        assert is_auth_url_reachable("http://") is True

    def test_successful_connection(self):
        """连接成功应返回 True"""
        with patch("src.network_decision.socket.create_connection") as mock_conn:
            mock_conn.return_value.__enter__ = lambda s: s
            mock_conn.return_value.__exit__ = lambda s, *a: None
            assert is_auth_url_reachable("http://10.0.0.1:8080/login") is True
            mock_conn.assert_called_once_with(("10.0.0.1", 8080), timeout=3)

    def test_connection_refused(self):
        """连接被拒绝应返回 False"""
        with patch("src.network_decision.socket.create_connection", side_effect=ConnectionRefusedError):
            assert is_auth_url_reachable("http://10.0.0.1/login") is False

    def test_timeout(self):
        """连接超时应返回 False"""
        with patch("src.network_decision.socket.create_connection", side_effect=TimeoutError):
            assert is_auth_url_reachable("http://10.0.0.1/login") is False

    def test_dns_failure(self):
        """DNS 解析失败应返回 False"""
        import socket
        with patch("src.network_decision.socket.create_connection", side_effect=socket.gaierror):
            assert is_auth_url_reachable("http://nonexistent.local/login") is False

    def test_https_default_port(self):
        """HTTPS URL 应默认使用 443 端口"""
        with patch("src.network_decision.socket.create_connection") as mock_conn:
            mock_conn.return_value.__enter__ = lambda s: s
            mock_conn.return_value.__exit__ = lambda s, *a: None
            is_auth_url_reachable("https://example.com/auth")
            mock_conn.assert_called_once_with(("example.com", 443), timeout=3)

    def test_http_default_port(self):
        """HTTP URL 应默认使用 80 端口"""
        with patch("src.network_decision.socket.create_connection") as mock_conn:
            mock_conn.return_value.__enter__ = lambda s: s
            mock_conn.return_value.__exit__ = lambda s, *a: None
            is_auth_url_reachable("http://example.com/auth")
            mock_conn.assert_called_once_with(("example.com", 80), timeout=3)


class TestShouldAttemptLogin:
    def _make_config(self, **overrides):
        """构建测试用配置字典"""
        config = {
            "auth_url": "http://10.0.0.1/login",
            "pause_login": {"enabled": False},
            "monitor": {
                "check_auth_url": True,
                "enable_tcp_check": True,
                "enable_http_check": True,
                "ping_targets": None,
                "test_urls": None,
                "network_check_timeout": 1.5,
            },
        }
        config.update(overrides)
        return config

    @patch("src.network_decision.is_network_available", return_value=False)
    @patch("src.network_decision.is_auth_url_reachable", return_value=True)
    @patch("src.network_decision.is_local_network_connected", return_value=True)
    @patch("src.network_decision.is_in_pause_period", return_value=False)
    def test_network_down_should_login(self, *mocks):
        """网络不可用时应尝试登录"""
        ok, reason = should_attempt_login(self._make_config())
        assert ok is True
        assert reason == ""

    @patch("src.network_decision.is_in_pause_period", return_value=True)
    def test_pause_period(self, *mocks):
        """暂停时段应跳过登录"""
        ok, reason = should_attempt_login(self._make_config())
        assert ok is False
        assert reason == "pause_period"

    @patch("src.network_decision.is_local_network_connected", return_value=False)
    @patch("src.network_decision.is_in_pause_period", return_value=False)
    def test_network_disconnected(self, *mocks):
        """物理网络断开应跳过登录"""
        ok, reason = should_attempt_login(self._make_config())
        assert ok is False
        assert reason == "network_disconnected"

    @patch("src.network_decision.is_auth_url_reachable", return_value=False)
    @patch("src.network_decision.is_local_network_connected", return_value=True)
    @patch("src.network_decision.is_in_pause_period", return_value=False)
    def test_auth_url_unreachable(self, *mocks):
        """认证地址不可达应跳过登录"""
        ok, reason = should_attempt_login(self._make_config())
        assert ok is False
        assert reason == "auth_url_unreachable"

    @patch("src.network_decision.is_network_available", return_value=True)
    @patch("src.network_decision.is_auth_url_reachable", return_value=True)
    @patch("src.network_decision.is_local_network_connected", return_value=True)
    @patch("src.network_decision.is_in_pause_period", return_value=False)
    def test_network_ok_no_login(self, *mocks):
        """网络正常时无需登录"""
        ok, reason = should_attempt_login(self._make_config())
        assert ok is False
        assert reason == "network_ok"

    @patch("src.network_decision.is_network_available", return_value=False)
    @patch("src.network_decision.is_auth_url_reachable", return_value=True)
    @patch("src.network_decision.is_local_network_connected", return_value=True)
    @patch("src.network_decision.is_in_pause_period", return_value=False)
    def test_skip_auth_url_check(self, *mocks):
        """关闭认证地址检查时应跳过可达性检测"""
        config = self._make_config()
        config["monitor"]["check_auth_url"] = False
        ok, reason = should_attempt_login(config)
        assert ok is True
