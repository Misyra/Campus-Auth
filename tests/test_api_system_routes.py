"""系统管理路由 API 测试 — 覆盖健康检查、更新检测、自启动、OCR、卸载等端点。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.schemas import MonitorConfigPayload


@pytest.fixture
def client(tmp_path):
    """创建测试客户端，mock 所有服务依赖。"""
    (tmp_path / "frontend").mkdir(exist_ok=True)
    (tmp_path / "frontend" / "index.html").write_text("<html></html>")
    (tmp_path / "logs").mkdir(exist_ok=True)
    (tmp_path / "temp").mkdir(exist_ok=True)

    with (
        patch("app.constants.PROJECT_ROOT", tmp_path),
        patch("app.constants.FRONTEND_DIR", tmp_path / "frontend"),
        patch("app.constants.LOGS_DIR", tmp_path / "logs"),
        patch("app.constants.TEMP_DIR", tmp_path / "temp"),
    ):
        from app.application import app

        mock_services = MagicMock()

        # monitor_service
        mock_services.monitor_service.get_config.return_value = MonitorConfigPayload(
            username="testuser", password="••••••••", auth_url="http://10.0.0.1"
        )
        mock_services.monitor_service.get_runtime_config.return_value = {
            "monitor": {"script_timeout": 60}
        }

        # autostart_service
        mock_services.autostart_service.status.return_value = {
            "platform": "windows",
            "enabled": False,
            "method": "vbs",
            "location": "",
        }
        mock_services.autostart_service.enable.return_value = (True, "已启用")
        mock_services.autostart_service.disable.return_value = (True, "已禁用")

        app.state.services = mock_services

        test_client = TestClient(app)
        yield test_client, mock_services, tmp_path


# ── 健康检查 ──


class TestHealth:
    """GET /api/health"""

    def test_health_returns_ok(self, client):
        """健康检查返回 ok 状态。"""
        test_client, _, _ = client
        resp = test_client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "version" in data
        assert "python_version" in data


# ── 初始化状态 ──


class TestInitStatus:
    """GET /api/init-status"""

    def test_initialized(self, client):
        """已初始化时返回 True。"""
        test_client, mock_services, _ = client
        mock_services.monitor_service.get_config.return_value = MonitorConfigPayload(
            username="testuser", password="secret", auth_url="http://10.0.0.1"
        )
        with patch("app.utils.crypto.has_decryption_error", return_value=False):
            resp = test_client.get("/api/init-status")
        assert resp.status_code == 200
        assert resp.json()["initialized"] is True
        assert resp.json()["password_decryption_failed"] is False

    def test_not_initialized(self, client):
        """未初始化时返回 False。"""
        test_client, mock_services, _ = client
        mock_services.monitor_service.get_config.return_value = MonitorConfigPayload(
            username="", password="", auth_url=""
        )
        with patch("app.utils.crypto.has_decryption_error", return_value=False):
            resp = test_client.get("/api/init-status")
        assert resp.status_code == 200
        assert resp.json()["initialized"] is False


# ── Shell 列表 ──


class TestShells:
    """GET /api/shells"""

    @patch("app.api.system.detect_available_shells")
    @patch("app.api.system.get_default_shell")
    def test_list_shells(self, mock_default, mock_detect, client):
        """返回可用 Shell 列表。"""
        mock_detect.return_value = [
            {"name": "cmd", "path": "cmd.exe", "description": "CMD"},
        ]
        mock_default.return_value = "cmd.exe"
        test_client, _, _ = client
        resp = test_client.get("/api/shells")
        assert resp.status_code == 200
        data = resp.json()
        assert "shells" in data
        assert "default" in data
        assert len(data["shells"]) >= 1


# ── 自启动管理 ──


class TestAutoStart:
    """自启动相关端点。"""

    def test_get_status(self, client):
        """GET /api/autostart/status"""
        test_client, mock_services, _ = client
        mock_services.autostart_service.status.return_value = {
            "platform": "windows",
            "enabled": True,
            "method": "vbs",
            "location": "C:\\Users\\test\\AppData\\Roaming\\Microsoft\\Windows\\Start Menu\\Programs\\Startup\\campus-auth.vbs",
        }
        resp = test_client.get("/api/autostart/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["platform"] == "windows"
        assert data["enabled"] is True

    def test_enable_autostart(self, client):
        """POST /api/autostart/enable"""
        test_client, mock_services, _ = client
        mock_services.autostart_service.enable.return_value = (True, "已启用自启动")
        resp = test_client.post("/api/autostart/enable")
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_disable_autostart(self, client):
        """POST /api/autostart/disable"""
        test_client, mock_services, _ = client
        mock_services.autostart_service.disable.return_value = (True, "已禁用自启动")
        resp = test_client.post("/api/autostart/disable")
        assert resp.status_code == 200
        assert resp.json()["success"] is True


# ── OCR 管理 ──


class TestOCR:
    """OCR 相关端点。"""

    @patch("app.api.system._check_ddddocr_installed")
    def test_ocr_status_not_installed(self, mock_check, client):
        """ddddocr 未安装时返回状态。"""
        mock_check.return_value = False
        test_client, _, _ = client
        resp = test_client.get("/api/ocr/status")
        assert resp.status_code == 200
        assert resp.json()["installed"] is False
        assert resp.json()["size_mb"] == 0.0

    @patch("app.api.system._check_ddddocr_installed")
    @patch("app.api.system._estimate_pkg_size_mb")
    def test_ocr_status_installed(self, mock_size, mock_check, client):
        """ddddocr 已安装时返回大小。"""
        mock_check.return_value = True
        mock_size.return_value = 50.0
        test_client, _, _ = client
        resp = test_client.get("/api/ocr/status")
        assert resp.status_code == 200
        assert resp.json()["installed"] is True
        assert resp.json()["size_mb"] > 0

    @patch("app.api.system._check_ddddocr_installed")
    def test_ocr_install_already_installed(self, mock_check, client):
        """已安装时直接返回成功。"""
        mock_check.return_value = True
        test_client, _, _ = client
        resp = test_client.post("/api/ocr/install")
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    @patch("app.api.system._check_ddddocr_installed")
    def test_ocr_uninstall_not_installed(self, mock_check, client):
        """未安装时直接返回成功。"""
        mock_check.return_value = False
        test_client, _, _ = client
        resp = test_client.post("/api/ocr/uninstall")
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    @patch("app.api.system._check_ddddocr_installed")
    @patch("subprocess.run")
    def test_ocr_install_success(self, mock_run, mock_check, client):
        """安装 ddddocr 成功。"""
        mock_check.return_value = False
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        test_client, _, _ = client
        resp = test_client.post("/api/ocr/install")
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    @patch("app.api.system._check_ddddocr_installed")
    @patch("subprocess.run")
    def test_ocr_install_failure(self, mock_run, mock_check, client):
        """安装 ddddocr 失败。"""
        mock_check.return_value = False
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="安装错误")
        test_client, _, _ = client
        resp = test_client.post("/api/ocr/install")
        assert resp.status_code == 200
        assert resp.json()["success"] is False
        assert "失败" in resp.json()["message"]

    @patch("app.api.system._check_ddddocr_installed")
    @patch("subprocess.run")
    def test_ocr_install_timeout(self, mock_run, mock_check, client):
        """安装超时。"""
        import subprocess

        mock_check.return_value = False
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="uv", timeout=300)
        test_client, _, _ = client
        resp = test_client.post("/api/ocr/install")
        assert resp.status_code == 200
        assert resp.json()["success"] is False
        assert "超时" in resp.json()["message"]

    @patch("app.api.system._check_ddddocr_installed")
    @patch("subprocess.run")
    def test_ocr_uninstall_success(self, mock_run, mock_check, client):
        """卸载 ddddocr 成功。"""
        mock_check.return_value = True
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        test_client, _, _ = client
        resp = test_client.post("/api/ocr/uninstall")
        assert resp.status_code == 200
        assert resp.json()["success"] is True


# ── 关机 ──


class TestShutdown:
    """POST /api/shutdown"""

    def test_shutdown_returns_success(self, client):
        """关机请求返回成功。"""
        test_client, mock_services, _ = client
        # 设置 shutdown_event mock

        mock_event = MagicMock()
        app_ref = test_client.app
        app_ref.state.shutdown_event = mock_event

        resp = test_client.post("/api/shutdown")
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        assert "关闭" in resp.json()["message"]
        mock_event.set.assert_called_once()


# ── 卸载 ──


class TestUninstall:
    """卸载相关端点。"""

    @patch("app.services.uninstall.detect")
    def test_uninstall_detect(self, mock_detect, client):
        """GET /api/uninstall/detect"""
        from app.services.uninstall import CleanupItem

        mock_detect.return_value = [
            CleanupItem("autostart", "开机自启", True, "C:\\startup.vbs"),
            CleanupItem("userdata", "用户数据", False),
        ]
        test_client, _, _ = client
        resp = test_client.get("/api/uninstall/detect")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        assert data[0]["key"] == "autostart"
        assert data[0]["exists"] is True

    @patch("app.services.uninstall.perform")
    def test_uninstall_perform(self, mock_perform, client):
        """POST /api/uninstall"""
        from app.services.uninstall import CleanupResult

        mock_perform.return_value = [
            CleanupResult("userdata", "删除用户数据", True, "已删除"),
        ]
        test_client, _, _ = client
        resp = test_client.post("/api/uninstall", json={"keys": ["userdata"]})
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_uninstall_perform_invalid_keys(self, client):
        """keys 不是列表返回 400。"""
        test_client, _, _ = client
        resp = test_client.post("/api/uninstall", json={"keys": "not_a_list"})
        assert resp.status_code == 400


# ── 更新检测 ──


class TestCheckUpdate:
    """GET /api/check-update"""

    @patch("httpx.AsyncClient.get")
    def test_check_update_success(self, mock_get, client):
        """更新检测成功。"""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "tag_name": "v99.0.0",
            "html_url": "https://example.com/release",
            "body": "新版本",
            "published_at": "2026-01-01T00:00:00Z",
        }
        mock_resp.headers = {}
        mock_get.return_value = mock_resp

        test_client, _, _ = client
        resp = test_client.get("/api/check-update")
        assert resp.status_code == 200
        data = resp.json()
        assert "current" in data
        assert "latest" in data

    @patch("httpx.AsyncClient.get", side_effect=Exception("网络错误"))
    def test_check_update_network_error(self, mock_get, client):
        """网络错误时返回错误信息。"""
        test_client, _, _ = client
        resp = test_client.get("/api/check-update")
        assert resp.status_code == 200
        data = resp.json()
        assert data["has_update"] is False
        assert "error" in data
