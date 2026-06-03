"""路由层综合测试 — 合并所有未覆盖的路由模块

覆盖：config / monitor / tasks / profiles / history / tools / repo / scripts / scheduled_tasks / debug
"""
from __future__ import annotations

import json
from unittest.mock import patch, MagicMock, AsyncMock

import pytest
from fastapi.testclient import TestClient

from backend.schemas import (
    MonitorConfigPayload,
    MonitorStatusResponse,
    ProfileSettings,
    ProfilesData,
    SystemSettings,
)


# =====================================================================
# 共用 fixture：创建测试客户端
# =====================================================================


@pytest.fixture
def client(tmp_path):
    """创建隔离的测试客户端，所有服务均 mock。"""
    # 初始化项目目录结构
    (tmp_path / "frontend").mkdir(exist_ok=True)
    (tmp_path / "frontend" / "index.html").write_text("<html></html>")
    (tmp_path / "logs").mkdir(exist_ok=True)
    (tmp_path / "temp").mkdir(exist_ok=True)
    (tmp_path / "backups").mkdir(exist_ok=True)
    (tmp_path / "tasks" / "browser").mkdir(parents=True)
    (tmp_path / "tasks" / "scripts").mkdir(parents=True)
    (tmp_path / "tools").mkdir(exist_ok=True)
    (tmp_path / "doc").mkdir(exist_ok=True)
    (tmp_path / "frontend" / "background").mkdir(parents=True)

    # 写入默认设置文件
    settings_data = {
        "system": {
            "username": "testuser",
            "password": "ENC:test",
            "auth_url": "http://10.0.0.1",
        },
        "profiles": {
            "default": {"name": "默认方案"},
        },
    }
    (tmp_path / "settings.json").write_text(
        json.dumps(settings_data, ensure_ascii=False), encoding="utf-8"
    )

    # 写入默认任务文件
    (tmp_path / "tasks" / "browser" / "default.json").write_text(
        json.dumps({
            "name": "默认任务",
            "url": "http://10.0.0.1",
            "steps": [{"id": "s1", "type": "click", "selector": "#btn"}],
        }, ensure_ascii=False),
        encoding="utf-8",
    )

    with patch("backend.constants.PROJECT_ROOT", tmp_path), \
         patch("backend.constants.FRONTEND_DIR", tmp_path / "frontend"), \
         patch("backend.constants.LOGS_DIR", tmp_path / "logs"), \
         patch("backend.constants.TEMP_DIR", tmp_path / "temp"), \
         patch("backend.constants.BACKUP_DIR", tmp_path / "backups"):

        from backend.main import app

        mock_services = MagicMock()

        # ── monitor_service ──
        mock_services.monitor_service.get_config.return_value = MonitorConfigPayload(
            username="testuser", password="••••••••", auth_url="http://10.0.0.1"
        )
        mock_services.monitor_service.get_status.return_value = MonitorStatusResponse(
            monitoring=False, network_check_count=0, login_attempt_count=0,
            last_check_time=None, runtime_seconds=0,
        )
        mock_services.monitor_service.list_logs.return_value = []
        mock_services.monitor_service.start_monitoring.return_value = (True, "监控已启动")
        mock_services.monitor_service.stop_monitoring.return_value = (True, "监控已停止")
        mock_services.monitor_service.run_manual_login.return_value = (True, "手动登录成功")
        mock_services.monitor_service.test_network.return_value = (True, "网络正常")
        mock_services.monitor_service.pure_mode = False
        mock_services.monitor_service.toggle_pure_mode.return_value = True
        mock_services.monitor_service.get_runtime_config.return_value = {
            "monitor": {"script_timeout": 60}
        }

        # ── profile_service ──
        profile_data = ProfilesData(
            system=SystemSettings(username="testuser", password="ENC:test"),
            profiles={"default": ProfileSettings(name="默认方案")},
        )
        mock_services.profile_service.load.return_value = profile_data
        mock_services.profile_service.get_active_profile.return_value = ProfileSettings(name="默认方案")
        mock_services.profile_service.save_profile.return_value = (True, "保存成功")
        mock_services.profile_service.delete_profile.return_value = (True, "删除成功")
        mock_services.profile_service.set_active_profile.return_value = (True, "切换成功")
        mock_services.profile_service.detect_matching_profile.return_value = None
        mock_services.profile_service.set_auto_switch.return_value = None

        # ── task_service ──
        mock_services.task_service.list_tasks.return_value = [
            {"id": "default", "name": "默认任务"}
        ]
        mock_services.task_service.get_active_task.return_value = "default"
        mock_services.task_service.get_task.return_value = {
            "id": "default", "name": "默认任务",
            "steps": [{"id": "s1", "type": "click", "selector": "#btn"}],
        }
        mock_services.task_service.save_task.return_value = (True, "保存成功")
        mock_services.task_service.delete_task.return_value = (True, "删除成功")
        mock_services.task_service.set_active_task.return_value = (True, "切换成功")
        mock_services.task_service.save_task_order.return_value = (True, "排序成功")
        mock_services.task_service.list_scripts.return_value = []
        mock_services.task_service.task_manager = MagicMock()

        # ── autostart_service ──
        mock_services.autostart_service = MagicMock()

        # ── debug_manager ──
        mock_services.debug_manager.get_status.return_value = {
            "running": False, "task_id": None, "current_step": 0,
            "total_steps": 0, "steps": [], "results": [], "screenshot_url": None,
        }
        mock_services.debug_manager.stop = AsyncMock(return_value={"running": False, "message": "调试会话已关闭"})
        mock_services.debug_manager.next_step = AsyncMock(return_value={"running": False})
        mock_services.debug_manager.run_all = AsyncMock(return_value={"running": False})

        # ── login_history_service ──
        mock_services.login_history_service = MagicMock()
        mock_services.login_history_service.list_recent.return_value = []
        mock_services.login_history_service.clear.return_value = 0

        # ── scheduler_service ──
        mock_services.scheduler_service = MagicMock()
        mock_services.scheduler_service.list_tasks.return_value = []
        mock_services.scheduler_service.get_task.return_value = None
        mock_services.scheduler_service.save_task.return_value = (True, "保存成功")
        mock_services.scheduler_service.delete_task.return_value = (True, "删除成功")
        mock_services.scheduler_service.get_history.return_value = []

        # ── ws_manager ──
        mock_services.ws_manager = MagicMock()

        app.state.services = mock_services

        test_client = TestClient(app)
        yield test_client


