"""自定义脚本路由 — 自定义脚本的 CRUD 和手动执行。"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request

from app.deps import get_task_service
from app.schemas import ActionResponse
from app.services.task import TaskService
from app.utils.logging import get_logger
from app.workers.script_runner import ScriptRunner, detect_available_binaries

router = APIRouter()
api_logger = get_logger("backend.api", source="backend")


@router.get("/api/scripts")
def list_scripts(
    task_svc: TaskService = Depends(get_task_service),
) -> list[dict[str, str]]:
    """列出所有自定义脚本任务。"""
    return task_svc.list_scripts()


@router.get("/api/scripts/binaries")
def list_binaries() -> list[dict[str, str]]:
    """获取系统可用的执行二进制列表。"""
    return detect_available_binaries()


@router.get("/api/scripts/{task_id}")
def get_script(
    task_id: str,
    task_svc: TaskService = Depends(get_task_service),
) -> dict:
    """获取脚本任务详情（含脚本内容）。"""
    task = task_svc.get_task(task_id)
    if not task or task.get("type") != "script":
        raise HTTPException(status_code=404, detail="脚本任务不存在")
    return task


@router.put("/api/scripts/{task_id}", response_model=ActionResponse)
def save_script(
    task_id: str,
    payload: dict,
    task_svc: TaskService = Depends(get_task_service),
) -> ActionResponse:
    """保存自定义脚本任务。"""
    payload["type"] = "script"
    ok, message = task_svc.save_task(task_id, payload)
    api_logger.info("保存脚本 {} -> success={}, message={}", task_id, ok, message)
    return ActionResponse(success=ok, message=message)


@router.delete("/api/scripts/{task_id}", response_model=ActionResponse)
def delete_script(
    task_id: str,
    task_svc: TaskService = Depends(get_task_service),
) -> ActionResponse:
    """删除脚本任务。"""
    ok, message = task_svc.delete_task(task_id)
    api_logger.info("删除脚本 {} -> success={}, message={}", task_id, ok, message)
    return ActionResponse(success=ok, message=message)


@router.post("/api/scripts/{task_id}/run", response_model=ActionResponse)
async def run_script(
    request: Request,
    task_id: str,
    task_svc: TaskService = Depends(get_task_service),
) -> ActionResponse:
    """手动执行脚本任务（测试用）。"""
    task = task_svc.get_task(task_id)
    if not task or task.get("type") != "script":
        raise HTTPException(status_code=404, detail="脚本任务不存在")

    # 通过 TaskManager 安全路径查找脚本文件
    script_path = task_svc.get_script_path(task_id)
    if not script_path or not script_path.exists():
        return ActionResponse(success=False, message="脚本文件不存在")

    # 从配置读取脚本超时，默认 60 秒
    try:
        services = request.app.state.services
        timeout = (
            services.monitor_service.get_runtime_config()
            .get("monitor", {})
            .get("script_timeout", 60)
        )
    except Exception:
        timeout = 60

    binary_path = task.get("binary_path", "")
    runner = ScriptRunner(script_path, timeout=timeout, binary_path=binary_path)

    loop = asyncio.get_running_loop()
    success, message = await loop.run_in_executor(None, runner.run)

    api_logger.info("运行脚本 {} -> success={}, message={}", task_id, success, message)
    return ActionResponse(success=success, message=message)
