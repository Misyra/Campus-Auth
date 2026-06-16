"""浏览器注册表 — 检测系统已安装的浏览器。"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from app.utils.logging import get_logger
from app.utils.platform import get_platform

logger = get_logger("browser_registry", source="backend")

PLATFORM = get_platform()


@dataclass
class BrowserInfo:
    """浏览器信息。"""

    channel: str          # "playwright" | "msedge" | "chrome" | "firefox" | "custom"
    name: str             # 显示名称
    icon: str             # 图标类名
    installed: bool       # 系统是否已安装
    needs_download: bool  # 是否需要下载驱动
    description: str      # 状态描述


def detect_browsers() -> list[BrowserInfo]:
    """检测系统已安装的浏览器。

    仅在向导和设置页面调用，启动时直接使用配置的 channel。
    """
    browsers = [
        _detect_playwright_chromium(),
        _detect_edge(),
        _detect_chrome(),
        _detect_firefox(),
        _detect_custom(),
    ]
    return browsers


def _detect_playwright_chromium() -> BrowserInfo:
    """检测 Playwright Chromium 是否已下载。"""
    installed = _has_playwright_chromium()
    return BrowserInfo(
        channel="playwright",
        name="Playwright Chromium",
        icon='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M12 2a10 10 0 0 1 0 20"/><path d="M12 2a10 10 0 0 0 0 20"/><line x1="2" y1="12" x2="22" y2="12"/></svg>',
        installed=installed,
        needs_download=not installed,
        description="推荐选项，内置浏览器" if installed else "需下载约 150MB"
    )


def _detect_edge() -> BrowserInfo:
    """检测系统是否安装 Microsoft Edge。"""
    installed = _check_command_exists("microsoft-edge") or _check_command_exists("msedge")
    if PLATFORM == "windows":
        # Windows 必有 Edge
        installed = True
    elif PLATFORM == "darwin":
        installed = Path("/Applications/Microsoft Edge.app").exists()
    return BrowserInfo(
        channel="msedge",
        name="Microsoft Edge",
        icon='<svg viewBox="0 0 24 24" fill="none"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-1 15h-2v-2h2v2zm0-4h-2V7h2v6zm4 4h-2v-2h2v2zm0-4h-2V7h2v6z" fill="#0078D4"/></svg>',
        installed=installed,
        needs_download=False,
        description="系统浏览器，无需下载" if installed else "未检测到 Edge 浏览器"
    )


def _detect_chrome() -> BrowserInfo:
    """检测系统是否安装 Google Chrome。"""
    installed = _check_command_exists("google-chrome") or _check_command_exists("chrome")
    if PLATFORM == "darwin":
        installed = Path("/Applications/Google Chrome.app").exists()
    return BrowserInfo(
        channel="chrome",
        name="Google Chrome",
        icon='<svg viewBox="0 0 24 24" fill="none"><circle cx="12" cy="12" r="10" fill="#4285F4"/><circle cx="12" cy="12" r="4" fill="white"/><path d="M12 2a10 10 0 0 1 10 10h-6a4 4 0 0 0-4-4V2z" fill="#EA4335"/><path d="M22 12a10 10 0 0 1-10 10v-6a4 4 0 0 0 4-4h6z" fill="#FBBC05"/><path d="M12 22a10 10 0 0 1-10-10h6a4 4 0 0 0 4 4v6z" fill="#34A853"/><path d="M2 12a10 10 0 0 1 10-10v6a4 4 0 0 0-4 4H2z" fill="#4285F4"/></svg>',
        installed=installed,
        needs_download=False,
        description="系统浏览器，无需下载" if installed else "未检测到 Chrome 浏览器"
    )


def _detect_firefox() -> BrowserInfo:
    """检测系统是否安装 Firefox。"""
    installed = _check_command_exists("firefox")
    if PLATFORM == "darwin":
        installed = Path("/Applications/Firefox.app").exists()
    return BrowserInfo(
        channel="firefox",
        name="Firefox",
        icon='<svg viewBox="0 0 24 24" fill="none"><circle cx="12" cy="12" r="10" fill="#FF7139"/><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm0 18c-4.42 0-8-3.58-8-8s3.58-8 8-8 8 3.58 8 8-3.58 8-8 8z" fill="white"/><path d="M12 6c-3.31 0-6 2.69-6 6s2.69 6 6 6 6-2.69 6-6-2.69-6-6-6zm0 10c-2.21 0-4-1.79-4-4s1.79-4 4-4 4 1.79 4 4-1.79 4-4 4z" fill="white"/></svg>',
        installed=installed,
        needs_download=not installed,
        description="系统浏览器，无需下载" if installed else "需下载 Firefox 驱动"
    )


def _detect_custom() -> BrowserInfo:
    """自定义路径选项（不检测，由用户自行确保）。"""
    return BrowserInfo(
        channel="custom",
        name="自定义路径",
        icon='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5"/><path d="M2 12l10 5 10-5"/></svg>',
        installed=True,  # 始终可用，由用户自行确保路径有效
        needs_download=False,
        description="手动指定浏览器可执行文件路径"
    )


def _has_playwright_chromium() -> bool:
    """检查 Playwright Chromium 是否已下载。"""
    if PLATFORM == "windows":
        cache_dir = Path.home() / "AppData" / "Local" / "ms-playwright"
    elif PLATFORM == "darwin":
        cache_dir = Path.home() / "Library" / "Caches" / "ms-playwright"
    else:
        cache_dir = Path.home() / ".cache" / "ms-playwright"

    if not cache_dir.exists():
        return False

    for d in cache_dir.glob("chromium-*"):
        if not d.is_dir():
            continue
        for candidate in [
            d / "chrome-win64" / "chrome.exe",
            d / "chrome-win" / "chrome.exe",
            d / "chrome-linux" / "chrome",
            d / "chrome-mac" / "Chromium.app" / "Contents" / "MacOS" / "Chromium",
        ]:
            if candidate.exists():
                return True
    return False


def _check_command_exists(command: str) -> bool:
    """检查命令是否存在。"""
    return shutil.which(command) is not None
