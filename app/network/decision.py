"""网络检测决策层 — 协调 TCP/HTTP/URL 探测，处理网卡绑定与暂停逻辑。"""

from __future__ import annotations

import asyncio
import socket
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from urllib.parse import urlparse

from app.schemas import MonitorSettings, PauseSettings
from app.utils.logging import get_logger
from app.utils.time_utils import is_pause_enabled

from .interface_bind import bind_socket_to_interface
from .interfaces import InterfaceManager
from .probes import (
    is_local_network_connected,
    is_network_available_http,
    is_network_available_socket,
    is_network_available_url,
)


@dataclass(slots=True)
class NetworkCheckResult:
    """单次网络检查的结果，无副作用。"""

    available: bool | None  # None 表示被暂停跳过
    method: str  # "tcp" / "http" / "url" / "paused" / "local_only" / "all_disabled"
    latency_ms: float
    detail: str = ""  # 失败时的附加信息


logger = get_logger("network_decision", source="backend")

# ── 绑定网卡解析 ──

_interface_mgr: InterfaceManager | None = None


def _get_interface_mgr() -> InterfaceManager:
    """获取 InterfaceManager 单例。"""
    global _interface_mgr
    if _interface_mgr is None:
        _interface_mgr = InterfaceManager()
    return _interface_mgr


def _resolve_interface(monitor: MonitorSettings) -> tuple[str, str | None]:
    """从 MonitorSettings 解析绑定网卡信息。

    Returns:
        (interface_name, fallback_source_ip)
        - interface_name: 网卡名，空串表示不绑定
        - fallback_source_ip: Linux 无 CAP_NET_RAW 时降级用 source IP
    """
    name = monitor.bind_interface_name
    if not name:
        return ("", None)
    ip = _get_interface_mgr().resolve_ip(name)
    if ip is None:
        logger.error("绑定网卡 {} 不可用，回退到系统默认路由", name)
        return ("", None)
    return (name, ip)


# ── 公共 API：三个职责清晰的检查函数 ──


def check_pause(pause: PauseSettings) -> tuple[bool, str]:
    """暂停时段检查。"""
    if is_pause_enabled(pause):
        logger.debug("暂停时段，跳过检测")
        logger.debug(
            "暂停配置: enabled={}, start={}, end={}",
            pause.enabled,
            pause.start_hour,
            pause.end_hour,
        )
        return (True, "pause_period")
    return (False, "")


async def check_network_status(monitor: MonitorSettings) -> tuple[bool, str, str]:
    """网络状态检测（async） (TCP / HTTP / 网址响应)。

    仅做网络连通性检测，不做物理网络检查和认证地址检查。
    由监控循环调用，决定是否需要触发登录。

    Returns:
        (True, "network_ok", method)   — 网络正常，method 为 tcp/http/url/local_only
        (False, "all_disabled", "none") — 所有检测方式均未启用
        (False, "network_down", "none") — 网络异常，应触发登录
    """
    enable_tcp = monitor.enable_tcp_check
    enable_http = monitor.enable_http_check

    from app.network.parsers import parse_url_checks

    url_checks = parse_url_checks(monitor.url_check_urls) or None
    enable_url = bool(url_checks)

    # 所有检测都未启用
    if not enable_tcp and not enable_http and not enable_url:
        logger.warning("所有网络检测方式均已关闭，无法判断网络状态")
        return (False, "all_disabled", "none")

    from app.network.parsers import parse_ping_targets

    try:
        test_sites = (
            parse_ping_targets(monitor.ping_targets) if monitor.ping_targets else None
        )
    except ValueError:
        logger.warning("网络检测目标配置格式错误，跳过 TCP 检测")
        test_sites = None

    test_urls = monitor.test_urls if monitor.test_urls else None

    interface_name, fallback_ip = _resolve_interface(monitor)

    ok = await is_network_available(
        test_sites=test_sites,
        test_urls=test_urls,
        timeout=monitor.network_check_timeout,
        enable_tcp=enable_tcp,
        enable_http=enable_http,
        url_checks=url_checks,
        interface_name=interface_name,
        fallback_source_ip=fallback_ip,
    )

    if ok:
        # M21: 返回实际使用的检测方法
        if enable_tcp:
            method = "tcp"
        elif enable_http:
            method = "http"
        elif enable_url:
            method = "url"
        else:
            method = "local_only"
        logger.debug("网络检测通过: 方式={}", method)
        return (True, "network_ok", method)
    return (False, "network_down", "none")


async def check_login_prerequisites(
    monitor: MonitorSettings, auth_url: str
) -> tuple[bool, str]:
    """登录前置检查（async）：物理网络 + 认证地址可达性。"""
    interface_name, fallback_ip = _resolve_interface(monitor)

    # 物理网络连接检查
    if monitor.enable_local_check and not await is_local_network_connected(
        interface_name=interface_name
    ):
        logger.debug("物理网络未连接，跳过登录")
        return (False, "local_disconnected")

    # 认证地址可达性检查
    if monitor.check_auth_url:
        extra_targets = monitor.auth_url_targets if monitor.auth_url_targets else None
        if not await _is_auth_url_reachable(
            auth_url,
            extra_targets=extra_targets,
            interface_name=interface_name,
            fallback_source_ip=fallback_ip,
        ):
            logger.debug("认证地址不可达，跳过登录")
            return (False, "auth_url_unreachable")

    return (True, "")


