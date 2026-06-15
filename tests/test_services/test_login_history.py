"""登录历史服务测试 — LoginHistoryEntry / LoginHistoryService

覆盖：add / list_recent / clear / _cleanup_old / record / 边界条件 / 异常分支
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.services.login_history_service import LoginHistoryEntry, LoginHistoryService

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


# =====================================================================
# record 方法
# =====================================================================


class TestRecord:
    @pytest.fixture
    def service(self, tmp_path: Path) -> LoginHistoryService:
        return LoginHistoryService(tmp_path)

    def test_record_without_services(self, service: LoginHistoryService):
        """无 profile_service / task_manager 时 record 退化为 add。"""
        service.record(success=True, duration_ms=200)
        entries = service.list_recent(limit=1)
        assert len(entries) == 1
        assert entries[0].success is True
        assert entries[0].duration_ms == 200
        assert entries[0].profile_name == ""
        assert entries[0].task_name == ""

    def test_record_with_profile_service(self, service: LoginHistoryService):
        """record 从 profile_service 提取活动方案名称。"""
        mock_profile = MagicMock()
        mock_profile.name = "校园网方案"
        ps = MagicMock()
        ps.get_active_profile.return_value = mock_profile

        service.record(success=True, duration_ms=100, profile_service=ps)
        entries = service.list_recent(limit=1)
        assert entries[0].profile_name == "校园网方案"

    def test_record_with_profile_service_returns_none(
        self, service: LoginHistoryService
    ):
        """profile_service.get_active_profile 返回 None 时 profile_name 为空。"""
        ps = MagicMock()
        ps.get_active_profile.return_value = None

        service.record(success=True, duration_ms=100, profile_service=ps)
        entries = service.list_recent(limit=1)
        assert entries[0].profile_name == ""

    def test_record_with_profile_service_raises(self, service: LoginHistoryService):
        """profile_service.get_active_profile 抛异常时静默跳过。"""
        ps = MagicMock()
        ps.get_active_profile.side_effect = RuntimeError("boom")

        service.record(success=True, duration_ms=100, profile_service=ps)
        entries = service.list_recent(limit=1)
        assert entries[0].profile_name == ""

    def test_record_with_task_manager(self, service: LoginHistoryService):
        """record 从 task_manager 提取活动任务名称。"""
        tm = MagicMock()
        tm.get_active_task.return_value = "task_001"
        task_info = MagicMock()
        task_info.name = "每日登录"
        tm.load_task.return_value = task_info

        service.record(success=True, duration_ms=100, task_manager=tm)
        entries = service.list_recent(limit=1)
        assert entries[0].task_name == "每日登录"

    def test_record_with_task_manager_no_name(self, service: LoginHistoryService):
        """task 对象无 name 属性时回退到 task_id。"""
        tm = MagicMock()
        tm.get_active_task.return_value = "task_002"
        task_info = MagicMock(spec=[])  # 无 name 属性
        tm.load_task.return_value = task_info

        service.record(success=True, duration_ms=100, task_manager=tm)
        entries = service.list_recent(limit=1)
        # getattr(task, "name", task_id) — spec=[] 无 name，回退 task_id
        assert entries[0].task_name == "task_002"

    def test_record_with_task_manager_load_returns_none(
        self, service: LoginHistoryService
    ):
        """task_manager.load_task 返回 None 时 task_name 为空。"""
        tm = MagicMock()
        tm.get_active_task.return_value = "task_x"
        tm.load_task.return_value = None

        service.record(success=True, duration_ms=100, task_manager=tm)
        entries = service.list_recent(limit=1)
        assert entries[0].task_name == ""

    def test_record_with_task_manager_raises(self, service: LoginHistoryService):
        """task_manager 抛异常时静默跳过。"""
        tm = MagicMock()
        tm.get_active_task.side_effect = RuntimeError("boom")

        service.record(success=True, duration_ms=100, task_manager=tm)
        entries = service.list_recent(limit=1)
        assert entries[0].task_name == ""

    def test_record_with_error(self, service: LoginHistoryService):
        """record 传递 error 参数。"""
        service.record(success=False, duration_ms=300, error="连接失败")
        entries = service.list_recent(limit=1)
        assert entries[0].success is False
        assert entries[0].error == "连接失败"


# =====================================================================
# add 异常分支
# =====================================================================


class TestAddException:
    @pytest.fixture
    def service(self, tmp_path: Path) -> LoginHistoryService:
        return LoginHistoryService(tmp_path)

    @patch("builtins.open", side_effect=PermissionError("denied"))
    def test_add_write_error_does_not_raise(
        self, mock_open: MagicMock, service: LoginHistoryService
    ):
        """写入失败时不抛异常，静默记录日志。"""
        service.add(success=True)  # 不应抛异常

    @patch("builtins.open", side_effect=PermissionError("denied"))
    def test_add_write_error_does_not_increment_count(
        self, mock_open: MagicMock, service: LoginHistoryService
    ):
        """写入失败时 _write_count 不递增。"""
        service.add(success=True)
        assert service._write_count == 0


# =====================================================================
# list_recent 大文件分支 (>5MB)
# =====================================================================


class TestListRecentLargeFile:
    @pytest.fixture
    def service(self, tmp_path: Path) -> LoginHistoryService:
        return LoginHistoryService(tmp_path)

    def test_list_recent_large_file_reads_tail(
        self, service: LoginHistoryService, tmp_path: Path
    ):
        """文件 >5MB 时只读取末尾部分。"""
        history_path = tmp_path / "login_history.jsonl"
        # 构造 >5MB 的文件：每行约 120 字节，需要 ~50000 行
        filler_lines = []
        for i in range(55000):
            filler_lines.append(
                json.dumps(
                    {
                        "id": f"filler_{i:06d}",
                        "timestamp": "2020-01-01 00:00:00",
                        "success": True,
                        "profile_name": "padding",
                        "task_name": "padding",
                    }
                )
            )
        # 最后一条有效记录
        filler_lines.append(
            json.dumps(
                {
                    "id": "last_entry",
                    "timestamp": "2026-06-15 12:00:00",
                    "success": True,
                    "duration_ms": 100,
                }
            )
        )
        content = "\n".join(filler_lines) + "\n"
        history_path.write_text(content, encoding="utf-8")

        # 确认文件确实 >5MB
        assert history_path.stat().st_size > 5 * 1024 * 1024

        entries = service.list_recent(limit=5)
        assert len(entries) > 0
        # 最新的条目应存在
        ids = [e.id for e in entries]
        assert "last_entry" in ids


# =====================================================================
# list_recent 异常分支
# =====================================================================


class TestListRecentException:
    @pytest.fixture
    def service(self, tmp_path: Path) -> LoginHistoryService:
        return LoginHistoryService(tmp_path)

    def test_list_recent_stat_error_returns_empty(
        self, service: LoginHistoryService, tmp_path: Path
    ):
        """文件 stat 大小查询抛异常时返回空列表。"""
        history_path = tmp_path / "login_history.jsonl"
        history_path.write_text(
            '{"id":"x","timestamp":"t","success":true}\n', encoding="utf-8"
        )
        # list_recent 先 exists()，再 stat().st_size
        # exists 使用 follow_symlinks 参数，而 st_size 查询不带参数
        # 可以通过 mock 整个 list_recent 内的 stat 调用来覆盖
        # 但 exists() 也调用 stat，所以我们用不同的方法：
        # 直接 patch stat 但让 exists 的调用通过
        original_stat = Path.stat

        call_count = [0]

        def fake_stat(self_path, *args, **kwargs):
            call_count[0] += 1
            # exists() 调用 stat(follow_symlinks=...) 有关键字参数
            # stat().st_size 调用 stat() 无参数
            if kwargs:
                # exists() 调用，放行
                return original_stat(self_path, *args, **kwargs)
            # st_size 调用，抛异常
            raise OSError("bad")

        with patch.object(Path, "stat", fake_stat):
            result = service.list_recent()
        assert result == []

    def test_list_recent_read_error_returns_empty(
        self, service: LoginHistoryService, tmp_path: Path
    ):
        """文件读取抛异常时返回空列表。"""
        history_path = tmp_path / "login_history.jsonl"
        history_path.write_text("content", encoding="utf-8")
        with patch("builtins.open", side_effect=OSError("read fail")):
            result = service.list_recent()
        assert result == []


# =====================================================================
# clear 异常分支
# =====================================================================


class TestClearException:
    @pytest.fixture
    def service(self, tmp_path: Path) -> LoginHistoryService:
        return LoginHistoryService(tmp_path)

    def test_clear_read_error_returns_zero(
        self, service: LoginHistoryService, tmp_path: Path
    ):
        """clear 读取文件失败时返回 0。"""
        history_path = tmp_path / "login_history.jsonl"
        history_path.write_text("data", encoding="utf-8")
        with patch("builtins.open", side_effect=OSError("fail")):
            result = service.clear()
        assert result == 0


# =====================================================================
# _cleanup_old 异常分支
# =====================================================================


class TestCleanupOldException:
    @pytest.fixture
    def service(self, tmp_path: Path) -> LoginHistoryService:
        return LoginHistoryService(tmp_path)

    def test_cleanup_old_read_error_does_not_raise(
        self, service: LoginHistoryService, tmp_path: Path
    ):
        """_cleanup_old 读取文件失败时静默处理。"""
        history_path = tmp_path / "login_history.jsonl"
        history_path.write_text("data", encoding="utf-8")
        with patch("builtins.open", side_effect=OSError("fail")):
            service._cleanup_old()  # 不应抛异常

    def test_cleanup_old_keeps_json_parse_errors(
        self, service: LoginHistoryService, tmp_path: Path
    ):
        """无法解析的行应保留（不删除）。"""
        history_path = tmp_path / "login_history.jsonl"
        # 有效 JSON 新记录 + 无法解析的行
        new_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        history_path.write_text(
            f'{{"id":"ok","timestamp":"{new_time}","success":true}}\nnot json\n',
            encoding="utf-8",
        )
        service._cleanup_old()
        content = history_path.read_text(encoding="utf-8").strip()
        lines = [l for l in content.split("\n") if l.strip()]
        assert len(lines) == 2
