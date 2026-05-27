from __future__ import annotations

import socket
from typing import Iterable, Sequence
from urllib.parse import urlparse

from src.network_probes import (
    is_local_network_connected,
    is_network_available_socket,
    is_network_available_http,
)
from src.utils.logging import get_logger
from src.utils.time_utils import is_in_pause_period

logger = get_logger("network_decision", side="BACKEND")


def is_network_available(
    test_sites: Sequence[tuple[str, int]] | None = None,
    test_urls: Iterable[str] | None = None,
    timeout: float = 1.5,
    enable_tcp: bool = True,
    enable_http: bool = True,
) -> bool:
    # 物理网络预检查：无实际连接时直接跳过，避免徒增功耗
    if not is_local_network_connected():
        logger.warning("物理网络未连接，跳过 TCP/HTTP 检测")
        return False

    # 两种探测都未启用时，视为网络正常（不做额外判断）
    if not enable_tcp and not enable_http:
        logger.info("TCP 和 HTTP 探测均未启用，跳过网络可用性检测")
        return True

    urls_list = list(test_urls or ())
    logger.info(
        "开始网络检测 (TCP=%s, HTTP=%s, TCP目标=%d, HTTP目标=%d)",
        "开" if enable_tcp else "关",
        "开" if enable_http else "关",
        len(test_sites or ()),
        len(urls_list),
    )

    # TCP 探测
    socket_ok = True
    if enable_tcp:
        socket_ok = is_network_available_socket(test_sites=test_sites, timeout=timeout)
        # 两种都启用时，TCP 失败可直接判定断网，跳过 HTTP 省时间
        if enable_http and not socket_ok:
            logger.info("网络检测完成: TCP=断 → 直接判定网络异常，跳过 HTTP")
            return False

    # HTTP 探测
    http_ok = True
    if enable_http:
        http_ok = is_network_available_http(
            test_urls=urls_list,
            timeout=max(timeout, 2.0),
            # 两个都启用时，HTTP 不跟重定向（portal 302 = 未认证 = 失败）
            # 只启用 HTTP 时，跟重定向（允许 portal 重定向后返回 200）
            follow_redirects=not enable_tcp,
        )

    # 两种都启用 → 必须都通过（TCP 失败已提前返回）；只启用一种 → 那种通过即可
    if enable_tcp and enable_http:
        result = http_ok  # TCP 已通过才能到这里
    elif enable_tcp:
        result = socket_ok
    else:
        result = http_ok

    logger.info(
        "网络检测完成: TCP=%s HTTP=%s → %s",
        "通" if socket_ok else ("关" if not enable_tcp else "断"),
        "通" if http_ok else ("关" if not enable_http else "断"),
        "网络正常" if result else "网络异常",
    )
    return result


def is_auth_url_reachable(auth_url: str) -> bool:
    """检查认证地址的 TCP 可达性。

    返回 False 时表示认证地址不可达，应跳过登录尝试。
    无认证地址配置时返回 True（兼容模式）。
    """
    if not auth_url:
        return True

    try:
        parsed = urlparse(auth_url)
        host = parsed.hostname
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        if not host:
            return True
        with socket.create_connection((host, port), timeout=3):
            pass
        return True
    except Exception:
        return False


def should_attempt_login(config: dict) -> tuple[bool, str]:
    """编排完整的登录前检查流程。

    返回 (should_login, reason) 元组：
        (False, "pause_period")          — 当前处于暂停时段
        (False, "network_disconnected")  — 物理网络未连接
        (False, "auth_url_unreachable")  — 认证地址不可达
        (False, "network_ok")            — 网络正常，无需登录
        (True, "")                       — 网络异常，可以尝试登录
    """
    # 1. 暂停时段检查
    pause_config = config.get("pause_login", {})
    if is_in_pause_period(pause_config):
        logger.info("暂停时段，跳过登录")
        return (False, "pause_period")

    # 2. 物理网络检查
    if not is_local_network_connected():
        logger.warning("物理网络未连接，跳过登录")
        return (False, "network_disconnected")

    # 3. 认证地址可达性检查（可配置关闭）
    monitor_config = config.get("monitor", {})
    check_auth_url = monitor_config.get("check_auth_url", True)
    auth_url = config.get("auth_url", "")
    if check_auth_url and not is_auth_url_reachable(auth_url):
        logger.warning("认证地址不可达，跳过登录")
        return (False, "auth_url_unreachable")

    # 4. 网络可用性检查（根据配置选择探测方式）
    enable_tcp = monitor_config.get("enable_tcp_check", True)
    enable_http = monitor_config.get("enable_http_check", True)
    test_sites = monitor_config.get("ping_targets", None)
    # ping_targets 是 list[str]，需要转为 list[tuple[str, int]]
    if test_sites and isinstance(test_sites[0], str):
        from src.utils.network_helpers import parse_host_port
        test_sites = parse_host_port(test_sites)
    test_urls = monitor_config.get("test_urls", None)

    if is_network_available(
        test_sites=test_sites,
        test_urls=test_urls,
        timeout=monitor_config.get("network_check_timeout", 1.5),
        enable_tcp=enable_tcp,
        enable_http=enable_http,
    ):
        logger.info("网络正常，无需登录")
        return (False, "network_ok")

    # 5. 网络异常，可以尝试登录
    logger.info("网络异常，准备登录")
    return (True, "")


def check_campus_network_status() -> str:
    logger.info("正在检测校园网状态...")

    if not is_local_network_connected():
        return "未检测到本地网络连接（未获取到有效IP）"

    if is_network_available():
        return "已连接校园网并可访问互联网"

    return "已连接校园网，但无法访问互联网，需要认证"
