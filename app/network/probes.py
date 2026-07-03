from __future__ import annotations

import socket
import ssl
import threading
import time
from collections.abc import Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor

import httpx
import psutil

from app.utils.concurrent import race_first_success
from app.utils.logging import get_logger

logger = get_logger("network_probes", source="backend")

executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix="net")
_shutdown_event = threading.Event()

# atexit.register(executor.shutdown, wait=False, cancel_futures=True)  # 改由 container.py 调用 shutdown_probes()
_proxy_lock = threading.Lock()
_block_proxy = True  # 默认屏蔽系统代理，避免代理影响网络检测

# ── httpx 全局单例 ──

_probe_client: httpx.Client | None = None
_probe_lock = threading.Lock()
_probe_block_proxy: bool = True  # 记录创建时的代理状态


def _get_probe_client(block_proxy: bool) -> httpx.Client:
    """获取全局复用的探测 Client，线程安全。代理设置变化时自动重建。"""
    global _probe_client, _probe_block_proxy
    with _probe_lock:
        if (
            _probe_client is not None
            and not _probe_client.is_closed
            and _probe_block_proxy == block_proxy
        ):
            return _probe_client
        if _probe_client is not None and not _probe_client.is_closed:
            _probe_client.close()
        _probe_client = httpx.Client(
            verify=False,
            follow_redirects=True,
            trust_env=not block_proxy,
            limits=httpx.Limits(
                max_connections=4,
                max_keepalive_connections=2,
                keepalive_expiry=30.0,
            ),
        )
        _probe_block_proxy = block_proxy
        return _probe_client


def _close_probe_client() -> None:
    global _probe_client
    with _probe_lock:
        if _probe_client and not _probe_client.is_closed:
            _probe_client.close()
            _probe_client = None


# ── 绑定源 IP 的 httpx Client 池 ──

_bound_clients: dict[str, httpx.Client] = {}
_bound_clients_lock = threading.Lock()
_MAX_BOUND_CLIENTS = 4


def _get_bound_client(source_ip: str, block_proxy: bool) -> httpx.Client:
    """获取绑定指定源 IP 的 httpx Client，按 IP 缓存复用。"""
    with _bound_clients_lock:
        if source_ip in _bound_clients:
            client = _bound_clients[source_ip]
            if not client.is_closed:
                return client
        # 超限关闭最旧的
        while len(_bound_clients) >= _MAX_BOUND_CLIENTS:
            oldest_key = next(iter(_bound_clients))
            _bound_clients.pop(oldest_key).close()

        client = httpx.Client(
            transport=httpx.HTTPTransport(local_address=source_ip),
            verify=False,
            follow_redirects=True,
            trust_env=not block_proxy,
            limits=httpx.Limits(max_connections=4, max_keepalive_connections=2),
        )
        _bound_clients[source_ip] = client
        return client


def close_bound_client(old_ip: str) -> None:
    """IP 变化时关闭旧 Client。"""
    with _bound_clients_lock:
        client = _bound_clients.pop(old_ip, None)
        if client and not client.is_closed:
            client.close()


def _close_all_bound_clients() -> None:
    """关闭时清理所有绑定 Client。"""
    with _bound_clients_lock:
        for client in _bound_clients.values():
            if not client.is_closed:
                client.close()
        _bound_clients.clear()


def shutdown_probes() -> None:
    """关闭探测模块：设置停止标志、关闭 HTTP 客户端、等待 in-flight 请求完成。

    由 ServiceContainer.shutdown() 在应用关闭时调用，
    替代原来的 atexit 注册，确保关闭顺序可控。
    """
    _shutdown_event.set()
    _close_probe_client()
    _close_all_bound_clients()
    executor.shutdown(wait=True, cancel_futures=True)


# atexit.register(_close_probe_client)  # 改由 container.py 调用 shutdown_probes()


