"""WsBroadcaster 单元测试。

覆盖：队列管理、消息入队、DashboardSink 迁移、WS 排空。
"""

from __future__ import annotations

import asyncio
import json
from collections import deque
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.ws_broadcaster import WsBroadcaster, WS_DRAIN_INTERVAL_SECONDS


class TestWsBroadcasterInit:
    def test_default_state(self):
        bc = WsBroadcaster()
        assert bc._ws_manager is None
        assert bc._dashboard_sink is None
        assert len(bc.broadcast_queue) == 0

    def test_ws_manager_injection(self):
        mock_ws = MagicMock()
        bc = WsBroadcaster(ws_manager=mock_ws)
        assert bc._ws_manager is mock_ws


class TestSetWsManager:
    def test_switch_ws_manager(self):
        bc = WsBroadcaster()
        mock_ws = MagicMock()
        bc.set_ws_manager(mock_ws)
        assert bc._ws_manager is mock_ws


class TestBroadcastQueue:
    def test_empty_queue_when_no_sink(self):
        bc = WsBroadcaster()
        assert len(bc.broadcast_queue) == 0

    def test_returns_sink_queue_when_sink_set(self):
        bc = WsBroadcaster()
        sink = MagicMock()
        sink.broadcast_queue = deque(maxlen=100)
        bc.set_dashboard_sink(sink)
        assert bc.broadcast_queue is sink.broadcast_queue

    def test_returns_empty_queue_when_no_sink(self):
        bc = WsBroadcaster()
        q = bc.broadcast_queue
        assert q is bc._empty_broadcast_queue


class TestEnqueueStatus:
    def test_enqueue_status(self):
        bc = WsBroadcaster()
        sink = MagicMock()
        sink.broadcast_queue = deque(maxlen=100)
        bc.set_dashboard_sink(sink)
        bc.enqueue_status({"monitoring": False})
        assert len(sink.broadcast_queue) == 1
        msg = sink.broadcast_queue[0]
        assert msg["type"] == "status"
        assert msg["data"]["monitoring"] is False

    def test_enqueue_to_empty_queue(self):
        bc = WsBroadcaster()
        bc.enqueue_status({"monitoring": True})
        assert len(bc.broadcast_queue) == 1

    def test_enqueue_multiple(self):
        bc = WsBroadcaster()
        bc.enqueue_status({"a": 1})
        bc.enqueue_status({"b": 2})
        assert len(bc.broadcast_queue) == 2


class TestSetDashboardSinkMigration:
    def test_migrates_old_queue_to_new_sink(self):
        bc = WsBroadcaster()
        bc.enqueue_status({"old": True})
        bc.enqueue_status({"old2": True})
        sink = MagicMock()
        sink.broadcast_queue = deque(maxlen=100)
        bc.set_dashboard_sink(sink)
        assert len(sink.broadcast_queue) == 2
        assert len(bc._empty_broadcast_queue) == 0

    def test_empty_old_queue_noop(self):
        bc = WsBroadcaster()
        sink = MagicMock()
        sink.broadcast_queue = deque(maxlen=100)
        bc.set_dashboard_sink(sink)
        assert len(sink.broadcast_queue) == 0
        assert bc._dashboard_sink is sink

    def test_migrates_when_old_queue_full(self):
        bc = WsBroadcaster()
        for i in range(15):
            bc.enqueue_status({"i": i})
        # maxlen=10, only last 10 remain
        assert len(bc._empty_broadcast_queue) == 10
        sink = MagicMock()
        sink.broadcast_queue = deque(maxlen=100)
        bc.set_dashboard_sink(sink)
        assert len(sink.broadcast_queue) == 10
        assert len(bc._empty_broadcast_queue) == 0


class TestDrainWsQueue:
    @pytest.mark.asyncio
    async def test_drain_empty_queue(self):
        ws_manager = AsyncMock()
        bc = WsBroadcaster(ws_manager=ws_manager)
        await bc.drain_ws_queue()
        ws_manager.broadcast.assert_not_called()

    @pytest.mark.asyncio
    async def test_drain_with_messages(self):
        ws_manager = AsyncMock()
        bc = WsBroadcaster(ws_manager=ws_manager)
        sink = MagicMock()
        sink.broadcast_queue = deque(maxlen=100)
        bc.set_dashboard_sink(sink)
        bc.enqueue_status({"test": 1})
        bc.enqueue_status({"test": 2})
        await bc.drain_ws_queue()
        assert ws_manager.broadcast.call_count == 2
        # verify JSON serialization
        call_arg = ws_manager.broadcast.call_args_list[0][0][0]
        assert json.loads(call_arg)["type"] == "status"

    @pytest.mark.asyncio
    async def test_drain_no_ws_manager(self):
        bc = WsBroadcaster()
        sink = MagicMock()
        sink.broadcast_queue = deque(maxlen=100)
        bc.set_dashboard_sink(sink)
        bc.enqueue_status({"test": 1})
        await bc.drain_ws_queue()
        # 没有 ws_manager，消息仍在队列中
        assert len(sink.broadcast_queue) == 1

    @pytest.mark.asyncio
    async def test_drain_broadcast_error_continues(self):
        ws_manager = AsyncMock()
        ws_manager.broadcast.side_effect = RuntimeError("ws error")
        bc = WsBroadcaster(ws_manager=ws_manager)
        sink = MagicMock()
        sink.broadcast_queue = deque(maxlen=100)
        bc.set_dashboard_sink(sink)
        bc.enqueue_status({"test": 1})
        bc.enqueue_status({"test": 2})
        # 不应抛异常
        await bc.drain_ws_queue()
        assert ws_manager.broadcast.call_count == 2


class TestWsDrainLoop:
    @pytest.mark.asyncio
    async def test_loop_cancels_cleanly(self):
        bc = WsBroadcaster()
        task = asyncio.create_task(bc.ws_drain_loop())
        await asyncio.sleep(0.1)
        task.cancel()
        # CancelledError 被循环内部捕获并 break，task 正常完成
        await task
        assert task.done()

    @pytest.mark.asyncio
    async def test_loop_drains_messages(self):
        ws_manager = AsyncMock()
        bc = WsBroadcaster(ws_manager=ws_manager)
        sink = MagicMock()
        sink.broadcast_queue = deque(maxlen=100)
        bc.set_dashboard_sink(sink)
        bc.enqueue_status({"test": 1})
        task = asyncio.create_task(bc.ws_drain_loop())
        # 等待至少一个排空周期
        await asyncio.sleep(WS_DRAIN_INTERVAL_SECONDS * 3)
        task.cancel()
        await task
        ws_manager.broadcast.assert_called()


class TestConstant:
    def test_ws_drain_interval_value(self):
        assert WS_DRAIN_INTERVAL_SECONDS == 0.05
