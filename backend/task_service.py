from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from src.task_executor import TaskManager, is_valid_task_id, normalize_task_id
from src.utils.logging import get_logger

task_logger = get_logger("backend.task_service", side="BACKEND")

# 危险步骤类型：包含任意 JS 执行
_DANGEROUS_STEP_TYPES = {"eval", "custom_js"}

# 任务来源标记
_TASK_SOURCE_BUILTIN = "builtin"
_TASK_SOURCE_SIGNED = "signed"
_TASK_SOURCE_API = "api"


def _check_dangerous_steps(task_data: dict[str, Any]) -> list[dict[str, Any]]:
    """检查任务中的危险步骤，返回详细信息列表（含代码内容）"""
    warnings = []
    steps = task_data.get("steps", [])
    for i, step in enumerate(steps):
        step_type = step.get("type", "")
        if step_type in _DANGEROUS_STEP_TYPES:
            desc = step.get("description", step.get("id", f"步骤{i+1}"))
            extra = step.get("extra", {})
            code = step.get("script") or extra.get("script") or ""
            warnings.append({
                "step_index": i + 1,
                "step_type": step_type,
                "description": desc,
                "code": str(code)[:2000],
            })
    return warnings


class TaskService:
    def __init__(self, project_root: Path):
        self.task_manager = TaskManager(project_root / "tasks")

    def _is_valid_task_id(self, task_id: str) -> bool:
        return is_valid_task_id(task_id)

    def list_tasks(self) -> list[dict[str, str]]:
        task_logger.debug("Listing tasks")
        return self.task_manager.list_tasks()

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        task_id = normalize_task_id(task_id)
        if not self._is_valid_task_id(task_id):
            return None
        task_logger.debug("Loading task %s", task_id)
        task = self.task_manager.load_task(task_id)
        if task:
            result = task.to_dict()
            result["id"] = task_id
            return result
        return None

    def save_task(self, task_id: str, config: dict[str, Any]) -> tuple[bool, str]:
        task_id = normalize_task_id(task_id)
        if not self._is_valid_task_id(task_id):
            return False, "任务ID只能包含字母、数字和下划线"

        if not config.get("name"):
            return False, "任务名称不能为空"

        if not config.get("steps"):
            return False, "至少需要一个执行步骤"

        # 如果已有同名任务且来源是 builtin/signed，保留原来源
        existing = self.task_manager.load_task(task_id)
        if existing and existing.source in (_TASK_SOURCE_BUILTIN, _TASK_SOURCE_SIGNED):
            config["source"] = existing.source
        elif "source" not in config:
            config["source"] = _TASK_SOURCE_API

        # 检查危险步骤并记录警告
        warnings = _check_dangerous_steps(config)
        for w in warnings:
            task_logger.warning("Task %s: %s", task_id, w)

        success = self.task_manager.save_task(task_id, config)
        if success:
            task_logger.info("Task saved: %s", task_id)
            return True, "任务保存成功"
        task_logger.error("Task save failed: %s", task_id)
        return False, "任务保存失败"

    def delete_task(self, task_id: str) -> tuple[bool, str]:
        task_id = normalize_task_id(task_id)
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
        task_id = normalize_task_id(task_id)
        if not self._is_valid_task_id(task_id):
            return False, "任务ID只能包含字母、数字和下划线"

        if not self.task_manager.load_task(task_id):
            return False, "任务不存在"

        success = self.task_manager.set_active_task(task_id)
        if success:
            task_logger.info("Active task set: %s", task_id)
            return True, "活动任务已设置"
        task_logger.error("Set active task failed: %s", task_id)
        return False, "设置活动任务失败"
