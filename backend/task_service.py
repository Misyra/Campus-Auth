from __future__ import annotations

from pathlib import Path
from typing import Any

from src.task_executor import TaskManager


class TaskService:
    def __init__(self, project_root: Path):
        self.task_manager = TaskManager(project_root / "tasks")

    def list_tasks(self) -> list[dict[str, str]]:
        return self.task_manager.list_tasks()

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        task = self.task_manager.load_task(task_id)
        if task:
            return {
                "id": task_id,
                "name": task.name,
                "description": task.description,
                "version": task.version,
                "url": task.url,
                "variables": task.variables,
                "timeout": task.timeout,
                "steps": task.steps,
                "success_conditions": task.success_conditions,
                "on_success": task.on_success,
                "on_failure": task.on_failure,
            }
        return None

    def save_task(self, task_id: str, config: dict[str, Any]) -> tuple[bool, str]:
        if not task_id or not task_id.isalnum() and "_" not in task_id:
            return False, "任务ID只能包含字母、数字和下划线"

        if not config.get("name"):
            return False, "任务名称不能为空"

        if not config.get("steps"):
            return False, "至少需要一个执行步骤"

        success = self.task_manager.save_task(task_id, config)
        if success:
            return True, "任务保存成功"
        return False, "任务保存失败"

    def delete_task(self, task_id: str) -> tuple[bool, str]:
        if task_id == "default":
            return False, "不能删除默认任务"

        success = self.task_manager.delete_task(task_id)
        if success:
            return True, "任务删除成功"
        return False, "任务删除失败"

    def get_active_task(self) -> str:
        return self.task_manager.get_active_task()

    def set_active_task(self, task_id: str) -> tuple[bool, str]:
        if not (self.task_manager.tasks_dir / f"{task_id}.json").exists():
            return False, "任务不存在"

        success = self.task_manager.set_active_task(task_id)
        if success:
            return True, "活动任务已设置"
        return False, "设置活动任务失败"
