#!/usr/bin/env python3
"""
配置工具模块 — 验证

合并自原 config.py（ConfigValidator）和 config_helpers.py。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.schemas import RuntimeConfig


# ── 验证器 ────────────────────────────────────────────────────────────


class ConfigValidator:
    """配置验证工具类 - 统一管理配置验证逻辑"""

    @staticmethod
    def validate_env_config(config: RuntimeConfig) -> tuple[bool, str]:
        """
        验证环境配置是否完整

        参数:
            config: RuntimeConfig 实例

        返回:
            tuple[bool, str]: (是否有效, 错误信息)
        """
        creds = config.credentials

        if not creds.username or not creds.password:
            return False, "缺少用户名或密码"

        if not creds.auth_url:
            return False, "缺少认证地址"

        from app.schemas import _URL_PATTERN

        if not _URL_PATTERN.match(creds.auth_url):
            return False, "认证地址必须以 http:// 或 https:// 开头"

        from app.utils.crypto import has_decryption_error
        if has_decryption_error():
            return False, "密码解密失败（可能是密钥变更），请在设置页面重新输入密码"

        return True, ""
