"""网络检测链路连接测试 — monitor_service → decision → engine。

验证网络检测结果正确驱动引擎行为。
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from app.network.decision import NetworkCheckResult
from app.schemas import AuthProfile
from app.services.monitor_service import CheckOnceResult, NetworkMonitorCore
from app.workers.playwright_worker import WorkerResponse


def _make_monitor_core(engine) -> NetworkMonitorCore:
    """直接创建 NetworkMonitorCore，绕过引擎异步队列。"""
    config = engine.get_runtime_config()
    core = NetworkMonitorCore(
        config=config,
        log_callback=engine.record_log,
        login_history=engine._login_history,
        worker_getter=engine._worker_getter,
    )
    core.set_profile_service(engine._profile_service)
    core.init_monitoring()
    return core


class TestNetworkConnection:
    """网络检测链路连接测试。"""

    def test_need_login(self, integration_stack):
        """网络不通 → 触发登录。"""
        engine, profile_service, task_executor, mock_worker = integration_stack

        core = _make_monitor_core(engine)

        with patch(
            "app.services.monitor_service.check_network_status",
            return_value=(False, "network_down", "none"),
        ):
            result = core.check_once()

        assert result.need_login is True

    def test_network_ok(self, integration_stack):
        """网络通 → 不触发登录。"""
        engine, profile_service, task_executor, mock_worker = integration_stack

        core = _make_monitor_core(engine)

        with patch(
            "app.services.monitor_service.check_network_status",
            return_value=(True, "network_ok", "tcp"),
        ):
            result = core.check_once()

        assert result.need_login is False

    def test_pause_window(self, integration_stack):
        """暂停时段 → check_once 跳过。"""
        engine, profile_service, task_executor, mock_worker = integration_stack

        core = _make_monitor_core(engine)

        with patch(
            "app.services.monitor_service.check_pause",
            return_value=(True, "pause_period"),
        ):
            result = core.check_once()

        assert result.paused is True
        assert result.need_login is False

    def test_probe_exception(self, integration_stack):
        """探测抛异常 → 引擎继续运行。"""
        engine, profile_service, task_executor, mock_worker = integration_stack

        # 手动设置 _monitor_core，让 _do_network_check 可以调用
        core = _make_monitor_core(engine)
        engine._monitor_core = core

        with patch(
            "app.services.monitor_service.check_network_status",
            side_effect=RuntimeError("探测失败"),
        ):
            # _do_network_check 内部捕获异常，不会传播
            engine._do_network_check()

        # 引擎仍在运行（_monitor_core 未被清除）
        assert engine._monitor_core is not None

    def test_profile_switch_signal(self, integration_stack):
        """方案切换 → engine reload + restart。"""
        engine, profile_service, task_executor, mock_worker = integration_stack

        # 手动设置 _monitor_core
        core = _make_monitor_core(engine)
        engine._monitor_core = core

        # mock 检测到方案切换
        with patch.object(core, "consume_profile_switch_flag", return_value=True):
            with patch.object(
                core,
                "check_once",
                return_value=CheckOnceResult(paused=False, net_ok=True, net_reason="", need_login=False, check_num=1, interval=1, result=NetworkCheckResult(available=True, method="tcp", latency_ms=0, detail="")),
            ):
                with patch.object(engine, "_reload_config_internal", return_value=True):
                    with patch.object(engine, "_handle_stop") as mock_stop:
                        with patch.object(engine, "_handle_start") as mock_start:
                            engine._do_network_check()

        # 方案切换触发了 stop + start
        mock_stop.assert_called_once()
        mock_start.assert_called_once()
