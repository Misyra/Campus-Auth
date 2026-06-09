"""文件辅助工具测试 — 覆盖 atomic_write。"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.utils.file_helpers import atomic_write

# ── atomic_write ──


class TestAtomicWrite:
    """原子写入。"""

    def test_basic_write(self, tmp_path):
        """基本写入。"""
        filepath = str(tmp_path / "test.txt")
        atomic_write(filepath, "hello world")
        assert Path(filepath).read_text(encoding="utf-8") == "hello world"

    def test_creates_parent_dirs(self, tmp_path):
        """自动创建父目录。"""
        filepath = str(tmp_path / "sub" / "dir" / "test.txt")
        atomic_write(filepath, "nested")
        assert Path(filepath).read_text(encoding="utf-8") == "nested"

    def test_overwrites_existing(self, tmp_path):
        """覆盖已有文件。"""
        filepath = str(tmp_path / "test.txt")
        atomic_write(filepath, "first")
        atomic_write(filepath, "second")
        assert Path(filepath).read_text(encoding="utf-8") == "second"

    def test_unicode_content(self, tmp_path):
        """Unicode 内容。"""
        filepath = str(tmp_path / "test.txt")
        atomic_write(filepath, "中文测试")
        assert Path(filepath).read_text(encoding="utf-8") == "中文测试"

    def test_empty_content(self, tmp_path):
        """空内容。"""
        filepath = str(tmp_path / "test.txt")
        atomic_write(filepath, "")
        assert Path(filepath).read_text(encoding="utf-8") == ""

    def test_prefix_too_long(self, tmp_path):
        """前缀过长抛异常。"""
        filepath = str(tmp_path / "test.txt")
        with pytest.raises(ValueError, match="prefix/suffix"):
            atomic_write(filepath, "test", prefix="toolong")

    def test_suffix_too_long(self, tmp_path):
        """后缀过长抛异常。"""
        filepath = str(tmp_path / "test.txt")
        with pytest.raises(ValueError, match="prefix/suffix"):
            atomic_write(filepath, "test", suffix="toolong")

    def test_custom_encoding(self, tmp_path):
        """自定义编码。"""
        filepath = str(tmp_path / "test.txt")
        atomic_write(filepath, "test", encoding="gbk")
        assert Path(filepath).read_text(encoding="gbk") == "test"

    def test_replace_errors(self, tmp_path):
        """编码错误处理。"""
        filepath = str(tmp_path / "test.txt")
        # 使用 replace 错误处理
        atomic_write(filepath, "test", encoding="ascii", errors="replace")
        assert Path(filepath).read_text(encoding="ascii") == "test"
