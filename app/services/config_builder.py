"""build_runtime_config — GlobalConfig + Profile → RuntimeConfig，全项目唯一的配置构建函数。"""

from __future__ import annotations

from app.schemas import (
    GlobalConfig,
    LoginCredentials,
    Profile,
    RuntimeConfig,
)

# ISP 映射常量
_ISP_CARRIER_NONE = "无"
_ISP_CARRIER_CUSTOM = "自定义"
_PASSWORD_MASK_PREFIX = "•"


def build_runtime_config(
    global_config: GlobalConfig, profile: Profile
) -> RuntimeConfig:
    """构建运行时配置。ISP 转换、密码过滤只在此处发生。"""
    username = profile.username.strip()
    raw_password = (profile.password or "").strip()
    password = (
        raw_password
        if (raw_password and not raw_password.startswith(_PASSWORD_MASK_PREFIX))
        else ""
    )
    auth_url = profile.auth_url.strip()

    # ISP 转换 — 全项目唯一
    carrier = str(profile.carrier or _ISP_CARRIER_NONE).strip() or _ISP_CARRIER_NONE
    custom_isp = str(profile.carrier_custom or "").strip()
    if carrier == _ISP_CARRIER_CUSTOM:
        isp = custom_isp
    elif carrier == _ISP_CARRIER_NONE:
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

    return RuntimeConfig(
        browser=global_config.browser,
        monitor=global_config.monitor,
        retry=global_config.retry,
        pause=global_config.pause,
        logging=global_config.logging,
        credentials=credentials,
        app_settings=global_config.app_settings,
        active_task=profile.active_task.strip(),
    )
