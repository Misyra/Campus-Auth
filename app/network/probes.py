from __future__ import annotations

import asyncio
import socket
import ssl
import threading
import time
from collections.abc import Iterable, Sequence

import httpx
import psutil

from app.utils.logging import get_logger

logger = get_logger("network_probes", source="backend")

_shutdown_event = threading.Event()

_proxy_lock = threading.Lock()
_block_proxy = True  # 默认屏蔽系统代理，避免代理影响网络检测


def shutdown_probes() -> None:
    """关闭探测模块：设置停止标志。

    由 ServiceContainer.shutdown() 在应用关闭时调用。
    """
    _shutdown_event.set()


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


_VIRTUAL_NIC_PREFIXES = (
    # Linux
    "docker",  # docker0, docker-*
    "veth",  # veth pair (Docker/K8s)
    "br-",  # bridge (Docker)
    "vmnet",  # VMware
    "vboxnet",  # VirtualBox
    "virbr",  # libvirt
    "tap-",  # TAP (OpenVPN 等)
    # Windows
    "hyper-v",  # Hyper-V Virtual Ethernet Adapter
    "virtualbox",  # VirtualBox Host-Only Network
    "vmware",  # VMware Network Adapter
)

_VIRTUAL_NIC_KEYWORDS = (
    "virtual",  # Virtual Ethernet, Virtual Adapter
    "pseudo",  # Pseudo-Interface
    "tunnel",  # Tunnel, Tunneling
    "miniport",  # WAN Miniport
    "teredo",  # Teredo Tunneling
    "loopback",  # Loopback
)


def _is_virtual_nic(name: str) -> bool:
    """判断接口名是否为虚拟网卡（候选过滤，非最终判定）。"""
    lower = name.lower()
    if lower.startswith(_VIRTUAL_NIC_PREFIXES):
        return True
    return any(kw in lower for kw in _VIRTUAL_NIC_KEYWORDS)


def _get_candidate_interfaces(
    interface_name: str = "",
) -> list[tuple[str, object]]:
    """获取候选网卡列表（up + 非 loopback + 非虚拟网卡 + speed > 0）。"""
    candidates = []
    all_stats = psutil.net_if_stats()

    if interface_name:
        # 指定网卡：直接作为候选（即使可能是虚拟网卡）
        stats = all_stats.get(interface_name)
        if stats is not None and stats.isup:
            candidates.append((interface_name, stats))
        return candidates

    # 未指定：遍历所有网卡，过滤候选
    for name, stats in all_stats.items():
        if not stats.isup:
            continue
        if name.lower().startswith("lo"):
            continue
        if _is_virtual_nic(name):
            continue
        # speed == 0 可能是虚拟网卡或半断开状态，跳过
        if stats.speed == 0:
            continue
        candidates.append((name, stats))

    return candidates


def _check_interface_connectivity(interface_name: str) -> bool:
    """通过 TCP Connect 验证网卡连通性。"""
    # 常见可达目标
    test_targets = [
        ("8.8.8.8", 53),  # Google DNS
        ("114.114.114.114", 53),  # 国内 DNS
        ("1.1.1.1", 53),  # Cloudflare DNS
    ]

    # 获取网卡绑定 IP
    addrs = psutil.net_if_addrs().get(interface_name, [])
    source_ip = None
    for addr in addrs:
        if addr.family == socket.AF_INET:
            source_ip = addr.address
            break

    if not source_ip:
        return False

    # TCP Connect 测试
    for host, port in test_targets:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1.0)
            sock.bind((source_ip, 0))
            result = sock.connect_ex((host, port))
            sock.close()

            if result == 0:
                return True
        except Exception:
            continue

    return False


def is_local_network_connected(interface_name: str = "") -> bool:
    """检查本地网络是否有实际连接。

    策略：候选网卡过滤 + TCP Connect 最终判定。
    """
    try:
        candidates = _get_candidate_interfaces(interface_name)
        if not candidates:
            if interface_name:
                logger.error("绑定网卡 {} 不可用", interface_name)
            else:
                logger.warning("未找到候选网卡")
            return False

        # 对候选网卡执行 TCP Connect 验证
        for name, stats in candidates:
            if _check_interface_connectivity(name):
                logger.debug("网卡 {} 连通性验证通过 (speed={}Mbps)", name, stats.speed)
                return True

        logger.warning("所有候选网卡连通性验证失败")
        return False

    except Exception as exc:
        logger.debug("psutil 网络检测失败: {}", exc)
        return False


