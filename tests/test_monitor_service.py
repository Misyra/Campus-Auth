from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

from backend.monitor_service import MonitorService, WebSocketManager
from backend.profile_service import ProfileService


class TestWebSocketManager:

    def test_connect_disconnect(self):
        ws_manager = WebSocketManager()
        mock_ws = AsyncMock()
        async def run():
            await ws_manager.connect(mock_ws)
            assert mock_ws in ws_manager._connections
            await ws_manager.disconnect(mock_ws)
            assert mock_ws not in ws_manager._connections
        asyncio.get_event_loop().run_until_complete(run())

    def test_broadcast_empty(self):
        ws_manager = WebSocketManager()
        async def run():
            await ws_manager.broadcast("test")
        asyncio.get_event_loop().run_until_complete(run())


class TestMonitorService:

    def _make_service(self, tmp_path):
        profile_svc = ProfileService(tmp_path)
        return MonitorService(tmp_path, profile_service=profile_svc)

    def test_init(self, tmp_path):
        svc = self._make_service(tmp_path)
        assert svc.project_root == tmp_path
        assert svc._profile_service is not None

    def test_get_config(self, tmp_path):
        svc = self._make_service(tmp_path)
        config = svc.get_config()
        assert config is not None

    def test_get_status(self, tmp_path):
        svc = self._make_service(tmp_path)
        status = svc.get_status()
        assert status.monitoring is False
        assert status.network_check_count == 0

    def test_list_logs_empty(self, tmp_path):
        svc = self._make_service(tmp_path)
        logs = svc.list_logs()
        assert logs == []

    def test_list_logs_limit_zero(self, tmp_path):
        svc = self._make_service(tmp_path)
        logs = svc.list_logs(limit=0)
        assert logs == []

    def test_toggle_safe_mode(self, tmp_path):
        svc = self._make_service(tmp_path)
        new_val = svc.toggle_safe_mode()
        assert new_val is True
        assert svc.safe_mode is True

    def test_get_runtime_config(self, tmp_path):
        svc = self._make_service(tmp_path)
        config = svc.get_runtime_config()
        assert isinstance(config, dict)

    def test_reload_config(self, tmp_path):
        svc = self._make_service(tmp_path)
        svc.reload_config()
        config = svc.get_runtime_config()
        assert isinstance(config, dict)

    def test_stop_monitoring_not_running(self, tmp_path):
        svc = self._make_service(tmp_path)
        ok, msg = svc.stop_monitoring()
        assert ok is False
        assert "未运行" in msg

    def test_apply_profile(self, tmp_path):
        svc = self._make_service(tmp_path)
        svc.apply_profile("default")
        config = svc.get_runtime_config()
        assert isinstance(config, dict)
