"""配置服务 — 配置的保存与重载。"""

from __future__ import annotations

import copy

from dataclasses import dataclass

from app.schemas import (
    ConfigResponseDTO,
    GlobalConfig,
    LoginCredentials,
    Profile,
    ProfilesData,
    RuntimeConfig,
)
from app.utils.crypto import save_password_field
from app.utils.logging import get_logger

from .profile_service import ProfileService

config_logger = get_logger("config_service", source="backend")


@dataclass
class SaveResult:
    """配置保存结果。"""

    success: bool
    message: str


def save_and_apply(
    config: RuntimeConfig,
    profile_service: ProfileService,
    reload_fn,
) -> SaveResult:
    """保存配置并重载运行时状态。失败时自动回滚。"""
    backup_data = copy.deepcopy(profile_service.load())

    def _apply(data: ProfilesData):
        # 剥离 credentials 和 active_task — 实际数据在 profiles 中，
        # global_config 中只存全局默认配置（browser/monitor/pause/logging/retry + 透传字段）
        data.global_config = config.model_copy(update={
            "credentials": LoginCredentials(),
            "active_task": "",
        })

    try:
        profile_service.update(_apply)
    except Exception as exc:
        config_logger.error("保存配置失败: {}", exc)
        return SaveResult(success=False, message=f"保存失败: {exc}")

    ok, msg = reload_fn()
    if not ok:
        config_logger.error("配置重载失败，正在回滚: {}", msg)
        try:
            profile_service.update(lambda data: _rollback_config(data, backup_data))
            rollback_ok, rollback_msg = reload_fn()
            if not rollback_ok:
                config_logger.error(
                    "配置回滚后重载仍失败: {}（磁盘已回滚，运行时状态可能不一致）",
                    rollback_msg,
                )
                return SaveResult(
                    success=False,
                    message=f"配置重载失败: {msg}（回滚后仍失败: {rollback_msg}）",
                )
            config_logger.warning("配置已回滚并重载成功（原失败: {}）", msg)
            return SaveResult(success=False, message=f"配置重载失败，已回滚: {msg}")
        except Exception as rollback_exc:
            config_logger.error(
                "回滚过程异常: {}", rollback_exc, exc_info=True,
            )
            return SaveResult(success=False, message=f"配置重载失败且回滚异常: {msg}")

    return SaveResult(success=True, message="配置保存成功")


def _rollback_config(data: ProfilesData, backup_data: ProfilesData) -> None:
    """回滚配置到备份状态。

    使用逐字段赋值而非 __dict__.update，确保 Pydantic 内部状态
    （如 model_fields_set）保持一致。
    """
    for field_name in ProfilesData.model_fields:
        setattr(data, field_name, getattr(backup_data, field_name))


def save_global_and_profile(
    payload: ConfigResponseDTO,
    profile_service: ProfileService,
    reload_fn,
) -> SaveResult:
    """原子保存全局配置 + 方案凭据。"""
    backup_data = copy.deepcopy(profile_service.load())

    def _apply(data: ProfilesData):
        # 1. 更新全局配置
        data.global_config = GlobalConfig(
            browser=payload.browser,
            monitor=payload.monitor,
            retry=payload.retry,
            pause=payload.pause,
            logging=payload.logging,
            block_proxy=payload.block_proxy,
            shell_path=payload.shell_path,
            minimize_to_tray=payload.minimize_to_tray,
            startup_action=payload.startup_action,
            autostart_lightweight=payload.autostart_lightweight,
            lightweight_tray=payload.lightweight_tray,
            auto_open_browser=payload.auto_open_browser,
            proxy=payload.proxy,
            app_port=payload.app_port,
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

        # 密码处理：掩码保留原值，明文加密
        new_password = save_password_field(
            payload.password or None,
            existing.password or "",
        )

        data.profiles[profile_id] = existing.model_copy(update={
            "username": payload.username or "",
            "password": new_password,
            "auth_url": payload.auth_url or "",
            "carrier": carrier,
            "carrier_custom": carrier_custom,
            "active_task": payload.active_task or "",
        })

    try:
        profile_service.update(_apply)
    except Exception as exc:
        config_logger.error("保存配置失败: {}", exc)
        return SaveResult(success=False, message=f"保存失败: {exc}")

    ok, msg = reload_fn()
    if not ok:
        # 回滚
        config_logger.error("配置重载失败，正在回滚: {}", msg)
        try:
            profile_service.update(lambda data: _rollback_config(data, backup_data))
            rollback_ok, rollback_msg = reload_fn()
            if not rollback_ok:
                return SaveResult(
                    success=False,
                    message=f"配置重载失败: {msg}（回滚后仍失败: {rollback_msg}）",
                )
            return SaveResult(success=False, message=f"配置重载失败，已回滚: {msg}")
        except Exception as rollback_exc:
            config_logger.error("回滚过程异常: {}", rollback_exc, exc_info=True)
            return SaveResult(
                success=False, message=f"配置重载失败且回滚异常: {msg}"
            )

    return SaveResult(success=True, message="配置保存成功")
