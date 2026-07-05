"""InterfaceInfo 数据模型测试。"""

from __future__ import annotations

from unittest.mock import MagicMock, mock_open, patch

import pytest


class TestInterfaceInfo:
    """InterfaceInfo 数据模型测试。"""

    def test_frozen_dataclass(self):
        from app.network.interfaces import InterfaceInfo

        info = InterfaceInfo(
            name="以太网", ip="192.168.1.5", gateway="192.168.1.1", is_up=True
        )
        with pytest.raises(AttributeError):
            info.name = "WLAN"  # type: ignore[misc]

    def test_empty_ip_and_gateway(self):
        from app.network.interfaces import InterfaceInfo

        info = InterfaceInfo(name="eth0", ip="", gateway="", is_up=False)
        assert info.ip == ""
        assert info.gateway == ""
        assert info.is_up is False

    def test_slots(self):
        from app.network.interfaces import InterfaceInfo

        info = InterfaceInfo(
            name="WLAN", ip="10.0.0.1", gateway="10.0.0.254", is_up=True
        )
        with pytest.raises((AttributeError, TypeError)):
            info.extra = "field"  # type: ignore[attr-defined]


class TestInterfaceManager:
    """InterfaceManager 测试。"""

    def test_list_interfaces_filters_virtual(self):
        from app.network.interfaces import InterfaceManager

        mock_stats = {
            "以太网": MagicMock(isup=True, isloopback=False),
            "lo": MagicMock(isup=True, isloopback=True),
            "docker0": MagicMock(isup=True, isloopback=False),
            "veth123": MagicMock(isup=True, isloopback=False),
        }
        mock_addrs = {
            "以太网": [MagicMock(family=2, address="192.168.1.5")],
            "lo": [MagicMock(family=2, address="127.0.0.1")],
            "docker0": [MagicMock(family=2, address="172.17.0.1")],
            "veth123": [MagicMock(family=2, address="10.0.0.1")],
        }
        with (
            patch(
                "app.network.interfaces.psutil.net_if_stats", return_value=mock_stats
            ),
            patch(
                "app.network.interfaces.psutil.net_if_addrs", return_value=mock_addrs
            ),
            patch.object(InterfaceManager, "get_gateways_by_name", return_value={}),
        ):
            mgr = InterfaceManager()
            result = mgr.list_interfaces()

        names = [i.name for i in result]
        assert "以太网" in names
        assert "lo" not in names
        assert "docker0" not in names
        assert "veth123" not in names

    def test_list_interfaces_excludes_no_ipv4(self):
        from app.network.interfaces import InterfaceManager

        mock_stats = {
            "tun0": MagicMock(isup=True, isloopback=False),
        }
        mock_addrs = {
            "tun0": [],  # 无 IPv4
        }
        with (
            patch(
                "app.network.interfaces.psutil.net_if_stats", return_value=mock_stats
            ),
            patch(
                "app.network.interfaces.psutil.net_if_addrs", return_value=mock_addrs
            ),
            patch.object(InterfaceManager, "get_gateways_by_name", return_value={}),
        ):
            mgr = InterfaceManager()
            result = mgr.list_interfaces()

        assert len(result) == 0

    def test_list_interfaces_populates_gateway(self):
        """list_interfaces 应填充 gateway 字段。"""
        from app.network.interfaces import InterfaceManager

        mock_stats = {
            "以太网": MagicMock(isup=True, isloopback=False),
            "WLAN": MagicMock(isup=True, isloopback=False),
        }
        mock_addrs = {
            "以太网": [MagicMock(family=2, address="192.168.1.5")],
            "WLAN": [MagicMock(family=2, address="10.0.0.3")],
        }
        gateways = {"以太网": "192.168.1.1"}
        with (
            patch(
                "app.network.interfaces.psutil.net_if_stats", return_value=mock_stats
            ),
            patch(
                "app.network.interfaces.psutil.net_if_addrs", return_value=mock_addrs
            ),
            patch.object(
                InterfaceManager, "get_gateways_by_name", return_value=gateways
            ),
        ):
            mgr = InterfaceManager()
            result = mgr.list_interfaces()

        by_name = {i.name: i for i in result}
        assert by_name["以太网"].gateway == "192.168.1.1"
        assert by_name["WLAN"].gateway == ""

    def test_resolve_ip_returns_ipv4(self):
        from app.network.interfaces import InterfaceManager

        mock_addrs = {
            "以太网": [
                MagicMock(family=2, address="192.168.1.5"),  # AF_INET
                MagicMock(family=23, address="fe80::1"),  # AF_INET6
            ],
        }
        mock_stats = {
            "以太网": MagicMock(isup=True, isloopback=False),
        }
        with (
            patch(
                "app.network.interfaces.psutil.net_if_addrs", return_value=mock_addrs
            ),
            patch(
                "app.network.interfaces.psutil.net_if_stats", return_value=mock_stats
            ),
        ):
            mgr = InterfaceManager()
            ip = mgr.resolve_ip("以太网")

        assert ip == "192.168.1.5"

    def test_resolve_ip_returns_none_for_missing(self):
        from app.network.interfaces import InterfaceManager

        with (
            patch("app.network.interfaces.psutil.net_if_addrs", return_value={}),
            patch("app.network.interfaces.psutil.net_if_stats", return_value={}),
        ):
            mgr = InterfaceManager()
            assert mgr.resolve_ip("不存在") is None

    def test_resolve_ip_caching_30s_ttl(self):
        from app.network.interfaces import InterfaceManager

        call_count = 0

        def fake_addrs():
            nonlocal call_count
            call_count += 1
            return {"以太网": [MagicMock(family=2, address="192.168.1.5")]}

        mock_stats = {"以太网": MagicMock(isup=True, isloopback=False)}
        with (
            patch("app.network.interfaces.psutil.net_if_addrs", side_effect=fake_addrs),
            patch(
                "app.network.interfaces.psutil.net_if_stats", return_value=mock_stats
            ),
            patch("app.network.interfaces.time.monotonic", side_effect=[0, 0, 10, 31]),
        ):
            mgr = InterfaceManager()
            mgr.resolve_ip("以太网")  # t=0, cache miss
            mgr.resolve_ip("以太网")  # t=0, cache hit
            mgr.resolve_ip("以太网")  # t=10, cache hit
            mgr.resolve_ip("以太网")  # t=31, cache expired

        assert call_count == 2  # 首次 + 过期后

    def test_is_interface_up(self):
        from app.network.interfaces import InterfaceManager

        mock_stats = {
            "以太网": MagicMock(isup=True, isloopback=False),
            "WLAN": MagicMock(isup=False, isloopback=False),
        }
        with patch(
            "app.network.interfaces.psutil.net_if_stats", return_value=mock_stats
        ):
            mgr = InterfaceManager()
            assert mgr.is_interface_up("以太网") is True
            assert mgr.is_interface_up("WLAN") is False
            assert mgr.is_interface_up("不存在") is False


