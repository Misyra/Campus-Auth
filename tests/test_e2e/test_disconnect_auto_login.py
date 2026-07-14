"""断网 → 监控自动触发登录 → 恢复 端到端测试。

验证应用的核心价值链路：
- 监控循环通过认证门户连通性探测（URL 检测）判断网络状态；
- 检测到「断网」（探测失败）时**自动**触发登录编排器；
- 登录编排器经 Worker 执行 active_task 浏览器任务，真实用 Playwright 登录门户；
- 登录成功后写入登录历史；
- 恢复网络后监控重新判定为「已连接」，且不再重复触发登录。

与 test_app_lifecycle::test_monitor_start_stop_toggle 的区别：
- 那个测试把 URL 检测指向「永远在线」的门户，**永远不会触发登录**；
- 本测试首次让监控真正经历「在线 → 断网 → 自动登录 → 恢复」的完整生命周期。

需要 Chromium 已安装（uv run playwright install chromium）。
"""

from __future__ import annotations

import os
import socket
import threading
import time

import pytest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

pytestmark = pytest.mark.slow


# ── Chromium 可用性检查（模块级，只检查一次）──


@pytest.fixture(scope="module", autouse=True)
def _ensure_chromium():
    """确保 Chromium 已安装，未安装则跳过模块内所有测试。"""
    from playwright.sync_api import sync_playwright

    try:
        pw = sync_playwright().start()
        browser = pw.chromium.launch(headless=True)
        browser.close()
        pw.stop()
    except Exception as e:
        if "Executable doesn't exist" in str(e) or "playwright install" in str(e):
            pytest.skip(f"Chromium 未安装: {e}")


# ── 可控门户：模拟认证门户 + 可切换的连通性探测结果 ──


class _PortalState:
    """门户运行时状态，由 fixture 与测试共享。"""

    def __init__(self) -> None:
        self.online: bool = True


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


