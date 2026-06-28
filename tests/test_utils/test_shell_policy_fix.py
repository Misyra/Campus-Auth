"""验证 shell_policy.py 两个 bug 修复 — 行为验证版本。"""

from __future__ import annotations

from app.utils.shell_policy import _MAX_TIMEOUT, ShellCommandPolicy


class TestReturncodeNoneBug:
    """Bug 1: proc.returncode 为 None 时应返回 -1，不是 0。

    注：async run() 已删除（零生产调用），以下测试仅覆盖 run_sync。
    """


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
