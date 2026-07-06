from __future__ import annotations

import json
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from app.network.detect import detect_gateway_ip, detect_wifi_ssid
from app.schemas import (
    ConfigSaveRequest,
    GlobalConfig,
    Profile,
    ProfilesData,
    RuntimeConfig,
)
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
        # 内存缓存 + mtime 失效
        self._cache: ProfilesData | None = None
        self._cache_mtime: float | None = None

    def _ensure_dirs(self) -> None:
        """确保 config/ 目录存在"""
        self._config_dir.mkdir(parents=True, exist_ok=True)

    def _load_unsafe(self) -> ProfilesData:
        """加载配置（不加锁，由调用者持有锁）。

        使用 mtime 失效的内存缓存：
        - 首次 load 或 mtime 变化时读盘
        - 后续 load 返回缓存引用
        - update/save 写盘后刷新缓存
        """
        self._ensure_dirs()

        if not self._settings_path.exists():
            self._cache = None
            self._cache_mtime = None
            return ProfilesData()

        # mtime 检查
        current_mtime = self._settings_path.stat().st_mtime
        if self._cache is not None and self._cache_mtime == current_mtime:
            return self._cache

        try:
            raw = self._settings_path.read_text(encoding="utf-8")
            data = ProfilesData.model_validate(json.loads(raw))
            if data.config_version != 5:
                profile_logger.warning(
                    "配置文件版本不匹配: 期望 5, 实际 {}",
                    data.config_version,
                )
            self._cache = data
            self._cache_mtime = current_mtime
            return data
        except Exception:
            profile_logger.warning("加载配置文件失败", exc_info=True)
            corrupt_name = f"settings.corrupt.{int(time.time())}.json"
            corrupt_path = self._config_dir / corrupt_name
            try:
                self._settings_path.rename(corrupt_path)
                profile_logger.info("备份损坏文件成功: {}", corrupt_path)
            except (FileNotFoundError, OSError):
                pass
            self._cache = None
            self._cache_mtime = None
            return ProfilesData()

    def _save_unsafe(self, data: ProfilesData) -> None:
        """原子写入配置并刷新缓存（不加锁，由调用者持有锁）"""
        self._ensure_dirs()
        settings_content = data.model_dump_json(indent=2)
        atomic_write(self._settings_path, settings_content)
        # 刷新缓存（保存后 mtime 已变，直接更新缓存避免下次 load 读盘）
        self._cache = data
        self._cache_mtime = self._settings_path.stat().st_mtime

    def load(self) -> ProfilesData:
        """加载配置，不存在则返回空结构"""
        with self._lock:
            return self._load_unsafe()

    def save(self, data: ProfilesData) -> None:
        """原子写入配置"""
        with self._lock:
            self._save_unsafe(data)

    def update(self, func: Callable[[ProfilesData], ProfilesData | None]) -> None:
        """原子化读-改-写操作（不可变版本）。

        持锁执行 load → func(data) → save，确保并发安全。
        func 接收当前 ProfilesData，返回新的 ProfilesData（frozen 不可变）。
        func 应快速返回，不要做 I/O 或网络操作。

        兼容旧签名：若 func 返回 None（原地修改风格），回退到旧逻辑
        （仅用于过渡期，新代码应返回新对象）。
        """
        with self._lock:
            data = self._load_unsafe()
            new_data = func(data)
            if new_data is None:
                new_data = data
            self._save_unsafe(new_data)

    def get_active_profile(self) -> Profile:
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
        return Profile()

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
            new_data = data.model_copy(update={"active_profile": profile_id})
            self._save_unsafe(new_data)
        profile_logger.info("切换活动方案 {} 成功", profile_id)
        return True, f"已切换到方案: {profile_name}"

    def save_profile(self, profile_id: str, settings: Profile) -> tuple[bool, str]:
        """创建或更新一个方案"""
        if not profile_id or not profile_id.strip():
            return False, "方案 ID 不能为空"

        profile_id = profile_id.strip()
        if not re.fullmatch(r"[a-zA-Z0-9_]+", profile_id):
            return False, "方案 ID 只能包含字母、数字和下划线"

        with self._lock:
            data = self._load_unsafe()
            existing = data.profiles.get(profile_id)

            # 处理密码字段：None 表示不修改，保留原值
            if settings.password is None:
                new_password = existing.password if existing else ""
            else:
                new_password = save_password_field(
                    settings.password,
                    existing.password if existing else "",
                )
            new_settings = settings.model_copy(update={"password": new_password})

            new_profiles = {**data.profiles, profile_id: new_settings}
            update: dict = {"profiles": new_profiles}
            if len(new_profiles) == 1:
                update["active_profile"] = profile_id
            new_data = data.model_copy(update=update)

            self._save_unsafe(new_data)
        profile_logger.info("保存方案 {} 成功 ({})", profile_id, new_settings.name)
        return True, f"方案 '{new_settings.name}' 保存成功"

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

            new_profiles = {k: v for k, v in data.profiles.items() if k != profile_id}
            update: dict = {"profiles": new_profiles}
            if data.active_profile == profile_id:
                update["active_profile"] = next(iter(new_profiles))

            new_data = data.model_copy(update=update)
            self._save_unsafe(new_data)
        profile_logger.info("删除方案 {} 成功", profile_id)
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

    def get_runtime_config(self) -> RuntimeConfig:
        """读磁盘 → 构建运行时配置。"""
        from app.services.config_builder import build_runtime_config

        data = self.load()
        profile = self._get_active_profile(data)
        return build_runtime_config(data.global_config, profile)

    def build_runtime_config(self, data: ProfilesData) -> RuntimeConfig:
        """从已加载的 data 构建运行时配置（避免重复读盘）。"""
        from app.services.config_builder import build_runtime_config

        profile = self._get_active_profile(data)
        return build_runtime_config(data.global_config, profile)

    def _get_active_profile(self, data: ProfilesData) -> Profile:
        """获取活跃方案并解密密码。"""
        from app.utils.crypto import decrypt_password_field

        profile = data.profiles.get(data.active_profile)
        if profile is None:
            profile = data.profiles.get("default", Profile())
        # 解密密码
        if profile.password:
            decrypted, err = decrypt_password_field(profile.password)
            if err:
                profile_logger.warning(
                    "密码解密失败: profile_id={}", data.active_profile
                )
            profile = profile.model_copy(update={"password": decrypted or ""})
        return profile

    def set_auto_switch(self, enabled: bool) -> None:
        """设置自动切换开关"""
        with self._lock:
            data = self._load_unsafe()
            new_data = data.model_copy(update={"auto_switch": enabled})
            self._save_unsafe(new_data)
        profile_logger.info("自动切换: {}", "开启" if enabled else "关闭")


