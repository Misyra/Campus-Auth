"""网络模块综合测试

合并原 test_network_decision.py，并新增 network_probes.py 和
network_decision.py 更多函数的测试。
"""
from __future__ import annotations

import socket
from unittest.mock import patch, MagicMock

import pytest

from src.network_decision import (
    is_auth_url_reachable,
    should_attempt_login,
    is_network_available,
    check_campus_network_status,
)
from src.network_probes import (
    set_block_proxy,
    is_local_network_connected,
    is_network_available_socket,
    is_network_available_http,
    is_network_available_portal,
)


# =====================================================================
# network_probes — set_block_proxy
# =====================================================================

class TestSetBlockProxy:
    def test_set_true(self):
        set_block_proxy(True)
        import src.network_probes as np
        assert np._block_proxy is True

    def test_set_false(self):
        set_block_proxy(False)
        import src.network_probes as np
        assert np._block_proxy is False

    def teardown_method(self):
        set_block_proxy(True)  # 恢复默认


# =====================================================================
# network_probes — is_local_network_connected
# =====================================================================

class TestIsLocalNetworkConnected:
    def test_connected_with_non_loopback_ip(self):
        """有非回环 IP 时应返回 True"""
        with patch("src.network_probes.socket") as mock_socket:
            mock_socket.gethostname.return_value = "myhost"
            mock_socket.gethostbyname_ex.return_value = ("myhost", [], ["192.168.1.100"])
            assert is_local_network_connected() is True

    def test_only_loopback_ip(self):
        """仅有回环 IP 时应尝试平台回退"""
        with patch("src.network_probes.socket") as mock_socket:
            mock_socket.gethostname.return_value = "localhost"
            mock_socket.gethostbyname_ex.return_value = ("localhost", [], ["127.0.0.1"])
            with patch("src.network_probes.is_windows", return_value=False), \
                 patch("src.network_probes.is_linux", return_value=False), \
                 patch("src.network_probes.is_macos", return_value=False):
                assert is_local_network_connected() is False

    def test_apipa_ip_only(self):
        """仅有 APIPA IP (169.254.x.x) 时应尝试平台回退"""
        with patch("src.network_probes.socket") as mock_socket:
            mock_socket.gethostname.return_value = "host"
            mock_socket.gethostbyname_ex.return_value = ("host", [], ["169.254.1.1"])
            with patch("src.network_probes.is_windows", return_value=False), \
                 patch("src.network_probes.is_linux", return_value=False), \
                 patch("src.network_probes.is_macos", return_value=False):
                assert is_local_network_connected() is False

    def test_exception_in_gethostbyname(self):
        """gethostbyname_ex 异常时应尝试平台回退"""
        with patch("src.network_probes.socket") as mock_socket:
            mock_socket.gethostname.return_value = "host"
            mock_socket.gethostbyname_ex.side_effect = OSError("fail")
            with patch("src.network_probes.is_windows", return_value=False), \
                 patch("src.network_probes.is_linux", return_value=False), \
                 patch("src.network_probes.is_macos", return_value=False):
                assert is_local_network_connected() is False


# =====================================================================
# network_probes — is_network_available_socket
# =====================================================================

class TestIsNetworkAvailableSocket:
    def test_success(self):
        """至少一个目标连接成功应返回 True"""
        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        with patch("src.network_probes.socket.create_connection", return_value=mock_conn):
            result = is_network_available_socket(
                test_sites=[("8.8.8.8", 53)], timeout=1.0
            )
            assert result is True

    def test_all_fail(self):
        """所有目标连接失败应返回 False"""
        with patch("src.network_probes.socket.create_connection", side_effect=TimeoutError):
            result = is_network_available_socket(
                test_sites=[("8.8.8.8", 53), ("1.1.1.1", 53)], timeout=0.1
            )
            assert result is False

    def test_one_success_one_fail(self):
        """一个成功一个失败应返回 True"""
        call_count = [0]
        def side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                mock = MagicMock()
                mock.__enter__ = MagicMock(return_value=mock)
                mock.__exit__ = MagicMock(return_value=False)
                return mock
            raise TimeoutError()

        with patch("src.network_probes.socket.create_connection", side_effect=side_effect):
            result = is_network_available_socket(
                test_sites=[("8.8.8.8", 53), ("1.1.1.1", 53)], timeout=0.1
            )
            assert result is True


# =====================================================================
# network_probes — is_network_available_http
# =====================================================================

