"""前端 E2E 测试共享 fixture — 真实 uvicorn 服务器 + 真实 Playwright。

复用 tests/test_e2e/conftest.py 的 e2e_project fixture 隔离项目目录，
通过 uvicorn 在真实端口启动应用，让 Playwright 可访问。

设计原则：
- 真实 ServiceContainer.startup() → 真实 engine 线程（不自动启动监控）
- 真实配置文件读写（tmp_path 隔离）
- 真实 API 路由（不 mock router）
- 仅 mock 外部危险边界（cleanup_orphan_browsers 防误杀真实浏览器进程）
- 预创建 .agree 文件跳过首次启动向导（page_regression 不需要测向导）
"""

from __future__ import annotations

import json
import socket
import threading
import time as _time
import urllib.request
from pathlib import Path
from unittest.mock import patch

import pytest

# ── 项目目录与配置初始化（从 tests/test_e2e/conftest.py 复制）──


def _write_minimal_config(project_root: Path, **overrides) -> None:
    """写入最小可运行的 settings.json + 默认 profile。

    结构必须匹配 ProfilesData schema：global_config（不是 global_settings）。
    """
    config_dir = project_root / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    profiles_dir = config_dir / "profiles"
    profiles_dir.mkdir(exist_ok=True)

    settings = {
        "auto_switch": False,
        "active_profile": "default",
        "global_config": {
            "monitor": {
                # check_interval_seconds 最小值 10（schema ge=10）
                "check_interval_seconds": 10,
                "script_timeout": 10,
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
                "auth_url": "http://127.0.0.1:1/",
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

    注意：
    - FRONTEND_DIR 保持真实前端目录，E2E 测试需要真实 Vue SPA 文件。
    - 必须同时 patch `app.constants` 与 `app.application` 两个模块的常量引用：
      `application.py` 顶部 `from app.constants import PROJECT_ROOT` 是值绑定，
      仅 patch `app.constants.PROJECT_ROOT` 不会影响 application 模块内已绑定的 PROJECT_ROOT。
      ServiceContainer 在 lifespan 内用 `PROJECT_ROOT` 创建，必须 patch 后者才能让
      ServiceContainer 真正使用 tmp_path（这样 /api/init-status 才能读到 tmp_path/config/.agree）。
    - 重置 ProfileService 单例，确保每次测试用独立 tmp_path 重建缓存。
    """
    # 重置 ProfileService 单例 — 确保每个测试使用独立的 tmp_path
    from app.services.profile_service import reset_profile_service_singleton

    reset_profile_service_singleton()

    _ensure_dir_layout(tmp_path)
    _write_minimal_config(tmp_path)

    # 在 patch 前捕获真实前端目录（patch 后 FRONTEND_DIR 会被覆盖）
    from app.constants import FRONTEND_DIR as _real_frontend

    with (
        # patch app.constants 模块属性（影响所有通过 `app.constants.XXX` 访问的代码）
        patch("app.constants.PROJECT_ROOT", tmp_path),
        patch("app.constants.FRONTEND_DIR", _real_frontend),
        patch("app.constants.DEBUG_DIR", tmp_path / "debug"),
        patch("app.constants.LOGS_DIR", tmp_path / "debug" / "logs"),
        patch("app.constants.SCREENSHOTS_DIR", tmp_path / "debug" / "screenshots"),
        patch("app.constants.TEMP_DIR", tmp_path / "temp"),
        patch("app.constants.BROWSER_DATA_DIR", tmp_path / "config" / "browser-data"),
        # 同时 patch app.application 模块内已绑定的引用（值绑定后不会跟随 constants）
        # 这是 lifespan 内 `ServiceContainer(PROJECT_ROOT)` 真正读取的位置
        patch("app.application.PROJECT_ROOT", tmp_path),
        patch("app.application.FRONTEND_DIR", _real_frontend),
        patch("app.application.DEBUG_DIR", tmp_path / "debug"),
        patch("app.application.LOGS_DIR", tmp_path / "debug" / "logs"),
        patch("app.application.SCREENSHOTS_DIR", tmp_path / "debug" / "screenshots"),
        patch("app.application.TEMP_DIR", tmp_path / "temp"),
    ):
        yield tmp_path


def _pick_free_port() -> int:
    """选取一个空闲端口。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_for_server(base_url: str, timeout_s: float = 15.0) -> None:
    """轮询健康检查接口直到服务器就绪。"""
    deadline = _time.monotonic() + timeout_s
    last_err: Exception | None = None
    while _time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"{base_url}/api/health", timeout=0.5) as resp:
                if resp.status == 200:
                    return
        except Exception as e:
            last_err = e
            _time.sleep(0.1)
    raise RuntimeError(f"uvicorn 启动超时: {last_err}")


# ── live_app fixture：真实 uvicorn + 真实 ServiceContainer ──


@pytest.fixture
def live_app(e2e_project):
    """启动真实 uvicorn 服务器，返回 (base_url, app)。

    复用 tests/test_e2e/conftest.py 的 e2e_project fixture 隔离项目目录。

    Mock 边界：
    - ScheduleEngine.boot：只启动线程不启动监控（避免访问外网）
    - cleanup_orphan_browsers：防止误杀测试环境外浏览器
    - resolve_port：固定端口避免冲突
    - _cleanup_temp_screenshots / _cleanup_dated_screenshots：跳过截图清理
    - get_project_version：固定版本号

    Yields:
        (base_url, app) — 服务器 base_url 和 FastAPI 实例
    """
    # 预创建 .agree 文件跳过首次启动向导（page_regression 不需要测向导）
    (e2e_project / "config" / ".agree").write_text("", encoding="utf-8")

    port = _pick_free_port()
    base_url = f"http://127.0.0.1:{port}"

    from app.application import create_app
    from app.services.engine import ScheduleEngine

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
        patch("app.application.resolve_port", return_value=port),
        patch("app.application._cleanup_temp_screenshots"),
        patch("app.application._cleanup_dated_screenshots"),
        patch("app.version.get_project_version", return_value="0.0.0-e2e"),
    ):
        app = create_app()

        import uvicorn

        uv_config = uvicorn.Config(
            app,
            host="127.0.0.1",
            port=port,
            reload=False,
            log_level="warning",
            access_log=False,
            ws_max_size=65536,
        )
        server = uvicorn.Server(uv_config)
        app.state._uvicorn_server = server

        thread = threading.Thread(target=server.run, daemon=True, name="test-uvicorn")
        thread.start()

        try:
            _wait_for_server(base_url)
            yield base_url, app
        finally:
            server.should_exit = True
            thread.join(timeout=5)
            ScheduleEngine.boot = original_boot


# ── browser_page fixture：Playwright Chromium + 新页面 ──


@pytest.fixture
def browser_page(live_app):
    """启动 Playwright Chromium（headless），yield page，关闭。

    依赖 live_app 启动 uvicorn 服务器。若 Chromium 未安装则跳过。
    """
    from playwright.sync_api import sync_playwright

    base_url, _ = live_app
    try:
        pw = sync_playwright().start()
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()
        # 捕获控制台错误，便于调试
        page_errors: list[str] = []
        page.on("pageerror", lambda exc: page_errors.append(str(exc)))
        try:
            yield page
        finally:
            # 测试期间检查是否有 JS 异常（仅记录到 stdout，不强制失败）
            if page_errors:
                print(f"[browser_page] JS errors during test: {page_errors}")
            page.close()
            context.close()
            browser.close()
            pw.stop()
    except Exception as e:
        if "Executable doesn't exist" in str(e) or "playwright install" in str(e):
            pytest.skip(f"Chromium 未安装: {e}")
        raise


# ── 通用辅助函数 ──


# 页面 ID → 侧边栏中文标签映射
_PAGE_LABELS = {
    "dashboard": "仪表盘",
    "settings": "设置",
    "tasks": "任务管理",
    "about": "关于",
    "profiles": "配置方案",
    "scripts": "自定义脚本",
    "scheduled_tasks": "定时任务",
    "appearance": "外观",
}

# 需要先展开"更多"菜单才能访问的子页面
_SUB_PAGES = {"profiles", "scripts", "scheduled_tasks", "appearance"}


def _navigate_to(page, page_name: str) -> None:
    """通过侧边栏导航到指定页面。

    Args:
        page: Playwright Page 实例
        page_name: 目标页面 ID（dashboard/settings/tasks/about/
                   profiles/scripts/scheduled_tasks/appearance）
    """
    label = _PAGE_LABELS.get(page_name, page_name)
    if page_name in _SUB_PAGES:
        # 子页面需要先展开"更多"菜单
        more_trigger = page.locator(".nav-more-trigger")
        if more_trigger.count() > 0 and not page.locator(
            ".nav-more-menu .nav-item", has_text=label
        ).first.is_visible():
            more_trigger.first.click()
            page.wait_for_timeout(300)
        # 点击子菜单项
        page.locator(".nav-more-menu .nav-item", has_text=label).first.click()
    else:
        # 主导航项
        page.locator(".nav-links > .nav-item", has_text=label).first.click()
    page.wait_for_timeout(400)


def _goto_app(page, base_url: str) -> None:
    """打开应用首页并等待 Vue 挂载完成。"""
    page.goto(base_url, wait_until="networkidle")
    # 等待 #app 显示（Vue mounted 后会移除 display:none）
    page.wait_for_selector("#app .sidebar", state="visible", timeout=15000)
    # 等待骨架屏消失、仪表盘渲染完成
    page.wait_for_selector(".stats-grid, .empty-state", state="visible", timeout=10000)


# ── 辅助函数 fixture ──
# 通过 fixture 暴露辅助函数，避免相对导入问题


@pytest.fixture
def goto_app():
    """返回 goto_app 辅助函数。"""
    return _goto_app


@pytest.fixture
def navigate_to():
    """返回 navigate_to 辅助函数。"""
    return _navigate_to
