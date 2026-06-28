"""FastAPI 依赖注入函数 — 保持路由签名简洁。"""

from __future__ import annotations

from fastapi import Request

from app.services.autostart import AutoStartService
from app.services.debug_service import DebugSessionManager
from app.services.engine import ScheduleEngine
from app.services.login_history_service import LoginHistoryService
from app.services.profile_service import ProfileService
from app.tasks import TaskManager


def get_monitor_service(request: Request) -> ScheduleEngine:
    return request.app.state.services.engine


def get_profile_service(request: Request) -> ProfileService:
    return request.app.state.services.profile_service


def get_task_manager(request: Request) -> TaskManager:
    return request.app.state.services.task_manager


def get_autostart_service(request: Request) -> AutoStartService:
    return request.app.state.services.autostart_service


def get_debug_manager(request: Request) -> DebugSessionManager:
    return request.app.state.services.debug_manager


def get_login_history_service(request: Request) -> LoginHistoryService:
    return request.app.state.services.login_history_service
