"""验证 container.py 异常处理和清理效率。

1. suppress(Exception) 改为 try/except + debug 日志（stop_web_services 和 shutdown）
2. 逐个遍历删除改为 shutil.rmtree 一步删除
"""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from app.container import ServiceContainer


@pytest.fixture
def mock_container_deps():
    """Mock 所有 ServiceContainer 依赖，返回 mock 字典。"""
    mocks = {}
    with (
        patch("app.container.WebSocketManager") as ws,
        patch("app.container.get_profile_service") as ps,
        patch("app.container.LoginHistoryService") as lhs,
        patch("app.container.ScheduleEngine") as se,
        patch("app.container.TaskManager") as ts,
        patch("app.container.AutoStartService") as ats,
        patch("app.container.TaskRegistry") as tr,
        patch("app.container.TaskHistoryStore") as ths,
        patch("app.container.TaskExecutor") as te,
        patch("app.network.probes.shutdown_probes"),
    ):
        # ws_manager.close_all() 需要可 await
        ws.return_value.close_all = AsyncMock()
        mocks["ws_manager"] = ws
        mocks["profile_service"] = ps
        mocks["login_history"] = lhs
        mocks["engine"] = se
        mocks["task_manager"] = ts
        mocks["autostart"] = ats
        mocks["task_registry"] = tr
        mocks["task_history"] = ths
        mocks["task_executor"] = te
        yield mocks


def _make_container(tmp_path: Path, mock_container_deps: dict):
    """创建一个已 mock 依赖的 ServiceContainer 实例。"""
    c = ServiceContainer(tmp_path)
    # wait_for_callbacks 是异步方法，mock executor 需要返回协程
    c.task_executor.wait_for_callbacks = AsyncMock()
    return c


class TestSuppressExceptionFix:
    """验证 contextlib.suppress(Exception) 已替换为 try/except + 日志。"""

    def test_stop_web_services_logs_on_remove_failure(
        self, tmp_path: Path, mock_container_deps: dict
    ):
        """stop_web_services 中 loguru.remove 失败时应记录 warning 日志而非静默吞掉。"""
        container = _make_container(tmp_path, mock_container_deps)
        container._web_services_started = True
        container._log_handler_id = 42
        container._ws_drain_task = None

        with patch("app.container.container_logger") as mock_logger:
            with patch("loguru.logger") as mock_loguru:
                mock_loguru.remove.side_effect = RuntimeError("remove failed")
                asyncio.run(container.stop_web_services())

                # 应记录 warning 日志，包含异常信息
                mock_logger.warning.assert_called()
                call_args = mock_logger.warning.call_args
                assert "移除日志处理器失败" in call_args[0][0]

    def test_shutdown_logs_on_remove_failure(
        self, tmp_path: Path, mock_container_deps: dict
    ):
        """shutdown 中 loguru.remove 失败时应记录 warning 日志而非静默吞掉。"""
        container = _make_container(tmp_path, mock_container_deps)
        container._log_handler_id = 42
        container._ws_drain_task = None
        container._web_services_started = True  # 复用 stop_web_services 需要此标志

        with patch("app.container.container_logger") as mock_logger:
            with patch("loguru.logger") as mock_loguru:
                mock_loguru.remove.side_effect = RuntimeError("remove failed")
                asyncio.run(container.shutdown())

                # 应记录 warning 日志，包含异常信息
                mock_logger.warning.assert_called()
                call_args = mock_logger.warning.call_args
                assert "移除日志处理器失败" in call_args[0][0]

    def test_stop_web_services_success_no_log(
        self, tmp_path: Path, mock_container_deps: dict
    ):
        """stop_web_services 中 loguru.remove 成功时不应记录异常日志。"""
        container = _make_container(tmp_path, mock_container_deps)
        container._web_services_started = True
        container._log_handler_id = 42
        container._ws_drain_task = None

        with patch("app.container.container_logger") as mock_logger:
            with patch("loguru.logger") as mock_loguru:
                mock_loguru.remove.return_value = None
                asyncio.run(container.stop_web_services())

                # 不应调用 debug（无异常）
                mock_logger.debug.assert_not_called()


class TestCleanupEfficiencyFix:
    """验证临时目录清理改为 shutil.rmtree 一步完成。"""

    def test_shutdown_cleans_temp_dir_with_rmtree(
        self, tmp_path: Path, mock_container_deps: dict
    ):
        """shutdown 应使用 shutil.rmtree 一步清理临时目录。"""
        temp_dir = tmp_path / "temp"
        temp_dir.mkdir()
        (temp_dir / "file1.txt").write_text("test")
        sub = temp_dir / "subdir"
        sub.mkdir()
        (sub / "file2.txt").write_text("test")

        container = _make_container(tmp_path, mock_container_deps)
        container._ws_drain_task = None

        with patch.object(shutil, "rmtree", wraps=shutil.rmtree) as mock_rmtree:
            asyncio.run(container.shutdown())

            # 应调用 shutil.rmtree 清理 temp_dir
            mock_rmtree.assert_called()
            call_args = mock_rmtree.call_args
            assert call_args[0][0] == temp_dir

    def test_shutdown_temp_dir_recreated_after_rmtree(
        self, tmp_path: Path, mock_container_deps: dict
    ):
        """shutdown 清理后应重新创建临时目录。"""
        temp_dir = tmp_path / "temp"
        temp_dir.mkdir()
        (temp_dir / "file.txt").write_text("test")

        container = _make_container(tmp_path, mock_container_deps)
        container._ws_drain_task = None

        asyncio.run(container.shutdown())

        # 临时目录应被重新创建
        assert temp_dir.exists()
        assert temp_dir.is_dir()

    def test_shutdown_temp_dir_cleaned_recursively(
        self, tmp_path: Path, mock_container_deps: dict
    ):
        """shutdown 应递归清理临时目录中的所有内容。"""
        temp_dir = tmp_path / "temp"
        temp_dir.mkdir()
        (temp_dir / "file.txt").write_text("test")
        sub = temp_dir / "subdir"
        sub.mkdir()
        (sub / "nested.txt").write_text("test")

        container = _make_container(tmp_path, mock_container_deps)
        container._ws_drain_task = None

        asyncio.run(container.shutdown())

        # 临时目录应存在但内容应被清空
        assert temp_dir.exists()
        assert list(temp_dir.iterdir()) == []


def test_lightweight_container_has_real_task_executor(tmp_path):
    """轻量模式应使用真实 TaskExecutor。"""
    from app.services.task_executor import TaskExecutor

    container = ServiceContainer(tmp_path, mode="lightweight")
    assert isinstance(container.task_executor, TaskExecutor)
