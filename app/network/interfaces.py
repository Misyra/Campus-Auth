"""网络接口信息数据模型与管理器。"""

from __future__ import annotations

import platform
import socket
import subprocess
import time
from dataclasses import dataclass

import psutil

from app.network.detect import (
    _parse_darwin_netstat_routes,
    _parse_linux_route_entry,
    _parse_windows_all_routes,
)
from app.network.probes import _is_virtual_nic
from app.network.utils import is_routable_ip
from app.utils.logging import get_logger
from app.utils.platform import CREATE_NO_WINDOW_FLAG

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
        # Windows 的 snicstats 没有 isloopback 属性，通过名称判断
        if name.lower().startswith("lo"):
            return False
        if _is_virtual_nic(name):
            return False
        # 无 IPv4 的排除
        return bool(self._get_ipv4(name))

    def _build_ip_to_name_map(self) -> dict[str, str]:
        """构建 IP → 网卡名映射。"""
        mapping: dict[str, str] = {}
        for name, addrs in psutil.net_if_addrs().items():
            for addr in addrs:
                if addr.family == _AF_INET:
                    mapping[addr.address] = name
        return mapping

    def get_gateways_by_name(self) -> dict[str, str]:
        """返回 {网卡名: 网关IP} 映射。"""
        ip_to_name = self._build_ip_to_name_map()
        system = platform.system()
        if system == "Windows":
            return self._gateways_windows(ip_to_name)
        if system == "Linux":
            return self._gateways_linux(ip_to_name)
        return self._gateways_macos(ip_to_name)

    def _gateways_windows(self, ip_map: dict[str, str]) -> dict[str, str]:
        """Windows: 通过 route print 获取所有默认路由，按接口 IP 匹配网卡名。"""
        try:
            result = subprocess.run(
                ["route", "print", "0.0.0.0"],
                capture_output=True,
                text=True,
                timeout=5,
                creationflags=CREATE_NO_WINDOW_FLAG,
            )
            if result.returncode != 0:
                return {}
            routes = _parse_windows_all_routes(result.stdout)
            gateways: dict[str, str] = {}
            for gw, iface_ip in routes:
                name = ip_map.get(iface_ip)
                if name:
                    gateways[name] = gw
            return gateways
        except Exception as exc:
            logger.debug("Windows 网关解析失败: {}", exc)
            return {}

    def _gateways_linux(self, ip_map: dict[str, str]) -> dict[str, str]:
        """Linux: 解析 /proc/net/route 获取所有默认路由。"""
        try:
            gateways: dict[str, str] = {}
            with open("/proc/net/route") as f:
                for line in f:
                    entry = _parse_linux_route_entry(line)
                    if entry is not None:
                        iface, gw = entry
                        if gw != "0.0.0.0":
                            gateways[iface] = gw
            return gateways
        except Exception as exc:
            logger.debug("Linux 网关解析失败: {}", exc)
            return {}

    def _gateways_macos(self, ip_map: dict[str, str]) -> dict[str, str]:
        """macOS: 解析 netstat -rn 获取所有默认路由。"""
        try:
            result = subprocess.run(
                ["netstat", "-rn"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode != 0:
                return {}
            return _parse_darwin_netstat_routes(result.stdout)
        except Exception as exc:
            logger.debug("macOS 网关解析失败: {}", exc)
            return {}

    def list_interfaces(self) -> list[InterfaceInfo]:
        """枚举物理网卡列表。"""
        gateways = self.get_gateways_by_name()
        result: list[InterfaceInfo] = []
        stats_all = psutil.net_if_stats()
        for name, stats in stats_all.items():
            if self._is_physical(name, stats):
                info = InterfaceInfo(
                    name=name,
                    ip=self._get_ipv4(name),
                    gateway=gateways.get(name, ""),
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

    def is_interface_bindable(self, name: str) -> tuple[bool, str]:
        """判断网卡是否可用于绑定。

        检查项：
        1. 网卡是否存在
        2. 网卡是否 up
        3. IP 是否可路由（非回环、非 APIPA）

        Returns:
            (是否可用, 原因)
        """
        stats = psutil.net_if_stats().get(name)
        if stats is None:
            return False, f"网卡 {name} 不存在"

        if not stats.isup:
            return False, f"网卡 {name} 未连接"

        ip = self._get_ipv4(name)
        if not ip:
            return False, f"网卡 {name} 无 IPv4 地址"

        if not is_routable_ip(ip):
            return False, f"网卡 {name} 的 IP {ip} 不可路由"

        return True, ""
