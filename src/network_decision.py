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
from src.utils.time_utils import TimeUtils

logger = get_logger("network_decision", side="BACKEND")


def is_network_available(
    test_sites: Sequence[tuple[str, int]] | None = None,
    test_urls: Iterable[str] | None = None,
    timeout: float = 1.5,
    require_both: bool = False,
) -> bool:
    # 物理网络预检查：无实际连接时直接跳过，避免徒增功耗
    if not is_local_network_connected():
        logger.warning("物理网络未连接，跳过 TCP/HTTP 检测")
        return False

    urls_list = list(test_urls or ())
    logger.info(
        "开始网络检测 (TCP目标=%d, HTTP目标=%d, require_both=%s)",
        len(test_sites or ()),
        len(urls_list),
        require_both,
    )
    socket_ok = is_network_available_socket(test_sites=test_sites, timeout=timeout)
    if require_both:
        # 严格模式：TCP + HTTP 双重验证
        # TCP 已失败则直接判定断网，跳过 HTTP 省时间
        if not socket_ok:
            logger.info("网络检测完成: TCP=断 → 严格模式直接判定网络异常，跳过 HTTP")
            return False
        # 不跟重定向：portal 重定向到登录页 = 未认证 = 判定失败
        http_ok = is_network_available_http(
            test_urls=urls_list,
            timeout=max(timeout, 2.0),
            follow_redirects=False,
        )
        result = http_ok
    else:
        # TCP 成功即可，跳过 HTTP 检测节省时间
        if socket_ok:
            logger.info("网络检测完成: TCP=通 → 网络正常")
            return True
        http_ok = is_network_available_http(
            test_urls=urls_list, timeout=max(timeout, 2.0)
        )
        result = http_ok
    logger.info(
        "网络检测完成: TCP=%s HTTP=%s → %s",
        "通" if socket_ok else "断",
        "通" if http_ok else "断",
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
        sock = socket.create_connection((host, port), timeout=3)
        sock.close()
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
    if TimeUtils.is_in_pause_period(pause_config):
        logger.info("暂停时段，跳过登录")
        return (False, "pause_period")

    # 2. 物理网络检查
    if not is_local_network_connected():
        logger.warning("物理网络未连接，跳过登录")
        return (False, "network_disconnected")

    # 3. 认证地址可达性检查
    auth_url = config.get("auth_url", "")
    if not is_auth_url_reachable(auth_url):
        logger.warning("认证地址不可达，跳过登录")
        return (False, "auth_url_unreachable")

    # 4. 网络可用性检查
    if is_network_available():
        logger.info("网络正常，无需登录")
        return (False, "network_ok")

    # 5. 网络异常，可以尝试登录
    logger.info("网络异常，准备登录")
    return (True, "")


def check_campus_network_status() -> str:
    logger.info("正在检测校园网状态...")

    if not is_local_network_connected():
        return "未连接到校园网（未获取到有效IP）"

    if is_network_available():
        return "已连接校园网并可访问互联网"

    return "已连接校园网，但无法访问互联网，需要认证"
