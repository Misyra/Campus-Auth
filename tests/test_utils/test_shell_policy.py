"""ShellCommandPolicy 安全策略测试。"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

from app.utils.shell_policy import _MAX_TIMEOUT, _MIN_TIMEOUT, ShellCommandPolicy

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


# =====================================================================
# 超时钳制
# =====================================================================


class TestTimeoutClamp:
    """测试超时值钳制逻辑。"""

    def test_default_timeout_clamped(self):
        """默认超时应被钳制到 [1, 3600] 范围。"""
        policy = ShellCommandPolicy(allowlist=["/bin/sh"], default_timeout=9999)
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
        ok, timeout, _ = policy.validate_and_prepare("/bin/sh", timeout=9999)
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
        mock_proc = MagicMock()
        mock_proc.communicate.return_value = ("hello", "")
        mock_proc.returncode = 0
        with patch("app.utils.shell_policy.subprocess.Popen", return_value=mock_proc):
            code, out, err = policy.run_sync(["/bin/sh", "-c", "echo hello"])
            assert code == 0
            assert out == "hello"

    def test_timeout_expired_returns_minus_one(self):
        """超时应返回 returncode=-1 并清理进程树。"""
        import subprocess as sp

        policy = ShellCommandPolicy(allowlist=["/bin/sh"])
        mock_proc = MagicMock()
        mock_proc.pid = 12345
        mock_proc.communicate.side_effect = sp.TimeoutExpired(cmd="/bin/sh", timeout=1)
        with (
            patch("app.utils.shell_policy.subprocess.Popen", return_value=mock_proc),
            patch.object(policy, "_kill_process_tree_sync") as mock_kill,
        ):
            code, out, err = policy.run_sync(["/bin/sh", "-c", "sleep 999"])
            assert code == -1
            assert "超时" in err
            mock_kill.assert_called_once_with(12345)

    def test_file_not_found_returns_minus_one(self):
        """文件不存在应返回 returncode=-1。"""
        policy = ShellCommandPolicy(allowlist=["/nonexistent/bin"])
        with patch("app.utils.shell_policy.subprocess.Popen") as mock_popen:
            mock_popen.side_effect = FileNotFoundError()
            code, out, err = policy.run_sync(["/nonexistent/bin", "-c", "test"])
            assert code == -1
            assert "不存在" in err


# =====================================================================
# _clamp_timeout 边界行为 (from test_shell_policy_fix)
# =====================================================================


class TestClampTimeoutBoundary:
    """_clamp_timeout 方法的边界行为验证。"""

    def test_max_timeout_is_3600(self):
        """确认 _MAX_TIMEOUT 常量为 3600。"""
        assert _MAX_TIMEOUT == 3600

    def test_clamp_timeout_at_max_boundary(self):
        """_clamp_timeout 在 _MAX_TIMEOUT 边界的行为。"""
        policy = ShellCommandPolicy(allowlist=["/bin/sh"])
        assert policy._clamp_timeout(_MAX_TIMEOUT) == _MAX_TIMEOUT
        assert policy._clamp_timeout(_MAX_TIMEOUT + 1) == _MAX_TIMEOUT

    def test_clamp_timeout_at_min_boundary(self):
        """_clamp_timeout 在下界的行为。"""
        policy = ShellCommandPolicy(allowlist=["/bin/sh"])
        assert policy._clamp_timeout(1) == 1
        assert policy._clamp_timeout(0) == 1
        assert policy._clamp_timeout(-10) == 1

    def test_default_timeout_within_range_preserved(self):
        """构造函数中 default_timeout 在有效范围内时保留原值。"""
        policy = ShellCommandPolicy(allowlist=["/bin/sh"], default_timeout=120)
        assert policy._default_timeout == 120
