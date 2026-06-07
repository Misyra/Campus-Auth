"""app/api/logfiles.py — 路径遍历防护测试"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.api.logfiles import (
    _validate_date,
    _validate_filename,
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
