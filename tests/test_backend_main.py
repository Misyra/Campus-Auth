"""backend/main.py — _resolve_port 函数测试"""
from __future__ import annotations

import logging



class TestResolvePort:
    """_resolve_port() 环境变量 fallback 测试"""

    def test_port_parse_falls_back_to_default(self, monkeypatch, caplog):
        """APP_PORT 为无效值时应返回默认端口 50721 并记录 warning"""
        from app.application import _resolve_port

        monkeypatch.setenv("APP_PORT", "abc")
        with caplog.at_level(logging.WARNING, logger="backend.startup"):
            result = _resolve_port()

        assert result == 50721
        assert "端口解析失败" in caplog.text

    def test_valid_env_port(self, monkeypatch):
        """APP_PORT 为有效端口时应返回该端口"""
        from app.application import _resolve_port

        monkeypatch.setenv("APP_PORT", "8080")
        assert _resolve_port() == 8080

    def test_out_of_range_port_falls_back(self, monkeypatch, caplog):
        """APP_PORT 超出范围时应 fallback"""
        from app.application import _resolve_port

        monkeypatch.setenv("APP_PORT", "99999")
        with caplog.at_level(logging.WARNING, logger="backend.startup"):
            result = _resolve_port()

        assert result == 50721

    def test_empty_env_port(self, monkeypatch):
        """APP_PORT 为空时应返回默认端口"""
        from app.application import _resolve_port

        monkeypatch.setenv("APP_PORT", "")
        # 可能返回 settings.json 中的端口或默认 50721
        result = _resolve_port()
        assert isinstance(result, int)
        assert 1 <= result <= 65535
