"""时间工具测试 — 覆盖 is_in_pause_period 和 get_runtime_stats。"""

from __future__ import annotations

import datetime
from unittest.mock import MagicMock, patch

from app.utils.time_utils import get_runtime_stats, is_in_pause_period

# ── is_in_pause_period ──


class TestIsInPausePeriod:
    """暂停时段检查。"""

    def test_disabled_returns_false(self):
        """禁用暂停时返回 False。"""
        assert is_in_pause_period({"enabled": False}) is False

    def test_same_start_end_means_all_day(self):
        """start == end 表示全天暂停。"""
        assert (
            is_in_pause_period({"enabled": True, "start_hour": 0, "end_hour": 0})
            is True
        )
        assert (
            is_in_pause_period({"enabled": True, "start_hour": 12, "end_hour": 12})
            is True
        )

    def test_same_day_in_range(self):
        """同一天内在范围内。"""
        mock_now = MagicMock()
        mock_now.hour = 3
        with patch("app.utils.time_utils.datetime") as mock_dt:
            mock_dt.datetime.now.return_value = mock_now
            assert (
                is_in_pause_period({"enabled": True, "start_hour": 0, "end_hour": 6})
                is True
            )

    def test_same_day_out_of_range(self):
        """同一天内在范围外。"""
        mock_now = MagicMock()
        mock_now.hour = 12
        with patch("app.utils.time_utils.datetime") as mock_dt:
            mock_dt.datetime.now.return_value = mock_now
            assert (
                is_in_pause_period({"enabled": True, "start_hour": 0, "end_hour": 6})
                is False
            )

    def test_cross_day_in_range(self):
        """跨天在范围内。"""
        mock_now = MagicMock()
        mock_now.hour = 23
        with patch("app.utils.time_utils.datetime") as mock_dt:
            mock_dt.datetime.now.return_value = mock_now
            assert (
                is_in_pause_period({"enabled": True, "start_hour": 23, "end_hour": 6})
                is True
            )

    def test_cross_day_out_of_range(self):
        """跨天在范围外。"""
        mock_now = MagicMock()
        mock_now.hour = 12
        with patch("app.utils.time_utils.datetime") as mock_dt:
            mock_dt.datetime.now.return_value = mock_now
            assert (
                is_in_pause_period({"enabled": True, "start_hour": 23, "end_hour": 6})
                is False
            )

    def test_empty_config(self):
        """空配置默认启用暂停。"""
        mock_now = MagicMock()
        mock_now.hour = 3
        with patch("app.utils.time_utils.datetime") as mock_dt:
            mock_dt.datetime.now.return_value = mock_now
            assert is_in_pause_period({}) is True

    def test_missing_enabled_defaults_true(self):
        """缺少 enabled 字段默认为 True。"""
        mock_now = MagicMock()
        mock_now.hour = 3
        with patch("app.utils.time_utils.datetime") as mock_dt:
            mock_dt.datetime.now.return_value = mock_now
            assert is_in_pause_period({"start_hour": 0, "end_hour": 6}) is True


# ── get_runtime_stats ──


class TestGetRuntimeStats:
    """运行时统计。"""

    def test_basic_stats(self):
        """基本统计。"""
        start_time = datetime.datetime.now().timestamp() - 3661  # 1小时1分1秒前
        runtime, stats = get_runtime_stats(start_time, 10)
        assert "01:01:01" in runtime
        assert "10" in stats

    def test_zero_elapsed(self):
        """零耗时。"""
        start_time = datetime.datetime.now().timestamp()
        runtime, stats = get_runtime_stats(start_time, 0)
        assert "00:00:00" in runtime or "00:00:01" in runtime  # 可能有 1 秒误差
        assert "0" in stats

    def test_none_start_time(self):
        """None 开始时间。"""
        runtime, stats = get_runtime_stats(None, 0)
        assert runtime == "00:00:00"
        assert "0" in stats

    def test_large_elapsed(self):
        """大耗时。"""
        start_time = datetime.datetime.now().timestamp() - 86400  # 1天前
        runtime, stats = get_runtime_stats(start_time, 100)
        assert "24:00:00" in runtime or "23:59:59" in runtime  # 可能有 1 秒误差
