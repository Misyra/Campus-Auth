from __future__ import annotations

import socket
from collections.abc import Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from urllib.parse import urlparse

from app.schemas import MonitorSettings, PauseSettings
from app.utils.concurrent import cancel_pending, race_first_success
from app.utils.logging import get_logger
from app.utils.time_utils import is_in_pause_period

from .probes import (
    executor as _executor,
)
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


_decision_executor = ThreadPoolExecutor(
    max_workers=3, thread_name_prefix="net-decision"
)

logger = get_logger("network_decision", source="network")


# ── 公共 API：三个职责清晰的检查函数 ──


def check_pause(pause: PauseSettings) -> tuple[bool, str]:
    """暂停时段检查。"""
    if is_in_pause_period(pause):
        logger.info("暂停时段，跳过检测")
        logger.debug("暂停配置: enabled={}, start={}, end={}",
                      pause.enabled, pause.start_hour, pause.end_hour)
        return (True, "pause_period")
    return (False, "")


def check_network_status(monitor: MonitorSettings) -> tuple[bool, str, str]:
    """网络状态检测 (TCP / HTTP / 网址响应)。

    仅做网络连通性检测，不做物理网络检查和认证地址检查。
    由监控循环调用，决定是否需要触发登录。

    Returns:
        (True, "network_ok", method)   — 网络正常，method 为 tcp/http/url/local_only
        (False, "all_disabled", "none") — 所有检测方式均未启用
        (False, "network_down", "none") — 网络异常，应触发登录
    """
    enable_tcp = monitor.enable_tcp_check
    enable_http = monitor.enable_http_check

    # C09: url_check_urls 已在 MonitorSettings 中为 list[dict]，无需解析
    from app.utils.network import parse_url_checks

    url_checks_raw = monitor.url_check_urls
    if isinstance(url_checks_raw, str) and url_checks_raw.strip():
        url_checks = parse_url_checks(url_checks_raw)
    elif isinstance(url_checks_raw, list) and url_checks_raw:
        # MonitorSettings.url_check_urls 是 list[dict]，转为 (url, expected) 元组
        url_checks = [
            (d["url"], d["expected"])
            for d in url_checks_raw
            if isinstance(d, dict) and d.get("url") and d.get("expected")
        ]
    else:
        url_checks = url_checks_raw if url_checks_raw else None
    enable_url = bool(url_checks)

    # 所有检测都未启用
    if not enable_tcp and not enable_http and not enable_url:
        logger.warning("所有网络检测方式均已关闭，无法判断网络状态")
        return (False, "all_disabled", "none")

    from app.utils.network import parse_ping_targets

    try:
        test_sites = parse_ping_targets(monitor.ping_targets) if monitor.ping_targets else None
    except ValueError:
        logger.warning("网络检测目标配置格式错误，跳过 TCP 检测")
        test_sites = None

    test_urls = monitor.test_urls if monitor.test_urls else None

    ok = is_network_available(
        test_sites=test_sites,
        test_urls=test_urls,
        timeout=monitor.network_check_timeout,
        enable_tcp=enable_tcp,
        enable_http=enable_http,
        url_checks=url_checks,
    )

    if ok:
        # M21: 返回实际使用的检测方法
        if enable_tcp:
            return (True, "network_ok", "tcp")
        if enable_http:
            return (True, "network_ok", "http")
        if enable_url:
            return (True, "network_ok", "url")
        return (True, "network_ok", "local_only")
    return (False, "network_down", "none")


def check_login_prerequisites(
    monitor: MonitorSettings, auth_url: str
) -> tuple[bool, str]:
    """登录前置检查：物理网络 + 认证地址可达性。

    在确定网络异常、准备登录之前调用，避免无效的浏览器启动。

    Returns:
        (True, "")                        — 前置条件满足，可以登录
        (False, "local_disconnected")     — 物理网络未连接
        (False, "auth_url_unreachable")   — 认证地址不可达
    """
    # 物理网络连接检查
    if monitor.enable_local_check and not is_local_network_connected():
        logger.warning("物理网络未连接，跳过登录")
        return (False, "local_disconnected")

    # 认证地址可达性检查
    if monitor.check_auth_url:
        extra_targets = monitor.auth_url_targets if monitor.auth_url_targets else None
        if not _is_auth_url_reachable(auth_url, extra_targets=extra_targets):
            logger.info("认证地址不可达，跳过登录")
            return (False, "auth_url_unreachable")

    return (True, "")


