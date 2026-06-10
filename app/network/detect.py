"""网络环境检测 — 网关 IP 和 WiFi SSID 的跨平台检测工具。

从 backend/profile_service.py 提取，作为独立的工具模块。
"""

from __future__ import annotations

import locale
import re
import subprocess

from app.utils.logging import get_logger
from app.utils.platform_utils import (
    CREATE_NO_WINDOW_FLAG,
    is_linux,
    is_macos,
    is_windows,
)

logger = get_logger("network_detect", source="network")


# ── 公共 API ──


def detect_gateway_ip() -> str | None:
    """检测当前默认网关 IP（跨平台）"""
    logger.debug("正在检测网关 IP")

    try:
        if is_windows():
            result = _detect_gateway_windows()
        elif is_linux():
            result = _detect_gateway_linux()
        elif is_macos():
            result = _detect_gateway_darwin()
        else:
            logger.warning("不支持的平台")
            return None

        if result:
            logger.info("检测到网关 IP: {}", result)
        else:
            logger.warning("未能检测到网关 IP")
        return result
    except Exception as exc:
        logger.error("网关检测异常: {}", exc, exc_info=True)
        return None


def detect_wifi_ssid() -> str | None:
    """检测当前连接的 WiFi SSID（跨平台）"""
    logger.debug("正在检测 SSID")

    try:
        if is_windows():
            result = _detect_ssid_windows()
        elif is_linux():
            result = _detect_ssid_linux()
        elif is_macos():
            result = _detect_ssid_darwin()
        else:
            logger.warning("不支持的平台")
            return None

        if result:
            logger.info("检测到 SSID: {}", result)
        else:
            logger.warning("未能检测到 SSID（可能未连接 WiFi）")
        return result
    except Exception as exc:
        logger.error("SSID 检测异常: {}", exc, exc_info=True)
        return None


# ── Windows 实现 ──


def _detect_gateway_windows() -> str | None:
    """Windows: 检测默认网关 IP。

    优先使用 PowerShell Get-NetRoute（结构化输出，不受系统语言影响），
    失败时回退到 ipconfig + 多语言字节匹配。
    """
    creationflags = CREATE_NO_WINDOW_FLAG

    # 优先使用 PowerShell（结构化输出，不受语言影响）
    try:
        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "Get-NetRoute -DestinationPrefix '0.0.0.0/0' | "
                "Select-Object -First 1 -ExpandProperty NextHop",
            ],
            capture_output=True,
            text=True,
            timeout=5,
            creationflags=creationflags,
        )
        if result.returncode == 0:
            ip = result.stdout.strip()
            if ip and re.fullmatch(r"\d+\.\d+\.\d+\.\d+", ip) and ip != "0.0.0.0":
                logger.info("检测到网关 IP (PowerShell): {}", ip)
                return ip
    except FileNotFoundError:
        logger.debug("PowerShell 不可用，回退到 ipconfig")
    except Exception as exc:
        logger.debug("PowerShell 网关检测失败: {}", exc)

    # 回退：ipconfig + 多语言字节匹配
    try:
        result = subprocess.run(
            ["ipconfig"],
            capture_output=True,
            timeout=5,
            creationflags=creationflags,
        )
        logger.debug(
            "ipconfig 返回码: {}, 输出长度: {}", result.returncode, len(result.stdout)
        )

        output = result.stdout

        # 使用原始字节匹配，避免 Windows 编码问题
        gateway_patterns = [
            rb"\xc4\xac\xc8\xcf\xcd\xf8\xb9\xd8",  # "默认网关" GBK
            rb"Default\s+Gateway",  # English
            rb"Standardgateway",  # German
            rb"Passerelle\s+par\s+d\xc3\xa9faut",  # French (UTF-8)
            rb"Gateway\s+predefinito",  # Italian
            rb"Puerta\s+de\s+enlace\s+predeterminada",  # Spanish
            rb"\xe3\x83\x87\xe3\x83\x95\xe3\x82\xa9\xe3\x83\xab\xe3\x83\x88\xe3\x82\xb2\xe3\x83\xbc\xe3\x83\x88\xe3\x82\xa6\xe3\x82\xa7\xe3\x82\xa4",  # "デフォルトゲートウェイ" UTF-8
            rb"\xec\x98\xa4\xeb\xa5\xb8 \xea\xb2\x8c\xec\x9d\xb4\xed\x8a\xb8\xec\x9b\xa8\xec\x9d\xb4",  # "오른 게이트웨이" UTF-8
        ]
        combined = rb"(?:" + rb"|".join(gateway_patterns) + rb")"
        pattern = re.compile(combined + rb"[\s.:]*(\d+\.\d+\.\d+\.\d+)")
        for match in pattern.finditer(output):
            ip = match.group(1).decode("ascii")
            if ip != "0.0.0.0":
                return ip

        logger.debug("ipconfig 输出中未找到网关地址")
    except FileNotFoundError:
        logger.error("ipconfig 命令不存在")
    except subprocess.TimeoutExpired:
        logger.error("ipconfig 执行超时")
    except Exception as exc:
        logger.error("Windows 网关检测失败: {}", exc, exc_info=True)

    return None