# =====================================================================
# 配置路由
# =====================================================================


class TestConfigRouter:
    def test_get_config(self, client):
        resp = client.get("/api/config")
        assert resp.status_code == 200
        data = resp.json()
        assert "username" in data
        assert "auth_url" in data


# =====================================================================
# 监控路由
# =====================================================================


class TestMonitorRouter:
    def test_get_status(self, client):
        resp = client.get("/api/status")
        assert resp.status_code == 200
        assert "monitoring" in resp.json()

    def test_get_logs(self, client):
        resp = client.get("/api/logs")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_get_logs_with_limit(self, client):
        resp = client.get("/api/logs?limit=50")
        assert resp.status_code == 200

    def test_start_monitoring(self, client):
        resp = client.post("/api/monitor/start")
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_stop_monitoring(self, client):
        resp = client.post("/api/monitor/stop")
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_manual_login(self, client):
        resp = client.post("/api/actions/login")
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_test_network(self, client):
        resp = client.post("/api/actions/test-network")
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_get_pure_mode(self, client):
        resp = client.get("/api/pure-mode")
        assert resp.status_code == 200
        assert "enabled" in resp.json()

    def test_toggle_pure_mode(self, client):
        resp = client.post("/api/pure-mode")
        assert resp.status_code == 200
        assert "enabled" in resp.json()


# =====================================================================
# 任务路由
# =====================================================================


