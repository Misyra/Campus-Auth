"""定时任务路由 — 定时任务的 CRUD、手动执行和历史查询。"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

from app.deps import get_scheduler_service
from app.schemas import ActionResponse
from app.utils.logging import get_logger

router = APIRouter()
api_logger = get_logger("api", source="backend")


def _get_scheduler(request: Request):
    """获取调度器服务实例。"""
    return get_scheduler_service(request)


@router.get("/api/scheduled-tasks")
def list_scheduled_tasks(request: Request) -> list[dict[str, Any]]:
    """列出所有定时任务。"""
    scheduler = _get_scheduler(request)
    return scheduler.list_tasks()


@router.get("/api/scheduled-tasks/{task_id}")
def get_scheduled_task(task_id: str, request: Request) -> dict[str, Any]:
    """获取定时任务详情。"""
    scheduler = _get_scheduler(request)
    task = scheduler.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="定时任务不存在")
    return task


@router.post("/api/scheduled-tasks", response_model=ActionResponse)
async def create_scheduled_task(payload: dict, request: Request) -> ActionResponse:
    """创建定时任务。"""
    scheduler = _get_scheduler(request)

    # 自动生成唯一 ID
    task_id = f"task_{uuid.uuid4().hex[:12]}"

    # 验证必填字段
    if not payload.get("name"):
        return ActionResponse(success=False, message="任务名称不能为空")

    task_type = payload.get("type", "")
    if task_type not in ("script", "browser", "shell"):
        return ActionResponse(success=False, message="无效的任务类型")

    if task_type == "shell" and not payload.get("command"):
        return ActionResponse(success=False, message="Shell 命令不能为空")

    if task_type in ("script", "browser") and not payload.get("target_id"):
        return ActionResponse(success=False, message="请选择目标任务")

    schedule = payload.get("schedule", {})
    if not isinstance(schedule.get("hour"), int) or not isinstance(
        schedule.get("minute"), int
    ):
        return ActionResponse(success=False, message="请设置执行时间")

    hour, minute = schedule["hour"], schedule["minute"]
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return ActionResponse(success=False, message="执行时间无效：小时须为 0-23，分钟须为 0-59")

    try:
        timeout = max(5, min(3600, int(payload.get("timeout", 60))))
    except (ValueError, TypeError):
        return ActionResponse(success=False, message="超时时间无效，须为 5 到 3600 之间的整数（秒）")

    # 构建任务配置
    config = {
        "name": payload.get("name", ""),
        "description": payload.get("description", ""),
        "type": task_type,
        "target_id": payload.get("target_id", ""),
        "command": payload.get("command", ""),
        "shell_path": payload.get("shell_path", ""),
        "enabled": payload.get("enabled", True),
        "schedule": {
            "hour": hour,
            "minute": minute,
        },
        "timeout": timeout,
    }

    ok, message = scheduler.save_task(task_id, config)
    api_logger.info("创建定时任务 {} -> success={}, message={}", task_id, ok, message)
    # 新建任务默认启用，确保调度器在运行
    if ok and config.get("enabled", True):
        scheduler.start_scheduler()
    return ActionResponse(success=ok, message=message)


@router.put("/api/scheduled-tasks/{task_id}", response_model=ActionResponse)
async def update_scheduled_task(
    task_id: str, payload: dict, request: Request
) -> ActionResponse:
    """更新定时任务。"""
    scheduler = _get_scheduler(request)

    existing = scheduler.get_task(task_id)
    if not existing:
        return ActionResponse(success=False, message="定时任务不存在")

    # 验证字段
    if "name" in payload and not payload["name"]:
        return ActionResponse(success=False, message="任务名称不能为空")

    task_type = payload.get("type", existing.get("type"))
    if "type" in payload and task_type not in ("script", "browser", "shell"):
        return ActionResponse(success=False, message="无效的任务类型")
    if task_type == "shell" and not payload.get("command", existing.get("command")):
        return ActionResponse(success=False, message="Shell 命令不能为空")

    schedule = payload.get("schedule", existing.get("schedule", {}))
    if "schedule" in payload and (
        not isinstance(schedule.get("hour"), int)
        or not isinstance(schedule.get("minute"), int)
    ):
        return ActionResponse(success=False, message="请设置执行时间")

    hour, minute = schedule.get("hour", 0), schedule.get("minute", 0)
    if "schedule" in payload and not (0 <= hour <= 23 and 0 <= minute <= 59):
        return ActionResponse(success=False, message="执行时间无效：小时须为 0-23，分钟须为 0-59")

    try:
        timeout = max(5, min(3600, int(payload.get("timeout", existing.get("timeout", 60)))))
    except (ValueError, TypeError):
        return ActionResponse(success=False, message="超时时间无效，须为 5 到 3600 之间的整数（秒）")

    # 更新配置
    config = {
        "name": payload.get("name", existing.get("name", "")),
        "description": payload.get("description", existing.get("description", "")),
        "type": task_type,
        "target_id": payload.get("target_id", existing.get("target_id", "")),
        "command": payload.get("command", existing.get("command", "")),
        "shell_path": payload.get("shell_path", existing.get("shell_path", "")),
        "enabled": payload.get("enabled", existing.get("enabled", True)),
        "schedule": {
            "hour": hour,
            "minute": minute,
        },
        "timeout": timeout,
        "last_run": existing.get("last_run"),
        "last_status": existing.get("last_status"),
    }

    ok, message = scheduler.save_task(task_id, config)
    api_logger.info("更新定时任务 {} -> success={}, message={}", task_id, ok, message)
    # 更新后任务启用时，确保调度器在运行
    if ok and config.get("enabled", True):
        scheduler.start_scheduler()
    return ActionResponse(success=ok, message=message)


@router.delete("/api/scheduled-tasks/{task_id}", response_model=ActionResponse)
def delete_scheduled_task(task_id: str, request: Request) -> ActionResponse:
    """删除定时任务。"""
    scheduler = _get_scheduler(request)
    ok, message = scheduler.delete_task(task_id)
    api_logger.info("删除定时任务 {} -> success={}, message={}", task_id, ok, message)
    return ActionResponse(success=ok, message=message)


@router.post("/api/scheduled-tasks/{task_id}/run", response_model=ActionResponse)
async def run_scheduled_task(
    task_id: str,
    request: Request,
    bg_tasks: BackgroundTasks,
) -> ActionResponse:
    """手动执行定时任务（异步后台执行，避免 HTTP 连接长时间阻塞）。"""
    scheduler = _get_scheduler(request)
    if not scheduler.get_task(task_id):
        return ActionResponse(success=False, message="定时任务不存在")

    # 后台执行，不阻塞 HTTP 响应
    async def _execute():
        try:
            success, message = await asyncio.to_thread(scheduler.execute_task, task_id)
            api_logger.info(
                "后台定时任务 {} -> success={}, message={}", task_id, success, message
            )
        except Exception as e:
            api_logger.error("后台定时任务执行异常 {}: {}", task_id, e, exc_info=True)

    bg_tasks.add_task(_execute)
    api_logger.info("定时任务 {} 已提交后台执行", task_id)
    return ActionResponse(success=True, message="任务已提交后台执行，请查看执行历史获取结果")


@router.post("/api/scheduled-tasks/{task_id}/toggle", response_model=ActionResponse)
async def toggle_scheduled_task(task_id: str, request: Request) -> ActionResponse:
    """启用/禁用定时任务。"""
    scheduler = _get_scheduler(request)
    task = scheduler.get_task(task_id)
    if not task:
        return ActionResponse(success=False, message="定时任务不存在")

    task["enabled"] = not task.get("enabled", True)
    ok, message = scheduler.save_task(task_id, task)
    status = "启用" if task["enabled"] else "禁用"
    api_logger.info("切换定时任务 {} -> {}", task_id, status)
    # 启用任务时确保调度器在运行
    if ok and task["enabled"]:
        scheduler.start_scheduler()
    return ActionResponse(success=ok, message=f"定时任务已{status}")


@router.get("/api/scheduled-tasks/{task_id}/history")
def get_scheduled_task_history(task_id: str, request: Request) -> list[dict[str, Any]]:
    """获取定时任务执行历史。"""
    scheduler = _get_scheduler(request)
    if not scheduler.get_task(task_id):
        raise HTTPException(status_code=404, detail="定时任务不存在")
    return scheduler.get_history(task_id)
