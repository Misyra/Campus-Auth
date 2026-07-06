"""浏览器注册表 — 检测系统已安装的浏览器。"""

from __future__ import annotations

import os
import platform
import shutil
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from app.utils.logging import get_logger
from app.utils.platform import get_platform, get_playwright_cache_dir

logger = get_logger("browser_registry", source="backend")

PLATFORM = get_platform()


def _get_icon_url(filename: str) -> str:
    """获取图标 URL。"""
    return f"/api/icons/{filename}"


@dataclass
class BrowserInfo:
    """浏览器信息。"""

    channel: str  # "playwright" | "msedge" | "chrome" | "firefox" | "custom"
    name: str  # 显示名称
    icon: str  # SVG 图标内容
    installed: bool  # 系统是否已安装
    needs_download: bool  # 是否需要下载驱动
    description: str  # 状态描述


# detect_browsers TTL 缓存（30 秒）
_DETECT_CACHE: list[BrowserInfo] | None = None
_DETECT_CACHE_TIME: float = 0.0
_DETECT_CACHE_TTL: float = 30.0
_DETECT_CACHE_LOCK = threading.Lock()


def detect_browsers() -> list[BrowserInfo]:
    """检测系统已安装的浏览器。

    仅在向导和设置页面调用，启动时直接使用配置的 channel。
    带 30 秒 TTL 缓存，避免频繁文件系统操作。
    """
    global _DETECT_CACHE, _DETECT_CACHE_TIME
    now = time.monotonic()
    with _DETECT_CACHE_LOCK:
        if _DETECT_CACHE is not None and (now - _DETECT_CACHE_TIME) < _DETECT_CACHE_TTL:
            return _DETECT_CACHE
        browsers = [
            _detect_playwright_chromium(),
            _detect_edge(),
            _detect_chrome(),
            _detect_firefox(),
            _detect_custom(),
        ]
        _DETECT_CACHE = browsers
        _DETECT_CACHE_TIME = now
    return browsers


def _detect_playwright_chromium() -> BrowserInfo:
    """检测 Playwright Chromium 是否已下载。"""
    installed = has_playwright_chromium()
    return BrowserInfo(
        channel="playwright",
        name="Playwright Chromium",
        icon=_get_icon_url("chromium.svg"),
        installed=installed,
        needs_download=not installed,
        description="推荐选项，内置浏览器" if installed else "需下载约 150MB",
    )


def _edge_path() -> Path | None:
    """返回 Windows 上 Edge 可执行文件路径，不存在则返回 None。"""
    candidates = [
        Path(os.environ.get("PROGRAMFILES(X86)", ""))
        / "Microsoft"
        / "Edge"
        / "Application"
        / "msedge.exe",
        Path(os.environ.get("PROGRAMFILES", ""))
        / "Microsoft"
        / "Edge"
        / "Application"
        / "msedge.exe",
    ]
    for c in candidates:
        if c.exists():
            return c
    return None


def _detect_edge() -> BrowserInfo:
    """检测系统是否安装 Microsoft Edge。"""
    installed = _check_command_exists("microsoft-edge") or _check_command_exists(
        "msedge"
    )
    if PLATFORM == "windows":
        installed = installed or _edge_path() is not None
    elif PLATFORM == "darwin":
        installed = installed or Path("/Applications/Microsoft Edge.app").exists()
    return BrowserInfo(
        channel="msedge",
        name="Microsoft Edge",
        icon=_get_icon_url("edge.svg"),
        installed=installed,
        needs_download=False,
        description="系统浏览器，无需下载" if installed else "未检测到 Edge 浏览器",
    )


def _detect_chrome() -> BrowserInfo:
    """检测系统是否安装 Google Chrome。"""
    installed = any(
        _check_command_exists(cmd)
        for cmd in (
            "google-chrome",
            "google-chrome-stable",
            "chrome",
            "chromium",
            "chromium-browser",
        )
    )
    if PLATFORM == "darwin":
        installed = installed or Path("/Applications/Google Chrome.app").exists()
    elif PLATFORM == "windows":
        # 检查 Windows 标准安装路径
        program_files = [
            Path(os.environ.get("PROGRAMFILES", "C:\\Program Files")),
            Path(os.environ.get("PROGRAMFILES(X86)", "C:\\Program Files (x86)")),
            *([Path(p)] if (p := os.environ.get("LOCALAPPDATA")) else []),
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
        description="系统浏览器，无需下载" if installed else "未检测到 Chrome 浏览器",
    )


def _detect_firefox() -> BrowserInfo:
    """检测系统是否安装 Firefox。"""
    installed = _check_command_exists("firefox")
    if PLATFORM == "darwin":
        installed = installed or Path("/Applications/Firefox.app").exists()
    elif PLATFORM == "windows":
        # 检查 Windows 标准安装路径
        program_files = [
            Path(os.environ.get("PROGRAMFILES", "C:\\Program Files")),
            Path(os.environ.get("PROGRAMFILES(X86)", "C:\\Program Files (x86)")),
            *([Path(p)] if (p := os.environ.get("LOCALAPPDATA")) else []),
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
        description="系统浏览器，无需下载" if installed else "未安装 Firefox 浏览器",
    )


def _detect_custom() -> BrowserInfo:
    """自定义路径选项（不检测，由用户自行确保）。"""
    return BrowserInfo(
        channel="custom",
        name="自定义浏览器",
        icon=_get_icon_url("custom.svg"),
        installed=True,  # 始终可用，由用户自行确保路径有效
        needs_download=False,
        description="手动指定浏览器可执行文件路径",
    )


def has_playwright_chromium() -> bool:
    """检查 Playwright Chromium 是否已下载（公共函数）。

    扫描标准缓存目录和包内 .local-browsers 备用路径。
    """
    cache_dir = get_playwright_cache_dir()
    if cache_dir is None:
        return False

    search_dirs = [cache_dir]

    # 添加包内 .local-browsers 备用路径
    try:
        import importlib.util as _ilu

        _spec = _ilu.find_spec("playwright")
        if _spec and _spec.submodule_search_locations:
            search_dirs.append(
                Path(_spec.submodule_search_locations[0])
                / "driver"
                / "package"
                / ".local-browsers"
            )
    except Exception:
        pass

    is_arm64 = platform.machine() == "arm64"

    for base_dir in search_dirs:
        if not base_dir.is_dir():
            continue
        for d in base_dir.glob("chromium-*"):
            if not d.is_dir():
                continue
            candidates = [
                d / "chrome-win64" / "chrome.exe",
                d / "chrome-win" / "chrome.exe",
                d / "chrome-linux" / "chrome",
                d / "chrome-mac" / "Chromium.app" / "Contents" / "MacOS" / "Chromium",
            ]
            if is_arm64:
                candidates.extend(
                    [
                        d / "chrome-linux-arm64" / "chrome",
                        d / "chrome-mac-arm64" / "chrome",
                    ]
                )
            for candidate in candidates:
                if candidate.exists():
                    return True
    return False


def _check_command_exists(command: str) -> bool:
    """检查命令是否存在。"""
    return shutil.which(command) is not None