def _detect_ssid_windows() -> str | None:
    """Windows: 解析 netsh wlan show interfaces 获取当前 WiFi SSID。"""
    try:
        creationflags = CREATE_NO_WINDOW_FLAG
        result = subprocess.run(
            ["netsh", "wlan", "show", "interfaces"],
            capture_output=True,
            timeout=5,
            creationflags=creationflags,
        )
        output = result.stdout

        encoding = locale.getpreferredencoding(False) or "utf-8"

        pattern = re.compile(rb"^\s*SSID\s*:\s*(.+)$", re.MULTILINE)
        match = pattern.search(output)
        if match:
            raw = match.group(1).strip()
            try:
                ssid = raw.decode(encoding)
            except (UnicodeDecodeError, LookupError):
                ssid = raw.decode("utf-8", errors="replace")
            if ssid:
                return ssid
    except Exception as exc:
        logger.debug("Windows SSID 检测失败: {}", exc)

    return None


# ── Linux 实现 ──


def _detect_gateway_linux() -> str | None:
    """Linux: 解析 /proc/net/route 获取默认网关"""
    try:
        with open("/proc/net/route") as f:
            for line in f:
                parts = line.strip().split()
                if len(parts) >= 3 and parts[1] == "00000000":
                    gateway_hex = parts[2]
                    gateway_bytes = bytes.fromhex(gateway_hex)
                    ip = ".".join(str(b) for b in reversed(gateway_bytes))
                    if ip != "0.0.0.0":
                        return ip
    except Exception as exc:
        logger.debug("Linux 网关检测失败: {}", exc)

    return None


def _detect_ssid_linux() -> str | None:
    """Linux: 使用 iwgetid 或 nmcli 获取当前 WiFi SSID"""
    try:
        result = subprocess.run(
            ["iwgetid", "-r"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        ssid = result.stdout.strip()
        if ssid:
            return ssid
    except FileNotFoundError:
        pass
    except Exception as exc:
        logger.debug("Linux SSID 检测失败 (iwgetid): {}", exc)

    # Fallback: nmcli
    try:
        result = subprocess.run(
            ["nmcli", "-t", "-f", "active,ssid", "dev", "wifi"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        for line in result.stdout.splitlines():
            if line.startswith("yes:"):
                return line.split(":", 1)[1].strip()
    except Exception as exc:
        logger.debug("Linux SSID 检测失败 (nmcli): {}", exc)

    return None


# ── macOS 实现 ──


def _detect_gateway_darwin() -> str | None:
    """macOS: 解析 netstat -nr 获取默认网关"""
    try:
        result = subprocess.run(
            ["netstat", "-nr"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        for line in result.stdout.splitlines():
            if line.startswith("default"):
                parts = line.split()
                if len(parts) >= 2:
                    ip = parts[1]
                    if re.fullmatch(r"\d+\.\d+\.\d+\.\d+", ip) and ip != "0.0.0.0":
                        return ip
    except Exception as exc:
        logger.debug("macOS 网关检测失败: {}", exc)

    return None


def _detect_ssid_darwin() -> str | None:
    """macOS: 获取当前 WiFi SSID。"""
    # 方式 1：airport 命令（较旧 macOS）
    try:
        result = subprocess.run(
            [
                "/System/Library/PrivateFrameworks/Apple80211.framework"
                "/Versions/Current/Resources/airport",
                "-I",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                if "SSID:" in line and "BSSID:" not in line:
                    ssid = line.split(":", 1)[1].strip()
                    if ssid:
                        return ssid
    except FileNotFoundError:
        logger.debug("airport 命令不存在（较新 macOS 版本）")
    except Exception as exc:
        logger.debug("macOS SSID 检测失败 (airport): {}", exc)

    # 方式 2：networksetup（所有 macOS 版本可用）
    try:
        result = subprocess.run(
            ["networksetup", "-listallhardwareports"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        wifi_device = None
        lines = result.stdout.splitlines()
        for i, line in enumerate(lines):
            if ("Wi-Fi" in line or "AirPort" in line) and i + 1 < len(lines):
                wifi_device = lines[i + 1].split(":")[-1].strip()
                break

        if wifi_device:
            result = subprocess.run(
                ["networksetup", "-getairportnetwork", wifi_device],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                output = result.stdout.strip()
                if ":" in output:
                    ssid = output.split(":", 1)[1].strip()
                    if ssid and "not associated" not in ssid.lower():
                        return ssid
    except Exception as exc:
        logger.debug("macOS SSID 检测失败 (networksetup): {}", exc)

    return None
