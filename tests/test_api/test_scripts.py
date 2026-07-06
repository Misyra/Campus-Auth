"""scripts API 模块级 executor 生命周期管理测试。"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from app.api.scripts import _script_executor, shutdown_script_executor


class TestScriptExecutorLifecycle:
    """模块级 executor 的生命周期管理。"""

    def test_executor_exists(self):
        """模块级 executor 应存在。"""
        assert _script_executor is not None
        assert isinstance(_script_executor, ThreadPoolExecutor)

    def test_executor_max_workers(self):
        """executor 应配置为 2 个工作线程。"""
        assert _script_executor._max_workers == 2

    def test_executor_thread_prefix(self):
        """executor 线程名前缀应为 script_api。"""
        assert _script_executor._thread_name_prefix == "script_api"


class TestShutdownScriptExecutor:
    """shutdown_script_executor() 函数行为。"""

    def test_shutdown_calls_executor_shutdown(self):
        """调用 shutdown_script_executor 应调用 executor.shutdown(wait=True)。"""
        with patch.object(_script_executor, "shutdown") as mock_shutdown:
            shutdown_script_executor()
            mock_shutdown.assert_called_once_with(wait=True)

    def test_shutdown_in_container(self):
        """ServiceContainer.shutdown() 应调用 shutdown_script_executor。"""
        import inspect

        from app.container import ServiceContainer

        source = inspect.getsource(ServiceContainer.shutdown)
        assert "shutdown_script_executor" in source
