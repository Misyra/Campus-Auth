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

from app.utils.logging import get_logger
from app.utils.platform_utils import is_windows, is_macos, CREATE_NO_WINDOW_FLAG
from pathlib import Path
from typing import Callable

logger = get_logger("playwright_bootstrap", side="BACKEND")

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
    """确保 playwright 包可导入且 Chromium 已安装。"""
    global _BOOTSTRAP_DONE, _BOOTSTRAP_SKIPPED

    with _BOOTSTRAP_LOCK:
        if _BOOTSTRAP_DONE:
            return True

        if _BOOTSTRAP_SKIPPED:
            return True

        if not _is_enabled():
            _BOOTSTRAP_SKIPPED = True
            if log:
                log("AUTO_INSTALL_PLAYWRIGHT 已禁用，跳过 Chromium 验证")
            return True

        # 快速路径：直接检查 chromium 是否已安装，避免导入 playwright（~15-20MB）
        try:
            if _has_chromium():
                _BOOTSTRAP_DONE = True
                return True
        except Exception:
            logger.debug("快速路径 Chromium 检查失败，回退到慢速路径", exc_info=True)

        # 慢速路径：chromium 未找到，需要导入 playwright 来安装
        try:
            import playwright  # noqa: F401
        except Exception as exc:
            if log:
                log(f"未检测到 playwright 包: {exc}")
                log("请先运行启动脚本执行 uv sync")
            return False

        try:
            if log:
                log("正在安装 Playwright Chromium 浏览器内核...")

            for host in _candidate_hosts():
                # NOTE: os.environ 在此处修改是安全的，因为：
                # 1. ensure_playwright_ready() 仅在服务启动时由主线程调用一次
                # 2. 此时尚无其他工作线程读取 os.environ
                # 3. _BOOTSTRAP_LOCK + _BOOTSTRAP_DONE 防止并发/重复执行
                os.environ["PLAYWRIGHT_DOWNLOAD_HOST"] = host
                if log:
                    log(f"尝试下载源: {host}")

                result = _run(
                    [sys.executable, "-m", "playwright", "install", "chromium"]
                )
                if result.returncode == 0:
                    _BOOTSTRAP_DONE = True
                    if log:
                        log("Playwright Chromium 下载完成")
                    return True

                if log:
                    msg = (result.stderr or result.stdout or "").strip()
                    log(f"下载源失败 ({host}): {msg}")

            return False
        except Exception as exc:
            if log:
                log(f"Playwright 初始化失败: {exc}")
            return False


def is_bootstrap_skipped() -> bool:
    """检查 bootstrap 是否被用户禁用（跳过验证）。"""
    return _BOOTSTRAP_SKIPPED


def is_bootstrap_done() -> bool:
    """检查 bootstrap 是否已完成验证。"""
    return _BOOTSTRAP_DONE
