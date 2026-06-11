"""卸载服务 — 检测和清理外部残留。"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from app.constants import AUTH_DATA_DIR, PROJECT_ROOT
from app.utils.platform_utils import get_platform

USER_DATA_DIR = AUTH_DATA_DIR

PLATFORM = (
    get_platform()
)  # 使用 platform_utils 获取平台标识（"windows"/"darwin"/"linux"）


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

    if "autostart" in keys:
        success, message = _remove_autostart()
        results.append(CleanupResult("autostart", "移除开机自启", success, message))

    if "userdata" in keys:
        success, message = _remove_user_data()
        results.append(CleanupResult("userdata", "删除用户数据", success, message))

    if "playwright" in keys:
        pw_cache = _playwright_cache_dir()
        if pw_cache:
            success, message = _remove_playwright_cache(pw_cache)
            results.append(CleanupResult("playwright", "删除 Playwright 缓存", success, message))

    return results


# ==================== 内部实现 ====================


def _check_autostart() -> dict:
    try:
        from app.services.autostart import AutoStartService

        autostart_service = AutoStartService(PROJECT_ROOT)
        return autostart_service.status()
    except Exception:
        return {
            "enabled": False,
            "platform": PLATFORM,
            "method": "unknown",
            "location": "",
        }


def _remove_autostart() -> tuple[bool, str]:
    try:
        from app.services.autostart import AutoStartService

        autostart_service = AutoStartService(PROJECT_ROOT)
        return autostart_service.disable()
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
    if PLATFORM == "windows":  # get_platform() 返回 "windows"
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
        for file_path in path.rglob("*"):
            if file_path.is_file():
                total += file_path.stat().st_size
    except OSError:
        pass
    return total / (1024 * 1024)
