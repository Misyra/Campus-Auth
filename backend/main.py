from __future__ import annotations

import asyncio
import json
import logging
import mimetypes
import os
import re
import time
from contextlib import asynccontextmanager
from pathlib import Path

# Windows 上 mimetypes 模块可能无法正确识别 .js 的 MIME 类型，
# 导致 type="module" 脚本因返回 text/plain 而被浏览器拒绝加载
mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("application/javascript", ".mjs")

from fastapi import (
    FastAPI,
    HTTPException,
    Query,
    Request,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from src.utils import ConfigValidator
from src.utils.config_helpers import BACKUP_FILENAME_PATTERN
from src.utils.env import build_login_env_vars
from src.utils.file_helpers import atomic_write
from src.utils.logging import LogConfigCenter, get_logger
from src.playwright_worker import (
    CMD_DEBUG_START,
    CMD_DEBUG_STEP,
    CMD_DEBUG_STOP,
    cleanup_orphan_browsers,
    get_worker,
)
from src.version import get_project_version

from .autostart_service import AutoStartService
from .config_service import save_config_combined
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
from backend.debug_session import (
    _debug_gen,
    _next_debug_gen,
    debug_to_response,
    empty_debug_session,
)

_ENV_PROJECT_ROOT = os.getenv("CAMPUS_AUTH_PROJECT_ROOT", "").strip()
PROJECT_ROOT = (
    Path(_ENV_PROJECT_ROOT).expanduser().resolve()
    if _ENV_PROJECT_ROOT
    else Path(__file__).resolve().parents[1]
)

FRONTEND_DIR = PROJECT_ROOT / "frontend"
DEBUG_DIR = PROJECT_ROOT / "debug"
DEBUG_DIR.mkdir(parents=True, exist_ok=True)


@asynccontextmanager
async def lifespan(app_instance):
    """应用生命周期管理"""
    start = time.perf_counter()
    startup_logger.info("FastAPI 启动: 开始设置服务引导")

    # 迁移：从 .env 创建或补充 settings.json
    settings_path = PROJECT_ROOT / "settings.json"
    startup_logger.info(
        "settings.json 路径: %s (存在=%s, 大小=%d)",
        settings_path,
        settings_path.exists(),
        settings_path.stat().st_size if settings_path.exists() else 0,
    )
    try:
        env_config = {}
        profile_service.migrate_config(env_config)
        service.reload_config()
        # 诊断：打印加载后的关键配置
        config = service.get_config()
        startup_logger.info(
            "当前配置: 用户=%s, 密码=%s, 认证=%s, 运营商=%s, 间隔=%dmin, 自动监控=%s",
            f"'{config.username}'" if config.username else "(空)",
            "已设置" if config.password else "(空)",
            f"'{config.auth_url}'" if config.auth_url else "(空)",
            config.carrier,
            config.check_interval_minutes,
            config.auto_start,
        )
    except Exception as exc:
        startup_logger.warning("配置迁移失败: %s", exc)

    service.boot()
    # 启动 WebSocket 广播队列消费任务（在 service.boot() 中也尝试启动，但加在这里确保成功）
    ws_drain_task = asyncio.create_task(service._ws_drain_loop())
    _cleanup_old_backups()
    # 启动时清理上次运行残留的孤儿 Chromium Worker 浏览器进程
    # 避免因前次 os._exit(0) 导致浏览器进程被孤立
    cleanup_orphan_browsers()
    startup_logger.info(
        "FastAPI 启动: 完成，耗时 %.3fs",
        time.perf_counter() - start,
    )
    yield
    startup_logger.info("FastAPI 关闭: 正在停止服务...")
    ws_drain_task.cancel()
    try:
        await ws_drain_task
    except asyncio.CancelledError:
        pass
    if _debug_session.session:
        await _debug_session.session.close()
    # 清理临时调试截图
    try:
        import shutil

        if TEMP_DIR.exists():
            shutil.rmtree(TEMP_DIR, ignore_errors=True)
    except Exception:
        pass
    service.stop_monitoring()
    startup_logger.info("监控服务已停止")
    await ws_manager.close_all()
    startup_logger.info("WebSocket 连接已关闭")


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

    # 回退：从 settings.json 读取（与 launcher.py 保持一致）
    settings_path = PROJECT_ROOT / "settings.json"
    if settings_path.exists():
        try:
            import json as _json

            data = _json.loads(settings_path.read_text(encoding="utf-8"))
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


profile_service = ProfileService(project_root=PROJECT_ROOT)
service = MonitorService(project_root=PROJECT_ROOT, profile_service=profile_service)
autostart_service = AutoStartService(project_root=PROJECT_ROOT)
task_service = TaskService(project_root=PROJECT_ROOT)
http_logger = get_logger("backend.http", side="BACKEND")
startup_logger = get_logger("backend.startup", side="BACKEND")
api_logger = get_logger("backend.api", side="BACKEND")
ws_logger = get_logger("backend.ws", side="BACKEND")
_access_log_enabled = False

# ==================== 调试会话 ====================

from datetime import datetime


class DebugSession:
    """调试会话（简化版）：浏览器生命周期由 PlaywrightWorker 管理。

    不再直接调用 async_playwright() 管理浏览器实例，
    所有浏览器操作通过 Worker 的命令队列提交执行。
    TaskExecutor 在 Worker 线程内创建和运行，确保 page 对象线程安全。
    """

    def __init__(self):
        self.page = None  # 向后兼容标记，实际 page 由 Worker 管理

    async def start(
        self, runtime_config: dict, url: str | None, safe_mode: bool = False
    ) -> None:
        """启动调试会话 — 委托 Worker 处理浏览器初始化。"""
        data = {
            "config": runtime_config,
            "task_url": url or "",
            "safe_mode": safe_mode,
        }
        response = await asyncio.to_thread(
            lambda: get_worker().submit(CMD_DEBUG_START, data=data)
        )
        if not response.success:
            raise RuntimeError(f"调试会话启动失败: {response.error}")
        self.page = True  # 标记已启动

    async def close(self) -> None:
        """关闭调试会话 — 委托 Worker 关闭浏览器页面。"""
        try:
            await asyncio.to_thread(
                lambda: get_worker().submit(CMD_DEBUG_STOP)
            )
        except Exception:
            pass
        self.page = None


_debug_session = empty_debug_session()
_debug_lock = asyncio.Lock()
_debug_exec_sem = asyncio.Semaphore(1)


def _debug_response() -> dict:
    return debug_to_response(_debug_session)


def _require_debug_session() -> None:
    """验证调试会话处于活跃状态。

    page 和 TaskExecutor 现在由 Worker 线程管理，不再从 API 线程直接访问。
    """
    if not _debug_session.running:
        raise HTTPException(status_code=400, detail="没有活跃的调试会话")


async def _debug_timeout_watcher(gen: int, *, timeout_seconds: float = 1800.0) -> None:
    """监控调试会话超时，超过 timeout_seconds 无操作则关闭浏览器。"""
    check_interval = min(60, timeout_seconds / 10)
    try:
        while True:
            await asyncio.sleep(check_interval)
            if gen != _debug_gen:
                return
            if time.monotonic() - _debug_session._last_activity > timeout_seconds:
                async with _debug_lock:
                    if gen != _debug_gen:
                        return
                    api_logger.info(
                        "调试会话超时（%ds 无操作），正在关闭浏览器",
                        timeout_seconds,
                    )
                    if _debug_session.session:
                        await _debug_session.session.close()
                    _debug_session.session = None
                    _debug_session.running = False
                    _debug_session.executor = None
                    _debug_session.current_step = 0
                    _debug_session.steps = []
                    _debug_session.results.clear()
                    _debug_session.screenshot_url = None
                    _debug_session._timer_task = None
                    _debug_session._last_activity = 0.0
    except asyncio.CancelledError:
        pass


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


@app.websocket("/ws/logs")
async def websocket_logs(websocket: WebSocket):
    ws_logger.info("WebSocket connecting: /ws/logs")
    await ws_manager.connect(websocket)
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
                if msg.get("type") == "frontend_log":
                    d = msg.get("data", {})
                    message_text = d.get("message", "")
                    if message_text:
                        service._push_log(
                            message=f"[{d.get('scope', '?')}] {message_text}",
                            level=d.get("level", "INFO"),
                            source="frontend",
                        )
            except (json.JSONDecodeError, KeyError):
                pass
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


@app.get("/api/check-update")
async def check_update() -> dict:
    import httpx

    current = get_project_version(PROJECT_ROOT)
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                "https://api.github.com/repos/Misyra/Campus-Auth/releases/latest",
                headers={
                    "Accept": "application/vnd.github.v3+json",
                    "User-Agent": "Campus-Auth",
                },
            )
        data = resp.json()
        tag = data.get("tag_name", "").lstrip("v")
        return {
            "current": current,
            "latest": tag,
            "has_update": _compare_versions(tag, current) > 0,
            "url": data.get("html_url", ""),
            "body": data.get("body", ""),
            "published_at": data.get("published_at", ""),
        }
    except Exception as e:
        return {
            "current": current,
            "latest": None,
            "has_update": False,
            "error": str(e),
        }


