"""FastAPI 依赖注入 — Annotated 类型别名。"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from app.services.autostart import AutoStartService
from app.services.debug_service import DebugSessionManager
from app.services.engine import ScheduleEngine
from app.services.login_history_service import LoginHistoryService
from app.services.profile_service import ProfileService
from app.tasks import TaskManager


def _get(attr: str):
    """生成从 request.app.state.services 取属性的 Depends 工厂。"""

    def _dep(request: Request):
        return getattr(request.app.state.services, attr)

    return _dep


MonitorServiceDep = Annotated[ScheduleEngine, Depends(_get("engine"))]
ProfileServiceDep = Annotated[ProfileService, Depends(_get("profile_service"))]
TaskManagerDep = Annotated[TaskManager, Depends(_get("task_manager"))]
AutoStartServiceDep = Annotated[AutoStartService, Depends(_get("autostart_service"))]
DebugManagerDep = Annotated[DebugSessionManager, Depends(_get("debug_manager"))]
LoginHistoryDep = Annotated[LoginHistoryService, Depends(_get("login_history_service"))]