class TestIsNetworkAvailableHttp:
    def test_success_200(self):
        """HTTP 200 应返回 True"""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_client = MagicMock()
        mock_client.get.return_value = mock_resp
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        with patch("src.network_probes.httpx.Client", return_value=mock_client):
            result = is_network_available_http(
                test_urls=["https://www.baidu.com"], timeout=2.0
            )
            assert result is True

    def test_redirect_302(self):
        """HTTP 302 应返回 False（门户重定向）"""
        mock_resp = MagicMock()
        mock_resp.status_code = 302
        mock_client = MagicMock()
        mock_client.get.return_value = mock_resp
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        with patch("src.network_probes.httpx.Client", return_value=mock_client):
            result = is_network_available_http(
                test_urls=["https://www.baidu.com"], timeout=2.0
            )
            assert result is False

    def test_connection_error(self):
        """连接异常应返回 False"""
        mock_client = MagicMock()
        mock_client.get.side_effect = ConnectionError("fail")
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        with patch("src.network_probes.httpx.Client", return_value=mock_client):
            result = is_network_available_http(
                test_urls=["https://www.baidu.com"], timeout=2.0
            )
            assert result is False

    def test_empty_urls_uses_defaults(self):
        """空 URL 列表会回退到默认 URL（baidu/qq）"""
        # [] 是 falsy，会回退到默认 URL 列表
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_client.get.return_value = mock_resp
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        with patch("src.network_probes.httpx.Client", return_value=mock_client):
            result = is_network_available_http(test_urls=[], timeout=2.0)
            assert result is True


# =====================================================================
# network_probes — is_network_available_portal
# =====================================================================

class TestIsNetworkAvailablePortal:
    def test_success(self):
        """portal 探测成功应返回 True"""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "Success"
        mock_client = MagicMock()
        mock_client.get.return_value = mock_resp
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        with patch("src.network_probes.httpx.Client", return_value=mock_client):
            result = is_network_available_portal(
                portal_checks=[("http://test.com", "Success")], timeout=3.0
            )
            assert result is True

    def test_content_mismatch(self):
        """内容不匹配应返回 False"""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "Login page"
        mock_client = MagicMock()
        mock_client.get.return_value = mock_resp
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        with patch("src.network_probes.httpx.Client", return_value=mock_client):
            result = is_network_available_portal(
                portal_checks=[("http://test.com", "Success")], timeout=3.0
            )
            assert result is False

    def test_empty_checks_returns_true(self):
        """空检查列表应返回 True（不启用探测）"""
        result = is_network_available_portal(portal_checks=[], timeout=3.0)
        assert result is True

    def test_connection_error(self):
        """连接异常应返回 False"""
        mock_client = MagicMock()
        mock_client.get.side_effect = ConnectionError("fail")
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        with patch("src.network_probes.httpx.Client", return_value=mock_client):
            result = is_network_available_portal(
                portal_checks=[("http://test.com", "Success")], timeout=3.0
            )
            assert result is False


# =====================================================================
# network_decision — is_auth_url_reachable
# =====================================================================

class TestIsAuthUrlReachable:
    def test_empty_url_returns_true(self):
        assert is_auth_url_reachable("") is True

    def test_no_hostname_returns_true(self):
        assert is_auth_url_reachable("http://") is True

    def test_successful_connection(self):
        with patch("src.network_decision.socket.create_connection") as mock_conn:
            mock_conn.return_value.__enter__ = lambda s: s
            mock_conn.return_value.__exit__ = lambda s, *a: None
            assert is_auth_url_reachable("http://10.0.0.1:8080/login") is True
            mock_conn.assert_called_once_with(("10.0.0.1", 8080), timeout=3)

    def test_connection_refused(self):
        with patch("src.network_decision.socket.create_connection", side_effect=ConnectionRefusedError):
            assert is_auth_url_reachable("http://10.0.0.1/login") is False

    def test_timeout(self):
        with patch("src.network_decision.socket.create_connection", side_effect=TimeoutError):
            assert is_auth_url_reachable("http://10.0.0.1/login") is False

    def test_dns_failure(self):
        with patch("src.network_decision.socket.create_connection", side_effect=socket.gaierror):
            assert is_auth_url_reachable("http://nonexistent.local/login") is False

    def test_https_default_port(self):
        with patch("src.network_decision.socket.create_connection") as mock_conn:
            mock_conn.return_value.__enter__ = lambda s: s
            mock_conn.return_value.__exit__ = lambda s, *a: None
            is_auth_url_reachable("https://example.com/auth")
            mock_conn.assert_called_once_with(("example.com", 443), timeout=3)

    def test_http_default_port(self):
        with patch("src.network_decision.socket.create_connection") as mock_conn:
            mock_conn.return_value.__enter__ = lambda s: s
            mock_conn.return_value.__exit__ = lambda s, *a: None
            is_auth_url_reachable("http://example.com/auth")
            mock_conn.assert_called_once_with(("example.com", 80), timeout=3)


# =====================================================================
# network_decision — should_attempt_login
# =====================================================================

