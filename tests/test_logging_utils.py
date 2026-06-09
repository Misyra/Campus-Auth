"""日志工具测试 — 覆盖纯逻辑函数。"""

from __future__ import annotations

import threading
from unittest.mock import MagicMock

from app.utils.logging import VALID_LOG_LEVELS, DashboardSink, normalize_level

# ── VALID_LOG_LEVELS ──


class TestValidLogLevels:
    """有效日志级别。"""

    def test_contains_standard_levels(self):
        """包含标准级别。"""
        assert "DEBUG" in VALID_LOG_LEVELS
        assert "INFO" in VALID_LOG_LEVELS
        assert "WARNING" in VALID_LOG_LEVELS
        assert "ERROR" in VALID_LOG_LEVELS
        assert "CRITICAL" in VALID_LOG_LEVELS

    def test_count(self):
        """级别数量。"""
        assert len(VALID_LOG_LEVELS) == 5


# ── normalize_level ──


class TestNormalizeLevel:
    """日志级别标准化。"""

    def test_uppercase(self):
        """转大写。"""
        assert normalize_level("info") == "INFO"
        assert normalize_level("debug") == "DEBUG"
        assert normalize_level("warning") == "WARNING"
        assert normalize_level("error") == "ERROR"

    def test_already_upper(self):
        """已是大写。"""
        assert normalize_level("INFO") == "INFO"

    def test_mixed_case(self):
        """混合大小写。"""
        assert normalize_level("Info") == "INFO"
        assert normalize_level("WARNING") == "WARNING"

    def test_whitespace_trimmed(self):
        """去除首尾空格。"""
        assert normalize_level("  INFO  ") == "INFO"

    def test_empty_string_returns_default(self):
        """空字符串返回默认值 INFO。"""
        assert normalize_level("") == "INFO"

    def test_invalid_level_returns_default(self):
        """无效级别返回默认值 INFO。"""
        assert normalize_level("INVALID") == "INFO"

    def test_none_returns_default(self):
        """None 返回默认值 INFO。"""
        assert normalize_level(None) == "INFO"

    def test_custom_default(self):
        """自定义默认值。"""
        assert normalize_level("INVALID", default="DEBUG") == "DEBUG"
        assert normalize_level("", default="ERROR") == "ERROR"


# ── DashboardSink ──


class TestDashboardSink:
    """DashboardSink 单元测试。"""

    def test_init_default(self):
        """默认初始化。"""
        sink = DashboardSink()
        assert sink.buffer.maxlen == 1200
        assert sink.broadcast_queue.maxlen == 200
        assert len(sink.buffer) == 0
        assert len(sink.broadcast_queue) == 0

    def test_init_custom_maxlen(self):
        """自定义 maxlen。"""
        sink = DashboardSink(maxlen=500)
        assert sink.buffer.maxlen == 500

    def test_write_appends_to_buffer_and_queue(self):
        """write 同时写入 buffer 和 broadcast_queue。"""
        sink = DashboardSink(maxlen=10)
        msg = MagicMock()
        level_mock = MagicMock()
        level_mock.name = "INFO"
        msg.record = {
            "time": MagicMock(timestamp=lambda: 1700000000.0),
            "level": level_mock,
            "extra": {"name": "test", "source": "backend"},
            "name": "test",
            "message": "测试消息",
        }
        msg.__str__ = lambda self: "测试消息"

        sink.write(msg)

        assert len(sink.buffer) == 1
        assert len(sink.broadcast_queue) == 1
        entry = sink.buffer[0]
        assert entry["level"] == "INFO"
        assert entry["source"] == "backend"
        assert entry["module"] == "test"
        assert entry["message"] == "测试消息"

    def test_write_buffer_overflow(self):
        """buffer 超出 maxlen 自动淘汰最旧。"""
        sink = DashboardSink(maxlen=3)
        level_mock = MagicMock()
        level_mock.name = "INFO"
        for i in range(5):
            msg = MagicMock()
            msg.record = {
                "time": MagicMock(timestamp=lambda: 1700000000.0),
                "level": level_mock,
                "extra": {"name": "test", "source": "backend"},
                "name": "test",
                "message": f"msg{i}",
            }
            msg.__str__ = lambda self, i=i: f"msg{i}"
            sink.write(msg)

        assert len(sink.buffer) == 3
        assert sink.buffer[0]["message"] == "msg2"
        assert sink.buffer[2]["message"] == "msg4"

    def test_list_logs_returns_last_n(self):
        """list_logs 返回最近 N 条。"""
        sink = DashboardSink(maxlen=10)
        for i in range(5):
            sink.buffer.append({"message": f"msg{i}"})

        result = sink.list_logs(limit=3)
        assert len(result) == 3
        assert result[0]["message"] == "msg2"

    def test_list_logs_limit_exceeds_buffer(self):
        """list_logs limit 超过 buffer 大小时返回全部。"""
        sink = DashboardSink(maxlen=10)
        sink.buffer.append({"message": "only"})
        result = sink.list_logs(limit=100)
        assert len(result) == 1

    def test_thread_safety(self):
        """多线程并发写入不会崩溃。"""
        sink = DashboardSink(maxlen=1000)
        errors = []

        level_mock = MagicMock()
        level_mock.name = "INFO"

        def writer(n):
            try:
                for i in range(100):
                    msg = MagicMock()
                    msg.record = {
                        "time": MagicMock(timestamp=lambda: 1700000000.0),
                        "level": level_mock,
                        "extra": {"name": "test", "source": "backend"},
                        "name": "test",
                        "message": f"t{n}_msg{i}",
                    }
                    msg.__str__ = lambda self, n=n, i=i: f"t{n}_msg{i}"
                    sink.write(msg)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(n,)) for n in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert len(sink.buffer) == 400
