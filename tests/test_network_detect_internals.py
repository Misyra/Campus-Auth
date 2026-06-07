"""network_detect 私有 helper 真实执行测试。

不 mock 解析逻辑，仅 mock subprocess.run / builtins.open 等 I/O 层，
用真实命令输出字符串验证 6 个私有 helper 的解析正确性。
"""

from __future__ import annotations

import builtins
from unittest.mock import patch, MagicMock, mock_open

import pytest

import app.network.detect as nd


# ── 辅助工具 ──


def _make_subprocess_result(
    stdout: str | bytes = "", returncode: int = 0
) -> MagicMock:
    """构造模拟 subprocess.CompletedProcess 对象。"""
    mock = MagicMock()
    mock.stdout = stdout
    mock.returncode = returncode
    return mock


# ══════════════════════════════════════════════════════════════
#  Windows 网关检测
# ══════════════════════════════════════════════════════════════


@patch.object(nd, "is_linux", return_value=False)
@patch.object(nd, "is_macos", return_value=False)
@patch.object(nd, "is_windows", return_value=True)
class TestDetectGatewayWindows:
    """测试 _detect_gateway_windows 的 PowerShell 与 ipconfig 回退逻辑。"""

    @patch(
        "subprocess.run",
        return_value=_make_subprocess_result("192.168.1.1\n"),
    )
    def test_powershell_success(self, _mock_run, *_):
        """PowerShell Get-NetRoute 成功返回网关 IP。"""
        assert nd._detect_gateway_windows() == "192.168.1.1"

    @patch(
        "subprocess.run",
        return_value=_make_subprocess_result("10.0.0.1\r\n"),
    )
    def test_powershell_with_crlf(self, _mock_run, *_):
        """PowerShell 输出带 CRLF 时应正确 strip。"""
        assert nd._detect_gateway_windows() == "10.0.0.1"

    @patch("subprocess.run", side_effect=FileNotFoundError)
    def test_powershell_not_found_returns_none(self, _mock_run, *_):
        """PowerShell 和 ipconfig 都不存在时返回 None。"""
        assert nd._detect_gateway_windows() is None

    @patch("subprocess.run")
    def test_ipconfig_fallback_chinese_gbk(self, mock_run, *_):
        """PowerShell 失败后回退到 ipconfig，解析中文 GBK 输出。"""
        ps_result = _make_subprocess_result("")
        ps_result.returncode = 1
        ipconfig_output = (
            b"Windows IP Configuration\r\n"
            b"\r\n"
            b"Ethernet adapter Ethernet:\r\n"
            b"\r\n"
            b"   Connection-specific DNS Suffix  . :\r\n"
            b"   IPv4 Address. . . . . . . . . . . : 192.168.1.100\r\n"
            b"   Subnet Mask . . . . . . . . . . . : 255.255.255.0\r\n"
            b"   \xc4\xac\xc8\xcf\xcd\xf8\xb9\xd8 . . . . . . . . . : 192.168.1.1\r\n"
        )
        ipconfig_result = _make_subprocess_result(ipconfig_output)
        mock_run.side_effect = [ps_result, ipconfig_result]
        assert nd._detect_gateway_windows() == "192.168.1.1"

    @patch("subprocess.run")
    def test_ipconfig_fallback_english(self, mock_run, *_):
        """回退到 ipconfig，解析英文输出。"""
        ps_result = _make_subprocess_result("")
        ps_result.returncode = 1
        ipconfig_output = (
            b"Windows IP Configuration\r\n"
            b"\r\n"
            b"Ethernet adapter Ethernet:\r\n"
            b"\r\n"
            b"   Default Gateway . . . . . . . . . : 10.0.0.1\r\n"
        )
        ipconfig_result = _make_subprocess_result(ipconfig_output)
        mock_run.side_effect = [ps_result, ipconfig_result]
        assert nd._detect_gateway_windows() == "10.0.0.1"

    @patch("subprocess.run")
    def test_ipconfig_multiple_gateways_returns_first(self, mock_run, *_):
        """多个适配器各有网关时，返回第一个非 0.0.0.0 的网关。"""
        ps_result = _make_subprocess_result("")
        ps_result.returncode = 1
        ipconfig_output = (
            b"   Default Gateway . . . . . . . . . : 192.168.1.1\r\n"
            b"   Default Gateway . . . . . . . . . : 10.0.0.1\r\n"
        )
        ipconfig_result = _make_subprocess_result(ipconfig_output)
        mock_run.side_effect = [ps_result, ipconfig_result]
        assert nd._detect_gateway_windows() == "192.168.1.1"

    @patch("subprocess.run")
    def test_ipconfig_no_default_gateway(self, mock_run, *_):
        """ipconfig 输出中没有默认网关时返回 None。"""
        ps_result = _make_subprocess_result("")
        ps_result.returncode = 1
        ipconfig_output = (
            b"Ethernet adapter Ethernet:\r\n"
            b"\r\n"
            b"   IPv4 Address. . . . . . . . . . . : 192.168.1.100\r\n"
        )
        ipconfig_result = _make_subprocess_result(ipconfig_output)
        mock_run.side_effect = [ps_result, ipconfig_result]
        assert nd._detect_gateway_windows() is None


