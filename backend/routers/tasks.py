"""任务路由 — 任务的 CRUD、活动任务管理。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from src.utils.logging import get_logger

from ..deps import get_task_service
from ..schemas import ActionResponse
from ..task_service import TaskService

router = APIRouter()
api_logger = get_logger("backend.api", side="BACKEND")


@router.get("/api/tasks")
def list_tasks(
    task_svc: TaskService = Depends(get_task_service),
) -> list[dict[str, str]]:
    return task_svc.list_tasks()


@router.get("/api/tasks/active")
def get_active_task(
    task_svc: TaskService = Depends(get_task_service),
) -> dict[str, str]:
    return {"task_id": task_svc.get_active_task()}


@router.get("/api/tasks/{task_id}")
def get_task(
    task_id: str,
    task_svc: TaskService = Depends(get_task_service),
) -> dict:
    task = task_svc.get_task(task_id)
    if task:
        return task
    raise HTTPException(status_code=404, detail="任务不存在")


@router.put("/api/tasks/{task_id}", response_model=ActionResponse)
def save_task(
    task_id: str,
    payload: dict,
    task_svc: TaskService = Depends(get_task_service),
) -> ActionResponse:
    ok, message = task_svc.save_task(task_id, payload)
    api_logger.info("Save task %s -> success=%s, message=%s", task_id, ok, message)
    return ActionResponse(success=ok, message=message)


@router.delete("/api/tasks/{task_id}", response_model=ActionResponse)
def delete_task(
    task_id: str,
    task_svc: TaskService = Depends(get_task_service),
) -> ActionResponse:
    ok, message = task_svc.delete_task(task_id)
    api_logger.info("Delete task %s -> success=%s, message=%s", task_id, ok, message)
    return ActionResponse(success=ok, message=message)


@router.post("/api/tasks/active/{task_id}", response_model=ActionResponse)
def set_active_task(
    task_id: str,
    task_svc: TaskService = Depends(get_task_service),
) -> ActionResponse:
    ok, message = task_svc.set_active_task(task_id)
    api_logger.info(
        "Set active task %s -> success=%s, message=%s", task_id, ok, message
    )
    return ActionResponse(success=ok, message=message)
