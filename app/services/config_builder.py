"""ConfigBuilder — GlobalConfig + Profile → RuntimeConfig，全项目唯一的配置构建器。"""

from __future__ import annotations

from app.schemas import (
    GlobalConfig,
    LoginCredentials,
    Profile,
    RuntimeConfig,
)


class ConfigBuilder:
    """GlobalConfig + Profile → RuntimeConfig，全项目唯一的凭据注入点。"""

    @staticmethod
    def build(global_config: GlobalConfig, profile: Profile) -> RuntimeConfig:
        """构建运行时配置。ISP 转换、密码过滤只在此处发生。"""
        username = profile.username.strip()
        raw_password = profile.password.strip()
        password = raw_password if (raw_password and not raw_password.startswith("•")) else ""
        auth_url = profile.auth_url.strip()

        # ISP 转换 — 全项目唯一
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
