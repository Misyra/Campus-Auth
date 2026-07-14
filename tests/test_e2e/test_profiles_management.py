"""配置方案（profiles）管理 + 手动立即登录（actions/login）端到端测试。

补足此前 e2e 薄弱的两个 API 面：
- profiles 的创建/读取/更新/删除/激活/auto-switch/detect（纯 API，无浏览器依赖）；
- /api/actions/login 手动立即登录（触发真实 Worker 登录，依赖 Chromium）。

需要 Chromium 已安装（仅 actions/login 用例会检查，未安装则跳过该用例）。
"""

from __future__ import annotations

import os
import socket
import threading
import time

import pytest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


# ── 可控门户（供 actions/login 用例复用，模拟可登录的认证门户）──


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
    """可控认证门户（仅 actions/login 用例使用）。

    - /                或 /?...   → 登录表单
    - POST /login                → 校验凭据，返回成功/失败页
    - /success                   → 连通性探测端点：返回含 Success 的 200
       （本用例门户始终在线，供 monitor 判定已连接、避免自动登录干扰手动登录）
    """

    state: _PortalState

    def log_message(self, fmt, *args):  # 静默日志
        pass

    def do_GET(self):
        if self.path == "/success":
            self._html("<html><body>Success</body></html>")
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
    """启动可控门户，返回 (_PortalState, base_url)。

    仅在用例真正使用时检查 Chromium —— 因此不依赖浏览器的 profiles 测试
    不会因缺少 Chromium 而被跳过。
    """
    from playwright.sync_api import sync_playwright

    try:
        pw = sync_playwright().start()
        pw.chromium.launch(headless=True).close()
        pw.stop()
    except Exception as e:
        if "Executable doesn't exist" in str(e) or "playwright install" in str(e):
            pytest.skip(f"Chromium 未安装: {e}")

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


