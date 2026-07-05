"""WebSocketManager 广播队列功能测试（原 WsBroadcaster 测试）。

覆盖：队列管理、消息入队、DashboardSink 迁移、WS 排空、事件驱动唤醒。
"""

from __future__ import annotations

import asyncio
import json
from collections import deque
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.websocket_manager import WebSocketManager


class TestBroadcastQueueInit:
    def test_default_state(self):
        mgr = WebSocketManager()
        assert mgr._dashboard_sink is None
        assert len(mgr.broadcast_queue) == 0

    def test_drain_event_initialized(self):
        mgr = WebSocketManager()
        assert isinstance(mgr._drain_event, asyncio.Event)
        assert not mgr._drain_event.is_set()

    def test_loop_initialized_to_none(self):
        mgr = WebSocketManager()
        assert mgr._loop is None


class TestSetLoop:
    def test_set_loop(self):
        mgr = WebSocketManager()
        loop = MagicMock()
        mgr.set_loop(loop)
        assert mgr._loop is loop


class TestNotifyDrain:
    def test_sets_event_when_no_loop(self):
        mgr = WebSocketManager()
        assert not mgr._drain_event.is_set()
        mgr._notify_drain()
        assert mgr._drain_event.is_set()

    def test_calls_call_soon_threadsafe_when_loop_running(self):
        mgr = WebSocketManager()
        loop = MagicMock()
        loop.is_running.return_value = True
        mgr.set_loop(loop)
        mgr._notify_drain()
        loop.call_soon_threadsafe.assert_called_once_with(mgr._drain_event.set)

    def test_falls_back_to_set_when_loop_not_running(self):
        mgr = WebSocketManager()
        loop = MagicMock()
        loop.is_running.return_value = False
        mgr.set_loop(loop)
        assert not mgr._drain_event.is_set()
        mgr._notify_drain()
        assert mgr._drain_event.is_set()
        loop.call_soon_threadsafe.assert_not_called()


class TestBroadcastQueue:
    def test_empty_queue_when_no_sink(self):
        mgr = WebSocketManager()
        assert len(mgr.broadcast_queue) == 0

    def test_returns_sink_queue_when_sink_set(self):
        mgr = WebSocketManager()
        sink = MagicMock()
        sink.broadcast_queue = deque(maxlen=100)
        mgr.set_dashboard_sink(sink)
        assert mgr.broadcast_queue is sink.broadcast_queue

    def test_returns_empty_queue_when_no_sink(self):
        mgr = WebSocketManager()
        q = mgr.broadcast_queue
        assert q is mgr._empty_broadcast_queue


class TestEnqueueStatus:
    def test_enqueue_status(self):
        mgr = WebSocketManager()
        sink = MagicMock()
        sink.broadcast_queue = deque(maxlen=100)
        mgr.set_dashboard_sink(sink)
        mgr.enqueue_status({"monitoring": False})
        assert len(sink.broadcast_queue) == 1
        msg = sink.broadcast_queue[0]
        assert msg["type"] == "status"
        assert msg["data"]["monitoring"] is False

    def test_enqueue_to_empty_queue(self):
        mgr = WebSocketManager()
        mgr.enqueue_status({"monitoring": True})
        assert len(mgr.broadcast_queue) == 1

    def test_enqueue_multiple(self):
        mgr = WebSocketManager()
        mgr.enqueue_status({"a": 1})
        mgr.enqueue_status({"b": 2})
        assert len(mgr.broadcast_queue) == 2

    def test_enqueue_triggers_drain_event(self):
        """enqueue_status 应设置 _drain_event 唤醒 drain loop。"""
        mgr = WebSocketManager()
        assert not mgr._drain_event.is_set()
        mgr.enqueue_status({"test": "data"})
        assert mgr._drain_event.is_set()


class TestSetDashboardSinkMigration:
    def test_migrates_old_queue_to_new_sink(self):
        mgr = WebSocketManager()
        mgr.enqueue_status({"old": True})
        mgr.enqueue_status({"old2": True})
        sink = MagicMock()
        sink.broadcast_queue = deque(maxlen=100)
        mgr.set_dashboard_sink(sink)
        assert len(sink.broadcast_queue) == 2
        assert len(mgr._empty_broadcast_queue) == 0

    def test_empty_old_queue_noop(self):
        mgr = WebSocketManager()
        sink = MagicMock()
        sink.broadcast_queue = deque(maxlen=100)
        mgr.set_dashboard_sink(sink)
        assert len(sink.broadcast_queue) == 0
        assert mgr._dashboard_sink is sink

    def test_migrates_when_old_queue_full(self):
        mgr = WebSocketManager()
        for i in range(15):
            mgr.enqueue_status({"i": i})
        # maxlen=10, only last 10 remain
        assert len(mgr._empty_broadcast_queue) == 10
        sink = MagicMock()
        sink.broadcast_queue = deque(maxlen=100)
        mgr.set_dashboard_sink(sink)
        assert len(sink.broadcast_queue) == 10
        assert len(mgr._empty_broadcast_queue) == 0

    def test_injects_drain_notifier(self):
        """set_dashboard_sink 应向 sink 注入 drain 通知器。"""
        mgr = WebSocketManager()
        sink = MagicMock()
        sink.broadcast_queue = deque(maxlen=100)
        mgr.set_dashboard_sink(sink)
        sink.set_drain_notifier.assert_called_once_with(mgr._notify_drain)


