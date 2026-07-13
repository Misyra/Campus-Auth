"""F07: boot() 与 DashboardSink 注入顺序测试。

验证 boot_engine 标记正确透传，且 boot() 在 start_web_services() 之后调用。
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import APIRouter

# ── 辅助 fixtures ──

_ROUTER_NAMES = [
    "monitor",
    "config",
    "tasks",
    "profiles",
    "debug",
    "repo",
    "system",
    "autostart",
    "ocr",
    "tools",
    "scripts",
    "scheduled_tasks",
    "history",
]


@pytest.fixture
def mock_all_routers():
    """Mock 所有 API 路由模块为空 APIRouter。"""
    patches = []
    for name in _ROUTER_NAMES:
        p = patch(f"app.api.{name}.router", new_callable=APIRouter)
        p.start()
        patches.append(p)
    yield
    for p in patches:
        p.stop()


@pytest.fixture
def mock_deps():
    """Mock 外部依赖。"""
    with (
        patch("app.application.resolve_port", return_value=50721),
        patch("app.application._cleanup_temp_screenshots"),
        patch("app.application._cleanup_dated_screenshots"),
        patch("app.version.get_project_version", return_value="0.0.0-test"),
    ):
        yield


def _make_mock_container():
    """创建配置好的 mock ServiceContainer。"""
    mock_container = MagicMock()
    mock_container.engine.has_enabled_tasks.return_value = False
    mock_container.engine.is_monitoring = False
    mock_container.start_web_services = MagicMock()
    mock_container.engine.boot = MagicMock()
    mock_container.shutdown = AsyncMock()
    mock_container.monitor_service.get_config.return_value = MagicMock(
        username="",
        password="",
        auth_url="",
        carrier="默认",
        check_interval_seconds=60,
    )
    return mock_container


# ── boot_engine 标记透传 ──


class TestBootEnginePropagation:
    """boot_engine 参数从 run() → create_app() → _create_lifespan() 正确透传。"""

    def test_run_passes_boot_engine_to_create_app(self, mock_all_routers, mock_deps):
        """run() 应将 boot_engine 传递给 create_app()。"""
        from app.application import run

        mock_server = MagicMock()
        mock_server.run = MagicMock()

        with (
            patch("app.application.create_app") as mock_create,
            patch("app.application.resolve_port", return_value=50721),
            patch("app.application.LogConfigCenter") as mock_lcc,
            patch("app.services.profile_service.ProfileService") as mock_ps,
            patch("uvicorn.Config"),
            patch("uvicorn.Server", return_value=mock_server),
        ):
            mock_app = MagicMock()
            mock_app.state = MagicMock()
            mock_create.return_value = mock_app
            mock_lcc.get_instance.return_value = MagicMock()
            mock_ps_instance = MagicMock()
            mock_sys_settings = MagicMock()
            mock_sys_settings.access_log = False
            mock_sys_settings.log_retention_days = 7

            mock_ps_instance.load.return_value.global_settings = mock_sys_settings
            mock_ps.return_value = mock_ps_instance

            run(
                access_log_enabled=False,
                log_retention=7,
                boot_engine=True,
            )
            mock_create.assert_called_once()
            _, kwargs = mock_create.call_args
            assert kwargs.get("boot_engine") is True

    def test_run_default_boot_engine_false(self, mock_all_routers, mock_deps):
        """run() 默认 boot_engine=False。"""
        from app.application import run

        mock_server = MagicMock()
        mock_server.run = MagicMock()

        with (
            patch("app.application.create_app") as mock_create,
            patch("app.application.resolve_port", return_value=50721),
            patch("app.application.LogConfigCenter") as mock_lcc,
            patch("app.services.profile_service.ProfileService") as mock_ps,
            patch("uvicorn.Config"),
            patch("uvicorn.Server", return_value=mock_server),
        ):
            mock_app = MagicMock()
            mock_app.state = MagicMock()
            mock_create.return_value = mock_app
            mock_lcc.get_instance.return_value = MagicMock()
            mock_ps_instance = MagicMock()
            mock_sys_settings = MagicMock()
            mock_sys_settings.access_log = False
            mock_sys_settings.log_retention_days = 7

            mock_ps_instance.load.return_value.global_settings = mock_sys_settings
            mock_ps.return_value = mock_ps_instance

            run(access_log_enabled=False, log_retention=7)
            _, kwargs = mock_create.call_args
            assert kwargs.get("boot_engine") is False


# ── lifespan 内 boot() 调用顺序 ──


class TestLifespanBootOrder:
    """lifespan 内 boot() 在 start_web_services() 之后调用。"""

    def _run_lifespan(self, app):
        """运行 lifespan context。"""

        async def _wrapper():
            async with app.router.lifespan_context(app):
                pass

        asyncio.run(_wrapper())

    def test_boot_called_after_start_web_services_when_flag_true(
        self, mock_all_routers, mock_deps
    ):
        """boot_engine=True 时，boot() 应在 start_web_services() 之后调用。"""
        from app.application import create_app

        mock_container = _make_mock_container()
        _app = create_app(existing_container=mock_container, boot_engine=True)

        self._run_lifespan(_app)

        mock_container.start_web_services.assert_called_once()
        mock_container.engine.boot.assert_called_once()

    def test_boot_not_called_when_flag_false(self, mock_all_routers, mock_deps):
        """boot_engine=False 时，lifespan 不应调用 boot()，但应启动引擎线程。"""
        from app.application import create_app

        mock_container = _make_mock_container()
        _app = create_app(existing_container=mock_container, boot_engine=False)

        self._run_lifespan(_app)

        mock_container.start_web_services.assert_called_once()
        mock_container.engine.start_thread.assert_called_once()
        mock_container.engine.boot.assert_not_called()

    def test_boot_not_called_when_already_monitoring(self, mock_all_routers, mock_deps):
        """引擎已在监控时，即使 boot_engine=True 也不应重复调用 boot()，但应启动线程。"""
        from app.application import create_app

        mock_container = _make_mock_container()
        mock_container.engine.is_monitoring = True
        _app = create_app(existing_container=mock_container, boot_engine=True)

        self._run_lifespan(_app)

        mock_container.start_web_services.assert_called_once()
        mock_container.engine.start_thread.assert_called_once()
        mock_container.engine.boot.assert_not_called()

    def test_boot_default_flag_false(self, mock_all_routers, mock_deps):
        """create_app() 默认 boot_engine=False，不调用 boot()，但应启动引擎线程。"""
        from app.application import create_app

        mock_container = _make_mock_container()
        _app = create_app(existing_container=mock_container)

        self._run_lifespan(_app)

        mock_container.start_web_services.assert_called_once()
        mock_container.engine.start_thread.assert_called_once()
        mock_container.engine.boot.assert_not_called()

    def test_call_order_start_web_services_then_boot(self, mock_all_routers, mock_deps):
        """验证调用顺序：start_web_services → start_thread → boot。"""
        from app.application import create_app

        mock_container = _make_mock_container()
        call_order = []
        mock_container.start_web_services.side_effect = lambda: call_order.append(
            "start_web_services"
        )
        mock_container.engine.start_thread.side_effect = lambda: call_order.append(
            "start_thread"
        )
        mock_container.engine.boot.side_effect = lambda: call_order.append("boot")

        _app = create_app(existing_container=mock_container, boot_engine=True)

        self._run_lifespan(_app)

        assert call_order == ["start_web_services", "start_thread", "boot"]


# ── _run_full 不再直接调 boot ──


class TestRunFullNoDirectBoot:
    """main.py _run_full 不再直接调用 container.engine.boot()。"""

    def test_run_full_does_not_call_boot_directly(self):
        """_run_full 应将 boot_engine 传递给 run()，而非直接调 boot()。"""
        from app.schemas import (
            AppConfig,
            ApplicationContext,
            LaunchContext,
            LaunchSource,
        )
        from app.services.launcher import launch_full as _run_full

        ctx = ApplicationContext(
            config=AppConfig(),
            launch=LaunchContext(source=LaunchSource.MANUAL),
        )
        logger = MagicMock()

        with (
            patch("app.utils.ports.resolve_port", return_value=50721),
            patch("app.container.ServiceContainer") as mock_container_cls,
            patch("app.application.run") as mock_run,
            patch("app.services.launcher.get_runtime_features") as mock_features,
            patch("app.services.launcher.signal.signal"),
            patch("app.services.launcher.force_exit"),
        ):
            mock_container = MagicMock()
            mock_container_cls.return_value = mock_container
            mock_features.return_value = MagicMock(
                tray_enabled=False, browser_enabled=False
            )
            mock_container.profile_service.load.return_value.global_config.logging.access_log = False
            mock_container.profile_service.load.return_value.global_config.logging.log_retention_days = 7

            # should_boot_engine=True
            _run_full(ctx, should_boot_engine=True, logger=logger, startup_begin=0.0)

            # 不应直接调用 engine.boot
            mock_container.engine.boot.assert_not_called()

            # 应传递 boot_engine=True 给 run()
            mock_run.assert_called_once()
            _, kwargs = mock_run.call_args
            assert kwargs.get("boot_engine") is True

    def test_run_full_passes_boot_engine_false(self):
        """should_boot_engine=False 时传递 boot_engine=False。"""
        from app.schemas import (
            AppConfig,
            ApplicationContext,
            LaunchContext,
            LaunchSource,
        )
        from app.services.launcher import launch_full as _run_full

        ctx = ApplicationContext(
            config=AppConfig(),
            launch=LaunchContext(source=LaunchSource.MANUAL),
        )
        logger = MagicMock()

        with (
            patch("app.utils.ports.resolve_port", return_value=50721),
            patch("app.container.ServiceContainer") as mock_container_cls,
            patch("app.application.run") as mock_run,
            patch("app.services.launcher.get_runtime_features") as mock_features,
            patch("app.services.launcher.signal.signal"),
            patch("app.services.launcher.force_exit"),
        ):
            mock_container = MagicMock()
            mock_container_cls.return_value = mock_container
            mock_features.return_value = MagicMock(
                tray_enabled=False, browser_enabled=False
            )
            mock_container.profile_service.load.return_value.global_config.logging.access_log = False
            mock_container.profile_service.load.return_value.global_config.logging.log_retention_days = 7

            _run_full(ctx, should_boot_engine=False, logger=logger, startup_begin=0.0)

            mock_container.engine.boot.assert_not_called()

            _, kwargs = mock_run.call_args
            assert kwargs.get("boot_engine") is False


# ── container.startup() 内部顺序已正确，不需要修改 ──


class TestContainerStartupOrder:
    """container.startup() 内部顺序已正确（先 start_web_services 后 boot）。"""

    def test_startup_calls_start_web_services_before_boot(self):
        """startup() 应先调 start_web_services() 再调 engine.boot()。"""

        from app.container import ServiceContainer

        with (
            patch.object(ServiceContainer, "__init__", lambda self, *a, **kw: None),
        ):
            container = ServiceContainer.__new__(ServiceContainer)
            container._web_services_started = False
            container._log_handler_id = None
            container._ws_drain_task = None
            container._shutdown_done = False
            container.task_registry = MagicMock()
            container.task_registry.has_enabled_tasks.return_value = False
            container.engine = MagicMock()
            container.task_executor = MagicMock()

            call_order = []

            def _mock_start_web():
                call_order.append("start_web_services")

            container.start_web_services = _mock_start_web
            container.engine.boot.side_effect = lambda: call_order.append("boot")

            asyncio.run(container.startup())

            assert call_order[0] == "start_web_services"
            assert call_order[1] == "boot"
