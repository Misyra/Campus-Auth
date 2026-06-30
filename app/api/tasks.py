"""任务路由 — 任务的 CRUD、活动任务管理。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.deps import TaskManagerDep
from app.schemas import ApiResponse, TaskOrderRequest, TaskSummary
from app.utils.logging import get_logger

router = APIRouter()
api_logger = get_logger("api", source="backend")


@router.get("/api/tasks", response_model=list[TaskSummary])
def list_tasks(
    task_mgr: TaskManagerDep,
) -> list[dict[str, str]]:
    return task_mgr.list_tasks()


@router.get("/api/tasks/active")
def get_active_task(
    task_mgr: TaskManagerDep,
) -> dict[str, str]:
    return {"task_id": task_mgr.get_active_task()}


@router.get("/api/tasks/{task_id}")
def get_task(
    task_id: str,
    task_mgr: TaskManagerDep,
) -> dict:
    task = task_mgr.get_task_detail(task_id)
    if task:
        return task
    raise HTTPException(status_code=404, detail="任务不存在")


@router.put("/api/tasks/{task_id}", response_model=ApiResponse)
def save_task(
    task_id: str,
    payload: dict,
    task_mgr: TaskManagerDep,
) -> ApiResponse:
    ok, message = task_mgr.save_task_with_validation(task_id, payload)
    if ok:
        api_logger.info("保存任务 {} 成功", task_id)
    else:
        api_logger.warning("保存任务 {} 失败: {}", task_id, message)
    return ApiResponse(success=ok, message=message)


@router.delete("/api/tasks/{task_id}", response_model=ApiResponse)
def delete_task(
    task_id: str,
    task_mgr: TaskManagerDep,
) -> ApiResponse:
    ok, message = task_mgr.delete_task_with_validation(task_id)
    if ok:
        api_logger.info("删除任务 {} 成功", task_id)
    else:
        api_logger.warning("删除任务 {} 失败: {}", task_id, message)
    return ApiResponse(success=ok, message=message)


@router.post("/api/tasks/active/{task_id}", response_model=ApiResponse)
def set_active_task(
    task_id: str,
    task_mgr: TaskManagerDep,
) -> ApiResponse:
    ok, message = task_mgr.set_active_task_with_validation(task_id)
    if ok:
        api_logger.info("设置活动任务 {} 成功", task_id)
    else:
        api_logger.warning("设置活动任务 {} 失败: {}", task_id, message)
    return ApiResponse(success=ok, message=message)


@router.post("/api/tasks/order", response_model=ApiResponse)
def save_task_order(
    payload: TaskOrderRequest,
    task_mgr: TaskManagerDep,
) -> ApiResponse:
    ok, message = task_mgr.save_order_with_validation({"order": payload.order})
    if ok:
        api_logger.info("保存任务排序成功")
    else:
        api_logger.warning("保存任务排序失败: {}", message)
    return ApiResponse(success=ok, message=message)
