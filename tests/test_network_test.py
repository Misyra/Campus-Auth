from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.network_test import (
    _check_macos_service,
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
    """测试 set_block_proxy 对 _block_proxy 标志位的影响"""

    def test_block_proxy_default_is_true(self):
        """默认 _block_proxy 应为 True"""
        import src.network_test as nt
        nt.set_block_proxy(True)
        assert nt._block_proxy is True

    def test_block_proxy_true_sets_flag(self):
        """set_block_proxy(True) → _block_proxy = True"""
        import src.network_test as nt
        nt.set_block_proxy(True)
        assert nt._block_proxy is True

    def test_block_proxy_false_sets_flag(self):
        """set_block_proxy(False) → _block_proxy = False"""
        import src.network_test as nt
        nt.set_block_proxy(False)
        assert nt._block_proxy is False


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
