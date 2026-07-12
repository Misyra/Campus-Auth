"""系统管理路由 API 测试 — 覆盖健康检查、更新检测、自启动、OCR、卸载等端点。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.schemas import LoginCredentials, RuntimeConfig

# ── 健康检查 ──


class TestHealth:
    """GET /api/health"""

    def test_health_returns_ok(self, api_client):
        """健康检查返回 ok 状态。"""
        test_client, _ = api_client
        resp = test_client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "version" in data
        assert "python_version" in data


# ── 初始化状态 ──


class TestInitStatus:
    """GET /api/init-status"""

    def test_initialized(self, api_client):
        """已初始化时返回 True。"""
        test_client, mock_services = api_client
        mock_services.engine.get_runtime_config.return_value = RuntimeConfig(
            credentials=LoginCredentials(username="test", password="test"),
        )
        with patch("app.utils.crypto.has_decryption_error", return_value=False):
            resp = test_client.get("/api/init-status")
        assert resp.status_code == 200
        assert resp.json()["initialized"] is True
        assert resp.json()["password_decryption_failed"] is False

    def test_not_initialized(self, api_client):
        """未初始化时返回 False。"""
        test_client, mock_services = api_client
        mock_services.engine.get_runtime_config.return_value = RuntimeConfig()
        with patch("app.utils.crypto.has_decryption_error", return_value=False):
            resp = test_client.get("/api/init-status")
        assert resp.status_code == 200
        assert resp.json()["initialized"] is False



# ── 自启动管理 ──


class TestAutoStart:
    """自启动相关端点。"""

    def test_get_status(self, api_client):
        """GET /api/autostart/status"""
        test_client, mock_services = api_client
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

    def test_enable_autostart(self, api_client):
        """POST /api/autostart/enable"""
        test_client, mock_services = api_client
        mock_services.autostart_service.enable.return_value = (True, "已启用自启动")
        resp = test_client.post("/api/autostart/enable")
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_disable_autostart(self, api_client):
        """POST /api/autostart/disable"""
        test_client, mock_services = api_client
        mock_services.autostart_service.disable.return_value = (True, "已禁用自启动")
        resp = test_client.post("/api/autostart/disable")
        assert resp.status_code == 200
        assert resp.json()["success"] is True


# ── OCR 管理 ──


class TestOCR:
    """OCR 相关端点。"""

    @patch("app.api.ocr._check_ddddocr_installed")
    def test_ocr_status_not_installed(self, mock_check, api_client):
        """ddddocr 未安装时返回状态。"""
        mock_check.return_value = False
        test_client, _ = api_client
        resp = test_client.get("/api/ocr/status")
        assert resp.status_code == 200
        assert resp.json()["installed"] is False
        assert resp.json()["size_mb"] == 0.0

    @patch("app.api.ocr._check_ddddocr_installed")
    @patch("app.api.ocr._estimate_pkg_size_mb")
    def test_ocr_status_installed(self, mock_size, mock_check, api_client):
        """ddddocr 已安装时返回大小。"""
        mock_check.return_value = True
        mock_size.return_value = 50.0
        test_client, _ = api_client
        resp = test_client.get("/api/ocr/status")
        assert resp.status_code == 200
        assert resp.json()["installed"] is True
        assert resp.json()["size_mb"] > 0

    @patch("app.api.ocr._check_ddddocr_installed")
    def test_ocr_install_already_installed(self, mock_check, api_client):
        """已安装时直接返回成功。"""
        mock_check.return_value = True
        test_client, _ = api_client
        resp = test_client.post("/api/ocr/install")
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    @patch("app.api.ocr._check_ddddocr_installed")
    def test_ocr_uninstall_not_installed(self, mock_check, api_client):
        """未安装时直接返回成功。"""
        mock_check.return_value = False
        test_client, _ = api_client
        resp = test_client.post("/api/ocr/uninstall")
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    @patch("app.api.ocr._check_ddddocr_installed")
    @patch("subprocess.run")
    def test_ocr_install_success(self, mock_run, mock_check, api_client):
        """安装 ddddocr 成功。"""
        mock_check.return_value = False
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        test_client, _ = api_client
        resp = test_client.post("/api/ocr/install")
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    @patch("app.api.ocr._check_ddddocr_installed")
    @patch("subprocess.run")
    def test_ocr_install_failure(self, mock_run, mock_check, api_client):
        """安装 ddddocr 失败。"""
        mock_check.return_value = False
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="安装错误")
        test_client, _ = api_client
        resp = test_client.post("/api/ocr/install")
        assert resp.status_code == 200
        assert resp.json()["success"] is False
        assert "失败" in resp.json()["message"]

    @patch("app.api.ocr._check_ddddocr_installed")
    @patch("subprocess.run")
    def test_ocr_install_timeout(self, mock_run, mock_check, api_client):
        """安装超时。"""
        import subprocess

        mock_check.return_value = False
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="uv", timeout=300)
        test_client, _ = api_client
        resp = test_client.post("/api/ocr/install")
        assert resp.status_code == 200
        assert resp.json()["success"] is False
        assert "超时" in resp.json()["message"]

    @patch("app.api.ocr._check_ddddocr_installed")
    @patch("subprocess.run")
    def test_ocr_uninstall_success(self, mock_run, mock_check, api_client):
        """卸载 ddddocr 成功。"""
        mock_check.return_value = True
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        test_client, _ = api_client
        resp = test_client.post("/api/ocr/uninstall")
        assert resp.status_code == 200
        assert resp.json()["success"] is True


# ── 关机 ──


class TestShutdown:
    """POST /api/shutdown"""

    def test_shutdown_returns_success(self, api_client):
        """关机请求返回成功。"""
        test_client, mock_services = api_client
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
    def test_uninstall_detect(self, mock_detect, api_client):
        """GET /api/uninstall/detect"""
        from app.services.uninstall import CleanupItem

        mock_detect.return_value = [
            CleanupItem("autostart", "开机自启", True, "C:\\startup.vbs"),
            CleanupItem("userdata", "用户数据", False),
        ]
        test_client, _ = api_client
        resp = test_client.get("/api/uninstall/detect")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        assert data[0]["key"] == "autostart"
        assert data[0]["exists"] is True

    @patch("app.services.uninstall.perform")
    def test_uninstall_perform(self, mock_perform, api_client):
        """POST /api/uninstall"""
        from app.services.uninstall import CleanupResult

        mock_perform.return_value = [
            CleanupResult("userdata", "删除用户数据", True, "已删除"),
        ]
        test_client, _ = api_client
        resp = test_client.post("/api/uninstall", json={"keys": ["userdata"]})
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_uninstall_perform_invalid_keys(self, api_client):
        """keys 不是列表返回 422（Pydantic 验证失败）。"""
        test_client, _ = api_client
        resp = test_client.post("/api/uninstall", json={"keys": "not_a_list"})
        assert resp.status_code == 422


# ── 更新检测 ──


class TestCheckUpdate:
    """GET /api/check-update"""

    @patch("httpx.AsyncClient.get")
    def test_check_update_success(self, mock_get, api_client):
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

        test_client, _ = api_client
        resp = test_client.get("/api/check-update")
        assert resp.status_code == 200
        data = resp.json()
        assert "current" in data
        assert "latest" in data

    @patch("httpx.AsyncClient.get", side_effect=Exception("网络错误"))
    def test_check_update_network_error(self, mock_get, api_client):
        """网络错误时返回错误信息。"""
        # 清除缓存，确保测试独立
        import app.api.system as sys_mod

        sys_mod._update_cache = None
        sys_mod._update_cache_time = 0

        test_client, _ = api_client
        resp = test_client.get("/api/check-update")
        assert resp.status_code == 200
        data = resp.json()
        assert data["has_update"] is False
        assert "error" in data
