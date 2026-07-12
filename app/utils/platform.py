#!/usr/bin/env python3
"""
平台检测工具函数集

提供纯函数式的跨平台检测能力，用于识别当前运行环境（Windows/macOS/Linux），
并在不引入任何副作用的前提下返回平台对应的 User-Agent 字符串。

所有函数均为无状态、无副作用的纯函数，导入模块不会触发 I/O、日志或配置访问。
"""

import subprocess
import sys

# subprocess.CREATE_NO_WINDOW 仅在 Windows 上可用（Python 3.7+）
CREATE_NO_WINDOW_FLAG: int = getattr(subprocess, "CREATE_NO_WINDOW", 0)

__all__ = [
    "CREATE_NO_WINDOW_FLAG",
    "get_platform",
    "get_playwright_cache_dir",
    "is_linux",
    "is_macos",
    "is_windows",
]


def get_platform() -> str:
    """获取当前操作系统标识，返回 ``"windows"`` / ``"darwin"`` / ``"linux"`` 三者之一"""
    if sys.platform == "win32":
        return "windows"
    if sys.platform == "darwin":
        return "darwin"
    # "linux" 或 "linux2"（Python 2 兼容）
    return "linux"


def is_windows() -> bool:
    """当前是否为 Windows 系统"""
    return sys.platform == "win32"


def is_macos() -> bool:
    """当前是否为 macOS 系统"""
    return sys.platform == "darwin"


def is_linux() -> bool:
    """当前是否为 Linux 系统"""
    return sys.platform == "linux"


def get_playwright_cache_dir() -> "Path | None":
    """返回 Playwright 浏览器缓存的标准目录路径。

    各平台路径：
    - Windows: ~/AppData/Local/ms-playwright
    - macOS:   ~/Library/Caches/ms-playwright
    - Linux:   ~/.cache/ms-playwright

    Returns:
        平台对应的缓存目录 Path，不支持的平台返回 None。
    """
    from pathlib import Path

    platform = get_platform()
    if platform == "windows":
        return Path.home() / "AppData" / "Local" / "ms-playwright"
    if platform == "darwin":
        return Path.home() / "Library" / "Caches" / "ms-playwright"
    if platform == "linux":
        return Path.home() / ".cache" / "ms-playwright"
    return None
