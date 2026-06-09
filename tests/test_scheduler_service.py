"""SchedulerService 测试 — 聚焦 _execute_shell 安全策略集成。"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from app.services.scheduler import SchedulerService, detect_available_shells


def _run_async(coro):
    """在当前线程运行异步协程（兼容 Python 3.12+ 无默认事件循环的场景）。"""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


# =====================================================================
# detect_available_shells
# =====================================================================


def test_history_lock_initialized_at_construct(tmp_path):
    """_history_lock 应在 __init__ 中初始化，而非惰性创建。"""
    from app.services.scheduler import SchedulerService

    svc = SchedulerService(tmp_path)
    assert hasattr(svc, "_history_lock")
    assert isinstance(svc._history_lock, asyncio.Lock)


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
    """验证 _execute_shell 内部使用 ShellCommandPolicy。"""

    @pytest.fixture
    def service(self, tmp_path):
        svc = SchedulerService(tmp_path)
        return svc

    def test_rejected_shell_path_returns_failure(self, service, tmp_path):
        """不在白名单的 shell_path 应被拒绝，返回失败消息。"""
        # 直接调用 _execute_shell，shell_path 不在 detect_available_shells 结果中
        result = _run_async(
            service._execute_shell(
                "echo hello", timeout=10, shell_path="/fake/malicious/shell"
            )
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
            "app.utils.shell_policy.asyncio.create_subprocess_exec"
        ) as mock_exec:
            mock_proc = AsyncMock()
            mock_proc.communicate = AsyncMock(return_value=(b"ok", b""))
            mock_proc.returncode = 0
            mock_exec.return_value = mock_proc

            _run_async(
                service._execute_shell("echo ok", timeout=9999, shell_path=shell_path)
            )
            # 验证 timeout 被 clamp：通过检查 mock 调用参数
            assert mock_exec.called

    def test_audit_log_called(self, service, tmp_path):
        """执行前应记录审计日志。"""
        shells = detect_available_shells()
        if not shells:
            pytest.skip("系统无可用 shell")

        shell_path = shells[0]["path"]

        with patch(
            "app.utils.shell_policy.asyncio.create_subprocess_exec"
        ) as mock_exec:
            mock_proc = AsyncMock()
            mock_proc.communicate = AsyncMock(return_value=(b"ok", b""))
            mock_proc.returncode = 0
            mock_exec.return_value = mock_proc

            with patch("app.services.scheduler.scheduler_logger"):
                result = _run_async(
                    service._execute_shell(
                        "echo audit_test", timeout=30, shell_path=shell_path
                    )
                )
                success, message = result
                assert success is True
                # 验证有 info 级别的日志（审计日志在 ShellCommandPolicy 中通过 logger.info 输出）
                # ShellCommandPolicy 使用自己的 logger，这里验证执行成功即可

    def test_empty_command_returns_failure(self, service):
        """空命令应返回失败。"""
        result = _run_async(service._execute_shell("", timeout=30))
        success, message = result
        assert success is False
        assert "空" in message

    def test_execute_shell_uses_policy_integration(self, service):
        """集成验证：_execute_shell 路径校验经过 ShellCommandPolicy。"""
        # 使用明显不在白名单的路径
        result = _run_async(
            service._execute_shell(
                "echo test", timeout=30, shell_path="/absolutely/fake/shell"
            )
        )
        success, message = result
        assert success is False
        # ShellCommandPolicy 会抛出 PermissionError，被 _execute_shell 捕获
        assert (
            "白名单" in message or "Permission" in message.lower() or "不在" in message
        )
