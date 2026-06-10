"""备份路由 API 测试 — 覆盖纯函数、常量和 API 端点。"""

from __future__ import annotations

import json
import re
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.api.backup import _cleanup_old_backups
from app.constants import BACKUP_FILENAME_PATTERN
from app.schemas import ProfilesData, ProfileSettings, SystemSettings


@pytest.fixture
def client(tmp_path):
    """创建测试客户端，使用临时备份目录。"""
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir(exist_ok=True)

    (tmp_path / "frontend").mkdir(exist_ok=True)
    (tmp_path / "frontend" / "index.html").write_text("<html></html>")
    (tmp_path / "logs").mkdir(exist_ok=True)
    (tmp_path / "temp").mkdir(exist_ok=True)

    # 写入默认设置文件
    settings_data = {
        "system": {
            "username": "testuser",
            "password": "ENC:test",
            "auth_url": "http://10.0.0.1",
        },
        "profiles": {"default": {"name": "默认方案"}},
    }
    (tmp_path / "settings.json").write_text(
        json.dumps(settings_data, ensure_ascii=False), encoding="utf-8"
    )

    with (
        patch("app.constants.PROJECT_ROOT", tmp_path),
        patch("app.constants.FRONTEND_DIR", tmp_path / "frontend"),
        patch("app.constants.LOGS_DIR", tmp_path / "logs"),
        patch("app.constants.TEMP_DIR", tmp_path / "temp"),
        patch("app.constants.BACKUP_DIR", backup_dir),
        patch("app.api.backup.BACKUP_DIR", backup_dir),
        patch("app.api.backup.PROJECT_ROOT", tmp_path),
    ):
        from app.application import create_app

        mock_services = MagicMock()

        # profile_service mock
        profile_data = ProfilesData(
            system=SystemSettings(username="testuser", password="ENC:test"),
            profiles={"default": ProfileSettings(name="默认方案")},
        )
        mock_services.profile_service.load.return_value = profile_data
        mock_services.profile_service.invalidate_cache = MagicMock()
        mock_services.engine.reload_config = MagicMock()

        app = create_app()
        app.state.services = mock_services

        test_client = TestClient(app)
        yield test_client, backup_dir, tmp_path


# ── 列出备份 ──


class TestListBackups:
    """GET /api/backup/list"""

    def test_list_empty(self, client):
        """无备份时返回空列表。"""
        test_client, _, _ = client
        resp = test_client.get("/api/backup/list")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_with_backups(self, client):
        """有备份时返回列表。"""
        test_client, backup_dir, _ = client
        (backup_dir / "settings_20260601_120000.json").write_text(
            "{}", encoding="utf-8"
        )
        (backup_dir / "settings_20260602_120000.json").write_text(
            "{}", encoding="utf-8"
        )
        resp = test_client.get("/api/backup/list")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        for item in data:
            assert "filename" in item
            assert "size" in item
            assert "created" in item


# ── 创建备份 ──


class TestCreateBackup:
    """POST /api/backup/create"""

    def test_create_backup_success(self, client):
        """settings.json 存在时成功创建备份。"""
        test_client, backup_dir, tmp_path = client
        resp = test_client.post("/api/backup/create")
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        # 备份目录中应有文件
        backups = list(backup_dir.glob("settings_*.json"))
        assert len(backups) >= 1

    def test_create_backup_no_settings(self, client):
        """settings.json 不存在时返回 404。"""
        test_client, _, tmp_path = client
        (tmp_path / "settings.json").unlink()
        resp = test_client.post("/api/backup/create")
        assert resp.status_code == 404


# ── 恢复备份 ──


class TestRestoreBackup:
    """POST /api/backup/restore/{filename}"""

    def test_restore_success(self, client):
        """恢复有效备份成功。"""
        test_client, backup_dir, tmp_path = client
        # 创建一个合法的备份文件
        backup_content = json.dumps(
            {
                "system": {"username": "restored", "password": "ENC:test"},
                "profiles": {"default": {"name": "恢复方案"}},
            },
            ensure_ascii=False,
        )
        (backup_dir / "settings_20260601_120000.json").write_text(
            backup_content, encoding="utf-8"
        )
        resp = test_client.post("/api/backup/restore/settings_20260601_120000.json")
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_restore_invalid_filename(self, client):
        """无效文件名返回 400。"""
        test_client, _, _ = client
        resp = test_client.post("/api/backup/restore/not_a_valid_name.json")
        assert resp.status_code == 400

    def test_restore_nonexistent_file(self, client):
        """备份文件不存在返回 404。"""
        test_client, _, _ = client
        resp = test_client.post("/api/backup/restore/settings_99999999_999999.json")
        assert resp.status_code == 404

    def test_restore_invalid_json(self, client):
        """备份文件格式错误返回 400。"""
        test_client, backup_dir, _ = client
        (backup_dir / "settings_20260601_120000.json").write_text(
            "not valid json", encoding="utf-8"
        )
        resp = test_client.post("/api/backup/restore/settings_20260601_120000.json")
        assert resp.status_code == 400


# ── 下载备份 ──


class TestDownloadBackup:
    """GET /api/backup/download/{filename}"""

    def test_download_existing(self, client):
        """下载存在的备份文件。"""
        test_client, backup_dir, _ = client
        content = '{"test": true}'
        (backup_dir / "settings_20260601_120000.json").write_text(
            content, encoding="utf-8"
        )
        resp = test_client.get("/api/backup/download/settings_20260601_120000.json")
        assert resp.status_code == 200
        assert resp.json() == {"test": True}

    def test_download_invalid_filename(self, client):
        """无效文件名返回 400。"""
        test_client, _, _ = client
        resp = test_client.get("/api/backup/download/not_a_valid_name.json")
        assert resp.status_code == 400

    def test_download_nonexistent(self, client):
        """不存在的备份返回 404。"""
        test_client, _, _ = client
        resp = test_client.get("/api/backup/download/settings_99999999_999999.json")
        assert resp.status_code == 404


# ── 删除备份 ──


class TestDeleteBackup:
    """DELETE /api/backup/{filename}"""

    def test_delete_existing(self, client):
        """删除存在的备份。"""
        test_client, backup_dir, _ = client
        (backup_dir / "settings_20260601_120000.json").write_text(
            "{}", encoding="utf-8"
        )
        resp = test_client.delete("/api/backup/settings_20260601_120000.json")
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        assert not (backup_dir / "settings_20260601_120000.json").exists()

    def test_delete_invalid_filename(self, client):
        """无效文件名返回 400。"""
        test_client, _, _ = client
        resp = test_client.delete("/api/backup/not_a_valid_name.json")
        assert resp.status_code == 400

    def test_delete_nonexistent(self, client):
        """不存在的备份返回 404。"""
        test_client, _, _ = client
        resp = test_client.delete("/api/backup/settings_99999999_999999.json")
        assert resp.status_code == 404


# ── _cleanup_old_backups 纯函数 ──


class TestCleanupOldBackups:
    """旧备份清理。"""

    def test_keeps_latest_files(self, tmp_path):
        """保留最新文件。"""
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