def _compare_versions(a: str, b: str) -> int:
    """比较语义版本号，a > b 返回 1，a < b 返回 -1，相等时返回 0"""
    try:
        va = [int(x) for x in a.split(".")]
        vb = [int(x) for x in b.split(".")]
        for x, y in zip(va, vb):
            if x > y:
                return 1
            if x < y:
                return -1
        return 1 if len(va) > len(vb) else -1 if len(va) < len(vb) else 0
    except (ValueError, AttributeError):
        return 0


@app.get("/api/init-status")
def get_init_status() -> dict:
    from src.utils.crypto import has_decryption_error

    config = service.get_config()
    is_initialized = bool(config.username and config.password)
    if not is_initialized:
        startup_logger.info(
            "初始化状态: 未完成 — username=%s, password=%s, auth_url=%s",
            f"'{config.username}'" if config.username else "空",
            "已设置" if config.password else "空",
            f"'{config.auth_url}'" if config.auth_url else "空",
        )
    return {
        "initialized": is_initialized,
        "password_decryption_failed": has_decryption_error(),
    }


@app.get("/api/config", response_model=MonitorConfigPayload)
def get_config() -> MonitorConfigPayload:
    return service.get_config()


@app.put("/api/config", response_model=ActionResponse)
def save_config(payload: MonitorConfigPayload) -> ActionResponse:
    try:
        # 校验关键字段
        ok, error = ConfigValidator.validate_gui_config(
            payload.username,
            payload.password,
            str(payload.check_interval_minutes),
        )
        if not ok:
            raise ValueError(error)

        # 原子化保存：系统设置 + 活动方案
        save_config_combined(payload, profile_service)
        # 热更新日志级别
        LogConfigCenter.get_instance().set_level(payload.backend_log_level)
        # 同步更新 MonitorService 运行时配置
        service.reload_config()
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
    if service.login_in_progress:
        raise HTTPException(
            status_code=409,
            detail={"success": False, "message": "登录操作正在进行中，请稍后再试"},
        )
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


