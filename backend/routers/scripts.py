"""脚本任务路由 — 自定义 Python 脚本的 CRUD 和手动执行。"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request

from src.script_runner import ScriptRunner
from src.utils.env import build_login_env_vars
from src.utils.logging import get_logger

from ..deps import get_task_service
from ..schemas import ActionResponse
from ..task_service import TaskService

router = APIRouter()
api_logger = get_logger("backend.api", side="BACKEND")


@router.get("/api/scripts")
def list_scripts(
    task_svc: TaskService = Depends(get_task_service),
) -> list[dict[str, str]]:
    """列出所有 .py 脚本任务。"""
    return task_svc.list_scripts()


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
    """保存脚本任务。"""
    payload["type"] = "script"
    ok, message = task_svc.save_task(task_id, payload)
    api_logger.info("Save script %s -> success=%s, message=%s", task_id, ok, message)
    return ActionResponse(success=ok, message=message)


@router.delete("/api/scripts/{task_id}", response_model=ActionResponse)
def delete_script(
    task_id: str,
    task_svc: TaskService = Depends(get_task_service),
) -> ActionResponse:
    """删除脚本任务。"""
    ok, message = task_svc.delete_task(task_id)
    api_logger.info("Delete script %s -> success=%s, message=%s", task_id, ok, message)
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

    script_path = task_svc.task_manager.tasks_dir / f"{task_id}.py"
    if not script_path.exists():
        return ActionResponse(success=False, message="脚本文件不存在")

    # 从 monitor_service 获取运行时配置来构建环境变量
    try:
        services = request.app.state.services
        runtime_config = services.monitor_service.get_runtime_config()
        env_vars = build_login_env_vars(
            runtime_config, None, runtime_config.get("custom_variables", {})
        )
    except Exception as exc:
        api_logger.warning("获取运行时配置失败: %s", exc)
        return ActionResponse(success=False, message=f"获取配置失败: {exc}")

    # 从配置读取脚本超时，默认 60 秒
    try:
        timeout = runtime_config.get("monitor", {}).get("script_timeout", 60)
    except Exception:
        timeout = 60

    runner = ScriptRunner(script_path, timeout=timeout)

    # 在线程池中执行，避免阻塞事件循环
    loop = asyncio.get_running_loop()
    success, message = await loop.run_in_executor(None, runner.run, env_vars)

    api_logger.info("Run script %s -> success=%s, message=%s", task_id, success, message)
    return ActionResponse(success=success, message=message)
