"""服务容器 — 统一管理服务实例的创建、启动和关闭。"""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

from src.playwright_worker import cleanup_orphan_browsers

from .autostart_service import AutoStartService
from .constants import BACKUP_DIR, LOGS_DIR, TEMP_DIR
from .debug_manager import DebugSessionManager
from .monitor_service import MonitorService
from .profile_service import ProfileService
from .task_service import TaskService
from .ws_manager import WebSocketManager

from src.utils.logging import get_logger

container_logger = get_logger("backend.container", side="BACKEND")


class ServiceContainer:
    """服务容器 — 统一管理服务实例的创建和访问。"""

    def __init__(self, project_root: Path):
        self.project_root = project_root

        # 创建必要的目录
        TEMP_DIR.mkdir(parents=True, exist_ok=True)
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)

        # 初始化服务
        self.ws_manager = WebSocketManager()
        self.profile_service = ProfileService(project_root)
        self.monitor_service = MonitorService(
            project_root, self.profile_service, self.ws_manager
        )
        self.task_service = TaskService(project_root)
        self.autostart_service = AutoStartService(project_root)
        self.debug_manager = DebugSessionManager(project_root)

        # WebSocket drain loop 任务
        self._ws_drain_task: asyncio.Task | None = None

    async def startup(self):
        """启动服务。"""
        # 清理孤儿浏览器进程
        cleanup_orphan_browsers()

        # 启动监控服务
        self.monitor_service.boot()

        # 启动 WebSocket drain loop
        self._ws_drain_task = asyncio.create_task(
            self.monitor_service._ws_drain_loop()
        )

        container_logger.info("服务容器启动完成")

    async def shutdown(self):
        """关闭服务。"""
        container_logger.info("服务容器开始关闭...")

        # 取消 WebSocket drain loop
        if self._ws_drain_task:
            self._ws_drain_task.cancel()
            try:
                await self._ws_drain_task
            except asyncio.CancelledError:
                pass

        # 关闭调试会话
        await self.debug_manager.close()

        # 停止监控
        self.monitor_service.stop_monitoring()

        # 关闭 WebSocket 连接
        await self.ws_manager.close_all()

        # 清理临时目录
        try:
            if TEMP_DIR.exists():
                for item in TEMP_DIR.iterdir():
                    if item.is_file():
                        item.unlink(missing_ok=True)
                    elif item.is_dir():
                        shutil.rmtree(item, ignore_errors=True)
        except Exception:
            container_logger.debug("临时目录清理失败", exc_info=True)

        container_logger.info("服务容器已关闭")