@app.get("/api/tools/task-recorder.user.js")
def download_task_recorder():
    """下载任务录制器用户脚本（Tampermonkey 会自动拦截 .user.js 并弹出安装）"""
    script_path = PROJECT_ROOT / "tools" / "task-recorder.user.js"
    if not script_path.exists():
        raise HTTPException(status_code=404, detail="任务录制器脚本不存在")
    return FileResponse(
        script_path,
        media_type="text/javascript",
    )


@app.get("/api/docs/task-writing-guide")
def download_task_writing_guide():
    """下载任务编写指南文档"""
    doc_path = PROJECT_ROOT / "doc" / "task-writing-guide.md"
    if not doc_path.exists():
        raise HTTPException(status_code=404, detail="文档不存在")
    return FileResponse(
        doc_path,
        media_type="text/markdown",
        filename="task-writing-guide.md",
    )


# ==================== 仓库代理 API ====================


def _normalize_repo_url(url: str) -> str:
    """将 GitHub/Gitee 页面链接转换为 raw 链接，其他链接原样返回"""
    m = re.match(r"https?://github\.com/([^/]+)/([^/]+)/blob/([^/]+)/(.+)", url)
    if m:
        return f"https://raw.githubusercontent.com/{m.group(1)}/{m.group(2)}/{m.group(3)}/{m.group(4)}"
    m = re.match(r"https?://gitee\.com/([^/]+)/([^/]+)/blob/([^/]+)/(.+)", url)
    if m:
        return (
            f"https://gitee.com/{m.group(1)}/{m.group(2)}/raw/{m.group(3)}/{m.group(4)}"
        )
    return url


