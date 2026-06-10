from __future__ import annotations

import atexit
import socket
import ssl
import threading
import time
from collections.abc import Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed

import httpx
import psutil

from app.utils.logging import get_logger

logger = get_logger("network_probes", source="network")

executor = ThreadPoolExecutor(max_workers=3)
atexit.register(executor.shutdown, wait=False, cancel_futures=True)
_proxy_lock = threading.Lock()
_block_proxy = True  # 默认屏蔽系统代理，避免代理影响网络检测


def set_block_proxy(enabled: bool) -> None:
    """设置是否屏蔽系统代理。

    当 enabled=True 时，HTTP 客户端不读取系统代理设置（默认行为）；
    当 enabled=False 时，允许 HTTP 客户端使用系统代理。
    """
    global _block_proxy
    with _proxy_lock:
        _block_proxy = enabled


def is_block_proxy() -> bool:
    """获取当前代理屏蔽设置。"""
    with _proxy_lock:
        return _block_proxy


def is_local_network_connected() -> bool:
    """检查本地网络是否有实际连接（有线或无线）。"""
    try:
        for name, stats in psutil.net_if_stats().items():
            if stats.isup and name.lower() not in ("lo", "loopback"):
                logger.debug("网络接口已连接: {} (speed={}Mbps)", name, stats.speed)
                return True
    except Exception as exc:
        logger.debug("psutil 网络检测失败: {}", exc)

    logger.warning("未检测到本地网络连接")
    return False


def is_network_available_socket(
    test_sites: Sequence[tuple[str, int]] | None = None,
    timeout: float = 1.5,
) -> bool:
    targets = test_sites or (("www.baidu.com", 443), ("1.1.1.1", 53))

    def _connect_one(host: str, port: int) -> tuple[str, bool, str]:
        start = time.perf_counter()
        try:
            with socket.create_connection((host, port), timeout=timeout):
                elapsed = (time.perf_counter() - start) * 1000
                return (f"{host}:{port}", True, f"({elapsed:.0f}ms)")
        except Exception as exc:
            elapsed = (time.perf_counter() - start) * 1000
            return (f"{host}:{port}", False, f"{type(exc).__name__}")

    futures = {executor.submit(_connect_one, h, p): (h, p) for h, p in targets}
    for future in as_completed(futures):
        label, ok, detail = future.result()
        if ok:
            logger.info("TCP 连接成功: {} {}", label, detail)
            return True
        logger.info("TCP 连接失败: {} -- {}", label, detail)
    logger.warning("所有 TCP 目标均不可达 ({} 个)", len(targets))
    return False


def is_network_available_url(
    url_checks: Sequence[tuple[str, str]] | None = None,
    timeout: float = 3.0,
) -> bool:
    """通过网址响应检测 URL 检测网络连通性。

    访问配置的网址响应检测地址，验证响应内容是否包含预期的"正常"标识。
    如果被重定向到登录页面或返回非预期内容，说明需要认证。

    参数:
        url_checks: (URL, 预期内容) 元组列表，为 None 时使用内置默认值
        timeout: 单个请求超时秒数

    返回 True 表示至少有一个检测 URL 返回了预期内容（网络正常）。
    """
    if url_checks is None:
        url_checks = [
            ("http://captive.apple.com/hotspot-detect.html", "Success"),
            (
                "http://www.msftconnecttest.com/connecttest.txt",
                "Microsoft Connect Test",
            ),
            ("http://detectportal.firefox.com/success.txt", "success"),
        ]
    if not url_checks:
        return True

    def _check_url(url: str, expected: str) -> tuple[str, bool, str]:
        start = time.perf_counter()
        try:
            with httpx.Client(
                verify=False, trust_env=not is_block_proxy(), follow_redirects=True
            ) as client:
                resp = client.get(url, timeout=timeout)
            elapsed = (time.perf_counter() - start) * 1000
            body = resp.text.strip()
            if expected in body:
                return (url, True, f"HTTP {resp.status_code} ({elapsed:.0f}ms)")
            return (
                url,
                False,
                f"HTTP {resp.status_code} 内容不匹配 ({elapsed:.0f}ms)",
            )
        except Exception as exc:
            elapsed = (time.perf_counter() - start) * 1000
            return (url, False, f"{type(exc).__name__} ({elapsed:.0f}ms)")

    futures = {
        executor.submit(_check_url, url, exp): url for url, exp in url_checks
    }
    for future in as_completed(futures):
        url, ok, detail = future.result()
        if ok:
            logger.info("网址响应检测成功: {} -> {}", url, detail)
            return True
        logger.info("网址响应检测失败: {} -- {}", url, detail)
    logger.warning("所有网址响应检测均未通过 ({} 个)", len(url_checks))
    return False


def is_network_available_http(
    test_urls: Iterable[str] | None = None,
    timeout: float = 2.0,
    follow_redirects: bool = True,
) -> bool:
    """通过 HTTP(S) 请求检测网络连通性。

    设计说明：故意禁用 SSL 验证（verify=False），因为校园网认证门户
    会用自签名证书拦截 HTTPS 流量。目的是检测连通性，而非验证 TLS 安全性。
    这与 browser.py 中的 ignore_https_errors=True 一致。

    在 follow_redirects=False 模式下，200<=status<300 表示连通正常；
    门户的 302 重定向不算正常（会触发登录）。注意：门户返回 200 且内容为
    登录页面（无重定向）是已知的检测限制。
    """
    urls = list(test_urls or ("https://www.baidu.com", "https://www.qq.com"))
    if len(urls) == 0:
        return False

    def _check_one(url: str) -> tuple[str, bool, str]:
        """在独立线程中检测单个 URL。返回 (url, success, detail)。"""
        start = time.perf_counter()
        try:
            with httpx.Client(verify=False, trust_env=not is_block_proxy()) as client:
                resp = client.get(
                    url, timeout=timeout, follow_redirects=follow_redirects
                )
            elapsed = (time.perf_counter() - start) * 1000
            if 200 <= resp.status_code < 300:
                return (url, True, f"HTTP {resp.status_code} ({elapsed:.0f}ms)")
            return (url, False, f"HTTP {resp.status_code} ({elapsed:.0f}ms)")
        except Exception as exc:
            elapsed = (time.perf_counter() - start) * 1000
            # SSL 证书验证失败（校园网门户 HTTPS 劫持自签名证书）降级为 DEBUG
            if isinstance(exc, ssl.SSLError) or "CERTIFICATE_VERIFY_FAILED" in str(exc):
                logger.debug("SSL 证书验证失败 (预期行为): {} -- {}", url, exc)
            else:
                logger.info("HTTP 请求异常: {} -- {}", url, exc)
            return (url, False, f"{type(exc).__name__}: {exc}")

    futures = {executor.submit(_check_one, url): url for url in urls}
    for future in as_completed(futures):
        url, ok, detail = future.result()
        if ok:
            logger.info("HTTP 请求成功: {} -> {}", url, detail)
            return True
        logger.info("HTTP 请求失败: {} -- {}", url, detail)
    logger.warning("所有 HTTP 目标均不可达 ({} 个)", len(urls))
    return False
