from __future__ import annotations

import re
import threading
import time
from collections.abc import Callable
from pathlib import Path

from app.network.detect import detect_gateway_ip, detect_wifi_ssid
from app.schemas import AuthProfile, ProfilesData
from app.utils.crypto import save_password_field
from app.utils.files import atomic_write
from app.utils.logging import get_logger

profile_logger = get_logger("profile_service", source="backend")


class ProfileService:
    """配置方案管理服务 — 读写 config/settings.json"""

    def __init__(self, project_root: Path):
        self.project_root = project_root
        self._config_dir = project_root / "config"
        self._settings_path = self._config_dir / "settings.json"
        self._lock = threading.Lock()

    def _ensure_dirs(self) -> None:
        """确保 config/ 目录存在"""
        self._config_dir.mkdir(parents=True, exist_ok=True)

    def _load_unsafe(self) -> ProfilesData:
        """加载配置（不加锁，由调用者持有锁）。

        不缓存配置：
        1. settings.json 很小（<10KB），每次读盘开销可忽略
        2. 多实例场景下缓存一致性成本高于收益
        """
        self._ensure_dirs()

        if not self._settings_path.exists():
            return ProfilesData()

        try:
            raw = self._settings_path.read_text(encoding="utf-8")
            return ProfilesData.model_validate_json(raw)
        except Exception:
            profile_logger.exception("加载 settings.json 失败")
            corrupt_name = f"settings.corrupt.{int(time.time())}.json"
            corrupt_path = self._config_dir / corrupt_name
            try:
                self._settings_path.rename(corrupt_path)
                profile_logger.info("已备份损坏文件到: {}", corrupt_path)
            except (FileNotFoundError, OSError):
                pass
            return ProfilesData()

    def _save_unsafe(self, data: ProfilesData) -> None:
        """原子写入配置（不加锁，由调用者持有锁）"""
        self._ensure_dirs()
        settings_content = data.model_dump_json(indent=2)
        atomic_write(self._settings_path, settings_content)
        profile_logger.info("配置已保存")

    def load(self) -> ProfilesData:
        """加载配置，不存在则返回空结构"""
        with self._lock:
            return self._load_unsafe()

    def save(self, data: ProfilesData) -> None:
        """原子写入配置"""
        with self._lock:
            self._save_unsafe(data)

    def update(self, func: Callable[[ProfilesData], None]) -> None:
        """原子化读-改-写操作。

        持锁执行 load → func(data) → save，确保并发安全。
        func 在锁内调用，应快速返回，不要做 I/O 或网络操作。
        """
        with self._lock:
            data = self._load_unsafe()
            func(data)
            self._save_unsafe(data)

    def get_active_profile(self) -> AuthProfile:
        """获取当前活动方案的设置（返回值由 load() 深拷贝保护，无需再次拷贝）"""
        data = self.load()
        profile_id = data.active_profile
        profile = data.profiles.get(profile_id)
        if profile:
            return profile
        # 如果活动方案不存在，返回第一个或默认
        if data.profiles:
            first_id = next(iter(data.profiles))
            return data.profiles[first_id]
        return AuthProfile()

    def get_active_profile_id(self) -> str:
        """获取当前活动方案 ID"""
        data = self.load()
        return data.active_profile

    def set_active_profile(self, profile_id: str) -> tuple[bool, str]:
        """设置活动方案"""
        with self._lock:
            data = self._load_unsafe()
            if profile_id not in data.profiles:
                return False, f"方案 '{profile_id}' 不存在"

            profile_name = data.profiles[profile_id].name
            data.active_profile = profile_id
            self._save_unsafe(data)
        profile_logger.info("活动方案已切换: {}", profile_id)
        return True, f"已切换到方案: {profile_name}"

    def save_profile(
        self, profile_id: str, settings: AuthProfile
    ) -> tuple[bool, str]:
        """创建或更新一个方案"""
        if not profile_id or not profile_id.strip():
            return False, "方案 ID 不能为空"

        profile_id = profile_id.strip()
        if not re.fullmatch(r"[a-zA-Z0-9_]+", profile_id):
            return False, "方案 ID 只能包含字母、数字和下划线"

        with self._lock:
            data = self._load_unsafe()
            existing = data.profiles.get(profile_id)
            settings.password = save_password_field(
                settings.password or "",
                existing.password if existing else "",
            )
            data.profiles[profile_id] = settings

            if len(data.profiles) == 1:
                data.active_profile = profile_id

            self._save_unsafe(data)
        profile_logger.info("方案已保存: {} ({})", profile_id, settings.name)
        return True, f"方案 '{settings.name}' 保存成功"

    def delete_profile(self, profile_id: str) -> tuple[bool, str]:
        """删除一个方案"""
        if profile_id == "default":
            return False, "不能删除默认方案"

        with self._lock:
            data = self._load_unsafe()
            if profile_id not in data.profiles:
                return False, f"方案 '{profile_id}' 不存在"

            if len(data.profiles) <= 1:
                return False, "至少需要保留一个方案"

            del data.profiles[profile_id]

            if data.active_profile == profile_id:
                data.active_profile = next(iter(data.profiles))

            self._save_unsafe(data)
        profile_logger.info("方案已删除: {}", profile_id)
        return True, "方案删除成功"

    def detect_matching_profile(self, data: ProfilesData | None = None) -> str | None:
        """检测当前网络环境并返回匹配的方案 ID，无匹配返回 None。

        匹配优先级：网关 IP > SSID（同一次遍历中先检查网关再检查 SSID）。

        Args:
            data: 预加载的配置数据。为 None 时内部调用 load()。
        """
        gateway = detect_gateway_ip()
        ssid = detect_wifi_ssid()

        profile_logger.debug("检测到网关: {}, SSID: {}", gateway, ssid)

        if data is None:
            data = self.load()
        ssid_match_id: str | None = None

        for profile_id, settings in data.profiles.items():
            # 优先匹配网关 IP（命中即返回）
            match_ip = (settings.match_gateway_ip or "").strip()
            if gateway and match_ip and match_ip == gateway:
                profile_logger.info(
                    "网关 {} 匹配方案: {} ({})",
                    gateway,
                    profile_id,
                    settings.name,
                )
                return profile_id

            # 记录首个 SSID 匹配（优先级低于网关）
            if ssid_match_id is None:
                match_ssid = (settings.match_ssid or "").strip()
                if ssid and match_ssid and match_ssid == ssid:
                    ssid_match_id = profile_id

        # SSID 匹配（延迟返回，确保网关优先）
        if ssid_match_id is not None:
            profile_logger.info(
                "SSID '{}' 匹配方案: {} ({})",
                ssid,
                ssid_match_id,
                data.profiles[ssid_match_id].name,
            )

        return ssid_match_id

    def set_auto_switch(self, enabled: bool) -> None:
        """设置自动切换开关"""
        with self._lock:
            data = self._load_unsafe()
            data.auto_switch = enabled
            self._save_unsafe(data)
        profile_logger.info("自动切换: {}", "开启" if enabled else "关闭")


def create_profile_service(project_root: Path | None = None) -> ProfileService:
    """ProfileService 工厂函数 — 统一各入口点的创建方式。

    每次调用返回新实例（非单例）。project_root 默认使用项目根目录
    （即 profile_service.py 向上三级: app/services/profile_service.py → 项目根）。

    Args:
        project_root: 项目根目录。None 时自动推导。

    Returns:
        新创建的 ProfileService 实例。
    """
    if project_root is None:
        project_root = Path(__file__).parent.parent.parent.resolve()
    return ProfileService(project_root)
