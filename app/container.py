"""服务容器 — 统一管理服务实例的创建、启动和关闭。"""

from __future__ import annotations

import asyncio
import contextlib
import shutil
from pathlib import Path

from app.services.autostart import AutoStartService
from app.services.debug import DebugSessionManager
from app.services.login_history import LoginHistoryService
from app.services.monitor import MonitorService
from app.services.profile import ProfileService
from app.services.scheduler import SchedulerService
from app.services.task import TaskService
from app.utils.logging import WebSocketSink, get_logger
from app.workers.playwright_worker import cleanup_orphan_browsers
from app.ws_manager import WebSocketManager

container_logger = get_logger("backend.container", side="BACKEND")


class ServiceContainer:
    """服务容器 — 统一管理服务实例的创建和访问。"""

    def __init__(self, project_root: Path):
        self.project_root = project_root
        self._temp_dir = project_root / "temp"
        self._logs_dir = project_root / "logs"
        self._backup_dir = project_root / "backups"

        # backups 目录（temp/logs 由 application.py 模块级创建）
        self._backup_dir.mkdir(parents=True, exist_ok=True)

        # 初始化服务
        self.ws_manager = WebSocketManager()
        self.profile_service = ProfileService(project_root)
        from app.constants import AUTH_DATA_DIR

        self.login_history_service = LoginHistoryService(AUTH_DATA_DIR)
        self.monitor_service = MonitorService(
            project_root,
            self.profile_service,
            self.ws_manager,
            login_history_service=self.login_history_service,
        )
        self.task_service = TaskService(project_root)
        self.scheduler_service = SchedulerService(
            project_root,
            self.task_service,
            self.monitor_service,
            login_history=self.login_history_service,
        )
        self.autostart_service = AutoStartService(project_root)
        self.debug_manager = DebugSessionManager(project_root)

        # WebSocket drain loop 任务
        self._ws_drain_task: asyncio.Task | None = None

    async def startup(self):
        """启动服务。"""
        # 清理孤儿浏览器进程
        cleanup_orphan_browsers()

        # 注册 WebSocket 日志 sink — 将 loguru 日志转发到前端并存入 _logs
        from loguru import logger

        ws_sink = WebSocketSink(
            self.monitor_service.ws_broadcast_queue,
            log_store=self.monitor_service.logs,
        )
        logger.add(
            ws_sink.write,
            format="{name} | {message}",
            level="DEBUG",
            filter=lambda record: record["extra"].get("side") == "BACKEND",
        )

        # 启动监控服务
        self.monitor_service.boot()

        # 启动定时任务调度器（仅在存在启用的任务时启动）
        if self.scheduler_service.has_enabled_tasks():
            self.scheduler_service.start()

        # 启动 WebSocket drain loop
        self._ws_drain_task = asyncio.create_task(self.monitor_service.ws_drain_loop())

        container_logger.info("服务容器启动完成")

    async def shutdown(self):
        """关闭服务。"""
        container_logger.info("服务容器开始关闭...")

        # 停止定时任务调度器
        self.scheduler_service.stop()

        # 取消 WebSocket drain loop
        if self._ws_drain_task:
            self._ws_drain_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._ws_drain_task

        # 完全关闭监控服务（停止监控 + 终止消费者线程）
        self.monitor_service.shutdown()

        # 关闭调试会话
        await self.debug_manager.close()

        # 关闭 WebSocket 连接
        await self.ws_manager.close_all()

        # 关闭 Playwright Worker（在所有服务关闭后，避免中断正在执行的任务）
        try:
            from app.workers.playwright_worker import shutdown_worker

            shutdown_worker()
            container_logger.info("Playwright Worker 已关闭")
        except Exception:
            container_logger.warning("关闭 Playwright Worker 异常", exc_info=True)

        # 清理临时目录
        try:
            if self._temp_dir.exists():
                for item in self._temp_dir.iterdir():
                    if item.is_file():
                        item.unlink(missing_ok=True)
                    elif item.is_dir():
                        shutil.rmtree(item, ignore_errors=True)
        except Exception:
            container_logger.warning("临时目录清理失败", exc_info=True)

        container_logger.info("服务容器已关闭")
