"""E2E 测试共享 fixture — 真实应用 + 真实服务栈。

仅 mock 外部危险边界（cleanup_orphan_browsers 防误杀真实浏览器进程）。
其他服务（engine、config、profiles、tasks、scheduler、autostart）全部真实运行。

设计原则：
- 真实 ServiceContainer.startup() → 真实 engine.boot()
- 真实配置文件读写（tmp_path 隔离）
- 真实 API 路由（不 mock router）
- 真实脚本子进程执行
- 仅在需要时启动真实 Playwright（real_browser fixture）
"""

from __future__ import annotations

import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

# ── 配置文件初始化 ──


def _write_minimal_config(project_root: Path, **overrides) -> None:
    """写入最小可运行的 settings.json + 默认 profile。"""
    config_dir = project_root / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    profiles_dir = config_dir / "profiles"
    profiles_dir.mkdir(exist_ok=True)

    # 最小全局配置 — 加速测试
    # 结构必须匹配 ProfilesData schema：global_config（不是 global_settings）
    settings = {
        "auto_switch": False,
        "active_profile": "default",
        "global_config": {
            "monitor": {
                "check_interval_seconds": 10,  # 最小值，加速测试
                "script_timeout": 10,  # 脚本超时 10 秒（timeout 测试依赖）
                "enable_tcp_check": True,
                "enable_http_check": False,
                "enable_local_check": False,
            },
            "retry": {
                "max_retries": 1,
                "retry_interval": 1,
            },
            "pause": {
                "enabled": False,
            },
            "browser": {
                "headless": True,
            },
        },
        "profiles": {
            "default": {
                "name": "E2E 默认方案",
                "username": "e2e_user",
                "password": "e2e_pass",
                "auth_url": "http://127.0.0.1:1/",  # 占位，由 http_portal fixture 覆盖
                "carrier": "无",
            }
        },
    }
    settings.update(overrides)
    (config_dir / "settings.json").write_text(
        json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _ensure_dir_layout(project_root: Path) -> None:
    """创建运行所需的目录布局。"""
    for d in [
        "frontend",
        "debug/logs",
        "temp",
        "tasks/browser",
        "tasks/scripts",
        "tasks/scheduled/history",
        "config/browser-data",
        "resources/icons",
    ]:
        (project_root / d).mkdir(parents=True, exist_ok=True)
    # 最小前端入口
    index = project_root / "frontend" / "index.html"
    if not index.exists():
        index.write_text("<html><body>E2E</body></html>", encoding="utf-8")


@pytest.fixture
def e2e_project(tmp_path: Path):
    """准备隔离的项目根目录，patch 所有路径常量。

    Yields:
        tmp_path（已 patch 为 PROJECT_ROOT）
    """
    # 重置 ProfileService 单例 — 确保每个测试使用独立的 tmp_path
    from app.services.profile_service import reset_profile_service_singleton

    reset_profile_service_singleton()

    _ensure_dir_layout(tmp_path)
    _write_minimal_config(tmp_path)

    # 让 Worker 子进程（manual login 等走 CMD_LOGIN 的通道）也能定位到 tmp_path。
    # 子进程不继承 pytest 运行期的 unittest.mock.patch，因此会回退到 PROJECT_ROOT
    # 常量（真实项目根），与 API 写入 tmp_path 不一致 → 找不到任务。
    # 通过环境变量传递，子进程 spawn 时会继承该值。
    import os

    _orig_root_env = os.environ.get("CAMPUS_AUTH_PROJECT_ROOT")
    os.environ["CAMPUS_AUTH_PROJECT_ROOT"] = str(tmp_path)

    # 关键：patch 所有路径常量，确保 ServiceContainer 使用 tmp_path
    # 同时 patch app.application 的模块级导入（from app.constants import PROJECT_ROOT 等），
    # 否则首次 import 后模块级引用绑定到第一个测试的 tmp_path，后续测试无法覆盖
    try:
        with (
            patch("app.constants.PROJECT_ROOT", tmp_path),
            patch("app.application.PROJECT_ROOT", tmp_path),
            patch("app.constants.FRONTEND_DIR", tmp_path / "frontend"),
            patch("app.application.FRONTEND_DIR", tmp_path / "frontend"),
            patch("app.constants.DEBUG_DIR", tmp_path / "debug"),
            patch("app.application.DEBUG_DIR", tmp_path / "debug"),
            patch("app.constants.LOGS_DIR", tmp_path / "debug" / "logs"),
            patch("app.application.LOGS_DIR", tmp_path / "debug" / "logs"),
            patch("app.constants.SCREENSHOTS_DIR", tmp_path / "debug" / "screenshots"),
            patch("app.application.SCREENSHOTS_DIR", tmp_path / "debug" / "screenshots"),
            patch("app.constants.TEMP_DIR", tmp_path / "temp"),
            patch("app.application.TEMP_DIR", tmp_path / "temp"),
            patch("app.constants.BROWSER_DATA_DIR", tmp_path / "config" / "browser-data"),
        ):
            yield tmp_path
    finally:
        # 恢复环境变量，避免污染后续测试进程
        if _orig_root_env is None:
            os.environ.pop("CAMPUS_AUTH_PROJECT_ROOT", None)
        else:
            os.environ["CAMPUS_AUTH_PROJECT_ROOT"] = _orig_root_env


@pytest.fixture
def real_app(e2e_project):
    """启动真实 FastAPI 应用 + 真实 ServiceContainer。

    Mock 边界：
    - cleanup_orphan_browsers：防止误杀测试环境外的真实浏览器
    - resolve_port：固定端口避免冲突
    - ScheduleEngine.boot：只启动线程，不自动启动监控（避免访问外网/触发 Playwright）

    其他全部真实：config_service、profile_service、task_executor、scheduler、autostart 等。
    需要监控的测试可显式调用 POST /api/monitor/start。
    """
    from app.application import create_app
    from app.services.engine import ScheduleEngine

    fixed_port = _pick_free_port()

    # 保存原始 boot，替换为只启动线程不启动监控的版本
    original_boot = ScheduleEngine.boot

    def _boot_thread_only(self):
        """E2E 专用 boot：只启动引擎线程，不自动启动监控。"""
        if self._engine_thread is not None and self._engine_thread.is_alive():
            return
        self._start_engine_thread()

    ScheduleEngine.boot = _boot_thread_only

    with (
        patch("app.workers.playwright_worker.cleanup_orphan_browsers"),
        patch("app.services.worker_port.cleanup_orphan_browsers"),
        patch("app.application.resolve_port", return_value=fixed_port),
        patch("app.application._cleanup_temp_screenshots"),
        patch("app.application._cleanup_dated_screenshots"),
        patch("app.version.get_project_version", return_value="0.0.0-e2e"),
        # system.py 通过 from ... import 在模块级绑定 get_project_version，
        # 若完整套件中 system.py 已被前序测试导入，app.version 上的 patch 不再生效，
        # 需直接 patch system 模块的绑定（与 patch app.application.PROJECT_ROOT 同理）
        patch("app.api.system.get_project_version", return_value="0.0.0-e2e"),
    ):
        app = create_app()
        try:
            with TestClient(app) as client:
                yield client, app
        finally:
            ScheduleEngine.boot = original_boot


# ── 本地 HTTP 门户服务（模拟认证页面）──


class _PortalHandler(BaseHTTPRequestHandler):
    """模拟校园网认证门户。

    行为：
    - GET /: 返回登录表单
    - POST /login: 校验 username/password，成功返回 success.html，失败返回 fail.html
    - GET /success: 返回 200 + "Success"（用于网络检测兜底）
    - GET /generate_204: 返回 204（用于 HTTP 探测）
    """

    # 静默日志
    def log_message(self, fmt, *args):
        pass

    def do_GET(self):
        if self.path == "/" or self.path.startswith("/?"):
            self._html(_LOGIN_FORM_HTML)
        elif self.path == "/success":
            self._html("<html><body>Success</body></html>")
        elif self.path == "/generate_204":
            self.send_response(204)
            self.end_headers()
        elif self.path == "/hotspot-detect.html":
            self._html("Success\n")
        else:
            self._html(f"<html><body>path: {self.path}</body></html>")

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8", errors="replace") if length else ""
        # 简单解析表单
        params = {}
        for pair in body.split("&"):
            if "=" in pair:
                k, v = pair.split("=", 1)
                params[k] = v

        username = params.get("username", "")
        password = params.get("password", "")

        if username == "e2e_user" and password == "e2e_pass":
            self._html(_SUCCESS_HTML)
        else:
            self._html(_FAIL_HTML)

    def _html(self, content: str, status: int = 200):
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        body = content.encode("utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


_LOGIN_FORM_HTML = """<!DOCTYPE html>
<html><head><title>校园网认证</title></head>
<body>
<form id="loginForm" method="POST" action="/login">
  <input id="username" name="username" type="text" placeholder="用户名"/>
  <input id="password" name="password" type="password" placeholder="密码"/>
  <button id="loginBtn" type="submit">登录</button>
</form>
</body></html>"""

_SUCCESS_HTML = "<html><body>登录成功</body></html>"
_FAIL_HTML = "<html><body>登录失败：用户名或密码错误</body></html>"


def _pick_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def http_portal():
    """启动本地 HTTP 门户服务，返回 (host, port, base_url)。

    模拟校园网认证页面，支持表单登录和多个网络检测路径。
    """
    port = _pick_free_port()
    server = ThreadingHTTPServer(("127.0.0.1", port), _PortalHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    # 等待服务就绪
    for _ in range(20):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                break
        except OSError:
            time.sleep(0.05)

    yield "127.0.0.1", port, f"http://127.0.0.1:{port}"

    server.shutdown()
    server.server_close()
    thread.join(timeout=2)


# ── 真实 Playwright 浏览器 ──


@pytest.fixture
def real_browser():
    """启动真实 Playwright Chromium 浏览器（headless）。

    若 Chromium 未安装则跳过测试。
    """
    from playwright.sync_api import sync_playwright

    try:
        pw = sync_playwright().start()
        browser = pw.chromium.launch(headless=True)
        yield browser
        browser.close()
        pw.stop()
    except Exception as e:
        if "Executable doesn't exist" in str(e) or "playwright install" in str(e):
            pytest.skip(f"Chromium 未安装: {e}")
        raise
