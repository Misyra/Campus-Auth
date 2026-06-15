"""Task 11: 验证 container.py 不直接访问 TaskExecutor 私有属性。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


class TestContainerPrivateAttrFix:
    """验证 ServiceContainer 通过公共方法绑定 runtime_config_getter。"""

    def test_container_uses_public_method_not_private_attr(self, tmp_path: Path):
        """container.__init__ 应使用 set_runtime_config_getter 而非直接设置 _get_runtime_config。"""
        with (
            patch("app.container.WebSocketManager"),
            patch("app.container.ProfileService"),
            patch("app.container.LoginHistoryService"),
            patch("app.container.ScheduleEngine") as mock_engine_cls,
            patch("app.container.TaskService"),
            patch("app.container.AutoStartService"),
            patch("app.container.TaskRegistry"),
            patch("app.container.TaskHistoryStore"),
            patch("app.container.TaskExecutor") as mock_te_cls,
        ):
            from app.container import ServiceContainer

            mock_te_instance = mock_te_cls.return_value
            container = ServiceContainer(tmp_path)

            # 验证调用了公共方法
            mock_te_instance.set_runtime_config_getter.assert_called_once()

    def test_container_passes_engine_getter(self, tmp_path: Path):
        """container.__init__ 应将 engine.get_runtime_config 传给 TaskExecutor。"""
        with (
            patch("app.container.WebSocketManager"),
            patch("app.container.ProfileService"),
            patch("app.container.LoginHistoryService"),
            patch("app.container.ScheduleEngine") as mock_engine_cls,
            patch("app.container.TaskService"),
            patch("app.container.AutoStartService"),
            patch("app.container.TaskRegistry"),
            patch("app.container.TaskHistoryStore"),
            patch("app.container.TaskExecutor") as mock_te_cls,
        ):
            from app.container import ServiceContainer

            container = ServiceContainer(tmp_path)

            # 验证传入的是 engine 的 get_runtime_config 方法
            getter = mock_te_instance = mock_te_cls.return_value
            call_args = mock_te_instance.set_runtime_config_getter.call_args[0][0]
            assert call_args is container.engine.get_runtime_config
