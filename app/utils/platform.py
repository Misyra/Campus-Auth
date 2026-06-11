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
    "get_default_ua",
    "get_platform",
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


# 各平台默认的 Chrome 125 User-Agent 字符串
_WINDOWS_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)
_MACOS_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)
_LINUX_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)


def get_default_ua() -> str:
    """返回当前操作系统对应的默认 Chrome 125 User-Agent 字符串

    对于不受支持平台，统一返回 Linux 版本的 UA。
    """
    platform = get_platform()
    if platform == "windows":
        return _WINDOWS_UA
    if platform == "darwin":
        return _MACOS_UA
    # Linux 及 fallback 平台均使用 Linux UA
    return _LINUX_UA
