"""backend/routers/backup.py — 备份验证顺序测试"""
from __future__ import annotations

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from unittest.mock import MagicMock

from app.api.backup import router, restore_backup


class TestBackupValidationOrder:
    """restore_backup 应先验证文件名格式，再检查文件是否存在"""

    def test_regex_before_path_construction(self):
        """无效文件名应先抛正则验证错误（400），而非文件不存在（404）"""
        from fastapi import FastAPI

        app = FastAPI()
        app.include_router(router)

        mock_profile_svc = MagicMock()
        mock_monitor_svc = MagicMock()

        from app.deps import get_profile_service, get_monitor_service
        app.dependency_overrides[get_profile_service] = lambda: mock_profile_svc
        app.dependency_overrides[get_monitor_service] = lambda: mock_monitor_svc

        client = TestClient(app)

        # 使用不匹配 BACKUP_FILENAME_PATTERN 的文件名
        response = client.post("/api/backup/restore/evil.json")

        # 应返回 400（正则验证失败），而非 404（文件不存在）
        assert response.status_code == 400
        assert "无效" in response.json()["detail"]

    def test_valid_regex_nonexistent_file_returns_404(self):
        """合法格式但不存在的文件名应返回 404"""
        from fastapi import FastAPI

        app = FastAPI()
        app.include_router(router)

        mock_profile_svc = MagicMock()
        mock_monitor_svc = MagicMock()

        from app.deps import get_profile_service, get_monitor_service
        app.dependency_overrides[get_profile_service] = lambda: mock_profile_svc
        app.dependency_overrides[get_monitor_service] = lambda: mock_monitor_svc

        client = TestClient(app)

        # 合法格式但不存在的备份文件
        response = client.post("/api/backup/restore/settings_20260101_000000.json")

        assert response.status_code == 404
        assert "不存在" in response.json()["detail"]
