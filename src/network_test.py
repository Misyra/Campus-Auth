from __future__ import annotations

import logging
import platform
import socket
import subprocess
import sys
import atexit
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Iterable, Sequence

import httpx

from src.utils.logging import get_logger

logger = get_logger("network_test", side="BACKEND")

_executor: ThreadPoolExecutor | None = None
_thread_local = threading.local()


def _get_executor() -> ThreadPoolExecutor:
    global _executor
    if _executor is None:
        _executor = ThreadPoolExecutor(max_workers=5)
    return _executor


def _get_http_client() -> httpx.Client:
    if not hasattr(_thread_local, "client"):
        _thread_local.client = httpx.Client(trust_env=False)
    return _thread_local.client


def _cleanup_resources() -> None:
    global _executor
    if _executor is not None:
        _executor.shutdown(wait=False, cancel_futures=True)
        _executor = None


atexit.register(_cleanup_resources)


def is_local_network_connected() -> bool:
    """检查本地网络是否有实际连接（有线或无线）。

    优先使用快速 IP 检测，失败时回退到平台特判。
    """
    # 优先：快速 IP 检测（~10ms），避免 Windows 上 PowerShell 启动慢
    try:
        hostname = socket.gethostname()
        ip_list = socket.gethostbyname_ex(hostname)[2]
        non_loopback = [ip for ip in ip_list if not ip.startswith("127.")]
        if non_loopback:
            logger.info("本地网络已连接，IP: %s", ", ".join(non_loopback))
            return True
    except Exception as exc:
        logger.debug("快速 IP 检测失败: %s", exc)

    # 回退：平台特判
    system = platform.system()
    try:
        if system == "Windows":
            return _check_windows_adapter()
        elif system == "Linux":
            return _check_linux_route()
        elif system == "Darwin":
            return _check_macos_service()
    except Exception as exc:
        logger.debug("平台网络检测失败: %s", exc)

    logger.warning("未检测到本地网络连接")
    return False


