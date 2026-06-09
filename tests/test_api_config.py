"""配置路由测试 — 覆盖常量和纯逻辑。"""

from __future__ import annotations

# ── 配置路由常量 ──


class TestConfigConstants:
    """配置路由相关常量。"""

    def test_stealth_script_accessible(self):
        """反检测脚本可访问。"""
        from app.utils.browser import STEALTH_INIT_SCRIPT
        assert isinstance(STEALTH_INIT_SCRIPT, str)
        assert len(STEALTH_INIT_SCRIPT) > 0

    def test_config_validator_importable(self):
        """ConfigValidator 可导入。"""
        from app.utils import ConfigValidator
        assert ConfigValidator is not None
