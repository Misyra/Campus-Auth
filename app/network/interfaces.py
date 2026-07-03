"""网络接口信息数据模型与管理器。"""

from __future__ import annotations

import socket
import time
from dataclasses import dataclass

import psutil

from app.network.probes import _is_virtual_nic
from app.utils.logging import get_logger

logger = get_logger("interfaces", source="backend")

# psutil 的 AF_INET 在不同平台值不同，用 socket.AF_INET
_AF_INET = socket.AF_INET  # Windows=2, Linux=2, macOS=2

_CACHE_TTL = 30.0  # 秒


@dataclass(frozen=True, slots=True)
class InterfaceInfo:
    """网络接口信息，统一用于 API、探测、代理、UI。"""

    name: str
    ip: str  # IPv4，空串表示无 IPv4
    gateway: str  # 默认网关，空串表示无
    is_up: bool


class InterfaceManager:
    """网卡信息管理入口。整个项目只有此模块调用 psutil 的网卡 API。"""

    def __init__(self) -> None:
        # resolve_ip 专用缓存: name -> (ip, timestamp)
        self._ip_cache: dict[str, tuple[str, float]] = {}

    def _get_ipv4(self, name: str) -> str:
        """获取指定网卡的 IPv4 地址，无则返回空串。"""
        for addr in psutil.net_if_addrs().get(name, []):
            if addr.family == _AF_INET:
                return addr.address
        return ""

    def _is_physical(self, name: str, stats: object) -> bool:
        """判断是否为物理网卡（排除回环、虚拟网卡、无 IPv4 的接口）。"""
        if stats.isloopback:
            return False
        if name.lower().startswith("lo"):
            return False
        if _is_virtual_nic(name):
            return False
        # 无 IPv4 的排除
        return bool(self._get_ipv4(name))

    def list_interfaces(self) -> list[InterfaceInfo]:
        """枚举物理网卡列表。"""
        result: list[InterfaceInfo] = []
        stats_all = psutil.net_if_stats()
        for name, stats in stats_all.items():
            if self._is_physical(name, stats):
                info = InterfaceInfo(
                    name=name,
                    ip=self._get_ipv4(name),
                    gateway="",
                    is_up=stats.isup,
                )
                result.append(info)
        return result

    def resolve_ip(self, name: str) -> str | None:
        """解析网卡 IPv4 地址，30 秒 TTL 缓存。"""
        now = time.monotonic()
        cached = self._ip_cache.get(name)
        if cached:
            ip, ts = cached
            if now - ts < _CACHE_TTL:
                return ip or None

        ip = self._get_ipv4(name)
        self._ip_cache[name] = (ip, now)
        return ip or None

    def is_interface_up(self, name: str) -> bool:
        """检查指定网卡是否 up。"""
        stats = psutil.net_if_stats().get(name)
        return stats is not None and stats.isup
