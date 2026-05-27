from __future__ import annotations

import re
import socket
import ssl
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Iterable, Sequence

import httpx

from src.utils.logging import get_logger
from src.utils.platform_utils import is_windows, is_macos, is_linux

logger = get_logger("network_probes", side="BACKEND")

_executor = ThreadPoolExecutor(max_workers=5)
_block_proxy = True  # 默认屏蔽系统代理，避免代理影响网络检测


def set_block_proxy(enabled: bool) -> None:
    """设置是否屏蔽系统代理。

    当 enabled=True 时，HTTP 客户端不读取系统代理设置（默认行为）；
    当 enabled=False 时，允许 HTTP 客户端使用系统代理。
    """
    global _block_proxy
    _block_proxy = enabled


def is_local_network_connected() -> bool:
    """检查本地网络是否有实际连接（有线或无线）。

    优先使用快速 IP 检测，失败时回退到平台特判。
    """
    # 优先：快速 IP 检测（~10ms），避免 Windows 上 PowerShell 启动慢
    try:
        hostname = socket.gethostname()
        ip_list = socket.gethostbyname_ex(hostname)[2]
        non_loopback = [
            ip
            for ip in ip_list
            if not ip.startswith("127.") and not ip.startswith("169.254.")
        ]
        if non_loopback:
            logger.info("本地网络已连接，IP: %s", ", ".join(non_loopback))
            return True
    except Exception as exc:
        logger.debug("快速 IP 检测失败: %s", exc)

    # 回退：平台特判
    try:
        if is_windows():
            return _check_windows_adapter()
        elif is_linux():
            return _check_linux_route()
        elif is_macos():
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
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "Get-NetAdapter | Select-Object -ExpandProperty Status",
            ],
            capture_output=True,
            text=True,
            timeout=5,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.returncode == 0:
            statuses = [
                line.strip().lower()
                for line in result.stdout.splitlines()
                if line.strip()
            ]
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
            capture_output=True,
            text=True,
            timeout=5,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.returncode != 0:
            logger.debug("netsh 执行失败: %s", result.stderr)
            return False

        # 已知的"已连接"多语言映射
        connected_keywords = {
            "connected",
            "已连接",
            "接続済み",
            "connecté",
            "verbunden",
            "подключено",
            "conectado",
        }
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

    动态获取所有硬件接口列表（而非硬编码 en0/en1），
    用 networksetup 列出所有端口对应的设备名，
    再用 ifconfig 逐一检查是否有活跃连接。
    """
    try:
        # 列出所有硬件端口及其设备名（输出受系统语言影响，设置 LC_ALL=C 强制英文）
        list_result = subprocess.run(
            ["networksetup", "-listallhardwareports"],
            capture_output=True,
            text=True,
            timeout=5,
            env={"LC_ALL": "C"},  # 强制英文输出，便于解析 Device/Port 等关键字
        )
        if list_result.returncode != 0:
            logger.debug("networksetup 执行失败: %s", list_result.stderr)
            raise RuntimeError("networksetup failed")

        # 解析 "Device: XXX" 行，提取所有硬件设备名
        devices = re.findall(r"^Device: (.+)$", list_result.stdout, re.MULTILINE)
        if not devices:
            logger.debug("未从 networksetup 输出中找到任何设备")
            return False
    except Exception as exc:
        logger.debug("networksetup 检测失败，回退到硬编码接口: %s", exc)
        devices = ("en0", "en1")  # 回退：常见接口名

    for iface in devices:
        try:
            result = subprocess.run(
                ["ifconfig", iface],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode != 0:
                continue
            # 检查是否有 "status: active" 或分配了非 0.0.0.0 的 IP
            output = result.stdout
            if "status: active" in output:
                # 进一步确认有 IP 地址
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

    futures = {_executor.submit(_connect_one, h, p): (h, p) for h, p in targets}
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
            with httpx.Client(verify=False, trust_env=not _block_proxy) as client:
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
                logger.debug("SSL 证书验证失败 (预期行为): %s — %s", url, exc)
            else:
                logger.info("HTTP 请求异常: %s — %s", url, exc)
            return (url, False, f"{type(exc).__name__}: {exc}")

    futures = {_executor.submit(_check_one, url): url for url in urls}
    for future in as_completed(futures):
        url, ok, detail = future.result()
        if ok:
            logger.info("HTTP 请求成功: %s → %s", url, detail)
            return True
        logger.info("HTTP 请求失败: %s — %s", url, detail)
    logger.warning("所有 HTTP 目标均不可达 (%d 个)", len(urls))
    return False
