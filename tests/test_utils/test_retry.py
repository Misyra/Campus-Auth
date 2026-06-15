"""重试间隔计算工具测试 — 覆盖固定间隔与指数退避逻辑。"""

from __future__ import annotations

import pytest

from app.utils.retry import get_retry_intervals


class TestGetRetryIntervals:
    """get_retry_intervals 参数化测试。"""

    # ── 固定间隔模式 (exponential=False) ──

    @pytest.mark.parametrize(
        "retry_interval, max_retries, expected",
        [
            (5, 0, []),
            (5, 1, [5]),
            (5, 3, [5, 5, 5]),
            (10, 5, [10, 10, 10, 10, 10]),
            (1, 4, [1, 1, 1, 1]),
        ],
        ids=[
            "fixed_zero_retries",
            "fixed_one_retry",
            "fixed_three_retries",
            "fixed_five_retries",
            "fixed_interval_1",
        ],
    )
    def test_fixed_interval(self, retry_interval, max_retries, expected):
        """固定间隔模式应返回相同间隔的列表。"""
        result = get_retry_intervals(retry_interval, max_retries)
        assert result == expected

    # ── 指数退避模式 (exponential=True) ──

    @pytest.mark.parametrize(
        "retry_interval, max_retries, expected",
        [
            (5, 0, []),
            (5, 1, [5]),
            (5, 3, [5, 10, 20]),
            (5, 5, [5, 10, 20, 40, 80]),
            (10, 4, [10, 20, 40, 80]),
            (1, 1, [1]),
            (3, 4, [3, 6, 12, 24]),
        ],
        ids=[
            "exp_zero_retries",
            "exp_one_retry",
            "exp_three_retries",
            "exp_five_retries",
            "exp_interval_10",
            "exp_interval_1",
            "exp_interval_3",
        ],
    )
    def test_exponential_interval(self, retry_interval, max_retries, expected):
        """指数退避模式应返回翻倍间隔的列表。"""
        result = get_retry_intervals(
            retry_interval, max_retries, exponential=True,
        )
        assert result == expected

    # ── 边界条件 ──

    def test_fixed_exponential_equivalent_when_max_retries_0(self):
        """max_retries=0 时两种模式均返回空列表。"""
        assert get_retry_intervals(5, 0) == []
        assert get_retry_intervals(5, 0, exponential=True) == []

    def test_fixed_exponential_equivalent_when_max_retries_1(self):
        """max_retries=1 时两种模式返回相同结果。"""
        assert get_retry_intervals(7, 1) == [7]
        assert get_retry_intervals(7, 1, exponential=True) == [7]

    def test_large_interval(self):
        """较大间隔值应正确计算。"""
        result = get_retry_intervals(100, 3, exponential=True)
        assert result == [100, 200, 400]

    def test_default_exponential_is_false(self):
        """默认 exponential=False 等同于固定间隔。"""
        result = get_retry_intervals(3, 3)
        assert result == [3, 3, 3]
