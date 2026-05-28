"""FastAPI 应用入口 — 精简为核心框架：app 创建、lifespan、中间件、WebSocket、静态文件。"""

from __future__ import annotations

import json
import logging
import mimetypes
import os
import time
from contextlib import asynccontextmanager

# Windows 上 mimetypes 模块可能无法正确识别 .js 的 MIME 类型
mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("application/javascript", ".mjs")

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from src.utils.logging import LogConfigCenter, get_logger
from src.version import get_project_version

from .constants import FRONTEND_DIR, LOGS_DIR, PROJECT_ROOT, TEMP_DIR
from .container import ServiceContainer
from .routers import backup, config, debug, monitor, profiles, repo, scripts, system, tasks, tools

http_logger = get_logger("backend.http", side="BACKEND")
startup_logger = get_logger("backend.startup", side="BACKEND")


# ==================== 生命周期管理 ====================


@asynccontextmanager
async def lifespan(app_instance):
    """应用生命周期管理"""
    start = time.perf_counter()
    startup_logger.info("FastAPI 启动: 开始设置服务引导")

    services = ServiceContainer(PROJECT_ROOT)
    app_instance.state.services = services

    # 配置迁移和诊断
    settings_path = PROJECT_ROOT / "settings.json"
    startup_logger.info(
        "settings.json 路径: %s (存在=%s, 大小=%d)",
        settings_path,
        settings_path.exists(),
        settings_path.stat().st_size if settings_path.exists() else 0,
    )
    try:
        services.monitor_service.reload_config()
        config = services.monitor_service.get_config()
        startup_logger.info(
            "当前配置: 用户=%s, 密码=%s, 认证=%s, 运营商=%s, 间隔=%dmin, 自动监控=%s",
            f"'{config.username}'" if config.username else "(空)",
            "已设置" if config.password else "(空)",
            f"'{config.auth_url}'" if config.auth_url else "(空)",
            config.carrier,
            config.check_interval_seconds,
            config.auto_start,
        )
    except Exception as exc:
        startup_logger.warning("配置迁移失败: %s", exc)

    # 检查 cryptography 库是否可用
    try:
        import cryptography  # noqa: F401
    except ImportError:
        startup_logger.warning(
            "cryptography 库未安装，密码仅使用 Base64 编码存储（非加密），"
            "建议安装: pip install cryptography"
        )

    await services.startup()

    startup_logger.info(
        "FastAPI 启动: 完成，耗时 %.3fs",
        time.perf_counter() - start,
    )
    yield

    startup_logger.info("FastAPI 关闭: 正在停止服务...")
    await services.shutdown()
    startup_logger.info("FastAPI 关闭: 完成")


app = FastAPI(
    title="校园网认证助手 API",
    version=get_project_version(PROJECT_ROOT),
    lifespan=lifespan,
)


# ==================== CORS 配置 ====================


def _resolve_port() -> int:
    raw = os.getenv("APP_PORT", "").strip()
    if raw:
        try:
            port = int(raw)
            if 1 <= port <= 65535:
                return port
        except ValueError:
            pass

    settings_path = PROJECT_ROOT / "settings.json"
    if settings_path.exists():
        try:
            data = json.loads(settings_path.read_text(encoding="utf-8"))
            app_port = data.get("system", {}).get("app_port")
            if app_port is not None:
                port = int(app_port)
                if 1 <= port <= 65535:
                    return port
        except Exception:
            pass

    return 50721


_cors_port = _resolve_port()
app.add_middleware(
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


_access_log_enabled = False


@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    start = time.perf_counter()
    try:
        response = await call_next(request)
        if _access_log_enabled:
            duration_ms = (time.perf_counter() - start) * 1000
            http_logger.info(
                "%s %s -> %s (%.1fms)",
                request.method,
                request.url.path,
                response.status_code,
                duration_ms,
            )
        return response
    except Exception:
        duration_ms = (time.perf_counter() - start) * 1000
        http_logger.exception(
            "%s %s -> EXCEPTION (%.1fms)",
            request.method,
            request.url.path,
            duration_ms,
        )
        raise


# ==================== WebSocket ====================


@app.websocket("/ws/logs")
async def websocket_logs(websocket: WebSocket):
    services = app.state.services
    ws_mgr = services.ws_manager
    monitor_svc = services.monitor_service

    await ws_mgr.connect(websocket)
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
                if msg.get("type") == "frontend_log":
                    d = msg.get("data", {})
                    message_text = str(d.get("message", ""))[:10000]
                    scope = str(d.get("scope", "?"))[:200]
                    if message_text:
                        monitor_svc._push_log(
                            message=f"[{scope}] {message_text}",
                            level=str(d.get("level", "INFO"))[:20],
                            source="frontend",
                        )
            except (json.JSONDecodeError, KeyError):
                pass
    except WebSocketDisconnect:
        await ws_mgr.disconnect(websocket)
    except Exception:
        await ws_mgr.disconnect(websocket)


# ==================== 路由注册 ====================


app.include_router(monitor.router)
app.include_router(config.router)
app.include_router(tasks.router)
app.include_router(profiles.router)
app.include_router(debug.router)
app.include_router(backup.router)
app.include_router(repo.router)
app.include_router(system.router)
app.include_router(tools.router)
app.include_router(scripts.router)


# ==================== 首页和静态文件 ====================


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "index.html")


app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")
app.mount("/logs", StaticFiles(directory=LOGS_DIR), name="logs")
app.mount("/temp", StaticFiles(directory=TEMP_DIR), name="temp")


# ==================== 启动入口 ====================


def run() -> None:
    import uvicorn

    from .profile_service import ProfileService

    profile_service = ProfileService(PROJECT_ROOT)

    try:
        sys_settings = profile_service.load().system
        log_level = sys_settings.backend_log_level or "WARNING"
        access_log_enabled = bool(sys_settings.access_log)
        log_retention = max(1, sys_settings.log_retention_days)
    except Exception:
        startup_logger.warning("读取日志配置失败，使用默认值", exc_info=True)
        log_level = "WARNING"
        access_log_enabled = False
        log_retention = 7

    log_center = LogConfigCenter.get_instance()
    log_center.initialize({"level": log_level}, side="BACKEND")
    logging.getLogger("PIL").setLevel(logging.WARNING)

    log_dir = LOGS_DIR
    try:
        log_center.add_file_handler(str(log_dir), retention_days=log_retention)
        from datetime import datetime

        today_dir = log_dir / datetime.now().strftime("%Y-%m-%d")
        today_log = today_dir / "app.log"
        print(f"[Campus-Auth] 日志文件: {today_log}")
        startup_logger.info("日志文件: %s", today_log)
        for old_name in ("campus_auth.log",):
            old_log = log_dir / old_name
            if old_log.exists():
                old_log.unlink(missing_ok=True)
    except Exception:
        startup_logger.debug("旧日志清理失败", exc_info=True)

    import shutil

    old_debug = PROJECT_ROOT / "debug"
    if old_debug.exists():
        try:
            shutil.rmtree(old_debug)
            startup_logger.info("已清理旧版 debug/ 目录")
        except Exception:
            startup_logger.debug("旧版 debug 目录清理失败", exc_info=True)

    global _access_log_enabled
    _access_log_enabled = access_log_enabled

    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

    uvicorn.run(
        "backend.main:app",
        host="127.0.0.1",
        port=_resolve_port(),
        reload=False,
        log_level="info",
        access_log=False,
    )


if __name__ == "__main__":
    run()
