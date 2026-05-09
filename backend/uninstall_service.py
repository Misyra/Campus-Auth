"""卸载服务 — 检测和清理外部残留。"""

from __future__ import annotations

import os
import shutil
import signal
import sys
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
USER_DATA_DIR = Path.home() / ".campus_network_auth"
PID_FILE = USER_DATA_DIR / "campus_network_auth.pid"

PLATFORM = sys.platform


@dataclass
class CleanupItem:
    key: str
    label: str
    exists: bool
    path: str = ""
    size_mb: float = 0.0


@dataclass
class CleanupResult:
    key: str
    label: str
    success: bool
    message: str


def detect() -> list[CleanupItem]:
    """检测可清理项目。"""
    items: list[CleanupItem] = []

    # 进程
    pid = _check_running_pid()
    if pid:
        items.append(
            CleanupItem("process", f"运行中的进程 (PID: {pid})", True, str(pid))
        )
    else:
        items.append(CleanupItem("process", "运行中的进程", False))

    # 开机自启
    autostart = _check_autostart()
    if autostart.get("enabled"):
        loc = autostart.get("location", "")
        items.append(CleanupItem("autostart", "开机自启", True, loc))
    else:
        items.append(CleanupItem("autostart", "开机自启动", False))

    # 用户数据
    if USER_DATA_DIR.exists():
        items.append(CleanupItem("userdata", "用户数据", True, str(USER_DATA_DIR)))
    else:
        items.append(CleanupItem("userdata", "用户数据", False))

    # Playwright 缓存
    pw_cache = _playwright_cache_dir()
    if pw_cache and pw_cache.exists():
        size = _dir_size_mb(pw_cache)
        items.append(
            CleanupItem(
                "playwright", "Playwright 浏览器缓存", True, str(pw_cache), size
            )
        )
    else:
        items.append(CleanupItem("playwright", "Playwright 浏览器缓存", False))

    return items


def perform(keys: list[str]) -> list[CleanupResult]:
    """执行清理。keys 为要清理的项目 key 列表。"""
    results: list[CleanupResult] = []

    if "process" in keys:
        pid = _check_running_pid()
        if pid:
            ok, msg = _stop_process(pid)
            results.append(CleanupResult("process", "停止进程", ok, msg))
        else:
            results.append(CleanupResult("process", "停止进程", True, "进程未在运行"))

    if "autostart" in keys:
        ok, msg = _remove_autostart()
        results.append(CleanupResult("autostart", "移除开机自启", ok, msg))

    if "userdata" in keys:
        ok, msg = _remove_user_data()
        results.append(CleanupResult("userdata", "删除用户数据", ok, msg))

    if "playwright" in keys:
        pw_cache = _playwright_cache_dir()
        if pw_cache:
            ok, msg = _remove_playwright_cache(pw_cache)
            results.append(CleanupResult("playwright", "删除 Playwright 缓存", ok, msg))

    return results


# ==================== 内部实现 ====================


def _check_running_pid() -> int | None:
    if not PID_FILE.exists():
        return None
    try:
        pid = int(PID_FILE.read_text(encoding="utf-8").strip())
        if pid <= 0:
            return None
        os.kill(pid, 0)
        return pid
    except (ValueError, ProcessLookupError, PermissionError, OSError):
        return None


def _check_autostart() -> dict:
    try:
        sys.path.insert(0, str(PROJECT_ROOT))
        from backend.autostart_service import AutoStartService

        svc = AutoStartService(PROJECT_ROOT)
        return svc.status()
    except Exception:
        return {
            "enabled": False,
            "platform": PLATFORM,
            "method": "unknown",
            "location": "",
        }


def _stop_process(pid: int) -> tuple[bool, str]:
    try:
        if PLATFORM == "win32":
            os.system(f"taskkill /F /PID {pid} /T >nul 2>&1")
        else:
            os.kill(pid, signal.SIGTERM)
            import time
            time.sleep(0.5)
            try:
                os.kill(pid, 0)
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        return True, f"已停止进程 PID={pid}"
    except Exception as exc:
        return False, f"停止进程失败: {exc}"


def _remove_autostart() -> tuple[bool, str]:
    try:
        sys.path.insert(0, str(PROJECT_ROOT))
        from backend.autostart_service import AutoStartService

        svc = AutoStartService(PROJECT_ROOT)
        return svc.disable()
    except Exception as exc:
        return False, f"移除开机自启失败: {exc}"


def _remove_user_data() -> tuple[bool, str]:
    if not USER_DATA_DIR.exists():
        return True, "用户数据目录不存在，跳过"
    try:
        shutil.rmtree(USER_DATA_DIR)
        return True, f"已删除 {USER_DATA_DIR}"
    except Exception as exc:
        return False, f"删除用户数据失败: {exc}"


def _playwright_cache_dir() -> Path | None:
    if PLATFORM == "win32":
        return Path.home() / "AppData" / "Local" / "ms-playwright"
    if PLATFORM == "darwin":
        return Path.home() / "Library" / "Caches" / "ms-playwright"
    if PLATFORM == "linux":
        return Path.home() / ".cache" / "ms-playwright"
    return None


def _remove_playwright_cache(cache_dir: Path) -> tuple[bool, str]:
    if not cache_dir.exists():
        return True, "Playwright 缓存不存在，跳过"
    try:
        shutil.rmtree(cache_dir)
        return True, f"已删除 {cache_dir}"
    except Exception as exc:
        return False, f"删除 Playwright 缓存失败: {exc}"


def _dir_size_mb(path: Path) -> float:
    total = 0
    try:
        for f in path.rglob("*"):
            if f.is_file():
                total += f.stat().st_size
    except OSError:
        pass
    return total / (1024 * 1024)
