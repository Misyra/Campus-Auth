"""网络环境检测模块测试。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.network.detect import (
    _get_windows_gateway_powershell,
    _get_windows_gateway_route_print,
    _is_valid_ipv4,
    _parse_windows_route_print,
    detect_gateway_ip,
)


class TestIsValidIpv4:
    """IPv4 地址验证测试。"""

    def test_valid_ip(self):
        assert _is_valid_ipv4("192.168.1.1") is True
        assert _is_valid_ipv4("10.0.0.1") is True
        assert _is_valid_ipv4("8.8.8.8") is True

    def test_invalid_ip(self):
        assert _is_valid_ipv4("0.0.0.0") is True  # 合法 IP，但业务上过滤
        assert _is_valid_ipv4("not_an_ip") is False
        assert _is_valid_ipv4("256.1.1.1") is False
        assert _is_valid_ipv4("") is False
        assert _is_valid_ipv4("192.168.1") is False


class TestParseWindowsRoutePrint:
    """route print 输出解析测试。"""

    def test_parse_standard_output(self):
        output = """===========================================================================
IPv4 Route Table
===========================================================================
Active Routes:
Network Destination        Netmask          Gateway       Interface  Metric
          0.0.0.0          0.0.0.0      192.168.1.1     192.168.1.100     25
        127.0.0.0        255.0.0.0         On-link         127.0.0.1    331
===========================================================================
"""
        assert _parse_windows_route_print(output) == "192.168.1.1"

    def test_parse_multiple_routes(self):
        """有多个 0.0.0.0 路由时，返回第一个非零网关。"""
        output = """Network Destination        Netmask          Gateway       Interface  Metric
          0.0.0.0          0.0.0.0          0.0.0.0     10.0.0.100     15
          0.0.0.0          0.0.0.0      10.0.0.1      10.0.0.100     25
"""
        assert _parse_windows_route_print(output) == "10.0.0.1"

    def test_parse_no_default_route(self):
        output = """Network Destination        Netmask          Gateway       Interface  Metric
        127.0.0.0        255.0.0.0         On-link         127.0.0.1    331
"""
        assert _parse_windows_route_print(output) is None

    def test_parse_empty_output(self):
        assert _parse_windows_route_print("") is None

    def test_parse_all_zero_gateway(self):
        """所有默认路由网关都是 0.0.0.0 时返回 None。"""
        output = """Network Destination        Netmask          Gateway       Interface  Metric
          0.0.0.0          0.0.0.0          0.0.0.0     10.0.0.100     15
"""
        assert _parse_windows_route_print(output) is None


class TestGetWindowsGatewayRoutePrint:
    """route print 调用测试。"""

    @patch("app.network.detect.subprocess.run")
    def test_success(self, mock_run: MagicMock):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="Network Destination        Netmask          Gateway       Interface  Metric\n"
            "          0.0.0.0          0.0.0.0      192.168.1.1     192.168.1.100     25\n",
        )
        result = _get_windows_gateway_route_print()
        assert result == "192.168.1.1"
        args, kwargs = mock_run.call_args
        assert args[0] == ["route", "print", "0.0.0.0"]
        assert kwargs["capture_output"] is True
        assert kwargs["text"] is True
        assert kwargs["timeout"] == 5

    @patch("app.network.detect.subprocess.run")
    def test_route_not_found(self, mock_run: MagicMock):
        mock_run.side_effect = FileNotFoundError
        result = _get_windows_gateway_route_print()
        assert result is None

    @patch("app.network.detect.subprocess.run")
    def test_non_zero_returncode(self, mock_run: MagicMock):
        mock_run.return_value = MagicMock(returncode=1, stdout="")
        result = _get_windows_gateway_route_print()
        assert result is None


class TestGetWindowsGatewayPowershell:
    """PowerShell 调用测试。"""

    @patch("app.network.detect.subprocess.run")
    def test_success(self, mock_run: MagicMock):
        mock_run.return_value = MagicMock(returncode=0, stdout="10.0.0.1\n")
        result = _get_windows_gateway_powershell()
        assert result == "10.0.0.1"

    @patch("app.network.detect.subprocess.run")
    def test_powershell_not_found(self, mock_run: MagicMock):
        mock_run.side_effect = FileNotFoundError
        result = _get_windows_gateway_powershell()
        assert result is None

    @patch("app.network.detect.subprocess.run")
    def test_invalid_output(self, mock_run: MagicMock):
        mock_run.return_value = MagicMock(returncode=0, stdout="not_an_ip\n")
        result = _get_windows_gateway_powershell()
        assert result is None


class TestDetectGatewayWindowsIntegration:
    """Windows 网关检测集成测试（mock subprocess）。"""

    @patch("app.network.detect._get_windows_gateway_powershell")
    @patch("app.network.detect._get_windows_gateway_route_print")
    @patch("app.network.detect.is_windows", return_value=True)
    def test_route_print_preferred(
        self,
        mock_is_windows: MagicMock,
        mock_route: MagicMock,
        mock_ps: MagicMock,
    ):
        """route print 成功时，不再调用 PowerShell。"""
        mock_route.return_value = "192.168.1.1"
        mock_ps.return_value = None
        result = detect_gateway_ip()
        assert result == "192.168.1.1"
        mock_route.assert_called_once()
        mock_ps.assert_not_called()

    @patch("app.network.detect._get_windows_gateway_powershell")
    @patch("app.network.detect._get_windows_gateway_route_print")
    @patch("app.network.detect.is_windows", return_value=True)
    def test_fallback_to_powershell(
        self,
        mock_is_windows: MagicMock,
        mock_route: MagicMock,
        mock_ps: MagicMock,
    ):
        """route print 失败时，回退到 PowerShell。"""
        mock_route.return_value = None
        mock_ps.return_value = "10.0.0.1"
        result = detect_gateway_ip()
        assert result == "10.0.0.1"
        mock_route.assert_called_once()
        mock_ps.assert_called_once()
