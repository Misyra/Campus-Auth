"""定时任务路由 — 定时任务的 CRUD、手动执行和历史查询。"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from app.deps import get_monitor_service
from app.services.engine import ScheduleEngine
from app.schemas import ActionResponse, ScheduledTaskConfig
from app.utils.logging import get_logger

router = APIRouter()
api_logger = get_logger("api", source="backend")


@router.get("/api/scheduled-tasks")
def list_scheduled_tasks(
    engine: ScheduleEngine = Depends(get_monitor_service),
) -> list[dict[str, Any]]:
    """列出所有定时任务。"""
    return engine.tasks.list_tasks()


@router.post("/api/scheduled-tasks", response_model=ActionResponse)
def create_scheduled_task(
    payload: ScheduledTaskConfig,
    engine: ScheduleEngine = Depends(get_monitor_service),
) -> ActionResponse:
    """创建定时任务。"""

    task_id = f"task_{uuid.uuid4().hex[:12]}"
    config = payload.model_dump()
    ok, message = engine.tasks.save_task(task_id, config)
    api_logger.info("创建定时任务 {} -> success={}, message={}", task_id, ok, message)
    if ok:
        engine.sync_scheduler_state()
    return ActionResponse(success=ok, message=message)


@router.put("/api/scheduled-tasks/{task_id}", response_model=ActionResponse)
def update_scheduled_task(
    task_id: str,
    payload: dict,
    engine: ScheduleEngine = Depends(get_monitor_service),
) -> ActionResponse:
    """更新定时任务。"""

    existing = engine.tasks.get_task(task_id)
    if not existing:
        raise HTTPException(status_code=404, detail="定时任务不存在")

    merged = {**existing, **payload}
    if "schedule" in payload:
        merged["schedule"] = {**existing.get("schedule", {}), **payload["schedule"]}

    try:
        config_model = ScheduledTaskConfig.model_validate(merged)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e

    config = config_model.model_dump()
    config["last_run"] = existing.get("last_run")
    config["last_status"] = existing.get("last_status")

    ok, message = engine.tasks.save_task(task_id, config)
    if ok:
        engine.sync_scheduler_state()
    return ActionResponse(success=ok, message=message)


@router.delete("/api/scheduled-tasks/{task_id}", response_model=ActionResponse)
def delete_scheduled_task(
    task_id: str,
    engine: ScheduleEngine = Depends(get_monitor_service),
) -> ActionResponse:
    """删除定时任务。"""
    ok, message = engine.tasks.delete_task(task_id)
    api_logger.info("删除定时任务 {} -> success={}, message={}", task_id, ok, message)
    if ok:
        engine.sync_scheduler_state()
    return ActionResponse(success=ok, message=message)


@router.post("/api/scheduled-tasks/{task_id}/run", response_model=ActionResponse)
def run_scheduled_task(
    task_id: str,
    bg_tasks: BackgroundTasks,
    engine: ScheduleEngine = Depends(get_monitor_service),
) -> ActionResponse:
    """手动执行定时任务（异步后台执行，避免 HTTP 连接长时间阻塞）。"""
    if not engine.tasks.get_task(task_id):
        raise HTTPException(status_code=404, detail="定时任务不存在")

    # 后台执行，不阻塞 HTTP 响应
    async def _execute():
        try:
            success, message = await asyncio.to_thread(
                engine.tasks.execute_task, task_id
            )
            api_logger.info(
                "后台定时任务 {} -> success={}, message={}", task_id, success, message
            )
        except Exception as e:
            api_logger.error("后台定时任务执行异常 {}: {}", task_id, e, exc_info=True)

    bg_tasks.add_task(_execute)
    api_logger.info("定时任务 {} 已提交后台执行", task_id)
    return ActionResponse(
        success=True, message="任务已提交后台执行，请查看执行历史获取结果"
    )


@router.post("/api/scheduled-tasks/{task_id}/toggle", response_model=ActionResponse)
def toggle_scheduled_task(
    task_id: str,
    engine: ScheduleEngine = Depends(get_monitor_service),
) -> ActionResponse:
    """启用/禁用定时任务。"""
    task = engine.tasks.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="定时任务不存在")

    task = {**task, "enabled": not task.get("enabled", True)}
    ok, message = engine.tasks.save_task(task_id, task)
    status = "启用" if task["enabled"] else "禁用"
    api_logger.info("切换定时任务 {} -> {}", task_id, status)
    if ok:
        engine.sync_scheduler_state()
    return ActionResponse(success=ok, message=f"定时任务已{status}")


@router.get("/api/scheduled-tasks/{task_id}/history")
def get_scheduled_task_history(
    task_id: str,
    engine: ScheduleEngine = Depends(get_monitor_service),
) -> list[dict[str, Any]]:
    """获取定时任务执行历史。"""
    if not engine.tasks.get_task(task_id):
        raise HTTPException(status_code=404, detail="定时任务不存在")
    return engine.tasks.get_history(task_id)