def _get_configured_proxy() -> str:
    """从 settings.json 读取代理配置"""
    try:
        return (profile_service.load().system.proxy or "").strip()
    except Exception as exc:
        api_logger.debug("读取代理配置失败: %s", exc)
        return ""


def _repo_get(url: str):
    """请求远程 JSON，使用配置的代理（如有）"""
    import httpx

    headers = {"User-Agent": "Campus-Auth"}
    proxy = _get_configured_proxy()
    proxies = {"http": proxy, "https": proxy} if proxy else {}

    with httpx.Client(proxies=proxies, timeout=httpx.Timeout(15)) as client:
        resp = client.get(url, headers=headers)
        resp.raise_for_status()
        return resp


@app.get("/api/repo/fetch")
def repo_fetch_index(url: str = Query(..., description="索引 JSON 地址")) -> list:
    """代理获取任务仓库索引，避免前端跨域问题"""
    import httpx

    url = _normalize_repo_url(url)
    api_logger.info("获取远程索引: %s", url)

    try:
        resp = _repo_get(url)
        data = resp.json()
        if not isinstance(data, list):
            raise HTTPException(
                status_code=422, detail="索引格式不正确，应为 JSON 数组"
            )
        api_logger.info("远程索引获取成功: %d 个任务", len(data))
        return data
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code if exc.response is not None else 502
        api_logger.error("远程索引获取失败: HTTP %s (%s)", status, url)
        raise HTTPException(
            status_code=status, detail=f"远程返回错误: {status} ({url})"
        ) from exc
    except Exception as exc:
        api_logger.error("远程索引获取失败: %s (%s)", exc, url)
        raise HTTPException(status_code=502, detail=f"获取索引失败: {exc}") from exc


@app.get("/api/repo/task")
def repo_fetch_task(url: str = Query(..., description="任务 JSON 地址")) -> dict:
    """代理获取单个任务配置"""
    import httpx

    url = _normalize_repo_url(url)
    api_logger.info("下载远程任务: %s", url)

    try:
        resp = _repo_get(url)
        data = resp.json()
        if not isinstance(data, dict):
            raise HTTPException(
                status_code=422, detail="任务格式不正确，应为 JSON 对象"
            )
        api_logger.info("远程任务下载成功: %s", data.get("name", "未命名"))
        return data
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code if exc.response is not None else 502
        api_logger.error("远程任务下载失败: HTTP %s (%s)", status, url)
        raise HTTPException(
            status_code=status, detail=f"远程返回错误: {status} ({url})"
        ) from exc
    except Exception as exc:
        api_logger.error("远程任务下载失败: %s (%s)", exc, url)
        raise HTTPException(status_code=502, detail=f"获取任务失败: {exc}") from exc


# ==================== 安全模式 API ====================


@app.get("/api/safe-mode")
def get_safe_mode() -> dict:
    return {"enabled": service.safe_mode}


@app.post("/api/safe-mode")
def toggle_safe_mode() -> dict:
    try:
        new_value = service.toggle_safe_mode()
        api_logger.info("Safe mode toggled -> %s", new_value)
        return {"enabled": new_value}
    except Exception as exc:
        api_logger.error("切换安全模式失败: %s", exc)
        raise HTTPException(status_code=500, detail=f"切换安全模式失败: {exc}")


# ==================== 调试 API ====================


