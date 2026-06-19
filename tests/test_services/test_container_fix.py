"""测试 ServiceContainer 轻量模式的登录能力。"""

from pathlib import Path
from unittest.mock import MagicMock, patch

from app.container import ServiceContainer


def test_lightweight_container_has_real_task_executor(tmp_path):
    """轻量模式应使用真实 TaskExecutor。"""
    from app.services.task_executor import TaskExecutor

    container = ServiceContainer(tmp_path, mode="lightweight")
    assert isinstance(container.task_executor, TaskExecutor)


def test_lightweight_execute_login_async_returns_future(tmp_path):
    """轻量模式的 execute_login_async 应返回 Future（不是 None）。"""
    from concurrent.futures import Future

    container = ServiceContainer(tmp_path, mode="lightweight")
    # mock worker 避免真实浏览器启动
    with patch("app.workers.playwright_worker.get_worker") as mock_get_worker:
        mock_worker = MagicMock()
        mock_worker.submit.return_value = MagicMock(success=True, data="ok")
        mock_get_worker.return_value = mock_worker

        future = container.task_executor.execute_login_async()
        # 应返回 Future 对象，不是 None
        assert isinstance(future, Future)
