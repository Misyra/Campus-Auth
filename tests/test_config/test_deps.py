"""依赖注入测试 — app/deps.py

覆盖：_get 工厂函数从 request.app.state.services 正确提取服务实例
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.deps import _get


def _make_request(services) -> MagicMock:
    """构造一个携带 services 的 mock Request。"""
    request = MagicMock()
    request.app.state.services = services
    return request


# =====================================================================
# 依赖注入工厂函数
# =====================================================================


class TestDeps:
    @pytest.fixture
    def services(self):
        svc = MagicMock()
        svc.engine = MagicMock(name="ScheduleEngine")
        svc.profile_service = MagicMock(name="ProfileService")
        svc.task_manager = MagicMock(name="TaskManager")
        svc.autostart_service = MagicMock(name="AutoStartService")
        svc.debug_manager = MagicMock(name="DebugSessionManager")
        svc.login_history_service = MagicMock(name="LoginHistoryService")
        return svc

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
