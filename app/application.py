"""FastAPI 应用入口 — 精简为核心框架：app 创建、lifespan、中间件、WebSocket、静态文件。"""

from __future__ import annotations

import asyncio
import json
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

from app.api import (
    autostart,
    backup,
    config,
    debug,
    history,
    logfiles,
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
from app.constants import FRONTEND_DIR, LOGS_DIR, PROJECT_ROOT, TEMP_DIR
from app.container import ServiceContainer
from app.utils.logging import LogConfigCenter, get_logger
from app.version import get_project_version

http_logger = get_logger("backend.http", side="BACKEND")
startup_logger = get_logger("backend.startup", side="BACKEND")
ws_logger = get_logger("backend.ws", side="BACKEND")

# temp 目录中截图的最大保留天数
_TEMP_SCREENSHOT_MAX_AGE_DAYS = 7


def _cleanup_temp_screenshots() -> None:
    """启动时清理 temp/ 目录中超过保留天数的截图文件。"""
    try:
        if not TEMP_DIR.exists():
            return
        import time as _time

        cutoff = _time.time() - _TEMP_SCREENSHOT_MAX_AGE_DAYS * 86400
        removed = 0
        for f in TEMP_DIR.iterdir():
            if (
                f.is_file()
                and f.suffix in (".png", ".jpg", ".jpeg")
                and f.stat().st_mtime < cutoff
            ):
                f.unlink()
                removed += 1
        if removed:
            startup_logger.info("启动时清理 temp 截图: 删除 {} 个过期文件", removed)
    except Exception as exc:
        startup_logger.warning("清理 temp 截图失败: {}", exc)


# ==================== 生命周期管理 ====================


@asynccontextmanager
async def lifespan(app_instance):
    """应用生命周期管理"""
    start = time.perf_counter()
    startup_logger.info("FastAPI 启动: 创建 shutdown_event")

    # 创建 shutdown_event 用于优雅关闭
    shutdown_event = asyncio.Event()
    app_instance.state.shutdown_event = shutdown_event

    startup_logger.info("FastAPI 启动: 开始设置服务引导")

    services = ServiceContainer(PROJECT_ROOT)
    app_instance.state.services = services

    # 配置诊断（__init__ 已加载，不重复 reload）
    settings_path = PROJECT_ROOT / "settings.json"
    startup_logger.info(
        "settings.json 路径: {} (存在={}, 大小={})",
        settings_path,
        settings_path.exists(),
        settings_path.stat().st_size if settings_path.exists() else 0,
    )
    config = services.monitor_service.get_config()
    startup_logger.info(
        "当前配置: 用户={}, 密码={}, 认证={}, 运营商={}, 间隔={}min, 自动监控={}",
        f"'{config.username}'" if config.username else "(空)",
        "已设置" if config.password else "(空)",
        f"'{config.auth_url}'" if config.auth_url else "(空)",
        config.carrier,
        config.check_interval_seconds,
        config.auto_start,
    )

    # 检查 cryptography 库是否可用
    try:
        import cryptography  # noqa: F401
    except ImportError:
        startup_logger.warning(
            "cryptography 库未安装，密码仅使用 Base64 编码存储（非加密），"
            "建议安装: pip install cryptography"
        )

    # 启动时清理 temp 目录中的旧截图
    _cleanup_temp_screenshots()

    await services.startup()

    startup_logger.info(
        "FastAPI 启动: 完成，耗时 {:.3f}s",
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
            startup_logger.warning("端口解析失败，使用默认 50721", exc_info=True)

    settings_path = PROJECT_ROOT / "settings.json"
    if settings_path.exists():
        try:
            data = json.loads(settings_path.read_text(encoding="utf-8"))
            app_port = data.get("system", {}).get("app_port")
            if app_port is not None:
                port = int(app_port)
                if 1 <= port <= 65535:
                    return port
        except (json.JSONDecodeError, ValueError, OSError) as exc:
            startup_logger.warning(
                "读取 settings.json 端口配置失败，使用默认端口 50721: {}", exc
            )

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


@app.websocket("/ws/logs")
async def websocket_logs(websocket: WebSocket):
    services = app.state.services
    ws_mgr = services.ws_manager
    monitor_svc = services.monitor_service

    await ws_mgr.connect(websocket)
    try:
        while True:
            raw = await websocket.receive_text()
            # WebSocket 消息大小预检，防止超大消息导致内存问题
            if len(raw) > 65536:
                ws_logger.warning("WebSocket 消息过大 ({} bytes)，断开连接", len(raw))
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
            except (json.JSONDecodeError, KeyError):
                ws_logger.debug("WebSocket 消息解析失败", exc_info=True)
    except WebSocketDisconnect:
        await ws_mgr.disconnect(websocket)
    except Exception:
        ws_logger.exception("WebSocket 通信异常")
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
app.include_router(autostart.router)
app.include_router(ocr.router)
app.include_router(tools.router)
app.include_router(scripts.router)
app.include_router(scheduled_tasks.router)
app.include_router(history.router)
app.include_router(logfiles.router)


# ==================== 首页和静态文件 ====================


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "index.html")


# 确保挂载目录存在（发布版本解压后这些目录可能不存在）
for _dir in (LOGS_DIR, TEMP_DIR):
    _dir.mkdir(parents=True, exist_ok=True)

app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")
app.mount("/logs", StaticFiles(directory=LOGS_DIR), name="logs")
app.mount("/temp", StaticFiles(directory=TEMP_DIR), name="temp")


# ==================== 启动入口 ====================


def run(
    access_log_enabled: bool | None = None,
    log_retention: int | None = None,
) -> None:
    import uvicorn

    if access_log_enabled is None or log_retention is None:
        # 调用方未传入日志配置，从 settings.json 读取
        try:
            from app.services.profile import ProfileService

            profile_service = ProfileService(PROJECT_ROOT)
            sys_settings = profile_service.load().system
            if access_log_enabled is None:
                access_log_enabled = bool(sys_settings.access_log)
            if log_retention is None:
                log_retention = max(1, sys_settings.log_retention_days)
        except Exception:
            startup_logger.warning("读取日志配置失败，使用默认值", exc_info=True)
            if access_log_enabled is None:
                access_log_enabled = False
            if log_retention is None:
                log_retention = 7

    log_center = LogConfigCenter.get_instance()
    log_center.initialize({"level": "INFO"}, side="BACKEND")

    # 压制第三方库的 DEBUG 日志
    import logging

    logging.getLogger("PIL").setLevel(logging.WARNING)

    log_dir = LOGS_DIR
    try:
        log_center.add_file_handler(str(log_dir), retention_days=log_retention)
        from datetime import datetime

        today_dir = log_dir / datetime.now().strftime("%Y-%m-%d")
        today_log = today_dir / "app.log"
        startup_logger.info("日志文件: {}", today_log)
        for old_name in ("campus_auth.log",):
            old_log = log_dir / old_name
            if old_log.exists():
                old_log.unlink(missing_ok=True)
    except Exception:
        startup_logger.warning("旧日志清理失败", exc_info=True)

    global _access_log_enabled
    _access_log_enabled = access_log_enabled

    # 压制 uvicorn access 日志
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

    uvicorn.run(
        "app.application:app",
        host="127.0.0.1",
        port=_resolve_port(),
        reload=False,
        log_level="info",
        access_log=False,
        ws_max_size=65536,
    )


if __name__ == "__main__":
    run()
