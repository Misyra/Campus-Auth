"""工具路由测试 — 覆盖纯函数和常量。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from app.api.tools import (
    ALLOWED_EXTENSIONS,
    MAX_FILE_SIZE,
    _cleanup_old_backgrounds,
)

# ── 常量 ──


class TestConstants:
    """常量定义。"""

    def test_allowed_extensions(self):
        """允许的扩展名。"""
        assert ".jpg" in ALLOWED_EXTENSIONS
        assert ".jpeg" in ALLOWED_EXTENSIONS
        assert ".png" in ALLOWED_EXTENSIONS
        assert ".gif" in ALLOWED_EXTENSIONS
        assert ".webp" in ALLOWED_EXTENSIONS
        assert ".exe" not in ALLOWED_EXTENSIONS

    def test_max_file_size(self):
        """最大文件大小 5MB。"""
        assert MAX_FILE_SIZE == 5 * 1024 * 1024


# ── _cleanup_old_backgrounds ──


class TestCleanupOldBackgrounds:
    """旧背景清理。"""

    def test_removes_other_files(self, tmp_path):
        """删除其他文件。"""
        (tmp_path / "old.jpg").write_bytes(b"old")
        (tmp_path / "keep.jpg").write_bytes(b"keep")

        with patch("app.api.tools.BG_DIR", tmp_path):
            _cleanup_old_backgrounds("keep.jpg")

        assert not (tmp_path / "old.jpg").exists()
        assert (tmp_path / "keep.jpg").exists()

    def test_no_files(self, tmp_path):
        """无文件时不抛异常。"""
        with patch("app.api.tools.BG_DIR", tmp_path):
            _cleanup_old_backgrounds("keep.jpg")

    def test_empty_exclude(self, tmp_path):
        """空排除名删除所有。"""
        (tmp_path / "test.jpg").write_bytes(b"test")

        with patch("app.api.tools.BG_DIR", tmp_path):
            _cleanup_old_backgrounds("")

        assert not (tmp_path / "test.jpg").exists()


# ── 路径安全 ──


class TestPathSafety:
    """路径安全校验。"""

    def test_path_traversal_detection(self):
        """路径穿越检测。"""
        # Path.name 提取文件名，防止穿越
        filename = "../../etc/passwd"
        safe_name = Path(filename).name
        assert safe_name == "passwd"
        assert safe_name != filename

    def test_normal_filename(self):
        """正常文件名。"""
        filename = "test.jpg"
        safe_name = Path(filename).name
        assert safe_name == filename
