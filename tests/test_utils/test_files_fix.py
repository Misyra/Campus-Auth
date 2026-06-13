"""测试 atomic_write 跨文件系统修复。

验证临时文件与目标文件在同一目录下创建，
避免 os.replace 跨文件系统失败。
"""

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from app.utils.files import atomic_write


class TestAtomicWriteCrossFilesystem:
    """测试 atomic_write 的跨文件系统兼容性。"""

    def test_temp_file_created_in_target_directory(self, tmp_path: Path):
        """验证临时文件在目标文件所在目录创建。"""
        target = tmp_path / "test.txt"
        captured_dir = None

        original_mkstemp = tempfile.mkstemp

        def mock_mkstemp(**kwargs):
            nonlocal captured_dir
            captured_dir = kwargs.get("dir")
            return original_mkstemp(**kwargs)

        with patch("app.utils.files.tempfile.mkstemp", side_effect=mock_mkstemp):
            atomic_write(target, "hello")

        # 临时文件应在目标目录中创建
        assert captured_dir == str(tmp_path)

    def test_temp_file_created_in_parent_for_relative_path(self):
        """验证相对路径时临时文件在当前目录创建（而非系统临时目录）。"""
        captured_dir = None
        original_mkstemp = tempfile.mkstemp

        def mock_mkstemp(**kwargs):
            nonlocal captured_dir
            captured_dir = kwargs.get("dir")
            return original_mkstemp(**kwargs)

        with patch("app.utils.files.tempfile.mkstemp", side_effect=mock_mkstemp):
            # 使用相对路径，parent 为空字符串
            atomic_write("test_relative_file.txt", "hello")
            # 清理
            if os.path.exists("test_relative_file.txt"):
                os.unlink("test_relative_file.txt")

        # 应为 "."（当前目录），而非 None（系统临时目录）
        assert captured_dir == "."
