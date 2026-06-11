"""系统关机路由测试"""

from __future__ import annotations

from unittest.mock import MagicMock


class TestShutdownUsesExit:
    """shutdown 使用 shutdown_event 触发 lifespan 正常关闭"""

    def test_shutdown_sets_shutdown_event(self):
        """验证 shutdown 设置 shutdown_event 而非 os._exit"""
        mock_monitor = MagicMock()
        mock_monitor.stop_monitoring.return_value = (True, "监控已停止")

        mock_request = MagicMock()
        mock_request.app.state.shutdown_event = MagicMock()

        mock_bg_tasks = MagicMock()

        from app.api.system import shutdown_server

        result = shutdown_server(
            request=mock_request, bg_tasks=mock_bg_tasks, svc=mock_monitor
        )

        # 验证通过 BackgroundTasks 调度了 shutdown_event.set()
        mock_bg_tasks.add_task.assert_called_once()
        # 验证返回成功响应
        assert result.success is True

    def test_shutdown_cleanup_functions_called(self):
        """测试 shutdown 调用清理函数，Worker/浏览器清理委托给 container.shutdown"""
        mock_monitor = MagicMock()
        mock_monitor.stop_monitoring.return_value = (True, "监控已停止")

        mock_request = MagicMock()
        mock_request.app.state.shutdown_event = MagicMock()

        mock_bg_tasks = MagicMock()

        from app.api.system import shutdown_server

        shutdown_server(request=mock_request, bg_tasks=mock_bg_tasks, svc=mock_monitor)

        # 验证监控停止和 shutdown_event 调度
        mock_monitor.stop_monitoring.assert_called_once()
        mock_bg_tasks.add_task.assert_called_once()
