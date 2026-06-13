"""验证 shell_policy.py 两个 bug 修复。"""

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
            # 修复前：`None or 0` == 0，错误地返回 0
            # 修复后：应返回 -1
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


class TestDocstringConsistency:
    """Bug 2: docstring 中的超时上限应与 _MAX_TIMEOUT 常量一致。"""

    def test_max_timeout_is_3600(self):
        """确认 _MAX_TIMEOUT 常量为 3600。"""
        assert _MAX_TIMEOUT == 3600

    def test_class_docstring_mentions_correct_timeout(self):
        """类 docstring 应引用 3600 而非 300。"""
        doc = ShellCommandPolicy.__doc__
        # 修复后 docstring 应包含 3600
        assert "3600" in doc, f"docstring 中未找到 '3600': {doc}"

    def test_init_docstring_mentions_correct_timeout(self):
        """__init__ docstring 应引用 3600 而非 300。"""
        doc = ShellCommandPolicy.__init__.__doc__
        assert "3600" in doc, f"__init__ docstring 中未找到 '3600': {doc}"

    def test_run_docstring_mentions_correct_timeout(self):
        """run docstring 应引用 3600 而非 300。"""
        doc = ShellCommandPolicy.run.__doc__
        assert "3600" in doc, f"run docstring 中未找到 '3600': {doc}"

    def test_run_sync_docstring_mentions_correct_timeout(self):
        """run_sync docstring 应引用 3600 而非 300。"""
        doc = ShellCommandPolicy.run_sync.__doc__
        assert "3600" in doc, f"run_sync docstring 中未找到 '3600': {doc}"

    def test_clamp_timeout_docstring_mentions_correct_timeout(self):
        """_clamp_timeout docstring 应引用 3600 而非 300。"""
        doc = ShellCommandPolicy._clamp_timeout.__doc__
        assert "3600" in doc, f"_clamp_timeout docstring 中未找到 '3600': {doc}"
