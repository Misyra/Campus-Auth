"""脚本路由 API 测试 — 覆盖脚本 CRUD 和执行等端点。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


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
        app.state.services = mock_services

        test_client = TestClient(app)
        yield test_client, mock_services, tmp_path


# ── 列出脚本 ──


class TestListScripts:
    """GET /api/scripts"""

    def test_list_empty(self, client):
        """无脚本时返回空列表。"""
        test_client, mock_services, _ = client
        mock_services.task_service.list_scripts.return_value = []
        resp = test_client.get("/api/scripts")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_with_scripts(self, client):
        """有脚本时返回列表。"""
        test_client, mock_services, _ = client
        mock_services.task_service.list_scripts.return_value = [
            {"id": "script1", "name": "脚本1", "type": "script"},
            {"id": "script2", "name": "脚本2", "type": "script"},
        ]
        resp = test_client.get("/api/scripts")
        assert resp.status_code == 200
        assert len(resp.json()) == 2


# ── 获取脚本详情 ──


class TestGetScript:
    """GET /api/scripts/{task_id}"""

    def test_get_existing_script(self, client):
        """获取存在的脚本任务。"""
        test_client, mock_services, _ = client
        mock_services.task_service.get_task.return_value = {
            "id": "script1",
            "name": "测试脚本",
            "type": "script",
            "content": "echo hello",
        }
        resp = test_client.get("/api/scripts/script1")
        assert resp.status_code == 200
        assert resp.json()["name"] == "测试脚本"

    def test_get_nonexistent_script(self, client):
        """获取不存在的脚本返回 404。"""
        test_client, mock_services, _ = client
        mock_services.task_service.get_task.return_value = None
        resp = test_client.get("/api/scripts/nonexistent")
        assert resp.status_code == 404

    def test_get_browser_task_as_script(self, client):
        """浏览器任务类型不是 script 返回 404。"""
        test_client, mock_services, _ = client
        mock_services.task_service.get_task.return_value = {
            "id": "task1",
            "name": "浏览器任务",
            "type": "browser",
        }
        resp = test_client.get("/api/scripts/task1")
        assert resp.status_code == 404


# ── 保存脚本 ──


class TestSaveScript:
    """PUT /api/scripts/{task_id}"""

    def test_save_script_success(self, client):
        """保存脚本成功。"""
        test_client, mock_services, _ = client
        mock_services.task_service.save_task.return_value = (True, "保存成功")
        resp = test_client.put(
            "/api/scripts/new_script",
            json={"name": "新脚本", "content": "echo test", "type": "script"},
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_save_script_failure(self, client):
        """保存脚本失败。"""
        test_client, mock_services, _ = client
        mock_services.task_service.save_task.return_value = (False, "保存失败")
        resp = test_client.put(
            "/api/scripts/bad_script",
            json={"name": "坏脚本"},
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is False


# ── 删除脚本 ──


class TestDeleteScript:
    """DELETE /api/scripts/{task_id}"""

    def test_delete_existing_script(self, client):
        """删除存在的脚本。"""
        test_client, mock_services, _ = client
        mock_services.task_service.delete_task.return_value = (True, "删除成功")
        resp = test_client.delete("/api/scripts/script1")
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_delete_nonexistent_script(self, client):
        """删除不存在的脚本。"""
        test_client, mock_services, _ = client
        mock_services.task_service.delete_task.return_value = (False, "脚本不存在")
        resp = test_client.delete("/api/scripts/nonexistent")
        assert resp.status_code == 200
        assert resp.json()["success"] is False


# ── 运行脚本 ──


class TestRunScript:
    """POST /api/scripts/{task_id}/run"""

    def test_run_script_success(self, client):
        """运行存在的脚本成功。"""
        test_client, mock_services, tmp_path = client
        script_file = tmp_path / "test_script.sh"
        script_file.write_text("echo hello", encoding="utf-8")

        mock_services.task_service.get_task.return_value = {
            "id": "script1",
            "name": "测试",
            "type": "script",
            "binary_path": "",
        }
        mock_services.task_service.get_script_path.return_value = script_file

        with patch("app.api.scripts.ScriptRunner") as MockRunner:
            mock_runner = MagicMock()
            mock_runner.run.return_value = (True, "执行成功")
            MockRunner.return_value = mock_runner

            resp = test_client.post("/api/scripts/script1/run")

        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_run_script_not_found(self, client):
        """运行不存在的脚本返回 404。"""
        test_client, mock_services, _ = client
        mock_services.task_service.get_task.return_value = None
        resp = test_client.post("/api/scripts/nonexistent/run")
        assert resp.status_code == 404

    def test_run_script_file_missing(self, client):
        """脚本文件不存在时返回失败。"""
        test_client, mock_services, _ = client
        mock_services.task_service.get_task.return_value = {
            "id": "script1",
            "name": "测试",
            "type": "script",
        }
        mock_services.task_service.get_script_path.return_value = None
        resp = test_client.post("/api/scripts/script1/run")
        assert resp.status_code == 200
        assert resp.json()["success"] is False


# ── 获取可用二进制列表 ──


class TestListBinaries:
    """GET /api/scripts/binaries"""

    @patch("app.api.scripts.detect_available_binaries")
    def test_list_binaries(self, mock_detect, client):
        """返回可用二进制列表。"""
        mock_detect.return_value = [
            {"name": "Python", "path": "/usr/bin/python3", "description": "Python"},
            {"name": "bash", "path": "/bin/bash", "description": "Bash"},
        ]
        test_client, _, _ = client
        resp = test_client.get("/api/scripts/binaries")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)
