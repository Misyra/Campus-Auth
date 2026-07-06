"""网络环境检测模块测试。"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from app.network.detect import (
    _detect_ssid_windows,
    _get_ssid_macos_modern,
    _get_windows_gateway_powershell,
    _get_windows_gateway_route_print,
    _hex_to_ipv4,
    _is_valid_ipv4,
    _parse_linux_gateway,
    _parse_windows_route_print,
    detect_gateway_ip,
    parse_darwin_netstat_routes,
    parse_linux_route_entry,
    parse_windows_all_routes,
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


class TestGetSsidMacosModern:
    """system_profiler SPAirPortDataType JSON 解析测试。"""

    @patch("app.network.detect.subprocess.run")
    def test_success_sairport_key(self, mock_run: MagicMock):
        """正常解析 spairport_current_wireless_information 键。"""
        json_data = {
            "SPAirPortDataType": [
                {
                    "spairport_current_wireless_information": {
                        "spairport_current_ssid": "MyWiFi"
                    }
                }
            ]
        }
        mock_run.return_value = MagicMock(
            returncode=0, stdout=json.dumps(json_data), stderr=""
        )
        result = _get_ssid_macos_modern()
        assert result == "MyWiFi"

    @patch("app.network.detect.subprocess.run")
    def test_success_current_key(self, mock_run: MagicMock):
        """回退解析 current_wireless_information 键。"""
        json_data = {
            "SPAirPortDataType": [
                {"current_wireless_information": {"current_ssid": "OfficeNet"}}
            ]
        }
        mock_run.return_value = MagicMock(
            returncode=0, stdout=json.dumps(json_data), stderr=""
        )
        result = _get_ssid_macos_modern()
        assert result == "OfficeNet"

    @patch("app.network.detect.subprocess.run")
    def test_nonzero_returncode(self, mock_run: MagicMock):
        """命令返回非零时返回 None。"""
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="error")
        result = _get_ssid_macos_modern()
        assert result is None

    @patch("app.network.detect.subprocess.run")
    def test_invalid_json(self, mock_run: MagicMock):
        """JSON 格式无效时返回 None。"""
        mock_run.return_value = MagicMock(returncode=0, stdout="not json", stderr="")
        result = _get_ssid_macos_modern()
        assert result is None

    @patch("app.network.detect.subprocess.run")
    def test_empty_sspairport_data_type(self, mock_run: MagicMock):
        """SPAirPortDataType 为空列表时返回 None。"""
        json_data = {"SPAirPortDataType": []}
        mock_run.return_value = MagicMock(
            returncode=0, stdout=json.dumps(json_data), stderr=""
        )
        result = _get_ssid_macos_modern()
        assert result is None

    @patch("app.network.detect.subprocess.run")
    def test_no_ssid_field(self, mock_run: MagicMock):
        """无线信息中无 SSID 字段时返回 None。"""
        json_data = {
            "SPAirPortDataType": [
                {
                    "spairport_current_wireless_information": {
                        "spairport_current_bssid": "aa:bb:cc:dd:ee:ff"
                    }
                }
            ]
        }
        mock_run.return_value = MagicMock(
            returncode=0, stdout=json.dumps(json_data), stderr=""
        )
        result = _get_ssid_macos_modern()
        assert result is None

    @patch("app.network.detect.subprocess.run")
    def test_file_not_found(self, mock_run: MagicMock):
        """system_profiler 命令不存在时返回 None。"""
        mock_run.side_effect = FileNotFoundError
        result = _get_ssid_macos_modern()
        assert result is None

    @patch("app.network.detect.subprocess.run")
    def test_empty_json_data(self, mock_run: MagicMock):
        """JSON 为空字典时返回 None。"""
        mock_run.return_value = MagicMock(returncode=0, stdout="{}", stderr="")
        result = _get_ssid_macos_modern()
        assert result is None


class TestDetectSsidDarwinFallbackOrder:
    """macOS SSID 检测回退顺序测试。"""

    @patch("app.network.detect._get_ssid_macos_modern")
    @patch("app.network.detect.subprocess.run")
    @patch("app.network.detect.is_windows", return_value=False)
    @patch("app.network.detect.is_linux", return_value=False)
    @patch("app.network.detect.is_macos", return_value=True)
    def test_airport_preferred(
        self,
        mock_is_macos: MagicMock,
        mock_is_linux: MagicMock,
        mock_is_windows: MagicMock,
        mock_run: MagicMock,
        mock_modern: MagicMock,
    ):
        """airport 成功时不再调用后续方法。"""
        mock_run.return_value = MagicMock(returncode=0, stdout="     SSID: HomeWiFi\n")
        mock_modern.return_value = None
        from app.network.detect import detect_wifi_ssid

        result = detect_wifi_ssid()
        assert result == "HomeWiFi"
        mock_modern.assert_not_called()

    @patch("app.network.detect._get_ssid_macos_modern")
    @patch("app.network.detect.subprocess.run")
    @patch("app.network.detect.is_windows", return_value=False)
    @patch("app.network.detect.is_linux", return_value=False)
    @patch("app.network.detect.is_macos", return_value=True)
    def test_system_profiler_fallback(
        self,
        mock_is_macos: MagicMock,
        mock_is_linux: MagicMock,
        mock_is_windows: MagicMock,
        mock_run: MagicMock,
        mock_modern: MagicMock,
    ):
        """airport 和 networksetup 都失败时，回退到 system_profiler。"""
        # airport 返回失败
        airport_result = MagicMock(returncode=1, stdout="")
        # networksetup -listallhardwareports 返回无 Wi-Fi 设备
        networksetup_list = MagicMock(
            returncode=0, stdout="Hardware Port: Ethernet\nDevice: en0\n"
        )
        mock_run.side_effect = [airport_result, networksetup_list]
        mock_modern.return_value = "SystemProfilerSSID"
        from app.network.detect import detect_wifi_ssid

        result = detect_wifi_ssid()
        assert result == "SystemProfilerSSID"
        # airport 和 networksetup 各调用一次
        assert mock_run.call_count == 2
        mock_run.assert_any_call(
            [
                "/System/Library/PrivateFrameworks/Apple80211.framework"
                "/Versions/Current/Resources/airport",
                "-I",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        mock_run.assert_any_call(
            ["networksetup", "-listallhardwareports"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        mock_modern.assert_called_once()


class TestHexToIpv4:
    """十六进制网关转换测试。"""

    def test_valid_gateway(self):
        """192.168.1.1 -> 0101A8C0 (little-endian hex)"""
        assert _hex_to_ipv4("0101A8C0") == "192.168.1.1"

    def test_zero_gateway(self):
        assert _hex_to_ipv4("00000000") == "0.0.0.0"

    def test_odd_length_hex(self):
        """奇数长度的十六进制字符串应返回 None。"""
        assert _hex_to_ipv4("01A8C") is None

    def test_invalid_hex_chars(self):
        assert _hex_to_ipv4("ZZZZZZZZ") is None


class TestParseLinuxGateway:
    """/proc/net/route 单行解析测试。"""

    def test_valid_default_route(self):
        """正常的默认路由行。"""
        line = "eth0\t00000000\t0101A8C0\t0001\t0\t0\t100\t00000000\t0\t0"
        assert _parse_linux_gateway(line) == "192.168.1.1"

    def test_not_default_route(self):
        """destination 非零（非默认路由）应返回 None。"""
        line = "eth0\t0000000A\t0101A8C0\t0001\t0\t0\t100\t00000000\t0\t0"
        assert _parse_linux_gateway(line) is None

    def test_too_few_fields(self):
        """字段数不足 3 应返回 None。"""
        assert _parse_linux_gateway("eth0\t00000000") is None

    def test_empty_line(self):
        assert _parse_linux_gateway("") is None

    def test_short_dest_field(self):
        """dest 字段长度不足 8 应返回 None。"""
        line = "eth0\t000000\t0101A8C0\t0001"
        assert _parse_linux_gateway(line) is None

    def test_short_gateway_field(self):
        """gateway 字段长度不足 8 应返回 None。"""
        line = "eth0\t00000000\t01A8C0\t0001"
        assert _parse_linux_gateway(line) is None

    def test_invalid_gateway_hex(self):
        """gateway 十六进制转换失败应返回 None。"""
        line = "eth0\t00000000\tZZZZZZZZ\t0001"
        assert _parse_linux_gateway(line) is None

    def test_gateway_is_zero_ip(self):
        """gateway 为 0.0.0.0 时 _parse_linux_gateway 仍返回 "0.0.0.0"，
        过滤由 _detect_gateway_linux 负责。"""
        line = "eth0\t00000000\t00000000\t0001"
        assert _parse_linux_gateway(line) == "0.0.0.0"

    def test_tab_separated(self):
        """/proc/net/route 常见格式：tab 分隔。"""
        line = "wlan0\t00000000\t0201A8C0\t0003\t0\t0\t600\t00000000\t0\t0"
        assert _parse_linux_gateway(line) == "192.168.1.2"


class TestDetectSsidWindowsEncodingFallback:
    """Windows SSID 编码回退链测试。"""

    def _make_netsh_output(self, raw_bytes: bytes) -> bytes:
        """构造 netsh wlan show interfaces 输出，SSID 为原始字节。"""
        # netsh 输出格式：每行前面有缩进，SSID 在 "SSID" 标签后
        header = b"    State                   : connected\r\n"
        ssid_line = b"    SSID                    : " + raw_bytes + b"\r\n"
        return header + ssid_line

    @patch("app.network.detect.is_macos", return_value=False)
    @patch("app.network.detect.is_linux", return_value=False)
    @patch("app.network.detect.is_windows", return_value=True)
    @patch("app.network.detect.subprocess.run")
    def test_utf8_ssid(
        self,
        mock_run: MagicMock,
        mock_is_windows: MagicMock,
        mock_is_linux: MagicMock,
        mock_is_macos: MagicMock,
    ):
        """UTF-8 编码的 SSID（现代 Windows 常见）。"""
        ssid_text = "MyWiFi_5G"
        raw = ssid_text.encode("utf-8")
        mock_run.return_value = MagicMock(
            returncode=0, stdout=self._make_netsh_output(raw)
        )
        result = _detect_ssid_windows()
        assert result == ssid_text

    @patch("app.network.detect.is_macos", return_value=False)
    @patch("app.network.detect.is_linux", return_value=False)
    @patch("app.network.detect.is_windows", return_value=True)
    @patch("app.network.detect.subprocess.run")
    def test_utf16le_ssid(
        self,
        mock_run: MagicMock,
        mock_is_windows: MagicMock,
        mock_is_linux: MagicMock,
        mock_is_macos: MagicMock,
    ):
        """UTF-16-LE 编码的 SSID（部分 Windows 系统输出）。"""
        ssid_text = "TestNetwork"
        raw = ssid_text.encode("utf-16-le")
        mock_run.return_value = MagicMock(
            returncode=0, stdout=self._make_netsh_output(raw)
        )
        result = _detect_ssid_windows()
        assert result == ssid_text

    @patch("app.network.detect.is_macos", return_value=False)
    @patch("app.network.detect.is_linux", return_value=False)
    @patch("app.network.detect.is_windows", return_value=True)
    @patch("app.network.detect.subprocess.run")
    @patch("app.network.detect.locale.getpreferredencoding", return_value="utf-8")
    def test_gbk_ssid(
        self,
        mock_locale: MagicMock,
        mock_run: MagicMock,
        mock_is_windows: MagicMock,
        mock_is_linux: MagicMock,
        mock_is_macos: MagicMock,
    ):
        """GBK 编码的中文 SSID（旧版中文 Windows）。"""
        ssid_text = "校园网"
        raw = ssid_text.encode("gbk")
        mock_run.return_value = MagicMock(
            returncode=0, stdout=self._make_netsh_output(raw)
        )
        result = _detect_ssid_windows()
        assert result == ssid_text

    @patch("app.network.detect.is_macos", return_value=False)
    @patch("app.network.detect.is_linux", return_value=False)
    @patch("app.network.detect.is_windows", return_value=True)
    @patch("app.network.detect.subprocess.run")
    @patch("app.network.detect.locale.getpreferredencoding", return_value="cp936")
    def test_locale_encoding_fallback(
        self,
        mock_locale: MagicMock,
        mock_run: MagicMock,
        mock_is_windows: MagicMock,
        mock_is_linux: MagicMock,
        mock_is_macos: MagicMock,
    ):
        """当 UTF-8 和 UTF-16-LE 都失败时，回退到 locale 编码。"""
        # cp936 编码的中文 SSID
        ssid_text = "测试网络"
        raw = ssid_text.encode("cp936")
        mock_run.return_value = MagicMock(
            returncode=0, stdout=self._make_netsh_output(raw)
        )
        result = _detect_ssid_windows()
        assert result == ssid_text

    @patch("app.network.detect.is_macos", return_value=False)
    @patch("app.network.detect.is_linux", return_value=False)
    @patch("app.network.detect.is_windows", return_value=True)
    @patch("app.network.detect.subprocess.run")
    @patch("app.network.detect.locale.getpreferredencoding", return_value="cp1252")
    def test_fallback_chain_order(
        self,
        mock_locale: MagicMock,
        mock_run: MagicMock,
        mock_is_windows: MagicMock,
        mock_is_linux: MagicMock,
        mock_is_macos: MagicMock,
    ):
        """验证回退链顺序：UTF-8 -> UTF-16-LE -> locale -> GBK。"""
        # 使用 UTF-8 编码，应该在第一次尝试就成功
        ssid_text = "FirstTry"
        raw = ssid_text.encode("utf-8")
        mock_run.return_value = MagicMock(
            returncode=0, stdout=self._make_netsh_output(raw)
        )
        result = _detect_ssid_windows()
        assert result == ssid_text
        # locale 用于构建编码链（函数启动时调用），但 UTF-8 优先成功
        mock_locale.assert_called_once_with(False)

    @patch("app.network.detect.is_macos", return_value=False)
    @patch("app.network.detect.is_linux", return_value=False)
    @patch("app.network.detect.is_windows", return_value=True)
    @patch("app.network.detect.subprocess.run")
    def test_ssid_with_null_bytes(
        self,
        mock_run: MagicMock,
        mock_is_windows: MagicMock,
        mock_is_linux: MagicMock,
        mock_is_macos: MagicMock,
    ):
        """SSID 包含 null 字节时应被清理。"""
        ssid_text = "MyWiFi"
        # 添加 null 字节（某些编码可能产生）
        raw = ssid_text.encode("utf-8") + b"\x00\x00"
        mock_run.return_value = MagicMock(
            returncode=0, stdout=self._make_netsh_output(raw)
        )
        result = _detect_ssid_windows()
        assert result == ssid_text

    @patch("app.network.detect.is_macos", return_value=False)
    @patch("app.network.detect.is_linux", return_value=False)
    @patch("app.network.detect.is_windows", return_value=True)
    @patch("app.network.detect.subprocess.run")
    def test_hex_encoded_ssid(
        self,
        mock_run: MagicMock,
        mock_is_windows: MagicMock,
        mock_is_linux: MagicMock,
        mock_is_macos: MagicMock,
    ):
        """十六进制编码的 SSID（netsh 输出格式）。"""
        # "ABC" 的十六进制表示
        ssid_text = "ABC"
        raw = ssid_text.encode("ascii").hex().upper().encode("ascii")
        mock_run.return_value = MagicMock(
            returncode=0, stdout=self._make_netsh_output(raw)
        )
        result = _detect_ssid_windows()
        assert result == ssid_text

    @patch("app.network.detect.is_macos", return_value=False)
    @patch("app.network.detect.is_linux", return_value=False)
    @patch("app.network.detect.is_windows", return_value=True)
    @patch("app.network.detect.subprocess.run")
    def test_no_ssid_in_output(
        self,
        mock_run: MagicMock,
        mock_is_windows: MagicMock,
        mock_is_linux: MagicMock,
        mock_is_macos: MagicMock,
    ):
        """输出中无 SSID 时返回 None。"""
        mock_run.return_value = MagicMock(
            returncode=0, stdout=b"    State                   : disconnected\r\n"
        )
        result = _detect_ssid_windows()
        assert result is None

    @patch("app.network.detect.is_macos", return_value=False)
    @patch("app.network.detect.is_linux", return_value=False)
    @patch("app.network.detect.is_windows", return_value=True)
    @patch("app.network.detect.subprocess.run")
    def test_empty_ssid(
        self,
        mock_run: MagicMock,
        mock_is_windows: MagicMock,
        mock_is_linux: MagicMock,
        mock_is_macos: MagicMock,
    ):
        """空 SSID 返回 None。"""
        mock_run.return_value = MagicMock(
            returncode=0, stdout=b"    SSID                    : \r\n"
        )
        result = _detect_ssid_windows()
        assert result is None


class TestParseWindowsAllRoutes:
    """route print 多路由解析测试。"""

    def test_multiple_routes(self):
        """多条默认路由应全部返回。"""
        output = (
            "Network Destination        Netmask          Gateway       Interface  Metric\n"
            "          0.0.0.0          0.0.0.0      192.168.1.1     192.168.1.100     25\n"
            "          0.0.0.0          0.0.0.0      10.0.0.254       10.0.0.100     30\n"
        )
        routes = parse_windows_all_routes(output)
        assert len(routes) == 2
        assert routes[0] == ("192.168.1.1", "192.168.1.100")
        assert routes[1] == ("10.0.0.254", "10.0.0.100")

    def test_skips_zero_gateway(self):
        """网关为 0.0.0.0 的路由应被跳过。"""
        output = (
            "Network Destination        Netmask          Gateway       Interface  Metric\n"
            "          0.0.0.0          0.0.0.0          0.0.0.0     10.0.0.100     15\n"
            "          0.0.0.0          0.0.0.0      10.0.0.1      10.0.0.100     25\n"
        )
        routes = parse_windows_all_routes(output)
        assert len(routes) == 1
        assert routes[0] == ("10.0.0.1", "10.0.0.100")

    def test_no_default_route(self):
        """无默认路由时返回空列表。"""
        output = (
            "Network Destination        Netmask          Gateway       Interface  Metric\n"
            "        127.0.0.0        255.0.0.0         On-link         127.0.0.1    331\n"
        )
        assert parse_windows_all_routes(output) == []

    def test_empty_output(self):
        assert parse_windows_all_routes("") == []


class TestParseLinuxRouteEntry:
    """/proc/net/route 带接口名解析测试。"""

    def test_valid_default_route(self):
        line = "eth0\t00000000\t0101A8C0\t0001\t0\t0\t100\t00000000\t0\t0"
        result = parse_linux_route_entry(line)
        assert result == ("eth0", "192.168.1.1")

    def test_not_default_route(self):
        line = "eth0\t0000000A\t0101A8C0\t0001\t0\t0\t100\t00000000\t0\t0"
        assert parse_linux_route_entry(line) is None

    def test_too_few_fields(self):
        assert parse_linux_route_entry("eth0\t00000000") is None

    def test_empty_line(self):
        assert parse_linux_route_entry("") is None

    def test_short_fields(self):
        line = "eth0\t000000\t01A8C0\t0001"
        assert parse_linux_route_entry(line) is None

    def test_wlan_interface(self):
        line = "wlan0\t00000000\t0201A8C0\t0003\t0\t0\t600\t00000000\t0\t0"
        result = parse_linux_route_entry(line)
        assert result == ("wlan0", "192.168.1.2")

    def test_zero_gateway(self):
        """网关为 0.0.0.0 时仍返回（过滤由调用方负责）。"""
        line = "eth0\t00000000\t00000000\t0001"
        result = parse_linux_route_entry(line)
        assert result == ("eth0", "0.0.0.0")


class TestParseDarwinNetstatRoutes:
    """macOS netstat -rn 解析测试。"""

    def test_single_default_route(self):
        output = """Routing tables:

