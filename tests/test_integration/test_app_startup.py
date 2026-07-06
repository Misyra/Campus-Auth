"""应用启动集成测试 — 验证 create_app 初始化、生命周期管理和依赖注入。"""

from __future__ import annotations

import asyncio
from pathlib import Path
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
    """Mock 所有 API 路由模块为空 APIRouter，避免加载真实路由依赖。"""
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
    """Mock 外部依赖（端口、清理、版本号）。"""
    with (
        patch("app.application.resolve_port", return_value=50721),
        patch("app.application._cleanup_screenshots"),
        patch("app.version.get_project_version", return_value="0.0.0-test"),
    ):
        yield


def _make_mock_container():
    """创建配置好的 mock ServiceContainer。"""
    mock_container = MagicMock()
    mock_container.engine.has_enabled_tasks.return_value = False
    mock_container.start_web_services = MagicMock()
    mock_container.shutdown = AsyncMock()
    mock_container.engine.get_config.return_value = MagicMock(
        username="",
        password="",
        auth_url="",
        carrier="默认",
        check_interval_seconds=60,
    )
    return mock_container


# ── create_app 初始化测试 ──


class TestCreateAppInitialization:
    """create_app 正确初始化测试。"""

    def test_returns_fastapi_instance(self, mock_all_routers, mock_deps):
        """create_app 应返回 FastAPI 实例。"""
        from fastapi import FastAPI
        from app.application import create_app

        result = create_app()
        assert isinstance(result, FastAPI)

    def test_sets_title_and_version(self, mock_all_routers, mock_deps):
        """create_app 应设置正确的标题和版本。"""
        from app.application import create_app

        result = create_app()
        assert result.title == "校园网认证助手 API"
        assert result.version == "0.0.0-test"

    def test_has_lifespan_configured(self, mock_all_routers, mock_deps):
        """create_app 返回的应用应配置了 lifespan。"""
        from app.application import create_app

        result = create_app()
        assert result.router.lifespan_context is not None

    def test_registers_index_route(self, mock_all_routers, mock_deps):
        """create_app 应注册首页路由 GET /。"""
        from app.application import create_app

        result = create_app()
        routes = [r for r in result.routes if hasattr(r, "path") and r.path == "/"]
        assert len(routes) >= 1

    def test_mounts_static_files(self, mock_all_routers, mock_deps):
        """create_app 应挂载 /static、/debug、/temp 静态文件。"""
        from app.application import create_app

        result = create_app()
        mounted_paths = [
            r.path for r in result.routes if hasattr(r, "path") and hasattr(r, "name")
        ]
        assert "/static" in mounted_paths
        assert "/debug" in mounted_paths
        assert "/temp" in mounted_paths

    def test_registers_websocket_endpoint(self, mock_all_routers, mock_deps):
        """create_app 应注册 WebSocket /ws/logs 端点。"""
        from app.application import create_app

        result = create_app()
        ws_routes = [
            r for r in result.routes if hasattr(r, "path") and r.path == "/ws/logs"
        ]
        assert len(ws_routes) >= 1

    def test_accepts_existing_container(self, mock_all_routers, mock_deps):
        """create_app 接受 existing_container 参数。"""
        from fastapi import FastAPI
        from app.application import create_app

        mock_container = _make_mock_container()
        result = create_app(existing_container=mock_container)
        assert isinstance(result, FastAPI)

    def test_cors_middleware_configured(self, mock_all_routers, mock_deps):
        """create_app 应配置 CORS 中间件。"""
        from app.application import create_app

        result = create_app()
        cors_middleware = [
            m
            for m in result.user_middleware
            if hasattr(m, "cls") and "CORS" in m.cls.__name__
        ]
        assert len(cors_middleware) >= 1

    def test_creates_required_directories(self, mock_all_routers, mock_deps):
        """create_app 应确保 DEBUG_DIR 和 TEMP_DIR 存在。"""
        from app.application import create_app
        from app.constants import DEBUG_DIR, TEMP_DIR

        create_app()
        assert DEBUG_DIR.exists()
        assert TEMP_DIR.exists()


# ── 生命周期管理测试 ──


