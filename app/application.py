"""FastAPI 应用入口 — 工厂模式：create_app() 延迟加载 FastAPI。"""

import asyncio
import contextlib
import mimetypes
import os
import signal
import threading
import time
from contextlib import asynccontextmanager

# Windows 上 mimetypes 模块可能无法正确识别 .js 的 MIME 类型
mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("application/javascript", ".mjs")

from loguru import logger

from app.constants import (
    DEBUG_DIR,
    FRONTEND_DIR,
    LOGS_DIR,
    PROJECT_ROOT,
    SCREENSHOTS_DIR,
    TEMP_DIR,
)
from app.schemas import LoggingSettings
from app.utils.logging import LogConfigCenter, get_logger
from app.utils.ports import resolve_port

http_logger = get_logger("http", source="backend")
startup_logger = get_logger("startup", source="backend")
api_logger = get_logger("api", source="backend")

# temp 目录中截图的最大保留天数
_TEMP_SCREENSHOT_MAX_AGE_DAYS = 7


def _cleanup_screenshots() -> None:
    """启动时清理截图文件：
    1. temp/ 目录中超过保留天数的截图文件。
    2. screenshots/ 目录中非当天的日期子目录。
    """
    # --- 清理 temp/ 中的过期截图 ---
    try:
        if TEMP_DIR.exists():
            cutoff = time.time() - _TEMP_SCREENSHOT_MAX_AGE_DAYS * 86400
            removed_temp = 0
            for f in TEMP_DIR.iterdir():
                if (
                    f.is_file()
                    and f.suffix in (".png", ".jpg", ".jpeg")
                    and f.stat().st_mtime < cutoff
                ):
                    f.unlink()
                    removed_temp += 1
            if removed_temp:
                startup_logger.debug(
                    "清理 temp 截图: 删除 {} 个过期文件", removed_temp
                )
    except Exception as exc:
        startup_logger.warning("清理 temp 截图失败: {}", exc)

    # --- 清理 screenshots/ 中的非当天目录 ---
    try:
        if SCREENSHOTS_DIR.exists():
            import shutil
            from datetime import datetime

            today = datetime.now().strftime("%Y-%m-%d")
            removed_dirs = 0
            for d in SCREENSHOTS_DIR.iterdir():
                if d.is_dir() and d.name != today:
                    shutil.rmtree(d, ignore_errors=True)
                    removed_dirs += 1
            if removed_dirs:
                startup_logger.debug(
                    "清理旧截图: 删除 {} 个日期目录", removed_dirs
                )
    except Exception as exc:
        startup_logger.warning("清理旧截图失败: {}", exc)


_access_log_event = threading.Event()  # 默认未 set（即关闭）

# 模块级占位符，run() 调用后设为实际 FastAPI 实例
app = None


# ==================== 工厂辅助函数 ====================


