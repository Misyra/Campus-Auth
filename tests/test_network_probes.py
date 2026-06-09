"""网络检测模块综合测试

覆盖 network_probes、network_decision 的全部函数，以及 network_test 向后兼容模块。
"""

from __future__ import annotations

import socket
from unittest.mock import MagicMock, patch

from app.network.decision import (
    check_campus_network_status,
    check_login_prerequisites,
    check_network_status,
    check_pause,
    is_network_available,
)
from app.network.probes import (
    is_local_network_connected,
    is_network_available_http,
    is_network_available_socket,
    is_network_available_url,
    set_block_proxy,
)

# =====================================================================
# network_probes — set_block_proxy
# =====================================================================


class TestSetBlockProxy:
    def test_sets_flag(self):
        set_block_proxy(True)
        from app.network.probes import _block_proxy

        assert _block_proxy is True

    def test_default_is_true(self):
        from app.network.probes import _block_proxy

        assert _block_proxy is True


# =====================================================================
# network_probes — is_local_network_connected
# =====================================================================


class TestIsLocalNetworkConnected:
    def test_returns_true_when_ip_found(self):
        with (
            patch("app.network.probes.socket.gethostname", return_value="test"),
            patch(
                "app.network.probes.socket.gethostbyname_ex",
                return_value=("test", [], ["192.168.1.100"]),
            ),
        ):
            assert is_local_network_connected() is True

    def test_returns_false_on_loopback_only(self):
        with (
            patch("app.network.probes.socket.gethostname", return_value="test"),
            patch(
                "app.network.probes.socket.gethostbyname_ex",
                return_value=("test", [], ["127.0.0.1"]),
            ),
            patch("app.network.probes.is_windows", return_value=False),
            patch("app.network.probes.is_linux", return_value=False),
            patch("app.network.probes.is_macos", return_value=False),
        ):
            assert is_local_network_connected() is False

    def test_returns_false_on_exception(self):
        with (
            patch(
                "app.network.probes.socket.gethostbyname_ex",
                side_effect=Exception("fail"),
            ),
            patch("app.network.probes.is_windows", return_value=False),
            patch("app.network.probes.is_linux", return_value=False),
            patch("app.network.probes.is_macos", return_value=False),
        ):
            assert is_local_network_connected() is False

    def test_returns_false_for_169_254(self):
        with (
            patch("app.network.probes.socket.gethostname", return_value="test"),
            patch(
                "app.network.probes.socket.gethostbyname_ex",
                return_value=("test", [], ["169.254.1.1"]),
            ),
            patch("app.network.probes.is_windows", return_value=False),
            patch("app.network.probes.is_linux", return_value=False),
            patch("app.network.probes.is_macos", return_value=False),
        ):
            assert is_local_network_connected() is False


# =====================================================================
# network_probes — is_network_available_socket
# =====================================================================


class TestIsNetworkAvailableSocket:
    def test_success_on_first_target(self):
        with patch("app.network.probes.socket.create_connection") as mock_conn:
            mock_conn.return_value.__enter__ = lambda s: s
            mock_conn.return_value.__exit__ = lambda s, *a: None
            result = is_network_available_socket(
                test_sites=[("8.8.8.8", 53)], timeout=1.0
            )
            assert result is True

    def test_failure_all_targets(self):
        with patch(
            "app.network.probes.socket.create_connection",
            side_effect=TimeoutError,
        ):
            result = is_network_available_socket(
                test_sites=[("8.8.8.8", 53), ("1.1.1.1", 53)], timeout=0.1
            )
            assert result is False

    def test_success_on_second_target(self):
        call_count = 0

        def side_effect(addr, timeout=None):
            nonlocal call_count
            call_count += 1
            if addr == ("8.8.8.8", 53):
                raise TimeoutError
            m = MagicMock()
            m.__enter__ = lambda s: s
            m.__exit__ = lambda s, *a: None
            return m

        with patch(
            "app.network.probes.socket.create_connection",
            side_effect=side_effect,
        ):
            result = is_network_available_socket(
                test_sites=[("8.8.8.8", 53), ("1.1.1.1", 53)], timeout=0.1
            )
            assert result is True


# =====================================================================
# network_probes — is_network_available_http
# =====================================================================


