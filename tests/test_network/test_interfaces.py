"""InterfaceInfo 数据模型测试。"""

from __future__ import annotations

import pytest


class TestInterfaceInfo:
    """InterfaceInfo 数据模型测试。"""

    def test_frozen_dataclass(self):
        from app.network.interfaces import InterfaceInfo

        info = InterfaceInfo(name="以太网", ip="192.168.1.5", gateway="192.168.1.1", is_up=True)
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

        info = InterfaceInfo(name="WLAN", ip="10.0.0.1", gateway="10.0.0.254", is_up=True)
        with pytest.raises((AttributeError, TypeError)):
            info.extra = "field"  # type: ignore[attr-defined]
