"""FastAPI 依赖注入函数 — 保持路由签名简洁。"""

from __future__ import annotations

from fastapi import Request

from .autostart_service import AutoStartService
from .container import ServiceContainer
from .debug_manager import DebugSessionManager
from .login_history_service import LoginHistoryService
from .monitor_service import MonitorService
from .profile_service import ProfileService
from .task_service import TaskService


def get_services(request: Request) -> ServiceContainer:
    return request.app.state.services


def get_monitor_service(request: Request) -> MonitorService:
    return request.app.state.services.monitor_service


def get_profile_service(request: Request) -> ProfileService:
    return request.app.state.services.profile_service


def get_task_service(request: Request) -> TaskService:
    return request.app.state.services.task_service


def get_autostart_service(request: Request) -> AutoStartService:
    return request.app.state.services.autostart_service


def get_debug_manager(request: Request) -> DebugSessionManager:
    return request.app.state.services.debug_manager


def get_login_history_service(request: Request) -> LoginHistoryService:
    return request.app.state.services.login_history_service
