"""配置服务 — 配置的保存与重载。"""

from __future__ import annotations

import copy
from dataclasses import dataclass

from app.schemas import (
    LoginCredentials,
    Profile,
    ProfilesData,
    RuntimeConfig,
)
from app.utils.logging import get_logger

from .profile_service import ProfileService

config_logger = get_logger("config_service", source="backend")


@dataclass
class SaveResult:
    """配置保存结果。"""

    success: bool
    message: str


def build_runtime_config(
    config: RuntimeConfig,
    profile: Profile,
) -> RuntimeConfig:
    """全局配置 + 活跃方案 → 最终运行时配置。凭证从 profile 读取。"""
    username = profile.username.strip()
    raw_password = profile.password.strip()
    password = raw_password if (raw_password and not raw_password.startswith("•")) else ""
    auth_url = profile.auth_url.strip()

    carrier = str(profile.carrier or "无").strip() or "无"
    custom_isp = str(profile.carrier_custom or "").strip()
    if carrier == "自定义":
        isp = custom_isp
    elif carrier == "无":
        isp = ""
    else:
        isp = carrier

    credentials = LoginCredentials(
        username=username,
        password=password,
        auth_url=auth_url,
        isp=isp,
        carrier_custom=custom_isp,
    )

    return config.model_copy(update={
        "credentials": credentials,
        "active_task": profile.active_task.strip(),
    })


def save_and_apply(
    config: RuntimeConfig,
    profile_service: ProfileService,
    reload_fn,
) -> SaveResult:
    """保存配置并重载运行时状态。失败时自动回滚。"""
    backup_data = copy.deepcopy(profile_service.load())

    def _apply(data: ProfilesData):
        data.config = config

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
