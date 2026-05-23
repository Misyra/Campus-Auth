from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx

from src.network_test import (
    _check_macos_service,
    _get_http_client,
    _thread_local,
    is_network_available,
    is_local_network_connected,
    set_block_proxy,
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
    """测试 set_block_proxy 对 _get_http_client 的影响"""

    def _clear_thread_local_client(self):
        """清理线程本地存储的 httpx 客户端"""
        if hasattr(_thread_local, "client"):
            del _thread_local.client

    def test_block_proxy_true_creates_client_with_trust_env_false(self):
        """set_block_proxy(True) → trust_env=False"""
        self._clear_thread_local_client()
        set_block_proxy(True)
        client = _get_http_client()
        assert client.trust_env is False

    def test_block_proxy_false_creates_client_with_trust_env_true(self):
        """set_block_proxy(False) → trust_env=True"""
        self._clear_thread_local_client()
        set_block_proxy(False)
        client = _get_http_client()
        assert client.trust_env is True

    def test_block_proxy_switches_correctly(self):
        """切换 set_block_proxy 后新客户端应使用新设置"""
        self._clear_thread_local_client()

        with patch("src.network_test.httpx.Client") as mock_client_cls:
            mock_client_cls.return_value = MagicMock(spec=httpx.Client)

            set_block_proxy(True)
            _get_http_client()
            call_kwargs = mock_client_cls.call_args.kwargs
            assert call_kwargs.get("trust_env") is False

        self._clear_thread_local_client()

        with patch("src.network_test.httpx.Client") as mock_client_cls:
            mock_client_cls.return_value = MagicMock(spec=httpx.Client)

            set_block_proxy(False)
            _get_http_client()
            call_kwargs = mock_client_cls.call_args.kwargs
            assert call_kwargs.get("trust_env") is True

    def test_default_block_proxy_is_true(self):
        """默认 _block_proxy 应为 True"""
        import src.network_test
        src.network_test.set_block_proxy(True)
        assert src.network_test._block_proxy is True


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
        with patch("src.network_test.subprocess.run", mock_run):
            with patch("src.network_test.is_macos", return_value=True):
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
        with patch("src.network_test.subprocess.run", mock_run):
            with patch("src.network_test.is_macos", return_value=True):
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
        with patch("src.network_test.subprocess.run", mock_run):
            with patch("src.network_test.is_macos", return_value=True):
                _check_macos_service()
                ifconfig_calls = [
                    call for call in mock_run.call_args_list
                    if call[0][0][0] == "ifconfig"
                ]
                # 降级后只检查 en0、en1
                assert len(ifconfig_calls) == 2
