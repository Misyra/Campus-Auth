"""src/utils/network_helpers.py 测试"""
from __future__ import annotations

import pytest
from src.utils.network_helpers import parse_host_port


class TestParseHostPort:
    def test_basic(self):
        result = parse_host_port(["8.8.8.8:53"])
        assert result == [("8.8.8.8", 53)]

    def test_multiple(self):
        result = parse_host_port(["8.8.8.8:53", "1.1.1.1:443"])
        assert result == [("8.8.8.8", 53), ("1.1.1.1", 443)]

    def test_empty_list(self):
        assert parse_host_port([]) == []

    def test_ipv6(self):
        """IPv6 地址应保留方括号（与原实现一致）"""
        result = parse_host_port(["[::1]:8080"])
        assert result == [("[::1]", 8080)]

    def test_missing_port(self):
        with pytest.raises(ValueError):
            parse_host_port(["8.8.8.8"])

    def test_invalid_port(self):
        with pytest.raises(ValueError):
            parse_host_port(["8.8.8.8:99999"])

    def test_non_numeric_port(self):
        with pytest.raises(ValueError):
            parse_host_port(["8.8.8.8:abc"])

    def test_hostname(self):
        result = parse_host_port(["www.baidu.com:443"])
        assert result == [("www.baidu.com", 443)]

    def test_empty_host(self):
        with pytest.raises(ValueError):
            parse_host_port([":8080"])
