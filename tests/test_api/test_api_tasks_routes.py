"""任务路由 API 测试 — 覆盖任务 CRUD 及活动任务管理端点。"""

from __future__ import annotations

from app.schemas import MonitorConfigPayload, MonitorStatusResponse


def _setup_task_mocks(mock_services):
    """配置 task_service 和 engine mock 返回值。"""
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

    mock_services.task_service.list_tasks.return_value = [
        {"id": "default", "name": "默认任务"}
    ]
    mock_services.task_service.get_active_task.return_value = "default"
    mock_services.task_service.get_task.return_value = {
        "id": "default",
        "name": "默认任务",
        "steps": [{"id": "s1", "type": "click", "selector": "#btn"}],
    }
    mock_services.task_service.save_task.return_value = (True, "保存成功")
    mock_services.task_service.delete_task.return_value = (True, "删除成功")
    mock_services.task_service.set_active_task.return_value = (True, "切换成功")
    mock_services.task_service.save_task_order.return_value = (True, "排序成功")


class TestListTasks:
    """测试 GET /api/tasks 端点。"""

    def test_list_tasks_returns_200(self, api_client):
        test_client, mock_services = api_client
        _setup_task_mocks(mock_services)
        resp = test_client.get("/api/tasks")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_list_tasks_content(self, api_client):
        test_client, mock_services = api_client
        _setup_task_mocks(mock_services)
        data = test_client.get("/api/tasks").json()
        assert len(data) == 1
        assert data[0]["id"] == "default"


class TestGetActiveTask:
    """测试 GET /api/tasks/active 端点。"""

    def test_get_active_task_returns_200(self, api_client):
        test_client, mock_services = api_client
        _setup_task_mocks(mock_services)
        resp = test_client.get("/api/tasks/active")
        assert resp.status_code == 200
        assert resp.json()["task_id"] == "default"


class TestGetTask:
    """测试 GET /api/tasks/{task_id} 端点。"""

    def test_get_task_found(self, api_client):
        test_client, mock_services = api_client
        _setup_task_mocks(mock_services)
        resp = test_client.get("/api/tasks/default")
        assert resp.status_code == 200
        assert resp.json()["name"] == "默认任务"

    def test_get_task_not_found(self, api_client):
        test_client, mock_services = api_client
        _setup_task_mocks(mock_services)
        mock_services.task_service.get_task.return_value = None
        resp = test_client.get("/api/tasks/nonexistent")
        assert resp.status_code == 404


class TestSaveTask:
    """测试 PUT /api/tasks/{task_id} 端点。"""

    def test_save_task_success(self, api_client):
        test_client, mock_services = api_client
        _setup_task_mocks(mock_services)
        resp = test_client.put(
            "/api/tasks/new_task",
            json={
                "name": "新任务",
                "steps": [{"id": "s1", "type": "click", "selector": "#btn"}],
            },
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is True


class TestDeleteTask:
    """测试 DELETE /api/tasks/{task_id} 端点。"""

    def test_delete_task_success(self, api_client):
        test_client, mock_services = api_client
        _setup_task_mocks(mock_services)
        resp = test_client.delete("/api/tasks/default")
        assert resp.status_code == 200
        assert resp.json()["success"] is True


class TestSetActiveTask:
    """测试 POST /api/tasks/active/{task_id} 端点。"""

    def test_set_active_task_success(self, api_client):
        test_client, mock_services = api_client
        _setup_task_mocks(mock_services)
        resp = test_client.post("/api/tasks/active/default")
        assert resp.status_code == 200
        assert resp.json()["success"] is True


class TestSaveTaskOrder:
    """测试 POST /api/tasks/order 端点。"""

    def test_save_task_order_success(self, api_client):
        test_client, mock_services = api_client
        _setup_task_mocks(mock_services)
        resp = test_client.post("/api/tasks/order", json={"order": ["default"]})
        assert resp.status_code == 200
        assert resp.json()["success"] is True
