"""仓库代理路由 API 测试 — 覆盖远程任务仓库索引和任务配置获取端点。"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from app.schemas import (
    GlobalSettings,
    MonitorConfigPayload,
    MonitorStatusResponse,
    ProfilesData,
    ProfileSettings,
)


class TestRepoFetchIndex:
    """测试 GET /api/repo/fetch 端点。"""

    @patch("app.api.repo.async_repo_fetch_json", new_callable=AsyncMock)
    def test_repo_fetch_index_success(self, mock_fetch, api_client):
        test_client, mock_services = api_client
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
        mock_services.profile_service.load.return_value = ProfilesData(
            global_settings=GlobalSettings(),
            profiles={"default": ProfileSettings(name="默认方案", username="testuser", password="ENC:test")},
        )
        mock_fetch.return_value = [{"id": "task1", "name": "任务1"}]
        resp = test_client.get("/api/repo/fetch?url=https://example.com/index.json")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert data[0]["id"] == "task1"

    @patch("app.api.repo.async_repo_fetch_json", new_callable=AsyncMock)
    def test_repo_fetch_index_empty(self, mock_fetch, api_client):
        test_client, mock_services = api_client
        mock_services.engine.get_config.return_value = MonitorConfigPayload(
            username="testuser", password="••••••••", auth_url="http://10.0.0.1"
        )
        mock_services.profile_service.load.return_value = ProfilesData(
            global_settings=GlobalSettings(),
            profiles={"default": ProfileSettings(name="默认方案", username="testuser", password="ENC:test")},
        )
        mock_fetch.return_value = []
        resp = test_client.get("/api/repo/fetch?url=https://example.com/index.json")
        assert resp.status_code == 200
        assert resp.json() == []


class TestRepoFetchTask:
    """测试 GET /api/repo/task 端点。"""

    @patch("app.api.repo.async_repo_fetch_json", new_callable=AsyncMock)
    def test_repo_fetch_task_success(self, mock_fetch, api_client):
        test_client, mock_services = api_client
        mock_services.engine.get_config.return_value = MonitorConfigPayload(
            username="testuser", password="••••••••", auth_url="http://10.0.0.1"
        )
        mock_services.profile_service.load.return_value = ProfilesData(
            global_settings=GlobalSettings(),
            profiles={"default": ProfileSettings(name="默认方案", username="testuser", password="ENC:test")},
        )
        mock_fetch.return_value = {"name": "任务详情", "steps": []}
        resp = test_client.get("/api/repo/task?url=https://example.com/task.json")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)
        assert data["name"] == "任务详情"
