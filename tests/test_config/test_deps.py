"""依赖注入测试 — app/deps.py

覆盖：_get 工厂函数从 request.app.state.services 正确提取服务实例
"""

from __future__ import annotations

from typing import get_args
from unittest.mock import MagicMock

import pytest

from app.deps import ConfigServiceDep, _get
from app.services.config_service import ConfigService


def _make_request(services) -> MagicMock:
    """构造一个携带 services 的 mock Request。"""
    request = MagicMock()
    request.app.state.services = services
    return request


@pytest.fixture
def services():
    """构造一组 mock services，覆盖所有 Dep 别名对应的属性。"""
    svc = MagicMock()
    svc.engine = MagicMock(name="ScheduleEngine")
    svc.profile_service = MagicMock(name="ProfileService")
    svc.task_manager = MagicMock(name="TaskManager")
    svc.autostart_service = MagicMock(name="AutoStartService")
    svc.debug_manager = MagicMock(name="DebugSessionManager")
    svc.login_history_service = MagicMock(name="LoginHistoryService")
    svc.config_service = MagicMock(name="ConfigService")
    return svc


# =====================================================================
# 依赖注入工厂函数
# =====================================================================


class TestDeps:
    def test_get_engine(self, services):
        request = _make_request(services)
        dep = _get("engine")
        assert dep(request) is services.engine

    def test_get_profile_service(self, services):
        request = _make_request(services)
        dep = _get("profile_service")
        assert dep(request) is services.profile_service

    def test_get_task_manager(self, services):
        request = _make_request(services)
        dep = _get("task_manager")
        assert dep(request) is services.task_manager

    def test_get_autostart_service(self, services):
        request = _make_request(services)
        dep = _get("autostart_service")
        assert dep(request) is services.autostart_service

    def test_get_debug_manager(self, services):
        request = _make_request(services)
        dep = _get("debug_manager")
        assert dep(request) is services.debug_manager

    def test_get_login_history_service(self, services):
        request = _make_request(services)
        dep = _get("login_history_service")
        assert dep(request) is services.login_history_service

    def test_get_config_service(self, services):
        """_get('config_service') 应从 services 取出 config_service 实例。"""
        request = _make_request(services)
        dep = _get("config_service")
        assert dep(request) is services.config_service


# =====================================================================
# ConfigServiceDep 类型别名
# =====================================================================


class TestConfigServiceDep:
    """验证 ConfigServiceDep 是正确的 Annotated 类型别名。"""

    def test_first_arg_is_config_service(self):
        """ConfigServiceDep 的首个类型参数应为 ConfigService。"""
        # Annotated[X, ...] 的 get_args 返回 (X, ...)
        args = get_args(ConfigServiceDep)
        assert args[0] is ConfigService

    def test_resolves_from_services_config_service(self, services):
        """ConfigServiceDep 内的 Depends 工厂应从 services.config_service 取值。"""
        request = _make_request(services)
        # Annotated[X, Depends(dep)] 的 metadata 是 get_args[1:]
        metadata = get_args(ConfigServiceDep)[1:]
        # Depends 对象的 .dependency 是被包装的可调用对象
        depends_obj = metadata[0]
        resolved = depends_obj.dependency(request)
        assert resolved is services.config_service
