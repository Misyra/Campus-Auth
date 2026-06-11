"""依赖注入函数测试 — backend/deps.py

覆盖：所有 get_* 函数从 request.app.state.services 正确提取服务实例
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.deps import (
    get_autostart_service,
    get_debug_manager,
    get_login_history_service,
    get_monitor_service,
    get_profile_service,
    get_services,
    get_task_service,
)


def _make_request(services) -> MagicMock:
    """构造一个携带 services 的 mock Request。"""
    request = MagicMock()
    request.app.state.services = services
    return request


# =====================================================================
# 依赖注入函数
# =====================================================================


class TestDeps:
    @pytest.fixture
    def services(self):
        svc = MagicMock()
        svc.engine = MagicMock(name="ScheduleEngine")
        svc.profile_service = MagicMock(name="ProfileService")
        svc.task_service = MagicMock(name="TaskService")
        svc.autostart_service = MagicMock(name="AutoStartService")
        svc.debug_manager = MagicMock(name="DebugSessionManager")
        svc.login_history_service = MagicMock(name="LoginHistoryService")
        return svc

    def test_get_services(self, services):
        request = _make_request(services)
        assert get_services(request) is services

    def test_get_monitor_service(self, services):
        request = _make_request(services)
        assert get_monitor_service(request) is services.engine

    def test_get_profile_service(self, services):
        request = _make_request(services)
        assert get_profile_service(request) is services.profile_service

    def test_get_task_service(self, services):
        request = _make_request(services)
        assert get_task_service(request) is services.task_service

    def test_get_autostart_service(self, services):
        request = _make_request(services)
        assert get_autostart_service(request) is services.autostart_service

    def test_get_debug_manager(self, services):
        request = _make_request(services)
        assert get_debug_manager(request) is services.debug_manager

    def test_get_login_history_service(self, services):
        request = _make_request(services)
        assert get_login_history_service(request) is services.login_history_service
