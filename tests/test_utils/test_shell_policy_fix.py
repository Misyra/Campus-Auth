"""验证 shell_policy.py 两个 bug 修复 — 行为验证版本。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.utils.shell_policy import _MAX_TIMEOUT, ShellCommandPolicy


class TestReturncodeNoneBug:
    """Bug 1: proc.returncode 为 None 时应返回 -1，不是 0。"""

    @pytest.mark.asyncio
    async def test_async_returncode_none_returns_minus_one(self):
        """异步 run 当 proc.returncode 为 None 时应返回 -1。"""
        policy = ShellCommandPolicy(allowlist=["/bin/sh"])

        mock_proc = MagicMock()
        mock_proc.communicate = AsyncMock(return_value=(b"out", b"err"))
        mock_proc.returncode = None  # 异常状态

        with patch(
            "app.utils.shell_policy.asyncio.create_subprocess_exec",
            return_value=mock_proc,
        ):
            code, _, _ = await policy.run(["/bin/sh", "-c", "test"])
            assert code == -1, (
                f"proc.returncode=None 时应返回 -1，实际返回 {code}"
            )

    @pytest.mark.asyncio
    async def test_async_returncode_zero_still_works(self):
        """异步 run 正常返回 0 不受影响。"""
        policy = ShellCommandPolicy(allowlist=["/bin/sh"])

        mock_proc = MagicMock()
        mock_proc.communicate = AsyncMock(return_value=(b"ok", b""))
        mock_proc.returncode = 0

        with patch(
            "app.utils.shell_policy.asyncio.create_subprocess_exec",
            return_value=mock_proc,
        ):
            code, out, _ = await policy.run(["/bin/sh", "-c", "echo ok"])
            assert code == 0
            assert out == "ok"

    @pytest.mark.asyncio
    async def test_async_returncode_negative_preserved(self):
        """异步 run 负返回码应原样保留（不被 `or 0` 吞掉）。"""
        policy = ShellCommandPolicy(allowlist=["/bin/sh"])

        mock_proc = MagicMock()
        mock_proc.communicate = AsyncMock(return_value=(b"", b"err"))
        mock_proc.returncode = -9

        with patch(
            "app.utils.shell_policy.asyncio.create_subprocess_exec",
            return_value=mock_proc,
        ):
            code, _, _ = await policy.run(["/bin/sh", "-c", "kill"])
            assert code == -9


class TestTimeoutBehavior:
    """Bug 2: 超时上限应为 _MAX_TIMEOUT (3600)，验证实际 clamp 行为。"""

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

    def test_default_timeout_clamped_to_max(self):
        """构造函数中 default_timeout 超过 _MAX_TIMEOUT 时被 clamp。"""
        policy = ShellCommandPolicy(allowlist=["/bin/sh"], default_timeout=99999)
        assert policy._default_timeout == _MAX_TIMEOUT

    def test_default_timeout_within_range_preserved(self):
        """构造函数中 default_timeout 在有效范围内时保留原值。"""
        policy = ShellCommandPolicy(allowlist=["/bin/sh"], default_timeout=120)
        assert policy._default_timeout == 120
