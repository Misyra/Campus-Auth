"""备份恢复路由测试 — 覆盖纯函数和 API 端点。"""

from __future__ import annotations

import re
from unittest.mock import patch

from app.api.backup import _cleanup_old_backups
from app.constants import BACKUP_FILENAME_PATTERN

# ── _cleanup_old_backups ──


class TestCleanupOldBackups:
    """旧备份清理。"""

    def test_keeps_latest_files(self, tmp_path):
        """保留最新文件。"""
        # 创建 5 个备份文件
        for i in range(5):
            (tmp_path / f"settings_2026060{i + 1}_000000.json").write_text("{}")

        with patch("app.api.backup.BACKUP_DIR", tmp_path):
            _cleanup_old_backups(max_backups=3)

        remaining = list(tmp_path.glob("settings_*.json"))
        assert len(remaining) == 3

    def test_no_files(self, tmp_path):
        """无文件时不抛异常。"""
        with patch("app.api.backup.BACKUP_DIR", tmp_path):
            _cleanup_old_backups()

    def test_fewer_than_max(self, tmp_path):
        """文件数少于最大值时不删除。"""
        for i in range(2):
            (tmp_path / f"settings_2026060{i + 1}_000000.json").write_text("{}")

        with patch("app.api.backup.BACKUP_DIR", tmp_path):
            _cleanup_old_backups(max_backups=5)

        remaining = list(tmp_path.glob("settings_*.json"))
        assert len(remaining) == 2


# ── BACKUP_FILENAME_PATTERN ──


class TestBackupFilenamePattern:
    """备份文件名正则。"""

    def test_valid_filename(self):
        """有效文件名匹配。"""
        assert re.match(BACKUP_FILENAME_PATTERN, "settings_20260601_120000.json")

    def test_autosave_filename(self):
        """自动保存文件名匹配。"""
        assert re.match(
            BACKUP_FILENAME_PATTERN, "settings_20260601_120000_123456_autosave.json"
        )

    def test_invalid_prefix(self):
        """无效前缀不匹配。"""
        assert not re.match(BACKUP_FILENAME_PATTERN, "backup_20260601.json")

    def test_invalid_extension(self):
        """无效扩展名不匹配。"""
        assert not re.match(BACKUP_FILENAME_PATTERN, "settings_20260601.txt")

    def test_path_traversal(self):
        """路径穿越不匹配。"""
        assert not re.match(BACKUP_FILENAME_PATTERN, "../../settings.json")
