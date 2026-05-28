from __future__ import annotations

import socket
from typing import Iterable, Sequence
from urllib.parse import urlparse

from src.network_probes import (
    is_local_network_connected,
    is_network_available_socket,
    is_network_available_http,
    is_network_available_portal,
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
    portal_checks: Sequence[tuple[str, str]] | None = None,
    skip_local_check: bool = False,
) -> bool:
    # 物理网络预检查：无实际连接时直接跳过，避免徒增功耗
    if not skip_local_check and not is_local_network_connected():
        logger.warning("物理网络未连接，跳过 TCP/HTTP 检测")
        return False

    enable_portal = bool(portal_checks)

    # 所有检测都未启用时，视为网络正常（不做额外判断）
    if not enable_tcp and not enable_http and not enable_portal:
        logger.warning("所有网络检测均未启用（TCP/HTTP/Captive Portal），请在设置中启用至少一种检测方式")
        return True

    urls_list = list(test_urls or ())
    logger.info(
        "开始网络检测 (TCP=%s, HTTP=%s, Portal=%s, TCP目标=%d, HTTP目标=%d, Portal目标=%d)",
        "开" if enable_tcp else "关",
        "开" if enable_http else "关",
        "开" if enable_portal else "关",
        len(test_sites or ()),
        len(urls_list),
        len(portal_checks or ()),
    )

    # 所有启用的检测并发执行，降低总检测延时
    from concurrent.futures import ThreadPoolExecutor, as_completed

    socket_ok = http_ok = portal_ok = True

    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {}
        if enable_tcp:
            futures[pool.submit(
                is_network_available_socket, test_sites=test_sites, timeout=timeout
            )] = "tcp"
        if enable_http:
            futures[pool.submit(
                is_network_available_http,
                test_urls=urls_list,
                timeout=max(timeout, 2.0),
                follow_redirects=not enable_tcp,
            )] = "http"
        if enable_portal:
            futures[pool.submit(
                is_network_available_portal,
                portal_checks=portal_checks,
                timeout=max(timeout, 3.0),
            )] = "portal"

        for future in as_completed(futures):
            kind = futures[future]
            try:
                ok = future.result()
            except Exception as exc:
                logger.debug("检测 %s 异常: %s", kind, exc)
                ok = False
            if kind == "tcp":
                socket_ok = ok
            elif kind == "http":
                http_ok = ok
            elif kind == "portal":
                portal_ok = ok

    # 所有启用的检测必须都通过才判定网络正常
    result = (
        (socket_ok or not enable_tcp)
        and (http_ok or not enable_http)
        and (portal_ok or not enable_portal)
    )

    logger.info(
        "网络检测完成: TCP=%s HTTP=%s Portal=%s → %s",
        "通" if socket_ok else ("关" if not enable_tcp else "断"),
        "通" if http_ok else ("关" if not enable_http else "断"),
        "通" if portal_ok else ("关" if not enable_portal else "断"),
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
    except Exception as exc:
        logger.debug("认证地址不可达 %s: %s", auth_url, exc)
        return False


def should_attempt_login(config: dict) -> tuple[bool, str]:
    """判断网络是否异常、是否需要尝试登录。

    仅检查网络连通性，不检查认证地址可达性（认证地址检查在登录前进行）。

    返回 (should_login, reason) 元组：
        (False, "pause_period")          — 当前处于暂停时段
        (False, "network_disconnected")  — 物理网络未连接
        (False, "network_ok")            — 网络正常，无需登录
        (True, "")                       — 网络异常，可以尝试登录
    """
    # 1. 暂停时段检查
    pause_config = config.get("pause_login", {})
    if is_in_pause_period(pause_config):
        logger.info("暂停时段，跳过登录 (配置: %s)", pause_config)
        return (False, "pause_period")

    # 2. 物理网络检查
    if not is_local_network_connected():
        logger.warning("物理网络未连接，跳过登录")
        return (False, "network_disconnected")

    # 3. 网络可用性检查（根据配置选择检测方式）
    monitor_config = config.get("monitor", {})
    enable_tcp = monitor_config.get("enable_tcp_check", True)
    enable_http = monitor_config.get("enable_http_check", True)
    test_sites = monitor_config.get("ping_targets", None)
    # ping_targets 是 list[str]，需要转为 list[tuple[str, int]]
    if test_sites and isinstance(test_sites[0], str):
        from src.utils.network_helpers import parse_host_port
        try:
            test_sites = parse_host_port(test_sites)
        except ValueError:
            logger.warning("ping_targets 配置格式错误，跳过 TCP 检测")
            test_sites = None
    test_urls = monitor_config.get("test_urls", None)

    if is_network_available(
        test_sites=test_sites,
        test_urls=test_urls,
        timeout=monitor_config.get("network_check_timeout", 1.5),
        enable_tcp=enable_tcp,
        enable_http=enable_http,
        portal_checks=monitor_config.get("portal_check_urls", None),
        skip_local_check=True,
    ):
        logger.info("网络正常，无需登录 (TCP=%s, HTTP=%s)", enable_tcp, enable_http)
        return (False, "network_ok")

    # 4. 网络异常，可以尝试登录
    logger.info("网络异常，准备登录")
    return (True, "")


def check_campus_network_status() -> str:
    logger.info("正在检测校园网状态...")

    if not is_local_network_connected():
        result = "未检测到本地网络连接（未获取到有效IP）"
    elif is_network_available(skip_local_check=True):
        result = "已连接校园网并可访问互联网"
    else:
        result = "已连接校园网，但无法访问互联网，需要认证"

    logger.info("校园网状态: %s", result)
    return result
