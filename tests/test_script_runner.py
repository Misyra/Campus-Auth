"""script_runner 模块测试

覆盖 PowerShell 单引号转义等辅助函数。
"""
from __future__ import annotations

import pytest

from src.script_runner import _escape_ps_single_quote


class TestEscapePsSingleQuote:
    """P1-SR-3: PowerShell 单引号转义测试。"""

    def test_no_single_quotes(self):
        """不含单引号的字符串应原样返回。"""
        assert _escape_ps_single_quote(r"C:\path\to\script") == r"C:\path\to\script"

    def test_single_quote_in_path(self):
        """路径中的单引号应被转义为两个连续单引号。"""
        input_path = r"C:\path\o's\script"
        expected = r"C:\path\o''s\script"
        assert _escape_ps_single_quote(input_path) == expected

    def test_multiple_single_quotes(self):
        """多个单引号应全部被转义。"""
        input_str = "it's a test's path"
        expected = "it''s a test''s path"
        assert _escape_ps_single_quote(input_str) == expected

    def test_empty_string(self):
        """空字符串应返回空字符串。"""
        assert _escape_ps_single_quote("") == ""

    def test_already_escaped(self):
        """已转义的单引号（''）应被再次转义为四个单引号。"""
        # 注意：这是幂等的 —— 每个 ' 都变成 ''
        input_str = "a''b"
        expected = "a''''b"
        assert _escape_ps_single_quote(input_str) == expected
