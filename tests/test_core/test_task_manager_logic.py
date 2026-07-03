"""任务管理器逻辑测试 — 覆盖 is_valid_task_id 和 normalize_task_id。"""

from __future__ import annotations

from app.tasks.manager import is_valid_task_id, normalize_task_id

# ── is_valid_task_id ──


class TestIsValidTaskId:
    """任务 ID 验证。"""

    def test_valid_ids(self):
        """有效 ID。"""
        assert is_valid_task_id("login") is True
        assert is_valid_task_id("task1") is True
        assert is_valid_task_id("my_task") is True
        assert is_valid_task_id("A") is True

    def test_invalid_ids(self):
        """无效 ID。"""
        assert is_valid_task_id("") is False
        assert is_valid_task_id("my task") is False
        assert is_valid_task_id("my.task") is False
        assert is_valid_task_id("a" * 65) is False  # 超过 64 字符上限

    def test_valid_ids_new_pattern(self):
        """新规则下允许的 ID。"""
        assert is_valid_task_id("123") is True
        assert is_valid_task_id("_task") is True
        assert is_valid_task_id("my-task") is True

    def test_numbers_allowed_after_first_char(self):
        """首字符后允许数字。"""
        assert is_valid_task_id("t123") is True

    def test_underscore_allowed_after_first_char(self):
        """首字符后允许下划线。"""
        assert is_valid_task_id("t_123") is True


# ── normalize_task_id ──


class TestNormalizeTaskId:
    """任务 ID 标准化。"""

    def test_strip_whitespace(self):
        """去除首尾空格。"""
        assert normalize_task_id("  login  ") == "login"

    def test_empty_string(self):
        """空字符串。"""
        assert normalize_task_id("") == ""

    def test_already_normalized(self):
        """已标准化的 ID 不变。"""
        assert normalize_task_id("login") == "login"

    def test_none_returns_empty(self):
        """None 返回空字符串。"""
        assert normalize_task_id(None) == ""

    def test_non_string_returns_empty(self):
        """非字符串返回空字符串。"""
        assert normalize_task_id(123) == ""

    def test_preserves_case(self):
        """保留大小写。"""
        assert normalize_task_id("MyTask") == "MyTask"
