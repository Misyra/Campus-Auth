"""TaskRegistry.get_tasks_dir() 与 TaskExecutor._get_script_path() 测试。

验证：
1. TaskRegistry 提供公共方法 get_tasks_dir()
2. TaskExecutor._get_script_path() 优先使用公共方法访问 tasks_dir
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from app.services.task_registry import TaskRegistry


class TestTaskRegistryGetTasksDir:
    """TaskRegistry.get_tasks_dir() 公共方法测试。"""

    def test_get_tasks_dir_returns_path(self, tmp_path: Path) -> None:
        """get_tasks_dir() 返回构造时传入的目录路径。"""
        tasks_dir = tmp_path / "tasks"
        reg = TaskRegistry(tasks_dir)
        assert reg.get_tasks_dir() == tasks_dir

    def test_get_tasks_dir_creates_dir(self, tmp_path: Path) -> None:
        """目录不存在时自动创建。"""
        tasks_dir = tmp_path / "new_tasks"
        reg = TaskRegistry(tasks_dir)
        assert reg.get_tasks_dir().exists()

    def test_get_tasks_dir_returns_same_as_private(self, tmp_path: Path) -> None:
        """公共方法返回值与私有属性一致。"""
        tasks_dir = tmp_path / "tasks"
        reg = TaskRegistry(tasks_dir)
        assert reg.get_tasks_dir() == reg._tasks_dir


class TestTaskExecutorGetScriptPath:
    """TaskExecutor._get_script_path() 使用公共方法的测试。"""

    def test_uses_public_method_first(self, tmp_path: Path) -> None:
        """优先使用 get_tasks_dir() 公共方法（当 get_script_path 不存在时）。"""
        tasks_dir = tmp_path / "tasks" / "scheduled"
        tasks_dir.mkdir(parents=True)
        scripts_dir = tmp_path / "tasks" / "scripts"
        scripts_dir.mkdir(parents=True)

        # 创建一个脚本文件
        script_file = scripts_dir / "test_script.json"
        script_file.write_text("{}")

        # 构造 mock registry，没有 get_script_path，有 get_tasks_dir
        mock_registry = MagicMock(spec=["get_tasks_dir"])
        mock_registry.get_tasks_dir.return_value = tasks_dir

        from app.services.task_executor import TaskExecutor

        executor = TaskExecutor.__new__(TaskExecutor)
        executor._registry = mock_registry

        result = executor._get_script_path("test_script")
        assert result == script_file

    def test_falls_back_to_private_attr(self, tmp_path: Path) -> None:
        """没有公共方法时回退到私有属性（兼容旧版本）。"""
        tasks_dir = tmp_path / "tasks" / "scheduled"
        tasks_dir.mkdir(parents=True)
        scripts_dir = tmp_path / "tasks" / "scripts"
        scripts_dir.mkdir(parents=True)

        script_file = scripts_dir / "test_script.json"
        script_file.write_text("{}")

        # 构造 mock registry，没有 get_script_path 也没有 get_tasks_dir，只有 _tasks_dir
        mock_registry = MagicMock(spec=[])
        mock_registry._tasks_dir = tasks_dir

        from app.services.task_executor import TaskExecutor

        executor = TaskExecutor.__new__(TaskExecutor)
        executor._registry = mock_registry

        result = executor._get_script_path("test_script")
        assert result == script_file

    def test_returns_none_when_no_dir_info(self) -> None:
        """没有目录信息时返回 None。"""
        mock_registry = MagicMock(spec=[])

        from app.services.task_executor import TaskExecutor

        executor = TaskExecutor.__new__(TaskExecutor)
        executor._registry = mock_registry

        result = executor._get_script_path("nonexistent")
        assert result is None
