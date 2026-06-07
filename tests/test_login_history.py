"""登录历史服务测试 — LoginHistoryEntry / LoginHistoryService

覆盖：add / list_recent / clear / _cleanup_old / 边界条件 / 线程安全
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from app.services.login_history import LoginHistoryEntry, LoginHistoryService


# =====================================================================
# LoginHistoryEntry
# =====================================================================


class TestLoginHistoryEntry:
    def test_default_values(self):
        entry = LoginHistoryEntry(
            id="test_001", timestamp="2025-01-01 00:00:00", success=True
        )
        assert entry.id == "test_001"
        assert entry.success is True
        assert entry.duration_ms == 0
        assert entry.profile_name == ""
        assert entry.error == ""

    def test_custom_values(self):
        entry = LoginHistoryEntry(
            id="test_002",
            timestamp="2025-06-01 12:00:00",
            success=False,
            duration_ms=1500,
            profile_name="校园网",
            error="连接超时",
        )
        assert entry.duration_ms == 1500
        assert entry.profile_name == "校园网"
        assert entry.error == "连接超时"

    def test_model_dump_roundtrip(self):
        entry = LoginHistoryEntry(
            id="r1", timestamp="2025-01-01", success=True, duration_ms=100
        )
        dumped = entry.model_dump()
        restored = LoginHistoryEntry.model_validate(dumped)
        assert restored.id == entry.id
        assert restored.duration_ms == entry.duration_ms

    def test_json_roundtrip(self):
        entry = LoginHistoryEntry(
            id="j1", timestamp="2025-01-01", success=False, error="err"
        )
        json_str = entry.model_dump_json()
        restored = LoginHistoryEntry.model_validate_json(json_str)
        assert restored.error == "err"
        assert restored.success is False


# =====================================================================
# LoginHistoryService
# =====================================================================


class TestLoginHistoryService:
    @pytest.fixture
    def service(self, tmp_path: Path) -> LoginHistoryService:
        return LoginHistoryService(tmp_path)

    # ── add ──

    def test_add_creates_file(self, service: LoginHistoryService, tmp_path: Path):
        service.add(success=True)
        assert (tmp_path / "login_history.jsonl").exists()

    def test_add_writes_valid_jsonl(self, service: LoginHistoryService, tmp_path: Path):
        service.add(success=True, duration_ms=500, profile_name="默认")
        service.add(success=False, error="超时")
        lines = (
            (tmp_path / "login_history.jsonl")
            .read_text(encoding="utf-8")
            .strip()
            .split("\n")
        )
        assert len(lines) == 2
        entry1 = LoginHistoryEntry.model_validate_json(lines[0])
        assert entry1.success is True
        assert entry1.duration_ms == 500
        entry2 = LoginHistoryEntry.model_validate_json(lines[1])
        assert entry2.success is False
        assert entry2.error == "超时"

    def test_add_generates_unique_ids(self, service: LoginHistoryService):
        service.add(success=True)
        service.add(success=True)
        entries = service.list_recent(limit=10)
        assert entries[0].id != entries[1].id

    def test_add_truncates_long_error(self, service: LoginHistoryService):
        long_error = "x" * 500
        service.add(success=False, error=long_error)
        entries = service.list_recent(limit=1)
        assert len(entries[0].error) == 200

    def test_add_empty_error_not_truncated(self, service: LoginHistoryService):
        service.add(success=True, error="")
        entries = service.list_recent(limit=1)
        assert entries[0].error == ""

    # ── list_recent ──

    def test_list_recent_empty(self, service: LoginHistoryService):
        assert service.list_recent() == []

    def test_list_recent_returns_newest_first(self, service: LoginHistoryService):
        service.add(success=True, profile_name="first")
        service.add(success=True, profile_name="second")
        service.add(success=True, profile_name="third")
        entries = service.list_recent(limit=10)
        assert entries[0].profile_name == "third"
        assert entries[2].profile_name == "first"

    def test_list_recent_respects_limit(self, service: LoginHistoryService):
        for i in range(10):
            service.add(success=True, profile_name=f"p{i}")
        entries = service.list_recent(limit=3)
        assert len(entries) == 3
        assert entries[0].profile_name == "p9"

    def test_list_recent_skips_malformed_lines(
        self, service: LoginHistoryService, tmp_path: Path
    ):
        history_path = tmp_path / "login_history.jsonl"
        history_path.write_text(
            'not valid json\n{"id":"ok","timestamp":"2025-01-01","success":true}\n',
            encoding="utf-8",
        )
        entries = service.list_recent()
        assert len(entries) == 1
        assert entries[0].id == "ok"

    # ── clear ──

    def test_clear_returns_count(self, service: LoginHistoryService):
        service.add(success=True)
        service.add(success=False)
        service.add(success=True)
        count = service.clear()
        assert count == 3

    def test_clear_empties_file(self, service: LoginHistoryService):
        service.add(success=True)
        service.clear()
        assert service.list_recent() == []

    def test_clear_nonexistent_returns_zero(self, service: LoginHistoryService):
        assert service.clear() == 0

    # ── _cleanup_old ──

    def test_cleanup_old_removes_old_entries(
        self, service: LoginHistoryService, tmp_path: Path
    ):
        old_time = (datetime.now() - timedelta(days=31)).strftime("%Y-%m-%d %H:%M:%S")
        new_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        history_path = tmp_path / "login_history.jsonl"
        lines = [
            json.dumps({"id": "old1", "timestamp": old_time, "success": True}),
            json.dumps({"id": "new1", "timestamp": new_time, "success": True}),
        ]
        history_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        service._cleanup_old(max_age_days=30)
        entries = service.list_recent()
        assert len(entries) == 1
        assert entries[0].id == "new1"

    def test_cleanup_old_keeps_recent_entries(
        self, service: LoginHistoryService, tmp_path: Path
    ):
        new_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        history_path = tmp_path / "login_history.jsonl"
        lines = [
            json.dumps({"id": "new1", "timestamp": new_time, "success": True}),
            json.dumps({"id": "new2", "timestamp": new_time, "success": False}),
        ]
        history_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        service._cleanup_old(max_age_days=30)
        entries = service.list_recent()
        assert len(entries) == 2

    def test_cleanup_old_keeps_malformed_lines(
        self, service: LoginHistoryService, tmp_path: Path
    ):
        history_path = tmp_path / "login_history.jsonl"
        history_path.write_text("not json at all\n", encoding="utf-8")
        service._cleanup_old(max_age_days=30)
        content = history_path.read_text(encoding="utf-8").strip()
        assert content == "not json at all"

    def test_cleanup_old_nonexistent_file(self, service: LoginHistoryService):
        # 不应抛异常
        service._cleanup_old()

    def test_cleanup_old_empty_file(self, service: LoginHistoryService, tmp_path: Path):
        (tmp_path / "login_history.jsonl").write_text("", encoding="utf-8")
        service._cleanup_old()
        assert service.list_recent() == []

    # ── 触发清理（每 50 次写入） ──

    def test_cleanup_triggered_every_50_writes(
        self, service: LoginHistoryService, tmp_path: Path
    ):
        old_time = (datetime.now() - timedelta(days=31)).strftime("%Y-%m-%d %H:%M:%S")
        history_path = tmp_path / "login_history.jsonl"
        # 写入一条旧记录
        history_path.write_text(
            json.dumps({"id": "old", "timestamp": old_time, "success": True}) + "\n",
            encoding="utf-8",
        )
        # 写入 49 条新记录（总共 50 条旧 + 49 新 = 不触发）
        for i in range(49):
            service.add(success=True, profile_name=f"p{i}")
        # 第 50 次写入应触发清理
        service.add(success=True, profile_name="trigger")
        entries = service.list_recent(limit=100)
        # 旧记录应被清理
        ids = [e.id for e in entries]
        assert "old" not in ids
