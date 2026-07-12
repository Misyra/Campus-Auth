"""验证 scheduled_tasks.py toggle 端点无副作用。

toggle 端点不原地修改 get_task 返回的数据，避免副作用。
"""

from __future__ import annotations

from unittest.mock import MagicMock


class TestToggleNoSideEffect:
    """验证 toggle 端点不会原地修改 get_task 返回的字典。"""

    def test_toggle_does_not_mutate_original_task_dict(self, api_client):
        """toggle 后传给 save_task 的字典应是副本，原字典的 enabled 不变。

        修复前：task["enabled"] = not task.get("enabled", True) 直接修改原字典，
        导致后续读取同一个 dict 时 enabled 已被改变。
        """
        test_client, mock_services = api_client
        mock_engine = MagicMock()
        mock_tasks = MagicMock()
        mock_engine.tasks = mock_tasks
        mock_services.engine = mock_engine

        mock_tasks.registry.get_task.return_value = None
        mock_tasks.registry.list_tasks.return_value = []
        mock_tasks.registry.save_task.return_value = (True, "保存成功")

        original_task = {
            "id": "task1",
            "name": "test",
            "enabled": False,
            "type": "script",
            "target_id": "test_script",
            "schedule": {"hour": 0, "minute": 0},
        }
        mock_tasks.registry.get_task.return_value = original_task
        mock_tasks.registry.save_task.return_value = (True, "成功")

        resp = test_client.post("/api/scheduled-tasks/task1/toggle")
        assert resp.status_code == 200
        assert resp.json()["success"] is True

        # 关键断言：原始字典不应被修改
        assert original_task["enabled"] is False, (
            "toggle 端点不应原地修改 get_task 返回的字典"
        )

        # save_task 应收到 enabled=True 的字典
        saved_task = mock_tasks.registry.save_task.call_args[0][1]
        assert saved_task["enabled"] is True

    def test_toggle_to_disable_does_not_mutate(self, api_client):
        """从启用切换到禁用时同样不应修改原字典。"""
        test_client, mock_services = api_client
        mock_engine = MagicMock()
        mock_tasks = MagicMock()
        mock_engine.tasks = mock_tasks
        mock_services.engine = mock_engine

        mock_tasks.registry.get_task.return_value = None
        mock_tasks.registry.list_tasks.return_value = []
        mock_tasks.registry.save_task.return_value = (True, "保存成功")

        original_task = {
            "id": "task2",
            "name": "test2",
            "enabled": True,
            "type": "script",
            "target_id": "test_script",
            "schedule": {"hour": 8, "minute": 0},
        }
        mock_tasks.registry.get_task.return_value = original_task
        mock_tasks.registry.save_task.return_value = (True, "成功")

        resp = test_client.post("/api/scheduled-tasks/task2/toggle")
        assert resp.status_code == 200

        # 原始字典不应被修改
        assert original_task["enabled"] is True, (
            "toggle 端点不应原地修改 get_task 返回的字典"
        )

        saved_task = mock_tasks.registry.save_task.call_args[0][1]
        assert saved_task["enabled"] is False
