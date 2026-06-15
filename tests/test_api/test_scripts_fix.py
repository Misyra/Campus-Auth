"""验证 scripts.py 使用专用线程池而非默认线程池。"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock, patch

import pytest


class TestScriptThreadPool:
    """验证 run_script 使用专用线程池。"""

    @pytest.mark.asyncio
    async def test_run_script_uses_dedicated_executor(self):
        """run_script 应使用专用 ThreadPoolExecutor 而非默认线程池。"""
        from app.api.scripts import run_script

        # 清除可能存在的旧 executor
        if hasattr(run_script, "_executor"):
            delattr(run_script, "_executor")

        captured_executor = {}

        # 构造 mock 依赖
        mock_task_service = MagicMock()
        mock_task_service.get_task.return_value = {"type": "script", "binary_path": ""}
        mock_task_service.get_script_path.return_value = MagicMock(
            exists=MagicMock(return_value=True)
        )

        mock_request = MagicMock()
        mock_request.app.state.services.monitor_service.get_runtime_config.return_value = {
            "monitor": {"script_timeout": 60}
        }

        # 拦截 run_in_executor，记录 executor 参数
        async def mock_run_in_executor(executor, func):
            captured_executor["executor"] = executor
            return True, "mock success"

        with (
            patch("app.api.scripts.ScriptRunner") as mock_runner_cls,
            patch.object(asyncio.BaseEventLoop, "run_in_executor", side_effect=mock_run_in_executor),
        ):
            mock_runner = MagicMock()
            mock_runner_cls.return_value = mock_runner

            result = await run_script(mock_request, "test_task", mock_task_service)

        assert result.success is True
        executor = captured_executor.get("executor")
        # 验证使用的不是 None（默认线程池）
        assert executor is not None
        # 验证是 ThreadPoolExecutor
        assert isinstance(executor, ThreadPoolExecutor)
        # 验证线程名前缀
        assert executor._thread_name_prefix == "script_runner"

    @pytest.mark.asyncio
    async def test_executor_is_reused(self):
        """模块级 executor 应存在并可复用。"""
        from app.api.scripts import _script_executor

        # 验证模块级 executor 存在且为 ThreadPoolExecutor
        assert _script_executor is not None
        assert isinstance(_script_executor, ThreadPoolExecutor)
        assert _script_executor._thread_name_prefix == "script_runner"