class TestDrainQueue:
    @pytest.mark.asyncio
    async def test_drain_empty_queue(self):
        mgr = WebSocketManager()
        with patch.object(mgr, "broadcast", new_callable=AsyncMock) as mock_broadcast:
            await mgr._drain_queue()
            mock_broadcast.assert_not_called()

    @pytest.mark.asyncio
    async def test_drain_with_messages(self):
        mgr = WebSocketManager()
        sink = MagicMock()
        sink.broadcast_queue = deque(maxlen=100)
        mgr.set_dashboard_sink(sink)
        mgr.enqueue_status({"test": 1})
        mgr.enqueue_status({"test": 2})
        with patch.object(mgr, "broadcast", new_callable=AsyncMock) as mock_broadcast:
            await mgr._drain_queue()
            assert mock_broadcast.call_count == 2
            # verify JSON serialization
            call_arg = mock_broadcast.call_args_list[0][0][0]
            assert json.loads(call_arg)["type"] == "status"

    @pytest.mark.asyncio
    async def test_drain_broadcast_error_continues(self):
        mgr = WebSocketManager()
        sink = MagicMock()
        sink.broadcast_queue = deque(maxlen=100)
        mgr.set_dashboard_sink(sink)
        mgr.enqueue_status({"test": 1})
        mgr.enqueue_status({"test": 2})
        with patch.object(
            mgr,
            "broadcast",
            new_callable=AsyncMock,
            side_effect=RuntimeError("ws error"),
        ) as mock_broadcast:
            # 不应抛异常
            await mgr._drain_queue()
            assert mock_broadcast.call_count == 2


class TestWsDrainLoop:
    @pytest.mark.asyncio
    async def test_loop_cancels_cleanly(self):
        mgr = WebSocketManager()
        task = asyncio.create_task(mgr.ws_drain_loop())
        await asyncio.sleep(0.05)
        task.cancel()
        await task
        assert task.done()

    @pytest.mark.asyncio
    async def test_loop_drains_on_enqueue(self):
        """drain loop 应在 enqueue_status 后立即排空队列。"""
        mgr = WebSocketManager()
        sink = MagicMock()
        sink.broadcast_queue = deque(maxlen=100)
        mgr.set_dashboard_sink(sink)
        mgr.enqueue_status({"test": 1})
        with patch.object(mgr, "broadcast", new_callable=AsyncMock) as mock_broadcast:
            task = asyncio.create_task(mgr.ws_drain_loop())
            await asyncio.sleep(0.05)
            task.cancel()
            await task
            mock_broadcast.assert_called()

    @pytest.mark.asyncio
    async def test_loop_sets_loop_reference(self):
        """ws_drain_loop 启动时应自动设置 _loop 引用。"""
        mgr = WebSocketManager()
        assert mgr._loop is None
        task = asyncio.create_task(mgr.ws_drain_loop())
        await asyncio.sleep(0.01)
        assert mgr._loop is asyncio.get_running_loop()
        task.cancel()
        await task

    @pytest.mark.asyncio
    async def test_drain_loop_wakes_on_event(self):
        """drain loop 应在 _drain_event 设置后立即排空队列。"""
        mgr = WebSocketManager()
        mgr.set_loop(asyncio.get_running_loop())
        mgr.enqueue_status({"test": "data"})

        with patch.object(mgr, "broadcast", new_callable=AsyncMock) as mock_broadcast:
            await mgr._drain_queue()
            assert len(mgr.broadcast_queue) == 0
            mock_broadcast.assert_called_once()

    @pytest.mark.asyncio
    async def test_drain_loop_no_wakeup_when_idle(self):
        """空闲时 drain_event 不应被设置。"""
        mgr = WebSocketManager()
        assert not mgr._drain_event.is_set()

    @pytest.mark.asyncio
    async def test_ws_drain_loop_exits_on_cancel(self):
        """ws_drain_loop 应在 CancelledError 时干净退出。"""
        mgr = WebSocketManager()
        task = asyncio.create_task(mgr.ws_drain_loop())
        await asyncio.sleep(0.05)
        task.cancel()
        await task
        assert task.done()
        assert not task.cancelled()
