"""Playwright 引导辅助模块。

当前策略：
- 依赖安装由启动脚本处理（`uv sync`）。
- 此处仅确保 Chromium 浏览器已安装。
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
from collections.abc import Callable
from pathlib import Path

from app.utils.logging import get_logger
from app.utils.platform import CREATE_NO_WINDOW_FLAG, is_macos, is_windows

logger = get_logger("playwright_bootstrap", source="backend")

_BOOTSTRAP_LOCK = threading.Lock()
_BOOTSTRAP_DONE = False
_BOOTSTRAP_SKIPPED = False  # 用户禁用 auto-install，跳过验证


def _candidate_hosts() -> list[str]:
    configured = os.getenv("PLAYWRIGHT_DOWNLOAD_HOST", "").strip()
    hosts: list[str] = []

    if configured:
        hosts.append(configured)

    defaults = [
        "https://npmmirror.com/mirrors/playwright",
        "https://playwright.azureedge.net",
    ]
    for host in defaults:
        if host not in hosts:
            hosts.append(host)
    return hosts


def _is_enabled() -> bool:
    from app.utils import str_to_bool

    return str_to_bool(os.getenv("AUTO_INSTALL_PLAYWRIGHT", "true"))


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    kwargs: dict = {"capture_output": True, "text": True, "check": False}
    if is_windows():
        kwargs["creationflags"] = CREATE_NO_WINDOW_FLAG
    return subprocess.run(cmd, **kwargs)


def _get_browser_channel() -> str | None:
    """从配置文件读取 browser_channel。

    Returns:
        str: 配置的浏览器类型
        None: 配置文件不存在或读取失败
    """
    try:
        import json

        from app.constants import PROJECT_ROOT

        settings_path = PROJECT_ROOT / "config" / "settings.json"
        if settings_path.exists():
            with open(settings_path, encoding="utf-8") as f:
                data = json.load(f)
            channel = data.get("global_settings", {}).get("browser_channel")
            if channel:
                return channel
    except Exception:
        logger.debug("读取 browser_channel 配置失败", exc_info=True)
    return None  # 配置文件不存在或未配置


def _has_browser(channel: str) -> bool:
    """检查指定浏览器是否已安装。"""
    if channel == "playwright":
        return _has_chromium()
    elif channel == "firefox":
        import shutil

        return shutil.which("firefox") is not None
    return False


def _has_chromium() -> bool:
    # 快速路径：直接扫描 ms-playwright 浏览器目录，避免导入 playwright.sync_api
    # （后者会加载 ~15-20MB 的 Python 绑定并启动一个 Playwright 实例）
    _search_locations = []
    # 标准 ms-playwright 缓存目录
    if is_windows():  # Windows 平台
        _search_locations.append(Path.home() / "AppData" / "Local" / "ms-playwright")
    elif is_macos():  # macOS 平台
        _search_locations.append(Path.home() / "Library" / "Caches" / "ms-playwright")
    else:
        _search_locations.append(Path.home() / ".cache" / "ms-playwright")
    # 包内 .local-browsers（部分安装方式）
    try:
        import importlib.util as _ilu

        _spec = _ilu.find_spec("playwright")
        if _spec and _spec.submodule_search_locations:
            _search_locations.append(
                Path(_spec.submodule_search_locations[0])
                / "driver"
                / "package"
                / ".local-browsers"
            )
    except Exception:
        logger.debug("查找 playwright 浏览器路径失败", exc_info=True)

    for base_dir in _search_locations:
        if not base_dir.is_dir():
            continue
        for d in base_dir.glob("chromium-*"):
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

    # 回退：使用 playwright.sync_api（较慢，~15-20MB 开销）
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            exe = p.chromium.executable_path
        return bool(exe and Path(exe).exists())
    except Exception:
        return False


def ensure_playwright_ready(log: Callable[[str], None] | None = None) -> bool:
    """确保 playwright 包可导入且所需浏览器已安装。

    根据配置的 browser_channel 决定下载内容：
    - playwright: 下载 Chromium
    - firefox: 下载 Firefox 驱动
    - msedge/chrome/custom: 跳过下载（使用系统浏览器）
    """
    global _BOOTSTRAP_DONE, _BOOTSTRAP_SKIPPED

    with _BOOTSTRAP_LOCK:
        if _BOOTSTRAP_DONE:
            return True

        if _BOOTSTRAP_SKIPPED:
            return True

        if not _is_enabled():
            _BOOTSTRAP_SKIPPED = True
            if log:
                log("AUTO_INSTALL_PLAYWRIGHT 已禁用，跳过浏览器验证")
            return True

        # 读取配置的 browser_channel
        channel = _get_browser_channel()

        # 配置文件不存在或未配置，跳过下载（首次启动向导会配置）
        if channel is None:
            _BOOTSTRAP_DONE = True
            if log:
                log("未配置浏览器类型，跳过下载（首次启动请完成向导配置）")
            return True

        if log:
            log(f"配置的浏览器类型: {channel}")

        # 系统浏览器不需要下载
        if channel in ("msedge", "chrome", "custom"):
            _BOOTSTRAP_DONE = True
            if log:
                log(f"使用系统浏览器 ({channel})，跳过下载")
            return True

        # 需要下载的浏览器：playwright 或 firefox
        VALID_CHANNELS = ("playwright", "msedge", "chrome", "firefox", "custom")
        if channel not in VALID_CHANNELS:
            logger.warning("无效的 browser_channel: {}，跳过下载", channel)
            _BOOTSTRAP_DONE = True
            return True
        install_target = "chromium" if channel == "playwright" else "firefox"

        # 快速路径：检查是否已安装
        try:
            if _has_browser(channel):
                _BOOTSTRAP_DONE = True
                return True
        except Exception:
            logger.debug("快速路径浏览器检查失败，回退到慢速路径", exc_info=True)

        # 慢速路径：需要导入 playwright 来安装
        try:
            import playwright  # noqa: F401
        except Exception as exc:
            if log:
                log(f"未检测到 playwright 包: {exc}")
                log("请先运行启动脚本执行 uv sync")
            return False

        try:
            if log:
                log(f"正在安装 Playwright {install_target} 浏览器...")

            for host in _candidate_hosts():
                # NOTE: os.environ 在此处修改是安全的，因为：
                # 1. ensure_playwright_ready() 仅在服务启动时由主线程调用一次
                # 2. 此时尚无其他工作线程读取 os.environ
                # 3. _BOOTSTRAP_LOCK + _BOOTSTRAP_DONE 防止并发/重复执行
                os.environ["PLAYWRIGHT_DOWNLOAD_HOST"] = host
                if log:
                    log(f"尝试下载源: {host}")

                result = _run(
                    [sys.executable, "-m", "playwright", "install", install_target]
                )
                if result.returncode == 0:
                    _BOOTSTRAP_DONE = True
                    if log:
                        log(f"Playwright {install_target} 下载完成")
                    return True

                if log:
                    msg = (result.stderr or result.stdout or "").strip()
                    log(f"下载源失败 ({host}): {msg}")

            return False
        except Exception as exc:
            if log:
                log(f"Playwright 初始化失败: {exc}")
            return False
