from __future__ import annotations

import logging
import socket
import sys
import time
from typing import Iterable, Sequence

import httpx

logger = logging.getLogger("network_test")


def is_local_network_connected() -> bool:
    try:
        hostname = socket.gethostname()
        ip_list = socket.gethostbyname_ex(hostname)[2]
        non_loopback = [ip for ip in ip_list if not ip.startswith("127.")]
        if non_loopback:
            logger.info("本地网络已连接，IP: %s", ", ".join(non_loopback))
        else:
            logger.warning("未检测到有效本地 IP")
        return len(non_loopback) > 0
    except Exception as exc:
        logger.warning("获取本地 IP 失败: %s", exc)
        return False


def is_network_available_socket(
    test_sites: Sequence[tuple[str, int]] | None = None,
    timeout: float = 1.5,
) -> bool:
    targets = test_sites or (("www.baidu.com", 443), ("1.1.1.1", 53))
    for host, port in targets:
        start = time.perf_counter()
        try:
            with socket.create_connection((host, port), timeout=timeout):
                elapsed = (time.perf_counter() - start) * 1000
                logger.info("TCP 连接成功: %s:%s (%.0fms)", host, port, elapsed)
                return True
        except Exception as exc:
            elapsed = (time.perf_counter() - start) * 1000
            logger.info("TCP 连接失败: %s:%s (%.0fms) — %s", host, port, elapsed, exc)
    logger.warning("所有 TCP 目标均不可达 (%d 个)", len(targets))
    return False


def is_network_available_http(
    test_urls: Iterable[str] | None = None,
    timeout: float = 2.0,
) -> bool:
    urls = list(test_urls or ("https://www.baidu.com", "https://www.qq.com"))
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            for url in urls:
                start = time.perf_counter()
                try:
                    resp = client.get(url)
                    elapsed = (time.perf_counter() - start) * 1000
                    if resp.status_code < 500:
                        logger.info("HTTP 请求成功: %s → %s (%.0fms)",
                                    url, resp.status_code, elapsed)
                        return True
                    logger.warning("HTTP 请求失败: %s → %s (%.0fms)",
                                   url, resp.status_code, elapsed)
                except Exception as exc:
                    elapsed = (time.perf_counter() - start) * 1000
                    logger.info("HTTP 请求异常: %s (%.0fms) — %s", url, elapsed, exc)
    except Exception as exc:
        logger.warning("HTTP 客户端初始化失败: %s", exc)
    logger.warning("所有 HTTP 目标均不可达 (%d 个)", len(urls))
    return False


def is_network_available(
    test_sites: Sequence[tuple[str, int]] | None = None,
    test_urls: Iterable[str] | None = None,
    timeout: float = 1.5,
    require_both: bool = False,
) -> bool:
    logger.info("开始网络检测 (TCP目标=%d, HTTP目标=%d, require_both=%s)",
                len(test_sites or ()), len(list(test_urls or ())), require_both)
    socket_ok = is_network_available_socket(test_sites=test_sites, timeout=timeout)
    if require_both:
        # 两者都必须成功，不能短路
        http_ok = is_network_available_http(test_urls=test_urls, timeout=max(timeout, 2.0))
        result = socket_ok and http_ok
    else:
        # TCP 成功即可，跳过 HTTP 检测节省时间
        if socket_ok:
            logger.info("网络检测完成: TCP=通 → 网络正常")
            return True
        http_ok = is_network_available_http(test_urls=test_urls, timeout=max(timeout, 2.0))
        result = http_ok
    logger.info("网络检测完成: TCP=%s HTTP=%s → %s",
                "通" if socket_ok else "断",
                "通" if http_ok else "断",
                "网络正常" if result else "网络异常")
    return result


def check_campus_network_status() -> str:
    logger.info("正在检测校园网状态...")

    if not is_local_network_connected():
        return "未连接到校园网（未获取到有效IP）"

    if is_network_available():
        return "已连接校园网并可访问互联网"

    return "已连接校园网，但无法访问互联网，需要认证"


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG if "-v" in sys.argv else logging.INFO)
    print(check_campus_network_status())
