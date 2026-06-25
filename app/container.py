"""服务容器 — 统一管理服务实例的创建、启动和关闭。"""

from __future__ import annotations

import asyncio
import contextlib
import shutil
from pathlib import Path

from app.services.autostart import AutoStartService
from app.services.engine import ScheduleEngine
from app.services.login_history_service import LoginHistoryService
from app.services.network_tester import NetworkTester
from app.services.profile_service import ProfileService
from app.services.task_executor import TaskExecutor
from app.services.task_registry import TaskHistoryStore, TaskRegistry
from app.services.websocket_manager import NullWebSocketManager, WebSocketManager
from app.services.ws_broadcaster import WsBroadcaster
from app.tasks import TaskManager
from app.utils.logging import DashboardSink, get_logger

container_logger = get_logger("container", source="backend")


class ServiceContainer:
    """服务容器 — 统一管理服务实例的创建和访问。"""

    def __init__(self, project_root: Path, mode: str = "full"):
        self.project_root = project_root
        self._temp_dir = project_root / "temp"
        self._is_lightweight = mode == "lightweight"

        # 基础服务
        # 轻量模式下使用 Null Object，避免 None 检查
        self.ws_manager = NullWebSocketManager() if self._is_lightweight else WebSocketManager()
        self.profile_service = ProfileService(project_root)
        from app.constants import AUTH_DATA_DIR

        self.login_history_service = LoginHistoryService(AUTH_DATA_DIR)
        self.task_manager = TaskManager(project_root / "tasks")
        self.autostart_service = AutoStartService(project_root)
        self._debug_manager = None  # 延迟初始化，避免轻量模式加载 FastAPI

        # 定时任务注册中心
        self.task_registry = TaskRegistry(project_root / "tasks" / "scheduled")
        self.task_history_store = TaskHistoryStore(
            project_root / "tasks" / "scheduled" / "history"
        )

        def _get_worker():
            from app.workers.playwright_worker import get_worker

            return get_worker()

        # 新组件
        self.ws_broadcaster = WsBroadcaster(ws_manager=self.ws_manager)
        self.network_tester = NetworkTester()

        # 统一引擎（替代 MonitorService + SchedulerService）
        self.engine = ScheduleEngine(
            project_root,
            self.profile_service,
            self.ws_manager,
            login_history_service=self.login_history_service,
            worker_getter=_get_worker,
            task_registry=self.task_registry,
            ws_broadcaster=self.ws_broadcaster,
            network_tester=self.network_tester,
        )

        # 注入 LoginOrchestrator — 登录执行的唯一入口（自行管理线程池）
        from app.services.login_orchestrator import LoginOrchestrator

        self.login_orchestrator = LoginOrchestrator(
            worker_getter=_get_worker,
            login_history=self.login_history_service,
            profile_service=self.profile_service,
            get_runtime_config=self.engine.get_runtime_config,
        )
        self.engine.set_orchestrator(self.login_orchestrator)

        # 任务执行器（轻量模式仅用于登录，完整模式支持定时任务）
        self.task_executor = TaskExecutor(
            registry=self.task_registry,
            history_store=self.task_history_store,
            worker_getter=_get_worker,
            login_orchestrator=self.login_orchestrator,
            task_manager=self.task_manager,
        )
        # 注入登录专用 executor（消除 LoginOrchestrator 自建线程池）
        self.login_orchestrator.set_executor(self.task_executor._login_executor)
        self.engine.set_task_executor(self.task_executor)

        # 延迟绑定：TaskExecutor 通过引擎获取运行时配置
        self.task_executor.set_runtime_config_getter(self.engine.get_runtime_config)

        self._ws_drain_task: asyncio.Task | None = None
        self._log_handler_id: int | None = None
        self._web_services_started = False
        self._shutdown_done = False

    # ── 属性别名（保持 API 路由兼容）──

    @property
    def monitor_service(self) -> ScheduleEngine:
        """已废弃：请使用 services.engine。"""
        return self.engine

    @property
    def debug_manager(self):
        """延迟初始化 DebugSessionManager（避免轻量模式加载 FastAPI）。"""
        if self._debug_manager is None:
            from app.services.debug_service import DebugSessionManager

            self._debug_manager = DebugSessionManager(self.project_root)
        return self._debug_manager

    # ── 生命周期 ──

    async def startup(self):
        """启动所有服务。"""
        from app.workers.playwright_worker import cleanup_orphan_browsers

        try:
            cleanup_orphan_browsers()
            self.start_web_services()
            self.engine.boot()
            self.engine.sync_scheduler_state()
            container_logger.info("服务容器启动完成")
        except Exception:
            container_logger.exception("服务启动失败，正在清理...")
            try:
                await self.shutdown()
            except Exception:
                container_logger.exception("清理过程中也发生异常")
            raise

    def start_web_services(self):
        """启动 Web 相关服务（DashboardSink + WS drain loop）。幂等。"""
        if self._web_services_started:
            return
        from loguru import logger

        # 轻量模式唤醒时，将 NullWebSocketManager 切换为真正的 WebSocketManager
        if self._is_lightweight and isinstance(self.ws_manager, NullWebSocketManager):
            self.ws_manager = WebSocketManager()
            self.ws_broadcaster.set_ws_manager(self.ws_manager)
            self.engine._ws_manager = self.ws_manager
            container_logger.info("WebSocket 管理器已切换为实时模式")

        if self._log_handler_id is None:
            dashboard_sink = DashboardSink()
            self._log_handler_id = logger.add(
                dashboard_sink.write,
                format="{message}",
                level="DEBUG",
                filter=lambda record: record["extra"].get("source") != "frontend",
            )
            self.engine.set_dashboard_sink(dashboard_sink)  # for list_logs
            self.ws_broadcaster.set_dashboard_sink(dashboard_sink)  # for broadcast
        self._ws_drain_task = asyncio.create_task(self.ws_broadcaster.ws_drain_loop())
        self._web_services_started = True
        container_logger.info("Web 服务已启动")

    async def stop_web_services(self):
        """停止 Web 相关服务（DashboardSink + WS drain loop）。"""
        if not self._web_services_started:
            return

        if self._log_handler_id is not None:
            from loguru import logger as _loguru_logger

            try:
                _loguru_logger.remove(self._log_handler_id)
            except Exception as exc:
                container_logger.debug("移除日志处理器失败: {}", exc)
            self._log_handler_id = None

        if self._ws_drain_task:
            self._ws_drain_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._ws_drain_task
            self._ws_drain_task = None

        self._web_services_started = False
        container_logger.info("Web 服务已停止")

    async def shutdown(self):
        """关闭服务。"""
        if self._shutdown_done:
            return
        self._shutdown_done = True
        container_logger.info("服务容器开始关闭...")

        # 复用 stop_web_services — 消除重复代码并修复 _ws_drain_task = None 遗漏 bug
        await self.stop_web_services()

        # BUG-013 修复：先关闭引擎（停止提交任务），再关闭线程池
        self.engine.shutdown()

        self.task_executor.shutdown(wait=False)

        if self._debug_manager is not None:
            await self._debug_manager.close()
        await self.ws_manager.close_all()

        try:
            from app.workers.playwright_worker import shutdown_worker

            shutdown_worker(timeout=2)
            container_logger.info("Playwright Worker 已关闭")
        except Exception:
            container_logger.warning("关闭 Playwright Worker 异常", exc_info=True)

        try:
            if self._temp_dir.exists():
                shutil.rmtree(self._temp_dir, ignore_errors=True)
                self._temp_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            container_logger.warning("临时目录清理失败", exc_info=True)

        container_logger.info("服务容器已关闭")
