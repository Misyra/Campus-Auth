"""定时任务路由 — 定时任务的 CRUD、手动执行和历史查询。"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException

from app.deps import MonitorServiceDep, TaskExecutorDep
from app.schemas import ApiResponse, ScheduledTaskConfig
from app.utils.logging import get_logger

router = APIRouter()
api_logger = get_logger("api", source="backend")


@router.get("/api/scheduled-tasks", response_model=list[dict[str, Any]])
def list_scheduled_tasks(
    task_executor: TaskExecutorDep,
) -> list[dict[str, Any]]:
    """列出所有定时任务。"""
    return task_executor.registry.list_tasks()


@router.post("/api/scheduled-tasks", response_model=ApiResponse)
def create_scheduled_task(
    payload: ScheduledTaskConfig,
    engine: MonitorServiceDep,
    task_executor: TaskExecutorDep,
) -> ApiResponse:
    """创建定时任务。"""

    task_id = f"task_{uuid.uuid4().hex[:12]}"
    config = payload.model_dump()
    ok, message = task_executor.registry.save_task(task_id, config)
    if ok:
        api_logger.info("创建定时任务 {} 成功", task_id)
    else:
        api_logger.warning("创建定时任务 {} 失败: {}", task_id, message)
    if ok:
        engine.sync_scheduler_state()
    return ApiResponse(success=ok, message=message)


@router.put("/api/scheduled-tasks/{task_id}", response_model=ApiResponse)
def update_scheduled_task(
    task_id: str,
    payload: dict,
    engine: MonitorServiceDep,
    task_executor: TaskExecutorDep,
) -> ApiResponse:
    """更新定时任务。"""

    existing = task_executor.registry.get_task(task_id)
    if not existing:
        raise HTTPException(status_code=404, detail="定时任务不存在")

    merged = {**existing}
    for k, v in payload.items():
        if isinstance(v, dict) and isinstance(merged.get(k), dict):
            merged[k] = {**merged[k], **v}
        else:
            merged[k] = v
    try:
        config_model = ScheduledTaskConfig.model_validate(merged)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e

    config = config_model.model_dump()
    config["last_run"] = existing.get("last_run")
    config["last_status"] = existing.get("last_status")

    ok, message = task_executor.registry.save_task(task_id, config)
    if ok:
        api_logger.info("更新定时任务 {} 成功", task_id)
    else:
        api_logger.warning("更新定时任务 {} 失败: {}", task_id, message)
    if ok:
        engine.sync_scheduler_state()
    return ApiResponse(success=ok, message=message)


@router.delete("/api/scheduled-tasks/{task_id}", response_model=ApiResponse)
def delete_scheduled_task(
    task_id: str,
    engine: MonitorServiceDep,
    task_executor: TaskExecutorDep,
) -> ApiResponse:
    """删除定时任务。"""
    ok, message = task_executor.delete_task(task_id)
    if ok:
        api_logger.info("删除定时任务 {} 成功", task_id)
    else:
        api_logger.warning("删除定时任务 {} 失败: {}", task_id, message)
    if ok:
        engine.sync_scheduler_state()
    return ApiResponse(success=ok, message=message)


@router.post("/api/scheduled-tasks/{task_id}/run", response_model=ApiResponse)
def run_scheduled_task(
    task_id: str,
    bg_tasks: BackgroundTasks,
    task_executor: TaskExecutorDep,
) -> ApiResponse:
    """手动执行定时任务（异步后台执行，避免 HTTP 连接长时间阻塞）。"""
    if not task_executor.registry.get_task(task_id):
        raise HTTPException(status_code=404, detail="定时任务不存在")

    # 后台执行，不阻塞 HTTP 响应
    async def _execute():
        try:
            success, message = await asyncio.to_thread(
                task_executor.execute_task, task_id
            )
            if success:
                api_logger.info("执行定时任务 {} 成功", task_id)
            else:
                api_logger.warning("执行定时任务 {} 失败: {}", task_id, message)
        except Exception:
            api_logger.error("执行定时任务 {} 异常", task_id, exc_info=True)

    bg_tasks.add_task(_execute)
    api_logger.info("定时任务 {} 已提交后台执行", task_id)
    return ApiResponse(
        success=True, message="任务已提交后台执行，请查看执行历史获取结果"
    )


@router.post("/api/scheduled-tasks/{task_id}/toggle", response_model=ApiResponse)
def toggle_scheduled_task(
    task_id: str,
    engine: MonitorServiceDep,
    task_executor: TaskExecutorDep,
) -> ApiResponse:
    """启用/禁用定时任务。"""
    task = task_executor.registry.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="定时任务不存在")

    task = {**task, "enabled": not task.get("enabled", True)}
    ok, message = task_executor.registry.save_task(task_id, task)
    status = "启用" if task["enabled"] else "禁用"
    if ok:
        api_logger.info("{}定时任务 {} 成功", status, task_id)
        engine.sync_scheduler_state()
    else:
        api_logger.warning("{}定时任务 {} 失败: {}", status, task_id, message)
    return ApiResponse(success=ok, message=f"定时任务已{status}")


@router.get(
    "/api/scheduled-tasks/{task_id}/history", response_model=list[dict[str, Any]]
)
def get_scheduled_task_history(
    task_id: str,
    task_executor: TaskExecutorDep,
) -> list[dict[str, Any]]:
    """获取定时任务执行历史。"""
    if not task_executor.registry.get_task(task_id):
        raise HTTPException(status_code=404, detail="定时任务不存在")
    return task_executor.history_store.get_history(task_id)