# ── 内部实现 ──


async def is_network_available(
    test_sites: Sequence[tuple[str, int]] | None = None,
    test_urls: Iterable[str] | None = None,
    timeout: float = 1.5,
    enable_tcp: bool = True,
    enable_http: bool = True,
    url_checks: Sequence[tuple[str, str]] | None = None,
    interface_name: str = "",
    fallback_source_ip: str | None = None,
) -> bool:
    """底层网络状态检测（async），不包含物理网络检查。

    绑定网卡时（interface_name 非空）：HTTP/URL 探测因 httpx 无法绑接口而跳过，
    只保留 TCP 探测（绑接口后能准确判断网卡连通性）。
    """
    enable_url = bool(url_checks)

    # 绑网卡时：只保留 TCP 探测（绑接口），跳过 HTTP/URL（httpx 无法绑接口）
    if interface_name:
        if not enable_tcp:
            logger.warning("绑定网卡但 TCP 检测未启用，无法判断网络状态")
            return False
        logger.debug("绑定网卡 {}，仅使用 TCP 探测", interface_name)
        return await is_network_available_socket(
            test_sites=test_sites,
            timeout=timeout,
            interface_name=interface_name,
            fallback_source_ip=fallback_source_ip,
        )

    if not enable_tcp and not enable_http and not enable_url:
        return True

    if enable_http and not test_urls:
        from app.constants import DEFAULT_HTTP_TARGETS

        test_urls = DEFAULT_HTTP_TARGETS.split(",")
    urls_list = list(test_urls) if enable_http and test_urls else []

    logger.debug(
        "开始网络检测 (TCP={}, HTTP={}, URL={})",
        "开" if enable_tcp else "关",
        "开" if enable_http else "关",
        "开" if enable_url else "关",
    )

    tasks = []
    if enable_tcp:
        tasks.append(
            is_network_available_socket(
                test_sites=test_sites, timeout=timeout
            )
        )
    if enable_http:
        tasks.append(
            is_network_available_http(
                test_urls=urls_list,
                timeout=max(timeout, 2.0),
                follow_redirects=not enable_tcp,
            )
        )
    if enable_url:
        tasks.append(
            is_network_available_url(
                url_checks=url_checks,
                timeout=max(timeout, 3.0),
            )
        )

    overall_timeout = max(timeout, 3.0) + 2.0
    try:
        results = await asyncio.wait_for(
            asyncio.gather(*tasks, return_exceptions=True),
            timeout=overall_timeout,
        )
    except TimeoutError:
        logger.warning("网络检测失败: 超时 ({:.1f}s)", overall_timeout)
        return False

    # AND 逻辑：任一检测方法失败即判定网络不可用。
    # 这是故意设计 — 宁可误报断网触发多余登录，不可漏报导致断网不处理。
    # HTTP 200 可能是 captive portal 拦截页面，需 TCP/URL 同时验证。
    for ok in results:
        if isinstance(ok, Exception):
            logger.debug("检测异常: {}", ok)
            return False
        if not ok:
            return False
    return True


async def _is_auth_url_reachable(
    auth_url: str,
    extra_targets: Sequence[str] | None = None,
    interface_name: str = "",
    fallback_source_ip: str | None = None,
) -> bool:
    """检查认证地址及附加目标的 TCP 可达性（async）。

    绑定网卡时用接口索引绑定，确保探测走指定接口。
    """
    if not auth_url and not extra_targets:
        return True

    use_interface = bool(interface_name)
    loop = asyncio.get_event_loop()

    async def _check_host_port(host: str, port: int, label: str) -> bool:
        if use_interface:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.setblocking(False)
            try:
                bind_socket_to_interface(sock, interface_name, fallback_source_ip)
                await asyncio.wait_for(
                    loop.sock_connect(sock, (host, port)), timeout=3
                )
                sock.close()
                logger.debug("认证可达性检测通过: {}", label)
                return True
            except (OSError, TimeoutError) as exc:
                sock.close()
                logger.debug("认证可达性检测失败: {} -- {}", label, exc)
                return False
        else:
            try:
                _, writer = await asyncio.wait_for(
                    asyncio.open_connection(host, port), timeout=3
                )
                writer.close()
                await writer.wait_closed()
                logger.debug("认证可达性检测通过: {}", label)
                return True
            except (OSError, TimeoutError) as exc:
                logger.debug("认证可达性检测失败: {} -- {}", label, exc)
                return False

    if extra_targets:
        from app.network.parsers import parse_host_port

        targets = parse_host_port(list(extra_targets))
        if targets:
            for host, port in targets:
                if await _check_host_port(host, port, f"{host}:{port}"):
                    return True
        logger.debug("自定义检测目标均不可达")
        return False

    if auth_url:
        try:
            parsed = urlparse(auth_url)
            host = parsed.hostname
            if not host:
                logger.debug("认证地址 hostname 解析失败，视为不可达: {}", auth_url)
                return False
            port = parsed.port or (443 if parsed.scheme == "https" else 80)
            if await _check_host_port(host, port, auth_url):
                return True
        except Exception as exc:
            logger.debug("认证地址可达性检测异常: {} -- {}", auth_url, exc)
            return False

    return False
