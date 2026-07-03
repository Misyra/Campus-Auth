"""TaskManager 常量一致性测试。"""

from __future__ import annotations

import json
from pathlib import Path

from app.tasks.manager import TaskManager, SCRIPT_TASK_TYPE


def _make_manager(tmp_path: Path) -> TaskManager:
    """在临时目录创建 TaskManager 实例。"""
    tasks_dir = tmp_path / "tasks"
    return TaskManager(tasks_dir)


# ── SCRIPT_TASK_TYPE 常量 ──


class TestScriptTaskTypeConstant:
    """SCRIPT_TASK_TYPE 常量值验证。"""

    def test_constant_value(self):
        """常量值为 'script'。"""
        assert SCRIPT_TASK_TYPE == "script"

    def test_save_task_with_validation_uses_constant(self):
        """save_task_with_validation 中的 task_type 比较使用常量。"""
        import inspect
        from app.tasks import manager

        source = inspect.getsource(manager.TaskManager.save_task_with_validation)
        # 确保源码中不包含硬编码的 "script" 字面量（而是使用常量）
        # 注意：source 中可能有 SCRIPT_TASK_TYPE 字符串，但不应有 == "script"
        assert '== "script"' not in source
        assert "SCRIPT_TASK_TYPE" in source

    def test_save_script_task_uses_constant(self):
        """_save_script_task 中的 type 字段使用常量。"""
        import inspect
        from app.tasks import manager

        source = inspect.getsource(manager.TaskManager._save_script_task)
        # 确保 save_data 字典中不包含硬编码的 "script" 字面量
        # 注意：可能有 type SCRIPT_TASK_TYPE 而非 type "script"
        assert '"type": "script"' not in source
        assert "SCRIPT_TASK_TYPE" in source


# ── save_task 与 save_task_with_validation 行为一致性 ──


class TestSaveTaskConsistency:
    """save_task 和 save_task_with_validation 的脚本任务保存行为一致。"""

    def test_save_task_script_type_saves_json(self, tmp_path):
        """save_task(task_type='scripts') 保存 JSON 文件到 scripts/ 目录。"""
        mgr = _make_manager(tmp_path)
        config = {
            "name": "test_script",
            "content": "print('hello')",
        }
        result = mgr.save_task("my_script", config, task_type="scripts")
        assert result is True
        script_file = mgr.scripts_dir / "my_script.json"
        assert script_file.exists()
        data = json.loads(script_file.read_text(encoding="utf-8"))
        assert data["type"] == SCRIPT_TASK_TYPE

    def test_save_task_with_validation_script_type(self, tmp_path):
        """save_task_with_validation 保存脚本任务到 scripts/ 目录。"""
        mgr = _make_manager(tmp_path)
        config = {
            "type": SCRIPT_TASK_TYPE,
            "name": "test_script",
            "content": "print('hello')",
        }
        success, msg = mgr.save_task_with_validation("val_script", config)
        assert success is True
        script_file = mgr.scripts_dir / "val_script.json"
        assert script_file.exists()
        data = json.loads(script_file.read_text(encoding="utf-8"))
        assert data["type"] == SCRIPT_TASK_TYPE

    def test_both_methods_save_to_same_location(self, tmp_path):
        """两种方法保存的脚本任务在同一位置。"""
        mgr = _make_manager(tmp_path)
        config_a = {"name": "shared", "content": "a = 1"}
        mgr.save_task("shared_id", config_a, task_type="scripts")
        path_a = mgr.scripts_dir / "shared_id.json"
        assert path_a.exists()

        config_b = {
            "type": SCRIPT_TASK_TYPE,
            "name": "shared",
            "content": "a = 1",
        }
        success, _ = mgr.save_task_with_validation("shared_id2", config_b)
        assert success is True
        path_b = mgr.scripts_dir / "shared_id2.json"
        assert path_b.exists()
