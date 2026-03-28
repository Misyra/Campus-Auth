from __future__ import annotations

import logging
import socket
import sys
from typing import Iterable, Sequence

import httpx

logger = logging.getLogger("network_test")


def is_local_network_connected() -> bool:
    try:
        hostname = socket.gethostname()
        ip_list = socket.gethostbyname_ex(hostname)[2]
        non_loopback = [ip for ip in ip_list if not ip.startswith("127.")]
        if non_loopback:
            logger.debug(f"本地IP: {non_loopback}")
        else:
            logger.debug("未检测到有效本地IP")
        return len(non_loopback) > 0
    except Exception as exc:
        logger.debug(f"获取本地IP失败: {exc}")
        return False


def is_network_available_socket(
    test_sites: Sequence[tuple[str, int]] | None = None,
    timeout: float = 1.5,
) -> bool:
    targets = test_sites or (("www.baidu.com", 443), ("1.1.1.1", 53))
    for host, port in targets:
        try:
            with socket.create_connection((host, port), timeout=timeout):
                logger.debug(f"TCP连接成功: {host}:{port}")
                return True
        except Exception as exc:
            logger.debug(f"TCP连接失败: {host}:{port} - {exc}")
    return False


def is_network_available_http(
    test_urls: Iterable[str] | None = None,
    timeout: float = 2.0,
) -> bool:
    urls = list(test_urls or ("https://www.baidu.com", "https://www.qq.com"))
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            for url in urls:
                try:
                    resp = client.get(url)
                    if resp.status_code < 500:
                        logger.debug(f"HTTP成功: {url} [{resp.status_code}]")
                        return True
                    logger.debug(f"HTTP失败: {url} [{resp.status_code}]")
                except Exception as exc:
                    logger.debug(f"HTTP异常: {url} - {exc}")
    except Exception as exc:
        logger.debug(f"HTTP客户端异常: {exc}")
    return False


def is_network_available(
    test_sites: Sequence[tuple[str, int]] | None = None,
    test_urls: Iterable[str] | None = None,
    timeout: float = 1.5,
    require_both: bool = False,
) -> bool:
    socket_ok = is_network_available_socket(test_sites=test_sites, timeout=timeout)
    http_ok = is_network_available_http(test_urls=test_urls, timeout=max(timeout, 2.0))
    return (socket_ok and http_ok) if require_both else (socket_ok or http_ok)


def check_campus_network_status() -> str:
    logger.info("正在检测网络状态...")

    if not is_local_network_connected():
        return "未连接到校园网（未获取到有效IP）"

    if is_network_available():
        return "已连接校园网并可访问互联网"

    return "已连接校园网，但无法访问互联网，需要认证"


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG if "-v" in sys.argv else logging.INFO)
    print(check_campus_network_status())