# ══════════════════════════════════════════════════════════════
#  Windows SSID 检测
# ══════════════════════════════════════════════════════════════


@patch.object(nd, "is_linux", return_value=False)
@patch.object(nd, "is_macos", return_value=False)
@patch.object(nd, "is_windows", return_value=True)
class TestDetectSsidWindows:
    """测试 _detect_ssid_windows 的 netsh 输出解析。"""

    @patch("subprocess.run")
    def test_utf8_ssid(self, mock_run, *_):
        """ASCII SSID 正常解析。"""
        mock_run.return_value = _make_subprocess_result(
            b"There is 1 interface on the system:\r\n"
            b"\r\n"
            b"    Name                   : Wi-Fi\r\n"
            b"    Description            : Intel Wi-Fi 6 AX201\r\n"
            b"    SSID                   : Campus-WiFi\r\n"
            b"    State                  : connected\r\n"
        )
        assert nd._detect_ssid_windows() == "Campus-WiFi"

    @patch("subprocess.run")
    def test_no_ssid_line(self, mock_run, *_):
        """netsh 输出中无 SSID 行时返回 None。"""
        mock_run.return_value = _make_subprocess_result(
            b"There is 1 interface on the system:\r\n"
            b"\r\n"
            b"    Name                   : Wi-Fi\r\n"
            b"    State                  : disconnected\r\n"
        )
        assert nd._detect_ssid_windows() is None

    @patch("subprocess.run")
    def test_ssid_with_spaces(self, mock_run, *_):
        """SSID 含空格时正确解析（strip 去除行首尾空白，SSID 内部空格保留）。"""
        mock_run.return_value = _make_subprocess_result(
            b"    SSID                   : My Home Network\r\n"
        )
        assert nd._detect_ssid_windows() == "My Home Network"


# ══════════════════════════════════════════════════════════════
#  Linux 网关检测
# ══════════════════════════════════════════════════════════════


@patch.object(nd, "is_linux", return_value=True)
@patch.object(nd, "is_macos", return_value=False)
@patch.object(nd, "is_windows", return_value=False)
class TestDetectGatewayLinux:
    """测试 _detect_gateway_linux 的 /proc/net/route 解析。"""

    @patch(
        "builtins.open",
        mock_open(
            read_data=(
                "Iface\tDestination\tGateway\tFlags\tRefCnt\tUse\tMetric\tMask\tMTU\tWindow\tIRTT\n"
                "eth0\t00000000\t0100A8C0\t0003\t0\t0\t100\t00000000\t0\t0\t0\n"
                "eth0\t0000A8C0\t00000000\t0001\t0\t0\t100\t00FFFFFF\t0\t0\t0\n"
            )
        ),
    )
    def test_standard_route(self, *_):
        """标准 /proc/net/route 格式，网关 192.168.0.1（C0A80001 反转）。"""
        assert nd._detect_gateway_linux() == "192.168.0.1"

    @patch(
        "builtins.open",
        mock_open(
            read_data=(
                "Iface\tDestination\tGateway\tFlags\n"
                "wlan0\t00000000\t0101A8C0\t0003\n"
            )
        ),
    )
    def test_wifi_interface(self, *_):
        """wlan0 接口的网关解析。"""
        assert nd._detect_gateway_linux() == "192.168.1.1"

    @patch(
        "builtins.open",
        mock_open(
            read_data=(
                "Iface\tDestination\tGateway\tFlags\n"
                "eth0\t0000A8C0\t00000000\t0001\n"
            )
        ),
    )
    def test_no_default_route(self, *_):
        """路由表中无默认路由（Destination 不是 00000000）时返回 None。"""
        assert nd._detect_gateway_linux() is None

    @patch("builtins.open", side_effect=PermissionError("Permission denied"))
    def test_permission_error(self, *_):
        """/proc/net/route 读取权限不足时返回 None。"""
        assert nd._detect_gateway_linux() is None


# ══════════════════════════════════════════════════════════════
#  Linux SSID 检测
# ══════════════════════════════════════════════════════════════


