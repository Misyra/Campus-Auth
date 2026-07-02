"""parse_host_port 容错解析测试"""

from __future__ import annotations

import logging

import pytest

from app.network.parsers import (
    _parse_single_host_port,
    parse_host_port,
    parse_ping_targets,
)

# =====================================================================
# _parse_single_host_port 单条解析
# =====================================================================


class TestParseSingleHostPort:
    def test_ipv4(self):
        assert _parse_single_host_port("8.8.8.8:53") == ("8.8.8.8", 53)

    def test_ipv6_bracketed(self):
        assert _parse_single_host_port("[::1]:8080") == ("::1", 8080)

    def test_hostname(self):
        assert _parse_single_host_port("example.com:443") == ("example.com", 443)

    def test_whitespace_stripped(self):
        assert _parse_single_host_port(" 8.8.8.8 : 53 ") == ("8.8.8.8", 53)

    def test_missing_port_raises(self):
        with pytest.raises(ValueError, match="缺少端口号"):
            _parse_single_host_port("8.8.8.8")

    def test_non_numeric_port_raises(self):
        with pytest.raises(ValueError, match="不是数字"):
            _parse_single_host_port("8.8.8.8:abc")

    def test_port_out_of_range_raises(self):
        with pytest.raises(ValueError, match="超出范围"):
            _parse_single_host_port("8.8.8.8:99999")

    def test_empty_host_raises(self):
        with pytest.raises(ValueError, match="主机名为空"):
            _parse_single_host_port(":8080")


# =====================================================================
# parse_host_port 容错批量解析
# =====================================================================


class TestParseHostPort:
    def test_basic(self):
        assert parse_host_port(["8.8.8.8:53"]) == [("8.8.8.8", 53)]

    def test_multiple(self):
        result = parse_host_port(["8.8.8.8:53", "1.1.1.1:443"])
        assert result == [("8.8.8.8", 53), ("1.1.1.1", 443)]

    def test_empty_list(self):
        assert parse_host_port([]) == []

    def test_ipv6(self):
        assert parse_host_port(["[::1]:8080"]) == [("::1", 8080)]

    def test_hostname(self):
        assert parse_host_port(["www.baidu.com:443"]) == [("www.baidu.com", 443)]

    def test_skip_invalid_entry(self):
        """无效条目被跳过，合法条目正常返回。"""
        result = parse_host_port(["8.8.8.8:53", "bad", "1.1.1.1:443"])
        assert result == [("8.8.8.8", 53), ("1.1.1.1", 443)]

    def test_skip_all_invalid(self):
        """全部无效时返回空列表，不抛异常。"""
        assert parse_host_port(["bad1", "bad2"]) == []

    def test_skip_logs_warning(self, caplog):
        """无效条目触发 warning 日志。"""
        with caplog.at_level(logging.WARNING):
            parse_host_port(["8.8.8.8:53", "bad", "1.1.1.1:443"])
        assert "忽略无效探测目标" in caplog.text

    def test_multiple_invalid_skipped(self):
        """多条无效被跳过，合法条目保留。"""
        result = parse_host_port(["bad1", "8.8.8.8:53", "bad2", "bad3", "1.1.1.1:443"])
        assert result == [("8.8.8.8", 53), ("1.1.1.1", 443)]

    def test_missing_port_skipped(self):
        assert parse_host_port(["8.8.8.8"]) == []

    def test_invalid_port_skipped(self):
        assert parse_host_port(["8.8.8.8:99999"]) == []

    def test_non_numeric_port_skipped(self):
        assert parse_host_port(["8.8.8.8:abc"]) == []

    def test_empty_host_skipped(self):
        assert parse_host_port([":8080"]) == []

    def test_mixed_valid_invalid(self):
        result = parse_host_port([":8080", "[::1]:8080", "bad", "8.8.8.8:53"])
        assert result == [("::1", 8080), ("8.8.8.8", 53)]


# =====================================================================
# parse_ping_targets IPv4 段范围校验
# =====================================================================


class TestParsePingTargetsIPv4Range:
    def test_valid_ipv4_gets_port_53(self):
        """合法 IPv4 自动补全端口 53。"""
        result = parse_ping_targets("8.8.8.8")
        assert result == [("8.8.8.8", 53)]

    def test_ipv4_segment_over_255_treated_as_domain(self):
        """段值超过 255 的不识别为 IPv4，按域名补全端口 443。"""
        result = parse_ping_targets("999.999.999.999")
        assert result == [("999.999.999.999", 443)]

    def test_ipv4_single_segment_over_255(self):
        """单段超过 255 也不识别为 IPv4。"""
        result = parse_ping_targets("192.168.1.256")
        assert result == [("192.168.1.256", 443)]

    def test_ipv4_boundary_255(self):
        """段值恰好为 255 是合法的。"""
        result = parse_ping_targets("255.255.255.255")
        assert result == [("255.255.255.255", 53)]

    def test_ipv4_boundary_0(self):
        """段值为 0 是合法的。"""
        result = parse_ping_targets("0.0.0.0")
        assert result == [("0.0.0.0", 53)]

    def test_ipv4_boundary_256(self):
        """段值为 256 不合法。"""
        result = parse_ping_targets("1.2.3.256")
        assert result == [("1.2.3.256", 443)]

    def test_ipv4_negative_segment(self):
        """含负数的不识别为 IPv4。"""
        result = parse_ping_targets("-1.0.0.0")
        assert result == [("-1.0.0.0", 443)]

    def test_domain_gets_port_443(self):
        """普通域名补全端口 443。"""
        result = parse_ping_targets("example.com")
        assert result == [("example.com", 443)]

    def test_comma_separated_mixed(self):
        """逗号分隔混合 IPv4 和域名。"""
        result = parse_ping_targets("8.8.8.8, example.com")
        assert result == [("8.8.8.8", 53), ("example.com", 443)]

    def test_comma_separated_invalid_ipv4_with_valid(self):
        """无效 IPv4 与合法 IPv4 混合。"""
        result = parse_ping_targets("192.168.1.256, 8.8.8.8")
        assert result == [("192.168.1.256", 443), ("8.8.8.8", 53)]

    def test_empty_input(self):
        """空输入返回空列表。"""
        assert parse_ping_targets(None) == []
        assert parse_ping_targets("") == []