async def _race_first_success_async(
    tasks: list,
    timeout: float,
    label: str,
    *,
    success_prefix: str = "",
    fail_prefix: str = "",
) -> bool:
    """OR 语义竞态（async 版本）：首个成功的 task 即返回 True。"""
    try:
        for coro in asyncio.as_completed(tasks, timeout=timeout):
            try:
                result = await coro
            except Exception as e:
                logger.debug("{} 探测异常: {}", label, e, exc_info=True)
                continue

            if isinstance(result, tuple) and len(result) == 3:
                result_label, ok, detail = result
            else:
                result_label, ok, detail = label, bool(result), ""

            if ok:
                if success_prefix:
                    logger.debug("{} 成功: {} {}", success_prefix, result_label, detail)
                return True

            if fail_prefix:
                logger.debug("{} 失败: {} - {}", fail_prefix, result_label, detail)

        return False

    except TimeoutError:
        logger.warning("{} 检测超时 ({:.1f}s)", label, timeout)
        return False


async def is_network_available_socket(
    test_sites: Sequence[tuple[str, int]] | None = None,
    timeout: float = 1.5,
    source_ip: str | None = None,
) -> bool:
    """TCP 连通性检测（async）。"""
    if _shutdown_event.is_set():
        return False
    if not test_sites:
        from app.constants import DEFAULT_NETWORK_TARGETS
        from app.network.parsers import parse_ping_targets

        test_sites = parse_ping_targets(DEFAULT_NETWORK_TARGETS)
    targets = test_sites

    local_addr = (source_ip, 0) if source_ip else None

    async def _connect_one(host: str, port: int) -> tuple[str, bool, str]:
        start = time.perf_counter()
        try:
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port, local_addr=local_addr),
                timeout=timeout,
            )
            writer.close()
            await writer.wait_closed()
            elapsed = (time.perf_counter() - start) * 1000
            return (f"{host}:{port}", True, f"({elapsed:.0f}ms)")
        except (OSError, TimeoutError):
            elapsed = (time.perf_counter() - start) * 1000
            return (f"{host}:{port}", False, "error")

    tasks = [_connect_one(h, p) for h, p in targets]
    return await _race_first_success_async(
        tasks,
        timeout=timeout + 2,
        label="TCP",
        success_prefix="TCP 连接",
        fail_prefix="TCP 连接",
    )


def _is_captive_portal_url(url: str) -> bool:
    """判断是否为 captive portal 检测 URL（返回 204 表示正常，200 表示被劫持）。"""
    return "generate_204" in url or "connectivitycheck" in url


async def is_network_available_url(
    url_checks: Sequence[tuple[str, str]] | None = None,
    timeout: float = 3.0,
    source_ip: str | None = None,
) -> bool:
    """通过网址响应检测 URL 检测网络连通性（async）。

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

    block = is_block_proxy()
    transport = httpx.AsyncHTTPTransport(local_address=source_ip) if source_ip else None

    async with httpx.AsyncClient(
        verify=False,
        follow_redirects=True,
        trust_env=not block,
        transport=transport,
        limits=httpx.Limits(max_connections=4, max_keepalive_connections=2),
    ) as client:

        async def _check_url(url: str, expected: str) -> tuple[str, bool, str]:
            start = time.perf_counter()
            try:
                resp = await client.get(url, timeout=timeout)
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

        tasks = [_check_url(url, exp) for url, exp in url_checks]
        return await _race_first_success_async(
            tasks,
            timeout=timeout + 2,
            label="网址响应检测",
            success_prefix="网址响应检测",
            fail_prefix="网址响应检测",
        )


async def is_network_available_http(
    test_urls: Iterable[str] | None = None,
    timeout: float = 2.0,
    follow_redirects: bool = True,
    source_ip: str | None = None,
) -> bool:
    """通过 HTTP(S) 请求检测网络连通性（async）。

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

    block = is_block_proxy()
    transport = httpx.AsyncHTTPTransport(local_address=source_ip) if source_ip else None

    async with httpx.AsyncClient(
        verify=False,
        follow_redirects=follow_redirects,
        trust_env=not block,
        transport=transport,
        limits=httpx.Limits(max_connections=4, max_keepalive_connections=2),
    ) as client:

        async def _check_one(url: str) -> tuple[str, bool, str]:
            start = time.perf_counter()
            try:
                resp = await client.get(url, timeout=timeout)
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
                if isinstance(exc, ssl.SSLError) or "CERTIFICATE_VERIFY_FAILED" in str(
                    exc
                ):
                    logger.debug("SSL 证书验证失败 (预期行为): {} - {}", url, exc)
                else:
                    logger.debug("HTTP 请求异常: {} - {}", url, exc)
                return (url, False, f"{type(exc).__name__}: {exc}")

        tasks = [_check_one(url) for url in urls]
        return await _race_first_success_async(
            tasks,
            timeout=timeout + 2,
            label="HTTP",
            success_prefix="HTTP 请求",
            fail_prefix="HTTP 请求",
        )
