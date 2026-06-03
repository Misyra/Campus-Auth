"""backend/routers/logfiles.py — 路径遍历防护测试"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from backend.routers.logfiles import _safe_resolve


class TestSafeResolve:
    """_safe_resolve() 路径遍历拒绝测试"""

    def test_path_traversal_rejected(self):
        """尝试 ../../etc/passwd 应被拒绝"""
        with pytest.raises(HTTPException) as exc_info:
            _safe_resolve("2026-01-01", "../../etc/passwd")

        assert exc_info.value.status_code == 400

    def test_dot_dot_in_date_rejected(self):
        """日期参数中包含 .. 应被拒绝"""
        with pytest.raises(HTTPException) as exc_info:
            _safe_resolve("../etc", "passwd")

        assert exc_info.value.status_code == 400

    def test_normal_path_accepted(self, tmp_path, monkeypatch):
        """正常路径应通过校验"""
        from backend.constants import LOGS_DIR

        # 创建临时日志目录结构
        date_dir = tmp_path / "2026-01-01"
        date_dir.mkdir(parents=True)
        log_file = date_dir / "app.log"
        log_file.write_text("test log")

        monkeypatch.setattr("backend.routers.logfiles.LOGS_DIR", tmp_path)
        result = _safe_resolve("2026-01-01", "app.log")
        assert result == log_file.resolve()
