"""服务容器 — 统一管理服务实例的创建、启动和关闭。"""

from __future__ import annotations

import asyncio
import contextlib
import shutil
from pathlib import Path

from app.services.autostart import AutoStartService
from app.services.engine import ScheduleEngine
from app.services.login_history import LoginHistoryService
from app.services.profile import ProfileService
from app.services.task import TaskService
from app.utils.logging import DashboardSink, get_logger
from app.ws_manager import WebSocketManager

container_logger = get_logger("container", source="backend")


class ServiceContainer:
    """服务容器 — 统一管理服务实例的创建和访问。"""

    def __init__(self, project_root: Path):
        self.project_root = project_root
        self._temp_dir = project_root / "temp"
        self._logs_dir = project_root / "logs"
        self._backup_dir = project_root / "backups"
        self._backup_dir.mkdir(parents=True, exist_ok=True)

        # 基础服务
        self.ws_manager = WebSocketManager()
        self.profile_service = ProfileService(project_root)
        from app.constants import AUTH_DATA_DIR

        self.login_history_service = LoginHistoryService(AUTH_DATA_DIR)
        self.task_service = TaskService(project_root)
        self.autostart_service = AutoStartService(project_root)
        self._debug_manager = None  # 延迟初始化，避免轻量模式加载 FastAPI

        # 统一引擎（替代 MonitorService + SchedulerService）
        self.engine = ScheduleEngine(
            project_root,
            self.profile_service,
            self.ws_manager,
            login_history_service=self.login_history_service,
            worker_getter=lambda: __import__('app.workers.playwright_worker', fromlist=['get_worker']).get_worker(),
        )

        self._ws_drain_task: asyncio.Task | None = None
        self._log_handler_id: int | None = None
        self._web_services_started = False

    # ── 属性别名（保持 API 路由兼容）──

    @property
    def monitor_service(self) -> ScheduleEngine:
        return self.engine

    @property
    def scheduler_service(self) -> ScheduleEngine:
        return self.engine

    @property
    def debug_manager(self):
        """延迟初始化 DebugSessionManager（避免轻量模式加载 FastAPI）。"""
        if self._debug_manager is None:
            from app.services.debug import DebugSessionManager
            self._debug_manager = DebugSessionManager(self.project_root)
        return self._debug_manager

    # ── 生命周期 ──

    async def startup(self):
        """启动所有服务。"""
        from app.workers.playwright_worker import cleanup_orphan_browsers
        cleanup_orphan_browsers()
        self.start_web_services()
        self.engine.boot()
        if self.engine.has_enabled_tasks():
            self.engine.start_scheduler()
        container_logger.info("服务容器启动完成")

    def start_web_services(self):
        """启动 Web 相关服务（DashboardSink + WS drain loop）。幂等。"""
        if self._web_services_started:
            return
        from loguru import logger

        if self._log_handler_id is None:
            dashboard_sink = DashboardSink(maxlen=1200, broadcast_maxlen=200)
            self._log_handler_id = logger.add(
                dashboard_sink.write,
                format="{message}",
                level="DEBUG",
                filter=lambda record: record["extra"].get("source") != "frontend",
            )
            self.engine._dashboard_sink = dashboard_sink
        self._ws_drain_task = asyncio.create_task(self.engine.ws_drain_loop())
        self._web_services_started = True
        container_logger.info("Web 服务已启动")

    async def stop_web_services(self):
        """停止 Web 相关服务（DashboardSink + WS drain loop）。

        用于空闲卸载：停止 uvicorn 后调用，允许下次重新启动。
        """
        if not self._web_services_started:
            return

        if self._log_handler_id is not None:
            from loguru import logger as _loguru_logger
            with contextlib.suppress(Exception):
                _loguru_logger.remove(self._log_handler_id)
            self._log_handler_id = None

        if self._ws_drain_task:
            self._ws_drain_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._ws_drain_task
            self._ws_drain_task = None

        self._web_services_started = False
        container_logger.info("Web 服务已停止（空闲卸载）")

    async def shutdown(self):
        """关闭服务。"""
        container_logger.info("服务容器开始关闭...")

        if self._log_handler_id is not None:
            from loguru import logger as _loguru_logger

            with contextlib.suppress(Exception):
                _loguru_logger.remove(self._log_handler_id)
            self._log_handler_id = None

        self.engine.stop_scheduler()

        if self._ws_drain_task:
            self._ws_drain_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._ws_drain_task

        self.engine.shutdown()

        if self._debug_manager is not None:
            await self._debug_manager.close()
        await self.ws_manager.close_all()

        try:
            from app.workers.playwright_worker import shutdown_worker

            shutdown_worker()
            container_logger.info("Playwright Worker 已关闭")
        except Exception:
            container_logger.warning("关闭 Playwright Worker 异常", exc_info=True)

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
