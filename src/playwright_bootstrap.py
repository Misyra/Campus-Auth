"""Playwright bootstrap utilities.

Used by packaged executables:
- Do not bundle playwright in Nuitka build.
- Install playwright package at first run.
- Install chromium browser at first run.
"""

from __future__ import annotations

import importlib
import os
import site
import sys
import subprocess
import threading
from pathlib import Path
from typing import Callable


_BOOTSTRAP_LOCK = threading.Lock()
_BOOTSTRAP_DONE = False


def _is_enabled() -> bool:
    value = os.getenv("AUTO_INSTALL_PLAYWRIGHT", "true").strip().lower()
    return value in {"1", "true", "yes", "on"}


def _run_playwright_driver(args: list[str]) -> subprocess.CompletedProcess[str]:
    from playwright._impl._driver import compute_driver_executable, get_driver_env

    driver_executable, driver_cli = compute_driver_executable()
    env = get_driver_env()
    return subprocess.run(
        [driver_executable, driver_cli, *args],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def _has_chromium() -> bool:
    result = _run_playwright_driver(["install", "--list"])
    output = f"{result.stdout}\n{result.stderr}".lower()
    return result.returncode == 0 and "chromium-" in output


def _can_import_pip() -> bool:
    try:
        import pip  # noqa: F401

        return True
    except Exception:
        return False


def _load_pip_from_ensurepip_bundled(log: Callable[[str], None] | None = None) -> bool:
    try:
        import ensurepip
    except Exception as exc:
        if log:
            log(f"无法导入 ensurepip: {exc}")
        return False

    bundled_dir = Path(ensurepip.__file__).resolve().parent / "_bundled"
    if not bundled_dir.exists():
        if log:
            log(f"ensurepip bundled 目录不存在: {bundled_dir}")
        return False

    # 直接从 ensurepip 自带 wheel 加载 pip，避免 frozen 环境下 ensurepip.bootstrap 子进程问题。
    wheel_candidates = []
    wheel_candidates.extend(sorted(bundled_dir.glob("pip-*.whl")))
    wheel_candidates.extend(sorted(bundled_dir.glob("setuptools-*.whl")))
    wheel_candidates.extend(sorted(bundled_dir.glob("wheel-*.whl")))

    if not wheel_candidates:
        if log:
            log(f"未找到 ensurepip bundled wheel 文件: {bundled_dir}")
        return False

    for wheel_path in wheel_candidates:
        wheel_str = str(wheel_path)
        if wheel_str not in sys.path:
            sys.path.insert(0, wheel_str)

    importlib.invalidate_caches()
    if _can_import_pip():
        if log:
            log("已从 ensurepip._bundled 加载 pip 组件")
        return True

    if log:
        log("从 ensurepip._bundled 加载 pip 失败")
    return False


def _ensure_playwright_package(log: Callable[[str], None] | None = None) -> bool:
    user_site = site.getusersitepackages()
    if user_site and user_site not in sys.path:
        sys.path.insert(0, user_site)

    try:
        import playwright  # noqa: F401

        return True
    except Exception:
        pass

    try:
        if not _can_import_pip():
            if log:
                log("检测到未安装 pip，正在从 ensurepip bundled 组件初始化...")

            if not _load_pip_from_ensurepip_bundled(log):
                # 兜底再尝试 ensurepip.bootstrap；在部分环境可成功。
                try:
                    import ensurepip

                    if log:
                        log("正在尝试 ensurepip.bootstrap 方式初始化 pip...")
                    ensurepip.bootstrap(upgrade=True, user=True)
                except Exception as exc:
                    if log:
                        log(f"ensurepip.bootstrap 初始化失败: {exc}")
                    return False

            if not _can_import_pip():
                if log:
                    log("pip 初始化完成但仍无法导入 pip 模块")
                return False

        user_site = site.getusersitepackages()
        if user_site and user_site not in sys.path:
            sys.path.insert(0, user_site)

        pip_main = importlib.import_module("pip._internal.cli.main").main
        index_url = os.getenv(
            "PIP_INDEX_URL",
            "https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple",
        )
        if log:
            log("检测到未安装 playwright，正在自动安装...")
        code = pip_main(
            [
                "install",
                "--upgrade",
                "--no-warn-script-location",
                "--disable-pip-version-check",
                "--index-url",
                index_url,
                "--user",
                "playwright>=1.55.0",
            ]
        )
        if int(code) != 0:
            if log:
                log("playwright 包安装失败")
            return False
        importlib.invalidate_caches()
        import playwright  # noqa: F401

        if log:
            log("playwright 包安装完成")
        return True
    except Exception as exc:
        if log:
            log(f"playwright 包安装异常: {exc}")
            log("请使用最新打包脚本重建：需包含 ensurepip 及 ensurepip._bundled 数据文件")
        return False


def ensure_playwright_ready(log: Callable[[str], None] | None = None) -> bool:
    """Ensure playwright package + chromium are installed."""
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

        if not _ensure_playwright_package(log):
            return False

        try:
            if _has_chromium():
                _BOOTSTRAP_DONE = True
                return True

            if log:
                log("首次运行，正在自动下载 Playwright Chromium 浏览器内核...")

            result = _run_playwright_driver(["install", "chromium"])
            if result.returncode == 0:
                _BOOTSTRAP_DONE = True
                if log:
                    log("Playwright Chromium 下载完成")
                return True

            if log:
                message = (result.stderr or result.stdout or "").strip()
                log(f"Playwright Chromium 下载失败: {message}")
            return False
        except Exception as exc:
            if log:
                log(f"Playwright 初始化失败: {exc}")
            return False


def ensure_chromium_installed(log: Callable[[str], None] | None = None) -> bool:
    """Backward-compatible alias."""
    return ensure_playwright_ready(log)
