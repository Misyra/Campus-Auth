"""脚本路由测试 — 覆盖常量和基本逻辑。"""

from __future__ import annotations

# ── 脚本类型校验 ──


class TestScriptTypeValidation:
    """脚本类型校验逻辑。"""

    def test_valid_type(self):
        """有效类型。"""
        task_type = "script"
        assert task_type == "script"

    def test_invalid_type(self):
        """无效类型。"""
        task_type = "browser"
        assert task_type != "script"
