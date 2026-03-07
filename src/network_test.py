from __future__ import annotations

import socket
import sys
from typing import Iterable, Sequence

import httpx


def log(message: str, verbose: bool = True) -> None:
    if verbose:
        print(message)


def is_local_network_connected(verbose: bool = False) -> bool:
    """检查是否获取到非回环地址。"""
    try:
        hostname = socket.gethostname()
        ip_list = socket.gethostbyname_ex(hostname)[2]
        non_loopback = [ip for ip in ip_list if not ip.startswith("127.")]
        log(f"本地IP地址: {non_loopback}", verbose)
        return len(non_loopback) > 0
    except Exception as exc:
        log(f"获取本地IP失败: {exc}", verbose)
        return False


def is_network_available_socket(
    test_sites: Sequence[tuple[str, int]] | None = None,
    timeout: float = 1.5,
    verbose: bool = False,
) -> bool:
    """通过 TCP 建连检测网络可用性。"""
    targets = test_sites or (("www.baidu.com", 443), ("1.1.1.1", 53))
    for host, port in targets:
        try:
            with socket.create_connection((host, port), timeout=timeout):
                log(f"Socket连接成功: {host}:{port}", verbose)
                return True
        except Exception as exc:
            log(f"Socket连接失败: {host}:{port} ({exc})", verbose)
    return False


def is_network_available_http(
    test_urls: Iterable[str] | None = None,
    timeout: float = 2.0,
    verbose: bool = False,
) -> bool:
    """通过 HTTP 请求检测网络可用性（替代 curl 子进程）。"""
    urls = list(test_urls or ("https://www.baidu.com", "https://www.qq.com"))
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            for url in urls:
                try:
                    resp = client.get(url)
                    if resp.status_code < 500:
                        log(f"HTTP访问成功: {url} [{resp.status_code}]", verbose)
                        return True
                    log(f"HTTP访问失败: {url} [{resp.status_code}]", verbose)
                except Exception as exc:
                    log(f"HTTP访问异常: {url} ({exc})", verbose)
    except Exception as exc:
        log(f"HTTP客户端创建失败: {exc}", verbose)
    return False


def is_network_available(
    test_sites: Sequence[tuple[str, int]] | None = None,
    test_urls: Iterable[str] | None = None,
    timeout: float = 1.5,
    verbose: bool = False,
    require_both: bool = False,
) -> bool:
    """综合网络检测。"""
    socket_ok = is_network_available_socket(test_sites=test_sites, timeout=timeout, verbose=verbose)
    http_ok = is_network_available_http(test_urls=test_urls, timeout=max(timeout, 2.0), verbose=verbose)
    return (socket_ok and http_ok) if require_both else (socket_ok or http_ok)


def check_campus_network_status(verbose: bool = True) -> str:
    log("正在检测网络状态...", verbose)

    if not is_local_network_connected(verbose=verbose):
        return "未连接到校园网（未获取到有效IP）"

    if is_network_available(verbose=verbose):
        return "已连接校园网并可访问互联网"

    return "已连接校园网，但无法访问互联网，需要认证"


if __name__ == "__main__":
    verbose_flag = "-v" in sys.argv or "--verbose" in sys.argv
    print(check_campus_network_status(verbose=verbose_flag))
