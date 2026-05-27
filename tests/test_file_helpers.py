"""src/utils/file_helpers.py 测试"""
from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from src.utils.file_helpers import atomic_write


class TestAtomicWrite:
    def test_basic_write(self, tmp_path):
        """基本写入应成功"""
        target = tmp_path / "test.txt"
        atomic_write(str(target), "hello world")
        assert target.read_text(encoding="utf-8") == "hello world"

    def test_creates_parent_dirs(self, tmp_path):
        """应自动创建父目录"""
        target = tmp_path / "a" / "b" / "c" / "test.txt"
        atomic_write(str(target), "nested")
        assert target.read_text(encoding="utf-8") == "nested"

    def test_overwrite_existing(self, tmp_path):
        """应覆盖已有文件"""
        target = tmp_path / "test.txt"
        target.write_text("old", encoding="utf-8")
        atomic_write(str(target), "new")
        assert target.read_text(encoding="utf-8") == "new"

    def test_empty_content(self, tmp_path):
        """空内容应正常写入"""
        target = tmp_path / "empty.txt"
        atomic_write(str(target), "")
        assert target.read_text(encoding="utf-8") == ""

    def test_unicode_content(self, tmp_path):
        """中文内容应正常写入"""
        target = tmp_path / "中文.txt"
        atomic_write(str(target), "校园网认证")
        assert target.read_text(encoding="utf-8") == "校园网认证"

    def test_permission_error_fallback(self, tmp_path):
        """os.replace 抛 PermissionError 时应回退到直接写入"""
        target = tmp_path / "test.txt"
        original_replace = os.replace

        def mock_replace(src, dst):
            raise PermissionError("mocked")

        with patch("src.utils.file_helpers.os.replace", side_effect=mock_replace):
            atomic_write(str(target), "fallback content")
        assert target.read_text(encoding="utf-8") == "fallback content"

    def test_cleanup_on_write_error(self, tmp_path):
        """写入失败时应抛出异常（临时文件清理由 os.unlink 处理）"""
        target = tmp_path / "test.txt"
        with patch("src.utils.file_helpers.os.fdopen", side_effect=IOError("disk full")):
            with pytest.raises(IOError, match="disk full"):
                atomic_write(str(target), "content")
        # 目标文件不应被创建
        assert not target.exists()

    def test_no_parent_dir(self, tmp_path):
        """无父目录时应正常工作（当前目录写入）"""
        import os
        old_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            atomic_write("relative.txt", "relative")
            assert (tmp_path / "relative.txt").read_text(encoding="utf-8") == "relative"
        finally:
            os.chdir(old_cwd)
