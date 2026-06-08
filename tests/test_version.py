"""版本工具测试 — 覆盖 get_project_version 和 compare_versions。"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.version import get_project_version, compare_versions


# ── get_project_version ──


class TestGetProjectVersion:
    """项目版本读取。"""

    def test_reads_version(self):
        """读取版本号。"""
        version = get_project_version()
        assert version != "unknown"
        assert "." in version  # 语义版本格式

    def test_custom_root(self, tmp_path):
        """自定义项目根目录。"""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text('[project]\nversion = "1.2.3"\n', encoding="utf-8")
        # 清除缓存
        get_project_version.cache_clear()
        version = get_project_version(tmp_path)
        assert version == "1.2.3"

    def test_missing_file(self, tmp_path):
        """文件不存在返回 unknown。"""
        get_project_version.cache_clear()
        version = get_project_version(tmp_path)
        assert version == "unknown"

    def test_no_version_field(self, tmp_path):
        """无 version 字段返回 unknown。"""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text('[project]\nname = "test"\n', encoding="utf-8")
        get_project_version.cache_clear()
        version = get_project_version(tmp_path)
        assert version == "unknown"

    def test_version_outside_project_block(self, tmp_path):
        """version 在 [project] 块外被忽略。"""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text('version = "0.0.1"\n\n[project]\nname = "test"\n', encoding="utf-8")
        get_project_version.cache_clear()
        version = get_project_version(tmp_path)
        assert version == "unknown"


# ── compare_versions ──


class TestCompareVersions:
    """版本比较。"""

    def test_equal(self):
        """相等。"""
        assert compare_versions("1.0.0", "1.0.0") == 0

    def test_greater_major(self):
        """主版本号更大。"""
        assert compare_versions("2.0.0", "1.0.0") == 1

    def test_less_major(self):
        """主版本号更小。"""
        assert compare_versions("1.0.0", "2.0.0") == -1

    def test_greater_minor(self):
        """次版本号更大。"""
        assert compare_versions("1.2.0", "1.1.0") == 1

    def test_less_minor(self):
        """次版本号更小。"""
        assert compare_versions("1.1.0", "1.2.0") == -1

    def test_greater_patch(self):
        """补丁版本号更大。"""
        assert compare_versions("1.0.2", "1.0.1") == 1

    def test_less_patch(self):
        """补丁版本号更小。"""
        assert compare_versions("1.0.1", "1.0.2") == -1

    def test_different_lengths(self):
        """不同长度版本号。"""
        assert compare_versions("1.0", "1.0.0") == 0
        assert compare_versions("1.0.0", "1.0") == 0
        assert compare_versions("1.0.1", "1.0") == 1

    def test_invalid_version_returns_zero(self):
        """无效版本号返回 0。"""
        assert compare_versions("invalid", "1.0.0") == 0
        assert compare_versions("1.0.0", "invalid") == 0
        assert compare_versions("invalid", "invalid") == 0

    def test_single_segment(self):
        """单段版本号。"""
        assert compare_versions("2", "1") == 1
        assert compare_versions("1", "2") == -1
        assert compare_versions("1", "1") == 0