@patch.object(nd, "is_linux", return_value=True)
@patch.object(nd, "is_macos", return_value=False)
@patch.object(nd, "is_windows", return_value=False)
class TestDetectSsidLinux:
    """测试 _detect_ssid_linux 的 iwgetid / nmcli 解析。"""

    @patch("subprocess.run")
    def test_iwgetid_success(self, mock_run, *_):
        """iwgetid -r 直接返回 SSID。"""
        mock_run.return_value = _make_subprocess_result("Campus-WiFi\n")
        assert nd._detect_ssid_linux() == "Campus-WiFi"

    @patch("subprocess.run")
    def test_nmcli_fallback(self, mock_run, *_):
        """iwgetid 不可用时回退到 nmcli 解析。"""
        # nmcli -t -f active,ssid dev wifi 仅输出 active 和 ssid 两列
        mock_run.side_effect = [
            FileNotFoundError("iwgetid not found"),
            _make_subprocess_result(
                "no:\n"
                "yes:CampusNet\n"
                "no:\n"
            ),
        ]
        assert nd._detect_ssid_linux() == "CampusNet"

    @patch("subprocess.run")
    def test_both_fail_returns_none(self, mock_run, *_):
        """iwgetid 和 nmcli 都失败时返回 None。"""
        mock_run.side_effect = [
            FileNotFoundError("iwgetid not found"),
            FileNotFoundError("nmcli not found"),
        ]
        assert nd._detect_ssid_linux() is None


# ══════════════════════════════════════════════════════════════
#  macOS 网关检测
# ══════════════════════════════════════════════════════════════


@patch.object(nd, "is_linux", return_value=False)
@patch.object(nd, "is_macos", return_value=True)
@patch.object(nd, "is_windows", return_value=False)
class TestDetectGatewayDarwin:
    """测试 _detect_gateway_darwin 的 netstat -nr 解析。"""

    @patch("subprocess.run")
    def test_standard_netstat(self, mock_run, *_):
        """标准 netstat -nr 输出，默认路由 10.0.0.1。"""
        mock_run.return_value = _make_subprocess_result(
            "Routing tables\n"
            "\n"
            "Internet:\n"
            "Destination        Gateway            Flags        Netif Expire\n"
            "default            10.0.0.1           UGScg        en0\n"
            "127.0.0.1          127.0.0.1          UH           lo0\n"
        )
        assert nd._detect_gateway_darwin() == "10.0.0.1"

    @patch("subprocess.run")
    def test_multiple_defaults_returns_first(self, mock_run, *_):
        """多条 default 路由时返回第一条。"""
        mock_run.return_value = _make_subprocess_result(
            "Routing tables\n"
            "\n"
            "default            192.168.1.1        UGScg        en0\n"
            "default            10.0.0.1           UGScI        en1\n"
        )
        assert nd._detect_gateway_darwin() == "192.168.1.1"

    @patch("subprocess.run")
    def test_no_default_route(self, mock_run, *_):
        """netstat 输出中无 default 行时返回 None。"""
        mock_run.return_value = _make_subprocess_result(
            "Routing tables\n"
            "\n"
            "127.0.0.1          127.0.0.1          UH           lo0\n"
        )
        assert nd._detect_gateway_darwin() is None


# ══════════════════════════════════════════════════════════════
#  macOS SSID 检测
# ══════════════════════════════════════════════════════════════


@patch.object(nd, "is_linux", return_value=False)
@patch.object(nd, "is_macos", return_value=True)
@patch.object(nd, "is_windows", return_value=False)
class TestDetectSsidDarwin:
    """测试 _detect_ssid_darwin 的 airport / networksetup 回退逻辑。"""

    @patch("subprocess.run")
    def test_airport_success(self, mock_run, *_):
        """airport -I 直接返回 SSID。"""
        mock_run.return_value = _make_subprocess_result(
            "     agrCtlRSSI: -50\n"
            "     agrExtRSSI: 0\n"
            "    agrCtlNoise: -90\n"
            "    BSSID: 0:11:22:33:44:55\n"
            "     SSID: Campus-WiFi\n"
        )
        assert nd._detect_ssid_darwin() == "Campus-WiFi"

    @patch("subprocess.run")
    def test_airport_not_found_networksetup_fallback(self, mock_run, *_):
        """airport 不可用时回退到 networksetup。"""
        hardware_ports = (
            "Hardware Port: Wi-Fi\n"
            "Device: en0\n"
            "Ethernet Address: aa:bb:cc:dd:ee:ff\n"
            "\n"
            "Hardware Port: Bluetooth PAN\n"
            "Device: en1\n"
            "Ethernet Address: aa:bb:cc:dd:ee:ff\n"
        )
        mock_run.side_effect = [
            FileNotFoundError("airport not found"),
            _make_subprocess_result(hardware_ports),
            _make_subprocess_result("Current Wi-Fi Network: CampusNet\n"),
        ]
        assert nd._detect_ssid_darwin() == "CampusNet"

    @patch("subprocess.run")
    def test_not_associated_returns_none(self, mock_run, *_):
        """networksetup 输出 'not associated' 时返回 None。"""
        hardware_ports = "Hardware Port: Wi-Fi\nDevice: en0\n"
        mock_run.side_effect = [
            FileNotFoundError("airport not found"),
            _make_subprocess_result(hardware_ports),
            _make_subprocess_result("You are not associated with an AirPort network.\n"),
        ]
        assert nd._detect_ssid_darwin() is None
