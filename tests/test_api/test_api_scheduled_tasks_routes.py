"""定时任务路由 API 测试 — 覆盖创建、更新、切换、手动执行、历史查询等端点。"""

from __future__ import annotations

from unittest.mock import MagicMock


# ── 创建定时任务 ──


class TestCreateScheduledTask:
    """POST /api/scheduled-tasks"""

    def test_create_shell_task_success(self, api_client):
        """创建 Shell 类型任务成功。"""
        test_client, mock_services = api_client
        mock_engine = MagicMock()
        mock_tasks = MagicMock()
        mock_engine.tasks = mock_tasks
        mock_services.engine = mock_engine
        mock_tasks.save_task.return_value = (True, "创建成功")
        resp = test_client.post(
            "/api/scheduled-tasks",
            json={
                "name": "测试任务",
                "type": "shell",
                "command": "echo hello",
                "schedule": {"hour": 8, "minute": 30},
            },
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_create_script_task_success(self, api_client):
        """创建 script 类型任务成功。"""
        test_client, mock_services = api_client
        mock_engine = MagicMock()
        mock_tasks = MagicMock()
        mock_engine.tasks = mock_tasks
        mock_services.engine = mock_engine
        mock_tasks.save_task.return_value = (True, "创建成功")
        resp = test_client.post(
            "/api/scheduled-tasks",
            json={
                "name": "脚本任务",
                "type": "script",
                "target_id": "script1",
                "schedule": {"hour": 10, "minute": 0},
            },
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_create_browser_task_success(self, api_client):
        """创建 browser 类型任务成功。"""
        test_client, mock_services = api_client
        mock_engine = MagicMock()
        mock_tasks = MagicMock()
        mock_engine.tasks = mock_tasks
        mock_services.engine = mock_engine
        mock_tasks.save_task.return_value = (True, "创建成功")
        resp = test_client.post(
            "/api/scheduled-tasks",
            json={
                "name": "浏览器任务",
                "type": "browser",
                "target_id": "default",
                "schedule": {"hour": 12, "minute": 0},
            },
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_create_missing_name(self, api_client):
        """缺少名称返回失败。"""
        test_client, mock_services = api_client
        mock_engine = MagicMock()
        mock_tasks = MagicMock()
        mock_engine.tasks = mock_tasks
        mock_services.engine = mock_engine
        resp = test_client.post(
            "/api/scheduled-tasks",
            json={
                "type": "shell",
                "command": "echo",
                "schedule": {"hour": 0, "minute": 0},
            },
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is False

    def test_create_invalid_type(self, api_client):
        """无效类型返回失败。"""
        test_client, mock_services = api_client
        mock_engine = MagicMock()
        mock_tasks = MagicMock()
        mock_engine.tasks = mock_tasks
        mock_services.engine = mock_engine
        resp = test_client.post(
            "/api/scheduled-tasks",
            json={
                "name": "test",
                "type": "invalid",
                "schedule": {"hour": 0, "minute": 0},
            },
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is False

    def test_create_shell_missing_command(self, api_client):
        """Shell 类型缺少命令返回失败。"""
        test_client, mock_services = api_client
        mock_engine = MagicMock()
        mock_tasks = MagicMock()
        mock_engine.tasks = mock_tasks
        mock_services.engine = mock_engine
        resp = test_client.post(
            "/api/scheduled-tasks",
            json={
                "name": "test",
                "type": "shell",
                "schedule": {"hour": 0, "minute": 0},
            },
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is False

    def test_create_script_missing_target(self, api_client):
        """script 类型缺少 target_id 返回失败。"""
        test_client, mock_services = api_client
        mock_engine = MagicMock()
        mock_tasks = MagicMock()
        mock_engine.tasks = mock_tasks
        mock_services.engine = mock_engine
        resp = test_client.post(
            "/api/scheduled-tasks",
            json={
                "name": "test",
                "type": "script",
                "schedule": {"hour": 0, "minute": 0},
            },
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is False

    def test_create_missing_schedule(self, api_client):
        """缺少时间设置返回失败。"""
        test_client, mock_services = api_client
        mock_engine = MagicMock()
        mock_tasks = MagicMock()
        mock_engine.tasks = mock_tasks
        mock_services.engine = mock_engine
        resp = test_client.post(
            "/api/scheduled-tasks",
            json={"name": "test", "type": "shell", "command": "echo"},
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is False

    def test_create_starts_scheduler_when_enabled(self, api_client):
        """创建启用的任务时会启动调度器。"""
        test_client, mock_services = api_client
        mock_engine = MagicMock()
        mock_tasks = MagicMock()
        mock_engine.tasks = mock_tasks
        mock_services.engine = mock_engine
        mock_tasks.save_task.return_value = (True, "创建成功")
        resp = test_client.post(
            "/api/scheduled-tasks",
            json={
                "name": "test",
                "type": "shell",
                "command": "echo",
                "enabled": True,
                "schedule": {"hour": 0, "minute": 0},
            },
        )
        assert resp.status_code == 200
        mock_engine.sync_scheduler_state.assert_called()


# ── 更新定时任务 ──


class TestUpdateScheduledTask:
    """PUT /api/scheduled-tasks/{task_id}"""

    def test_update_success(self, api_client):
        """更新已有任务成功。"""
        test_client, mock_services = api_client
        mock_engine = MagicMock()
        mock_tasks = MagicMock()
        mock_engine.tasks = mock_tasks
        mock_services.engine = mock_engine
        mock_tasks.get_task.return_value = {
            "id": "task1",
            "name": "旧名称",
            "type": "shell",
            "command": "echo old",
            "enabled": True,
            "schedule": {"hour": 8, "minute": 0},
            "timeout": 60,
        }
        mock_tasks.save_task.return_value = (True, "更新成功")
        resp = test_client.put(
            "/api/scheduled-tasks/task1",
            json={"name": "新名称", "command": "echo new"},
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_update_nonexistent(self, api_client):
        """更新不存在的任务返回失败。"""
        test_client, mock_services = api_client
        mock_engine = MagicMock()
        mock_tasks = MagicMock()
        mock_engine.tasks = mock_tasks
        mock_services.engine = mock_engine
        mock_tasks.get_task.return_value = None
        resp = test_client.put(
            "/api/scheduled-tasks/nonexistent",
            json={"name": "test"},
        )
        assert resp.status_code == 404

    def test_update_empty_name(self, api_client):
        """更新为空名称返回失败。"""
        test_client, mock_services = api_client
        mock_engine = MagicMock()
        mock_tasks = MagicMock()
        mock_engine.tasks = mock_tasks
        mock_services.engine = mock_engine
        mock_tasks.get_task.return_value = {
            "id": "task1",
            "name": "旧名称",
            "type": "shell",
            "command": "echo",
            "schedule": {"hour": 0, "minute": 0},
        }
        resp = test_client.put(
            "/api/scheduled-tasks/task1",
            json={"name": ""},
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is False

    def test_update_invalid_type(self, api_client):
        """更新为无效类型返回失败。"""
        test_client, mock_services = api_client
        mock_engine = MagicMock()
        mock_tasks = MagicMock()
        mock_engine.tasks = mock_tasks
        mock_services.engine = mock_engine
        mock_tasks.get_task.return_value = {
            "id": "task1",
            "name": "test",
            "type": "shell",
            "command": "echo",
            "schedule": {"hour": 0, "minute": 0},
        }
        resp = test_client.put(
            "/api/scheduled-tasks/task1",
            json={"type": "invalid"},
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is False

    def test_update_to_shell_without_command(self, api_client):
        """更新为 shell 类型但无命令返回失败。"""
        test_client, mock_services = api_client
        mock_engine = MagicMock()
        mock_tasks = MagicMock()
        mock_engine.tasks = mock_tasks
        mock_services.engine = mock_engine
        mock_tasks.get_task.return_value = {
            "id": "task1",
            "name": "test",
            "type": "script",
            "target_id": "s1",
            "schedule": {"hour": 0, "minute": 0},
        }
        resp = test_client.put(
            "/api/scheduled-tasks/task1",
            json={"type": "shell"},
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is False


# ── 切换启用/禁用 ──


class TestToggleScheduledTask:
    """POST /api/scheduled-tasks/{task_id}/toggle"""

    def test_toggle_enable(self, api_client):
        """切换启用禁用状态。"""
        test_client, mock_services = api_client
        mock_engine = MagicMock()
        mock_tasks = MagicMock()
        mock_engine.tasks = mock_tasks
        mock_services.engine = mock_engine
        mock_tasks.get_task.return_value = {
            "id": "task1",
            "name": "test",
            "enabled": False,
            "type": "shell",
            "command": "echo",
            "schedule": {"hour": 0, "minute": 0},
        }
        mock_tasks.save_task.return_value = (True, "成功")
        resp = test_client.post("/api/scheduled-tasks/task1/toggle")
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        assert "启用" in resp.json()["message"]

    def test_toggle_disable(self, api_client):
        """切换禁用状态。"""
        test_client, mock_services = api_client
        mock_engine = MagicMock()
        mock_tasks = MagicMock()
        mock_engine.tasks = mock_tasks
        mock_services.engine = mock_engine
        mock_tasks.get_task.return_value = {
            "id": "task1",
            "name": "test",
            "enabled": True,
            "type": "shell",
            "command": "echo",
            "schedule": {"hour": 0, "minute": 0},
        }
        mock_tasks.save_task.return_value = (True, "成功")
        resp = test_client.post("/api/scheduled-tasks/task1/toggle")
        assert resp.status_code == 200
        assert "禁用" in resp.json()["message"]

    def test_toggle_nonexistent(self, api_client):
        """切换不存在的任务返回失败。"""
        test_client, mock_services = api_client
        mock_engine = MagicMock()
        mock_tasks = MagicMock()
        mock_engine.tasks = mock_tasks
        mock_services.engine = mock_engine
        mock_tasks.get_task.return_value = None
        resp = test_client.post("/api/scheduled-tasks/nonexistent/toggle")
        assert resp.status_code == 404


# ── 手动执行 ──


class TestRunScheduledTask:
    """POST /api/scheduled-tasks/{task_id}/run"""

    def test_run_success(self, api_client):
        """手动执行存在的任务成功。"""
        test_client, mock_services = api_client
        mock_engine = MagicMock()
        mock_tasks = MagicMock()
        mock_engine.tasks = mock_tasks
        mock_services.engine = mock_engine
        mock_tasks.get_task.return_value = {"id": "task1", "name": "test"}
        mock_tasks.execute_task = MagicMock(return_value=(True, "执行成功"))
        resp = test_client.post("/api/scheduled-tasks/task1/run")
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_run_nonexistent(self, api_client):
        """执行不存在的任务返回失败。"""
        test_client, mock_services = api_client
        mock_engine = MagicMock()
        mock_tasks = MagicMock()
        mock_engine.tasks = mock_tasks
        mock_services.engine = mock_engine
        mock_tasks.get_task.return_value = None
        resp = test_client.post("/api/scheduled-tasks/nonexistent/run")
        assert resp.status_code == 404

    def test_run_failure(self, api_client):
        """后台执行时立即返回成功，实际结果通过执行历史查看。"""
        test_client, mock_services = api_client
        mock_engine = MagicMock()
        mock_tasks = MagicMock()
        mock_engine.tasks = mock_tasks
        mock_services.engine = mock_engine
        mock_tasks.get_task.return_value = {"id": "task1", "name": "test"}
        mock_tasks.execute_task = MagicMock(return_value=(False, "执行超时"))
        resp = test_client.post("/api/scheduled-tasks/task1/run")
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        assert "已提交后台执行" in resp.json()["message"]


# ── 获取执行历史 ──


class TestGetScheduledTaskHistory:
    """GET /api/scheduled-tasks/{task_id}/history"""

    def test_get_history_success(self, api_client):
        """获取存在的任务历史。"""
        test_client, mock_services = api_client
        mock_engine = MagicMock()
        mock_tasks = MagicMock()
        mock_engine.tasks = mock_tasks
        mock_services.engine = mock_engine
        mock_tasks.get_task.return_value = {"id": "task1", "name": "test"}
        mock_tasks.get_history.return_value = [
            {"timestamp": "2026-06-08T10:00:00", "status": "success", "message": "ok"},
            {"timestamp": "2026-06-08T09:00:00", "status": "failure", "message": "err"},
        ]
        resp = test_client.get("/api/scheduled-tasks/task1/history")
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    def test_get_history_nonexistent(self, api_client):
        """获取不存在的任务历史返回 404。"""
        test_client, mock_services = api_client
        mock_engine = MagicMock()
        mock_tasks = MagicMock()
        mock_engine.tasks = mock_tasks
        mock_services.engine = mock_engine
        mock_tasks.get_task.return_value = None
        resp = test_client.get("/api/scheduled-tasks/nonexistent/history")
        assert resp.status_code == 404
