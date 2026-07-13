"""脚本路由 API 测试 — 覆盖脚本 CRUD 和执行等端点。"""

from __future__ import annotations

# ── 列出脚本 ──


class TestListScripts:
    """GET /api/scripts"""

    def test_list_empty(self, api_client):
        """无脚本时返回空列表。"""
        test_client, mock_services = api_client
        mock_services.task_manager.list_script_tasks.return_value = []
        resp = test_client.get("/api/scripts")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_with_scripts(self, api_client):
        """有脚本时返回列表。"""
        test_client, mock_services = api_client
        mock_services.task_manager.list_script_tasks.return_value = [
            {"id": "script1", "name": "脚本1", "type": "py"},
            {"id": "script2", "name": "脚本2", "type": "py"},
        ]
        resp = test_client.get("/api/scripts")
        assert resp.status_code == 200
        assert len(resp.json()) == 2


# ── 获取脚本详情 ──


class TestGetScript:
    """GET /api/scripts/{task_id}"""

    def test_get_existing_script(self, api_client):
        """获取存在的脚本任务。"""
        test_client, mock_services = api_client
        mock_services.task_manager.get_task_detail.return_value = {
            "id": "script1",
            "name": "测试脚本",
            "type": "py",
            "content": "echo hello",
        }
        resp = test_client.get("/api/scripts/script1")
        assert resp.status_code == 200
        assert resp.json()["name"] == "测试脚本"

    def test_get_nonexistent_script(self, api_client):
        """获取不存在的脚本返回 404。"""
        test_client, mock_services = api_client
        mock_services.task_manager.get_task_detail.return_value = None
        resp = test_client.get("/api/scripts/nonexistent")
        assert resp.status_code == 404

    def test_get_browser_task_as_script(self, api_client):
        """浏览器任务类型不是 script 返回 404。"""
        test_client, mock_services = api_client
        mock_services.task_manager.get_task_detail.return_value = {
            "id": "task1",
            "name": "浏览器任务",
            "type": "browser",
        }
        resp = test_client.get("/api/scripts/task1")
        assert resp.status_code == 404


# ── 保存脚本 ──


class TestSaveScript:
    """PUT /api/scripts/{task_id}"""

    def test_save_script_success(self, api_client):
        """保存脚本成功。"""
        test_client, mock_services = api_client
        mock_services.task_manager.save_task_with_validation.return_value = (
            True,
            "保存成功",
        )
        resp = test_client.put(
            "/api/scripts/new_script",
            json={"name": "新脚本", "content": "echo test", "type": "py"},
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_save_script_failure(self, api_client):
        """保存脚本失败。"""
        test_client, mock_services = api_client
        mock_services.task_manager.save_task_with_validation.return_value = (
            False,
            "保存失败",
        )
        resp = test_client.put(
            "/api/scripts/bad_script",
            json={"name": "坏脚本"},
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is False


# ── 删除脚本 ──


class TestDeleteScript:
    """DELETE /api/scripts/{task_id}"""

    def test_delete_existing_script(self, api_client):
        """删除存在的脚本。"""
        test_client, mock_services = api_client
        mock_services.task_manager.delete_task_with_validation.return_value = (
            True,
            "删除成功",
        )
        resp = test_client.delete("/api/scripts/script1")
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_delete_nonexistent_script(self, api_client):
        """删除不存在的脚本。"""
        test_client, mock_services = api_client
        mock_services.task_manager.delete_task_with_validation.return_value = (
            False,
            "脚本不存在",
        )
        resp = test_client.delete("/api/scripts/nonexistent")
        assert resp.status_code == 200
        assert resp.json()["success"] is False


# ── 运行脚本 ──


class TestRunScript:
    """POST /api/scripts/{task_id}/run

    Task 4.2：run_script 改用 TaskExecutor.run_script_on_demand + asyncio.to_thread，
    不再使用模块级 _script_executor 线程池，不再构造 ScriptRunner。
    """

    def test_run_script_success(self, api_client):
        """运行存在的脚本成功 — 通过 task_executor.run_script_on_demand 返回成功。"""
        test_client, mock_services = api_client
        mock_services.task_manager.get_task_detail.return_value = {
            "id": "script1",
            "name": "测试",
            "type": "py",
        }
        mock_services.task_executor.run_script_on_demand.return_value = (
            True,
            "执行成功",
        )

        resp = test_client.post("/api/scripts/script1/run")

        assert resp.status_code == 200
        assert resp.json()["success"] is True
        assert resp.json()["message"] == "执行成功"
        # 应调用 task_executor.run_script_on_demand 且不传 timeout（使用默认 None）
        mock_services.task_executor.run_script_on_demand.assert_called_once_with(
            "script1"
        )

    def test_run_script_not_found(self, api_client):
        """运行不存在的脚本返回 404 — task_mgr.get_task_detail 返回 None 触发。"""
        test_client, mock_services = api_client
        mock_services.task_manager.get_task_detail.return_value = None
        resp = test_client.post("/api/scripts/nonexistent/run")
        assert resp.status_code == 404
        # 404 时不应调用 run_script_on_demand
        mock_services.task_executor.run_script_on_demand.assert_not_called()

    def test_run_script_file_missing(self, api_client):
        """脚本文件不存在时返回失败 — 由 run_script_on_demand 内部检查。"""
        test_client, mock_services = api_client
        mock_services.task_manager.get_task_detail.return_value = {
            "id": "test_task",
            "name": "测试",
            "type": "py",
        }
        # 模拟 _execute_script 内部检查脚本文件不存在时的返回
        mock_services.task_executor.run_script_on_demand.return_value = (
            False,
            "脚本文件不存在: test_task",
        )

        resp = test_client.post("/api/scripts/test_task/run")

        assert resp.status_code == 200
        assert resp.json()["success"] is False
        assert resp.json()["message"] == "脚本文件不存在: test_task"

    def test_run_script_wrong_type(self, api_client):
        """任务类型非脚本时返回 404 — 仍由 task_mgr 验证触发。"""
        test_client, mock_services = api_client
        mock_services.task_manager.get_task_detail.return_value = {
            "id": "task1",
            "name": "浏览器任务",
            "type": "browser",
        }
        resp = test_client.post("/api/scripts/task1/run")
        assert resp.status_code == 404
        mock_services.task_executor.run_script_on_demand.assert_not_called()