class TestInterfaceManagerGateway:
    """网关解析测试。"""

    def test_build_ip_to_name_map(self):
        from app.network.interfaces import InterfaceManager

        mock_addrs = {
            "以太网": [MagicMock(family=2, address="192.168.1.5")],
            "WLAN": [MagicMock(family=2, address="10.0.0.3")],
        }
        with patch(
            "app.network.interfaces.psutil.net_if_addrs", return_value=mock_addrs
        ):
            mgr = InterfaceManager()
            mapping = mgr._build_ip_to_name_map()

        assert mapping == {"192.168.1.5": "以太网", "10.0.0.3": "WLAN"}

    def test_gateways_linux(self):
        """Linux: 从 /proc/net/route 解析所有默认路由。"""
        from app.network.interfaces import InterfaceManager

        proc_content = (
            "Iface\tDestination\tGateway\tFlags\tRefCnt\tUse\tMetric\tMask\n"
            "eth0\t00000000\t0101A8C0\t0003\t0\t0\t100\t00000000\n"
            "wlan0\t00000000\tFE00A8C0\t0003\t0\t0\t600\t00000000\n"
        )
        ip_map = {"192.168.1.5": "eth0", "192.168.0.3": "wlan0"}
        mgr = InterfaceManager()

        with patch("builtins.open", mock_open(read_data=proc_content)):
            result = mgr._gateways_linux(ip_map)

        # 0101A8C0 → 192.168.1.1 (little-endian hex)
        assert result.get("eth0") == "192.168.1.1"
        # FE00A8C0 → 192.168.0.254
        assert result.get("wlan0") == "192.168.0.254"

    def test_gateways_linux_skips_zero_gateway(self):
        """Linux: 网关为 0.0.0.0 的路由应被跳过。"""
        from app.network.interfaces import InterfaceManager

        proc_content = (
            "Iface\tDestination\tGateway\tFlags\tRefCnt\tUse\tMetric\tMask\n"
            "eth0\t00000000\t00000000\t0003\t0\t0\t100\t00000000\n"
        )
        mgr = InterfaceManager()

        with patch("builtins.open", mock_open(read_data=proc_content)):
            result = mgr._gateways_linux({})

        assert result == {}

    def test_gateways_linux_io_error(self):
        """Linux: /proc/net/route 不可读时返回空字典。"""
        from app.network.interfaces import InterfaceManager

        mgr = InterfaceManager()

        with patch("builtins.open", side_effect=OSError("permission denied")):
            result = mgr._gateways_linux({})

        assert result == {}

    def test_gateways_windows(self):
        """Windows: 通过 route print + IP 映射获取网关。"""
        from app.network.interfaces import InterfaceManager

        route_output = (
            "Network Destination        Netmask          Gateway       Interface  Metric\n"
            "          0.0.0.0          0.0.0.0      192.168.1.1     192.168.1.5     25\n"
            "          0.0.0.0          0.0.0.0      10.0.0.254      10.0.0.3      30\n"
        )
        ip_map = {"192.168.1.5": "以太网", "10.0.0.3": "WLAN"}
        mock_result = MagicMock(returncode=0, stdout=route_output)
        mgr = InterfaceManager()

        with patch("app.network.interfaces.subprocess.run", return_value=mock_result):
            result = mgr._gateways_windows(ip_map)

        assert result.get("以太网") == "192.168.1.1"
        assert result.get("WLAN") == "10.0.0.254"

    def test_gateways_windows_no_match(self):
        """Windows: 接口 IP 不在映射中的路由应被跳过。"""
        from app.network.interfaces import InterfaceManager

        route_output = (
            "Network Destination        Netmask          Gateway       Interface  Metric\n"
            "          0.0.0.0          0.0.0.0      192.168.1.1     192.168.1.99     25\n"
        )
        ip_map = {"10.0.0.3": "WLAN"}  # 192.168.1.99 不在映射中
        mock_result = MagicMock(returncode=0, stdout=route_output)
        mgr = InterfaceManager()

        with patch("app.network.interfaces.subprocess.run", return_value=mock_result):
            result = mgr._gateways_windows(ip_map)

        assert result == {}

    def test_gateways_windows_route_fails(self):
        """Windows: route print 失败时返回空字典。"""
        from app.network.interfaces import InterfaceManager

        mock_result = MagicMock(returncode=1, stdout="")
        mgr = InterfaceManager()

        with patch("app.network.interfaces.subprocess.run", return_value=mock_result):
            result = mgr._gateways_windows({})

        assert result == {}

    def test_gateways_macos(self):
        """macOS: 从 netstat -rn 输出解析默认路由。"""
        from app.network.interfaces import InterfaceManager

        netstat_output = """Routing tables:

Internet:
Destination        Gateway            Flags           Netif Expire
default            192.168.1.1        UGScg          en0
default            10.0.0.254         UGScIg         en1
127.0.0.1          127.0.0.1          UH             lo0

Internet6:
"""
        mock_result = MagicMock(returncode=0, stdout=netstat_output)
        mgr = InterfaceManager()

        with patch("app.network.interfaces.subprocess.run", return_value=mock_result):
            result = mgr._gateways_macos({})

        assert result.get("en0") == "192.168.1.1"
        assert result.get("en1") == "10.0.0.254"
        assert "lo0" not in result  # 127.0.0.1 不是有效网关

    def test_gateways_macos_netstat_fails(self):
        """macOS: netstat 失败时返回空字典。"""
        from app.network.interfaces import InterfaceManager

        mock_result = MagicMock(returncode=1, stdout="")
        mgr = InterfaceManager()

        with patch("app.network.interfaces.subprocess.run", return_value=mock_result):
            result = mgr._gateways_macos({})

        assert result == {}

    def test_get_gateways_by_name_dispatches_by_platform(self):
        """get_gateways_by_name 根据平台分发到对应方法。"""
        from app.network.interfaces import InterfaceManager

        mgr = InterfaceManager()
        expected = {"eth0": "192.168.1.1"}

        with (
            patch("app.network.interfaces.platform.system", return_value="Linux"),
            patch.object(mgr, "_gateways_linux", return_value=expected) as mock_linux,
            patch("app.network.interfaces.psutil.net_if_addrs", return_value={}),
        ):
            result = mgr.get_gateways_by_name()

        assert result == expected
        mock_linux.assert_called_once()