def _check_windows_adapter() -> bool:
    """Windows: 检查网络适配器是否实际连接。

    netsh 输出是本地化的（中文"已连接"、英文"Connected"、日文"接続済み"等），
    无法穷举所有语言。改用 PowerShell Get-NetAdapter（输出结构化，不依赖语言），
    失败时回退到 netsh + 多语言匹配。
    """
    # 优先使用 PowerShell（结构化输出，不受系统语言影响）
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-NetAdapter | Select-Object -ExpandProperty Status"],
            capture_output=True, text=True, timeout=5,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.returncode == 0:
            statuses = [line.strip().lower() for line in result.stdout.splitlines() if line.strip()]
            if "up" in statuses:
                logger.info("检测到已连接的网络适配器 (PowerShell)")
                return True
            logger.warning("所有网络适配器均未连接 (PowerShell)")
            return False
    except FileNotFoundError:
        logger.debug("PowerShell 不可用，回退到 netsh")

    # 回退：netsh（输出受系统语言影响，尝试常见语言）
    try:
        result = subprocess.run(
            ["netsh", "interface", "show", "interface"],
            capture_output=True, text=True, timeout=5,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.returncode != 0:
            logger.debug("netsh 执行失败: %s", result.stderr)
            return False

        # 已知的"已连接"多语言映射
        connected_keywords = {"connected", "已连接", "接続済み", "connecté",
                              "verbunden", "подключено", "conectado"}
        for line in result.stdout.splitlines():
            parts = line.split()
            if len(parts) >= 4 and parts[1].lower() in connected_keywords:
                name = " ".join(parts[3:])
                lower_name = name.lower()
                if "loopback" not in lower_name and "tunnel" not in lower_name:
                    logger.info("检测到已连接的网络接口: %s", name)
                    return True

        logger.warning("未检测到已连接的网络接口")
        return False
    except FileNotFoundError:
        logger.debug("netsh 不可用")
        return False


def _check_linux_route() -> bool:
    """Linux: 检查是否有默认路由（表示有实际网络连接）。"""
    try:
        with open("/proc/net/route", "r") as f:
            for line in f:
                fields = line.strip().split()
                if len(fields) >= 3 and fields[1] == "00000000":
                    iface = fields[0]
                    if iface != "lo":
                        logger.info("检测到默认路由接口: %s", iface)
                        return True
    except Exception as exc:
        logger.debug("读取路由表失败: %s", exc)
    logger.warning("未检测到默认路由")
    return False


def _check_macos_service() -> bool:
    """macOS: 检查网络接口是否有实际连接（IP 地址分配）。

    使用 ifconfig 检查常见接口（en0=有线/WiFi, en1=WiFi/有线）是否分配了 IP。
    仅检查接口名存在不够 — 接口可能存在但未连接。
    """
    for iface in ("en0", "en1"):
        try:
            result = subprocess.run(
                ["ifconfig", iface],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode != 0:
                continue
            # 检查是否有 "status: active" 或分配了非 0.0.0.0 的 IP
            output = result.stdout
            if "status: active" in output:
                # 进一步确认有 IP 地址
                import re
                if re.search(r"inet\s+(?!0\.0\.0\.0)\d+\.\d+\.\d+\.\d+", output):
                    logger.info("检测到活跃的网络接口: %s", iface)
                    return True
        except Exception:
            continue

    logger.warning("未检测到活跃的网络接口")
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

    executor = _get_executor()
    futures = {executor.submit(_connect_one, h, p): (h, p) for h, p in targets}
    for future in as_completed(futures):
        label, ok, detail = future.result()
        if ok:
            logger.info("TCP 连接成功: %s %s", label, detail)
            return True
        logger.info("TCP 连接失败: %s — %s", label, detail)
    logger.warning("所有 TCP 目标均不可达 (%d 个)", len(targets))
    return False


def is_network_available_http(
    test_urls: Iterable[str] | None = None,
    timeout: float = 2.0,
    follow_redirects: bool = True,
) -> bool:
    urls = list(test_urls or ("https://www.baidu.com", "https://www.qq.com"))
    if len(urls) == 0:
        return False

    def _check_one(url: str) -> tuple[str, bool, str]:
        """在独立线程中检测单个 URL。返回 (url, success, detail)。"""
        start = time.perf_counter()
        try:
            client = _get_http_client()
            resp = client.get(url, timeout=timeout, follow_redirects=follow_redirects)
            elapsed = (time.perf_counter() - start) * 1000
            if 200 <= resp.status_code < 300:
                return (url, True, f"HTTP {resp.status_code} ({elapsed:.0f}ms)")
            return (url, False, f"HTTP {resp.status_code} ({elapsed:.0f}ms)")
        except Exception as exc:
            elapsed = (time.perf_counter() - start) * 1000
            return (url, False, f"{type(exc).__name__}: {exc}")

    executor = _get_executor()
    futures = {executor.submit(_check_one, url): url for url in urls}
    for future in as_completed(futures):
        url, ok, detail = future.result()
        if ok:
            logger.info("HTTP 请求成功: %s → %s", url, detail)
            return True
        logger.info("HTTP 请求失败: %s — %s", url, detail)
    logger.warning("所有 HTTP 目标均不可达 (%d 个)", len(urls))
    return False


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
    logger.info("开始网络检测 (TCP目标=%d, HTTP目标=%d, require_both=%s)",
                len(test_sites or ()), len(urls_list), require_both)
    socket_ok = is_network_available_socket(test_sites=test_sites, timeout=timeout)
    if require_both:
        # 严格模式：TCP + HTTP 双重验证
        # TCP 已失败则直接判定断网，跳过 HTTP 省时间
        if not socket_ok:
            logger.info("网络检测完成: TCP=断 → 严格模式直接判定网络异常，跳过 HTTP")
            return False
        # 不跟重定向：portal 重定向到登录页 = 未认证 = 判定失败
        http_ok = is_network_available_http(
            test_urls=urls_list, timeout=max(timeout, 2.0), follow_redirects=False,
        )
        result = http_ok
    else:
        # TCP 成功即可，跳过 HTTP 检测节省时间
        if socket_ok:
            logger.info("网络检测完成: TCP=通 → 网络正常")
            return True
        http_ok = is_network_available_http(test_urls=urls_list, timeout=max(timeout, 2.0))
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
