"""运行时配置提供者 — 统一配置加载、缓存、线程安全读取。"""

from __future__ import annotations

import copy
import threading
from typing import Any

from app.schemas import MonitorConfigPayload
from app.utils.logging import get_logger

from .config import build_runtime_config, load_runtime_config, load_ui_config
from .profile import ProfileService

provider_logger = get_logger("config_provider", source="backend")


class RuntimeConfigProvider:
    """配置中心：从 ProfileService 加载配置，缓存运行时配置和 UI 配置，返回 deepcopy 防止多线程污染。"""

    def __init__(self, profile_service: ProfileService) -> None:
        self._profile_service = profile_service
        self._lock = threading.Lock()
        self._runtime_config: dict[str, Any] = {}
        self._ui_config: MonitorConfigPayload = MonitorConfigPayload()

    def reload(self) -> None:
        """从 settings.json 重新加载 UI 和运行时配置。"""
        with self._lock:
            data = self._profile_service.load()
            self._ui_config = load_ui_config(self._profile_service, data=data)
            runtime_payload, has_decrypt_error = load_runtime_config(
                self._profile_service, data=data
            )
            if has_decrypt_error:
                provider_logger.warning("配置重载时部分密码解密失败")
            self._runtime_config = build_runtime_config(runtime_payload, data.system)

    def get_runtime_config(self) -> dict[str, Any]:
        """返回运行时配置的深拷贝，防止多线程污染。"""
        with self._lock:
            return copy.deepcopy(self._runtime_config)

    def get_ui_config(self) -> MonitorConfigPayload:
        """返回 UI 配置的深拷贝，防止多线程污染。"""
        with self._lock:
            return self._ui_config.model_copy(deep=True)
