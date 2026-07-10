"""跨平台 socket 绑定到指定网络接口。

Windows 使用 IP_UNICAST_IF，Linux 使用 SO_BINDTODEVICE，macOS 使用 IP_BOUND_IF。
绑定接口索引而非 source IP，确保出站流量真正走指定接口（解决 Windows weak host model
下 source IP 绑定不控制出口路由的问题）。

Linux 下 SO_BINDTODEVICE 需要 CAP_NET_RAW，失败时降级为 source IP 绑定
（Linux strong host model 下 source IP 绑定有效）。
"""

from __future__ import annotations

import platform
import socket
import struct

from app.utils.logging import get_logger

logger = get_logger("interface_bind", source="backend")

# Windows socket 选项常量（Python 标准库在 Windows 上未定义）
_IP_UNICAST_IF = 31  # IPPROTO_IP 级别，强制出站走指定接口索引

# Linux socket 选项常量
_SO_BINDTODEVICE = 25  # SOL_SOCKET 级别

# macOS socket 选项常量
_IP_BOUND_IF = 25  # IPPROTO_IP 级别

# Windows 接口索引遍历上限（足够覆盖所有物理/虚拟网卡）
_MAX_INTERFACE_INDEX = 200


def get_interface_index(if_name: str) -> int | None:
    """获取网卡接口索引，失败返回 None。

    Windows 上 socket.if_nametoindex 对中文/带空格的网卡名可能失败，
    需通过遍历索引 + UDP connect 反查 local IP 匹配。
    """
    # 优先用标准库（Linux/macOS 可靠，部分 Windows 网卡名也可用）
    try:
        return socket.if_nametoindex(if_name)
    except (OSError, ValueError):
        pass

    # Windows fallback：遍历索引，用 IP_UNICAST_IF 绑定后 UDP connect
    # 触发选路，getsockname 拿 local IP，再和 psutil 的网卡 IP 匹配
    if platform.system() != "Windows":
        return None

    import psutil

    # 目标网卡的 IPv4
    target_ip = None
    for name, addrs in psutil.net_if_addrs().items():
        if name == if_name:
            for addr in addrs:
                if addr.family == socket.AF_INET:
                    target_ip = addr.address
                    break
            break
    if not target_ip:
        return None

    # 遍历接口索引，找 local IP 匹配的
    for if_index in range(1, _MAX_INTERFACE_INDEX):
        try:
            socket.if_indextoname(if_index)
        except OSError:
            continue
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.IPPROTO_IP, _IP_UNICAST_IF, struct.pack("!I", if_index))
            # UDP connect 不发包，只触发内核选路
            sock.connect(("8.8.8.8", 53))
            local_ip = sock.getsockname()[0]
            sock.close()
            if local_ip == target_ip:
                return if_index
        except OSError:
            continue

    return None


def bind_socket_to_interface(
    sock: socket.socket,
    if_name: str,
    fallback_source_ip: str | None = None,
) -> str:
    """将 socket 绑定到指定网络接口（connect 前调用）。

    Args:
        sock: 待绑定的 socket（未 connect）
        if_name: 网卡名称
        fallback_source_ip: Linux 权限不足时降级绑定的源 IP

    Returns:
        实际生效的绑定方式:
        - "interface_index": 接口索引绑定（最优）
        - "source_ip_fallback": Linux 降级为源 IP 绑定
        - "none": 未绑定（接口解析失败等）

    Raises:
        PermissionError: Linux 无权限且无 fallback_ip
        OSError: 绑定失败
    """
    if not if_name:
        return "none"

    system = platform.system()

    if system == "Windows":
        if_index = get_interface_index(if_name)
        if if_index is None:
            logger.warning("Windows 接口索引解析失败: {}", if_name)
            return "none"
        # Windows 要求 interface index 按网络字节序（大端）打包成 4 字节
        # 用主机字节序在小端机器上会绑错接口或失败
        sock.setsockopt(socket.IPPROTO_IP, _IP_UNICAST_IF, struct.pack("!I", if_index))
        return "interface_index"

    if system == "Linux":
        try:
            # SO_BINDTODEVICE 接受接口名（null 结尾字符串）
            sock.setsockopt(
                socket.SOL_SOCKET, _SO_BINDTODEVICE, if_name.encode() + b"\0"
            )
            return "interface_index"
        except PermissionError:
            if not fallback_source_ip:
                raise
            # Linux strong host model 下 source IP 绑定有效，非妥协方案
            sock.bind((fallback_source_ip, 0))
            logger.info(
                "Linux 无 CAP_NET_RAW，降级为 source IP 绑定: {}",
                fallback_source_ip,
            )
            return "source_ip_fallback"

    if system == "Darwin":
        if_index = get_interface_index(if_name)
        if if_index is None:
            logger.warning("macOS 接口索引解析失败: {}", if_name)
            return "none"
        sock.setsockopt(socket.IPPROTO_IP, _IP_BOUND_IF, struct.pack("!I", if_index))
        return "interface_index"

    logger.warning("不支持的平台: {}", system)
    return "none"
