"""网络检测链路连接测试 — monitor_service → decision → engine。

验证网络检测结果正确驱动引擎行为。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from app.network.decision import NetworkCheckResult
from app.services.monitor_service import CheckOnceResult, NetworkMonitorCore


def _make_monitor_core(engine) -> NetworkMonitorCore:
    """直接创建 NetworkMonitorCore，绕过引擎异步队列。"""
    config = engine.get_runtime_config()
    core = NetworkMonitorCore(
        get_config=lambda: config,
        logger=engine._logger,
    )
    core.set_profile_service(engine._profile_service)
    core.init_monitoring()
    return core


class TestNetworkConnection:
    """网络检测链路连接测试。"""

    async def test_need_login(self, integration_stack):
        """网络不通 → 触发登录。"""
        engine, profile_service, task_executor, _, mock_worker = integration_stack

        core = _make_monitor_core(engine)

        with (
            patch(
                "app.services.monitor_service.check_network_status",
                new=AsyncMock(return_value=(False, "network_down", "none")),
            ),
            patch(
                "app.services.monitor_service.check_pause",
                return_value=(False, ""),
            ),
        ):
            result = await core.check_once()

        assert result.need_login is True

    async def test_network_ok(self, integration_stack):
        """网络通 → 不触发登录。"""
        engine, profile_service, task_executor, _, mock_worker = integration_stack

        core = _make_monitor_core(engine)

        with (
            patch(
                "app.services.monitor_service.check_network_status",
                new=AsyncMock(return_value=(True, "network_ok", "tcp")),
            ),
            patch(
                "app.services.monitor_service.check_pause",
                return_value=(False, ""),
            ),
        ):
            result = await core.check_once()

        assert result.need_login is False

    async def test_pause_window(self, integration_stack):
        """暂停时段 → check_once 跳过。"""
        engine, profile_service, task_executor, _, mock_worker = integration_stack

        core = _make_monitor_core(engine)

        with patch(
            "app.services.monitor_service.check_pause",
            return_value=(True, "pause_period"),
        ):
            result = await core.check_once()

        assert result.paused is True
        assert result.need_login is False

    async def test_probe_exception(self, integration_stack):
        """探测抛异常 → 引擎继续运行。"""
        engine, profile_service, task_executor, _, mock_worker = integration_stack

        # 手动设置 _monitor_core，让 _do_network_check 可以调用
        core = _make_monitor_core(engine)
        engine._monitor_core = core

        with patch(
            "app.services.monitor_service.check_network_status",
            new=AsyncMock(side_effect=RuntimeError("探测失败")),
        ):
            # _do_network_check_async 内部捕获异常，不会传播
            await engine._do_network_check_async()

        # 引擎仍在运行（_monitor_core 未被清除）
        assert engine._monitor_core is not None

