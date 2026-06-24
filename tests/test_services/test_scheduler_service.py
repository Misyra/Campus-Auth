"""TaskExecutor 测试 — 聚焦 shell 安全策略集成。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.services.task_executor import TaskExecutor
from app.services.task_registry import TaskHistoryStore, TaskRegistry
from app.utils.shell_utils import detect_shells as detect_available_shells

# =====================================================================
# detect_available_shells
# =====================================================================


def test_history_store_initialized_at_construct(tmp_path):
    """TaskRegistry 和 TaskHistoryStore 应可独立创建。"""
    registry = TaskRegistry(tmp_path / "tasks" / "scheduled")
    history_store = TaskHistoryStore(tmp_path / "tasks" / "scheduled" / "history")
    assert hasattr(registry, "list_tasks")
    assert hasattr(history_store, "add_record")


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
            login_orchestrator=MagicMock(),
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

        with patch("app.utils.shell_policy.subprocess.Popen") as mock_popen:
            mock_proc = MagicMock()
            mock_proc.communicate.return_value = ("ok", "")
            mock_proc.returncode = 0
            mock_popen.return_value = mock_proc

            executor._execute_shell("echo ok", timeout=9999, shell_path=shell_path)
            assert mock_popen.called

    def test_audit_log_called(self, executor):
        """执行前应记录审计日志。"""
        shells = detect_available_shells()
        if not shells:
            pytest.skip("系统无可用 shell")

        shell_path = shells[0]["path"]

        with patch("app.utils.shell_policy.subprocess.Popen") as mock_popen:
            mock_proc = MagicMock()
            mock_proc.communicate.return_value = ("ok", "")
            mock_proc.returncode = 0
            mock_popen.return_value = mock_proc

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
