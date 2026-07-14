"""E2E 基础 fixture 烟雾测试 — 验证 real_app / http_portal / real_browser fixture 可用。"""

from __future__ import annotations

import json
import urllib.request


class TestRealAppFixture:
    """验证 real_app fixture 真实启动了应用与服务。"""

    def test_app_root_responds(self, real_app):
        """应用根路径返回 HTML。"""
        client, _ = real_app
        resp = client.get("/")
        assert resp.status_code == 200

    def test_status_endpoint_real_engine(self, real_app):
        """/api/status 返回真实引擎状态（非 mock）。"""
        client, app = real_app
        # 验证 services 真实挂载
        assert app.state.services is not None
        assert hasattr(app.state.services, "engine")
        # 引擎线程应已启动
        assert app.state.services.engine._engine_thread is not None

        resp = client.get("/api/status")
        assert resp.status_code == 200
        data = resp.json()
        # 真实引擎字段（MonitorStatusResponse schema）
        assert "monitoring" in data
        assert "network_check_count" in data
        assert "login_attempt_count" in data
        # E2E fixture 不自动启动监控
        assert data["monitoring"] is False

    def test_config_endpoint_real_config(self, real_app, e2e_project):
        """/api/config 返回真实持久化的配置。"""
        client, _ = real_app
        resp = client.get("/api/config")
        assert resp.status_code == 200
        cfg = resp.json()
        # ConfigResponse 扁平字段
        assert cfg["username"] == "e2e_user"
        assert cfg["auth_url"] == "http://127.0.0.1:1/"
        # carrier="无" 在 API 中被解释为"无运营商"，返回空 isp
        assert cfg["isp"] in ("", "无")

    def test_settings_json_persisted(self, e2e_project):
        """配置文件确实落盘。"""
        settings_file = e2e_project / "config" / "settings.json"
        assert settings_file.exists()
        data = json.loads(settings_file.read_text(encoding="utf-8"))
        assert data["profiles"]["default"]["username"] == "e2e_user"


class TestHttpPortalFixture:
    """验证 http_portal fixture 可响应。"""

    def test_root_returns_login_form(self, http_portal):
        host, port, base = http_portal
        with urllib.request.urlopen(f"{base}/") as resp:
            body = resp.read().decode("utf-8")
        assert "loginForm" in body
        assert "username" in body

    def test_success_path(self, http_portal):
        host, port, base = http_portal
        with urllib.request.urlopen(f"{base}/success") as resp:
            body = resp.read().decode("utf-8")
        assert "Success" in body

    def test_generate_204(self, http_portal):
        host, port, base = http_portal
        with urllib.request.urlopen(f"{base}/generate_204") as resp:
            assert resp.status == 204

    def test_login_correct_credentials(self, http_portal):
        """正确账号密码登录成功。"""
        host, port, base = http_portal
        data = b"username=e2e_user&password=e2e_pass"
        req = urllib.request.Request(
            f"{base}/login", data=data, method="POST"
        )
        with urllib.request.urlopen(req) as resp:
            body = resp.read().decode("utf-8")
        assert "登录成功" in body

    def test_login_wrong_credentials(self, http_portal):
        """错误账号密码登录失败。"""
        host, port, base = http_portal
        data = b"username=bad&password=bad"
        req = urllib.request.Request(
            f"{base}/login", data=data, method="POST"
        )
        with urllib.request.urlopen(req) as resp:
            body = resp.read().decode("utf-8")
        assert "登录失败" in body


class TestRealBrowserFixture:
    """验证 real_browser fixture 可启动真实 Chromium。"""

    def test_browser_launches(self, real_browser):
        """Chromium 能正常启动。"""
        page = real_browser.new_page()
        page.set_content("<html><body><h1>hello</h1></body></html>")
        assert page.evaluate("() => document.querySelector('h1').textContent") == "hello"
        page.close()

    def test_browser_navigates_to_portal(self, real_browser, http_portal):
        """Chromium 能访问本地门户。"""
        host, port, base = http_portal
        page = real_browser.new_page()
        page.goto(base)
        assert page.title() == "校园网认证"
        # 填表并提交
        page.fill("#username", "e2e_user")
        page.fill("#password", "e2e_pass")
        page.click("#loginBtn")
        page.wait_for_load_state("networkidle")
        assert "登录成功" in page.content()
        page.close()
