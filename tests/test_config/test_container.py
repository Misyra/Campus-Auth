"""ServiceContainer 测试 — app/container.py

覆盖：初始化、服务创建与获取、startup、shutdown 生命周期。
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── 模块级 mock，避免构造函数中触发真实依赖 ──


@pytest.fixture
def project_root(tmp_path: Path) -> Path:
    """返回一个临时项目根目录。"""
    return tmp_path


@pytest.fixture
def mock_classes():
    """返回所有被 patch 的服务类 mock。"""
    with (
        patch("app.container.WebSocketManager") as mock_ws_cls,
        patch("app.container.ProfileService") as mock_profile_cls,
        patch("app.container.LoginHistoryService") as mock_lh_cls,
        patch("app.container.ScheduleEngine") as mock_engine_cls,
        patch("app.container.TaskService") as mock_task_cls,
        patch("app.container.AutoStartService") as mock_autostart_cls,
        patch("app.container.TaskRegistry") as mock_tr_cls,
        patch("app.container.TaskHistoryStore") as mock_ths_cls,
        patch("app.container.TaskExecutor") as mock_te_cls,
        patch("app.services.debug_service.DebugSessionManager") as mock_debug_cls,
    ):
        yield {
            "WebSocketManager": mock_ws_cls,
            "ProfileService": mock_profile_cls,
            "LoginHistoryService": mock_lh_cls,
            "ScheduleEngine": mock_engine_cls,
            "TaskService": mock_task_cls,
            "AutoStartService": mock_autostart_cls,
            "TaskRegistry": mock_tr_cls,
            "TaskHistoryStore": mock_ths_cls,
            "TaskExecutor": mock_te_cls,
            "DebugSessionManager": mock_debug_cls,
        }


@pytest.fixture
def container(project_root: Path, mock_classes: dict):
    """在 patch 下创建 ServiceContainer 实例。"""
    from app.container import ServiceContainer

    c = ServiceContainer(project_root)

    # ws_drain_loop 必须返回协程，否则 asyncio.create_task 会失败
    c.engine.ws_drain_loop = AsyncMock()

    c._mock_classes = mock_classes
    return c


# =====================================================================
# 初始化
# =====================================================================


class TestInit:
    def test_project_root_stored(self, container, project_root):
        """__init__ 应保存 project_root。"""
        assert container.project_root == project_root

    def test_backup_dir_created(self, container, project_root):
        """__init__ 应创建 backups 目录。"""
        assert (project_root / "backups").is_dir()

    def test_temp_dir_path(self, container, project_root):
        """temp_dir 路径应为 project_root / temp。"""
        assert container._temp_dir == project_root / "temp"

    def test_logs_dir_path(self, container, project_root):
        """logs_dir 路径应为 project_root / logs。"""
        assert container._logs_dir == project_root / "logs"

    def test_ws_drain_task_initially_none(self, container):
        """ws_drain_task 初始应为 None。"""
        assert container._ws_drain_task is None

    def test_websocket_manager_created(self, container, mock_classes):
        """WebSocketManager 应被实例化。"""
        mock_classes["WebSocketManager"].assert_called_once()

    def test_profile_service_created_with_root(
        self, container, project_root, mock_classes
    ):
        """ProfileService 应以 project_root 构造。"""
        mock_classes["ProfileService"].assert_called_once_with(project_root)

    def test_login_history_service_created(self, container, mock_classes):
        """LoginHistoryService 应被实例化。"""
        mock_classes["LoginHistoryService"].assert_called_once()

    def test_engine_created_with_dependencies(
        self, container, project_root, mock_classes
    ):
        """ScheduleEngine 应接收 project_root、profile_service、ws_manager、login_history_service。"""
        mock_classes["ScheduleEngine"].assert_called_once()
        call_args = mock_classes["ScheduleEngine"].call_args
        assert call_args[0][0] == project_root
        assert call_args[1]["login_history_service"] is container.login_history_service

    def test_task_service_created_with_root(
        self, container, project_root, mock_classes
    ):
        """TaskService 应以 project_root 构造。"""
        mock_classes["TaskService"].assert_called_once_with(project_root)

    def test_autostart_service_created(self, container, project_root, mock_classes):
        """AutoStartService 应以 project_root 构造。"""
        mock_classes["AutoStartService"].assert_called_once_with(project_root)

    def test_debug_manager_created(self, container, project_root, mock_classes):
        """DebugSessionManager 应以 project_root 构造（延迟初始化）。"""
        _ = container.debug_manager  # 触发延迟初始化
        mock_classes["DebugSessionManager"].assert_called_once_with(project_root)

    def test_services_accessible_as_attributes(self, container):
        """各服务实例应可作为属性直接访问。"""
        assert hasattr(container, "ws_manager")
        assert hasattr(container, "profile_service")
        assert hasattr(container, "login_history_service")
        assert hasattr(container, "engine")
        assert hasattr(container, "monitor_service")  # 向后兼容别名
        assert hasattr(container, "task_service")
        assert hasattr(container, "autostart_service")
        assert hasattr(container, "debug_manager")
        assert hasattr(container, "task_registry")
        assert hasattr(container, "task_history_store")
        assert hasattr(container, "task_executor")

    def test_lightweight_mode_uses_null_ws_manager(self, project_root, mock_classes):
        """轻量模式下应使用 NullWebSocketManager。"""
        from app.container import ServiceContainer
        from app.services.websocket_manager import NullWebSocketManager

        container = ServiceContainer(project_root, mode="lightweight")
        assert isinstance(container.ws_manager, NullWebSocketManager)
        mock_classes["WebSocketManager"].assert_not_called()

    def test_lightweight_mode_creates_task_executor(self, project_root, mock_classes):
        """轻量模式下应创建 TaskExecutor（定时任务需要）。"""
        from app.container import ServiceContainer

        container = ServiceContainer(project_root, mode="lightweight")
        mock_classes["TaskExecutor"].assert_called_once()
        assert container.task_executor is not None

    def test_full_mode_creates_ws_manager(self, container, mock_classes):
        """完整模式下应创建 WebSocketManager。"""
        mock_classes["WebSocketManager"].assert_called_once()
        assert container.ws_manager is not None

    def test_full_mode_creates_task_executor(self, container, mock_classes):
        """完整模式下应创建 TaskExecutor。"""
        mock_classes["TaskExecutor"].assert_called_once()
        assert container.task_executor is not None


# =====================================================================
# startup
# =====================================================================


class TestStartup:
    @pytest.fixture
    def container_for_startup(self, container):
        """为 startup 测试配置 mock 行为。"""
        container.task_registry.has_enabled_tasks = MagicMock(return_value=False)
        container.engine.start_scheduler = MagicMock()
        return container

    @patch("app.workers.playwright_worker.cleanup_orphan_browsers")
    @patch("app.container.DashboardSink")
    @patch("loguru.logger")
    def test_startup_calls_cleanup_orphans(
        self, mock_logger, mock_dashboard_sink, mock_cleanup, container_for_startup
    ):
        """startup 应调用 cleanup_orphan_browsers。"""
        asyncio.run(container_for_startup.startup())
        mock_cleanup.assert_called_once()

    @patch("app.workers.playwright_worker.cleanup_orphan_browsers")
    @patch("app.container.DashboardSink")
    @patch("loguru.logger")
    def test_startup_boots_monitor(
        self, mock_logger, mock_dashboard_sink, mock_cleanup, container_for_startup
    ):
        """startup 应调用 engine.boot()。"""
        asyncio.run(container_for_startup.startup())
        container_for_startup.engine.boot.assert_called_once()

    @patch("app.workers.playwright_worker.cleanup_orphan_browsers")
    @patch("app.container.DashboardSink")
    @patch("loguru.logger")
    def test_startup_starts_scheduler_when_enabled(
        self, mock_logger, mock_dashboard_sink, mock_cleanup, container_for_startup
    ):
        """当存在启用的定时任务时，startup 应启动调度器。"""
        container_for_startup.task_registry.has_enabled_tasks.return_value = True
        asyncio.run(container_for_startup.startup())
        container_for_startup.engine.start_scheduler.assert_called_once()

    @patch("app.workers.playwright_worker.cleanup_orphan_browsers")
    @patch("app.container.DashboardSink")
    @patch("loguru.logger")
    def test_startup_skips_scheduler_when_no_enabled_tasks(
        self, mock_logger, mock_dashboard_sink, mock_cleanup, container_for_startup
    ):
        """没有启用的定时任务时，startup 不应启动调度器。"""
        container_for_startup.task_registry.has_enabled_tasks.return_value = False
        asyncio.run(container_for_startup.startup())
        container_for_startup.engine.start_scheduler.assert_not_called()

    @patch("app.workers.playwright_worker.cleanup_orphan_browsers")
    @patch("app.container.DashboardSink")
    @patch("loguru.logger")
    def test_startup_creates_ws_drain_task(
        self, mock_logger, mock_dashboard_sink, mock_cleanup, container_for_startup
    ):
        """startup 应创建 ws_drain_loop 异步任务。"""
        asyncio.run(container_for_startup.startup())
        assert container_for_startup._ws_drain_task is not None


# =====================================================================
# shutdown
# =====================================================================


class TestShutdown:
    @pytest.fixture
    def container_for_shutdown(self, container):
        """为 shutdown 测试配置 mock 行为。"""
        container.engine.shutdown = MagicMock()
        container.debug_manager.close = AsyncMock()
        container.ws_manager.close_all = AsyncMock()
        return container

    def test_shutdown_calls_monitor_shutdown(self, container_for_shutdown):
        """shutdown 应调用 engine.shutdown()。"""
        asyncio.run(container_for_shutdown.shutdown())
        container_for_shutdown.engine.shutdown.assert_called_once()

    def test_shutdown_closes_debug_manager(self, container_for_shutdown):
        """shutdown 应关闭调试会话管理器。"""
        asyncio.run(container_for_shutdown.shutdown())
        container_for_shutdown.debug_manager.close.assert_awaited_once()

    def test_shutdown_closes_all_ws(self, container_for_shutdown):
        """shutdown 应关闭所有 WebSocket 连接。"""
        asyncio.run(container_for_shutdown.shutdown())
        container_for_shutdown.ws_manager.close_all.assert_awaited_once()

    def test_shutdown_cancels_ws_drain_task(self, container_for_shutdown, project_root):
        """shutdown 应取消 ws_drain_task（如果存在）。"""

        async def _run():
            # 创建一个真实的 asyncio task 来模拟 ws_drain_loop
            async def _dummy_loop():
                while True:
                    await asyncio.sleep(1)

            container_for_shutdown._ws_drain_task = asyncio.create_task(_dummy_loop())
            # 让 task 开始运行
            await asyncio.sleep(0.01)

            await container_for_shutdown.shutdown()

            assert container_for_shutdown._ws_drain_task.cancelled()

        asyncio.run(_run())

    def test_shutdown_handles_no_drain_task(self, container_for_shutdown):
        """ws_drain_task 为 None 时 shutdown 不应报错。"""
        container_for_shutdown._ws_drain_task = None
        asyncio.run(container_for_shutdown.shutdown())
        # 不抛异常即通过

    @patch("app.workers.playwright_worker.cleanup_orphan_browsers")
    def test_shutdown_cleans_temp_dir(
        self, mock_cleanup, container_for_shutdown, project_root
    ):
        """shutdown 应使用 shutil.rmtree 一步清理临时目录。"""
        temp_dir = project_root / "temp"
        temp_dir.mkdir()

        # 创建临时文件和子目录
        temp_file = temp_dir / "test.txt"
        temp_file.write_text("test")
        temp_subdir = temp_dir / "subdir"
        temp_subdir.mkdir()

        # mock shutdown_worker
        with patch("app.workers.playwright_worker.shutdown_worker"):
            asyncio.run(container_for_shutdown.shutdown())

        # 验证临时目录被清理后重建
        assert temp_dir.exists()
        assert not temp_file.exists()
        assert list(temp_dir.iterdir()) == []

    @patch("app.workers.playwright_worker.cleanup_orphan_browsers")
    def test_shutdown_handles_temp_dir_not_exist(
        self, mock_cleanup, container_for_shutdown, project_root
    ):
        """临时目录不存在时 shutdown 不应报错。"""
        # 确保 temp_dir 不存在
        temp_dir = project_root / "temp"
        if temp_dir.exists():
            import shutil

            shutil.rmtree(temp_dir)

        # mock shutdown_worker
        with patch("app.workers.playwright_worker.shutdown_worker"):
            asyncio.run(container_for_shutdown.shutdown())
        # 不抛异常即通过

    @patch("app.workers.playwright_worker.cleanup_orphan_browsers")
    def test_shutdown_handles_worker_shutdown_error(
        self, mock_cleanup, container_for_shutdown
    ):
        """Worker 关闭异常时 shutdown 不应崩溃。"""
        with patch(
            "app.workers.playwright_worker.shutdown_worker",
            side_effect=RuntimeError("worker already dead"),
        ):
            asyncio.run(container_for_shutdown.shutdown())
        # 不抛异常即通过

    @patch("app.workers.playwright_worker.cleanup_orphan_browsers")
    @patch("app.container.shutil.rmtree", side_effect=PermissionError("denied"))
    def test_shutdown_handles_temp_cleanup_error(
        self, mock_rmtree, mock_cleanup, container_for_shutdown, project_root
    ):
        """临时目录清理失败时 shutdown 不应崩溃（覆盖 except 分支）。"""
        temp_dir = project_root / "temp"
        temp_dir.mkdir()
        (temp_dir / "subdir").mkdir()

        with patch("app.workers.playwright_worker.shutdown_worker"):
            asyncio.run(container_for_shutdown.shutdown())
        # 不抛异常即通过


# =====================================================================
# 集成验证
# =====================================================================


class TestIntegration:
    def test_startup_then_shutdown(self, container):
        """完整的 startup → shutdown 生命周期不应抛异常。"""
        container.task_registry.has_enabled_tasks = MagicMock(return_value=False)
        container.engine.start_scheduler = MagicMock()
        container.debug_manager.close = AsyncMock()
        container.ws_manager.close_all = AsyncMock()

        async def _lifecycle():
            with patch("app.workers.playwright_worker.cleanup_orphan_browsers"):
                await container.startup()
            await container.shutdown()

        asyncio.run(_lifecycle())

    def test_all_services_share_same_project_root(
        self, container, project_root, mock_classes
    ):
        """所有通过容器创建的服务都应基于相同的 project_root。"""
        assert mock_classes["ProfileService"].call_args[0][0] == project_root
        assert mock_classes["TaskService"].call_args[0][0] == project_root
        assert mock_classes["AutoStartService"].call_args[0][0] == project_root
        _ = container.debug_manager  # 触发延迟初始化
        assert mock_classes["DebugSessionManager"].call_args[0][0] == project_root
        assert mock_classes["ScheduleEngine"].call_args[0][0] == project_root
