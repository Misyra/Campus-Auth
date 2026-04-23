from __future__ import annotations

import asyncio
import logging
import os
import sys
import time
from pathlib import Path

from fastapi import (
    FastAPI,
    HTTPException,
    Query,
    Request,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from src.utils import ConfigLoader
from src.utils.logging import LogConfigCenter, get_logger
from src.version import get_project_version

from .autostart_service import AutoStartService
from .monitor_service import MonitorService, ws_manager
from .schemas import (
    ActionResponse,
    AutoStartStatusResponse,
    LogEntry,
    MonitorConfigPayload,
    MonitorStatusResponse,
)
from .task_service import TaskService

_ENV_PROJECT_ROOT = os.getenv("Campus-Auth_PROJECT_ROOT", "").strip()
PROJECT_ROOT = (
    Path(_ENV_PROJECT_ROOT).expanduser().resolve()
    if _ENV_PROJECT_ROOT
    else Path(__file__).resolve().parents[1]
)
os.environ.setdefault("Campus-Auth_ENV_FILE", str(PROJECT_ROOT / ".env"))
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

FRONTEND_DIR = PROJECT_ROOT / "frontend"
DEBUG_DIR = PROJECT_ROOT / "debug"
DEBUG_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(
    title="校园网认证助手 API",
    version=get_project_version(PROJECT_ROOT),
)

# ==================== CORS 配置 ====================
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1", "http://localhost"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==================== API 鉴权 ====================
_API_TOKEN = os.getenv("API_TOKEN", "").strip()
_WRITE_METHODS = {"POST", "PUT", "DELETE"}


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    """对写操作 API 进行简易 token 鉴权校验"""
    if request.method in _WRITE_METHODS and _API_TOKEN:
        token = request.headers.get("X-API-Token", "")
        if token != _API_TOKEN:
            return JSONResponse(
                status_code=403,
                content={"detail": "无效的 API Token"},
            )
    return await call_next(request)


service = MonitorService(project_root=PROJECT_ROOT)
autostart_service = AutoStartService(project_root=PROJECT_ROOT)
task_service = TaskService(project_root=PROJECT_ROOT)
http_logger = get_logger("backend.http", side="BACKEND")
startup_logger = get_logger("backend.startup", side="BACKEND")
api_logger = get_logger("backend.api", side="BACKEND")
ws_logger = get_logger("backend.ws", side="BACKEND")


@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    start = time.perf_counter()
    try:
        response = await call_next(request)
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


@app.on_event("startup")
async def on_startup() -> None:
    start = asyncio.get_event_loop().time()
    startup_logger.info("FastAPI 启动钩子: 开始设置事件循环与服务引导")
    service.set_event_loop(asyncio.get_event_loop())
    service.boot()
    startup_logger.info(
        "FastAPI 启动钩子: 完成，耗时 %.3fs",
        asyncio.get_event_loop().time() - start,
    )


@app.on_event("shutdown")
async def on_shutdown() -> None:
    startup_logger.info("FastAPI 关闭钩子: 正在停止服务...")
    service.stop_monitoring()
    startup_logger.info("监控服务已停止")


@app.websocket("/ws/logs")
async def websocket_logs(websocket: WebSocket):
    ws_logger.info("WebSocket connecting: /ws/logs")
    await ws_manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_logger.info("WebSocket disconnected: /ws/logs")
        await ws_manager.disconnect(websocket)
    except Exception:
        ws_logger.exception("WebSocket error: /ws/logs")
        await ws_manager.disconnect(websocket)


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": get_project_version(PROJECT_ROOT)}


@app.get("/api/init-status")
def get_init_status() -> dict[str, bool]:
    config = service.get_config()
    is_initialized = bool(config.username and config.password)
    return {"initialized": is_initialized}


@app.get("/api/config", response_model=MonitorConfigPayload)
def get_config() -> MonitorConfigPayload:
    return service.get_config()


@app.put("/api/config", response_model=ActionResponse)
def save_config(payload: MonitorConfigPayload) -> ActionResponse:
    try:
        service.save_config(payload)
        api_logger.info("Config updated")
        return ActionResponse(success=True, message="配置保存成功")
    except ValueError as exc:
        api_logger.warning("Config update rejected: %s", exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/status", response_model=MonitorStatusResponse)
def get_status() -> MonitorStatusResponse:
    return service.get_status()


@app.get("/api/logs", response_model=list[LogEntry])
def get_logs(limit: int = Query(default=200, ge=1, le=1000)) -> list[LogEntry]:
    return service.list_logs(limit=limit)


@app.post("/api/monitor/start", response_model=ActionResponse)
def start_monitoring() -> ActionResponse:
    ok, message = service.start_monitoring()
    api_logger.info("Monitor start requested -> success=%s, message=%s", ok, message)
    return ActionResponse(success=ok, message=message)


@app.post("/api/monitor/stop", response_model=ActionResponse)
def stop_monitoring() -> ActionResponse:
    ok, message = service.stop_monitoring()
    api_logger.info("Monitor stop requested -> success=%s, message=%s", ok, message)
    return ActionResponse(success=ok, message=message)


@app.post("/api/actions/login", response_model=ActionResponse)
def manual_login() -> ActionResponse:
    ok, message = service.run_manual_login()
    api_logger.info("Manual login requested -> success=%s, message=%s", ok, message)
    return ActionResponse(success=ok, message=message)


@app.post("/api/actions/test-network", response_model=ActionResponse)
def test_network() -> ActionResponse:
    ok, message = service.test_network()
    api_logger.info("Network test requested -> success=%s, message=%s", ok, message)
    return ActionResponse(success=ok, message=message)


@app.get("/api/autostart/status", response_model=AutoStartStatusResponse)
def autostart_status() -> AutoStartStatusResponse:
    status = autostart_service.status()
    return AutoStartStatusResponse(
        platform=str(status.get("platform", "")),
        enabled=bool(status.get("enabled", False)),
        method=str(status.get("method", "")),
        location=str(status.get("location", "")),
    )


@app.post("/api/autostart/enable", response_model=ActionResponse)
def enable_autostart() -> ActionResponse:
    ok, message = autostart_service.enable()
    api_logger.info("Autostart enable requested -> success=%s, message=%s", ok, message)
    return ActionResponse(success=ok, message=message)


@app.post("/api/autostart/disable", response_model=ActionResponse)
def disable_autostart() -> ActionResponse:
    ok, message = autostart_service.disable()
    api_logger.info(
        "Autostart disable requested -> success=%s, message=%s", ok, message
    )
    return ActionResponse(success=ok, message=message)


@app.get("/api/tasks")
def list_tasks() -> list[dict[str, str]]:
    return task_service.list_tasks()


@app.get("/api/tasks/active")
def get_active_task() -> dict[str, str]:
    return {"task_id": task_service.get_active_task()}


@app.get("/api/tasks/{task_id}")
def get_task(task_id: str) -> dict:
    task = task_service.get_task(task_id)
    if task:
        return task
    raise HTTPException(status_code=404, detail="任务不存在")


@app.put("/api/tasks/{task_id}", response_model=ActionResponse)
def save_task(task_id: str, payload: dict) -> ActionResponse:
    ok, message = task_service.save_task(task_id, payload)
    api_logger.info("Save task %s -> success=%s, message=%s", task_id, ok, message)
    return ActionResponse(success=ok, message=message)


@app.delete("/api/tasks/{task_id}", response_model=ActionResponse)
def delete_task(task_id: str) -> ActionResponse:
    ok, message = task_service.delete_task(task_id)
    api_logger.info("Delete task %s -> success=%s, message=%s", task_id, ok, message)
    return ActionResponse(success=ok, message=message)


@app.post("/api/tasks/active/{task_id}", response_model=ActionResponse)
def set_active_task(task_id: str) -> ActionResponse:
    ok, message = task_service.set_active_task(task_id)
    api_logger.info(
        "Set active task %s -> success=%s, message=%s", task_id, ok, message
    )
    return ActionResponse(success=ok, message=message)


# 全局停止事件与系统托盘引用
_shutdown_event = None
_tray_icon_ref = None  # 由 app.py 中设置，用于 shutdown 时正确停止


def _setShutdownEvent(event):
    """设置关闭事件回调"""
    global _shutdown_event
    _shutdown_event = event


def _setTrayIcon(tray_icon):
    """设置系统托盘实例引用"""
    global _tray_icon_ref
    _tray_icon_ref = tray_icon


@app.post("/api/shutdown", response_model=ActionResponse)
def shutdown_server() -> ActionResponse:
    """关闭服务器"""
    api_logger.warning("Shutdown requested")
    import threading

    def _do_shutdown():
        import os
        import signal
        import time

        try:
            service.stop_monitoring()
        except Exception:
            pass

        # 停止正在运行的系统托盘实例（而非创建新实例）
        try:
            if _tray_icon_ref:
                _tray_icon_ref.stop()
        except Exception:
            pass

        time.sleep(0.5)

        os.kill(os.getpid(), signal.SIGTERM)

    threading.Thread(target=_do_shutdown, daemon=True).start()

    return ActionResponse(success=True, message="服务器正在关闭...")


app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")
app.mount("/debug", StaticFiles(directory=DEBUG_DIR), name="debug")


def _resolve_port() -> int:
    raw = os.getenv("APP_PORT", "50721")
    try:
        port = int(raw)
    except ValueError:
        return 50721
    if 1 <= port <= 65535:
        return port
    return 50721


def run() -> None:
    import uvicorn

    config = ConfigLoader.load_config_from_env()

    # 使用日志配置中心统一配置
    log_center = LogConfigCenter.get_instance()
    log_center.initialize(config.get("logging", {}), side="BACKEND")

    access_log_enabled = bool(config.get("access_log", False))

    if not access_log_enabled:
        logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

    uvicorn.run(
        "backend.main:app",
        host="127.0.0.1",
        port=_resolve_port(),
        reload=False,
        log_level="info",
        access_log=access_log_enabled,
    )


if __name__ == "__main__":
    run()
