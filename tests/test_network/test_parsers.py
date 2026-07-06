"""parse_host_port 容错解析测试"""

from __future__ import annotations

import logging

import pytest

from app.network.parsers import (
    _looks_like_ipv6,
    _parse_single_host_port,
    parse_host_port,
    parse_ping_targets,
)

# =====================================================================
# _looks_like_ipv6 IPv6 地址检测
# =====================================================================


class TestLooksLikeIPv6:
    def test_loopback(self):
        assert _looks_like_ipv6("::1") is True

    def test_full_address(self):
        assert _looks_like_ipv6("2001:0db8:85a3:0000:0000:8a2e:0370:7334") is True

    def test_compressed(self):
        assert _looks_like_ipv6("2001:db8::1") is True

    def test_all_zeros(self):
        assert _looks_like_ipv6("::") is True

    def test_link_local(self):
        assert _looks_like_ipv6("fe80::1") is True

    def test_not_ipv6_string(self):
        assert _looks_like_ipv6("example.com") is False

    def test_not_ipv6_ipv4(self):
        assert _looks_like_ipv6("8.8.8.8") is False

    def test_not_ipv6_colon_with_port(self):
        assert _looks_like_ipv6("host:8080") is False

    def test_not_ipv6_random_string(self):
        assert _looks_like_ipv6("abc:def:ghi") is False

    def test_empty_string(self):
        assert _looks_like_ipv6("") is False


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


# =====================================================================
# parse_ping_targets IPv6 地址处理
# =====================================================================


class TestParsePingTargetsIPv6:
    def test_ipv6_loopback(self):
        """IPv6 环回地址自动补全端口 53。"""
        result = parse_ping_targets("::1")
        assert result == [("::1", 53)]

    def test_ipv6_compressed(self):
        """压缩格式 IPv6 自动补全端口 53。"""
        result = parse_ping_targets("2001:db8::1")
        assert result == [("2001:db8::1", 53)]

    def test_ipv6_with_port(self):
        """带端口的 IPv6 地址直接传递。"""
        result = parse_ping_targets("[::1]:8080")
        assert result == [("::1", 8080)]

    def test_ipv6_mixed_with_ipv4(self):
        """混合 IPv6 和 IPv4。"""
        result = parse_ping_targets("::1, 8.8.8.8")
        assert result == [("::1", 53), ("8.8.8.8", 53)]

    def test_ipv6_mixed_with_domain(self):
        """混合 IPv6 和域名。"""
        result = parse_ping_targets("::1, example.com")
        assert result == [("::1", 53), ("example.com", 443)]
