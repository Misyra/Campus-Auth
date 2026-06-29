"""脚本任务功能测试

测试 TaskManager 脚本扫描和 CRUD。
"""

import json
from pathlib import Path

from app.tasks.manager import TaskManager
from app.tasks.models import ScriptTaskInfo

# ==================== TaskManager 脚本扫描 ====================


class TestTaskManagerScriptScan:
    """TaskManager 对脚本文件的扫描和加载"""

    def test_list_tasks_separates_by_dir(self, tmp_path: Path):
        """list_tasks 只返回 browser/ 目录的任务，list_script_tasks 只返回 scripts/ 目录"""
        tm = TaskManager(tmp_path)
        # 浏览器任务在 browser/
        (tmp_path / "browser" / "browser_task.json").write_text(
            json.dumps(
                {
                    "name": "浏览器任务",
                    "steps": [{"id": "s1", "type": "input", "selector": "#x"}],
                }
            ),
            encoding="utf-8",
        )
        # 脚本在 scripts/
        (tmp_path / "scripts" / "my_script.json").write_text(
            json.dumps(
                {"type": "script", "name": "我的脚本", "content": 'print("hello")'}
            ),
            encoding="utf-8",
        )

        browser_tasks = tm.list_tasks()
        script_tasks = tm.list_script_tasks()

        assert len(browser_tasks) == 1
        assert browser_tasks[0]["id"] == "browser_task"
        assert len(script_tasks) == 1
        assert script_tasks[0]["id"] == "my_script"

    def test_list_script_tasks_json_and_py(self, tmp_path: Path):
        """list_script_tasks 同时返回 .json 和 .py 脚本"""
        tm = TaskManager(tmp_path)
        (tmp_path / "scripts" / "a.json").write_text(
            json.dumps({"type": "script", "name": "A", "content": 'print("a")'}),
            encoding="utf-8",
        )
        (tmp_path / "scripts" / "b.py").write_text('print("b")', encoding="utf-8")

        scripts = tm.list_script_tasks()

        ids = {s["id"] for s in scripts}
        assert "a" in ids
        assert "b" in ids

    def test_load_script_task(self, tmp_path: Path):
        """load_task 对 scripts/ 下的 .py 文件返回 ScriptTaskInfo"""
        tm = TaskManager(tmp_path)
        (tmp_path / "scripts" / "login.py").write_text(
            '# name: 登录脚本\n# description: HTTP 登录\nprint("ok")',
            encoding="utf-8",
        )

        task = tm.load_task("login")

        assert isinstance(task, ScriptTaskInfo)
        assert task.task_id == "login"
        assert task.name == "登录脚本"
        assert task.description == "HTTP 登录"
        assert task.script_path == tmp_path / "scripts" / "login.py"

    def test_load_script_metadata_from_docstring(self, tmp_path: Path):
        """没有 # name 注释时，从 docstring 提取名称"""
        tm = TaskManager(tmp_path)
        (tmp_path / "scripts" / "test.py").write_text(
            '"""校园网自动登录"""\nimport os\n',
            encoding="utf-8",
        )

        task = tm.load_task("test")

        assert isinstance(task, ScriptTaskInfo)
        assert task.name == "校园网自动登录"

    def test_load_script_metadata_fallback_to_stem(self, tmp_path: Path):
        """没有注释和 docstring 时，使用文件名"""
        tm = TaskManager(tmp_path)
        (tmp_path / "scripts" / "my_task.py").write_text(
            'print("hi")', encoding="utf-8"
        )

        task = tm.load_task("my_task")

        assert isinstance(task, ScriptTaskInfo)
        assert task.name == "my_task"


class TestTaskManagerScriptCRUD:
    """TaskManager 脚本任务的增删改"""

    def test_save_script_task(self, tmp_path: Path):
        """save_task task_type='script' 写入 scripts/ 子目录"""
        tm = TaskManager(tmp_path)

        ok = tm.save_task("test", {"content": 'print("hello")'}, task_type="scripts")
        assert ok is True
        script_file = tmp_path / "scripts" / "test.json"
        assert script_file.exists()
        data = json.loads(script_file.read_text(encoding="utf-8"))
        assert data["content"] == 'print("hello")'
        assert data["type"] == "script"

    def test_save_browser_and_script_independent(self, tmp_path: Path):
        """浏览器任务和脚本任务可以同名，分别存在不同子目录"""
        tm = TaskManager(tmp_path)
        tm.save_task(
            "dup",
            {
                "name": "浏览器 dup",
                "steps": [{"id": "s1", "type": "input", "selector": "#x"}],
            },
        )
        tm.save_task("dup", {"content": 'print("dup")'}, task_type="scripts")

        assert (tmp_path / "browser" / "dup.json").exists()
        assert (tmp_path / "scripts" / "dup.json").exists()

    def test_save_script_empty_content_fails(self, tmp_path: Path):
        """空内容保存失败"""
        tm = TaskManager(tmp_path)
        ok = tm.save_task("test", {"content": ""}, task_type="scripts")
        assert ok is False
        ok = tm.save_task("test", {"content": "   \n  "}, task_type="scripts")
        assert ok is False

    def test_delete_task_removes_from_both_dirs(self, tmp_path: Path):
        """delete_task 从两个子目录中删除"""
        tm = TaskManager(tmp_path)
        browser_dir = tmp_path / "browser"
        scripts_dir = tmp_path / "scripts"
        (browser_dir / "x.json").write_text("{}", encoding="utf-8")
        (scripts_dir / "x.json").write_text(
            '{"type":"script","content":"print()"}', encoding="utf-8"
        )

        ok = tm.delete_task("x")

        assert ok is True
        assert not (browser_dir / "x.json").exists()
        assert not (scripts_dir / "x.json").exists()

    def test_delete_nonexistent_returns_false(self, tmp_path: Path):
        """删除不存在的任务返回 False"""
        tm = TaskManager(tmp_path)
        assert tm.delete_task("nonexistent") is False

    def test_delete_default_returns_false(self, tmp_path: Path):
        """default 任务不可删除"""
        tm = TaskManager(tmp_path)
        assert tm.delete_task("default") is False

    def test_set_active_task_script(self, tmp_path: Path):
        """set_active_task 支持 scripts/ 下的脚本"""
        tm = TaskManager(tmp_path)
        (tmp_path / "scripts" / "s.json").write_text(
            '{"type":"script","content":"print()"}', encoding="utf-8"
        )

        ok = tm.set_active_task("s")

        assert ok is True
        assert tm.get_active_task() == "s"

    def test_set_active_task_nonexistent_fails(self, tmp_path: Path):
        """不存在的任务不能设为活动"""
        tm = TaskManager(tmp_path)
        assert tm.set_active_task("nope") is False
