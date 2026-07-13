"""ConfigService — 运行时配置的唯一持有者。

从 ScheduleEngine 抽离的配置管理职责：
- 运行时配置持有与原子替换
- 纯净模式（pure_mode）状态管理
- 日志级别更新
- 配置重载（从 profile_service.load() 重建）

Engine 不再持有 _runtime_config，通过依赖注入获取 ConfigService。
API 层通过 ConfigServiceDep 访问配置。
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

from app.schemas import RuntimeConfig
from app.utils.logging import get_logger

if TYPE_CHECKING:
    from app.services.profile_service import ProfileService

logger = get_logger("config_service", source="backend")


class ConfigService:
    """运行时配置服务 — 配置的唯一持有者。

    职责：
    - 持有 frozen RuntimeConfig 引用（原子替换）
    - 持有 pure_mode 标志
    - 提供 get_runtime_config() 线程安全访问
    - 提供 update_log_level() 原子更新日志级别
    - 提供 toggle_pure_mode() 切换并持久化纯净模式
    - 提供 reload() 从磁盘重新加载配置

    不负责：
    - 监控启动/停止（Engine 职责）
    - 配置磁盘 IO（委托 ProfileService）
    - 命令队列派发（Engine 职责）
    """

    def __init__(self, profile_service: ProfileService) -> None:
        self._profile_service = profile_service
        self._reload_lock: threading.Lock = threading.Lock()
        self._runtime_config: RuntimeConfig = RuntimeConfig()
        self._pure_mode: bool = False
        # 初始加载
        self._reload_internal()

    # ── 公共 API ──

    def get_runtime_config(self) -> RuntimeConfig:
        """线程安全地获取运行时配置（frozen 对象，直接返回引用）。

        返回的 RuntimeConfig 是 frozen Pydantic 对象，调用方可安全持有引用。
        reload 后返回新引用。
        """
        return self._runtime_config

    @property
    def pure_mode(self) -> bool:
        """线程安全地读取纯净模式标志。"""
        with self._reload_lock:
            return self._pure_mode

    def update_log_level(self, level: str) -> None:
        """更新运行时日志级别（线程安全）。

        校验级别合法性后，通过 model_copy 原子替换 _runtime_config。
        不负责持久化到磁盘（由调用方通过 profile_service.update 完成）。

        model_copy 在锁外执行（基于当前引用快照），仅 _swap 持锁——
        与 Engine.update_log_level 行为对齐，避免 Lock 不可重入导致的死锁。
        """
        from app.constants import VALID_LOG_LEVELS

        if level not in VALID_LOG_LEVELS:
            raise ValueError(f"无效的日志级别: {level}")
        base = self._runtime_config
        new_config = base.model_copy(
            update={
                "logging": base.logging.model_copy(update={"level": level})
            }
        )
        self._swap(new_config)

    def toggle_pure_mode(self) -> bool:
        """切换纯净模式，返回新值。

        行为：
        1. 读取当前 pure_mode，取反
        2. 持久化到 profile_service（磁盘）
        3. 原子替换 _runtime_config.browser.pure_mode
        4. 返回新值
        """
        with self._reload_lock:
            new_value = not self._pure_mode
            base_config = self._runtime_config

        # 磁盘持久化（profile_service 内部有自己的锁，无需 _reload_lock 保护）
        self._profile_service.update(
            lambda d: d.model_copy(
                update={
                    "global_config": d.global_config.model_copy(
                        update={
                            "browser": d.global_config.browser.model_copy(
                                update={"pure_mode": new_value}
                            )
                        }
                    )
                }
            )
        )

        # 原子替换运行时配置（model_copy 在锁外，仅 _swap 持锁）
        new_config = base_config.model_copy(
            update={
                "browser": base_config.browser.model_copy(
                    update={"pure_mode": new_value}
                )
            }
        )
        self._swap(new_config, pure_mode=new_value)
        return new_value

    def reload(self) -> bool:
        """从磁盘重新加载配置。返回 True 表示成功。

        磁盘 IO 在锁外执行，仅 frozen 引用替换持锁。
        """
        return self._reload_internal()

    # ── 内部方法 ──

    def _swap(self, new: RuntimeConfig, *, pure_mode: bool | None = None) -> None:
        """原子替换运行时配置（线程安全）。

        所有 _runtime_config 写入必须经此方法，在 _reload_lock 保护下
        原子替换 frozen 引用。禁止直接赋值 self._runtime_config = ...
        """
        with self._reload_lock:
            self._runtime_config = new
            if pure_mode is not None:
                self._pure_mode = pure_mode

    def _reload_internal(self) -> bool:
        """从 profile_service.load() 重新加载配置。返回 True 表示成功。

        磁盘 IO 在锁外执行（缩小锁粒度），仅 frozen 引用替换持锁。
        """
        try:
            data = self._profile_service.load()
            new_config = self._profile_service.build_runtime_config(data)
            pure_mode = data.global_config.browser.pure_mode
        except Exception:
            logger.warning("配置重载失败", exc_info=True)
            return False
        self._swap(new_config, pure_mode=pure_mode)
        return True