def set_block_proxy(enabled: bool) -> None:
    """设置是否屏蔽系统代理。

    当 enabled=True 时，HTTP 客户端不读取系统代理设置（默认行为）；
    当 enabled=False 时，允许 HTTP 客户端使用系统代理。
    """
    global _block_proxy, _probe_client, _probe_block_proxy
    with _proxy_lock:
        _block_proxy = enabled
    # 关闭旧客户端，下次探测时自动重建
    with _probe_lock:
        if _probe_client is not None and not _probe_client.is_closed:
            _probe_client.close()
        _probe_client = None


def is_block_proxy() -> bool:
    """获取当前代理屏蔽设置。"""
    with _proxy_lock:
        return _block_proxy


_VIRTUAL_NIC_PREFIXES = (
    "docker",  # docker0, docker-*
    "veth",  # veth pair (Docker/K8s)
    "br-",  # bridge (Docker)
    "vmnet",  # VMware
    "vboxnet",  # VirtualBox
    "virbr",  # libvirt
    "tap-",  # TAP (OpenVPN 等)
)


def _is_virtual_nic(name: str) -> bool:
    """判断接口名是否为虚拟网卡（docker/bridge/虚拟机/TAP 等）。"""
    return name.lower().startswith(_VIRTUAL_NIC_PREFIXES)


def is_local_network_connected(interface_name: str = "") -> bool:
    """检查本地网络是否有实际连接（有线或无线）。

    参数:
        interface_name: 指定网卡名称，为空时检查所有物理网卡。
            指定时优先检查该网卡，不可用时回退到检查所有物理网卡。
    """
    try:
        if interface_name:
            stats = psutil.net_if_stats().get(interface_name)
            if stats is not None and stats.isup:
                logger.debug("绑定网卡已连接: {}", interface_name)
                return True
            logger.error("绑定网卡 {} 不可用，回退检查物理网络", interface_name)
        # 原逻辑：任一物理网卡 up
        for name, stats in psutil.net_if_stats().items():
            if (
                stats.isup
                and not name.lower().startswith("lo")
                and not _is_virtual_nic(name)
            ):
                logger.debug("网络接口已连接: {} (speed={}Mbps)", name, stats.speed)
                return True
    except Exception as exc:
        logger.debug("psutil 网络检测失败: {}", exc)

    logger.warning("未检测到本地网络连接")
    return False


def is_network_available_socket(
    test_sites: Sequence[tuple[str, int]] | None = None,
    timeout: float = 1.5,
    source_ip: str | None = None,
) -> bool:
    if _shutdown_event.is_set():
        return False
    if not test_sites:
        from app.constants import DEFAULT_NETWORK_TARGETS
        from app.network.parsers import parse_ping_targets

        test_sites = parse_ping_targets(DEFAULT_NETWORK_TARGETS)
    targets = test_sites

    def _connect_one(host: str, port: int) -> tuple[str, bool, str]:
        start = time.perf_counter()
        try:
            sa = (source_ip, 0) if source_ip else None
            with socket.create_connection(
                (host, port), timeout=timeout, source_address=sa
            ):
                elapsed = (time.perf_counter() - start) * 1000
                return (f"{host}:{port}", True, f"({elapsed:.0f}ms)")
        except Exception as exc:
            elapsed = (time.perf_counter() - start) * 1000
            return (f"{host}:{port}", False, f"{type(exc).__name__}")

    futures = {executor.submit(_connect_one, h, p): (h, p) for h, p in targets}
    return race_first_success(
        futures,
        timeout=timeout + 2,
        label="TCP",
        success_prefix="TCP 连接",
        fail_prefix="TCP 连接",
    )


