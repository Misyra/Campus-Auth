"""ShellCommandPolicy 安全策略测试。"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

from src.utils.shell_policy import ShellCommandPolicy, _MAX_TIMEOUT, _MIN_TIMEOUT


# =====================================================================
# 白名单验证
# =====================================================================


class TestAllowlist:
    """测试执行路径白名单验证。"""

    def test_allowed_path_accepted(self):
        """白名单内路径应被接受。"""
        policy = ShellCommandPolicy(allowlist=["/usr/bin/python", "/bin/bash"])
        ok, timeout, err = policy.validate_and_prepare("/usr/bin/python")
        assert ok is True
        assert err == ""

    def test_rejected_path_returns_error(self):
        """不在白名单的路径应被拒绝。"""
        policy = ShellCommandPolicy(allowlist=["/usr/bin/python"])
        ok, timeout, err = policy.validate_and_prepare("/usr/bin/malicious")
        assert ok is False
        assert "白名单" in err

    def test_empty_allowlist_rejects_all(self):
        """空白名单应拒绝所有路径。"""
        policy = ShellCommandPolicy(allowlist=[])
        ok, _, _ = policy.validate_and_prepare("/usr/bin/python")
        assert ok is False

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows 路径大小写测试")
    def test_windows_case_insensitive(self):
        """Windows 路径比较应不区分大小写。"""
        policy = ShellCommandPolicy(allowlist=["C:\\Windows\\System32\\cmd.exe"])
        ok, _, _ = policy.validate_and_prepare("c:\\windows\\system32\\cmd.exe")
        assert ok is True

    def test_run_sync_rejects_not_allowed(self):
        """run_sync 对不在白名单的路径应抛出 PermissionError。"""
        policy = ShellCommandPolicy(allowlist=["/usr/bin/python"])
        with pytest.raises(PermissionError, match="白名单"):
            policy.run_sync(["/usr/bin/malicious", "-c", "pass"])

    @pytest.mark.asyncio
    async def test_run_async_rejects_not_allowed(self):
        """run（异步）对不在白名单的路径应抛出 PermissionError。"""
        policy = ShellCommandPolicy(allowlist=["/usr/bin/python"])
        with pytest.raises(PermissionError, match="白名单"):
            await policy.run(["/usr/bin/malicious", "-c", "pass"])


# =====================================================================
# 超时钳制
# =====================================================================


class TestTimeoutClamp:
    """测试超时值钳制逻辑。"""

    def test_default_timeout_clamped(self):
        """默认超时应被钳制到 [1, 300] 范围。"""
        policy = ShellCommandPolicy(allowlist=["/bin/sh"], default_timeout=500)
        assert policy._default_timeout == _MAX_TIMEOUT

    def test_negative_timeout_clamped_to_min(self):
        """负超时应被钳制到最小值。"""
        policy = ShellCommandPolicy(allowlist=["/bin/sh"], default_timeout=-10)
        assert policy._default_timeout == _MIN_TIMEOUT

    def test_zero_timeout_clamped_to_min(self):
        """零超时应被钳制到最小值 1。"""
        policy = ShellCommandPolicy(allowlist=["/bin/sh"], default_timeout=0)
        assert policy._default_timeout == _MIN_TIMEOUT

    def test_prepare_clamps_runtime_timeout(self):
        """validate_and_prepare 应钳制运行时传入的超时。"""
        policy = ShellCommandPolicy(allowlist=["/bin/sh"], default_timeout=60)
        ok, timeout, _ = policy.validate_and_prepare("/bin/sh", timeout=999)
        assert ok is True
        assert timeout == _MAX_TIMEOUT

    def test_prepare_clamps_low_runtime_timeout(self):
        """validate_and_prepare 应钳制过低的运行时超时。"""
        policy = ShellCommandPolicy(allowlist=["/bin/sh"], default_timeout=60)
        ok, timeout, _ = policy.validate_and_prepare("/bin/sh", timeout=0)
        assert ok is True
        assert timeout == _MIN_TIMEOUT

    def test_prepare_uses_default_when_none(self):
        """timeout=None 时应使用默认值。"""
        policy = ShellCommandPolicy(allowlist=["/bin/sh"], default_timeout=42)
        ok, timeout, _ = policy.validate_and_prepare("/bin/sh", timeout=None)
        assert ok is True
        assert timeout == 42


# =====================================================================
# 审计日志
# =====================================================================


class TestAuditLog:
    """测试执行前审计日志。"""

    def test_audit_hook_called_on_run_sync(self):
        """run_sync 执行时应调用审计钩子。"""
        hook = MagicMock()
        policy = ShellCommandPolicy(
            allowlist=["/bin/sh"],
            default_timeout=30,
            audit_hook=hook,
        )
        # 模拟 subprocess.run 避免真实执行
        with patch("src.utils.shell_policy.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="ok", stderr="")
            policy.run_sync(["/bin/sh", "-c", "echo ok"])

        hook.assert_called_once()
        call_args = hook.call_args[0]
        assert call_args[0] == ["/bin/sh", "-c", "echo ok"]
        assert call_args[1] == 30

    @pytest.mark.asyncio
    async def test_audit_hook_called_on_run_async(self):
        """run（异步）执行时应调用审计钩子。"""
        from unittest.mock import AsyncMock

        hook = MagicMock()
        policy = ShellCommandPolicy(
            allowlist=["/bin/sh"],
            default_timeout=30,
            audit_hook=hook,
        )

        mock_proc = MagicMock()
        mock_proc.communicate = AsyncMock(return_value=(b"ok", b""))
        mock_proc.returncode = 0
        mock_proc.kill = MagicMock()
        mock_proc.wait = MagicMock()

        with patch("src.utils.shell_policy.asyncio.create_subprocess_exec", return_value=mock_proc):
            await policy.run(["/bin/sh", "-c", "echo ok"])

        hook.assert_called_once()

    def test_audit_hook_exception_does_not_propagate(self):
        """审计钩子异常不应影响命令执行。"""
        def bad_hook(argv, timeout):
            raise RuntimeError("hook 故障")

        policy = ShellCommandPolicy(
            allowlist=["/bin/sh"],
            audit_hook=bad_hook,
        )
        with patch("src.utils.shell_policy.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="ok", stderr="")
            # 不应抛出异常
            code, out, err = policy.run_sync(["/bin/sh", "-c", "echo ok"])
            assert code == 0

    def test_no_hook_still_works(self):
        """不设置审计钩子时命令执行应正常。"""
        policy = ShellCommandPolicy(allowlist=["/bin/sh"], audit_hook=None)
        with patch("src.utils.shell_policy.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="ok", stderr="")
            code, out, err = policy.run_sync(["/bin/sh", "-c", "echo ok"])
            assert code == 0


# =====================================================================
# run_sync 完整路径
# =====================================================================


class TestRunSync:
    """测试同步执行路径。"""

    def test_empty_argv_raises_value_error(self):
        """空参数列表应抛出 ValueError。"""
        policy = ShellCommandPolicy(allowlist=["/bin/sh"])
        with pytest.raises(ValueError, match="不能为空"):
            policy.run_sync([])

    def test_success_returns_zero(self):
        """成功执行应返回 returncode=0。"""
        policy = ShellCommandPolicy(allowlist=["/bin/sh"])
        with patch("src.utils.shell_policy.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="hello", stderr="")
            code, out, err = policy.run_sync(["/bin/sh", "-c", "echo hello"])
            assert code == 0
            assert out == "hello"

    def test_timeout_expired_returns_minus_one(self):
        """超时应返回 returncode=-1。"""
        import subprocess as sp

        policy = ShellCommandPolicy(allowlist=["/bin/sh"])
        with patch("src.utils.shell_policy.subprocess.run") as mock_run:
            mock_run.side_effect = sp.TimeoutExpired(cmd="/bin/sh", timeout=1)
            code, out, err = policy.run_sync(["/bin/sh", "-c", "sleep 999"])
            assert code == -1
            assert "超时" in err

    def test_file_not_found_returns_minus_one(self):
        """文件不存在应返回 returncode=-1。"""
        policy = ShellCommandPolicy(allowlist=["/nonexistent/bin"])
        with patch("src.utils.shell_policy.subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError()
            code, out, err = policy.run_sync(["/nonexistent/bin", "-c", "test"])
            assert code == -1
            assert "不存在" in err


# =====================================================================
# run（异步）完整路径
# =====================================================================


class TestRunAsync:
    """测试异步执行路径。"""

    @pytest.mark.asyncio
    async def test_empty_argv_raises_value_error(self):
        """空参数列表应抛出 ValueError。"""
        policy = ShellCommandPolicy(allowlist=["/bin/sh"])
        with pytest.raises(ValueError, match="不能为空"):
            await policy.run([])

    @pytest.mark.asyncio
    async def test_success_returns_zero(self):
        """成功执行应返回 returncode=0。"""
        from unittest.mock import AsyncMock

        policy = ShellCommandPolicy(allowlist=["/bin/sh"])

        mock_proc = MagicMock()
        mock_proc.communicate = AsyncMock(return_value=(b"hello", b""))
        mock_proc.returncode = 0

        with patch("src.utils.shell_policy.asyncio.create_subprocess_exec", return_value=mock_proc):
            code, out, err = await policy.run(["/bin/sh", "-c", "echo hello"])
            assert code == 0
            assert out == "hello"

    @pytest.mark.asyncio
    async def test_timeout_returns_minus_one(self):
        """超时应返回 returncode=-1 并 kill 进程。"""
        import asyncio as _asyncio
        from unittest.mock import AsyncMock

        policy = ShellCommandPolicy(allowlist=["/bin/sh"])

        mock_proc = MagicMock()
        mock_proc.communicate = AsyncMock(side_effect=_asyncio.TimeoutError())
        mock_proc.kill = MagicMock()
        mock_proc.wait = AsyncMock()

        with patch("src.utils.shell_policy.asyncio.create_subprocess_exec", return_value=mock_proc):
            with patch("src.utils.shell_policy.asyncio.wait_for", side_effect=_asyncio.TimeoutError()):
                code, out, err = await policy.run(["/bin/sh", "-c", "sleep 999"])
                assert code == -1
                assert "超时" in err
                mock_proc.kill.assert_called_once()
