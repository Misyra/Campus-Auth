from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from src.task_executor import TaskManager
from src.utils.logging import get_logger

task_logger = get_logger("backend.task_service", side="BACKEND")


class TaskService:
    def __init__(self, project_root: Path):
        self.task_manager = TaskManager(project_root / "tasks")

    def list_tasks(self) -> list[dict[str, str]]:
        task_logger.debug("Listing tasks")
        return self.task_manager.list_tasks()

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        task_logger.debug("Loading task %s", task_id)
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
        if not task_id or not re.fullmatch(r"[A-Za-z0-9_]+", task_id):
            return False, "任务ID只能包含字母、数字和下划线"

        if not config.get("name"):
            return False, "任务名称不能为空"

        if not config.get("steps"):
            return False, "至少需要一个执行步骤"

        success = self.task_manager.save_task(task_id, config)
        if success:
            task_logger.info("Task saved: %s", task_id)
            return True, "任务保存成功"
        task_logger.error("Task save failed: %s", task_id)
        return False, "任务保存失败"

    def delete_task(self, task_id: str) -> tuple[bool, str]:
        if task_id == "default":
            return False, "不能删除默认任务"

        success = self.task_manager.delete_task(task_id)
        if success:
            task_logger.info("Task deleted: %s", task_id)
            return True, "任务删除成功"
        task_logger.error("Task delete failed: %s", task_id)
        return False, "任务删除失败"

    def get_active_task(self) -> str:
        return self.task_manager.get_active_task()

    def set_active_task(self, task_id: str) -> tuple[bool, str]:
        if not (self.task_manager.tasks_dir / f"{task_id}.json").exists():
            return False, "任务不存在"

        success = self.task_manager.set_active_task(task_id)
        if success:
            task_logger.info("Active task set: %s", task_id)
            return True, "活动任务已设置"
        task_logger.error("Set active task failed: %s", task_id)
        return False, "设置活动任务失败"
