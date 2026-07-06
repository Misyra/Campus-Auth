"""服务容器 — 统一管理服务实例的创建、启动和关闭。"""

from __future__ import annotations

import asyncio
import contextlib
import shutil
from pathlib import Path

from app.services.autostart import AutoStartService
from app.services.engine import ScheduleEngine
from app.services.login_history_service import LoginHistoryService
from app.services.profile_service import get_profile_service
from app.services.task_executor import TaskExecutor
from app.services.task_registry import TaskHistoryStore, TaskRegistry
from app.services.websocket_manager import WebSocketManager
from app.tasks import TaskManager
from app.utils.logging import DashboardSink, get_logger

container_logger = get_logger("container", source="backend")


class ServiceContainer:
    """服务容器 — 统一管理服务实例的创建和访问。"""

    def __init__(self, project_root: Path, mode: str = "full"):
        self.project_root = project_root
        self._temp_dir = project_root / "temp"

        # 基础服务
        self.ws_manager = WebSocketManager()
        self.profile_service = get_profile_service(project_root)
        from app.constants import AUTH_DATA_DIR

        self.login_history_service = LoginHistoryService(AUTH_DATA_DIR)
        self.task_manager = TaskManager(project_root / "tasks")
        self.autostart_service = AutoStartService(project_root)
        from app.services.debug_service import DebugSessionManager

        self.debug_manager = DebugSessionManager(project_root)

        # 定时任务注册中心
        self.task_registry = TaskRegistry(project_root / "tasks" / "scheduled")
        self.task_history_store = TaskHistoryStore(
            project_root / "tasks" / "scheduled" / "history"
        )

        def _get_worker():
            from app.workers.playwright_worker import get_worker

            return get_worker()

        # 新组件

        # 1. 创建 TaskExecutor（login_orchestrator 延迟绑定，打破循环依赖）
        self.task_executor = TaskExecutor(
            registry=self.task_registry,
            history_store=self.task_history_store,
            worker_getter=_get_worker,
            task_manager=self.task_manager,
        )

        # 2. 创建 LoginOrchestrator（executor 复用 TaskExecutor 的 login_executor）
        from app.services.login_orchestrator import LoginOrchestrator

        self.login_orchestrator = LoginOrchestrator(
            worker_getter=_get_worker,
            executor=self.task_executor.login_executor,
            login_history=self.login_history_service,
            profile_service=self.profile_service,
        )

        # 3. 反向绑定：让 TaskExecutor 持有 orchestrator
        self.task_executor.bind_login_orchestrator(self.login_orchestrator)

        # 3.5 创建 SchedulerService
        from app.services.scheduler_service import SchedulerService

        self.scheduler_service = SchedulerService(
            task_registry=self.task_registry,
            task_executor=self.task_executor,
        )

        # 4. 创建 ScheduleEngine（传入 orchestrator + task_executor + scheduler）
        self.engine = ScheduleEngine(
            project_root,
            self.profile_service,
            self.ws_manager,
            login_history_service=self.login_history_service,
            worker_getter=_get_worker,
            task_registry=self.task_registry,
            task_executor=self.task_executor,
            orchestrator=self.login_orchestrator,
            scheduler=self.scheduler_service,
        )

        # 5. 延迟绑定 get_runtime_config（engine 现在存在）
        self.login_orchestrator.bind_runtime_config(self.engine.get_runtime_config)
        self.task_executor.bind_runtime_config(self.engine.get_runtime_config)

        self._ws_drain_task: asyncio.Task | None = None
        self._log_handler_id: int | None = None
        self._web_services_started = False
        self._shutdown_done = False

    # ── 生命周期 ──

    async def startup(self):
        """启动所有服务。"""
        try:
            from app.workers.playwright_worker import cleanup_orphan_browsers

            cleanup_orphan_browsers()
            self.start_web_services()
            self.engine.boot()
            self.engine.sync_scheduler_state()
            container_logger.info("服务容器启动成功")
        except Exception as e:
            container_logger.exception("服务启动异常，正在清理: {}", e)
            try:
                await self.shutdown()
            except Exception as e2:
                container_logger.exception("清理过程异常: {}", e2)
            raise

    def start_web_services(self):
        """启动 Web 相关服务（DashboardSink + WS drain loop）。幂等。"""
        if self._web_services_started:
            return
        from loguru import logger

        if self._log_handler_id is None:
            dashboard_sink = DashboardSink()
            self._log_handler_id = logger.add(
                dashboard_sink.write,
                format="{message}",
                level="DEBUG",
            )
            self.engine._status_manager.set_dashboard_sink(dashboard_sink)  # for list_logs
            self.ws_manager.set_dashboard_sink(dashboard_sink)  # for broadcast
        self._ws_drain_task = asyncio.create_task(self.ws_manager.ws_drain_loop())
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
                container_logger.warning("移除日志处理器失败: {}", exc)
            self._log_handler_id = None

        if self._ws_drain_task:
            try:
                loop = asyncio.get_running_loop()
                if self._ws_drain_task.get_loop() is loop:
                    self._ws_drain_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await self._ws_drain_task
                else:
                    container_logger.debug("WS drain task 属于其他事件循环，跳过 await")
            except Exception:
                pass
            self._ws_drain_task = None

        self._web_services_started = False
        container_logger.info("Web 服务已停止")

    async def shutdown(self):
        """关闭服务。"""
        if self._shutdown_done:
            return
        self._shutdown_done = True
        container_logger.debug("服务容器开始关闭")

        # BUG-013 修复：先关闭引擎（停止提交任务），再关闭线程池
        self.engine.shutdown()

        # 等待进行中的任务完成回调，避免回调触及已关闭的组件
        try:
            await asyncio.wait_for(self.task_executor.wait_for_callbacks(), timeout=10)
        except TimeoutError:
            container_logger.warning("等待任务回调超时，继续关闭")

        # 关闭网络探测模块（停止接收新任务，等待 in-flight 请求完成）
        from app.network.probes import shutdown_probes

        shutdown_probes()

        # 关闭 scripts API 模块级 executor
        from app.api.scripts import shutdown_script_executor

        shutdown_script_executor()

        self.task_executor.shutdown(wait=True, timeout=10)

        # 复用 stop_web_services — 消除重复代码并修复 _ws_drain_task = None 遗漏 bug
        await self.stop_web_services()

        await self.debug_manager.close()
        await self.ws_manager.close_all()

        try:
            from app.workers.playwright_worker import shutdown_worker

            shutdown_worker(timeout=2)
            container_logger.info("Playwright Worker 已关闭")
        except Exception as e:
            container_logger.exception("关闭 Playwright Worker 异常: {}", e)

        try:
            if self._temp_dir.exists():
                shutil.rmtree(self._temp_dir, ignore_errors=True)
                self._temp_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            container_logger.warning("临时目录清理失败", exc_info=True)

        container_logger.info("服务容器已关闭")
