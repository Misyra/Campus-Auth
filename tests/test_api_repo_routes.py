"""仓库代理路由 API 测试 — 覆盖远程任务仓库索引和任务配置获取端点。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.schemas import (
    MonitorConfigPayload,
    MonitorStatusResponse,
    ProfilesData,
    ProfileSettings,
    SystemSettings,
)


@pytest.fixture
def client(tmp_path):
    """创建隔离的测试客户端。"""
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
        mock_services.engine.get_config.return_value = MonitorConfigPayload(
            username="testuser", password="••••••••", auth_url="http://10.0.0.1"
        )
        mock_services.engine.get_status.return_value = MonitorStatusResponse(
            monitoring=False,
            network_check_count=0,
            login_attempt_count=0,
            last_check_time=None,
            runtime_seconds=0,
        )
        mock_services.engine.list_logs.return_value = []

        # profile_service
        profile_data = ProfilesData(
            system=SystemSettings(username="testuser", password="ENC:test"),
            profiles={"default": ProfileSettings(name="默认方案")},
        )
        mock_services.profile_service.load.return_value = profile_data

        app.state.services = mock_services

        test_client = TestClient(app)
        yield test_client, mock_services


class TestRepoFetchIndex:
    """测试 GET /api/repo/fetch 端点。"""

    @patch("app.api.repo.repo_fetch_json")
    def test_repo_fetch_index_success(self, mock_fetch, client):
        test_client, _ = client
        mock_fetch.return_value = [{"id": "task1", "name": "任务1"}]
        resp = test_client.get("/api/repo/fetch?url=https://example.com/index.json")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert data[0]["id"] == "task1"

    @patch("app.api.repo.repo_fetch_json")
    def test_repo_fetch_index_empty(self, mock_fetch, client):
        test_client, _ = client
        mock_fetch.return_value = []
        resp = test_client.get("/api/repo/fetch?url=https://example.com/index.json")
        assert resp.status_code == 200
        assert resp.json() == []


class TestRepoFetchTask:
    """测试 GET /api/repo/task 端点。"""

    @patch("app.api.repo.repo_fetch_json")
    def test_repo_fetch_task_success(self, mock_fetch, client):
        test_client, _ = client
        mock_fetch.return_value = {"name": "任务详情", "steps": []}
        resp = test_client.get("/api/repo/task?url=https://example.com/task.json")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)
        assert data["name"] == "任务详情"
