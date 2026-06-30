"""WebSocket 管理器 — 实时日志推送的基础设施组件。

从 monitor_service.py 提取，作为独立模块供多个组件使用。
合并原 WsBroadcaster 的广播队列功能。
"""

from __future__ import annotations

import asyncio
import json
from collections import deque
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import WebSocket
    from app.utils.logging import DashboardSink

from app.utils.logging import get_logger

ws_logger = get_logger("websocket_manager", source="backend")


class WebSocketManager:
    """WebSocket 管理器 — 连接管理 + 广播队列"""

    def __init__(self):
        self._connections: list[WebSocket] = []
        self._lock = asyncio.Lock()
        # 广播队列
        self._dashboard_sink: DashboardSink | None = None
        self._empty_broadcast_queue: deque = deque(maxlen=10)
        self._drain_event: asyncio.Event = asyncio.Event()
        self._loop: asyncio.AbstractEventLoop | None = None

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        async with self._lock:
            self._connections.append(websocket)
        ws_logger.debug("WebSocket 客户端已连接")

    async def disconnect(self, websocket: WebSocket):
        async with self._lock:
            removed = websocket in self._connections
            if removed:
                self._connections.remove(websocket)
        if removed:
            try:
                await websocket.close()
            except Exception:
                ws_logger.warning("WebSocket 关闭失败", exc_info=True)

    async def broadcast(self, message: str):
        """广播消息（直接发送，保证实时性）"""
        async with self._lock:
            connections = self._connections.copy()

        if not connections:
            return

        # 并发发送给所有连接，总体超时 5 秒
        # 显式创建任务，便于超时时检查状态和取消
        tasks = [asyncio.create_task(self._send_safe(ws, message)) for ws in connections]
        try:
            results = await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=5.0,
            )
        except TimeoutError:
            ws_logger.warning("WebSocket 广播失败: 超时")
            # 超时时取消未完成的任务，清理对应连接
            # _send_safe 内部会清理单个超时的连接，但总体超时时
            # 有些任务被取消了，没机会执行清理，需要手动处理
            to_close = []
            async with self._lock:
                for ws, task in zip(connections, tasks):
                    if not task.done() and ws in self._connections:
                        self._connections.remove(ws)
                        to_close.append(ws)
                        task.cancel()
            for ws in to_close:
                try:
                    await ws.close()
                except Exception:
                    ws_logger.warning("WebSocket 关闭失败", exc_info=True)
            return

        # 清理断开连接
        # 已知：list.remove() 是 O(n)，k 个死亡连接总代价 O(k·n)。
        # 实际无影响：本地桌面应用仅监听 127.0.0.1，连接数通常为 1-2 个（浏览器标签页），
        # O(n²) 在 n≤2 时等价于 O(1)。无需改为 set/dict。
        to_close = []
        async with self._lock:
            for ws, result in zip(connections, results, strict=False):
                if isinstance(result, Exception) and ws in self._connections:
                    self._connections.remove(ws)
                    to_close.append(ws)
        for ws in to_close:
            try:
                await ws.close()
            except Exception:
                ws_logger.warning("WebSocket 关闭失败", exc_info=True)

    async def close_all(self):
        """关闭所有 WebSocket 连接"""
        async with self._lock:
            connections = self._connections.copy()
            self._connections.clear()

        for ws in connections:
            try:
                await ws.close(code=1001, reason="Server shutting down")
            except Exception:
                ws_logger.warning("WebSocket 关闭失败", exc_info=True)

    async def _send_safe(self, ws: WebSocket, message: str):
        try:
            await asyncio.wait_for(ws.send_text(message), timeout=2.0)
        except TimeoutError:
            ws_logger.warning("WebSocket 发送失败: 超时")
            async with self._lock:
                removed = ws in self._connections
                if removed:
                    self._connections.remove(ws)
            if removed:
                try:
                    await ws.close()
                except Exception:
                    ws_logger.warning("WebSocket 关闭失败", exc_info=True)

    # ── 广播队列（原 WsBroadcaster）──

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """记录事件循环引用，用于跨线程安全唤醒。"""
        self._loop = loop

    def _notify_drain(self) -> None:
        """唤醒 drain loop（线程安全）。"""
        if self._loop is not None and self._loop.is_running():
            try:
                self._loop.call_soon_threadsafe(self._drain_event.set)
            except RuntimeError:
                # loop 关闭过程中 call_soon_threadsafe 可能失败，回退到直接 set
                self._drain_event.set()
        else:
            self._drain_event.set()

    def set_dashboard_sink(self, sink: DashboardSink) -> None:
        """注入 DashboardSink，并迁移轻量模式期间积累的广播消息。"""
        old_queue = self._empty_broadcast_queue
        new_queue = sink.broadcast_queue
        if old_queue:
            while old_queue:
                try:
                    new_queue.append(old_queue.popleft())
                except IndexError:
                    break
        # 原子切换：此后 enqueue_status 直接入队到 sink，不再写入 old_queue
        self._dashboard_sink = sink
        # 捕获迁移窗口（迁移循环结束 -> 赋值）期间新入队的消息
        if old_queue:
            while old_queue:
                try:
                    new_queue.append(old_queue.popleft())
                except IndexError:
                    break
        # 注入 drain 通知器并立即唤醒 drain loop，避免已迁移消息延迟排空
        sink.set_drain_notifier(self._notify_drain)
        self._notify_drain()

    @property
    def broadcast_queue(self) -> deque:
        """WS 广播队列（从 DashboardSink 获取）。"""
        if self._dashboard_sink is None:
            return self._empty_broadcast_queue
        return self._dashboard_sink.broadcast_queue

    def enqueue_status(self, status_dict: dict) -> None:
        """将状态更新放入广播队列。"""
        try:
            queue = self.broadcast_queue
            if queue.maxlen is not None and len(queue) >= queue.maxlen:
                ws_logger.warning(
                    "WebSocket 广播队列已满 (maxlen={})，丢弃最旧消息",
                    queue.maxlen,
                )
            queue.append({"type": "status", "data": status_dict})
            self._notify_drain()
        except Exception as exc:
            ws_logger.exception("状态广播入队失败: {}", exc)

    async def ws_drain_loop(self) -> None:
        """后台 asyncio 任务：事件驱动排空 WS 广播队列。

        空闲时阻塞在 _drain_event.wait()，有新消息入队时通过 set() 唤醒。
        异常不会退出循环，CancelledError 由外层捕获退出。
        """
        self.set_loop(asyncio.get_running_loop())
        ws_logger.info("WebSocket 排空循环已启动")
        while True:
            try:
                await self._drain_event.wait()
                self._drain_event.clear()
                await self._drain_queue()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                ws_logger.exception("WebSocket 排空循环异常: {}", exc)
                await asyncio.sleep(1)

    async def _drain_queue(self) -> None:
        """排空 WS 广播队列到 WebSocket 客户端。"""
        broadcast_queue = self.broadcast_queue
        while True:
            try:
                data = broadcast_queue.popleft()
            except IndexError:
                break
            try:
                await self.broadcast(json.dumps(data))
            except Exception as exc:
                ws_logger.exception("WebSocket 广播发送异常: {}", exc)