Internet:
Destination        Gateway            Flags           Netif Expire
default            192.168.1.1        UGScg          en0
127.0.0.1          127.0.0.1          UH             lo0

Internet6:
"""
        routes = parse_darwin_netstat_routes(output)
        assert routes == {"en0": "192.168.1.1"}

    def test_multiple_default_routes(self):
        output = """Routing tables:

Internet:
Destination        Gateway            Flags           Netif Expire
default            192.168.1.1        UGScg          en0
default            10.0.0.254         UGScIg         en1
127.0.0.1          127.0.0.1          UH             lo0

Internet6:
"""
        routes = parse_darwin_netstat_routes(output)
        assert routes.get("en0") == "192.168.1.1"
        assert routes.get("en1") == "10.0.0.254"
        assert "lo0" not in routes

    def test_no_internet_section(self):
        output = """Routing tables:

Internet6:
"""
        assert parse_darwin_netstat_routes(output) == {}

    def test_empty_output(self):
        assert parse_darwin_netstat_routes("") == {}

    def test_zero_gateway_skipped(self):
        output = """Routing tables:

Internet:
Destination        Gateway            Flags           Netif Expire
default            0.0.0.0            UGScg          en0

Internet6:
"""
        assert parse_darwin_netstat_routes(output) == {}
