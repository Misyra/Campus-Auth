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
from typing import Callable


_BOOTSTRAP_LOCK = threading.Lock()
_BOOTSTRAP_DONE = False


def _is_enabled() -> bool:
    value = os.getenv("AUTO_INSTALL_PLAYWRIGHT", "true").strip().lower()
    return value in {"1", "true", "yes", "on"}


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=False,
    )


def _has_chromium() -> bool:
    result = _run([sys.executable, "-m", "playwright", "install", "--list"])
    output = f"{result.stdout}\n{result.stderr}".lower()
    return result.returncode == 0 and "chromium-" in output


def ensure_playwright_ready(log: Callable[[str], None] | None = None) -> bool:
    """Ensure playwright package is importable and chromium is installed."""
    global _BOOTSTRAP_DONE

    with _BOOTSTRAP_LOCK:
        if _BOOTSTRAP_DONE:
            return True

        if not _is_enabled():
            _BOOTSTRAP_DONE = True
            return True

        os.environ.setdefault(
            "PLAYWRIGHT_DOWNLOAD_HOST",
            "https://npmmirror.com/mirrors/playwright",
        )

        try:
            import playwright  # noqa: F401
        except Exception as exc:
            if log:
                log(f"未检测到 playwright 包: {exc}")
                log("请先运行启动脚本执行 uv sync")
            return False

        try:
            if _has_chromium():
                _BOOTSTRAP_DONE = True
                return True

            if log:
                log("正在安装 Playwright Chromium 浏览器内核...")

            result = _run([sys.executable, "-m", "playwright", "install", "chromium"])
            if result.returncode == 0:
                _BOOTSTRAP_DONE = True
                if log:
                    log("Playwright Chromium 下载完成")
                return True

            if log:
                msg = (result.stderr or result.stdout or "").strip()
                log(f"Playwright Chromium 下载失败: {msg}")
            return False
        except Exception as exc:
            if log:
                log(f"Playwright 初始化失败: {exc}")
            return False


def ensure_chromium_installed(log: Callable[[str], None] | None = None) -> bool:
    return ensure_playwright_ready(log)
