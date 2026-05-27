"""src/utils/time_utils.py 测试"""
from __future__ import annotations

import time
from unittest.mock import patch
import datetime

from src.utils.time_utils import is_in_pause_period, get_runtime_stats


class TestIsInPausePeriod:
    def test_disabled(self):
        """暂停功能关闭时应返回 False"""
        config = {"enabled": False, "start_hour": 0, "end_hour": 6}
        assert is_in_pause_period(config) is False

    def test_same_hour_means_all_day(self):
        """start_hour == end_hour 表示全天暂停"""
        config = {"enabled": True, "start_hour": 5, "end_hour": 5}
        assert is_in_pause_period(config) is True

    def test_normal_range_in_pause(self):
        """正常范围内的时段应返回 True"""
        config = {"enabled": True, "start_hour": 0, "end_hour": 6}
        mock_now = datetime.datetime(2025, 1, 1, 3, 0, 0)
        with patch("src.utils.time_utils.datetime") as mock_dt:
            mock_dt.datetime.now.return_value = mock_now
            assert is_in_pause_period(config) is True

    def test_normal_range_outside_pause(self):
        """正常范围外的时段应返回 False"""
        config = {"enabled": True, "start_hour": 0, "end_hour": 6}
        mock_now = datetime.datetime(2025, 1, 1, 12, 0, 0)
        with patch("src.utils.time_utils.datetime") as mock_dt:
            mock_dt.datetime.now.return_value = mock_now
            assert is_in_pause_period(config) is False

    def test_cross_midnight_in_pause(self):
        """跨午夜暂停（23:00-06:00），凌晨 2 点应在暂停内"""
        config = {"enabled": True, "start_hour": 23, "end_hour": 6}
        mock_now = datetime.datetime(2025, 1, 1, 2, 0, 0)
        with patch("src.utils.time_utils.datetime") as mock_dt:
            mock_dt.datetime.now.return_value = mock_now
            assert is_in_pause_period(config) is True

    def test_cross_midnight_outside_pause(self):
        """跨午夜暂停（23:00-06:00），中午 12 点应不在暂停内"""
        config = {"enabled": True, "start_hour": 23, "end_hour": 6}
        mock_now = datetime.datetime(2025, 1, 1, 12, 0, 0)
        with patch("src.utils.time_utils.datetime") as mock_dt:
            mock_dt.datetime.now.return_value = mock_now
            assert is_in_pause_period(config) is False

    def test_missing_keys_in_pause(self):
        """空配置默认启用暂停（0-6 点），凌晨 3 点应在暂停内"""
        config = {}
        mock_now = datetime.datetime(2025, 1, 1, 3, 0, 0)
        with patch("src.utils.time_utils.datetime") as mock_dt:
            mock_dt.datetime.now.return_value = mock_now
            assert is_in_pause_period(config) is True

    def test_missing_keys_outside_pause(self):
        """空配置默认启用暂停（0-6 点），中午 12 点应不在暂停内"""
        config = {}
        mock_now = datetime.datetime(2025, 1, 1, 12, 0, 0)
        with patch("src.utils.time_utils.datetime") as mock_dt:
            mock_dt.datetime.now.return_value = mock_now
            assert is_in_pause_period(config) is False


class TestGetRuntimeStats:
    def test_basic(self):
        """基本运行时间统计"""
        start = time.time() - 3665  # ~1 小时 1 分前
        runtime_str, stats_str = get_runtime_stats(start, 42)
        assert "01:01:" in runtime_str
        assert "42" in stats_str

    def test_zero_time(self):
        """刚启动时的统计"""
        start = time.time()
        runtime_str, stats_str = get_runtime_stats(start, 0)
        assert "00:00:0" in runtime_str
        assert "0" in stats_str

    def test_none_start_time(self):
        """None 开始时间应返回默认值"""
        runtime_str, stats_str = get_runtime_stats(None, 10)
        assert runtime_str == "00:00:00"
        assert "10" in stats_str
