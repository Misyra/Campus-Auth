"""Playwright bootstrap helpers.

Current strategy:
- Dependency installation is handled by startup scripts (`uv sync`).
- Here we only ensure Chromium browser is present for Playwright.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Callable

from dotenv import load_dotenv

_BOOTSTRAP_LOCK = threading.Lock()
_BOOTSTRAP_DONE = False


def _load_env_file() -> None:
    env_file = os.getenv("Campus-Auth_ENV_FILE", "").strip()
    if env_file:
        load_dotenv(Path(env_file), override=False)
        return

    cwd_env = Path.cwd() / ".env"
    if cwd_env.exists():
        load_dotenv(cwd_env, override=False)


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
    from src.utils import str_to_bool
    return str_to_bool(os.getenv("AUTO_INSTALL_PLAYWRIGHT", "true"))


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=False,
    )


def _has_chromium() -> bool:
    # 快速路径：直接扫描 ms-playwright 浏览器目录，避免导入 playwright.sync_api
    # （后者会加载 ~15-20MB 的 Python 绑定并启动一个 Playwright 实例）
    import glob as _glob

    _search_locations = []
    # 标准 ms-playwright 缓存目录
    if sys.platform == "win32":
        _search_locations.append(Path.home() / "AppData" / "Local" / "ms-playwright")
    elif sys.platform == "darwin":
        _search_locations.append(Path.home() / "Library" / "Caches" / "ms-playwright")
    else:
        _search_locations.append(Path.home() / ".cache" / "ms-playwright")
    # 包内 .local-browsers（部分安装方式）
    try:
        import importlib.util as _ilu
        _spec = _ilu.find_spec("playwright")
        if _spec and _spec.submodule_search_locations:
            _search_locations.append(
                Path(_spec.submodule_search_locations[0]) / "driver" / "package" / ".local-browsers"
            )
    except Exception:
        pass

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
    """Ensure playwright package is importable and chromium is installed."""
    global _BOOTSTRAP_DONE

    with _BOOTSTRAP_LOCK:
        if _BOOTSTRAP_DONE:
            return True

        if not _is_enabled():
            _BOOTSTRAP_DONE = True
            return True

        _load_env_file()

        # 快速路径：直接检查 chromium 是否已安装，避免导入 playwright（~15-20MB）
        try:
            if _has_chromium():
                _BOOTSTRAP_DONE = True
                return True
        except Exception:
            pass

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
