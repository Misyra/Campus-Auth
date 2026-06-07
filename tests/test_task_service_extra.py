"""TaskService 扩展测试 — save_task_order / list_scripts / _save_script_task

补充 test_backend_services.py 中未覆盖的部分。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.task import TaskService


# =====================================================================
# save_task_order
# =====================================================================


class TestSaveTaskOrder:
    @pytest.fixture
    def service(self, tmp_path: Path) -> TaskService:
        return TaskService(tmp_path)

    def test_save_valid_order(self, service: TaskService):
        order = {"browser": ["task_a", "task_b"], "scripts": ["script_1"]}
        ok, msg = service.save_task_order(order)
        assert ok is True
        assert "成功" in msg

    def test_save_invalid_order_type(self, service: TaskService):
        ok, msg = service.save_task_order("not a dict")
        assert ok is False
        assert "格式" in msg

    def test_save_empty_order(self, service: TaskService):
        ok, msg = service.save_task_order({})
        assert ok is True


# =====================================================================
# list_scripts
# =====================================================================


class TestListScripts:
    @pytest.fixture
    def service(self, tmp_path: Path) -> TaskService:
        return TaskService(tmp_path)

    def test_list_scripts_empty(self, service: TaskService):
        assert service.list_scripts() == []

    def test_list_scripts_returns_scripts(self, service: TaskService, tmp_path: Path):
        scripts_dir = tmp_path / "tasks" / "scripts"
        scripts_dir.mkdir(parents=True, exist_ok=True)
        (scripts_dir / "my_script.json").write_text(
            json.dumps({"type": "script", "name": "我的脚本", "content": 'print("hi")'}),
            encoding="utf-8",
        )
        scripts = service.list_scripts()
        assert len(scripts) == 1
        assert scripts[0]["id"] == "my_script"


# =====================================================================
# _save_script_task
# =====================================================================


class TestSaveScriptTask:
    @pytest.fixture
    def service(self, tmp_path: Path) -> TaskService:
        return TaskService(tmp_path)

    def test_save_script_success(self, service: TaskService):
        config = {"type": "script", "content": 'print("hello")', "name": "测试脚本"}
        ok, msg = service.save_task("my_script", config)
        assert ok is True
        assert "脚本" in msg

    def test_save_script_empty_content(self, service: TaskService):
        config = {"type": "script", "content": "", "name": "空脚本"}
        ok, msg = service.save_task("empty_script", config)
        assert ok is False
        assert "内容" in msg

    def test_save_script_whitespace_content(self, service: TaskService):
        config = {"type": "script", "content": "   \n  ", "name": "空白脚本"}
        ok, msg = service.save_task("ws_script", config)
        assert ok is False
        assert "内容" in msg

    def test_save_script_with_binary_path(self, service: TaskService):
        config = {
            "type": "script",
            "content": 'print("custom binary")',
            "name": "自定义二进制",
            "binary_path": "/usr/bin/python3",
        }
        ok, msg = service.save_task("custom_bin", config)
        assert ok is True

    def test_save_script_invalid_id(self, service: TaskService):
        config = {"type": "script", "content": 'print("hi")'}
        ok, msg = service.save_task("123bad", config)
        assert ok is False
        assert "ID" in msg


# =====================================================================
# get_task 脚本分支
# =====================================================================


class TestGetTaskScript:
    @pytest.fixture
    def service(self, tmp_path: Path) -> TaskService:
        return TaskService(tmp_path)

    def test_get_script_task(self, service: TaskService):
        config = {"type": "script", "content": 'print("test")', "name": "测试"}
        service.save_task("test_script", config)
        task = service.get_task("test_script")
        assert task is not None
        assert task["type"] == "script"
        assert task["content"] == 'print("test")'
        assert task["name"] == "测试"

    def test_get_script_task_with_binary(self, service: TaskService):
        config = {
            "type": "script",
            "content": 'print("binary")',
            "name": "二进制脚本",
            "binary_path": "/usr/bin/python3",
        }
        service.save_task("bin_script", config)
        task = service.get_task("bin_script")
        assert task is not None
        assert task["binary_path"] == "/usr/bin/python3"

    def test_get_browser_task(self, service: TaskService):
        config = {
            "name": "浏览器任务",
            "url": "http://test.com",
            "steps": [{"id": "s1", "type": "click", "selector": "#btn"}],
        }
        service.save_task("browser_task", config)
        task = service.get_task("browser_task")
        assert task is not None
        assert task["type"] == "browser"
        assert task["name"] == "浏览器任务"