@app.post("/api/debug/start")
async def debug_start(request: Request) -> dict:
    global _debug_session
    body = await request.json()
    task_id = body.get("task_id", "")
    if not task_id:
        raise HTTPException(status_code=400, detail="缺少 task_id")

    from src.task_executor import TaskManager

    tm = TaskManager(PROJECT_ROOT / "tasks")
    task = tm.load_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    # 构建环境变量（复用 service 的运行时配置）
    runtime_config = service.get_runtime_config()
    env_vars = build_login_env_vars(
        runtime_config, task.url, runtime_config.get("custom_variables", {})
    )

    # 解析任务 URL
    url = task.url or ""
    for k, v in env_vars.items():
        url = url.replace("{{" + k + "}}", v)

    browser_timeout = runtime_config.get("browser_settings", {}).get(
        "timeout", 10000
    )

    # 构建 Worker 启动数据
    worker_data = {
        "config": runtime_config,
        "task_url": url if url else "",
        "task_data": task.to_dict(),
        "env_vars": env_vars,
        "screenshot_dir": str(TEMP_DIR),
        "default_timeout": browser_timeout,
    }

    async with _debug_lock:
        # 修复：整个会话创建放在锁内，防止并发请求泄漏浏览器进程
        if _debug_session.session:
            await _debug_session.session.close()
        if _debug_session._timer_task and not _debug_session._timer_task.done():
            _debug_session._timer_task.cancel()
            try:
                await _debug_session._timer_task
            except asyncio.CancelledError:
                pass

        session = DebugSession()
        try:
            # DebugSession.start() 通过 asyncio.to_thread 提交到 Worker，
            # Worker 线程内启动浏览器、导航、创建 TaskExecutor（page 安全）
            await session.start(
                runtime_config, url if url else None, safe_mode=service.safe_mode
            )

            steps_info = [
                {
                    "index": i,
                    "id": step.id,
                    "type": step.type,
                    "description": step.description or step.type,
                }
                for i, step in enumerate(task.steps)
            ]

            gen = _next_debug_gen()
            _debug_session = empty_debug_session()
            _debug_session.session = session
            _debug_session.task_id = task_id
            _debug_session.steps = steps_info
            _debug_session.running = True
            _debug_session._last_activity = time.monotonic()
            _debug_session._timer_task = asyncio.create_task(
                _debug_timeout_watcher(gen)
            )
            # TaskExecutor 在 Worker 线程内创建，API 线程不再持有引用
            _debug_session.executor = None
            # Worker 返回的初始截图 URL
            response = await asyncio.to_thread(
                lambda: get_worker().submit(CMD_DEBUG_START, data=worker_data)
            )
            if response.success and isinstance(response.data, dict):
                _debug_session.screenshot_url = response.data.get("screenshot_url")
        except Exception:
            await session.close()
            raise

    api_logger.info("Debug session started for task %s", task_id)
    return _debug_response()


@app.post("/api/debug/next")
async def debug_next() -> dict:
    async with _debug_exec_sem:
        async with _debug_lock:
            _require_debug_session()
            idx = _debug_session.current_step

            if idx >= len(_debug_session.steps):
                return {**_debug_response(), "message": "所有步骤已执行完毕"}

        # 通过 Worker 执行单步调试，TaskExecutor 在 Worker 线程内操作 page
        response = await asyncio.to_thread(
            lambda: get_worker().submit(
                CMD_DEBUG_STEP, data={"step_index": idx}
            )
        )
        if not response.success:
            async with _debug_lock:
                _debug_session.results.append(
                    {
                        "step_index": idx,
                        "success": False,
                        "message": response.error or "步骤执行失败",
                        "screenshot_url": None,
                    }
                )
                _debug_session.current_step = idx + 1
                _debug_session._last_activity = time.monotonic()
                return _debug_response()

        result = response.data

        async with _debug_lock:
            _debug_session.results.append(result)
            _debug_session.screenshot_url = result.get("screenshot_url")
            _debug_session.current_step = idx + 1
            _debug_session._last_activity = time.monotonic()
            return _debug_response()


