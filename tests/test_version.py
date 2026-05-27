"""src/version.py 测试"""
from __future__ import annotations

from pathlib import Path

from src.version import get_project_version


class TestGetProjectVersion:
    def setup_method(self):
        get_project_version.cache_clear()

    def test_valid_pyproject(self, tmp_path):
        """有效 pyproject.toml 应返回版本号"""
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "test"\nversion = "1.2.3"\n'
        )
        assert get_project_version(tmp_path) == "1.2.3"

    def test_missing_file(self, tmp_path):
        """文件不存在应返回 unknown"""
        assert get_project_version(tmp_path) == "unknown"

    def test_no_project_section(self, tmp_path):
        """无 [project] section 应返回 unknown"""
        (tmp_path / "pyproject.toml").write_text('[tool.poetry]\nversion = "1.0.0"\n')
        assert get_project_version(tmp_path) == "unknown"

    def test_no_version_line(self, tmp_path):
        """[project] 中无 version 行应返回 unknown"""
        (tmp_path / "pyproject.toml").write_text('[project]\nname = "test"\n')
        assert get_project_version(tmp_path) == "unknown"

    def test_version_outside_project_section(self, tmp_path):
        """version 在 [project] 之外不应匹配"""
        (tmp_path / "pyproject.toml").write_text(
            'version = "0.0.1"\n\n[project]\nname = "test"\n'
        )
        assert get_project_version(tmp_path) == "unknown"

    def test_lru_cache(self, tmp_path):
        """相同参数应返回缓存结果"""
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nversion = "1.0.0"\n'
        )
        v1 = get_project_version(tmp_path)
        # 修改文件后，缓存应返回旧值
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nversion = "2.0.0"\n'
        )
        v2 = get_project_version(tmp_path)
        assert v1 == "1.0.0"
        assert v2 == "1.0.0"  # 缓存命中

    def test_default_root(self):
        """不传 project_root 时应使用项目根目录"""
        v = get_project_version()
        assert isinstance(v, str)
        assert v != "unknown"  # 项目根目录有 pyproject.toml
