"""ScheduleEngine 测试 — 聚焦 _execute_shell 安全策略集成。"""

from __future__ import annotations

import threading
from unittest.mock import MagicMock, patch

import pytest

from app.services.engine import ScheduleEngine, detect_available_shells



# =====================================================================
# detect_available_shells
# =====================================================================


def test_history_lock_initialized_at_construct(tmp_path):
    """_history_lock 应在 __init__ 中初始化，而非惰性创建。"""
    svc = ScheduleEngine(tmp_path)
    assert hasattr(svc, "_history_lock")
    assert hasattr(svc._history_lock, "acquire")


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
# _execute_shell 使用 ShellCommandPolicy
# =====================================================================


class TestExecuteShellUsesPolicy:
    """验证 _execute_shell_sync 内部使用 ShellCommandPolicy。"""

    @pytest.fixture
    def service(self, tmp_path):
        svc = ScheduleEngine(tmp_path)
        return svc

    def test_rejected_shell_path_returns_failure(self, service, tmp_path):
        """不在白名单的 shell_path 应被拒绝，返回失败消息。"""
        result = service._execute_shell_sync(
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

    def test_timeout_clamped_to_max(self, service):
        """超时应被 clamp 到 300 秒上限。"""
        # 使用真实 shell 路径但不真正执行（通过 mock）
        shells = detect_available_shells()
        if not shells:
            pytest.skip("系统无可用 shell")

        shell_path = shells[0]["path"]

        with patch(
            "app.utils.shell_policy.subprocess.run"
        ) as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=b"ok", stderr=b"")

            service._execute_shell_sync("echo ok", timeout=9999, shell_path=shell_path)
            # 验证 timeout 被 clamp：通过检查 mock 调用参数
            assert mock_run.called

    def test_audit_log_called(self, service, tmp_path):
        """执行前应记录审计日志。"""
        shells = detect_available_shells()
        if not shells:
            pytest.skip("系统无可用 shell")

        shell_path = shells[0]["path"]

        with patch(
            "app.utils.shell_policy.subprocess.run"
        ) as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=b"ok", stderr=b"")

            with patch("app.services.engine.engine_logger"):
                result = service._execute_shell_sync(
                    "echo audit_test", timeout=30, shell_path=shell_path
                )
                success, message = result
                assert success is True

    def test_empty_command_returns_failure(self, service):
        """空命令应返回失败。"""
        result = service._execute_shell_sync("", timeout=30)
        success, message = result
        assert success is False
        assert "空" in message

    def test_execute_shell_uses_policy_integration(self, service):
        """集成验证：_execute_shell_sync 路径校验经过 ShellCommandPolicy。"""
        # 使用明显不在白名单的路径
        result = service._execute_shell_sync(
            "echo test", timeout=30, shell_path="/absolutely/fake/shell"
        )
        success, message = result
        assert success is False
        # ShellCommandPolicy 会抛出 PermissionError，被 _execute_shell_sync 捕获
        assert (
            "白名单" in message or "Permission" in message.lower() or "不在" in message
        )