def is_network_available_url(
    url_checks: Sequence[tuple[str, str]] | None = None,
    timeout: float = 3.0,
    source_ip: str | None = None,
) -> bool:
    """通过网址响应检测 URL 检测网络连通性。

    访问配置的网址响应检测地址，验证响应内容是否包含预期的"正常"标识。
    如果被重定向到登录页面或返回非预期内容，说明需要认证。

    参数:
        url_checks: (URL, 预期内容) 元组列表，为 None 时使用内置默认值
        timeout: 单个请求超时秒数

    返回 True 表示至少有一个检测 URL 返回了预期内容（网络正常）。
    """
    if _shutdown_event.is_set():
        return False
    if url_checks is None:
        from app.constants import DEFAULT_URL_CHECK_URLS
        from app.network.parsers import parse_url_checks

        url_checks = parse_url_checks(DEFAULT_URL_CHECK_URLS)
    if not url_checks:
        return True

    def _check_url(url: str, expected: str) -> tuple[str, bool, str]:
        start = time.perf_counter()
        try:
            block = is_block_proxy()
            client = (
                _get_bound_client(source_ip, block)
                if source_ip
                else _get_probe_client(block)
            )
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

    futures = {executor.submit(_check_url, url, exp): url for url, exp in url_checks}
    return race_first_success(
        futures,
        timeout=timeout + 2,
        label="网址响应检测",
        success_prefix="网址响应检测",
        fail_prefix="网址响应检测",
    )


def _is_captive_portal_url(url: str) -> bool:
    """判断是否为 captive portal 检测 URL（返回 204 表示正常，200 表示被劫持）。"""
    return "generate_204" in url or "connectivitycheck" in url


def is_network_available_http(
    test_urls: Iterable[str] | None = None,
    timeout: float = 2.0,
    follow_redirects: bool = True,
    source_ip: str | None = None,
) -> bool:
    """通过 HTTP(S) 请求检测网络连通性。

    设计说明：故意禁用 SSL 验证（verify=False），因为校园网认证门户
    会用自签名证书拦截 HTTPS 流量。目的是检测连通性，而非验证 TLS 安全性。
    这与 browser.py 中的 ignore_https_errors=True 一致。

    captive portal URL（含 generate_204/connectivitycheck）：仅 204 表示正常，
    200 为门户劫持。普通 URL：200<=status<300 表示连通。
    """
    if _shutdown_event.is_set():
        return False
    if not test_urls:
        from app.constants import DEFAULT_HTTP_TARGETS

        test_urls = DEFAULT_HTTP_TARGETS.split(",")
    urls = list(test_urls)
    if len(urls) == 0:
        return False

    def _check_one(url: str) -> tuple[str, bool, str]:
        """在独立线程中检测单个 URL。返回 (url, success, detail)。"""
        start = time.perf_counter()
        try:
            block = is_block_proxy()
            client = (
                _get_bound_client(source_ip, block)
                if source_ip
                else _get_probe_client(block)
            )
            resp = client.get(
                url, timeout=timeout, follow_redirects=follow_redirects
            )
            elapsed = (time.perf_counter() - start) * 1000
            if _is_captive_portal_url(url):
                ok = resp.status_code == 204
            else:
                ok = 200 <= resp.status_code < 300
            if ok:
                return (url, True, f"HTTP {resp.status_code} ({elapsed:.0f}ms)")
            return (url, False, f"HTTP {resp.status_code} ({elapsed:.0f}ms)")
        except Exception as exc:
            elapsed = (time.perf_counter() - start) * 1000
            # SSL 证书验证失败（校园网门户 HTTPS 劫持自签名证书）降级为 DEBUG
            if isinstance(exc, ssl.SSLError) or "CERTIFICATE_VERIFY_FAILED" in str(exc):
                logger.debug("SSL 证书验证失败 (预期行为): {} - {}", url, exc)
            else:
                logger.debug("HTTP 请求异常: {} - {}", url, exc)
            return (url, False, f"{type(exc).__name__}: {exc}")

    futures = {executor.submit(_check_one, url): url for url in urls}
    return race_first_success(
        futures,
        timeout=timeout + 2,
        label="HTTP",
        success_prefix="HTTP 请求",
        fail_prefix="HTTP 请求",
    )
