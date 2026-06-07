from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.tasks import TaskManager, ScriptTaskInfo, is_valid_task_id, normalize_task_id
from app.utils.logging import get_logger

task_logger = get_logger("backend.task_service", side="BACKEND")

# 危险步骤类型：包含任意 JS 执行
_DANGEROUS_STEP_TYPES = {"eval", "custom_js"}

# 任务 ID 校验失败的统一错误消息
_INVALID_TASK_ID_MSG = "任务ID必须以字母开头，且只能包含字母、数字和下划线"


def _check_dangerous_steps(task_data: dict[str, Any]) -> list[dict[str, Any]]:
    """检查任务中的危险步骤，返回详细信息列表（含代码内容）"""
    warnings = []
    steps = task_data.get("steps", [])
    for i, step in enumerate(steps):
        if not isinstance(step, dict):
            continue
        step_type = step.get("type", "")
        if step_type in _DANGEROUS_STEP_TYPES:
            desc = step.get("description", step.get("id", f"步骤{i + 1}"))
            extra = step.get("extra", {})
            code = (
                step.get("script")
                or step.get("code")
                or extra.get("script")
                or extra.get("code")
                or ""
            )
            warnings.append(
                {
                    "step_index": i + 1,
                    "step_type": step_type,
                    "description": desc,
                    "code": str(code)[:2000],
                }
            )
    return warnings


class TaskService:
    def __init__(self, project_root: Path):
        self.task_manager = TaskManager(project_root / "tasks")

    def _validate_task_id(self, task_id: str) -> str | None:
        """规范化并校验任务 ID，返回规范化后的 ID；无效则返回 None。"""
        task_id = normalize_task_id(task_id)
        if not is_valid_task_id(task_id):
            return None
        return task_id

    def list_tasks(self) -> list[dict[str, str]]:
        tasks = self.task_manager.list_tasks()
        task_logger.debug("列出任务: %d 个", len(tasks))
        return tasks

    def list_scripts(self) -> list[dict[str, str]]:
        """列出所有自定义脚本任务。"""
        tasks = self.task_manager.list_script_tasks()
        task_logger.debug("列出脚本任务: %d 个", len(tasks))
        return tasks

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        task_id = self._validate_task_id(task_id) or ""
        if not task_id:
            return None
        task_logger.debug("Loading task %s", task_id)
        task = self.task_manager.load_task(task_id)
        if task is None:
            return None
        if isinstance(task, ScriptTaskInfo):
            # 读取脚本内容
            content = ""
            if task.script_path.suffix.lower() == ".json":
                # JSON 格式：从 content 字段读取
                try:
                    data = json.loads(task.script_path.read_text(encoding="utf-8"))
                    content = data.get("content", "")
                except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                    task_logger.error("读取脚本 JSON 失败 %s: %s", task.script_path, exc)
                    return None
            else:
                # .py 文件：直接读取
                try:
                    content = task.script_path.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError) as exc:
                    task_logger.error("读取脚本文件失败 %s: %s", task.script_path, exc)
                    return None
            return {
                "id": task_id,
                "name": task.name,
                "description": task.description,
                "type": "script",
                "content": content,
                "binary_path": task.binary_path,
            }
        result = task.to_dict()
        result["id"] = task_id
        result["type"] = "browser"
        # 附加原始文件内容供编辑器使用
        try:
            json_path = self.task_manager._safe_json_path(task_id, task_type="browser")
            if json_path and json_path.exists():
                result["raw_json"] = json.loads(json_path.read_text(encoding="utf-8"))
        except Exception:
            task_logger.warning("读取任务原始 JSON 失败 (task_id=%s)", task_id, exc_info=True)
        return result

    def save_task(self, task_id: str, config: dict[str, Any]) -> tuple[bool, str]:
        task_id = self._validate_task_id(task_id) or ""
        if not task_id:
            return False, _INVALID_TASK_ID_MSG

        task_type = config.get("type", "browser")

        if task_type == "script":
            return self._save_script_task(task_id, config)

        # 浏览器任务
        if not config.get("name"):
            return False, "任务名称不能为空"
        if not config.get("steps"):
            return False, "至少需要一个执行步骤"

        # 检查危险步骤并记录警告
        warnings = _check_dangerous_steps(config)
        for w in warnings:
            task_logger.warning("Task %s: %s", task_id, w)

        success = self.task_manager.save_task(task_id, config)
        if success:
            task_logger.info("任务已保存: %s", task_id)
            return True, "任务保存成功"
        task_logger.error("任务保存失败: %s", task_id)
        return False, "任务保存失败"

    def _save_script_task(self, task_id: str, config: dict[str, Any]) -> tuple[bool, str]:
        """保存自定义脚本任务。"""
        content = config.get("content", "")
        if not content.strip():
            return False, "脚本内容不能为空"

        save_data = {
            "content": content,
            "name": config.get("name", ""),
            "description": config.get("description", ""),
            "binary_path": config.get("binary_path", ""),
        }
        success = self.task_manager.save_task(task_id, save_data, task_type="scripts")
        if success:
            task_logger.info("脚本任务已保存: %s", task_id)
            return True, "脚本任务保存成功"
        return False, "脚本任务保存失败"

    def delete_task(self, task_id: str) -> tuple[bool, str]:
        task_id = normalize_task_id(task_id)  # delete 不校验格式，仅规范化
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
        task_id = self._validate_task_id(task_id) or ""
        if not task_id:
            return False, _INVALID_TASK_ID_MSG

        if not self.task_manager.load_task(task_id):
            return False, "任务不存在"

        success = self.task_manager.set_active_task(task_id)
        if success:
            task_logger.info("Active task set: %s", task_id)
            return True, "活动任务已设置"
        task_logger.error("Set active task failed: %s", task_id)
        return False, "设置活动任务失败"

    def save_task_order(self, order: dict[str, list[str]]) -> tuple[bool, str]:
        """保存任务排序配置。"""
        if not isinstance(order, dict):
            return False, "排序数据格式无效"
        success = self.task_manager.save_order(order)
        if success:
            task_logger.info("任务排序已保存")
            return True, "排序保存成功"
        return False, "排序保存失败"
