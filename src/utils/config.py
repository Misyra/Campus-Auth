#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
配置加载和验证工具类
"""

import os
import threading
from pathlib import Path
from typing import Tuple

from dotenv import load_dotenv

from .crypto import decrypt_password


class ConfigLoader:
    """配置加载工具类 - 统一管理所有配置加载逻辑"""

    @staticmethod
    def _str_to_bool(value: str) -> bool:
        """将字符串转换为布尔值"""
        return value.lower() in ("true", "1", "yes", "on")

    @staticmethod
    def _get_int_env(key: str, default: int) -> int:
        """安全获取整数环境变量"""
        try:
            return int(os.getenv(key, str(default)))
        except ValueError:
            return default

    @staticmethod
    def _load_basic_config() -> dict:
        """加载基础配置（密码自动解密）"""
        return {
            "username": os.getenv("USERNAME", ""),
            "password": decrypt_password(os.getenv("PASSWORD", "")),
            "auth_url": os.getenv("LOGIN_URL", "http://172.29.0.2"),
            "isp": os.getenv("ISP", ""),
            "auto_start_monitoring": ConfigLoader._str_to_bool(
                os.getenv("AUTO_START_MONITORING", "false")
            ),
        }

    @staticmethod
    def _load_browser_config() -> dict:
        """加载浏览器配置"""
        # 使用固定的User-Agent，简化逻辑
        default_user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

        return {
            "headless": ConfigLoader._str_to_bool(
                os.getenv("BROWSER_HEADLESS", "false")
            ),
            "timeout": ConfigLoader._get_int_env("BROWSER_TIMEOUT", 8000),
            "user_agent": os.getenv("BROWSER_USER_AGENT", default_user_agent),
            "low_resource_mode": ConfigLoader._str_to_bool(
                os.getenv("BROWSER_LOW_RESOURCE_MODE", "false")
            ),
            "extra_headers_json": os.getenv("BROWSER_EXTRA_HEADERS_JSON", ""),
            "disable_web_security": ConfigLoader._str_to_bool(
                os.getenv("BROWSER_DISABLE_WEB_SECURITY", "false")
            ),
        }

    @staticmethod
    def _load_other_configs() -> dict:
        """加载其他配置项"""
        return {
            "retry_settings": {
                "max_retries": ConfigLoader._get_int_env("RETRY_MAX_RETRIES", 3),
                "retry_interval": ConfigLoader._get_int_env("RETRY_INTERVAL", 5),
            },
            "logging": {
                "level": os.getenv("BACKEND_LOG_LEVEL", os.getenv("LOG_LEVEL", "INFO")),
                "format": os.getenv(
                    "LOG_FORMAT", "%(asctime)s - %(levelname)s - %(message)s"
                ),
                "file": os.getenv("LOG_FILE", "logs/campus_auth.log") or None,
            },
            "frontend_logging": {
                "level": os.getenv("FRONTEND_LOG_LEVEL", "INFO"),
            },
            "pause_login": {
                "enabled": ConfigLoader._str_to_bool(
                    os.getenv("PAUSE_LOGIN_ENABLED", "true")
                ),
                "start_hour": ConfigLoader._get_int_env("PAUSE_LOGIN_START_HOUR", 0),
                "end_hour": ConfigLoader._get_int_env("PAUSE_LOGIN_END_HOUR", 6),
            },
            "monitor": {
                "interval": ConfigLoader._get_int_env("MONITOR_INTERVAL", 300),
                "ping_targets": [
                    target.strip()
                    for target in os.getenv(
                        "PING_TARGETS",
                        "8.8.8.8:53,114.114.114.114:53,www.baidu.com:443",
                    ).split(",")
                    if target.strip()
                ],
            },
            "minimize_to_tray": ConfigLoader._str_to_bool(
                os.getenv("MINIMIZE_TO_TRAY", "false")
            ),
        }

    @staticmethod
    def load_config_from_env() -> dict:
        """从环境变量加载配置"""
        env_override = (
            os.getenv("Campus-Auth_ENV_FILE", "").strip()
            or os.getenv("JCU_ENV_FILE", "").strip()
        )
        if env_override:
            load_dotenv(Path(env_override), override=True)
        else:
            load_dotenv(Path.cwd() / ".env", override=True)

        config = ConfigLoader._load_basic_config()
        config["browser_settings"] = ConfigLoader._load_browser_config()
        config.update(ConfigLoader._load_other_configs())
        return config


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

        if not username:
            return False, "账号不能为空"
        if not password:
            return False, "密码不能为空"

        # 验证账号格式（基本验证）
        if len(username) < 2:
            return False, "账号长度不能少于2位"

        # 验证密码格式（基本验证）
        if len(password) < 2:
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


class ConfigManager:
    """
    配置管理器（单例模式）

    统一管理配置加载，避免重复读取环境变量
    """

    _instance = None
    _config = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    @classmethod
    def get_config(cls, force_reload: bool = False) -> dict:
        """
        获取配置（单例访问点）

        Args:
            force_reload: 是否强制重新加载配置

        Returns:
            dict: 配置字典
        """
        if cls._config is None or force_reload:
            with cls._lock:
                if cls._config is None or force_reload:
                    cls._config = ConfigLoader.load_config_from_env()
        return cls._config

    @classmethod
    def reload_config(cls) -> dict:
        """
        重新加载配置

        Returns:
            dict: 新的配置字典
        """
        return cls.get_config(force_reload=True)

    @classmethod
    def clear_cache(cls) -> None:
        """清除配置缓存"""
        with cls._lock:
            cls._config = None

    @classmethod
    def get_instance(cls) -> "ConfigManager":
        """获取配置管理器实例"""
        if cls._instance is None:
            cls()
        return cls._instance
