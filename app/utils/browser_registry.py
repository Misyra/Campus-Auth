"""浏览器注册表 — 检测系统已安装的浏览器。"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from app.utils.logging import get_logger
from app.utils.platform import get_platform

logger = get_logger("browser_registry", source="backend")

PLATFORM = get_platform()

# 图标目录
ICONS_DIR = Path(__file__).parent.parent.parent / "res" / "icons"


def _get_icon_url(filename: str) -> str:
    """获取图标 URL。"""
    return f"/api/icons/{filename}"


@dataclass
class BrowserInfo:
    """浏览器信息。"""

    channel: str          # "playwright" | "msedge" | "chrome" | "firefox" | "custom"
    name: str             # 显示名称
    icon: str             # SVG 图标内容
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
        icon=_get_icon_url("chromium.svg"),
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
        icon=_get_icon_url("edge.svg"),
        installed=installed,
        needs_download=False,
        description="系统浏览器，无需下载" if installed else "未检测到 Edge 浏览器"
    )


def _detect_chrome() -> BrowserInfo:
    """检测系统是否安装 Google Chrome。"""
    installed = _check_command_exists("google-chrome") or _check_command_exists("chrome")
    if PLATFORM == "darwin":
        installed = Path("/Applications/Google Chrome.app").exists()
    elif PLATFORM == "windows":
        # 检查 Windows 标准安装路径
        program_files = [
            Path(os.environ.get("PROGRAMFILES", "C:\\Program Files")),
            Path(os.environ.get("PROGRAMFILES(X86)", "C:\\Program Files (x86)")),
            Path(os.environ.get("LOCALAPPDATA", "")),
        ]
        for base in program_files:
            chrome_path = base / "Google" / "Chrome" / "Application" / "chrome.exe"
            if chrome_path.exists():
                installed = True
                break
    return BrowserInfo(
        channel="chrome",
        name="Google Chrome",
        icon=_get_icon_url("google-chrome.svg"),
        installed=installed,
        needs_download=False,
        description="系统浏览器，无需下载" if installed else "未检测到 Chrome 浏览器"
    )


def _detect_firefox() -> BrowserInfo:
    """检测系统是否安装 Firefox。"""
    installed = _check_command_exists("firefox")
    if PLATFORM == "darwin":
        installed = Path("/Applications/Firefox.app").exists()
    elif PLATFORM == "windows":
        # 检查 Windows 标准安装路径
        program_files = [
            Path(os.environ.get("PROGRAMFILES", "C:\\Program Files")),
            Path(os.environ.get("PROGRAMFILES(X86)", "C:\\Program Files (x86)")),
        ]
        for base in program_files:
            firefox_path = base / "Mozilla Firefox" / "firefox.exe"
            if firefox_path.exists():
                installed = True
                break
    return BrowserInfo(
        channel="firefox",
        name="Firefox",
        icon=_get_icon_url("firefox.svg"),
        installed=installed,
        needs_download=not installed,
        description="系统浏览器，无需下载" if installed else "未安装 Firefox 浏览器"
    )


def _detect_custom() -> BrowserInfo:
    """自定义路径选项（不检测，由用户自行确保）。"""
    return BrowserInfo(
        channel="custom",
        name="自定义浏览器",
        icon=_get_icon_url("custom.svg"),
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