# ── 辅助函数（供 actions/login 用例）──


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
    """创建浏览器任务定义，指向可控门户登录表单（步骤与 test_browser_task 一致）。"""
    payload = {
        "name": f"E2E 手动登录任务 {task_id}",
        "description": "E2E 手动登录测试",
        "url": portal_url + "/",
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


# ── 测试：profiles 管理（纯 API，无浏览器依赖）──


class TestProfilesCRUD:
    """配置方案 CRUD / 激活 / auto-switch / detect 端到端覆盖。"""

    def test_put_creates_profile_and_lists(self, real_app):
        """PUT 创建方案后 GET /api/profiles 能列出该方案。"""
        client, _ = real_app
        pid = "lab_wifi"
        payload = {
            "name": "实验室WiFi",
            "username": "u1",
            "password": "p1",
            "auth_url": "https://example.com/login",
            "active_task": "t1",
        }
        resp = client.put(f"/api/profiles/{pid}", json=payload)
        assert resp.status_code == 200, resp.text
        assert resp.json()["success"] is True

        listing = client.get("/api/profiles").json()
        assert pid in listing["profiles"]
        assert listing["profiles"][pid]["name"] == "实验室WiFi"
        assert listing["profiles"][pid]["auth_url"] == "https://example.com/login"

    def test_get_profile_detail_and_masked_password(self, real_app):
        """GET 单个方案返回详情，且密码字段被掩码（不泄露明文/密文）。"""
        client, _ = real_app
        pid = "lab_detail"
        client.put(f"/api/profiles/{pid}", json={"name": "N2", "password": "secret"})
        detail = client.get(f"/api/profiles/{pid}").json()
        assert detail["profile_id"] == pid
        assert detail["settings"]["name"] == "N2"
        assert detail["settings"]["password"] == ""

    def test_get_missing_profile_returns_404(self, real_app):
        """GET 不存在的方案返回 404。"""
        client, _ = real_app
        resp = client.get("/api/profiles/does_not_exist")
        assert resp.status_code == 404

    def test_update_existing_profile(self, real_app):
        """PUT 已存在方案应更新而非新建，字段被覆盖。"""
        client, _ = real_app
        pid = "lab_update"
        client.put(f"/api/profiles/{pid}", json={"name": "Old", "auth_url": "https://old/x"})
        resp = client.put(
            f"/api/profiles/{pid}", json={"name": "New", "auth_url": "https://new/y"}
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        detail = client.get(f"/api/profiles/{pid}").json()
        assert detail["settings"]["name"] == "New"
        assert detail["settings"]["auth_url"] == "https://new/y"

    def test_set_active_profile(self, real_app):
        """POST /api/profiles/active/{id} 切换活动方案。"""
        client, _ = real_app
        client.put("/api/profiles/alpha", json={"name": "Alpha"})
        client.put("/api/profiles/beta", json={"name": "Beta"})
        resp = client.post("/api/profiles/active/beta")
        assert resp.status_code == 200, resp.text
        assert resp.json()["success"] is True
        listing = client.get("/api/profiles").json()
        assert listing["active_profile"] == "beta"

    def test_auto_switch_toggle(self, real_app):
        """auto-switch 开关可开启/关闭并持久化到列表响应。"""
        client, _ = real_app
        # 默认应关闭
        assert client.get("/api/profiles").json()["auto_switch"] is False

        resp = client.post("/api/profiles/auto-switch", json={"enabled": True})
        assert resp.status_code == 200, resp.text
        assert resp.json()["success"] is True
        assert client.get("/api/profiles").json()["auto_switch"] is True

        resp2 = client.post("/api/profiles/auto-switch", json={"enabled": False})
        assert resp2.status_code == 200
        assert resp2.json()["success"] is True
        assert client.get("/api/profiles").json()["auto_switch"] is False

    def test_delete_profile(self, real_app):
        """删除非默认方案成功；删除默认方案被拒绝。"""
        client, _ = real_app
        # 准备至少两个方案，确保删除后仍有剩余
        listing = client.get("/api/profiles").json()
        ids = set(listing["profiles"].keys())
        if "alpha" not in ids:
            client.put("/api/profiles/alpha", json={"name": "Alpha"})
        if "beta" not in ids:
            client.put("/api/profiles/beta", json={"name": "Beta"})

        # 删除非 default 方案应成功
        resp = client.delete("/api/profiles/beta")
        assert resp.status_code == 200, resp.text
        assert resp.json()["success"] is True
        assert "beta" not in client.get("/api/profiles").json()["profiles"]

        # 删除 default 应被拒绝（success=False，HTTP 仍为 200）
        resp2 = client.delete("/api/profiles/default")
        assert resp2.status_code == 200
        assert resp2.json()["success"] is False
        # default 仍存在
        assert "default" in client.get("/api/profiles").json()["profiles"]

    def test_delete_last_remaining_profile_fails(self, real_app):
        """仅剩一个方案时删除应失败（至少保留一个方案约束）。"""
        client, _ = real_app
        # 删光所有非 default 方案，仅保留 default
        listing = client.get("/api/profiles").json()
        for pid in list(listing["profiles"].keys()):
            if pid != "default":
                client.delete(f"/api/profiles/{pid}")
        resp = client.delete("/api/profiles/default")
        assert resp.status_code == 200
        assert resp.json()["success"] is False

    def test_detect_network_profile_returns_200(self, real_app):
        """detect 接口在本机应正常返回 200（gateway/ssid 可能为空，matched 可能为 None）。"""
        client, _ = real_app
        resp = client.post("/api/profiles/detect")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert "gateway_ip" in body
        assert "ssid" in body
        assert "matched_profile_id" in body
        assert "matched_profile_name" in body


# ── 测试：手动立即登录（actions/login）──


class TestManualLogin:
    """POST /api/actions/login 触发真实 Worker 登录（与监控自动触发互补）。"""

    @pytest.mark.slow
    def test_actions_login_triggers_real_login(
        self, real_app, e2e_project, controllable_portal, monkeypatch
    ):
        client, _ = real_app
        tmp_path = e2e_project
        _, portal_base = controllable_portal

        # 让 Worker 的 TaskManager 从 tmp_path 读取任务（与 API 写入位置一致）
        monkeypatch.setenv("CAMPUS_AUTH_PROJECT_ROOT", str(tmp_path))
        _ensure_probes_active()

        task_id = "e2e_manual_login_task"
        _save_browser_task(client, task_id, portal_base)

        # 配置：auth_url 指向门户；active_task 指向登录任务；
        # 监控仅做 URL 连通性检测且门户始终在线 —— 确保 monitor 判定「已连接」、
        # 不会自动触发登录，从而本用例观察到的登录 100% 来自手动 actions/login。
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

        # 启动监控（仅用于确保 engine/worker 处于活跃态，门户在线不触发自动登录）
        r = client.post("/api/monitor/start")
        assert r.status_code == 200 and r.json()["success"] is True
        _wait_for(lambda: _status(client)["monitoring"] is True, timeout=10)
        # 在线阶段不应触发任何登录
        assert _status(client)["login_attempt_count"] == 0, "在线时不应触发自动登录"

        # 以当前登录尝试数为基线（监控在线不触发自动登录，应为 0）
        base_attempt = _status(client)["login_attempt_count"]

        # 手动立即登录（阻塞，等待 Worker 真实执行完）
        resp = client.post("/api/actions/login")
        assert resp.status_code == 200, resp.text
        assert resp.json()["success"] is True, f"手动登录未成功: {resp.text}"

        # 手动登录应触发登录编排（login_attempt_count 递增），且真实浏览器登录成功
        _wait_for(
            lambda: _status(client)["login_attempt_count"] >= base_attempt + 1,
            timeout=30,
            interval=1.0,
        )

        client.post("/api/monitor/stop")
