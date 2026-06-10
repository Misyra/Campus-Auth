"""系统关机路由测试"""

from __future__ import annotations

from unittest.mock import MagicMock, patch


class TestShutdownUsesExit:
    """shutdown 使用 shutdown_event 触发 lifespan 正常关闭"""

    def test_shutdown_sets_shutdown_event(self):
        """验证 shutdown 设置 shutdown_event 而非 os._exit"""
        mock_monitor = MagicMock()
        mock_monitor.stop_monitoring.return_value = (True, "监控已停止")

        mock_request = MagicMock()
        mock_request.app.state.shutdown_event = MagicMock()

        mock_bg_tasks = MagicMock()

        with (
            patch("app.workers.playwright_worker.get_worker") as mock_get_worker,
            patch("app.workers.playwright_worker.cleanup_orphan_browsers"),
        ):
            mock_worker = MagicMock()
            mock_get_worker.return_value = mock_worker

            from app.api.system import shutdown_server

            result = shutdown_server(
                request=mock_request, bg_tasks=mock_bg_tasks, svc=mock_monitor
            )

        # 验证通过 BackgroundTasks 调度了 shutdown_event.set()
        mock_bg_tasks.add_task.assert_called_once()
        # 验证返回成功响应
        assert result.success is True

    def test_shutdown_cleanup_functions_called(self):
        """测试 shutdown 调用清理函数"""
        mock_monitor = MagicMock()
        mock_monitor.stop_monitoring.return_value = (True, "监控已停止")

        mock_request = MagicMock()
        mock_request.app.state.shutdown_event = MagicMock()

        mock_bg_tasks = MagicMock()

        with (
            patch("app.workers.playwright_worker.get_worker") as mock_get_worker,
            patch(
                "app.workers.playwright_worker.cleanup_orphan_browsers"
            ) as mock_cleanup,
        ):
            mock_worker = MagicMock()
            mock_get_worker.return_value = mock_worker

            from app.api.system import shutdown_server

            shutdown_server(
                request=mock_request, bg_tasks=mock_bg_tasks, svc=mock_monitor
            )

        # 验证清理函数被调用
        mock_monitor.stop_monitoring.assert_called_once()
        mock_worker.stop.assert_called_once()
        mock_cleanup.assert_called_once()
        # 验证通过 BackgroundTasks 调度了 shutdown_event
        mock_bg_tasks.add_task.assert_called_once()
