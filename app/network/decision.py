from __future__ import annotations

import socket
from collections.abc import Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from urllib.parse import urlparse

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


def check_pause(config: dict) -> tuple[bool, str]:
    """暂停时段检查。

    Returns:
        (True, "pause_period") — 当前处于暂停时段，应跳过检测
        (False, "")            — 不在暂停时段，可以继续
    """
    pause_config = config.get("pause_login", {})
    if is_in_pause_period(pause_config):
        logger.info("暂停时段，跳过检测 (配置: {})", pause_config)
        return (True, "pause_period")
    return (False, "")


def check_network_status(config: dict) -> tuple[bool, str]:
    """网络状态检测 (TCP / HTTP / 网址响应)。

    仅做网络连通性检测，不做物理网络检查和认证地址检查。
    由监控循环调用，决定是否需要触发登录。

    Returns:
        (True, "network_ok")      — 网络正常，无需登录
        (False, "all_disabled")   — 所有检测方式均未启用
        (False, "network_down")   — 网络异常，应触发登录
    """
    monitor_config = config.get("monitor", {})
    enable_tcp = monitor_config.get("enable_tcp_check", False)
    enable_http = monitor_config.get("enable_http_check", False)
    url_checks = monitor_config.get("url_check_urls", None)
    enable_url = bool(url_checks)

    # 所有检测都未启用
    if not enable_tcp and not enable_http and not enable_url:
        logger.warning(
            "所有网络检测方式均已关闭，无法判断网络状态。请在设置页面的高级选项中至少启用一种检测方式（TCP 或 HTTP）"
        )
        return (False, "all_disabled")

    from app.utils.network import parse_ping_targets

    try:
        test_sites = parse_ping_targets(monitor_config.get("ping_targets", None))
    except ValueError:
        logger.warning("ping_targets 配置格式错误，跳过 TCP 检测")
        test_sites = None

    test_urls = monitor_config.get("test_urls", None)

    ok = is_network_available(
        test_sites=test_sites,
        test_urls=test_urls,
        timeout=monitor_config.get("network_check_timeout", 1.5),
        enable_tcp=enable_tcp,
        enable_http=enable_http,
        url_checks=url_checks,
    )

    if ok:
        return (True, "network_ok")
    return (False, "network_down")


def check_login_prerequisites(config: dict) -> tuple[bool, str]:
    """登录前置检查：物理网络 + 认证地址可达性。

    在确定网络异常、准备登录之前调用，避免无效的浏览器启动。

    Returns:
        (True, "")                        — 前置条件满足，可以登录
        (False, "local_disconnected")     — 物理网络未连接
        (False, "auth_url_unreachable")   — 认证地址不可达
    """
    monitor_config = config.get("monitor", {})

    # 物理网络连接检查
    if (
        monitor_config.get("enable_local_check", True)
        and not is_local_network_connected()
    ):
        logger.warning("物理网络未连接，跳过登录")
        return (False, "local_disconnected")

    # 认证地址可达性检查
    if monitor_config.get("check_auth_url", True):
        auth_url = config.get("auth_url", "")
        extra_targets = monitor_config.get("auth_url_targets")
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
        "开始网络检测 (TCP={}, HTTP={}, 网址响应={}, TCP目标={}, HTTP目标={}, 网址响应目标={})",
        "开" if enable_tcp else "关",
        "开" if enable_http else "关",
        "开" if enable_url else "关",
        len(test_sites or ()),
        len(urls_list),
        len(url_checks or ()),
    )

    from concurrent.futures import as_completed

    socket_ok = http_ok = url_ok = True

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
                for f in futures:
                    if not f.done():
                        f.cancel()
                return False
            if kind == "tcp":
                socket_ok = ok
            elif kind == "http":
                http_ok = ok
            elif kind == "url":
                url_ok = ok
    except TimeoutError:
        logger.warning("网络检测超时 ({:.1f}s)，视为网络异常", overall_timeout)
        for f in futures:
            if not f.done():
                f.cancel()
        return False

    result = (
        (socket_ok or not enable_tcp)
        and (http_ok or not enable_http)
        and (url_ok or not enable_url)
    )

    logger.debug(
        "网络检测完成: TCP={} HTTP={} 网址响应={} -> {}",
        "关" if not enable_tcp else ("通" if socket_ok else "断"),
        "关" if not enable_http else ("通" if http_ok else "断"),
        "关" if not enable_url else ("通" if url_ok else "断"),
        "网络正常" if result else "网络异常",
    )
    return result


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

    if extra_targets:
        from concurrent.futures import as_completed

        from app.utils.network import parse_host_port

        try:
            targets = parse_host_port(list(extra_targets))
        except ValueError:
            logger.warning("auth_url_targets 格式错误，跳过附加目标检测")
            targets = []
        if targets:
            futures = {
                _executor.submit(_check_host_port, host, port, f"{host}:{port}"): (
                    host,
                    port,
                )
                for host, port in targets
            }
            try:
                for future in as_completed(futures, timeout=4):
                    if future.result(timeout=1):
                        # 任一目标可达即取消其余任务
                        for f in futures:
                            f.cancel()
                        return True
            except Exception:
                logger.debug("附加目标并发检测异常", exc_info=True)
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


def check_campus_network_status() -> str:
    """校园网状态检测（供 API 调用）。"""
    logger.info("正在检测校园网状态...")

    if not is_local_network_connected():
        result = "未检测到本地网络连接（未获取到有效IP）"
    elif is_network_available():
        result = "已连接校园网并可访问互联网"
    else:
        result = "已连接校园网，但无法访问互联网，需要认证"

    logger.info("校园网状态: {}", result)
    return result