class _ControllablePortalHandler(BaseHTTPRequestHandler):
    """可控认证门户。

    - /                或 /?...   → 登录表单
    - POST /login                → 校验凭据，返回成功/失败页
    - /success                   → 连通性探测端点：online 时返回含 Success 的 200，
                                     offline 时返回 503（不含 Success），模拟「断网」
    - /generate_204              → 204
    登录页与 POST /login 在 offline 时仍可用（captive portal 始终可达，可用来登录）。
    """

    state: _PortalState

    def log_message(self, fmt, *args):  # 静默日志
        pass

    def do_GET(self):
        if self.path == "/success":
            if self.state.online:
                self._html("<html><body>Success</body></html>")
            else:
                self.send_response(503)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.end_headers()
                self.wfile.write(b"Disconnected")
        elif self.path == "/generate_204":
            self.send_response(204)
            self.end_headers()
        elif self.path == "/" or self.path.startswith("/?"):
            self._html(_LOGIN_FORM_HTML)
        else:
            self._html(f"<html><body>path: {self.path}</body></html>")

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8", errors="replace") if length else ""
        params = {}
        for pair in body.split("&"):
            if "=" in pair:
                k, v = pair.split("=", 1)
                params[k] = v
        if params.get("username") == "e2e_user" and params.get("password") == "e2e_pass":
            self._html(_SUCCESS_HTML)
        else:
            self._html(_FAIL_HTML)

    def _html(self, content: str, status: int = 200):
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        data = content.encode("utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def _pick_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def controllable_portal():
    """启动可控门户，返回 (_PortalState, base_url)。"""
    state = _PortalState()
    port = _pick_free_port()
    handler_cls = type(
        "ControllablePortalHandler", (_ControllablePortalHandler,), {"state": state}
    )
    server = ThreadingHTTPServer(("127.0.0.1", port), handler_cls)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    # 等待服务就绪
    for _ in range(20):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                break
        except OSError:
            time.sleep(0.05)

    yield state, f"http://127.0.0.1:{port}"

    server.shutdown()
    server.server_close()
    thread.join(timeout=2)


# ── 辅助函数 ──


def _ensure_probes_active() -> None:
    """清空网络探测关闭标志，避免上一轮真实 App 关闭残留影响。"""
    from app.network.probes import _shutdown_event

    _shutdown_event.clear()


def _status(client) -> dict:
    return client.get("/api/status").json()


def _login_success_count(client) -> int:
    history = client.get("/api/login-history").json()
    return sum(1 for h in history if h.get("success"))


def _wait_for(pred, timeout: float, interval: float = 0.5) -> None:
    deadline = time.time() + timeout
    last_err: Exception | None = None
    while time.time() < deadline:
        try:
            if pred():
                return
        except Exception as exc:  # 状态接口偶发未就绪
            last_err = exc
        time.sleep(interval)
    msg = f"条件在 {timeout}s 内未满足"
    if last_err is not None:
        msg += f"（最后异常: {last_err}）"
    pytest.fail(msg)


def _save_browser_task(client, task_id: str, portal_url: str) -> None:
    """创建浏览器任务定义，指向可控门户登录表单（与 test_browser_task 验证过的步骤一致）。"""
    payload = {
        "name": f"E2E 断网自动登录任务 {task_id}",
        "description": "E2E 断网自动登录测试",
        "url": "{{LOGIN_URL}}",
        "timeout": 30000,
        "variables": {
            "username": "{{USERNAME}}",
            "password": "{{PASSWORD}}",
        },
        "steps": [
            {"id": "fill_username", "type": "input", "description": "填写用户名",
             "selector": "#username", "value": "{{username}}", "clear": True},
            {"id": "fill_password", "type": "input", "description": "填写密码",
             "selector": "#password", "value": "{{password}}", "clear": True},
            {"id": "click_login", "type": "click", "description": "点击登录按钮",
             "selector": "#loginBtn"},
            {"id": "verify_success", "type": "assert_text", "description": "验证登录成功",
             "value": "登录成功", "timeout": 15000},
        ],
        "on_success": {"message": "浏览器任务执行成功"},
        "on_failure": {"message": "浏览器任务执行失败", "screenshot": True},
    }
    resp = client.put(f"/api/tasks/{task_id}", json=payload)
    assert resp.status_code == 200, f"保存浏览器任务失败: {resp.text}"


# ── 测试 ──


class TestDisconnectAutoLogin:
    """断网 → 监控自动触发登录 → 恢复 完整生命周期。"""

    def test_disconnect_triggers_auto_login_and_recovers(
        self, real_app, e2e_project, controllable_portal, monkeypatch
    ):
        client, _ = real_app
        tmp_path = e2e_project
        state, portal_base = controllable_portal

        # 让 Worker 的 TaskManager 从 tmp_path 读取任务（与 API 写入位置一致），
        # 否则 Worker 会按文件相对路径去真实项目根找任务而找不到。
        monkeypatch.setenv("CAMPUS_AUTH_PROJECT_ROOT", str(tmp_path))

        _ensure_probes_active()

        task_id = "e2e_auto_login_task"
        _save_browser_task(client, task_id, portal_base)

        # 配置：auth_url 指向门户；仅启用 URL 连通性检测（指向 /success|Success）；
        # 关闭登录前置检查（enable_local_check / check_auth_url），避免无关物理网络判断。
        resp = client.patch(
            "/api/config",
            json={
                "auth_url": portal_base + "/",
                "username": "e2e_user",
                "password": "e2e_pass",
                "active_task": task_id,
                "browser": {"browser_channel": "playwright", "pure_mode": True},
                "monitor": {
                    "enable_tcp_check": False,
                    "enable_http_check": False,
                    "enable_local_check": False,
                    "check_auth_url": False,
                    "url_check_urls": [f"{portal_base}/success|Success"],
                },
            },
        )
        assert resp.status_code == 200, f"更新配置失败: {resp.text}"

        # 1) 起监控（此时在线）→ 应判定「已连接」，且尚未触发登录
        resp = client.post("/api/monitor/start")
        assert resp.status_code == 200, resp.text
        assert resp.json()["success"] is True

        _wait_for(lambda: _status(client)["network_state"] == "connected", timeout=20)
        assert _status(client)["monitoring"] is True
        assert _status(client)["login_attempt_count"] == 0, "在线时不应触发登录"

        # 以当前成功登录数为基线（login-history 可能跨测试累积，需用增量判断）
        base_success = _login_success_count(client)

        # 2) 模拟拔网：门户 /success 不再返回 Success
        state.online = False

        # 3) 监控应检测到断网并自动触发登录（login_attempt_count 来自本测试全新的 monitor core）
        _wait_for(
            lambda: _status(client)["login_attempt_count"] >= 1,
            timeout=60,
            interval=1.0,
        )
        status = _status(client)
        assert (
            status["network_state"] == "disconnected"
        ), f"断网后 network_state 应为 disconnected，实际: {status['network_state']}"

        # 4) 登录应真实成功并写入历史（相对基线新增至少一条成功记录）
        _wait_for(
            lambda: _login_success_count(client) >= base_success + 1,
            timeout=60,
            interval=1.0,
        )

        # 5) 恢复网络 → 监控应重新判定「已连接」，且不再重复触发登录
        state.online = True
        _wait_for(lambda: _status(client)["network_state"] == "connected", timeout=25)

        # 恢复后等待超过一个检测周期（check_interval=10s），确认 login_attempt_count 不再增长
        count_after_recover = _status(client)["login_attempt_count"]
        time.sleep(15)
        assert (
            _status(client)["login_attempt_count"] == count_after_recover
        ), "恢复连接后监控不应再重复触发登录"

        # 收尾
        client.post("/api/monitor/stop")
