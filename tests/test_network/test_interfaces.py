"""InterfaceInfo 数据模型测试。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

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
        ):
            mgr = InterfaceManager()
            result = mgr.list_interfaces()

        assert len(result) == 0

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
