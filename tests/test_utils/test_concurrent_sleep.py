"""interruptible_sleep 单元测试。"""

from __future__ import annotations

import asyncio
import threading
import time

from app.utils.concurrent import interruptible_sleep


class TestInterruptibleSleep:
    async def test_normal_completion_returns_true(self):
        """未取消时，等待完成后返回 True。"""
        result = await interruptible_sleep(0.1, threading.Event())
        assert result is True

    async def test_cancel_during_sleep_returns_false(self):
        """等待中 set cancel_event，应快速返回 False。"""
        cancel_event = threading.Event()
        start = time.monotonic()

        async def cancel_soon():
            await asyncio.sleep(0.05)
            cancel_event.set()

        asyncio.create_task(cancel_soon())
        result = await interruptible_sleep(1.0, cancel_event, poll_interval=0.05)

        elapsed = time.monotonic() - start
        assert result is False
        # 响应时间应远小于 1.0s（poll_interval=0.05 + ε）
        assert elapsed < 0.3

    async def test_zero_seconds_returns_true_immediately(self):
        """seconds=0 立即返回 True。"""
        result = await interruptible_sleep(0, threading.Event())
        assert result is True

    async def test_negative_seconds_returns_true_immediately(self):
        """seconds 为负数立即返回 True（防御性）。"""
        result = await interruptible_sleep(-5.0, threading.Event())
        assert result is True

    async def test_already_set_cancel_returns_false_quickly(self):
        """cancel_event 已 set 时，首次检查即返回 False。"""
        cancel_event = threading.Event()
        cancel_event.set()
        start = time.monotonic()
        result = await interruptible_sleep(10.0, cancel_event)
        elapsed = time.monotonic() - start
        assert result is False
        assert elapsed < 0.1

    async def test_custom_poll_interval(self):
        """自定义 poll_interval 影响取消响应上界。"""
        cancel_event = threading.Event()

        async def cancel_soon():
            await asyncio.sleep(0.05)
            cancel_event.set()

        asyncio.create_task(cancel_soon())
        # poll_interval=0.01 比 0.2 更快响应
        result = await interruptible_sleep(1.0, cancel_event, poll_interval=0.01)
        assert result is False
