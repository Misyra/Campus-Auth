"""卸载服务 — 检测和清理外部残留。"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from app.constants import AUTH_DATA_DIR, PROJECT_ROOT
from app.utils.files import dir_size_mb
from app.utils.logging import get_logger
from app.utils.platform import get_platform, get_playwright_cache_dir

logger = get_logger("uninstall", source="backend")

USER_DATA_DIR = AUTH_DATA_DIR

PLATFORM = get_platform()  # 使用 platform 获取平台标识（"windows"/"darwin"/"linux"）


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
    pw_cache = get_playwright_cache_dir()
    if pw_cache and pw_cache.exists():
        size = dir_size_mb(pw_cache)
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
        pw_cache = get_playwright_cache_dir()
        if pw_cache:
            success, message = _remove_playwright_cache(pw_cache)
            results.append(
                CleanupResult("playwright", "删除 Playwright 缓存", success, message)
            )

    return results


# ==================== 内部实现 ====================


_autostart_service = None


def _get_autostart_service():
    global _autostart_service
    if _autostart_service is None:
        from app.services.autostart import AutoStartService
        _autostart_service = AutoStartService(PROJECT_ROOT)
    return _autostart_service


def _reset_autostart_service():
    """重置单例（仅用于测试）。"""
    global _autostart_service
    _autostart_service = None


def _check_autostart() -> dict:
    try:
        return _get_autostart_service().status()
    except Exception:
        return {
            "enabled": False,
            "platform": PLATFORM,
            "method": "unknown",
            "location": "",
        }


def _remove_autostart() -> tuple[bool, str]:
    try:
        return _get_autostart_service().disable()
    except Exception as exc:
        return False, f"移除开机自启失败: {exc}"


def _remove_user_data() -> tuple[bool, str]:
    if not USER_DATA_DIR.exists():
        return True, "用户数据目录不存在，跳过"

    # 路径校验：确保删除的是预期的用户数据目录
    expected_name = ".campus_network_auth"
    if USER_DATA_DIR.name != expected_name:
        return False, f"安全检查失败：目录名不是 {expected_name}"

    try:
        file_count = sum(1 for _ in USER_DATA_DIR.rglob("*") if _.is_file())
        logger.warning("即将删除用户数据目录: {} ({} 个文件)", USER_DATA_DIR, file_count)
        shutil.rmtree(USER_DATA_DIR)
        return True, f"已删除 {USER_DATA_DIR}"
    except Exception as exc:
        return False, f"删除用户数据失败: {exc}"


def _remove_playwright_cache(cache_dir: Path) -> tuple[bool, str]:
    if not cache_dir.exists():
        return True, "Playwright 缓存不存在，跳过"
    try:
        shutil.rmtree(cache_dir)
        return True, f"已删除 {cache_dir}"
    except Exception as exc:
        return False, f"删除 Playwright 缓存失败: {exc}"

