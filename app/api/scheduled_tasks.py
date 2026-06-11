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


def _validate_schedule_payload(
    payload: dict,
    existing: dict | None = None,
    *,
    is_update: bool = False,
) -> tuple[bool, str, dict | None]:
    """验证定时任务 payload。

    Args:
        payload: 前端传入的任务配置
        existing: 已有任务配置（更新时传入，允许字段缺失）
        is_update: 是否为更新模式（更新时仅验证 payload 中显式传入的字段）

    Returns:
        (是否有效, 错误消息, 规范化后的配置字典)
    """

    def _get(key, default=None):
        if key in payload:
            return payload[key]
        if existing is not None:
            return existing.get(key, default)
        return default

    # ── 名称验证 ──
    name = _get("name", "")
    if (is_update and "name" in payload and not name) or (
        not is_update and not name
    ):
        return False, "任务名称不能为空", None

    # ── 类型验证 ──
    task_type = _get("type", "")
    if (is_update and "type" in payload or not is_update) and task_type not in (
        "script",
        "browser",
        "shell",
    ):
        return False, "无效的任务类型", None

    # ── 类型关联字段验证 ──
    if task_type == "shell" and not _get("command"):
        return False, "Shell 命令不能为空", None

    if task_type in ("script", "browser") and not _get("target_id"):
        return False, "请选择目标任务", None

    # ── 时间验证 ──
    schedule = _get("schedule", {})
    if (is_update and "schedule" in payload or not is_update) and (
        not isinstance(schedule.get("hour"), int)
        or not isinstance(schedule.get("minute"), int)
    ):
        return False, "请设置执行时间", None

    hour = schedule.get("hour", 0)
    minute = schedule.get("minute", 0)
    if (is_update and "schedule" in payload or not is_update) and not (
        0 <= hour <= 23 and 0 <= minute <= 59
    ):
        return False, "执行时间无效：小时须为 0-23，分钟须为 0-59", None

    # ── 超时验证 ──
    try:
        timeout = max(5, min(3600, int(_get("timeout", 60))))
    except (ValueError, TypeError):
        return False, "超时时间无效，须为 5 到 3600 之间的整数（秒）", None

    config = {
        "name": name,
        "description": _get("description", ""),
        "type": task_type,
        "target_id": _get("target_id", ""),
        "command": _get("command", ""),
        "shell_path": _get("shell_path", ""),
        "enabled": _get("enabled", True),
        "schedule": {"hour": hour, "minute": minute},
        "timeout": timeout,
    }

    if existing is not None:
        config["last_run"] = existing.get("last_run")
        config["last_status"] = existing.get("last_status")

    return True, "", config



@router.get("/api/scheduled-tasks")
def list_scheduled_tasks(request: Request) -> list[dict[str, Any]]:
    """列出所有定时任务。"""
    scheduler = get_scheduler_service(request)
    return scheduler.list_tasks()


@router.get("/api/scheduled-tasks/{task_id}")
def get_scheduled_task(task_id: str, request: Request) -> dict[str, Any]:
    """获取定时任务详情。"""
    scheduler = get_scheduler_service(request)
    task = scheduler.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="定时任务不存在")
    return task


@router.post("/api/scheduled-tasks", response_model=ActionResponse)
async def create_scheduled_task(payload: dict, request: Request) -> ActionResponse:
    """创建定时任务。"""
    scheduler = get_scheduler_service(request)

    # 自动生成唯一 ID
    task_id = f"task_{uuid.uuid4().hex[:12]}"

    # 验证并规范化配置
    valid, message, config = _validate_schedule_payload(payload, is_update=False)
    if not valid:
        return ActionResponse(success=False, message=message)

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
    scheduler = get_scheduler_service(request)

    existing = scheduler.get_task(task_id)
    if not existing:
        return ActionResponse(success=False, message="定时任务不存在")

    # 验证并规范化配置（更新模式：仅校验 payload 中显式传入的字段）
    valid, message, config = _validate_schedule_payload(
        payload, existing=existing, is_update=True
    )
    if not valid:
        return ActionResponse(success=False, message=message)

    ok, message = scheduler.save_task(task_id, config)
    api_logger.info("更新定时任务 {} -> success={}, message={}", task_id, ok, message)
    # 更新后任务启用时，确保调度器在运行
    if ok and config.get("enabled", True):
        scheduler.start_scheduler()
    return ActionResponse(success=ok, message=message)


@router.delete("/api/scheduled-tasks/{task_id}", response_model=ActionResponse)
def delete_scheduled_task(task_id: str, request: Request) -> ActionResponse:
    """删除定时任务。"""
    scheduler = get_scheduler_service(request)
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
    scheduler = get_scheduler_service(request)
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
    scheduler = get_scheduler_service(request)
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
    scheduler = get_scheduler_service(request)
    if not scheduler.get_task(task_id):
        raise HTTPException(status_code=404, detail="定时任务不存在")
    return scheduler.get_history(task_id)
