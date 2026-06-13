"""验证 scheduled_tasks.py 两个修复点的测试。

1. toggle 端点不原地修改 get_task 返回的数据（避免副作用）
2. 依赖注入使用 Depends 模式（已有测试覆盖端点功能，此处补充 toggle 副作用测试）
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path):
    """创建测试客户端。"""
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
        from app.application import create_app

        mock_services = MagicMock()
        mock_engine = MagicMock()
        mock_tasks = MagicMock()
        mock_engine.tasks = mock_tasks
        mock_services.engine = mock_engine

        mock_tasks.get_task.return_value = None
        mock_tasks.list_tasks.return_value = []
        mock_tasks.save_task.return_value = (True, "保存成功")

        app = create_app()
        app.state.services = mock_services

        test_client = TestClient(app)
        yield test_client, mock_tasks, mock_engine


class TestToggleNoSideEffect:
    """验证 toggle 端点不会原地修改 get_task 返回的字典。"""

    def test_toggle_does_not_mutate_original_task_dict(self, client):
        """toggle 后传给 save_task 的字典应是副本，原字典的 enabled 不变。

        修复前：task["enabled"] = not task.get("enabled", True) 直接修改原字典，
        导致后续读取同一个 dict 时 enabled 已被改变。
        """
        test_client, tasks, engine = client
        original_task = {
            "id": "task1",
            "name": "test",
            "enabled": False,
            "type": "shell",
            "command": "echo",
            "schedule": {"hour": 0, "minute": 0},
        }
        tasks.get_task.return_value = original_task
        tasks.save_task.return_value = (True, "成功")

        resp = test_client.post("/api/scheduled-tasks/task1/toggle")
        assert resp.status_code == 200
        assert resp.json()["success"] is True

        # 关键断言：原始字典不应被修改
        assert original_task["enabled"] is False, (
            "toggle 端点不应原地修改 get_task 返回的字典"
        )

        # save_task 应收到 enabled=True 的字典
        saved_task = tasks.save_task.call_args[0][1]
        assert saved_task["enabled"] is True

    def test_toggle_to_disable_does_not_mutate(self, client):
        """从启用切换到禁用时同样不应修改原字典。"""
        test_client, tasks, engine = client
        original_task = {
            "id": "task2",
            "name": "test2",
            "enabled": True,
            "type": "shell",
            "command": "echo",
            "schedule": {"hour": 8, "minute": 0},
        }
        tasks.get_task.return_value = original_task
        tasks.save_task.return_value = (True, "成功")

        resp = test_client.post("/api/scheduled-tasks/task2/toggle")
        assert resp.status_code == 200

        # 原始字典不应被修改
        assert original_task["enabled"] is True, (
            "toggle 端点不应原地修改 get_task 返回的字典"
        )

        saved_task = tasks.save_task.call_args[0][1]
        assert saved_task["enabled"] is False
