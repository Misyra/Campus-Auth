"""任务路由 — 任务的 CRUD、活动任务管理。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.deps import get_task_manager
from app.schemas import ActionResponse
from app.tasks import TaskManager
from app.utils.logging import get_logger

router = APIRouter()
api_logger = get_logger("api", source="backend")


@router.get("/api/tasks")
def list_tasks(
    task_mgr: TaskManager = Depends(get_task_manager),
) -> list[dict[str, str]]:
    return task_mgr.list_tasks()


@router.get("/api/tasks/active")
def get_active_task(
    task_mgr: TaskManager = Depends(get_task_manager),
) -> dict[str, str]:
    return {"task_id": task_mgr.get_active_task()}


@router.get("/api/tasks/{task_id}")
def get_task(
    task_id: str,
    task_mgr: TaskManager = Depends(get_task_manager),
) -> dict:
    task = task_mgr.get_task_detail(task_id)
    if task:
        return task
    raise HTTPException(status_code=404, detail="任务不存在")


@router.put("/api/tasks/{task_id}", response_model=ActionResponse)
def save_task(
    task_id: str,
    payload: dict,
    task_mgr: TaskManager = Depends(get_task_manager),
) -> ActionResponse:
    ok, message = task_mgr.save_task_with_validation(task_id, payload)
    api_logger.info("保存任务 {} -> success={}, message={}", task_id, ok, message)
    return ActionResponse(success=ok, message=message)


@router.delete("/api/tasks/{task_id}", response_model=ActionResponse)
def delete_task(
    task_id: str,
    task_mgr: TaskManager = Depends(get_task_manager),
) -> ActionResponse:
    ok, message = task_mgr.delete_task_with_validation(task_id)
    api_logger.info("删除任务 {} -> success={}, message={}", task_id, ok, message)
    return ActionResponse(success=ok, message=message)


@router.post("/api/tasks/active/{task_id}", response_model=ActionResponse)
def set_active_task(
    task_id: str,
    task_mgr: TaskManager = Depends(get_task_manager),
) -> ActionResponse:
    ok, message = task_mgr.set_active_task_with_validation(task_id)
    api_logger.info("设置活动任务 {} -> success={}, message={}", task_id, ok, message)
    return ActionResponse(success=ok, message=message)


@router.post("/api/tasks/order", response_model=ActionResponse)
def save_task_order(
    payload: dict,
    task_mgr: TaskManager = Depends(get_task_manager),
) -> ActionResponse:
    ok, message = task_mgr.save_order_with_validation(payload)
    api_logger.info("保存任务排序 -> success={}, message={}", ok, message)
    return ActionResponse(success=ok, message=message)
