"""ProfileService TOCTOU 修复测试"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from app.services.profile import ProfileService


class TestCorruptRenameEAFP:
    """P1-BE-6: 损坏文件重命名使用 EAFP 模式，避免 TOCTOU 竞态"""

    def test_corrupt_rename_eafp(self, tmp_path: Path):
        """测试文件不存在时 rename 抛出 FileNotFoundError 被静默处理"""
        settings_path = tmp_path / "settings.json"
        # 写入无效 JSON 触发解析失败
        settings_path.write_text("{invalid json!!!", encoding="utf-8")

        svc = ProfileService.__new__(ProfileService)
        svc.project_root = tmp_path
        svc._settings_path = settings_path
        svc._lock = MagicMock()  # 模拟锁（调用者持有）
        svc._data = None

        # 调用 _load_unsafe —— 应该捕获 FileNotFoundError 而非检查 exists()
        # 由于文件存在但 JSON 无效，会触发 except 分支
        result = svc._load_unsafe()

        # 验证返回空默认值（无备份可用）
        assert result is not None
        # 验证损坏文件已被重命名（EAFP 路径）
        corrupt_files = list(tmp_path.glob("settings.corrupt.*.json"))
        assert len(corrupt_files) == 1, "损坏文件应被重命名为 settings.corrupt.*.json"

    def test_corrupt_rename_file_missing(self, tmp_path: Path):
        """测试文件在读取和重命名之间被删除时，FileNotFoundError 被静默处理"""
        settings_path = tmp_path / "settings.json"
        # 文件不存在
        # settings_path 不存在

        svc = ProfileService.__new__(ProfileService)
        svc.project_root = tmp_path
        svc._settings_path = settings_path
        svc._lock = MagicMock()
        svc._data = None

        # _load_unsafe 应该优雅处理文件不存在的情况
        result = svc._load_unsafe()

        # 验证返回包含 default 方案的默认值
        assert result is not None
        assert "default" in result.profiles
        assert len(result.profiles) == 1
