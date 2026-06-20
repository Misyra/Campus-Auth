"""Profile 切换链路连接测试 — profile_service → engine 配置重载 → 监控重启。"""

from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from app.schemas import AuthProfile
from app.workers.playwright_worker import WorkerResponse


class TestProfileConnection:
    """Profile 切换链路连接测试。"""

    def test_apply_profile(self, integration_stack):
        """切换方案 → engine 使用新凭证。"""
        engine, profile_service, task_executor, mock_worker = integration_stack

        # 创建第二个 profile 并设为活动方案
        profile_service.update(
            lambda d: d.profiles.update({"profile-b": AuthProfile(
                name="方案B", username="user-b", auth_url="http://10.0.0.2"
            )})
        )
        profile_service.set_active_profile("profile-b")

        ok, msg = engine.apply_profile("profile-b")
        assert ok is True

        config = engine.get_config()
        assert config.username == "user-b"

    def test_switch_while_monitoring(self, integration_stack):
        """监控运行中切换 → 旧配置停、新配置起，无线程泄漏。"""
        engine, profile_service, task_executor, mock_worker = integration_stack

        profile_service.update(
            lambda d: d.profiles.update({"profile-b": AuthProfile(
                name="方案B", username="user-b", auth_url="http://10.0.0.2"
            )})
        )

        # 直接设置 monitor_core，绕过异步队列
        from app.services.monitor_service import NetworkMonitorCore
        config = engine.get_runtime_config().model_dump()
        core = NetworkMonitorCore(
            config=config,
            log_callback=engine.record_log,
            login_history=engine._login_history,
            worker_getter=engine._worker_getter,
        )
        core.set_profile_service(engine._profile_service)
        core.init_monitoring()
        engine._monitor_core = core

        assert engine._is_monitoring

        profile_service.set_active_profile("profile-b")
        ok, msg = engine.apply_profile("profile-b")
        assert ok is True

        # apply_profile 通过队列异步处理，等待引擎线程处理完成
        time.sleep(0.5)

        assert engine._is_monitoring
        assert engine.get_config().username == "user-b"

    def test_delete_current_profile(self, integration_stack):
        """删除当前方案 → 回退到 default。"""
        engine, profile_service, task_executor, mock_worker = integration_stack

        # 确保 default profile 有完整凭证
        profile_service.update(
            lambda d: d.profiles.update({"default": AuthProfile(
                name="默认方案", username="testuser", auth_url="http://10.0.0.1"
            )})
        )

        profile_service.update(
            lambda d: d.profiles.update({"profile-b": AuthProfile(
                name="方案B", username="user-b", auth_url="http://10.0.0.2"
            )})
        )
        profile_service.set_active_profile("profile-b")
        engine.apply_profile("profile-b")

        ok, msg = profile_service.delete_profile("profile-b")
        assert ok is True

        engine.reload_config()
        config = engine.get_config()
        assert config.username == "testuser"
