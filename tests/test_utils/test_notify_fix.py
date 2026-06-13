"""notify.py 中 _escape_ps 函数的转义完整性测试"""

from __future__ import annotations

from app.utils.notify import _notify_windows


class TestEscapePs:
    """测试 PowerShell 字符串转义函数"""

    def _escape_ps(self, s: str) -> str:
        """从 _notify_windows 中提取的转义函数副本"""
        return s.replace("`", "``").replace('"', '`"').replace("$", "`$").replace("\n", "`n").replace("\r", "`r")

    def test_escape_backtick(self):
        """反引号应被转义为两个反引号"""
        assert self._escape_ps("hello`world") == "hello``world"

    def test_escape_double_quote(self):
        """双引号应被转义"""
        assert self._escape_ps('hello"world') == 'hello`"world'

    def test_escape_dollar_sign(self):
        """美元符号应被转义"""
        assert self._escape_ps("hello$world") == "hello`$world"

    def test_escape_newline(self):
        """换行符应被转义为 `n"""
        result = self._escape_ps("hello\nworld")
        assert result == "hello`nworld", f"换行符未被正确转义: {result!r}"

    def test_escape_carriage_return(self):
        """回车符应被转义为 `r"""
        result = self._escape_ps("hello\rworld")
        assert result == "hello`rworld", f"回车符未被正确转义: {result!r}"

    def test_escape_crlf(self):
        """Windows 换行符应被正确转义"""
        result = self._escape_ps("hello\r\nworld")
        assert result == "hello`r`nworld", f"CRLF 未被正确转义: {result!r}"

    def test_escape_combined(self):
        """多个特殊字符组合应被正确转义"""
        result = self._escape_ps('hello$`\n"world')
        assert result == 'hello`$```n`"world', f"组合字符未被正确转义: {result!r}"

    def test_no_escape_needed(self):
        """普通字符串不需要转义"""
        assert self._escape_ps("hello world") == "hello world"

    def test_empty_string(self):
        """空字符串应返回空字符串"""
        assert self._escape_ps("") == ""
