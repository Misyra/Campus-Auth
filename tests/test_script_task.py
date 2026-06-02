"""脚本任务功能测试

测试 ScriptTaskInfo、TaskManager 脚本扫描、ScriptRunner 执行。
"""

import json
import textwrap
from pathlib import Path

import pytest

from src.script_runner import ScriptRunner, _build_minimal_env
from src.task_executor import ScriptTaskInfo, TaskManager


# ==================== TaskManager 脚本扫描 ====================


class TestTaskManagerScriptScan:
    """TaskManager 对 .py 文件的扫描和加载"""

    def test_list_tasks_includes_script(self, tmp_path: Path):
        """list_tasks 应同时返回 .json 和 .py 任务，含 type 字段"""
        # 创建 .json 任务
        (tmp_path / "browser_task.json").write_text(
            json.dumps({"name": "浏览器任务", "steps": [{"id": "s1", "type": "input", "selector": "#x"}]}),
            encoding="utf-8",
        )
        # 创建 .py 脚本
        (tmp_path / "my_script.py").write_text(
            '# name: 我的脚本\n# description: 测试\nprint("hello")',
            encoding="utf-8",
        )

        tm = TaskManager(tmp_path)
        tasks = tm.list_tasks()

        ids = {t["id"] for t in tasks}
        assert "browser_task" in ids
        assert "my_script" in ids

        browser = next(t for t in tasks if t["id"] == "browser_task")
        script = next(t for t in tasks if t["id"] == "my_script")

        assert browser["type"] == "browser"
        assert script["type"] == "script"

    def test_list_tasks_deduplication(self, tmp_path: Path):
        """同名 .json 和 .py 只出现一次（.json 优先）"""
        (tmp_path / "foo.json").write_text(
            json.dumps({"name": "Foo JSON", "steps": [{"id": "s1", "type": "input", "selector": "#x"}]}),
            encoding="utf-8",
        )
        (tmp_path / "foo.py").write_text('print("hello")', encoding="utf-8")

        tm = TaskManager(tmp_path)
        tasks = tm.list_tasks()

        foo_tasks = [t for t in tasks if t["id"] == "foo"]
        assert len(foo_tasks) == 1
        assert foo_tasks[0]["type"] == "browser"

    def test_list_script_tasks_only_py(self, tmp_path: Path):
        """list_script_tasks 只返回 .py 任务"""
        (tmp_path / "a.json").write_text(
            json.dumps({"name": "A", "steps": [{"id": "s1", "type": "input", "selector": "#x"}]}),
            encoding="utf-8",
        )
        (tmp_path / "b.py").write_text('print("b")', encoding="utf-8")

        tm = TaskManager(tmp_path)
        scripts = tm.list_script_tasks()

        assert len(scripts) == 1
        assert scripts[0]["id"] == "b"

    def test_load_script_task(self, tmp_path: Path):
        """load_task 对 .py 文件返回 ScriptTaskInfo"""
        (tmp_path / "login.py").write_text(
            '# name: 登录脚本\n# description: HTTP 登录\nprint("ok")',
            encoding="utf-8",
        )

        tm = TaskManager(tmp_path)
        task = tm.load_task("login")

        assert isinstance(task, ScriptTaskInfo)
        assert task.task_id == "login"
        assert task.name == "登录脚本"
        assert task.description == "HTTP 登录"
        assert task.script_path == tmp_path / "login.py"

    def test_load_script_metadata_from_docstring(self, tmp_path: Path):
        """没有 # name 注释时，从 docstring 提取名称"""
        (tmp_path / "test.py").write_text(
            '"""校园网自动登录"""\nimport os\n',
            encoding="utf-8",
        )

        tm = TaskManager(tmp_path)
        task = tm.load_task("test")

        assert isinstance(task, ScriptTaskInfo)
        assert task.name == "校园网自动登录"

    def test_load_script_metadata_fallback_to_stem(self, tmp_path: Path):
        """没有注释和 docstring 时，使用文件名"""
        (tmp_path / "my_task.py").write_text('print("hi")', encoding="utf-8")

        tm = TaskManager(tmp_path)
        task = tm.load_task("my_task")

        assert isinstance(task, ScriptTaskInfo)
        assert task.name == "my_task"


