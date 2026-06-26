"""自定义脚本路由 — 自定义脚本的 CRUD 和手动执行。"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, Depends, HTTPException, Request

from app.deps import get_task_manager
from app.schemas import ApiResponse, BinaryInfo, TaskSummary
from app.tasks import TaskManager
from app.utils.logging import get_logger
from app.workers.script_runner import ScriptRunner, detect_available_binaries

router = APIRouter()
api_logger = get_logger("api", source="backend")
_script_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="script_runner")


@router.get("/api/scripts", response_model=list[TaskSummary])
def list_scripts(
    task_mgr: TaskManager = Depends(get_task_manager),
) -> list[dict[str, str]]:
    """列出所有自定义脚本任务。"""
    return task_mgr.list_script_tasks()


@router.get("/api/scripts/binaries", response_model=list[BinaryInfo])
def list_binaries() -> list[BinaryInfo]:
    """获取系统可用的执行二进制列表。"""
    raw = detect_available_binaries()
    return [BinaryInfo(path=b.get("path", ""), name=b.get("name", "")) for b in raw]


@router.get("/api/scripts/{task_id}")
def get_script(
    task_id: str,
    task_mgr: TaskManager = Depends(get_task_manager),
) -> dict:
    """获取脚本任务详情（含脚本内容）。"""
    task = task_mgr.get_task_detail(task_id)
    if not task or task.get("type") != "script":
        raise HTTPException(status_code=404, detail="脚本任务不存在")
    return task


@router.put("/api/scripts/{task_id}", response_model=ApiResponse)
def save_script(
    task_id: str,
    payload: dict,
    task_mgr: TaskManager = Depends(get_task_manager),
) -> ApiResponse:
    """保存自定义脚本任务。"""
    payload["type"] = "script"
    ok, message = task_mgr.save_task_with_validation(task_id, payload)
    api_logger.info("保存脚本 {} -> success={}, message={}", task_id, ok, message)
    return ApiResponse(success=ok, message=message)


@router.delete("/api/scripts/{task_id}", response_model=ApiResponse)
def delete_script(
    task_id: str,
    task_mgr: TaskManager = Depends(get_task_manager),
) -> ApiResponse:
    """删除脚本任务。"""
    ok, message = task_mgr.delete_task_with_validation(task_id)
    api_logger.info("删除脚本 {} -> success={}, message={}", task_id, ok, message)
    return ApiResponse(success=ok, message=message)


@router.post("/api/scripts/{task_id}/run", response_model=ApiResponse)
async def run_script(
    request: Request,
    task_id: str,
    task_mgr: TaskManager = Depends(get_task_manager),
) -> ApiResponse:
    """手动执行脚本任务（测试用）。"""
    task = task_mgr.get_task_detail(task_id)
    if not task or task.get("type") != "script":
        raise HTTPException(status_code=404, detail="脚本任务不存在")

    # 通过 TaskManager 安全路径查找脚本文件
    script_path = task_mgr.get_script_path_public(task_id)
    if not script_path or not script_path.exists():
        return ApiResponse(success=False, message="脚本文件不存在")

    # 从配置读取脚本超时，默认 60 秒
    try:
        services = request.app.state.services
        timeout = services.engine.get_runtime_config().monitor.script_timeout
    except Exception:
        timeout = 60

    binary_path = task.get("binary_path", "")
    runner = ScriptRunner(script_path, timeout=timeout, binary_path=binary_path)

    loop = asyncio.get_running_loop()
    success, message = await loop.run_in_executor(_script_executor, runner.run)

    api_logger.info("运行脚本 {} -> success={}, message={}", task_id, success, message)
    return ApiResponse(success=success, message=message)
