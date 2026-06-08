"""网络辅助工具测试 — 覆盖 parse_host_port。"""

from __future__ import annotations

import pytest

from app.utils.network_helpers import parse_host_port


# ── parse_host_port ──


class TestParseHostPort:
    """host:port 解析。"""

    def test_basic_parse(self):
        """基本解析。"""
        result = parse_host_port(["192.168.1.1:53"])
        assert result == [("192.168.1.1", 53)]

    def test_domain_parse(self):
        """域名解析。"""
        result = parse_host_port(["example.com:443"])
        assert result == [("example.com", 443)]

    def test_ipv6_parse(self):
        """IPv6 解析（保留方括号）。"""
        result = parse_host_port(["[::1]:8080"])
        assert result == [("[::1]", 8080)]

    def test_empty_list(self):
        """空列表返回空列表。"""
        result = parse_host_port([])
        assert result == []

    def test_multiple_targets(self):
        """多个目标。"""
        result = parse_host_port(["8.8.8.8:53", "1.1.1.1:53"])
        assert result == [("8.8.8.8", 53), ("1.1.1.1", 53)]

    def test_no_port_raises(self):
        """无端口抛异常。"""
        with pytest.raises(ValueError, match="缺少端口号"):
            parse_host_port(["example.com"])

    def test_invalid_port_raises(self):
        """无效端口抛异常。"""
        with pytest.raises(ValueError, match="不是数字"):
            parse_host_port(["example.com:abc"])

    def test_port_out_of_range_raises(self):
        """端口超出范围抛异常。"""
        with pytest.raises(ValueError, match="超出范围"):
            parse_host_port(["example.com:99999"])

    def test_port_zero_raises(self):
        """端口 0 抛异常（不在 1-65535 范围）。"""
        with pytest.raises(ValueError, match="超出范围"):
            parse_host_port(["example.com:0"])

    def test_max_port(self):
        """最大端口 65535。"""
        result = parse_host_port(["example.com:65535"])
        assert result == [("example.com", 65535)]

    def test_empty_host_raises(self):
        """空主机名抛异常。"""
        with pytest.raises(ValueError, match="主机名为空"):
            parse_host_port([":80"])