def _create_lifespan(existing_container, boot_engine=False):
    """创建 FastAPI 生命周期管理器。

    Args:
        existing_container: 已有的 ServiceContainer（轻量模式升级时使用），或 None。
        boot_engine: 是否在 lifespan 内启动监控引擎（仅 existing_container 分支有效）。

    Returns:
        async context manager 函数，供 FastAPI(lifespan=...) 使用。
    """

    @asynccontextmanager
    async def lifespan(app_instance):
        """应用生命周期管理"""
        start = time.perf_counter()
        startup_logger.debug("FastAPI 启动: 创建 shutdown_event")

        # 创建 shutdown_event 用于优雅关闭
        shutdown_event = asyncio.Event()
        app_instance.state.shutdown_event = shutdown_event

        startup_logger.debug("FastAPI 启动: 开始设置服务引导")

        if existing_container is not None:
            services = existing_container
            # 升级路径同样清理上一次崩溃残留的浏览器进程
            from app.workers.playwright_worker import cleanup_orphan_browsers

            cleanup_orphan_browsers()
            services.start_web_services()
            # 引擎线程必须始终运行（处理配置保存等命令），监控按需启动
            services.engine.start_thread()
            if boot_engine and not services.engine._is_monitoring:
                services.engine.boot()
            services.engine.sync_scheduler_state()
        else:
            from app.container import ServiceContainer

            services = ServiceContainer(PROJECT_ROOT)
            await services.startup()

        app_instance.state.services = services

        # 配置诊断
        settings_path = PROJECT_ROOT / "config" / "settings.json"
        startup_logger.debug(
            "settings.json 路径: {} (存在={}, 大小={})",
            settings_path,
            settings_path.exists(),
            settings_path.stat().st_size if settings_path.exists() else 0,
        )
        cfg = services.engine.get_config()
        startup_logger.debug(
            "当前配置: 用户={}, 密码={}, 认证={}, 运营商={}, 间隔={}min",
            f"'{cfg.credentials.username}'" if cfg.credentials.username else "(空)",
            "已设置" if cfg.credentials.password else "(空)",
            f"'{cfg.credentials.auth_url}'" if cfg.credentials.auth_url else "(空)",
            cfg.credentials.isp,
            cfg.monitor.check_interval_seconds // 60,
        )

        # 检查 cryptography 库是否可用
        try:
            import cryptography  # noqa: F401
        except ImportError:
            startup_logger.warning(
                "cryptography 库未安装，密码将以明文存储（非加密），建议安装 cryptography"
            )

        # 启动时清理截图文件
        _cleanup_screenshots()

        startup_logger.info(
            "FastAPI 启动成功 (耗时 {:.3f}s)",
            time.perf_counter() - start,
        )

        # 创建后台任务等待 shutdown_event，当事件被设置时触发应用关闭
        async def _wait_shutdown():
            await shutdown_event.wait()
            # 通过设置 uvicorn Server.should_exit 触发优雅关闭，
            # 而非发送 SIGTERM（后者会被 main.py 的信号处理器拦截并 os._exit）
            _server = getattr(app_instance.state, "_uvicorn_server", None)
            if _server is not None:
                _server.should_exit = True
            else:
                # 回退：无法获取 server 引用。
                # Windows 上 os.kill(pid, SIGTERM) 实为 TerminateProcess 硬终止，
                # 会跳过 lifespan yield 之后的 services.shutdown() 清理逻辑。
                # 因此先同步执行 services.shutdown()，再 force_exit。
                try:
                    await app_instance.state.services.shutdown()
                except Exception as e:
                    startup_logger.exception("回退关闭异常: {}", e)
                from app.utils.shutdown import force_exit
                force_exit(0)

        shutdown_waiter = asyncio.create_task(_wait_shutdown())

        yield

        # 取消等待任务
        shutdown_waiter.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await shutdown_waiter

        startup_logger.debug("FastAPI 关闭: 开始停止服务")
        await services.shutdown()
        startup_logger.info("FastAPI 关闭完成")

    return lifespan


def _register_routes(app) -> None:
    """注册所有 API 路由到 FastAPI 应用。

    Args:
        app: FastAPI 应用实例。
    """
    from app.api import (
        autostart,
        browsers,
        config,
        debug,
        history,
        icons,
        install_playwright,
        monitor,
        ocr,
        profiles,
        repo,
        scheduled_tasks,
        scripts,
        system,
        tasks,
        tools,
    )

    app.include_router(monitor.router)
    app.include_router(config.router)
    app.include_router(tasks.router)
    app.include_router(profiles.router)
    app.include_router(debug.router)
    app.include_router(repo.router)
    app.include_router(system.router)
    app.include_router(autostart.router)
    app.include_router(ocr.router)
    app.include_router(tools.router)
    app.include_router(scripts.router)
    app.include_router(scheduled_tasks.router)
    app.include_router(history.router)
    app.include_router(browsers.router)
    app.include_router(icons.router)
    app.include_router(install_playwright.router)


def _register_static(app) -> None:
    """注册首页路由和静态文件挂载。

    Args:
        app: FastAPI 应用实例。
    """
    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(FRONTEND_DIR / "index.html")

    # 确保挂载目录存在（发布版本解压后这些目录可能不存在）
    for _dir in (DEBUG_DIR, TEMP_DIR):
        _dir.mkdir(parents=True, exist_ok=True)

    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")
    app.mount("/debug", StaticFiles(directory=DEBUG_DIR), name="debug")
    app.mount("/temp", StaticFiles(directory=TEMP_DIR), name="temp")