@app.post("/api/debug/run-all")
async def debug_run_all() -> dict:
    async with _debug_exec_sem:
        async with _debug_lock:
            _require_debug_session()
            from_idx = _debug_session.current_step

            if from_idx >= len(_debug_session.steps):
                return {**_debug_response(), "message": "所有步骤已执行完毕"}

        worker = get_worker()
        results: list[dict] = []
        all_success = True

        # 逐步骤通过 Worker 执行，TaskExecutor 在 Worker 线程内操作 page
        for i in range(from_idx, len(_debug_session.steps)):
            response = await asyncio.to_thread(
                lambda idx=i: worker.submit(
                    CMD_DEBUG_STEP, data={"step_index": idx}
                )
            )
            if not response.success:
                # Worker 级错误（非步骤失败）
                results.append(
                    {
                        "step_index": i,
                        "success": False,
                        "message": response.error or "步骤执行异常",
                        "screenshot_url": None,
                    }
                )
                all_success = False
                break

            step_result = response.data
            results.append(step_result)
            if not step_result.get("success", False):
                all_success = False
                break

        async with _debug_lock:
            _debug_session.results.extend(results)
            _debug_session.current_step = (
                len(_debug_session.steps) if all_success else from_idx + len(results)
            )
            _debug_session._last_activity = time.monotonic()
            if results:
                _debug_session.screenshot_url = results[-1].get("screenshot_url")
            return _debug_response()


@app.post("/api/debug/stop")
async def debug_stop() -> dict:
    global _debug_session
    async with _debug_exec_sem:
        async with _debug_lock:
            timer = _debug_session._timer_task
            if timer and not timer.done():
                timer.cancel()
                try:
                    await timer
                except asyncio.CancelledError:
                    pass
            if _debug_session.session:
                await _debug_session.session.close()
            _debug_session = empty_debug_session()
    # 清理临时调试截图
    try:
        import shutil

        if TEMP_DIR.exists():
            shutil.rmtree(TEMP_DIR, ignore_errors=True)
            TEMP_DIR.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    api_logger.info("Debug session stopped")
    return {"running": False, "message": "调试会话已关闭"}


@app.get("/api/debug/status")
async def debug_status() -> dict:
    async with _debug_lock:
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
            "carrier": settings.carrier,
            "carrier_custom": settings.carrier_custom,
            "use_global_auth_url": settings.use_global_auth_url,
            "auth_url": settings.auth_url,
            "use_global_task": settings.use_global_task,
            "active_task": settings.active_task,
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
        gateway,
        ssid,
        matched_id,
    )
    return {
        "gateway_ip": gateway,
        "ssid": ssid,
        "matched_profile_id": matched_id,
        "matched_profile_name": matched_name,
    }


@app.post("/api/profiles/auto-switch", response_model=ActionResponse)
def toggle_auto_switch(enabled: str = Query(default="true")) -> ActionResponse:
    enabled_bool = enabled.strip().lower() in ("true", "1", "yes", "on")
    profile_service.set_auto_switch(enabled_bool)
    state = "开启" if enabled_bool else "关闭"
    api_logger.info("Auto-switch %s", state)
    return ActionResponse(success=True, message=f"自动切换已{state}")


@app.post("/api/shutdown", response_model=ActionResponse)
def shutdown_server() -> ActionResponse:
    """关闭服务器"""
    api_logger.warning("Shutdown requested")
    import threading

    def _do_shutdown():
        try:
            service.stop_monitoring()
        except Exception:
            pass
        # 故意使用 os._exit(0) 而非 sys.exit(0)：sys.exit() 在 daemon 线程中仅退出该线程，
        # 不会终止进程；os._exit(0) 是 Windows 上唯一可靠的立即退出方式。
        # 日志已由 _DateRotatingFileHandler.emit() 即时写入，无需额外刷盘。
        try:
            (Path.home() / ".campus_network_auth" / "campus_network_auth.pid").unlink(missing_ok=True)
        except Exception:
            pass
        os._exit(0)

    threading.Thread(target=_do_shutdown, daemon=True).start()

    return ActionResponse(success=True, message="服务器正在关闭...")


# ==================== 卸载 API ====================


