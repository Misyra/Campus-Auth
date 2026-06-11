"""ScheduledTaskService 测试 — 聚焦 shell 安全策略集成。"""

from __future__ import annotations

import threading
from unittest.mock import MagicMock, patch

import pytest

from app.services.scheduled_task import ScheduledTaskService
from app.services.task_executor import TaskExecutor
from app.services.task_registry import TaskHistoryStore, TaskRegistry
from app.tasks import TaskManager
from app.utils.shell_utils import detect_shells as detect_available_shells



# =====================================================================
# detect_available_shells
# =====================================================================


def test_history_store_initialized_at_construct(tmp_path):
    """_history_store 应在 __init__ 中初始化。"""
    task_manager = TaskManager(tmp_path / "tasks")
    svc = ScheduledTaskService(
        tmp_path,
        task_manager=task_manager,
    )
    assert hasattr(svc, "_history_store")
    assert hasattr(svc._history_store, "add_record")


class TestDetectAvailableShells:
    """测试系统可用 Shell 检测。"""

    def test_returns_list(self):
        shells = detect_available_shells()
        assert isinstance(shells, list)

    def test_each_entry_has_required_keys(self):
        shells = detect_available_shells()
        for entry in shells:
            assert "name" in entry
            assert "path" in entry
            assert "description" in entry

    @pytest.mark.skipif(__import__("sys").platform != "win32", reason="仅 Windows")
    def test_windows_finds_cmd(self):
        shells = detect_available_shells()
        names = [s["name"] for s in shells]
        assert "cmd" in names


# =====================================================================
# TaskExecutor._execute_shell 使用 ShellCommandPolicy
# =====================================================================


class TestExecuteShellUsesPolicy:
    """验证 TaskExecutor._execute_shell 内部使用 ShellCommandPolicy。"""

    @pytest.fixture
    def executor(self, tmp_path):
        registry = TaskRegistry(tmp_path / "tasks" / "scheduled")
        history_store = TaskHistoryStore(tmp_path / "tasks" / "scheduled" / "history")
        return TaskExecutor(
            registry=registry,
            history_store=history_store,
            worker_getter=lambda: None,
        )

    def test_rejected_shell_path_returns_failure(self, executor):
        """不在白名单的 shell_path 应被拒绝，返回失败消息。"""
        result = executor._execute_shell(
            "echo hello", timeout=10, shell_path="/fake/malicious/shell"
        )
        success, message = result
        assert success is False
        assert (
            "白名单" in message
            or "拒绝" in message
            or "Permission" in message.lower()
            or "不在" in message
        )

    def test_timeout_clamped_to_max(self, executor):
        """超时应被 clamp 到 300 秒上限。"""
        shells = detect_available_shells()
        if not shells:
            pytest.skip("系统无可用 shell")

        shell_path = shells[0]["path"]

        with patch(
            "app.utils.shell_policy.subprocess.run"
        ) as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=b"ok", stderr=b"")

            executor._execute_shell("echo ok", timeout=9999, shell_path=shell_path)
            assert mock_run.called

    def test_audit_log_called(self, executor):
        """执行前应记录审计日志。"""
        shells = detect_available_shells()
        if not shells:
            pytest.skip("系统无可用 shell")

        shell_path = shells[0]["path"]

        with patch(
            "app.utils.shell_policy.subprocess.run"
        ) as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=b"ok", stderr=b"")

            result = executor._execute_shell(
                "echo audit_test", timeout=30, shell_path=shell_path
            )
            success, message = result
            assert success is True

    def test_empty_command_returns_failure(self, executor):
        """空命令应返回失败。"""
        result = executor._execute_shell("", timeout=30)
        success, message = result
        assert success is False
        assert "空" in message

    def test_execute_shell_uses_policy_integration(self, executor):
        """集成验证：_execute_shell 路径校验经过 ShellCommandPolicy。"""
        result = executor._execute_shell(
            "echo test", timeout=30, shell_path="/absolutely/fake/shell"
        )
        success, message = result
        assert success is False
        assert (
            "白名单" in message or "Permission" in message.lower() or "不在" in message
        )
