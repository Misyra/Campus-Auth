"""测试 ServiceContainer 轻量模式的登录能力。"""

from pathlib import Path
from unittest.mock import MagicMock, patch

from app.container import ServiceContainer


def test_lightweight_container_has_real_task_executor(tmp_path):
    """轻量模式应使用真实 TaskExecutor。"""
    from app.services.task_executor import TaskExecutor

    container = ServiceContainer(tmp_path, mode="lightweight")
    assert isinstance(container.task_executor, TaskExecutor)
