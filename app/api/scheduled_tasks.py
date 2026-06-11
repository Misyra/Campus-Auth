"""定时任务路由 — 定时任务的 CRUD、手动执行和历史查询。"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

from app.deps import get_monitor_service
from app.schemas import ActionResponse
from app.utils.logging import get_logger

router = APIRouter()
api_logger = get_logger("api", source="backend")


def _validate_create_payload(payload: dict) -> tuple[bool, str, dict | None]:
    """验证创建定时任务的 payload。

    Args:
        payload: 前端传入的任务配置，所有必填字段必须存在

    Returns:
        (是否有效, 错误消息, 规范化后的配置字典)
    """
    # ── 名称验证 ──
    name = payload.get("name", "")
    if not name:
        return False, "任务名称不能为空", None

    # ── 类型验证 ──
    task_type = payload.get("type", "")
    if task_type not in ("script", "browser", "shell"):
        return False, "无效的任务类型", None

    # ── 类型关联字段验证 ──
    if task_type == "shell" and not payload.get("command"):
        return False, "Shell 命令不能为空", None

    if task_type in ("script", "browser") and not payload.get("target_id"):
        return False, "请选择目标任务", None

    # ── 时间验证 ──
    schedule = payload.get("schedule", {})
    if (
        not isinstance(schedule.get("hour"), int)
        or not isinstance(schedule.get("minute"), int)
    ):
        return False, "请设置执行时间", None

    hour = schedule.get("hour", 0)
    minute = schedule.get("minute", 0)
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return False, "执行时间无效：小时须为 0-23，分钟须为 0-59", None

    # ── 超时验证 ──
    try:
        timeout = max(5, min(3600, int(payload.get("timeout", 60))))
    except (ValueError, TypeError):
        return False, "超时时间无效，须为 5 到 3600 之间的整数（秒）", None

    config = {
        "name": name,
        "description": payload.get("description", ""),
        "type": task_type,
        "target_id": payload.get("target_id", ""),
        "command": payload.get("command", ""),
        "shell_path": payload.get("shell_path", ""),
        "enabled": payload.get("enabled", True),
        "schedule": {"hour": hour, "minute": minute},
        "timeout": timeout,
    }

    return True, "", config


def _validate_update_payload(
    payload: dict, existing: dict
) -> tuple[bool, str, dict | None]:
    """验证更新定时任务的 payload。

    用 existing 填充 payload 的缺失字段后，调用 _validate_create_payload 做完整验证。

    Args:
        payload: 前端传入的更新字段（允许部分字段缺失）
        existing: 已有的任务配置

    Returns:
        (是否有效, 错误消息, 规范化后的配置字典)
    """
    # 合并：payload 优先，缺失字段从 existing 取
    merged = {**existing, **payload}

    # schedule 是嵌套字段，需要单独合并
    if "schedule" in payload:
        merged["schedule"] = {**existing.get("schedule", {}), **payload["schedule"]}

    # 保留历史记录字段
    merged["last_run"] = existing.get("last_run")
    merged["last_status"] = existing.get("last_status")

    return _validate_create_payload(merged)


@router.get("/api/scheduled-tasks")
def list_scheduled_tasks(request: Request) -> list[dict[str, Any]]:
    """列出所有定时任务。"""
    engine = get_monitor_service(request)
    return engine.tasks.list_tasks()


@router.get("/api/scheduled-tasks/{task_id}")
def get_scheduled_task(task_id: str, request: Request) -> dict[str, Any]:
    """获取定时任务详情。"""
    engine = get_monitor_service(request)
    task = engine.tasks.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="定时任务不存在")
    return task


@router.post("/api/scheduled-tasks", response_model=ActionResponse)
async def create_scheduled_task(payload: dict, request: Request) -> ActionResponse:
    """创建定时任务。"""
    engine = get_monitor_service(request)

    # 自动生成唯一 ID
    task_id = f"task_{uuid.uuid4().hex[:12]}"

    # 验证并规范化配置
    valid, message, config = _validate_create_payload(payload)
    if not valid:
        return ActionResponse(success=False, message=message)

    ok, message = engine.tasks.save_task(task_id, config)
    api_logger.info("创建定时任务 {} -> success={}, message={}", task_id, ok, message)
    # 新建任务默认启用，确保调度器在运行
    if ok and config.get("enabled", True):
        engine.start_scheduler()
    return ActionResponse(success=ok, message=message)


@router.put("/api/scheduled-tasks/{task_id}", response_model=ActionResponse)
async def update_scheduled_task(
    task_id: str, payload: dict, request: Request
) -> ActionResponse:
    """更新定时任务。"""
    engine = get_monitor_service(request)

    existing = engine.tasks.get_task(task_id)
    if not existing:
        return ActionResponse(success=False, message="定时任务不存在")

    # 验证并规范化配置（更新模式：payload 缺失字段从 existing 填充）
    valid, message, config = _validate_update_payload(payload, existing)
    if not valid:
        return ActionResponse(success=False, message=message)

    ok, message = engine.tasks.save_task(task_id, config)
    api_logger.info("更新定时任务 {} -> success={}, message={}", task_id, ok, message)
    # 更新后任务启用时，确保调度器在运行
    if ok and config.get("enabled", True):
        engine.start_scheduler()
    return ActionResponse(success=ok, message=message)


@router.delete("/api/scheduled-tasks/{task_id}", response_model=ActionResponse)
def delete_scheduled_task(task_id: str, request: Request) -> ActionResponse:
    """删除定时任务。"""
    engine = get_monitor_service(request)
    ok, message = engine.tasks.delete_task(task_id)
    api_logger.info("删除定时任务 {} -> success={}, message={}", task_id, ok, message)
    return ActionResponse(success=ok, message=message)


@router.post("/api/scheduled-tasks/{task_id}/run", response_model=ActionResponse)
async def run_scheduled_task(
    task_id: str,
    request: Request,
    bg_tasks: BackgroundTasks,
) -> ActionResponse:
    """手动执行定时任务（异步后台执行，避免 HTTP 连接长时间阻塞）。"""
    engine = get_monitor_service(request)
    if not engine.tasks.get_task(task_id):
        return ActionResponse(success=False, message="定时任务不存在")

    # 后台执行，不阻塞 HTTP 响应
    async def _execute():
        try:
            success, message = await asyncio.to_thread(engine.tasks.execute_task, task_id)
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
async def toggle_scheduled_task(task_id: str, request: Request) -> ActionResponse:
    """启用/禁用定时任务。"""
    engine = get_monitor_service(request)
    task = engine.tasks.get_task(task_id)
    if not task:
        return ActionResponse(success=False, message="定时任务不存在")

    task["enabled"] = not task.get("enabled", True)
    ok, message = engine.tasks.save_task(task_id, task)
    status = "启用" if task["enabled"] else "禁用"
    api_logger.info("切换定时任务 {} -> {}", task_id, status)
    # 启用任务时确保调度器在运行
    if ok and task["enabled"]:
        engine.start_scheduler()
    return ActionResponse(success=ok, message=f"定时任务已{status}")


@router.get("/api/scheduled-tasks/{task_id}/history")
def get_scheduled_task_history(task_id: str, request: Request) -> list[dict[str, Any]]:
    """获取定时任务执行历史。"""
    engine = get_monitor_service(request)
    if not engine.tasks.get_task(task_id):
        raise HTTPException(status_code=404, detail="定时任务不存在")
    return engine.tasks.get_history(task_id)
