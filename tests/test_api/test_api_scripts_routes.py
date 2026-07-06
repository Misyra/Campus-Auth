"""脚本路由 API 测试 — 覆盖脚本 CRUD 和执行等端点。"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock, patch

import pytest

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
            {"id": "script1", "name": "脚本1", "type": "script"},
            {"id": "script2", "name": "脚本2", "type": "script"},
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
            "type": "script",
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
            json={"name": "新脚本", "content": "echo test", "type": "script"},
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
    """POST /api/scripts/{task_id}/run"""

    def test_run_script_success(self, api_client, tmp_path):
        """运行存在的脚本成功。"""
        test_client, mock_services = api_client
        script_file = tmp_path / "test_script.sh"
        script_file.write_text("echo hello", encoding="utf-8")

        mock_services.task_manager.get_task_detail.return_value = {
            "id": "script1",
            "name": "测试",
            "type": "script",
            "binary_path": "",
        }
        mock_services.task_manager.get_script_path.return_value = script_file

        with patch("app.api.scripts.ScriptRunner") as MockRunner:
            mock_runner = MagicMock()
            mock_runner.run.return_value = (True, "执行成功")
            MockRunner.return_value = mock_runner

            resp = test_client.post("/api/scripts/script1/run")

        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_run_script_not_found(self, api_client):
        """运行不存在的脚本返回 404。"""
        test_client, mock_services = api_client
        mock_services.task_manager.get_task_detail.return_value = None
        resp = test_client.post("/api/scripts/nonexistent/run")
        assert resp.status_code == 404

    def test_run_script_file_missing(self, api_client):
        """脚本文件不存在时返回失败。"""
        test_client, mock_services = api_client
        mock_services.task_manager.get_task_detail.return_value = {
            "id": "script1",
            "name": "测试",
            "type": "script",
        }
        mock_services.task_manager.get_script_path.return_value = None
        resp = test_client.post("/api/scripts/script1/run")
        assert resp.status_code == 200
        assert resp.json()["success"] is False


# ── 获取可用二进制列表 ──


class TestListBinaries:
    """GET /api/scripts/binaries"""

    @patch("app.api.scripts.detect_available_binaries")
    def test_list_binaries(self, mock_detect, api_client):
        """返回可用二进制列表。"""
        mock_detect.return_value = [
            {"name": "Python", "path": "/usr/bin/python3", "description": "Python"},
            {"name": "bash", "path": "/bin/bash", "description": "Bash"},
        ]
        test_client, _ = api_client
        resp = test_client.get("/api/scripts/binaries")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


# ── 线程池验证 ──


class TestScriptThreadPool:
    """验证 run_script 使用专用线程池。"""

    @pytest.mark.asyncio
    async def test_run_script_uses_dedicated_executor(self):
        """run_script 应使用专用 ThreadPoolExecutor 而非默认线程池。"""
        from app.api.scripts import run_script

        if hasattr(run_script, "_executor"):
            delattr(run_script, "_executor")

        captured_executor = {}

        mock_task_mgr = MagicMock()
        mock_task_mgr.get_task_detail.return_value = {
            "type": "script",
            "binary_path": "",
        }
        mock_task_mgr.get_script_path.return_value = MagicMock(
            exists=MagicMock(return_value=True)
        )

        mock_request = MagicMock()
        mock_request.app.state.services.monitor_service.get_runtime_config.return_value = {
            "monitor": {"script_timeout": 60}
        }

        async def mock_run_in_executor(executor, func):
            captured_executor["executor"] = executor
            return True, "mock success"

        with (
            patch("app.api.scripts.ScriptRunner") as mock_runner_cls,
            patch.object(
                asyncio.BaseEventLoop,
                "run_in_executor",
                side_effect=mock_run_in_executor,
            ),
        ):
            mock_runner = MagicMock()
            mock_runner_cls.return_value = mock_runner
            result = await run_script(mock_request, "test_task", mock_task_mgr)

        assert result.success is True
        executor = captured_executor.get("executor")
        assert executor is not None
        assert isinstance(executor, ThreadPoolExecutor)
        assert executor._thread_name_prefix == "script_api"

    @pytest.mark.asyncio
    async def test_executor_is_reused(self):
        """模块级 executor 应存在并可复用。"""
        from app.api.scripts import _script_executor

        assert _script_executor is not None
        assert isinstance(_script_executor, ThreadPoolExecutor)
        assert _script_executor._thread_name_prefix == "script_api"