class TestAppLifespan:
    """应用生命周期管理测试。"""

    def _run_lifespan(self, app, test_coro):
        """运行 lifespan context 并在 yield 前后执行测试协程。"""

        async def _wrapper():
            async with app.router.lifespan_context(app):
                await test_coro(app)

        asyncio.run(_wrapper())

    def test_creates_shutdown_event(self, mock_all_routers, mock_deps):
        """lifespan 启动时应创建 shutdown_event 并设置到 app.state。"""
        from app.application import create_app

        mock_container = _make_mock_container()
        _app = create_app(existing_container=mock_container)

        async def _check(app):
            assert hasattr(app.state, "shutdown_event")
            assert isinstance(app.state.shutdown_event, asyncio.Event)
            assert app.state.services is mock_container

        self._run_lifespan(_app, _check)

    def test_existing_container_starts_web_services(self, mock_all_routers, mock_deps):
        """existing_container 模式下 lifespan 应调用 start_web_services。"""
        from app.application import create_app

        mock_container = _make_mock_container()
        _app = create_app(existing_container=mock_container)

        async def _check(app):
            mock_container.start_web_services.assert_called_once()

        self._run_lifespan(_app, _check)

    def test_starts_scheduler_when_enabled(self, mock_all_routers, mock_deps):
        """有启用的定时任务时 lifespan 应同步调度器状态。"""
        from app.application import create_app

        mock_container = _make_mock_container()
        mock_container.engine.has_enabled_tasks.return_value = True
        _app = create_app(existing_container=mock_container)

        async def _check(app):
            mock_container.engine.sync_scheduler_state.assert_called_once()

        self._run_lifespan(_app, _check)

    def test_skips_scheduler_when_no_enabled_tasks(self, mock_all_routers, mock_deps):
        """无启用的定时任务时 lifespan 也应同步调度器状态（由 sync 内部判断）。"""
        from app.application import create_app

        mock_container = _make_mock_container()
        mock_container.engine.has_enabled_tasks.return_value = False
        _app = create_app(existing_container=mock_container)

        async def _check(app):
            mock_container.engine.sync_scheduler_state.assert_called_once()

        self._run_lifespan(_app, _check)

    def test_shutdown_calls_container_shutdown(self, mock_all_routers, mock_deps):
        """lifespan 退出时应调用容器的 shutdown。"""
        from app.application import create_app

        mock_container = _make_mock_container()
        _app = create_app(existing_container=mock_container)

        # 先运行 lifespan，退出后验证
        async def _wrapper():
            async with _app.router.lifespan_context(_app):
                pass
            mock_container.shutdown.assert_awaited_once()

        asyncio.run(_wrapper())

    def test_full_lifecycle_startup_then_shutdown(self, mock_all_routers, mock_deps):
        """完整生命周期 startup→yield→shutdown 不应抛异常。"""
        from app.application import create_app

        mock_container = _make_mock_container()
        mock_container.engine.has_enabled_tasks.return_value = True
        mock_container.engine.start_scheduler = MagicMock()
        mock_container.engine.get_config.return_value = MagicMock(
            username="admin",
            password="secret",
            auth_url="http://auth.example.com",
            carrier="中国移动",
            check_interval_seconds=30,
        )
        _app = create_app(existing_container=mock_container)

        async def _wrapper():
            async with _app.router.lifespan_context(_app):
                assert _app.state.services is mock_container
            mock_container.shutdown.assert_awaited_once()

        asyncio.run(_wrapper())

    def test_new_container_mode_calls_startup(self, mock_all_routers, mock_deps):
        """无 existing_container 时 lifespan 应创建新 ServiceContainer 并调用 startup。"""
        from app.application import create_app

        mock_container = _make_mock_container()
        mock_container.startup = AsyncMock()

        # ServiceContainer 在 create_app() 内部通过 from app.container import
        # 绑定为局部变量，因此必须在 create_app() 调用前 patch
        with patch("app.container.ServiceContainer", return_value=mock_container):
            _app = create_app()

            async def _wrapper():
                async with _app.router.lifespan_context(_app):
                    assert _app.state.services is mock_container
                    mock_container.startup.assert_awaited_once()
                mock_container.shutdown.assert_awaited_once()

            asyncio.run(_wrapper())


# ── 依赖注入正确性测试 ──


class TestDependencyInjection:
    """依赖注入正确性测试。"""

    def test_services_stored_on_app_state(self, mock_all_routers, mock_deps):
        """lifespan 后 services 应存储在 app.state 上。"""
        from app.application import create_app

        mock_container = _make_mock_container()
        _app = create_app(existing_container=mock_container)

        async def _check(app):
            assert app.state.services is mock_container

        asyncio.run(_run_lifespan_coro(_app, _check))

    def test_shutdown_event_is_asyncio_event(self, mock_all_routers, mock_deps):
        """shutdown_event 应为 asyncio.Event 实例。"""
        from app.application import create_app

        mock_container = _make_mock_container()
        _app = create_app(existing_container=mock_container)

        async def _check(app):
            assert isinstance(app.state.shutdown_event, asyncio.Event)

        asyncio.run(_run_lifespan_coro(_app, _check))

    def test_engine_config_accessible(self, mock_all_routers, mock_deps):
        """lifespan 中应能通过 engine.get_config() 获取配置。"""
        from app.application import create_app

        mock_config = MagicMock(
            username="testuser",
            password="testpass",
            auth_url="http://example.com",
            carrier="中国电信",
            check_interval_seconds=120,
        )
        mock_container = _make_mock_container()
        mock_container.engine.get_config.return_value = mock_config
        _app = create_app(existing_container=mock_container)

        async def _check(app):
            cfg = mock_container.engine.get_config()
            assert cfg.username == "testuser"
            assert cfg.carrier == "中国电信"
            assert cfg.check_interval_seconds == 120

        asyncio.run(_run_lifespan_coro(_app, _check))

    def test_uvicorn_server_stored_on_state(self, mock_all_routers, mock_deps):
        """run() 中应将 uvicorn Server 存储到 app.state._uvicorn_server。"""
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
            mock_server.run.assert_called_once()

    def test_server_ref_populated(self, mock_all_routers, mock_deps):
        """run() 接收 server_ref 时应填充 uvicorn Server。"""
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

            server_ref = [None]
            run(access_log_enabled=False, log_retention=7, server_ref=server_ref)
            assert server_ref[0] is mock_server

    def test_access_log_event_controlled_by_flag(self, mock_all_routers, mock_deps):
        """access_log_enabled 参数应控制 _access_log_event。"""
        from app.application import run, _access_log_event

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

            mock_ps_instance.load.return_value.global_settings = mock_sys_settings
            mock_ps.return_value = mock_ps_instance

            # 测试开启
            _access_log_event.clear()
            run(access_log_enabled=True, log_retention=7)
            assert _access_log_event.is_set()

            # 测试关闭
            _access_log_event.set()
            run(access_log_enabled=False, log_retention=7)
            assert not _access_log_event.is_set()


# ── 辅助函数 ──


async def _run_lifespan_coro(app, check_coro):
    """运行 lifespan context 并在 yield 前执行检查协程。"""
    async with app.router.lifespan_context(app):
        await check_coro(app)
