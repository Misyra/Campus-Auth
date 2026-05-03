from __future__ import annotations

import asyncio
import logging
import os
import sys
import time
from contextlib import asynccontextmanager
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
from .config_service import save_profile_from_payload
from .monitor_service import MonitorService, ws_manager
from .profile_service import ProfileService
from .schemas import (
    ActionResponse,
    AutoStartStatusResponse,
    LogEntry,
    MonitorConfigPayload,
    MonitorStatusResponse,
    ProfileSettings,
    ProfilesData,
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

@asynccontextmanager
async def lifespan(app_instance):
    """应用生命周期管理"""
    start = asyncio.get_event_loop().time()
    startup_logger.info("FastAPI 启动: 开始设置事件循环与服务引导")
    service.set_event_loop(asyncio.get_event_loop())

    # 迁移：从 .env 创建或补充 settings.json
    try:
        from src.utils import ConfigLoader

        env_config = ConfigLoader.load_config_from_env()
        profile_service.migrate_config(env_config)
        service.reload_config()
    except Exception as exc:
        startup_logger.warning("配置迁移失败: %s", exc)

    service.boot()
    startup_logger.info(
        "FastAPI 启动: 完成，耗时 %.3fs",
        asyncio.get_event_loop().time() - start,
    )
    yield
    startup_logger.info("FastAPI 关闭: 正在停止服务...")
    if _debug["session"]:
        await _debug["session"].close()
    service.stop_monitoring()
    startup_logger.info("监控服务已停止")


app = FastAPI(
    title="校园网认证助手 API",
    version=get_project_version(PROJECT_ROOT),
    lifespan=lifespan,
)

# ==================== CORS 配置 ====================
_cors_port = os.getenv("APP_PORT", "50721")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        f"http://127.0.0.1:{_cors_port}",
        f"http://localhost:{_cors_port}",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-API-Token"],
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
profile_service = ProfileService(project_root=PROJECT_ROOT)
http_logger = get_logger("backend.http", side="BACKEND")
startup_logger = get_logger("backend.startup", side="BACKEND")
api_logger = get_logger("backend.api", side="BACKEND")
ws_logger = get_logger("backend.ws", side="BACKEND")

# ==================== 调试会话 ====================

from datetime import datetime

from src.task_executor import TaskExecutor, TaskManager


class DebugSession:
    """调试会话：管理浏览器生命周期 + 单步执行"""

    def __init__(self):
        self._pw = None
        self._browser = None
        self._context = None
        self.page = None

    async def start(
        self, runtime_config: dict, url: str | None, safe_mode: bool = False
    ) -> None:
        from playwright.async_api import async_playwright

        self._pw = await async_playwright().start()

        if safe_mode:
            # 安全模式：不注入任何自定义参数，使用 Chromium 默认设置
            self._browser = await self._pw.chromium.launch(headless=False)
            self._context = await self._browser.new_context(
                viewport={"width": 1280, "height": 720},
            )
        else:
            browser_settings = runtime_config.get("browser_settings", {})

            args = [
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--memory-pressure-off",
            ]
            if browser_settings.get("disable_web_security", False):
                args.append("--disable-web-security")
            if browser_settings.get("low_resource_mode", False):
                args.append("--blink-settings=imagesEnabled=false")
            # 用户自定义参数
            custom_args = str(browser_settings.get("browser_args", "") or "").strip()
            if custom_args:
                for flag in custom_args.split():
                    flag = flag.strip()
                    if flag and flag not in args:
                        args.append(flag)

            extra_headers: dict = {}
            raw_headers = str(
                browser_settings.get("extra_headers_json", "") or ""
            ).strip()
            if raw_headers:
                try:
                    import json as _json

                    custom = _json.loads(raw_headers)
                    if isinstance(custom, dict):
                        extra_headers = {
                            str(k): str(v)
                            for k, v in custom.items()
                            if k is not None
                        }
                except Exception:
                    pass

            self._browser = await self._pw.chromium.launch(
                headless=False, args=args
            )
            ctx_opts: dict = {
                "viewport": {"width": 1280, "height": 720},
            }
            if extra_headers:
                ctx_opts["extra_http_headers"] = extra_headers
            user_agent = (browser_settings.get("user_agent") or "").strip()
            if user_agent:
                ctx_opts["user_agent"] = user_agent
            self._context = await self._browser.new_context(**ctx_opts)

            if browser_settings.get("low_resource_mode", False):

                async def _block_images(route):
                    if route.request.resource_type == "image":
                        await route.abort()
                    else:
                        await route.continue_()

                await self._context.route("**/*", _block_images)

        self.page = await self._context.new_page()

        if url:
            await self.page.goto(url, wait_until="domcontentloaded", timeout=30000)

    async def close(self) -> None:
        for resource in [self.page, self._context, self._browser]:
            if resource:
                try:
                    await resource.close()
                except Exception:
                    pass
        if self._pw:
            try:
                await self._pw.stop()
            except Exception:
                pass
        self.page = None
        self._pw = None
        self._browser = None
        self._context = None


_debug: dict = {
    "session": None,
    "task_id": None,
    "executor": None,
    "current_step": 0,
    "steps": [],
    "results": [],
    "screenshot_url": None,
    "running": False,
}


def _debug_response() -> dict:
    return {
        "running": _debug["running"],
        "task_id": _debug["task_id"],
        "current_step": _debug["current_step"],
        "total_steps": len(_debug["steps"]),
        "steps": _debug["steps"],
        "results": _debug["results"],
        "screenshot_url": _debug["screenshot_url"],
    }


def _require_debug_session():
    if not _debug["session"] or not _debug["running"]:
        raise HTTPException(status_code=400, detail="没有活跃的调试会话")
    return _debug["session"], _debug["executor"], _debug["session"].page


async def _take_debug_screenshot(page) -> str | None:
    try:
        debug_dir = PROJECT_ROOT / "debug"
        debug_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        filename = f"debug_step_{stamp}.png"
        await page.screenshot(path=str(debug_dir / filename), full_page=True)
        return f"/debug/{filename}"
    except Exception:
        return None


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
        # 同时保存 profile 非敏感设置
        try:
            save_profile_from_payload(payload, PROJECT_ROOT)
        except Exception as exc:
            api_logger.warning("Profile save failed: %s", exc)
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


# ==================== 安全模式 API ====================


@app.get("/api/safe-mode")
def get_safe_mode() -> dict:
    return {"enabled": service.safe_mode}


@app.post("/api/safe-mode")
def toggle_safe_mode() -> dict:
    new_value = not service.safe_mode
    try:
        with service._lock:
            data = service._profile_service.load()
            data.system.safe_mode = new_value
            service._profile_service.save(data)
        service.safe_mode = new_value
        api_logger.info("Safe mode toggled -> %s", new_value)
        return {"enabled": new_value}
    except Exception as exc:
        api_logger.error("切换安全模式失败: %s", exc)
        raise HTTPException(status_code=500, detail=f"切换安全模式失败: {exc}")


# ==================== 调试 API ====================


@app.post("/api/debug/start")
async def debug_start(request: Request) -> dict:
    global _debug
    if _debug["session"]:
        await _debug["session"].close()

    body = await request.json()
    task_id = body.get("task_id", "")
    if not task_id:
        raise HTTPException(status_code=400, detail="缺少 task_id")

    tm = TaskManager(PROJECT_ROOT / "tasks")
    task = tm.load_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    # 构建环境变量（复用 service 的运行时配置）
    with service._lock:
        runtime_config = service._runtime_config.copy()

    env_vars = dict(os.environ)
    if runtime_config.get("auth_url"):
        env_vars["LOGIN_URL"] = runtime_config["auth_url"]
    # 任务自定义 url 覆盖系统 LOGIN_URL
    if task.url:
        resolved_url = task.url
        for k, v in env_vars.items():
            resolved_url = resolved_url.replace("{{" + k + "}}", v)
        env_vars["LOGIN_URL"] = resolved_url
    if runtime_config.get("isp"):
        env_vars["ISP"] = runtime_config["isp"]
    if runtime_config.get("username"):
        env_vars["USERNAME"] = runtime_config["username"]
    if runtime_config.get("password"):
        env_vars["PASSWORD"] = runtime_config["password"]
    custom_vars = runtime_config.get("custom_variables", {})
    if custom_vars and isinstance(custom_vars, dict):
        env_vars.update(custom_vars)

    # 解析任务 URL
    url = task.url or ""
    for k, v in env_vars.items():
        url = url.replace("{{" + k + "}}", v)

    session = DebugSession()
    await session.start(runtime_config, url if url else None, safe_mode=service.safe_mode)

    steps_info = [
        {
            "index": i,
            "id": step.id,
            "type": step.type,
            "description": step.description or step.type,
        }
        for i, step in enumerate(task.steps)
    ]

    executor = TaskExecutor(task, env_vars)

    _debug = {
        "session": session,
        "task_id": task_id,
        "executor": executor,
        "current_step": 0,
        "steps": steps_info,
        "results": [],
        "screenshot_url": None,
        "running": True,
    }

    _debug["screenshot_url"] = await _take_debug_screenshot(session.page)
    api_logger.info("Debug session started for task %s", task_id)
    return _debug_response()


@app.post("/api/debug/next")
async def debug_next() -> dict:
    session, executor, page = _require_debug_session()
    idx = _debug["current_step"]

    if idx >= len(_debug["steps"]):
        return {**_debug_response(), "message": "所有步骤已执行完毕"}

    result = await executor.execute_step_at(page, idx)
    _debug["results"].append(result)
    _debug["screenshot_url"] = result.get("screenshot_url")
    _debug["current_step"] = idx + 1
    return _debug_response()


@app.post("/api/debug/run-all")
async def debug_run_all() -> dict:
    session, executor, page = _require_debug_session()
    from_idx = _debug["current_step"]

    if from_idx >= len(_debug["steps"]):
        return {**_debug_response(), "message": "所有步骤已执行完毕"}

    agg = await executor.execute_remaining(page, from_idx)
    _debug["results"].extend(agg["results"])
    _debug["current_step"] = len(_debug["steps"])

    if agg["results"]:
        _debug["screenshot_url"] = agg["results"][-1].get("screenshot_url")

    return _debug_response()


@app.post("/api/debug/stop")
async def debug_stop() -> dict:
    global _debug
    if _debug["session"]:
        await _debug["session"].close()
    _debug = {
        "session": None, "task_id": None, "executor": None,
        "current_step": 0, "steps": [], "results": [],
        "screenshot_url": None, "running": False,
    }
    api_logger.info("Debug session stopped")
    return {"running": False, "message": "调试会话已关闭"}


@app.get("/api/debug/status")
async def debug_status() -> dict:
    return _debug_response()


# ==================== 配置方案 API ====================


@app.get("/api/profiles")
def list_profiles() -> dict:
    data = profile_service.load()
    result = {}
    for pid, settings in data.profiles.items():
        result[pid] = {
            "name": settings.name,
            "match_gateway_ip": settings.match_gateway_ip,
            "match_ssid": settings.match_ssid,
        }
    return {
        "profiles": result,
        "active_profile": data.active_profile,
        "auto_switch": data.auto_switch,
    }


@app.get("/api/profiles/active")
def get_active_profile() -> dict:
    data = profile_service.load()
    profile = profile_service.get_active_profile()
    return {
        "profile_id": data.active_profile,
        "auto_switch": data.auto_switch,
        "settings": profile.model_dump(),
    }


@app.get("/api/profiles/{profile_id}")
def get_profile(profile_id: str) -> dict:
    data = profile_service.load()
    profile = data.profiles.get(profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="方案不存在")
    return {
        "profile_id": profile_id,
        "settings": profile.model_dump(),
    }


@app.put("/api/profiles/{profile_id}", response_model=ActionResponse)
def save_profile(profile_id: str, payload: ProfileSettings) -> ActionResponse:
    ok, message = profile_service.save_profile(profile_id, payload)
    api_logger.info(
        "Save profile %s -> success=%s, message=%s", profile_id, ok, message
    )
    if ok:
        # 如果修改的是当前活动方案，热更新配置
        data = profile_service.load()
        if data.active_profile == profile_id:
            try:
                service.apply_profile(payload.name)
            except Exception as exc:
                api_logger.warning("Apply profile failed: %s", exc)
    return ActionResponse(success=ok, message=message)


@app.delete("/api/profiles/{profile_id}", response_model=ActionResponse)
def delete_profile(profile_id: str) -> ActionResponse:
    ok, message = profile_service.delete_profile(profile_id)
    api_logger.info(
        "Delete profile %s -> success=%s, message=%s", profile_id, ok, message
    )
    return ActionResponse(success=ok, message=message)


@app.post("/api/profiles/active/{profile_id}", response_model=ActionResponse)
def set_active_profile(profile_id: str) -> ActionResponse:
    ok, message = profile_service.set_active_profile(profile_id)
    api_logger.info(
        "Set active profile %s -> success=%s, message=%s", profile_id, ok, message
    )
    if ok:
        data = profile_service.load()
        profile = data.profiles.get(profile_id)
        profile_name = profile.name if profile else profile_id
        try:
            service.apply_profile(profile_name)
        except Exception as exc:
            api_logger.warning("Apply profile failed: %s", exc)
    return ActionResponse(success=ok, message=message)


@app.post("/api/profiles/detect")
def detect_network_profile() -> dict:
    from .profile_service import detect_gateway_ip, detect_wifi_ssid

    try:
        gateway = detect_gateway_ip()
    except Exception as exc:
        api_logger.error("网关检测异常: %s", exc, exc_info=True)
        gateway = None

    try:
        ssid = detect_wifi_ssid()
    except Exception as exc:
        api_logger.error("SSID 检测异常: %s", exc, exc_info=True)
        ssid = None

    try:
        matched_id = profile_service.detect_matching_profile()
    except Exception as exc:
        api_logger.error("方案匹配异常: %s", exc, exc_info=True)
        matched_id = None

    data = profile_service.load()
    matched_name = None
    if matched_id and matched_id in data.profiles:
        matched_name = data.profiles[matched_id].name

    api_logger.info(
        "网络检测结果: gateway=%s, ssid=%s, matched=%s",
        gateway, ssid, matched_id,
    )
    return {
        "gateway_ip": gateway,
        "ssid": ssid,
        "matched_profile_id": matched_id,
        "matched_profile_name": matched_name,
    }


@app.post("/api/profiles/auto-switch", response_model=ActionResponse)
def toggle_auto_switch(enabled: bool = True) -> ActionResponse:
    profile_service.set_auto_switch(enabled)
    state = "开启" if enabled else "关闭"
    api_logger.info("Auto-switch %s", state)
    return ActionResponse(success=True, message=f"自动切换已{state}")


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
