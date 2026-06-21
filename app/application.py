"""FastAPI 应用入口 — 工厂模式：create_app() 延迟加载 FastAPI。"""

import asyncio
import contextlib
import json
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
from app.utils.logging import LogConfigCenter, get_logger
from app.utils.ports import resolve_port

http_logger = get_logger("http", source="backend")
startup_logger = get_logger("startup", source="backend")
ws_logger = get_logger("ws", source="backend")

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
                startup_logger.info(
                    "启动时清理 temp 截图: 删除 {} 个过期文件", removed_temp
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
                startup_logger.info(
                    "启动时清理旧截图: 删除 {} 个日期目录", removed_dirs
                )
    except Exception as exc:
        startup_logger.warning("清理旧截图失败: {}".format(exc))


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
        startup_logger.info("FastAPI 启动: 创建 shutdown_event")

        # 创建 shutdown_event 用于优雅关闭
        shutdown_event = asyncio.Event()
        app_instance.state.shutdown_event = shutdown_event

        startup_logger.info("FastAPI 启动: 开始设置服务引导")

        if existing_container is not None:
            services = existing_container
            services.start_web_services()
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
        cfg = services.monitor_service.get_config()
        startup_logger.info(
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
                "cryptography 库未安装，密码仅使用 Base64 编码存储（非加密），"
                "建议安装: pip install cryptography"
            )

        # 启动时清理截图文件
        _cleanup_screenshots()

        startup_logger.info(
            "FastAPI 启动: 完成，耗时 {:.3f}s",
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
                # 回退：发送 SIGTERM（仅在无法获取 server 引用时）
                if hasattr(signal, "SIGTERM"):
                    os.kill(os.getpid(), signal.SIGTERM)
                else:
                    os._exit(0)

        shutdown_waiter = asyncio.create_task(_wait_shutdown())

        yield

        # 取消等待任务
        shutdown_waiter.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await shutdown_waiter

        startup_logger.info("FastAPI 关闭: 正在停止服务...")
        await services.shutdown()
        startup_logger.info("FastAPI 关闭: 完成")

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
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type"],
    )

    # ==================== 中间件 ====================

    @_app.middleware("http")
    async def request_logging_middleware(request: Request, call_next):
        start = time.perf_counter()
        try:
            response = await call_next(request)
            if _access_log_event.is_set():
                duration_ms = (time.perf_counter() - start) * 1000
                http_logger.info(
                    "{} {} -> {} ({:.1f}ms)",
                    request.method,
                    request.url.path,
                    response.status_code,
                    duration_ms,
                )
            return response
        except Exception:
            duration_ms = (time.perf_counter() - start) * 1000
            http_logger.exception(
                "{} {} -> EXCEPTION ({:.1f}ms)",
                request.method,
                request.url.path,
                duration_ms,
            )
            raise

    # ==================== WebSocket ====================

    @_app.websocket("/ws/logs")
    async def websocket_logs(websocket: WebSocket):
        services = _app.state.services
        ws_mgr = services.ws_manager
        monitor_svc = services.monitor_service

        await ws_mgr.connect(websocket)
        try:
            while True:
                raw = await websocket.receive_text()
                # WebSocket 消息大小预检，防止超大消息导致内存问题
                if len(raw) > 65536:
                    ws_logger.warning(
                        "WebSocket 消息过大 ({} bytes)，断开连接", len(raw)
                    )
                    await ws_mgr.disconnect(websocket)
                    return
                try:
                    msg = json.loads(raw)
                    msg_type = msg.get("type")
                    if msg_type == "ping":
                        # 应用层 ping/pong，防止代理切断空闲连接
                        await websocket.send_text('{"type":"pong"}')
                    elif msg_type == "frontend_log":
                        d = msg.get("data", {})
                        message_text = str(d.get("message", ""))[:10000]
                        scope = str(d.get("scope", "?"))[:200]
                        if message_text:
                            monitor_svc.record_log(
                                message=f"[{scope}] {message_text}",
                                level=str(d.get("level", "INFO"))[:20],
                                source="frontend",
                            )
                except json.JSONDecodeError:
                    ws_logger.debug("WebSocket 消息解析失败", exc_info=True)
                except Exception:
                    ws_logger.debug("WebSocket 消息处理异常", exc_info=True)
        except WebSocketDisconnect:
            await ws_mgr.disconnect(websocket)
        except Exception:
            ws_logger.exception("WebSocket 通信异常")
            await ws_mgr.disconnect(websocket)

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
) -> None:
    """启动 uvicorn Web 服务器。

    Args:
        server_ref: 若传入，运行后 [0] 为 uvicorn.Server 实例（供外部停止）。
        boot_engine: 是否在 lifespan 内启动监控引擎（仅 existing_container 分支有效）。
    """
    global app

    import uvicorn

    sys_settings = None
    if access_log_enabled is None or log_retention is None:
        # 调用方未传入日志配置，从 settings.json 读取
        try:
            from app.services.profile_service import ProfileService

            profile_service = ProfileService(PROJECT_ROOT)
            sys_logging = profile_service.load().config.logging
            if access_log_enabled is None:
                access_log_enabled = bool(sys_logging.access_log)
            if log_retention is None:
                log_retention = max(1, sys_logging.log_retention_days)
        except Exception:
            startup_logger.warning("读取日志配置失败，使用默认值", exc_info=True)
            if access_log_enabled is None:
                access_log_enabled = False
            if log_retention is None:
                log_retention = 7

    log_center = LogConfigCenter.get_instance()
    log_center.initialize({"level": "INFO"}, source="backend")

    # 从 settings.json 恢复 source 级别配置
    if sys_settings is not None and hasattr(sys_settings, "source_levels") and sys_settings.source_levels:
        for src, lvl in sys_settings.source_levels.items():
            with contextlib.suppress(ValueError):
                log_center.set_source_level(src, lvl)

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
