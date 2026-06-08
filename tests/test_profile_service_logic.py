"""配置方案服务逻辑测试 — 覆盖纯逻辑函数。"""

from __future__ import annotations

import pytest


# ── ProfileService 初始化 ──


class TestProfileServiceInit:
    """ProfileService 初始化。"""

    def test_import(self):
        """可导入。"""
        from app.services.profile import ProfileService
        assert ProfileService is not None

    def test_settings_file_constant(self):
        """设置文件常量。"""
        from app.services.profile import _SETTINGS_FILE
        assert _SETTINGS_FILE == "settings.json"