class TestTasksRouter:
    def test_list_tasks(self, client):
        resp = client.get("/api/tasks")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_get_active_task(self, client):
        resp = client.get("/api/tasks/active")
        assert resp.status_code == 200
        assert "task_id" in resp.json()

    def test_get_task(self, client):
        resp = client.get("/api/tasks/default")
        assert resp.status_code == 200
        assert resp.json()["name"] == "默认任务"

    def test_save_task(self, client):
        resp = client.put(
            "/api/tasks/new_task",
            json={"name": "新任务", "steps": [{"id": "s1", "type": "click", "selector": "#btn"}]},
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_delete_task(self, client):
        resp = client.delete("/api/tasks/default")
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_set_active_task(self, client):
        resp = client.post("/api/tasks/active/default")
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_save_task_order(self, client):
        resp = client.post("/api/tasks/order", json={"order": ["default"]})
        assert resp.status_code == 200
        assert resp.json()["success"] is True


# =====================================================================
# 方案路由
# =====================================================================


class TestProfilesRouter:
    def test_list_profiles(self, client):
        resp = client.get("/api/profiles")
        assert resp.status_code == 200
        data = resp.json()
        assert "profiles" in data
        assert "active_profile" in data

    def test_get_active_profile(self, client):
        resp = client.get("/api/profiles/active")
        assert resp.status_code == 200
        data = resp.json()
        assert "profile_id" in data
        assert "settings" in data

    def test_get_profile(self, client):
        resp = client.get("/api/profiles/default")
        assert resp.status_code == 200
        data = resp.json()
        assert data["profile_id"] == "default"
        assert "settings" in data

    def test_save_profile(self, client):
        resp = client.put(
            "/api/profiles/default",
            json={"name": "更新方案", "network_targets": "8.8.8.8:53"},
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_delete_profile(self, client):
        resp = client.delete("/api/profiles/default")
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_set_active_profile(self, client):
        resp = client.post("/api/profiles/active/default")
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_detect_network(self, client):
        resp = client.post("/api/profiles/detect")
        assert resp.status_code == 200
        data = resp.json()
        assert "gateway_ip" in data
        assert "ssid" in data

    def test_toggle_auto_switch(self, client):
        resp = client.post("/api/profiles/auto-switch?enabled=true")
        assert resp.status_code == 200
        assert resp.json()["success"] is True


# =====================================================================
# 登录历史路由
# =====================================================================


class TestHistoryRouter:
    def test_get_login_history(self, client):
        resp = client.get("/api/login-history")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_get_login_history_with_limit(self, client):
        resp = client.get("/api/login-history?limit=10")
        assert resp.status_code == 200

    def test_clear_login_history(self, client):
        resp = client.delete("/api/login-history")
        assert resp.status_code == 200
        assert resp.json()["success"] is True


# =====================================================================
# 调试路由
# =====================================================================


class TestDebugRouter:
    def test_debug_status(self, client):
        resp = client.get("/api/debug/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "running" in data
        assert "current_step" in data

    def test_debug_stop(self, client):
        resp = client.post("/api/debug/stop")
        assert resp.status_code == 200
        assert resp.json()["running"] is False

    def test_debug_next(self, client):
        resp = client.post("/api/debug/next")
        assert resp.status_code == 200

    def test_debug_run_all(self, client):
        resp = client.post("/api/debug/run-all")
        assert resp.status_code == 200


# =====================================================================
# 定时任务路由
# =====================================================================


class TestScheduledTasksRouter:
    def test_list_scheduled_tasks(self, client):
        resp = client.get("/api/scheduled-tasks")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_create_scheduled_task(self, client):
        resp = client.post(
            "/api/scheduled-tasks",
            json={
                "name": "测试定时任务",
                "type": "shell",
                "command": "echo hello",
                "schedule": {"hour": 8, "minute": 30},
            },
        )
        assert resp.status_code == 200

    def test_create_scheduled_task_missing_name(self, client):
        resp = client.post(
            "/api/scheduled-tasks",
            json={"type": "shell", "command": "echo hello", "schedule": {"hour": 8, "minute": 0}},
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is False

    def test_create_scheduled_task_invalid_type(self, client):
        resp = client.post(
            "/api/scheduled-tasks",
            json={"name": "test", "type": "invalid", "schedule": {"hour": 8, "minute": 0}},
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is False

    def test_create_scheduled_task_shell_missing_command(self, client):
        resp = client.post(
            "/api/scheduled-tasks",
            json={"name": "test", "type": "shell", "schedule": {"hour": 8, "minute": 0}},
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is False

    def test_create_scheduled_task_missing_schedule(self, client):
        resp = client.post(
            "/api/scheduled-tasks",
            json={"name": "test", "type": "shell", "command": "echo hello"},
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is False

    def test_get_scheduled_task_not_found(self, client):
        # get_task 返回 None，应返回 404
        resp = client.get("/api/scheduled-tasks/nonexistent")
        assert resp.status_code == 404

    def test_delete_scheduled_task(self, client):
        resp = client.delete("/api/scheduled-tasks/task_123")
        assert resp.status_code == 200


# =====================================================================
# 仓库代理路由
# =====================================================================


class TestRepoRouter:
    @patch("backend.routers.repo.repo_fetch_json")
    def test_repo_fetch_index(self, mock_fetch, client):
        mock_fetch.return_value = [{"id": "task1", "name": "任务1"}]
        resp = client.get("/api/repo/fetch?url=https://example.com/index.json")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    @patch("backend.routers.repo.repo_fetch_json")
    def test_repo_fetch_task(self, mock_fetch, client):
        mock_fetch.return_value = {"name": "任务详情"}
        resp = client.get("/api/repo/task?url=https://example.com/task.json")
        assert resp.status_code == 200
        assert isinstance(resp.json(), dict)


# =====================================================================
# 脚本路由
# =====================================================================


class TestScriptsRouter:
    def test_list_scripts(self, client):
        resp = client.get("/api/scripts")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_get_script_not_found(self, client):
        # get_task 返回非 script 类型
        resp = client.get("/api/scripts/nonexistent")
        assert resp.status_code == 404
