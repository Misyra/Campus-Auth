#!/usr/bin/env python3
"""
配置工具模块 — 验证、字段赋值

合并自原 config.py（ConfigValidator）和 config_helpers.py。
"""

from __future__ import annotations


# ── 字段赋值 ──────────────────────────────────────────────────────────


def assign_profile_fields(target: dict, source: dict, field_names: list[str]) -> None:
    """将 source 字典中的指定字段原地赋值到 target 字典。

    对于 field_names 中每个字段，如果 source 中存在则覆盖 target 中同名键。
    Args:
        target: 目标字典（原地修改）
        source: 源字典（通常为 MonitorConfigPayload.model_dump() 结果）
        field_names: 需要复制的字段名列表
    """
    for name in field_names:
        if name in source:
            target[name] = source[name]



# ── 验证器 ────────────────────────────────────────────────────────────


class ConfigValidator:
    """配置验证工具类 - 统一管理配置验证逻辑"""

    @staticmethod
    def validate_env_config(config: dict) -> tuple[bool, str]:
        """
        验证环境配置是否完整

        参数:
            config: 配置字典

        返回:
            tuple[bool, str]: (是否有效, 错误信息)
        """
        # 检查必要配置
        username = config.get("username")
        password = config.get("password")
        auth_url = config.get("auth_url")

        if not username or not password:
            return False, "缺少用户名或密码"

        if not auth_url:
            return False, "缺少认证地址"

        from app.schemas import _URL_PATTERN

        if not _URL_PATTERN.match(auth_url):
            return False, "认证地址必须以 http:// 或 https:// 开头"

        # 检查密码解密是否失败
        from app.utils.crypto import has_decryption_error
        if has_decryption_error():
            return False, "密码解密失败（可能是密钥变更），请在设置页面重新输入密码"

        return True, ""
