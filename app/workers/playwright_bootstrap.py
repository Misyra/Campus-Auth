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

from app.utils.logging import get_logger
from app.utils.platform import CREATE_NO_WINDOW_FLAG, is_windows

logger = get_logger("playwright_bootstrap", source="backend")

BOOTSTRAP_TIMEOUT = 300

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


def _run(cmd: list[str], env: dict | None = None) -> subprocess.CompletedProcess[str]:
    kwargs: dict = {"capture_output": True, "text": True, "check": False, "timeout": BOOTSTRAP_TIMEOUT}
    if is_windows():
        kwargs["creationflags"] = CREATE_NO_WINDOW_FLAG
    if env is not None:
        kwargs["env"] = env
    return subprocess.run(cmd, **kwargs)


def _get_browser_channel() -> str | None:
    """从配置文件读取 browser_channel。

    Returns:
        str: 配置的浏览器类型
        None: 配置文件不存在或读取失败
    """
    try:
        from app.services.profile_service import create_profile_service

        _ps = create_profile_service()
        _data = _ps.load()
        channel = _data.global_config.browser.browser_channel
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
    """检查 Playwright Chromium 是否已下载。"""
    from app.utils.browser_registry import has_playwright_chromium

    return has_playwright_chromium()


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
        VALID_CHANNELS = ("playwright", "firefox")
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

            base_env = os.environ.copy()
            for host in _candidate_hosts():
                env = base_env.copy()
                env["PLAYWRIGHT_DOWNLOAD_HOST"] = host
                if log:
                    log(f"尝试下载源: {host}")

                result = _run(
                    [sys.executable, "-m", "playwright", "install", install_target],
                    env=env,
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