class TestShouldAttemptLogin:
    def _make_config(self, **overrides):
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
        ok, reason = should_attempt_login(self._make_config())
        assert ok is True
        assert reason == ""

    @patch("src.network_decision.is_in_pause_period", return_value=True)
    def test_pause_period(self, *mocks):
        ok, reason = should_attempt_login(self._make_config())
        assert ok is False
        assert reason == "pause_period"

    @patch("src.network_decision.is_local_network_connected", return_value=False)
    @patch("src.network_decision.is_in_pause_period", return_value=False)
    def test_network_disconnected(self, *mocks):
        ok, reason = should_attempt_login(self._make_config())
        assert ok is False
        assert reason == "network_disconnected"

    @patch("src.network_decision.is_network_available", return_value=False)
    @patch("src.network_decision.is_auth_url_reachable", return_value=False)
    @patch("src.network_decision.is_local_network_connected", return_value=True)
    @patch("src.network_decision.is_in_pause_period", return_value=False)
    def test_auth_url_unreachable_still_checks_network(self, *mocks):
        ok, reason = should_attempt_login(self._make_config())
        assert ok is True

    @patch("src.network_decision.is_network_available", return_value=True)
    @patch("src.network_decision.is_auth_url_reachable", return_value=True)
    @patch("src.network_decision.is_local_network_connected", return_value=True)
    @patch("src.network_decision.is_in_pause_period", return_value=False)
    def test_network_ok_no_login(self, *mocks):
        ok, reason = should_attempt_login(self._make_config())
        assert ok is False
        assert reason == "network_ok"


# =====================================================================
# network_decision — is_network_available
# =====================================================================

class TestIsNetworkAvailable:
    def test_all_disabled_returns_true(self):
        """所有探测都未启用时应返回 True"""
        result = is_network_available(
            enable_tcp=False, enable_http=False, portal_checks=None,
            skip_local_check=True,
        )
        assert result is True

    @patch("src.network_decision.is_local_network_connected", return_value=False)
    def test_local_disconnected_returns_false(self, mock_local):
        """物理网络断开时应返回 False"""
        result = is_network_available(skip_local_check=False)
        assert result is False

    @patch("src.network_decision.is_network_available_socket", return_value=True)
    @patch("src.network_decision.is_network_available_http", return_value=True)
    @patch("src.network_decision.is_local_network_connected", return_value=True)
    def test_all_pass(self, *mocks):
        """所有探测通过应返回 True"""
        result = is_network_available(
            test_sites=[("8.8.8.8", 53)],
            test_urls=["https://www.baidu.com"],
            enable_tcp=True, enable_http=True,
            skip_local_check=False,
        )
        assert result is True

    @patch("src.network_decision.is_network_available_socket", return_value=False)
    @patch("src.network_decision.is_network_available_http", return_value=True)
    @patch("src.network_decision.is_local_network_connected", return_value=True)
    def test_tcp_fail_http_pass(self, *mocks):
        """TCP 失败但 HTTP 通过时应返回 False（所有启用的探测必须都通过）"""
        result = is_network_available(
            test_sites=[("8.8.8.8", 53)],
            test_urls=["https://www.baidu.com"],
            enable_tcp=True, enable_http=True,
            skip_local_check=False,
        )
        assert result is False

    @patch("src.network_decision.is_network_available_socket", return_value=True)
    @patch("src.network_decision.is_local_network_connected", return_value=True)
    def test_tcp_only(self, *mocks):
        """仅启用 TCP 时，TCP 通过应返回 True"""
        result = is_network_available(
            test_sites=[("8.8.8.8", 53)],
            enable_tcp=True, enable_http=False,
            skip_local_check=False,
        )
        assert result is True

    def test_skip_local_check(self):
        """skip_local_check=True 时应跳过物理网络检查"""
        with patch("src.network_decision.is_network_available_socket", return_value=True):
            result = is_network_available(
                test_sites=[("8.8.8.8", 53)],
                enable_tcp=True, enable_http=False,
                skip_local_check=True,
            )
            assert result is True


# =====================================================================
# network_decision — check_campus_network_status
# =====================================================================

class TestCheckCampusNetworkStatus:
    @patch("src.network_decision.is_local_network_connected", return_value=False)
    def test_no_local_network(self, mock_local):
        result = check_campus_network_status()
        assert "未检测到" in result

    @patch("src.network_decision.is_network_available", return_value=True)
    @patch("src.network_decision.is_local_network_connected", return_value=True)
    def test_fully_connected(self, *mocks):
        result = check_campus_network_status()
        assert "可访问互联网" in result

    @patch("src.network_decision.is_network_available", return_value=False)
    @patch("src.network_decision.is_local_network_connected", return_value=True)
    def test_connected_but_no_internet(self, *mocks):
        result = check_campus_network_status()
        assert "无法访问互联网" in result