# ── 内部实现 ──


def is_network_available(
    test_sites: Sequence[tuple[str, int]] | None = None,
    test_urls: Iterable[str] | None = None,
    timeout: float = 1.5,
    enable_tcp: bool = True,
    enable_http: bool = True,
    url_checks: Sequence[tuple[str, str]] | None = None,
) -> bool:
    """底层网络状态检测，不包含物理网络检查。"""
    enable_url = bool(url_checks)

    if not enable_tcp and not enable_http and not enable_url:
        return True

    # HTTP 检测：配置为空时使用默认 URL
    _DEFAULT_HTTP_URLS = ("https://www.baidu.com", "https://www.qq.com")
    urls_list = list(test_urls or _DEFAULT_HTTP_URLS) if enable_http else []

    logger.debug(
        "开始网络检测 (TCP={}, HTTP={}, URL={})",
        "开" if enable_tcp else "关",
        "开" if enable_http else "关",
        "开" if enable_url else "关",
    )

    pool = _decision_executor
    futures = {}
    if enable_tcp:
        futures[
            pool.submit(
                is_network_available_socket, test_sites=test_sites, timeout=timeout
            )
        ] = "tcp"
    if enable_http:
        futures[
            pool.submit(
                is_network_available_http,
                test_urls=urls_list,
                timeout=max(timeout, 2.0),
                follow_redirects=not enable_tcp,
            )
        ] = "http"
    if enable_url:
        futures[
            pool.submit(
                is_network_available_url,
                url_checks=url_checks,
                timeout=max(timeout, 3.0),
            )
        ] = "url"

    overall_timeout = max(timeout, 3.0) + 2.0
    try:
        for future in as_completed(futures, timeout=overall_timeout):
            kind = futures[future]
            try:
                ok = future.result(timeout=1)
            except Exception as exc:
                logger.debug("检测 {} 异常: {}", kind, exc)
                ok = False
            if not ok:
                # AND 逻辑：任一检测方法失败即判定网络不可用。
                # 这是故意设计 — 宁可误报断网触发多余登录，不可漏报导致断网不处理。
                # HTTP 200 可能是 captive portal 拦截页面，需 TCP/URL 同时验证。
                cancel_pending(futures)
                return False
    except TimeoutError:
        logger.warning("网络检测超时 ({:.1f}s)，视为网络异常", overall_timeout)
        cancel_pending(futures)
        return False

    return True


def _is_auth_url_reachable(
    auth_url: str,
    extra_targets: Sequence[str] | None = None,
) -> bool:
    """检查认证地址及附加目标的 TCP 可达性。

    有自定义目标时只检测自定义目标，否则检测认证地址本身。
    任一目标可达即返回 True。
    """
    if not auth_url and not extra_targets:
        return True

    def _check_host_port(host: str, port: int, label: str) -> bool:
        try:
            with socket.create_connection((host, port), timeout=3):
                logger.debug("认证可达性检测通过: {}", label)
                return True
        except Exception as exc:
            logger.debug("认证可达性检测失败: {} -- {}", label, exc)
            return False

    # 有 extra_targets 时只检测自定义目标，不回退到 auth_url。
    # 这是故意设计：用户配置 extra_targets 意味着用自定义目标替代认证地址做可达性判断。
    if extra_targets:
        from app.utils.network import parse_host_port

        try:
            targets = parse_host_port(list(extra_targets))
        except ValueError:
            logger.warning("认证地址附加目标格式错误，跳过检测")
            targets = []
        if targets:
            futures = {
                _executor.submit(
                    _check_host_port, host, port, f"{host}:{port}"
                ): (host, port)
                for host, port in targets
            }
            if race_first_success(
                futures,
                timeout=4,
                label="认证可达性",
                success_prefix="",
                fail_prefix="",
            ):
                return True
        logger.info("自定义检测目标均不可达")
        return False

    if auth_url:
        try:
            parsed = urlparse(auth_url)
            host = parsed.hostname
            if not host:
                return True
            port = parsed.port or (443 if parsed.scheme == "https" else 80)
            if _check_host_port(host, port, auth_url):
                return True
        except Exception as exc:
            logger.debug("认证地址解析失败 {}: {}", auth_url, exc)

    logger.info("认证地址不可达")
    return False
