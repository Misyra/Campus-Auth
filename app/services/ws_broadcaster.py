"""WsBroadcaster — WebSocket 广播队列管理。

从 ScheduleEngine 提取，负责：
- 管理 broadcast_queue（从 DashboardSink 获取或 fallback 到空队列）
- ws_drain_loop（asyncio 后台任务，定期排空队列到 WS 客户端）
- drain_ws_queue（单次排空）
- set_dashboard_sink（注入 sink 并迁移积累的消息）
- enqueue_status（将状态放入队列）
"""

from __future__ import annotations

import asyncio
import json
from collections import deque
from typing import TYPE_CHECKING

from app.utils.logging import get_logger

if TYPE_CHECKING:
    from app.services.websocket_manager import WebSocketManager
    from app.utils.logging import DashboardSink

logger = get_logger("ws_broadcaster", source="backend")

# WS 广播队列排空间隔（秒）
WS_DRAIN_INTERVAL_SECONDS = 0.05


class WsBroadcaster:
    """WebSocket 广播队列管理器。"""

    def __init__(self, ws_manager: WebSocketManager | None = None):
        self._ws_manager = ws_manager
        self._dashboard_sink: DashboardSink | None = None
        # 轻量模式下的空广播队列（仅接收不消费，小容量即可）
        self._empty_broadcast_queue: deque = deque(maxlen=10)
        self._drain_event: asyncio.Event = asyncio.Event()
        self._loop: asyncio.AbstractEventLoop | None = None

    def set_ws_manager(self, ws_manager: WebSocketManager) -> None:
        """切换 WS 管理器（轻量模式唤醒时调用）。"""
        self._ws_manager = ws_manager

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """记录事件循环引用，用于跨线程安全唤醒。"""
        self._loop = loop

    def _notify_drain(self) -> None:
        """唤醒 drain loop（线程安全）。"""
        if self._loop is not None and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._drain_event.set)
        else:
            self._drain_event.set()

    def set_dashboard_sink(self, sink: DashboardSink) -> None:
        """注入 DashboardSink，并迁移轻量模式期间积累的广播消息。"""
        old_queue = self._empty_broadcast_queue
        if old_queue:
            new_queue = sink.broadcast_queue
            while old_queue:
                try:
                    new_queue.append(old_queue.popleft())
                except IndexError:
                    break
        self._dashboard_sink = sink
        # 注入 drain 通知器
        sink.set_drain_notifier(self._notify_drain)

    @property
    def broadcast_queue(self) -> deque:
        """WS 广播队列（从 DashboardSink 获取）。"""
        if self._dashboard_sink is None:
            return self._empty_broadcast_queue
        return self._dashboard_sink.broadcast_queue

    def enqueue_status(self, status_dict: dict) -> None:
        """将状态更新放入广播队列。"""
        try:
            self.broadcast_queue.append({"type": "status", "data": status_dict})
            self._notify_drain()
        except Exception:
            logger.exception("状态广播入队失败")

    async def ws_drain_loop(self) -> None:
        """后台 asyncio 任务：事件驱动排空 WS 广播队列。

        空闲时阻塞在 _drain_event.wait()，有新消息入队时通过 set() 唤醒。
        异常不会退出循环，CancelledError 由外层捕获退出。
        """
        self.set_loop(asyncio.get_running_loop())
        while True:
            try:
                await self._drain_event.wait()
                self._drain_event.clear()
                await self.drain_ws_queue()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("WS 排空循环异常")

    async def drain_ws_queue(self) -> None:
        """排空 WS 广播队列到 WebSocket 客户端。"""
        if self._ws_manager is None:
            return
        broadcast_queue = self.broadcast_queue
        while True:
            try:
                data = broadcast_queue.popleft()
            except IndexError:
                break
            try:
                await self._ws_manager.broadcast(json.dumps(data))
            except Exception:
                logger.exception("WS 广播发送失败")
