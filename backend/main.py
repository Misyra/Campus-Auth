from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

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

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

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


FRONTEND_DIR = PROJECT_ROOT / "frontend"

app = FastAPI(
    title="Campus Network Auth API",
    version="2.0.0",
)

service = MonitorService(project_root=PROJECT_ROOT)
autostart_service = AutoStartService(project_root=PROJECT_ROOT)
task_service = TaskService(project_root=PROJECT_ROOT)


@app.on_event("startup")
def on_startup() -> None:
    service.set_event_loop(asyncio.get_event_loop())
    service.boot()


@app.websocket("/ws/logs")
async def websocket_logs(websocket: WebSocket):
    await ws_manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        await ws_manager.disconnect(websocket)
    except Exception:
        await ws_manager.disconnect(websocket)


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


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
        return ActionResponse(success=True, message="配置保存成功")
    except ValueError as exc:
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
    return ActionResponse(success=ok, message=message)


@app.post("/api/monitor/stop", response_model=ActionResponse)
def stop_monitoring() -> ActionResponse:
    ok, message = service.stop_monitoring()
    return ActionResponse(success=ok, message=message)


@app.post("/api/actions/login", response_model=ActionResponse)
def manual_login() -> ActionResponse:
    ok, message = service.run_manual_login()
    return ActionResponse(success=ok, message=message)


@app.post("/api/actions/test-network", response_model=ActionResponse)
def test_network() -> ActionResponse:
    ok, message = service.test_network()
    return ActionResponse(success=ok, message=message)


@app.get("/api/autostart/status", response_model=AutoStartStatusResponse)
def autostart_status() -> AutoStartStatusResponse:
    status = autostart_service.status()
    return AutoStartStatusResponse(**status)


@app.post("/api/autostart/enable", response_model=ActionResponse)
def enable_autostart() -> ActionResponse:
    ok, message = autostart_service.enable()
    return ActionResponse(success=ok, message=message)


@app.post("/api/autostart/disable", response_model=ActionResponse)
def disable_autostart() -> ActionResponse:
    ok, message = autostart_service.disable()
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
    return ActionResponse(success=ok, message=message)


@app.delete("/api/tasks/{task_id}", response_model=ActionResponse)
def delete_task(task_id: str) -> ActionResponse:
    ok, message = task_service.delete_task(task_id)
    return ActionResponse(success=ok, message=message)


@app.post("/api/tasks/active/{task_id}", response_model=ActionResponse)
def set_active_task(task_id: str) -> ActionResponse:
    ok, message = task_service.set_active_task(task_id)
    return ActionResponse(success=ok, message=message)


# 全局停止事件
_shutdown_event = None


def _setShutdownEvent(event):
    """设置关闭事件回调"""
    global _shutdown_event
    _shutdown_event = event


@app.post("/api/shutdown", response_model=ActionResponse)
def shutdown_server() -> ActionResponse:
    """关闭服务器"""
    import threading

    def _do_shutdown():
        import os
        import signal

        # 停止托盘图标
        try:
            from src.system_tray import SystemTray
            tray = SystemTray(port=50721)
            tray.stop()
        except Exception:
            pass

        # 发送 SIGTERM 信号给当前进程
        os.kill(os.getpid(), signal.SIGTERM)

    # 在后台线程中执行关闭，确保响应能正常返回
    threading.Thread(target=_do_shutdown, daemon=True).start()

    return ActionResponse(success=True, message="服务器正在关闭...")


app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


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
    import logging
    import uvicorn
    from src.utils import ConfigLoader

    config = ConfigLoader.load_config_from_env()
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
