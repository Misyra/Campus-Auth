"""TaskManager 单元测试 — 覆盖 get_script_path 及相关路径方法。"""

from __future__ import annotations

import json
from pathlib import Path

from app.tasks.manager import TaskManager


def _make_manager(tmp_path: Path) -> TaskManager:
    """在临时目录创建 TaskManager 实例。"""
    tasks_dir = tmp_path / "tasks"
    return TaskManager(tasks_dir)


# ── get_script_path ──


class TestGetScriptPath:
    """get_script_path 公共方法测试。"""

    def test_returns_json_when_exists(self, tmp_path):
        """scripts/ 下有 .json 文件时返回该路径。"""
        mgr = _make_manager(tmp_path)
        script_json = mgr.scripts_dir / "my_task.json"
        script_json.write_text(json.dumps({"name": "test"}), encoding="utf-8")

        result = mgr.get_script_path("my_task")
        assert result is not None
        assert result.name == "my_task.json"
        assert result.exists()


    def test_returns_path_when_not_exists(self, tmp_path):
        """脚本不存在时仍返回路径（指向 scripts/ 下的 .json）。"""
        mgr = _make_manager(tmp_path)
        result = mgr.get_script_path("nonexistent")
        assert result is not None
        assert result.name == "nonexistent.json"
        assert not result.exists()

    def test_invalid_id_returns_none(self, tmp_path):
        """无效 ID 返回 None。"""
        mgr = _make_manager(tmp_path)
        assert mgr.get_script_path("") is None
        assert mgr.get_script_path("../escape") is None
        assert mgr.get_script_path("a" * 65) is None  # 超过 64 字符上限

    def test_looks_in_scripts_dir_not_browser(self, tmp_path):
        """仅搜索 scripts/ 目录，不搜索 browser/。"""
        mgr = _make_manager(tmp_path)
        browser_json = mgr.browser_dir / "shared.json"
        browser_json.write_text("{}", encoding="utf-8")

        # browser/ 下有文件但 scripts/ 下没有
        result = mgr.get_script_path("shared")
        assert result is not None
        assert "browser" not in str(result)
        # 返回的是 scripts/ 下的路径（即使文件不存在）
        assert result.parent == mgr.scripts_dir


# ── _safe_task_path 仍可正常工作 ──


class TestSafeTaskPath:
    """确保公共方法未破坏私有方法的既有行为。"""

    def test_searches_all_dirs_by_default(self, tmp_path):
        """无 task_type 时搜索 browser + scripts。"""
        mgr = _make_manager(tmp_path)
        browser_json = mgr.browser_dir / "findme.json"
        browser_json.write_text("{}", encoding="utf-8")

        result = mgr._safe_task_path("findme")
        assert result is not None
        assert result.exists()
        assert result == browser_json.absolute()

    def test_scripts_type_returns_script_path(self, tmp_path):
        """task_type='scripts' 时仅搜索 scripts/。"""
        mgr = _make_manager(tmp_path)
        (mgr.scripts_dir / "s_task.json").write_text('{}', encoding="utf-8")

        result = mgr._safe_task_path("s_task", task_type="scripts")
        assert result is not None
        assert result.name == "s_task.json"
