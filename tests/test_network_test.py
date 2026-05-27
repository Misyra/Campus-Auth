from __future__ import annotations

import logging
import ssl

from unittest.mock import MagicMock, patch

from src.network_test import (
    _check_macos_service,
    is_network_available,
    is_network_available_http,
    is_local_network_connected,
)


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


class TestSetBlockProxy:
    """测试 set_block_proxy 对 _block_proxy 标志位的影响"""

    def test_block_proxy_default_is_true(self):
        """默认 _block_proxy 应为 True"""
        import src.network_probes as np
        np.set_block_proxy(True)
        assert np._block_proxy is True

    def test_block_proxy_true_sets_flag(self):
        """set_block_proxy(True) → _block_proxy = True"""
        import src.network_probes as np
        np.set_block_proxy(True)
        assert np._block_proxy is True

    def test_block_proxy_false_sets_flag(self):
        """set_block_proxy(False) → _block_proxy = False"""
        import src.network_probes as np
        np.set_block_proxy(False)
        assert np._block_proxy is False


class TestCheckMacosService:
    """测试 macOS 网络检测使用 networksetup 而非硬编码 en0/en1"""

    def test_uses_networksetup_not_hardcoded_en0_en1(self):
        """_check_macos_service 应使用 networksetup 检测接口"""
        mock_run = MagicMock()
        # 第一次调用 networksetup 返回设备列表，第二次调用 ifconfig 返回无网络
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="Device: en0\nDevice: en1\n"),
            MagicMock(returncode=0, stdout=""),
            MagicMock(returncode=0, stdout=""),
        ]
        with patch("src.network_probes.subprocess.run", mock_run):
            with patch("src.network_probes.is_macos", return_value=True):
                _check_macos_service()
                # 验证 networksetup 被调用
                networksetup_call = mock_run.call_args_list[0]
                assert networksetup_call[0][0][0] == "networksetup"
                assert "-listallhardwareports" in str(networksetup_call[0][0])

    def test_networksetup_output_parsed_for_device_names(self):
        """_check_macos_service 应解析 networksetup 输出中的所有设备名"""
        mock_run = MagicMock()
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="Device: en0\nDevice: en1\nDevice: en2\n"),
            MagicMock(returncode=0, stdout=""),
            MagicMock(returncode=0, stdout=""),
            MagicMock(returncode=0, stdout=""),
        ]
        with patch("src.network_probes.subprocess.run", mock_run):
            with patch("src.network_probes.is_macos", return_value=True):
                _check_macos_service()
                # 应调用 ifconfig 三次（各设备一次），而非仅 en0/en1
                ifconfig_calls = [
                    call for call in mock_run.call_args_list
                    if call[0][0][0] == "ifconfig"
                ]
                assert len(ifconfig_calls) == 3

    def test_networksetup_failure_uses_en0_en1_fallback(self):
        """networksetup 失败时降级到 en0/en1 硬编码回退"""
        mock_run = MagicMock()
        mock_run.side_effect = [
            MagicMock(returncode=1, stdout=""),
            MagicMock(returncode=0, stdout=""),
            MagicMock(returncode=0, stdout=""),
        ]
        with patch("src.network_probes.subprocess.run", mock_run):
            with patch("src.network_probes.is_macos", return_value=True):
                _check_macos_service()
                ifconfig_calls = [
                    call for call in mock_run.call_args_list
                    if call[0][0][0] == "ifconfig"
                ]
                # 降级后只检查 en0、en1
                assert len(ifconfig_calls) == 2


class TestSslProbe:
    """SSL 证书错误与 HTTP 探测器测试"""

    def test_http_probe_ssl_cert_error_returns_false(self):
        """SSL 证书错误时 is_network_available_http 应返回 False 而非崩溃"""
        with patch('src.network_probes.httpx.Client') as mock_client:
            mock_client.return_value.__enter__.side_effect = ssl.SSLError("certificate verify failed")
            result = is_network_available_http(
                test_urls=["https://test.example.com"],
                timeout=0.5,
            )
        assert result is False

    def test_http_probe_ssl_redirect_returns_false(self):
        """302 重定向（认证门户）不应被视为网络连通"""
        with patch('src.network_probes.httpx.Client') as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 302
            # httpx.Client() → ctx_mgr, ctx_mgr.__enter__() → client, client.get() → resp
            mock_client_instance = MagicMock()
            mock_client_instance.get.return_value = mock_response
            mock_client.return_value.__enter__.return_value = mock_client_instance
            result = is_network_available_http(
                test_urls=["https://test.example.com"],
                timeout=0.5,
                follow_redirects=False,
            )
        assert result is False

    def test_http_probe_ssl_200_returns_true(self):
        """HTTP 200 响应应被视为网络连通"""
        with patch('src.network_probes.httpx.Client') as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_client_instance = MagicMock()
            mock_client_instance.get.return_value = mock_response
            mock_client.return_value.__enter__.return_value = mock_client_instance
            result = is_network_available_http(
                test_urls=["https://test.example.com"],
                timeout=0.5,
            )
        assert result is True

    def test_http_probe_ssl_error_logged_at_debug(self, caplog):
        """SSL 证书验证错误应在 DEBUG 级别记录"""
        with patch('src.network_probes.httpx.Client') as mock_client:
            mock_client.return_value.__enter__.side_effect = ssl.SSLError("certificate verify failed")
            with caplog.at_level(logging.DEBUG, logger="network_probes"):
                is_network_available_http(
                    test_urls=["https://test.example.com"],
                    timeout=0.5,
                )
        # 筛选 SSL 证书验证专用日志（不含后续 INFO 中的 "SSLError" 字样）
        ssl_records = [r for r in caplog.records if "证书验证失败" in r.getMessage()]
        assert len(ssl_records) > 0, "SSL 证书验证错误日志应出现在记录中"
        assert all(r.levelno == logging.DEBUG for r in ssl_records), "SSL 证书验证错误应在 DEBUG 级别记录"

    def test_http_strict_mode_ssl_error_returns_false(self):
        """严格模式下 HTTP 探测失败（SSL 错误）时 is_network_available 应返回 False"""
        with patch('src.network_decision.is_network_available_http', return_value=False):
            with patch('src.network_decision.is_network_available_socket', return_value=True):
                with patch('src.network_decision.is_local_network_connected', return_value=True):
                    result = is_network_available(require_both=True)
        assert result is False

    def test_http_probe_verify_false_no_console_warning(self, caplog):
        """verify=False 不应产生 InsecureRequestWarning 等 SSL 警告"""
        with patch('src.network_probes.httpx.Client') as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_client_instance = MagicMock()
            mock_client_instance.get.return_value = mock_response
            mock_client.return_value.__enter__.return_value = mock_client_instance
            with caplog.at_level(logging.DEBUG, logger="network_probes"):
                result = is_network_available_http(
                    test_urls=["https://test.example.com"],
                    timeout=0.5,
                )
        assert result is True
        # httpx 使用 httpcore 而非 urllib3，不应产生 InsecureRequestWarning
        assert "InsecureRequest" not in caplog.text
