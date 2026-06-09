"""登录历史路由测试 — 覆盖常量和纯逻辑。"""

from __future__ import annotations

# ── 登录历史路由常量 ──


class TestHistoryConstants:
    """登录历史路由相关常量。"""

    def test_login_history_entry_importable(self):
        """LoginHistoryEntry 可导入。"""
        from app.services.login_history import LoginHistoryEntry
        assert LoginHistoryEntry is not None

    def test_login_history_service_importable(self):
        """LoginHistoryService 可导入。"""
        from app.services.login_history import LoginHistoryService
        assert LoginHistoryService is not None