class TestIsNetworkAvailableHttp:
    def test_success_200(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        with patch("app.network.probes.httpx.Client") as MockClient:
            instance = MockClient.return_value.__enter__.return_value
            instance.get.return_value = mock_resp
            result = is_network_available_http(
                test_urls=["https://www.baidu.com"], timeout=2.0
            )
            assert result is True

    def test_failure_500(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        with patch("app.network.probes.httpx.Client") as MockClient:
            instance = MockClient.return_value.__enter__.return_value
            instance.get.return_value = mock_resp
            result = is_network_available_http(
                test_urls=["https://www.baidu.com"], timeout=2.0
            )
            assert result is False

    def test_connection_error(self):
        with patch("app.network.probes.httpx.Client") as MockClient:
            instance = MockClient.return_value.__enter__.return_value
            instance.get.side_effect = Exception("connection error")
            result = is_network_available_http(
                test_urls=["https://www.baidu.com"], timeout=2.0
            )
            assert result is False

    def test_empty_urls_uses_defaults(self):
        """空列表回退到默认 URL，实际发送请求"""
        with patch("app.network.probes.httpx.Client") as MockClient:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            instance = MockClient.return_value.__enter__.return_value
            instance.get.return_value = mock_resp
            result = is_network_available_http(test_urls=[], timeout=2.0)
            assert result is True


# =====================================================================
# network_probes — is_network_available_url
# =====================================================================


class TestIsNetworkAvailableUrl:
    def test_success_matching_content(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "Success"
        with patch("app.network.probes.httpx.Client") as MockClient:
            instance = MockClient.return_value.__enter__.return_value
            instance.get.return_value = mock_resp
            result = is_network_available_url(
                url_checks=[("http://test.com", "Success")], timeout=3.0
            )
            assert result is True

    def test_failure_content_mismatch(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "Login Page"
        with patch("app.network.probes.httpx.Client") as MockClient:
            instance = MockClient.return_value.__enter__.return_value
            instance.get.return_value = mock_resp
            result = is_network_available_url(
                url_checks=[("http://test.com", "Success")], timeout=3.0
            )
            assert result is False

    def test_empty_checks_returns_true(self):
        result = is_network_available_url(url_checks=[], timeout=3.0)
        assert result is True

    def test_connection_error(self):
        with patch("app.network.probes.httpx.Client") as MockClient:
            instance = MockClient.return_value.__enter__.return_value
            instance.get.side_effect = Exception("timeout")
            result = is_network_available_url(
                url_checks=[("http://test.com", "Success")], timeout=3.0
            )
            assert result is False

    def test_check_url_keeps_verify_false(self):
        """verify=False 应保留（兼容校园网自签证书）"""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "Success"
        with patch("app.network.probes.httpx.Client") as MockClient:
            instance = MockClient.return_value.__enter__.return_value
            instance.get.return_value = mock_resp
            is_network_available_url(
                url_checks=[("http://test.com", "Success")], timeout=3.0
            )
            # 验证 verify=False 被传入 httpx.Client
            _, kwargs = MockClient.call_args
            assert kwargs.get("verify") is False


# =====================================================================
# network_decision — check_pause
# =====================================================================


class TestCheckPause:
    @patch("app.network.decision.is_in_pause_period", return_value=True)
    def test_in_pause_period(self, *mocks):
        is_paused, reason = check_pause({"pause_login": {"enabled": True}})
        assert is_paused is True
        assert reason == "pause_period"

    @patch("app.network.decision.is_in_pause_period", return_value=False)
    def test_not_in_pause_period(self, *mocks):
        is_paused, reason = check_pause({"pause_login": {"enabled": False}})
        assert is_paused is False
        assert reason == ""


# =====================================================================
# network_decision — check_network_status
# =====================================================================


class TestCheckNetworkStatus:
    def _make_config(self, **overrides):
        config = {
            "monitor": {
                "enable_tcp_check": True,
                "enable_http_check": True,
                "ping_targets": None,
                "test_urls": None,
                "url_check_urls": None,
                "network_check_timeout": 1.5,
            },
        }
        config["monitor"].update(overrides)
        return config

    @patch("app.network.decision.is_network_available", return_value=True)
    def test_network_ok(self, *mocks):
        ok, reason = check_network_status(self._make_config())
        assert ok is True
        assert reason == "network_ok"

    @patch("app.network.decision.is_network_available", return_value=False)
    def test_network_down(self, *mocks):
        ok, reason = check_network_status(self._make_config())
        assert ok is False
        assert reason == "network_down"

    def test_all_disabled(self):
        ok, reason = check_network_status(
            self._make_config(
                enable_tcp_check=False,
                enable_http_check=False,
                url_check_urls=None,
            )
        )
        assert ok is False
        assert reason == "all_disabled"


# =====================================================================
# network_decision — check_login_prerequisites
# =====================================================================


class TestCheckLoginPrerequisites:
    def _make_config(self, **overrides):
        config = {
            "auth_url": "http://10.0.0.1/login",
            "monitor": {
                "enable_local_check": True,
                "check_auth_url": True,
                "auth_url_targets": None,
            },
        }
        if "monitor" in overrides:
            config["monitor"].update(overrides.pop("monitor"))
        config.update(overrides)
        return config

    @patch("app.network.decision._is_auth_url_reachable", return_value=True)
    @patch("app.network.decision.is_local_network_connected", return_value=True)
    def test_all_pass(self, *mocks):
        ok, reason = check_login_prerequisites(self._make_config())
        assert ok is True
        assert reason == ""

    @patch("app.network.decision.is_local_network_connected", return_value=False)
    def test_local_disconnected(self, *mocks):
        ok, reason = check_login_prerequisites(self._make_config())
        assert ok is False
        assert reason == "local_disconnected"

    @patch("app.network.decision._is_auth_url_reachable", return_value=False)
    @patch("app.network.decision.is_local_network_connected", return_value=True)
    def test_auth_url_unreachable(self, *mocks):
        ok, reason = check_login_prerequisites(self._make_config())
        assert ok is False
        assert reason == "auth_url_unreachable"

    @patch("app.network.decision._is_auth_url_reachable", return_value=False)
    @patch("app.network.decision.is_local_network_connected", return_value=False)
    def test_local_check_disabled(self, *mocks):
        ok, reason = check_login_prerequisites(
            self._make_config(
                monitor={"enable_local_check": False},
            )
        )
        assert ok is False
        assert reason == "auth_url_unreachable"

    @patch("app.network.decision._is_auth_url_reachable", return_value=True)
    @patch("app.network.decision.is_local_network_connected", return_value=True)
    def test_auth_url_check_disabled(self, *mocks):
        ok, reason = check_login_prerequisites(
            self._make_config(
                monitor={"check_auth_url": False},
            )
        )
        assert ok is True
        assert reason == ""

    @patch("app.network.decision._is_auth_url_reachable", return_value=False)
    @patch("app.network.decision.is_local_network_connected", return_value=False)
    def test_both_disabled(self, *mocks):
        ok, reason = check_login_prerequisites(
            self._make_config(
                monitor={"enable_local_check": False, "check_auth_url": False},
            )
        )
        assert ok is True
        assert reason == ""


# =====================================================================
# network_decision — _is_auth_url_reachable（内部函数）
# =====================================================================


class TestIsAuthUrlReachable:
    def test_empty_url_returns_true(self):
        from app.network.decision import _is_auth_url_reachable

        assert _is_auth_url_reachable("") is True

    def test_no_hostname_returns_true(self):
        from app.network.decision import _is_auth_url_reachable

        assert _is_auth_url_reachable("http://") is True

    def test_successful_connection(self):
        from app.network.decision import _is_auth_url_reachable

        with patch("app.network.decision.socket.create_connection") as mock_conn:
            mock_conn.return_value.__enter__ = lambda s: s
            mock_conn.return_value.__exit__ = lambda s, *a: None
            assert _is_auth_url_reachable("http://10.0.0.1:8080/login") is True
            mock_conn.assert_called_once_with(("10.0.0.1", 8080), timeout=3)

    def test_connection_refused(self):
        from app.network.decision import _is_auth_url_reachable

        with patch(
            "app.network.decision.socket.create_connection",
            side_effect=ConnectionRefusedError,
        ):
            assert _is_auth_url_reachable("http://10.0.0.1/login") is False

    def test_timeout(self):
        from app.network.decision import _is_auth_url_reachable

        with patch(
            "app.network.decision.socket.create_connection", side_effect=TimeoutError
        ):
            assert _is_auth_url_reachable("http://10.0.0.1/login") is False

    def test_dns_failure(self):
        from app.network.decision import _is_auth_url_reachable

        with patch(
            "app.network.decision.socket.create_connection", side_effect=socket.gaierror
        ):
            assert _is_auth_url_reachable("http://nonexistent.local/login") is False

    def test_https_default_port(self):
        from app.network.decision import _is_auth_url_reachable

        with patch("app.network.decision.socket.create_connection") as mock_conn:
            mock_conn.return_value.__enter__ = lambda s: s
            mock_conn.return_value.__exit__ = lambda s, *a: None
            _is_auth_url_reachable("https://example.com/auth")
            mock_conn.assert_called_once_with(("example.com", 443), timeout=3)

    def test_http_default_port(self):
        from app.network.decision import _is_auth_url_reachable

        with patch("app.network.decision.socket.create_connection") as mock_conn:
            mock_conn.return_value.__enter__ = lambda s: s
            mock_conn.return_value.__exit__ = lambda s, *a: None
            _is_auth_url_reachable("http://example.com/auth")
            mock_conn.assert_called_once_with(("example.com", 80), timeout=3)


# =====================================================================
# network_decision — is_network_available
# =====================================================================


class TestIsNetworkAvailable:
    def test_all_disabled_returns_true(self):
        result = is_network_available(
            enable_tcp=False,
            enable_http=False,
            url_checks=None,
        )
        assert result is True

    @patch("app.network.decision.is_network_available_socket", return_value=True)
    @patch("app.network.decision.is_network_available_http", return_value=True)
    def test_all_pass(self, *mocks):
        result = is_network_available(
            test_sites=[("8.8.8.8", 53)],
            test_urls=["https://www.baidu.com"],
            enable_tcp=True,
            enable_http=True,
        )
        assert result is True

    @patch("app.network.decision.is_network_available_socket", return_value=False)
    @patch("app.network.decision.is_network_available_http", return_value=True)
    def test_tcp_fail_http_pass(self, *mocks):
        result = is_network_available(
            test_sites=[("8.8.8.8", 53)],
            test_urls=["https://www.baidu.com"],
            enable_tcp=True,
            enable_http=True,
        )
        assert result is False

    @patch("app.network.decision.is_network_available_socket", return_value=True)
    def test_tcp_only(self, *mocks):
        result = is_network_available(
            test_sites=[("8.8.8.8", 53)],
            enable_tcp=True,
            enable_http=False,
        )
        assert result is True


# =====================================================================
# network_decision — check_campus_network_status
# =====================================================================


class TestCheckCampusNetworkStatus:
    @patch("app.network.decision.is_local_network_connected", return_value=False)
    def test_no_local_network(self, mock_local):
        result = check_campus_network_status()
        assert "未检测到" in result

    @patch("app.network.decision.is_network_available", return_value=True)
    @patch("app.network.decision.is_local_network_connected", return_value=True)
    def test_fully_connected(self, *mocks):
        result = check_campus_network_status()
        assert "可访问互联网" in result

    @patch("app.network.decision.is_network_available", return_value=False)
    @patch("app.network.decision.is_local_network_connected", return_value=True)
    def test_connected_but_no_internet(self, *mocks):
        result = check_campus_network_status()
        assert "无法访问互联网" in result


# =====================================================================
# network_test — 向后兼容模块
# =====================================================================


class TestNetworkTestImports:
    def test_import_all_symbols(self):
        from app.network.diagnostics import (
            check_campus_network_status,
            check_login_prerequisites,
            check_network_status,
            check_pause,
            is_local_network_connected,
            is_network_available,
            is_network_available_http,
            is_network_available_socket,
            set_block_proxy,
        )

        assert callable(is_local_network_connected)
        assert callable(is_network_available_http)
        assert callable(is_network_available_socket)
        assert callable(set_block_proxy)
        assert callable(check_campus_network_status)
        assert callable(check_login_prerequisites)
        assert callable(check_network_status)
        assert callable(check_pause)
        assert callable(is_network_available)

    def test_all_list(self):
        import app.network.diagnostics as nt

        assert hasattr(nt, "__all__")
        assert len(nt.__all__) == 10

    def test_functions_match_original(self):
        from app.network.decision import is_network_available as original
        from app.network.diagnostics import is_network_available

        assert is_network_available is original