def create_app(existing_container=None, boot_engine=False):
    """创建 FastAPI 应用实例。

    Args:
        existing_container: 已有的 ServiceContainer（轻量模式→完整模式转换时使用）。
            若不为 None，复用该容器并启动 Web 服务和调度器；
            若为 None，创建新的 ServiceContainer 并执行完整启动。
        boot_engine: 是否在 lifespan 内启动监控引擎（仅 existing_container 分支有效）。
    """
    from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import JSONResponse

    from app.version import get_project_version

    # ==================== 生命周期 ====================

    lifespan = _create_lifespan(existing_container, boot_engine=boot_engine)

    _app = FastAPI(
        title="校园网认证助手 API",
        version=get_project_version(PROJECT_ROOT),
        lifespan=lifespan,
    )

    # ==================== CORS 配置 ====================

    _cors_port = resolve_port()
    _app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            f"http://127.0.0.1:{_cors_port}",
            f"http://localhost:{_cors_port}",
        ],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type"],
    )

    # ==================== 全局异常处理 ====================

    @_app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        """捕获所有未处理异常，返回统一 JSON 格式。"""
        api_logger.error(
            "未处理异常: {} {}", request.method, request.url.path, exc_info=True
        )
        return JSONResponse(
            status_code=500,
            content={"detail": f"服务器内部错误: {type(exc).__name__}"},
        )

    @_app.exception_handler(ValueError)
    async def value_error_handler(request: Request, exc: ValueError):
        """业务逻辑校验错误统一返回 400。"""
        return JSONResponse(
            status_code=400,
            content={"detail": str(exc)},
        )

    # ==================== 中间件 ====================

    @_app.middleware("http")
    async def request_logging_middleware(request: Request, call_next):
        start = time.perf_counter()
        try:
            response = await call_next(request)
            if _access_log_event.is_set():
                duration_ms = (time.perf_counter() - start) * 1000
                http_logger.debug(
                    "{} {} -> {} ({:.1f}ms)",
                    request.method,
                    request.url.path,
                    response.status_code,
                    duration_ms,
                )
            return response
        except Exception:
            duration_ms = (time.perf_counter() - start) * 1000
            if _access_log_event.is_set():
                http_logger.warning(
                    "{} {} 异常 ({:.1f}ms)",
                    request.method,
                    request.url.path,
                    duration_ms,
                )
            http_logger.debug(
                "{} {} 异常 ({:.1f}ms)",
                request.method,
                request.url.path,
                duration_ms,
                exc_info=True,
            )
            raise

    # ==================== WebSocket ====================

    @_app.websocket("/ws/logs")
    async def websocket_logs(websocket: WebSocket):
        from app.api.ws import websocket_logs_handler
        services = _app.state.services
        await websocket_logs_handler(websocket, services.ws_manager)

    # ==================== 路由 + 静态文件 ====================

    _register_routes(_app)
    _register_static(_app)

    return _app


# ==================== 启动入口 ====================


def run(
    access_log_enabled: bool | None = None,
    log_retention: int | None = None,
    existing_container=None,
    server_ref: list | None = None,
    boot_engine: bool = False,
    logging_settings: LoggingSettings | None = None,
) -> None:
    """启动 uvicorn Web 服务器。

    Args:
        server_ref: 若传入，运行后 [0] 为 uvicorn.Server 实例（供外部停止）。
        boot_engine: 是否在 lifespan 内启动监控引擎（仅 existing_container 分支有效）。
    """
    global app

    import uvicorn

    # 使用调用方传入的日志配置，或从 settings.json 读取
    if logging_settings is None and (access_log_enabled is None or log_retention is None):
        try:
            if existing_container is not None:
                profile_service = existing_container.profile_service
            else:
                from app.services.profile_service import get_profile_service

                profile_service = get_profile_service(PROJECT_ROOT)
            logging_settings = profile_service.load().global_config.logging
        except Exception:
            startup_logger.warning("读取日志配置失败，使用默认值", exc_info=True)

    # 填充未传入的参数
    if access_log_enabled is None:
        access_log_enabled = bool(logging_settings.access_log) if logging_settings else False
    if log_retention is None:
        log_retention = max(1, logging_settings.log_retention_days) if logging_settings else 7

    log_center = LogConfigCenter.get_instance()
    log_center.initialize({"level": logging_settings.level if logging_settings else "INFO"}, source="backend")

    # 压制第三方库的 DEBUG 日志
    import logging

    logging.getLogger("PIL").setLevel(logging.WARNING)

    log_dir = LOGS_DIR
    try:
        log_center.add_file_handler(str(log_dir), retention_days=log_retention)
        startup_logger.info("日志文件: {}", log_dir / "app.log")
    except Exception:
        startup_logger.warning("日志系统初始化失败", exc_info=True)

    if access_log_enabled:
        _access_log_event.set()
    else:
        _access_log_event.clear()

    # 将 uvicorn 的标准 logging 路由到 loguru，确保日志格式统一
    class _UvicornLogHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            logger.opt(exception=record.exc_info).log(
                record.levelno, record.getMessage()
            )

    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        log = logging.getLogger(name)
        log.handlers.clear()
        log.propagate = False
        log.addHandler(_UvicornLogHandler())

    # 创建 FastAPI 应用
    _app = create_app(existing_container=existing_container, boot_engine=boot_engine)
    app = _app

    # 使用 Server 实例而非 uvicorn.run()，以便 _wait_shutdown 可通过
    # server.should_exit = True 触发优雅关闭（避免 SIGTERM → os._exit 路径）
    uv_config = uvicorn.Config(
        _app,
        host="127.0.0.1",
        port=resolve_port(),
        reload=False,
        log_level="warning",
        access_log=False,
        ws_max_size=65536,
    )
    uv_server = uvicorn.Server(uv_config)
    _app.state._uvicorn_server = uv_server
    if server_ref is not None:
        server_ref[0] = uv_server
    uv_server.run()


if __name__ == "__main__":
    run()
