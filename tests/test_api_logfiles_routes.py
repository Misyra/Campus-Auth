"""日志文件路由测试 — 覆盖纯函数和 API 端点。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.api.logfiles import (
    _parse_log_line,
    _validate_date,
    _validate_filename,
    get_log_file_content,
    list_log_files,
    read_tail,
    scan_file,
)

# ── _validate_date ──


class TestValidateDate:
    """日期格式校验。"""

    def test_valid_date(self):
        """有效日期不抛异常。"""
        _validate_date("2026-06-01")  # 不应抛异常

    def test_invalid_format(self):
        """无效格式抛 HTTPException。"""
        with pytest.raises(HTTPException) as exc_info:
            _validate_date("2026/06/01")
        assert exc_info.value.status_code == 400

    def test_invalid_date_value(self):
        """不存在的日期抛 HTTPException。"""
        with pytest.raises(HTTPException) as exc_info:
            _validate_date("2026-02-30")
        assert exc_info.value.status_code == 400

    def test_empty_string(self):
        """空字符串抛 HTTPException。"""
        with pytest.raises(HTTPException):
            _validate_date("")

    def test_partial_date(self):
        """不完整的日期抛 HTTPException。"""
        with pytest.raises(HTTPException):
            _validate_date("2026-06")


# ── _validate_filename ──


class TestValidateFilename:
    """文件名安全性校验。"""

    def test_valid_filenames(self):
        """有效文件名不抛异常。"""
        _validate_filename("app.log")
        _validate_filename("app.log.1")
        _validate_filename("app.log.999")

    def test_path_traversal_rejected(self):
        """路径穿越被拒绝。"""
        with pytest.raises(HTTPException) as exc_info:
            _validate_filename("../../etc/passwd")
        assert exc_info.value.status_code == 400

    def test_invalid_extension_rejected(self):
        """无效扩展名被拒绝。"""
        with pytest.raises(HTTPException):
            _validate_filename("app.log.abc")

    def test_similar_name_rejected(self):
        """类似但无效的名称被拒绝。"""
        with pytest.raises(HTTPException):
            _validate_filename("app.logx")

    def test_empty_string_rejected(self):
        """空字符串被拒绝。"""
        with pytest.raises(HTTPException):
            _validate_filename("")

    def test_dot_file_rejected(self):
        """点文件被拒绝。"""
        with pytest.raises(HTTPException):
            _validate_filename(".log")

    def test_negative_number_rejected(self):
        """负数后缀被拒绝（app.log.-1）。"""
        with pytest.raises(HTTPException):
            _validate_filename("app.log.-1")


# ── _parse_log_line ──


class TestParseLogLine:
    """日志行解析。"""

    def test_standard_format(self):
        """标准格式解析。"""
        raw = "[2026-06-01 00:04:44][INFO][backend][module] 这是消息"
        line = _parse_log_line(raw)
        assert line.timestamp == "2026-06-01 00:04:44"
        assert line.level == "INFO"
        assert line.source == "backend"
        assert line.name == "module"
        assert line.message == "这是消息"

    def test_error_level(self):
        """ERROR 级别解析。"""
        raw = "[2026-06-01 12:00:00][ERROR][backend][main] 出错了"
        line = _parse_log_line(raw)
        assert line.level == "ERROR"
        assert line.message == "出错了"

    def test_warning_level(self):
        """WARNING 级别解析。"""
        raw = "[2026-06-01 12:00:00][WARNING][backend][service] 警告"
        line = _parse_log_line(raw)
        assert line.level == "WARNING"

    def test_non_standard_line(self):
        """非标准行只填充 message。"""
        raw = "这不是标准日志格式"
        line = _parse_log_line(raw)
        assert line.timestamp == ""
        assert line.level == ""
        assert line.source == ""
        assert line.name == ""
        assert line.message == "这不是标准日志格式"

    def test_empty_line(self):
        """空行只填充 message。"""
        line = _parse_log_line("")
        assert line.message == ""

    def test_multiline_message(self):
        """消息中包含特殊字符。"""
        raw = "[2026-06-01 00:00:00][INFO][backend][mod] key=value, a=b"
        line = _parse_log_line(raw)
        assert line.message == "key=value, a=b"


# ── list_log_files ──


class TestListLogFiles:
    """list_log_files 端点。"""

    def test_empty_logs_dir(self, tmp_path):
        """日志目录为空返回空列表。"""
        with patch("app.api.logfiles.LOGS_DIR", tmp_path):
            result = list_log_files()
            assert result == []

    def test_logs_dir_not_exists(self, tmp_path):
        """日志目录不存在返回空列表。"""
        with patch("app.api.logfiles.LOGS_DIR", tmp_path / "nonexistent"):
            result = list_log_files()
            assert result == []

    def test_groups_by_date(self, tmp_path):
        """按日期分组。"""
        # 创建日期目录和日志文件
        date_dir = tmp_path / "2026-06-01"
        date_dir.mkdir()
        (date_dir / "app.log").write_text("test log content")

        with patch("app.api.logfiles.LOGS_DIR", tmp_path):
            result = list_log_files()
            assert len(result) == 1
            assert result[0].date == "2026-06-01"
            assert len(result[0].files) == 1
            assert result[0].files[0].name == "app.log"

    def test_skips_invalid_date_dirs(self, tmp_path):
        """跳过无效日期目录。"""
        # 有效目录
        valid_dir = tmp_path / "2026-06-01"
        valid_dir.mkdir()
        (valid_dir / "app.log").write_text("content")
        # 无效目录
        invalid_dir = tmp_path / "not-a-date"
        invalid_dir.mkdir()
        (invalid_dir / "app.log").write_text("content")

        with patch("app.api.logfiles.LOGS_DIR", tmp_path):
            result = list_log_files()
            assert len(result) == 1
            assert result[0].date == "2026-06-01"

    def test_skips_non_matching_files(self, tmp_path):
        """跳过不符合命名规则的文件。"""
        date_dir = tmp_path / "2026-06-01"
        date_dir.mkdir()
        (date_dir / "app.log").write_text("valid")
        (date_dir / "other.log").write_text("invalid")
        (date_dir / "app.log.abc").write_text("invalid")

        with patch("app.api.logfiles.LOGS_DIR", tmp_path):
            result = list_log_files()
            assert len(result) == 1
            assert len(result[0].files) == 1
            assert result[0].files[0].name == "app.log"

    def test_sorted_by_date_desc(self, tmp_path):
        """按日期降序排列。"""
        for date in ["2026-06-01", "2026-06-03", "2026-06-02"]:
            d = tmp_path / date
            d.mkdir()
            (d / "app.log").write_text("content")

        with patch("app.api.logfiles.LOGS_DIR", tmp_path):
            result = list_log_files()
            dates = [g.date for g in result]
            assert dates == ["2026-06-03", "2026-06-02", "2026-06-01"]


# ── get_log_file_content ──


class TestGetLogFileContent:
    """get_log_file_content 端点。"""

    def _create_log_file(self, tmp_path: Path, date: str, filename: str, content: str):
        """辅助方法：创建日志文件。"""
        date_dir = tmp_path / date
        date_dir.mkdir(parents=True, exist_ok=True)
        (date_dir / filename).write_text(content, encoding="utf-8")

    def test_basic_content(self, tmp_path):
        """基本内容读取。"""
        content = "[2026-06-01 00:00:00][INFO][backend][mod] hello\n"
        self._create_log_file(tmp_path, "2026-06-01", "app.log", content)

        with patch("app.api.logfiles.LOGS_DIR", tmp_path):
            result = get_log_file_content(
                date="2026-06-01",
                file="app.log",
                level="",
                source="",
                search="",
                limit=2000,
            )
            assert result.date == "2026-06-01"
            assert result.file == "app.log"
            assert result.total_lines == 1
            assert result.returned_lines == 1
            assert result.lines[0].message == "hello"

    def test_file_not_found(self, tmp_path):
        """文件不存在抛 404。"""
        with patch("app.api.logfiles.LOGS_DIR", tmp_path):
            with pytest.raises(HTTPException) as exc_info:
                get_log_file_content(
                    date="2026-06-01",
                    file="app.log",
                    level="",
                    source="",
                    search="",
                    limit=2000,
                )
            assert exc_info.value.status_code == 404

    def test_level_filter(self, tmp_path):
        """级别过滤。"""
        content = (
            "[2026-06-01 00:00:00][INFO][backend][mod] info msg\n"
            "[2026-06-01 00:00:01][ERROR][backend][mod] error msg\n"
            "[2026-06-01 00:00:02][INFO][backend][mod] info msg 2\n"
        )
        self._create_log_file(tmp_path, "2026-06-01", "app.log", content)

        with patch("app.api.logfiles.LOGS_DIR", tmp_path):
            result = get_log_file_content(
                date="2026-06-01",
                file="app.log",
                level="ERROR",
                source="",
                search="",
                limit=2000,
            )
            assert result.total_lines == 1
            assert result.lines[0].level == "ERROR"

    def test_search_filter(self, tmp_path):
        """关键词搜索。"""
        content = (
            "[2026-06-01 00:00:00][INFO][backend][mod] 登录成功\n"
            "[2026-06-01 00:00:01][ERROR][backend][mod] 连接超时\n"
            "[2026-06-01 00:00:02][INFO][backend][mod] 网络正常\n"
        )
        self._create_log_file(tmp_path, "2026-06-01", "app.log", content)

        with patch("app.api.logfiles.LOGS_DIR", tmp_path):
            result = get_log_file_content(
                date="2026-06-01",
                file="app.log",
                level="",
                source="",
                search="超时",
                limit=2000,
            )
            assert result.total_lines == 1
            assert "超时" in result.lines[0].message

    def test_search_case_insensitive(self, tmp_path):
        """搜索大小写不敏感。"""
        content = "[2026-06-01 00:00:00][INFO][backend][mod] Hello World\n"
        self._create_log_file(tmp_path, "2026-06-01", "app.log", content)

        with patch("app.api.logfiles.LOGS_DIR", tmp_path):
            result = get_log_file_content(
                date="2026-06-01",
                file="app.log",
                level="",
                source="",
                search="hello",
                limit=2000,
            )
            assert result.total_lines == 1

    def test_limit_applied(self, tmp_path):
        """限制返回行数（浏览模式下 total_lines = returned_lines）。"""
        lines = [
            f"[2026-06-01 00:00:{i:02d}][INFO][backend][mod] msg {i}\n"
            for i in range(100)
        ]
        content = "".join(lines)
        self._create_log_file(tmp_path, "2026-06-01", "app.log", content)

        with patch("app.api.logfiles.LOGS_DIR", tmp_path):
            result = get_log_file_content(
                date="2026-06-01",
                file="app.log",
                level="",
                source="",
                search="",
                limit=10,
            )
            # 浏览模式下 total_lines 等于 returned_lines
            assert result.total_lines == 10
            assert result.returned_lines == 10

    def test_invalid_date_rejected(self, tmp_path):
        """无效日期被拒绝。"""
        with patch("app.api.logfiles.LOGS_DIR", tmp_path):
            with pytest.raises(HTTPException) as exc_info:
                get_log_file_content(
                    date="invalid",
                    file="app.log",
                    level="",
                    source="",
                    search="",
                    limit=2000,
                )
            assert exc_info.value.status_code == 400

    def test_invalid_filename_rejected(self, tmp_path):
        """无效文件名被拒绝。"""
        with patch("app.api.logfiles.LOGS_DIR", tmp_path):
            with pytest.raises(HTTPException) as exc_info:
                get_log_file_content(
                    date="2026-06-01",
                    file="../../etc/passwd",
                    level="",
                    source="",
                    search="",
                    limit=2000,
                )
            assert exc_info.value.status_code == 400


# ── scan_file ──


class TestScanFile:
    """scan_file 全文扫描函数。"""

    def _create_log_file(self, tmp_path: Path, content: str) -> Path:
        """辅助方法：创建临时日志文件。"""
        filepath = tmp_path / "app.log"
        filepath.write_text(content, encoding="utf-8")
        return filepath

    def test_scan_file_by_keyword(self, tmp_path):
        """按关键词搜索。"""
        content = (
            "[2026-06-01 00:00:00][INFO][backend][mod] 登录成功\n"
            "[2026-06-01 00:00:01][ERROR][backend][mod] 连接超时\n"
            "[2026-06-01 00:00:02][INFO][backend][mod] 网络正常\n"
        )
        filepath = self._create_log_file(tmp_path, content)

        result = scan_file(
            filepath=filepath,
            level="",
            source="",
            search="超时",
            limit=2000,
        )
        assert len(result) == 1
        assert "超时" in result[0].message

    def test_scan_file_by_level(self, tmp_path):
        """按级别过滤。"""
        content = (
            "[2026-06-01 00:00:00][INFO][backend][mod] info msg\n"
            "[2026-06-01 00:00:01][ERROR][backend][mod] error msg\n"
            "[2026-06-01 00:00:02][WARNING][backend][mod] warning msg\n"
            "[2026-06-01 00:00:03][INFO][backend][mod] info msg 2\n"
        )
        filepath = self._create_log_file(tmp_path, content)

        result = scan_file(
            filepath=filepath,
            level="ERROR",
            source="",
            search="",
            limit=2000,
        )
        assert len(result) == 1
        assert result[0].level == "ERROR"

    def test_scan_file_by_source(self, tmp_path):
        """按来源过滤。"""
        content = (
            "[2026-06-01 00:00:00][INFO][backend][mod] backend msg\n"
            "[2026-06-01 00:00:01][INFO][network][mod] network msg\n"
            "[2026-06-01 00:00:02][INFO][backend][mod] backend msg 2\n"
        )
        filepath = self._create_log_file(tmp_path, content)

        result = scan_file(
            filepath=filepath,
            level="",
            source="network",
            search="",
            limit=2000,
        )
        assert len(result) == 1
        assert result[0].source == "network"

    def test_scan_file_limit(self, tmp_path):
        """结果数量限制 — 超过 limit 时返回最后 N 条。"""
        lines = [
            f"[2026-06-01 00:00:{i:02d}][INFO][backend][mod] msg {i}\n"
            for i in range(50)
        ]
        content = "".join(lines)
        filepath = self._create_log_file(tmp_path, content)

        result = scan_file(
            filepath=filepath,
            level="",
            source="",
            search="",
            limit=10,
        )
        # 应返回最后 10 条
        assert len(result) == 10
        assert result[0].message == "msg 40"
        assert result[-1].message == "msg 49"


# ── read_tail ──


class TestReadTail:
    """read_tail 读取末尾行函数。"""

    def _create_log_file(self, tmp_path: Path, content: str) -> Path:
        """辅助方法：创建临时日志文件。"""
        filepath = tmp_path / "app.log"
        filepath.write_text(content, encoding="utf-8")
        return filepath

    def test_read_tail_basic(self, tmp_path):
        """读取末尾行。"""
        lines = [
            f"[2026-06-01 00:00:{i:02d}][INFO][backend][mod] msg {i}\n"
            for i in range(100)
        ]
        content = "".join(lines)
        filepath = self._create_log_file(tmp_path, content)

        result = read_tail(filepath, limit=10)
        assert len(result) == 10
        assert result[0].message == "msg 90"
        assert result[-1].message == "msg 99"

    def test_read_tail_fewer_than_limit(self, tmp_path):
        """文件行数少于 limit 时返回全部。"""
        content = "[2026-06-01 00:00:00][INFO][backend][mod] hello\n"
        filepath = self._create_log_file(tmp_path, content)

        result = read_tail(filepath, limit=100)
        assert len(result) == 1
        assert result[0].message == "hello"

    def test_read_tail_file_not_found(self, tmp_path):
        """文件不存在返回空列表。"""
        filepath = tmp_path / "nonexistent.log"
        result = read_tail(filepath, limit=100)
        assert result == []


# ── 搜索模式与浏览模式集成测试 ──


class TestBrowseVsSearchMode:
    """测试搜索模式与浏览模式的分离。"""

    def _create_log_file(self, tmp_path: Path, date: str, filename: str, content: str):
        """辅助方法：创建日志文件。"""
        date_dir = tmp_path / date
        date_dir.mkdir(parents=True, exist_ok=True)
        (date_dir / filename).write_text(content, encoding="utf-8")

    def test_browse_mode_uses_read_tail(self, tmp_path):
        """浏览模式（无过滤条件）应读取末尾行。"""
        lines = [
            f"[2026-06-12 10:00:{i:02d}][INFO][backend][test] 日志 {i}\n"
            for i in range(100)
        ]
        content = "".join(lines)
        self._create_log_file(tmp_path, "2026-06-12", "app.log", content)

        with patch("app.api.logfiles.LOGS_DIR", tmp_path):
            result = get_log_file_content(
                date="2026-06-12",
                file="app.log",
                level="",
                source="",
                search="",
                limit=10,
            )
        assert result.returned_lines == 10
        assert result.lines[0].message == "日志 90"
        assert result.lines[-1].message == "日志 99"

    def test_search_mode_uses_scan_file(self, tmp_path):
        """搜索模式（有关键词）应全文扫描。"""
        content = (
            "[2026-06-12 10:00:00][INFO][backend][test] 普通日志\n"
            "[2026-06-12 10:00:01][ERROR][network][monitor] 认证失败\n"
            "[2026-06-12 10:00:02][INFO][backend][test] 普通日志\n"
        )
        self._create_log_file(tmp_path, "2026-06-12", "app.log", content)

        with patch("app.api.logfiles.LOGS_DIR", tmp_path):
            result = get_log_file_content(
                date="2026-06-12",
                file="app.log",
                level="",
                source="",
                search="认证失败",
                limit=100,
            )
        assert result.returned_lines == 1
        assert result.lines[0].message == "认证失败"
        assert result.lines[0].level == "ERROR"

    def test_level_filter_uses_scan_file(self, tmp_path):
        """级别过滤应使用全文扫描。"""
        content = (
            "[2026-06-12 10:00:00][INFO][backend][test] 普通日志\n"
            "[2026-06-12 10:00:01][ERROR][backend][test] 错误日志\n"
            "[2026-06-12 10:00:02][INFO][backend][test] 普通日志\n"
        )
        self._create_log_file(tmp_path, "2026-06-12", "app.log", content)

        with patch("app.api.logfiles.LOGS_DIR", tmp_path):
            result = get_log_file_content(
                date="2026-06-12",
                file="app.log",
                level="ERROR",
                source="",
                search="",
                limit=100,
            )
        assert result.returned_lines == 1
        assert result.lines[0].level == "ERROR"

    def test_source_filter_uses_scan_file(self, tmp_path):
        """来源过滤应使用全文扫描。"""
        content = (
            "[2026-06-12 10:00:00][INFO][backend][test] 后端日志\n"
            "[2026-06-12 10:00:01][INFO][network][monitor] 网络日志\n"
            "[2026-06-12 10:00:02][INFO][backend][test] 后端日志\n"
        )
        self._create_log_file(tmp_path, "2026-06-12", "app.log", content)

        with patch("app.api.logfiles.LOGS_DIR", tmp_path):
            result = get_log_file_content(
                date="2026-06-12",
                file="app.log",
                level="",
                source="network",
                search="",
                limit=100,
            )
        assert result.returned_lines == 1
        assert result.lines[0].source == "network"