class TestTaskManagerScriptCRUD:
    """TaskManager 脚本任务的增删改"""

    def test_save_script_task(self, tmp_path: Path):
        """save_task task_type='script' 写入 .py 文件"""
        tm = TaskManager(tmp_path)

        ok = tm.save_task("test", {"content": 'print("hello")'}, task_type="script")
        assert ok is True
        assert (tmp_path / "test.py").exists()
        assert (tmp_path / "test.py").read_text(encoding="utf-8") == 'print("hello")'

    def test_save_script_removes_conflict_json(self, tmp_path: Path):
        """保存脚本时删除同名 .json 文件"""
        (tmp_path / "dup.json").write_text(
            json.dumps({"name": "dup", "steps": [{"id": "s1", "type": "input", "selector": "#x"}]}),
            encoding="utf-8",
        )
        tm = TaskManager(tmp_path)
        tm.save_task("dup", {"content": 'print("dup")'}, task_type="script")

        assert not (tmp_path / "dup.json").exists()
        assert (tmp_path / "dup.py").exists()

    def test_save_browser_removes_conflict_py(self, tmp_path: Path):
        """保存浏览器任务时删除同名 .py 文件"""
        (tmp_path / "dup.py").write_text('print("dup")', encoding="utf-8")
        tm = TaskManager(tmp_path)
        tm.save_task("dup", {
            "name": "dup",
            "steps": [{"id": "s1", "type": "input", "selector": "#x"}],
        })

        assert not (tmp_path / "dup.py").exists()
        assert (tmp_path / "dup.json").exists()

    def test_save_script_empty_content_fails(self, tmp_path: Path):
        """空内容保存失败"""
        tm = TaskManager(tmp_path)
        ok = tm.save_task("test", {"content": ""}, task_type="script")
        assert ok is False
        ok = tm.save_task("test", {"content": "   \n  "}, task_type="script")
        assert ok is False

    def test_delete_task_removes_both(self, tmp_path: Path):
        """delete_task 同时删除 .json 和 .py"""
        (tmp_path / "x.json").write_text("{}", encoding="utf-8")
        (tmp_path / "x.py").write_text('print("x")', encoding="utf-8")

        tm = TaskManager(tmp_path)
        ok = tm.delete_task("x")

        assert ok is True
        assert not (tmp_path / "x.json").exists()
        assert not (tmp_path / "x.py").exists()

    def test_delete_nonexistent_returns_true(self, tmp_path: Path):
        """删除不存在的任务返回 True（无操作成功）"""
        tm = TaskManager(tmp_path)
        assert tm.delete_task("nonexistent") is True

    def test_delete_default_returns_false(self, tmp_path: Path):
        """default 任务不可删除"""
        tm = TaskManager(tmp_path)
        assert tm.delete_task("default") is False

    def test_set_active_task_script(self, tmp_path: Path):
        """set_active_task 支持 .py 脚本"""
        (tmp_path / "s.py").write_text('print("s")', encoding="utf-8")

        tm = TaskManager(tmp_path)
        ok = tm.set_active_task("s")

        assert ok is True
        assert tm.get_active_task() == "s"

    def test_set_active_task_nonexistent_fails(self, tmp_path: Path):
        """不存在的任务不能设为活动"""
        tm = TaskManager(tmp_path)
        assert tm.set_active_task("nope") is False


# ==================== ScriptRunner ====================


class TestScriptRunner:
    """ScriptRunner 子进程执行"""

    def test_run_success(self, tmp_path: Path):
        """脚本正常退出（exit 0）返回 True"""
        script = tmp_path / "ok.py"
        script.write_text('print("HTTP 200")\n', encoding="utf-8")

        runner = ScriptRunner(script, timeout=10)
        ok, msg = runner.run()

        assert ok is True
        assert "HTTP 200" in msg

    def test_run_failure(self, tmp_path: Path):
        """脚本非零退出返回 False"""
        script = tmp_path / "fail.py"
        script.write_text('import sys\nprint("连接超时")\nsys.exit(1)\n', encoding="utf-8")

        runner = ScriptRunner(script, timeout=10)
        ok, msg = runner.run()

        assert ok is False
        assert "连接超时" in msg

    def test_run_nonzero_exit_no_output(self, tmp_path: Path):
        """脚本非零退出且无输出时返回失败"""
        script = tmp_path / "crash.py"
        script.write_text('import sys\nsys.exit(1)\n', encoding="utf-8")

        runner = ScriptRunner(script, timeout=10)
        ok, msg = runner.run()

        assert ok is False
        assert "无输出" in msg

    def test_run_timeout(self, tmp_path: Path):
        """脚本超时返回失败"""
        script = tmp_path / "slow.py"
        script.write_text('import time\ntime.sleep(100)\n', encoding="utf-8")

        runner = ScriptRunner(script, timeout=1)
        ok, msg = runner.run()

        assert ok is False
        assert "超时" in msg

    def test_run_stdout_recorded(self, tmp_path: Path):
        """脚本 stdout 作为输出信息返回"""
        script = tmp_path / "text.py"
        script.write_text('print("all good")\n', encoding="utf-8")

        runner = ScriptRunner(script, timeout=10)
        ok, msg = runner.run()

        assert ok is True
        assert "all good" in msg

    def test_run_mixed_output(self, tmp_path: Path):
        """脚本多行 print 输出取全部"""
        script = tmp_path / "mixed.py"
        script.write_text(textwrap.dedent("""\
            print("调试信息")
            print("HTTP 200")
        """), encoding="utf-8")

        runner = ScriptRunner(script, timeout=10)
        ok, msg = runner.run()

        assert ok is True
        assert "调试信息" in msg
        assert "HTTP 200" in msg

    def test_env_isolation(self, tmp_path: Path):
        """子进程只接收最小系统环境变量，不继承宿主全部环境"""
        script = tmp_path / "isolated.py"
        script.write_text(textwrap.dedent("""\
            import os, json
            path = os.environ.get("PATH", "")
            has_path = bool(path)
            print(json.dumps({"success": has_path, "message": f"has_path={has_path}"}))
        """), encoding="utf-8")

        runner = ScriptRunner(script, timeout=10)
        ok, msg = runner.run()

        assert ok is True
        assert "has_path=True" in msg

    def test_build_minimal_env(self):
        """_build_minimal_env 只包含基本系统变量，不含业务变量"""
        env = _build_minimal_env()

        assert "PATH" in env
        assert "PYTHONIOENCODING" in env
        # 不应包含任何 CAMPUS_* 业务变量
        assert "CAMPUS_USERNAME" not in env
        assert "CAMPUS_PASSWORD" not in env
        assert "CAMPUS_URL" not in env
