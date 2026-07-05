"""网络模块工具函数。"""


def is_local_address(addr: str) -> bool:
    """判断是否为本地地址（127.0.0.0/8 或 localhost）。"""
    return addr == "localhost" or addr.startswith("127.")


def _is_apipa_address(addr: str) -> bool:
    """判断是否为 APIPA 地址（169.254.0.0/16）。"""
    return addr.startswith("169.254.")


def is_routable_ip(ip: str) -> bool:
    """判断 IP 是否可路由（非回环、非 APIPA）。"""
    return not (is_local_address(ip) or _is_apipa_address(ip))