# 进程级单例
_singleton_instance: ProfileService | None = None
_singleton_lock = threading.Lock()


def get_profile_service(project_root: Path | None = None) -> ProfileService:
    """获取 ProfileService 单例（进程级）。

    所有调用点共享同一实例，确保锁和缓存一致。
    project_root 仅首次调用生效（后续忽略）。
    """
    global _singleton_instance
    if _singleton_instance is not None:
        return _singleton_instance
    with _singleton_lock:
        if _singleton_instance is None:
            if project_root is None:
                project_root = Path(__file__).parent.parent.parent.resolve()
            _singleton_instance = ProfileService(project_root)
    return _singleton_instance


def reset_profile_service_singleton() -> None:
    """重置单例（仅供测试使用）。"""
    global _singleton_instance
    with _singleton_lock:
        _singleton_instance = None


@dataclass
class SaveResult:
    """配置保存结果。"""

    success: bool
    message: str




def save_global_and_profile(
    payload: ConfigSaveRequest,
    profile_service: ProfileService,
    reload_fn,
) -> SaveResult:
    """原子保存全局配置 + 方案凭据。"""
    backup_data = profile_service.load().model_copy(deep=True)

    def _apply(data: ProfilesData) -> ProfilesData:
        # 1. 更新全局配置
        new_global = GlobalConfig(
            browser=payload.browser,
            monitor=payload.monitor,
            retry=payload.retry,
            pause=payload.pause,
            logging=payload.logging,
            app_settings=payload.app_settings,
        )

        # 2. 更新活跃方案的凭据
        profile_id = data.active_profile
        existing = data.profiles.get(profile_id)
        if existing is None:
            existing = data.profiles.get("default", Profile())

        # ISP 反向映射
        carrier_custom = payload.carrier_custom or ""
        if carrier_custom:
            carrier = "自定义"
        elif not payload.isp:
            carrier = "无"
        else:
            carrier = payload.isp

        # 密码处理：None 保留原值，空串清除，明文加密
        if payload.password is None:
            new_password = existing.password or ""
        else:
            new_password = save_password_field(
                payload.password,
                existing.password or "",
            )

        new_profile = Profile.model_validate(
            {
                **existing.model_dump(),
                "username": payload.username or "",
                "password": new_password,
                "auth_url": payload.auth_url or "",
                "carrier": carrier,
                "carrier_custom": carrier_custom,
                "active_task": payload.active_task or "",
            }
        )

        new_profiles = {**data.profiles, profile_id: new_profile}
        return data.model_copy(
            update={
                "global_config": new_global,
                "profiles": new_profiles,
            }
        )

    try:
        profile_service.update(_apply)
    except Exception as exc:
        profile_logger.warning("保存配置失败: {}", exc)
        return SaveResult(success=False, message=f"保存失败: {exc}")

    ok, msg = reload_fn()
    if not ok:
        # 回滚
        profile_logger.warning("配置重载失败，正在回滚: {}", msg)
        try:
            profile_service.update(lambda data: backup_data.model_copy(deep=True))
            rollback_ok, rollback_msg = reload_fn()
            if not rollback_ok:
                return SaveResult(
                    success=False,
                    message=f"配置重载失败: {msg}（回滚后仍失败: {rollback_msg}）",
                )
            return SaveResult(success=False, message=f"配置重载失败，已回滚: {msg}")
        except Exception as rollback_exc:
            profile_logger.exception("回滚异常: {}", rollback_exc)
            return SaveResult(success=False, message=f"配置重载失败且回滚异常: {msg}")

    return SaveResult(success=True, message="配置保存成功")
