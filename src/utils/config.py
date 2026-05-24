#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
配置加载和验证工具类
"""

from typing import Tuple
from .logging import get_logger  # noqa: F401 — intentionally kept for future use


class ConfigValidator:
    """配置验证工具类 - 统一管理配置验证逻辑"""

    @staticmethod
    def validate_gui_config(
        username: str, password: str, check_interval: str
    ) -> Tuple[bool, str]:
        """
        验证GUI配置是否有效

        参数:
            username: 用户名
            password: 密码
            check_interval: 检测间隔

        返回:
            tuple[bool, str]: (是否有效, 错误信息)
        """
        # 验证必填字段
        username = username.strip()
        password = password.strip()

        # 掩码密码（"••••••••"）表示服务端已有加密密码，无需校验
        is_masked = password.startswith("•")

        if not username:
            return False, "账号不能为空"
        if not password and not is_masked:
            return False, "密码不能为空"

        # 验证账号格式（基本验证）
        if len(username) < 2:
            return False, "账号长度不能少于2位"

        # 验证密码格式（基本验证）— 跳过掩码
        if not is_masked and len(password) < 2:
            return False, "密码长度不能少于2位"

        # 验证检测间隔
        check_interval = check_interval.strip()
        try:
            interval_int = int(check_interval)
            if interval_int < 1:
                return False, "检测间隔必须大于0"
            if interval_int > 1440:  # 24小时
                return False, "检测间隔不能超过1440分钟（24小时）"
        except ValueError:
            return False, "检测间隔必须是正整数"

        return True, ""

    @staticmethod
    def validate_env_config(config: dict) -> Tuple[bool, str]:
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

        return True, ""
