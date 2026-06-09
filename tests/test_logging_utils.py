"""日志工具测试 — 覆盖纯逻辑函数。"""

from __future__ import annotations

from app.utils.logging import VALID_LOG_LEVELS, normalize_level

# ── VALID_LOG_LEVELS ──


class TestValidLogLevels:
    """有效日志级别。"""

    def test_contains_standard_levels(self):
        """包含标准级别。"""
        assert "DEBUG" in VALID_LOG_LEVELS
        assert "INFO" in VALID_LOG_LEVELS
        assert "WARNING" in VALID_LOG_LEVELS
        assert "ERROR" in VALID_LOG_LEVELS
        assert "CRITICAL" in VALID_LOG_LEVELS

    def test_count(self):
        """级别数量。"""
        assert len(VALID_LOG_LEVELS) == 5


# ── normalize_level ──


class TestNormalizeLevel:
    """日志级别标准化。"""

    def test_uppercase(self):
        """转大写。"""
        assert normalize_level("info") == "INFO"
        assert normalize_level("debug") == "DEBUG"
        assert normalize_level("warning") == "WARNING"
        assert normalize_level("error") == "ERROR"

    def test_already_upper(self):
        """已是大写。"""
        assert normalize_level("INFO") == "INFO"

    def test_mixed_case(self):
        """混合大小写。"""
        assert normalize_level("Info") == "INFO"
        assert normalize_level("WARNING") == "WARNING"

    def test_whitespace_trimmed(self):
        """去除首尾空格。"""
        assert normalize_level("  INFO  ") == "INFO"

    def test_empty_string_returns_default(self):
        """空字符串返回默认值 INFO。"""
        assert normalize_level("") == "INFO"

    def test_invalid_level_returns_default(self):
        """无效级别返回默认值 INFO。"""
        assert normalize_level("INVALID") == "INFO"

    def test_none_returns_default(self):
        """None 返回默认值 INFO。"""
        assert normalize_level(None) == "INFO"

    def test_custom_default(self):
        """自定义默认值。"""
        assert normalize_level("INVALID", default="DEBUG") == "DEBUG"
        assert normalize_level("", default="ERROR") == "ERROR"
