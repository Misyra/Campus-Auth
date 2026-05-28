from __future__ import annotations

import re
import threading
from pathlib import Path
from typing import Any

from src.network_detect import detect_gateway_ip, detect_wifi_ssid
from src.utils.file_helpers import atomic_write
from src.utils.crypto import save_password_field
from src.utils.logging import get_logger

from .schemas import ProfileSettings, ProfilesData, SystemSettings

profile_logger = get_logger("backend.profile_service", side="BACKEND")

_SETTINGS_FILE = "settings.json"


class ProfileService:
    """配置方案管理服务"""

    def __init__(self, project_root: Path):
        self.project_root = project_root
        self._settings_path = project_root / _SETTINGS_FILE
        self._lock = threading.Lock()
        self._data: ProfilesData | None = None

    def invalidate_cache(self) -> None:
        """清除缓存，强制下次 load() 从磁盘读取"""
        with self._lock:
            self._data = None

    def _load_unsafe(self) -> ProfilesData:
        """加载 settings.json（不加锁，由调用者持有锁）"""
        if self._data is not None:
            return self._data.model_copy(deep=True)

        if self._settings_path.exists():
            try:
                raw = self._settings_path.read_text(encoding="utf-8")
                self._data = ProfilesData.model_validate_json(raw)
                return self._data.model_copy(deep=True)
            except Exception as exc:
                profile_logger.error("加载 settings.json 失败: %s", exc)

        self._data = ProfilesData()
        return self._data.model_copy(deep=True)

    def _save_unsafe(self, data: ProfilesData) -> None:
        """原子写入 settings.json（不加锁，由调用者持有锁）"""
        content = data.model_dump_json(indent=2)
        atomic_write(self._settings_path, content)

        self._data = data
        profile_logger.info("settings.json 已保存")

    def load(self) -> ProfilesData:
        """加载 settings.json，不存在则返回空结构"""
        with self._lock:
            return self._load_unsafe()

    def save(self, data: ProfilesData) -> None:
        """原子写入 settings.json"""
        with self._lock:
            self._save_unsafe(data)

    def get_active_profile(self) -> ProfileSettings:
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
        return ProfileSettings()

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

            data.active_profile = profile_id
            self._save_unsafe(data)
        profile_logger.info("活动方案已切换: %s", profile_id)
        return True, f"已切换到方案: {data.profiles[profile_id].name}"

    def save_profile(
        self, profile_id: str, settings: ProfileSettings
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
        profile_logger.info("方案已保存: %s (%s)", profile_id, settings.name)
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
        profile_logger.info("方案已删除: %s", profile_id)
        return True, "方案删除成功"

    def detect_matching_profile(self) -> str | None:
        """检测当前网络环境并返回匹配的方案 ID，无匹配返回 None

        匹配优先级：网关 IP > SSID
        """
        gateway = detect_gateway_ip()
        ssid = detect_wifi_ssid()

        profile_logger.debug("检测到网关: %s, SSID: %s", gateway, ssid)

        data = self.load()

        # 优先匹配网关 IP
        if gateway:
            for profile_id, settings in data.profiles.items():
                match_ip = (settings.match_gateway_ip or "").strip()
                if match_ip and match_ip == gateway:
                    profile_logger.info(
                        "网关 %s 匹配方案: %s (%s)",
                        gateway,
                        profile_id,
                        settings.name,
                    )
                    return profile_id

        # 其次匹配 SSID
        if ssid:
            for profile_id, settings in data.profiles.items():
                match_ssid = (settings.match_ssid or "").strip()
                if match_ssid and match_ssid == ssid:
                    profile_logger.info(
                        "SSID '%s' 匹配方案: %s (%s)",
                        ssid,
                        profile_id,
                        settings.name,
                    )
                    return profile_id

        return None

    def set_auto_switch(self, enabled: bool) -> None:
        """设置自动切换开关"""
        with self._lock:
            data = self._load_unsafe()
            data.auto_switch = enabled
            self._save_unsafe(data)
        profile_logger.info("自动切换: %s", "开启" if enabled else "关闭")
