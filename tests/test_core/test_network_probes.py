"""网络检测模块综合测试

覆盖 network_probes、network_decision 的全部函数，以及 network_test 向后兼容模块。
"""

from __future__ import annotations

import socket
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _fresh_executor():
    """确保模块级 executor 未被关闭（atexit 或前序测试可能已触发 shutdown）。"""
    import app.network.probes as probes_mod
    import app.network.decision as decision_mod

    old = probes_mod.executor
    try:
        old.submit(lambda: None).result(timeout=1)
    except RuntimeError:
        # executor 已关闭，替换为新实例
        fresh = ThreadPoolExecutor(max_workers=8, thread_name_prefix="net-test")
        probes_mod.executor = fresh
        decision_mod._executor = fresh
        yield
        fresh.shutdown(wait=False, cancel_futures=True)
        probes_mod.executor = old
        decision_mod._executor = old
        return
    yield

from app.network.decision import (
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
from app.schemas import MonitorSettings, PauseSettings

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
    def test_returns_true_when_interface_up(self):
        """有活跃的非回环接口时返回 True。"""
        mock_stats = {
            "Ethernet": MagicMock(isup=True, speed=1000),
            "Loopback Pseudo-Interface 1": MagicMock(isup=True, speed=1073),
        }
        with patch("app.network.probes.psutil.net_if_stats", return_value=mock_stats):
            assert is_local_network_connected() is True

    def test_returns_false_on_loopback_only(self):
        """仅有回环接口时返回 False。"""
        mock_stats = {
            "lo": MagicMock(isup=True, speed=0),
        }
        with patch("app.network.probes.psutil.net_if_stats", return_value=mock_stats):
            assert is_local_network_connected() is False

    def test_returns_false_on_exception(self):
        """psutil 抛异常时返回 False。"""
        with patch(
            "app.network.probes.psutil.net_if_stats",
            side_effect=Exception("fail"),
        ):
            assert is_local_network_connected() is False

    def test_returns_false_when_all_down(self):
        """所有接口都 down 时返回 False。"""
        mock_stats = {
            "Ethernet": MagicMock(isup=False, speed=0),
            "Wi-Fi": MagicMock(isup=False, speed=0),
        }
        with patch("app.network.probes.psutil.net_if_stats", return_value=mock_stats):
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
    def _setup_mock_client(self, MockClient, mock_resp):
        """_get_probe_client() 直接返回 client 实例，不需要 __enter__ 上下文。"""
        MockClient.return_value.get.return_value = mock_resp

    def test_success_200(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        with patch("app.network.probes.httpx.Client") as MockClient:
            self._setup_mock_client(MockClient, mock_resp)
            result = is_network_available_http(
                test_urls=["https://www.baidu.com"], timeout=2.0
            )
            assert result is True

    def test_failure_500(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        with patch("app.network.probes.httpx.Client") as MockClient:
            self._setup_mock_client(MockClient, mock_resp)
            result = is_network_available_http(
                test_urls=["https://www.baidu.com"], timeout=2.0
            )
            assert result is False

    def test_connection_error(self):
        with patch("app.network.probes.httpx.Client") as MockClient:
            MockClient.return_value.get.side_effect = Exception("connection error")
            result = is_network_available_http(
                test_urls=["https://www.baidu.com"], timeout=2.0
            )
            assert result is False

    def test_empty_urls_uses_defaults(self):
        """空列表回退到默认 URL（captive portal），需要 204 才算成功"""
        with patch("app.network.probes.httpx.Client") as MockClient:
            mock_resp = MagicMock()
            mock_resp.status_code = 204
            self._setup_mock_client(MockClient, mock_resp)
            result = is_network_available_http(test_urls=[], timeout=2.0)
            assert result is True


# =====================================================================
# network_probes — is_network_available_url
# =====================================================================


class TestIsNetworkAvailableUrl:
    def setup_method(self):
        """清空 _probe_client 缓存，确保每次测试使用新的 mock。"""
        import app.network.probes as probes_module

        probes_module._probe_client = None

    def _setup_mock_client(self, MockClient, mock_resp):
        """_get_probe_client() 直接返回 client 实例，不需要 __enter__ 上下文。"""
        MockClient.return_value.get.return_value = mock_resp

    def test_success_matching_content(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "Success"
        with patch("app.network.probes.httpx.Client") as MockClient:
            self._setup_mock_client(MockClient, mock_resp)
            result = is_network_available_url(
                url_checks=[("http://test.com", "Success")], timeout=3.0
            )
            assert result is True

    def test_failure_content_mismatch(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "Login Page"
        with patch("app.network.probes.httpx.Client") as MockClient:
            self._setup_mock_client(MockClient, mock_resp)
            result = is_network_available_url(
                url_checks=[("http://test.com", "Success")], timeout=3.0
            )
            assert result is False

    def test_empty_checks_returns_true(self):
        result = is_network_available_url(url_checks=[], timeout=3.0)
        assert result is True

    def test_connection_error(self):
        with patch("app.network.probes.httpx.Client") as MockClient:
            MockClient.return_value.get.side_effect = Exception("timeout")
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
            self._setup_mock_client(MockClient, mock_resp)
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
    @patch("app.network.decision.is_pause_enabled", return_value=True)
    def test_in_pause_period(self, *mocks):
        is_paused, reason = check_pause(PauseSettings(enabled=True))
        assert is_paused is True
        assert reason == "pause_period"

    @patch("app.network.decision.is_pause_enabled", return_value=False)
    def test_not_in_pause_period(self, *mocks):
        is_paused, reason = check_pause(PauseSettings(enabled=False))
        assert is_paused is False
        assert reason == ""


# =====================================================================
# network_decision — check_network_status
# =====================================================================


class TestCheckNetworkStatus:
    def _make_config(self, **overrides):
        defaults = {
            "enable_tcp_check": True,
            "enable_http_check": True,
            "ping_targets": [],
            "test_urls": [],
            "url_check_urls": [],
            "network_check_timeout": 2,
        }
        defaults.update(overrides)
        return MonitorSettings(**defaults)

    @patch("app.network.decision.is_network_available", return_value=True)
    def test_network_ok(self, *mocks):
        ok, reason, method = check_network_status(self._make_config())
        assert ok is True
        assert reason == "network_ok"
        assert method in ("tcp", "http", "url", "local_only")

    @patch("app.network.decision.is_network_available", return_value=False)
    def test_network_down(self, *mocks):
        ok, reason, method = check_network_status(self._make_config())
        assert ok is False
        assert reason == "network_down"
        assert method == "none"

    def test_all_disabled(self):
        ok, reason, method = check_network_status(
            self._make_config(
                enable_tcp_check=False,
                enable_http_check=False,
                url_check_urls=[],
            )
        )
        assert ok is False
        assert reason == "all_disabled"
        assert method == "none"


# =====================================================================
# network_decision — check_login_prerequisites
# =====================================================================


class TestCheckLoginPrerequisites:
    def _make_config(self, **overrides):
        defaults = {
            "enable_local_check": True,
            "check_auth_url": True,
            "auth_url_targets": [],
        }
        defaults.update(overrides)
        return MonitorSettings(**defaults)

    @patch("app.network.decision._is_auth_url_reachable", return_value=True)
    @patch("app.network.decision.is_local_network_connected", return_value=True)
    def test_all_pass(self, *mocks):
        ok, reason = check_login_prerequisites(
            self._make_config(), "http://10.0.0.1/login"
        )
        assert ok is True
        assert reason == ""

    @patch("app.network.decision.is_local_network_connected", return_value=False)
    def test_local_disconnected(self, *mocks):
        ok, reason = check_login_prerequisites(
            self._make_config(), "http://10.0.0.1/login"
        )
        assert ok is False
        assert reason == "local_disconnected"

    @patch("app.network.decision._is_auth_url_reachable", return_value=False)
    @patch("app.network.decision.is_local_network_connected", return_value=True)
    def test_auth_url_unreachable(self, *mocks):
        ok, reason = check_login_prerequisites(
            self._make_config(), "http://10.0.0.1/login"
        )
        assert ok is False
        assert reason == "auth_url_unreachable"

    @patch("app.network.decision._is_auth_url_reachable", return_value=False)
    @patch("app.network.decision.is_local_network_connected", return_value=False)
    def test_local_check_disabled(self, *mocks):
        ok, reason = check_login_prerequisites(
            self._make_config(enable_local_check=False),
            "http://10.0.0.1/login",
        )
        assert ok is False
        assert reason == "auth_url_unreachable"

    @patch("app.network.decision._is_auth_url_reachable", return_value=True)
    @patch("app.network.decision.is_local_network_connected", return_value=True)
    def test_auth_url_check_disabled(self, *mocks):
        ok, reason = check_login_prerequisites(
            self._make_config(check_auth_url=False),
            "http://10.0.0.1/login",
        )
        assert ok is True
        assert reason == ""

    @patch("app.network.decision._is_auth_url_reachable", return_value=False)
    @patch("app.network.decision.is_local_network_connected", return_value=False)
    def test_both_disabled(self, *mocks):
        ok, reason = check_login_prerequisites(
            self._make_config(enable_local_check=False, check_auth_url=False),
            "http://10.0.0.1/login",
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

    def test_no_hostname_returns_false(self):
        from app.network.decision import _is_auth_url_reachable

        # hostname 解析失败视为不可达（[44] 修复：原错误返回 True）
        assert _is_auth_url_reachable("http://") is False

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

    def test_extra_targets_reachable(self):
        """extra_targets 中任一目标可达返回 True。"""
        from app.network.decision import _is_auth_url_reachable

        with patch("app.network.decision.socket.create_connection") as mock_conn:
            mock_conn.return_value.__enter__ = lambda s: s
            mock_conn.return_value.__exit__ = lambda s, *a: None
            assert (
                _is_auth_url_reachable(
                    "",
                    extra_targets=["10.0.0.1:8080", "10.0.0.2:9090"],
                )
                is True
            )

    def test_extra_targets_all_unreachable(self):
        """extra_targets 全部不可达返回 False。"""
        from app.network.decision import _is_auth_url_reachable

        with patch(
            "app.network.decision.socket.create_connection",
            side_effect=TimeoutError,
        ):
            assert (
                _is_auth_url_reachable(
                    "",
                    extra_targets=["10.0.0.1:8080", "10.0.0.2:9090"],
                )
                is False
            )

    @patch('app.network.decision.socket.create_connection', side_effect=TimeoutError)
    def test_extra_targets_empty_skip(self, mock_conn):
        """extra_targets 解析为空时跳过检测。"""
        from app.network.decision import _is_auth_url_reachable

        assert _is_auth_url_reachable("http://10.0.0.1/login", extra_targets=[]) is False


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

    @patch("app.network.decision.is_network_available_url", return_value=True)
    def test_url_checks_only(self, *mocks):
        """仅启用 URL 响应检测。"""
        result = is_network_available(
            enable_tcp=False,
            enable_http=False,
            url_checks=[("http://test.com", "Success")],
        )
        assert result is True

    @patch("app.network.decision.is_network_available_url", return_value=False)
    def test_url_checks_fail(self, *mocks):
        """URL 响应检测失败。"""
        result = is_network_available(
            enable_tcp=False,
            enable_http=False,
            url_checks=[("http://test.com", "Success")],
        )
        assert result is False

    @patch("app.network.decision.is_network_available_socket", side_effect=Exception("boom"))
    def test_future_exception_returns_false(self, *mocks):
        """future 抛异常时视为检测失败。"""
        result = is_network_available(
            test_sites=[("8.8.8.8", 53)],
            enable_tcp=True,
            enable_http=False,
        )
        assert result is False
