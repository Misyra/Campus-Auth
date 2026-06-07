"""app/api/logfiles.py — 路径遍历防护测试"""
from __future__ import annotations

import zipfile

import pytest
from fastapi import HTTPException

from app.api.logfiles import (
    _validate_date,
    _validate_filename,
    _list_zip_files,
    _read_from_zip,
)


class TestValidateDate:
    """_validate_date() 日期格式校验"""

    def test_invalid_date_rejected(self):
        with pytest.raises(HTTPException) as exc_info:
            _validate_date("../etc")
        assert exc_info.value.status_code == 400

    def test_dot_dot_rejected(self):
        with pytest.raises(HTTPException):
            _validate_date("2026-../01")

    def test_valid_date_accepted(self):
        _validate_date("2026-01-01")  # 不应抛异常


class TestValidateFilename:
    """_validate_filename() 文件名校验"""

    def test_path_traversal_rejected(self):
        with pytest.raises(HTTPException) as exc_info:
            _validate_filename("../../etc/passwd")
        assert exc_info.value.status_code == 400

    def test_dot_dot_rejected(self):
        with pytest.raises(HTTPException):
            _validate_filename("../app.log")

    def test_normal_filename_accepted(self):
        _validate_filename("app.log")
        _validate_filename("app.log.1")

    def test_unrelated_filename_rejected(self):
        with pytest.raises(HTTPException):
            _validate_filename("secrets.txt")


class TestZipSupport:
    """zip 归档读取测试"""

    def test_list_zip_files(self, tmp_path):
        """zip 中的日志文件应被正确列出"""
        zip_path = tmp_path / "2026-01-01.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("2026-01-01/app.log", "line1\nline2\n")
            zf.writestr("2026-01-01/app.log.1", "old line\n")
            zf.writestr("2026-01-01/screenshots/xxx.png", b"fake")

        files = _list_zip_files(zip_path)
        names = [f.name for f in files]
        assert "app.log" in names
        assert "app.log.1" in names
        # screenshots 子目录下的文件不应出现
        assert len(files) == 2

    def test_read_from_zip(self, tmp_path):
        """应能从 zip 中读取日志内容"""
        zip_path = tmp_path / "2026-01-01.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("2026-01-01/app.log", "line1\nline2\nline3\n")

        lines = _read_from_zip(zip_path, "2026-01-01", "app.log")
        assert lines == ["line1", "line2", "line3"]

    def test_read_from_zip_missing_file(self, tmp_path):
        """zip 中不存在的文件应返回空列表"""
        zip_path = tmp_path / "2026-01-01.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("2026-01-01/app.log", "content")

        lines = _read_from_zip(zip_path, "2026-01-01", "app.log.9")
        assert lines == []

    def test_corrupted_zip_returns_empty(self, tmp_path):
        """损坏的 zip 文件不应崩溃"""
        zip_path = tmp_path / "2026-01-01.zip"
        zip_path.write_bytes(b"not a zip")

        files = _list_zip_files(zip_path)
        assert files == []