@app.get("/api/uninstall/detect")
def uninstall_detect() -> list[dict]:
    """检测可清理的外部残留项目"""
    from backend.uninstall_service import detect

    items = detect()
    return [
        {
            "key": it.key,
            "label": it.label,
            "exists": it.exists,
            "path": it.path,
            "size_mb": round(it.size_mb, 1),
        }
        for it in items
    ]


@app.post("/api/uninstall")
def uninstall_perform(payload: dict) -> dict:
    """执行卸载清理"""
    from backend.uninstall_service import perform

    keys = payload.get("keys", [])
    api_logger.warning("Uninstall requested, keys=%s", keys)
    results = perform(keys)
    return {
        "success": all(r.success for r in results),
        "results": [
            {"key": r.key, "label": r.label, "success": r.success, "message": r.message}
            for r in results
        ],
    }


# ==================== 配置备份与恢复 API ====================

_BACKUP_DIR = PROJECT_ROOT / "backups"
_BACKUP_DIR.mkdir(parents=True, exist_ok=True)
MAX_BACKUPS = 20


def _cleanup_old_backups(max_backups: int = MAX_BACKUPS) -> None:
    """清理旧备份，仅保留最新的 max_backups 个文件"""
    backups = sorted(_BACKUP_DIR.glob("settings_*.json"), reverse=True)
    for old in backups[max_backups:]:
        try:
            old.unlink()
        except OSError:
            pass


@app.get("/api/backup/list")
def list_backups() -> list[dict]:
    """列出所有备份"""
    backups = []
    for f in sorted(_BACKUP_DIR.glob("settings_*.json"), reverse=True):
        stat = f.stat()
        backups.append(
            {
                "filename": f.name,
                "size": stat.st_size,
                "created": datetime.fromtimestamp(stat.st_mtime).strftime(
                    "%Y-%m-%d %H:%M:%S"
                ),
            }
        )
    return backups


@app.post("/api/backup/create", response_model=ActionResponse)
def create_backup() -> ActionResponse:
    """创建当前配置的备份"""
    settings_path = PROJECT_ROOT / "settings.json"
    if not settings_path.exists():
        raise HTTPException(status_code=404, detail="settings.json 不存在，无需备份")

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = _BACKUP_DIR / f"settings_{stamp}.json"

    try:
        backup_path.write_bytes(settings_path.read_bytes())
        _cleanup_old_backups()
        api_logger.info("备份已创建: %s", backup_path.name)
        return ActionResponse(success=True, message=f"备份已创建: {backup_path.name}")
    except Exception as exc:
        api_logger.error("创建备份失败: %s", exc)
        raise HTTPException(status_code=500, detail=f"创建备份失败: {exc}")


