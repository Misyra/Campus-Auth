"""自定义脚本路由 — 自定义脚本的 CRUD 和手动执行。"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException

from app.deps import TaskExecutorDep, TaskManagerDep
from app.schemas import ApiResponse, TaskSummary
from app.utils.logging import get_logger

router = APIRouter()
api_logger = get_logger("api", source="backend")


@router.get("/api/scripts", response_model=list[TaskSummary])
def list_scripts(
    task_mgr: TaskManagerDep,
) -> list[dict[str, str]]:
    """列出所有自定义脚本任务。"""
    return task_mgr.list_script_tasks()


@router.get("/api/scripts/{task_id}")
def get_script(
    task_id: str,
    task_mgr: TaskManagerDep,
) -> dict:
    """获取脚本任务详情（含脚本内容）。"""
    task = task_mgr.get_task_detail(task_id)
    if not task or task.get("type") not in ("py", "bat", "ps1", "sh", "exe"):
        raise HTTPException(status_code=404, detail="脚本任务不存在")
    return task


@router.put("/api/scripts/{task_id}", response_model=ApiResponse)
def save_script(
    task_id: str,
    payload: dict,
    task_mgr: TaskManagerDep,
) -> ApiResponse:
    """保存自定义脚本任务。"""
    data = payload
    ok, message = task_mgr.save_task_with_validation(task_id, data)
    if ok:
        api_logger.info("保存脚本 {} 成功", task_id)
    else:
        api_logger.warning("保存脚本 {} 失败: {}", task_id, message)
    return ApiResponse(success=ok, message=message)


@router.delete("/api/scripts/{task_id}", response_model=ApiResponse)
def delete_script(
    task_id: str,
    task_mgr: TaskManagerDep,
) -> ApiResponse:
    """删除脚本任务。"""
    ok, message = task_mgr.delete_task_with_validation(task_id)
    if ok:
        api_logger.info("删除脚本 {} 成功", task_id)
    else:
        api_logger.warning("删除脚本 {} 失败: {}", task_id, message)
    return ApiResponse(success=ok, message=message)


@router.post("/api/scripts/{task_id}/run", response_model=ApiResponse)
async def run_script(
    task_id: str,
    task_mgr: TaskManagerDep,
    task_executor: TaskExecutorDep,
) -> ApiResponse:
    """手动执行脚本任务（测试用）。

    通过 TaskExecutor.run_script_on_demand 执行，超时由 ConfigService
    在 run_script_on_demand 内部读取。保留 task_mgr 仅用于 404 验证。
    """
    task = task_mgr.get_task_detail(task_id)
    if not task or task.get("type") not in ("py", "bat", "ps1", "sh", "exe"):
        raise HTTPException(status_code=404, detail="脚本任务不存在")

    success, message = await asyncio.to_thread(
        task_executor.run_script_on_demand, task_id
    )

    if success:
        api_logger.info("运行脚本 {} 成功", task_id)
    else:
        api_logger.warning("运行脚本 {} 失败: {}", task_id, message)
    return ApiResponse(success=success, message=message)