@app.post("/api/backup/restore/{filename}", response_model=ActionResponse)
def restore_backup(filename: str) -> ActionResponse:
    """从备份恢复配置"""
    backup_path = _BACKUP_DIR / filename
    if not backup_path.exists():
        raise HTTPException(status_code=404, detail="备份文件不存在")

    # 安全校验：文件名格式 settings_YYYYMMDD_HHMMSS[_ffffff][_autosave].json
    if not re.match(BACKUP_FILENAME_PATTERN, filename):
        raise HTTPException(status_code=400, detail="无效的备份文件名")

    # 恢复前先自动创建当前配置的备份
    settings_path = PROJECT_ROOT / "settings.json"
    if settings_path.exists():
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        auto_backup = _BACKUP_DIR / f"settings_{stamp}_autosave.json"
        try:
            auto_backup.write_bytes(settings_path.read_bytes())
        except Exception:
            pass

    try:
        backup_data = json.loads(backup_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        api_logger.error("备份文件不是有效 JSON: %s — %s", filename, exc)
        raise HTTPException(status_code=400, detail=f"备份文件格式损坏: {exc}")

    try:
        ProfilesData.model_validate(backup_data)
    except Exception as exc:
        api_logger.error("备份文件 schema 校验失败: %s — %s", filename, exc)
        raise HTTPException(status_code=400, detail=f"备份文件结构不合法: {exc}")

    try:
        atomic_write(settings_path, backup_path.read_text(encoding="utf-8"))
        # 清除 ProfileService 缓存，强制从磁盘重新读取
        profile_service.invalidate_cache()
        service.reload_config()
        _cleanup_old_backups()
        api_logger.info("配置已从备份恢复: %s", filename)
        return ActionResponse(success=True, message="配置已从备份恢复，请刷新页面查看")
    except Exception as exc:
        api_logger.error("恢复备份失败: %s", exc)
        raise HTTPException(status_code=500, detail=f"恢复备份失败: {exc}")


@app.get("/api/backup/download/{filename}")
def download_backup(filename: str):
    """下载备份文件"""
    if not re.match(BACKUP_FILENAME_PATTERN, filename):
        raise HTTPException(status_code=400, detail="无效的备份文件名")
    backup_path = _BACKUP_DIR / filename
    if not backup_path.exists():
        raise HTTPException(status_code=404, detail="备份文件不存在")
    return FileResponse(
        backup_path,
        media_type="application/json",
        filename=filename,
    )


@app.delete("/api/backup/{filename}", response_model=ActionResponse)
def delete_backup(filename: str) -> ActionResponse:
    """删除备份"""
    if not re.match(BACKUP_FILENAME_PATTERN, filename):
        raise HTTPException(status_code=400, detail="无效的备份文件名")

    backup_path = _BACKUP_DIR / filename
    if not backup_path.exists():
        raise HTTPException(status_code=404, detail="备份文件不存在")

    try:
        backup_path.unlink()
        api_logger.info("备份已删除: %s", filename)
        return ActionResponse(success=True, message="备份已删除")
    except Exception as exc:
        api_logger.error("删除备份失败: %s", exc)
        raise HTTPException(status_code=500, detail=f"删除备份失败: {exc}")


TEMP_DIR = PROJECT_ROOT / "temp"
TEMP_DIR.mkdir(parents=True, exist_ok=True)

app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")
app.mount("/debug", StaticFiles(directory=DEBUG_DIR), name="debug")
app.mount("/temp", StaticFiles(directory=TEMP_DIR), name="temp")


def run() -> None:
    import uvicorn

    # 优先从 settings.json 读取系统设置（Web 控制台可修改）
    try:
        sys_settings = profile_service.load().system
        log_level = sys_settings.backend_log_level or "WARNING"
        access_log_enabled = bool(sys_settings.access_log)
        log_retention = max(1, sys_settings.log_retention_days)
        sc_retention = max(1, sys_settings.screenshot_retention_days)
    except Exception:
        log_level = "WARNING"
        access_log_enabled = False
        log_retention = 7
        sc_retention = 7

    # 使用日志配置中心统一配置
    log_center = LogConfigCenter.get_instance()
    log_center.initialize({"level": log_level}, side="BACKEND")
    # 压制 PIL 库的 DEBUG 日志，避免启动时大量 "Importing XxxImagePlugin" 刷屏
    logging.getLogger("PIL").setLevel(logging.WARNING)

    # 启用日志持久化到文件（按天存储，自动清理过期日志和截图）
    log_dir = PROJECT_ROOT / "logs"
    try:
        # 文件始终记录完整日志，不受前后端日志级别限制
        log_center.add_file_handler(str(log_dir), retention_days=log_retention)
        today_log = log_dir / f"{datetime.now().strftime('%Y-%m-%d')}.log"
        print(f"[Campus-Auth] 日志文件: {today_log}")
        startup_logger.info("日志文件: %s", today_log)
        # 清理旧版日志文件，避免混淆
        old_log = log_dir / "campus_auth.log"
        if old_log.exists():
            old_log.unlink(missing_ok=True)
    except Exception:
        pass

    # 自动清理过期的调试截图（按日期子目录）
    try:
        from src.utils.logging import cleanup_debug_screenshots

        n = cleanup_debug_screenshots(str(DEBUG_DIR), sc_retention)
        if n:
            startup_logger.info("清理过期截图: %d 张", n)
    except Exception:
        pass

    global _access_log_enabled
    _access_log_enabled = access_log_enabled

    # 始终禁用 Uvicorn 内置 access log，由自定义中间件统一处理，避免重复输出
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
