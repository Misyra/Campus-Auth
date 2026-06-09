"""WebSocket 管理器 — 实时日志推送的基础设施组件。

从 monitor_service.py 提取，作为独立模块供多个组件使用。
"""

from __future__ import annotations

import asyncio

from fastapi import WebSocket

from app.utils.logging import get_logger

ws_logger = get_logger("backend.ws_manager", source="BACKEND")


class WebSocketManager:
    """WebSocket 管理器 - 实时日志推送"""

    def __init__(self):
        self._connections: list[WebSocket] = []
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        async with self._lock:
            self._connections.append(websocket)

    async def disconnect(self, websocket: WebSocket):
        async with self._lock:
            if websocket in self._connections:
                self._connections.remove(websocket)

    async def broadcast(self, message: str):
        """广播消息（直接发送，保证实时性）"""
        async with self._lock:
            connections = self._connections.copy()

        if not connections:
            return

        # 并发发送给所有连接
        tasks = [self._send_safe(ws, message) for ws in connections]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 清理断开连接
        async with self._lock:
            for ws, result in zip(connections, results, strict=False):
                if isinstance(result, Exception) and ws in self._connections:
                    self._connections.remove(ws)

    async def close_all(self):
        """关闭所有 WebSocket 连接"""
        async with self._lock:
            connections = self._connections.copy()
            self._connections.clear()

        for ws in connections:
            try:
                await ws.close(code=1001, reason="Server shutting down")
            except Exception:
                ws_logger.debug("ws close 失败", exc_info=True)

    async def _send_safe(self, ws: WebSocket, message: str):
        try:
            await asyncio.wait_for(ws.send_text(message), timeout=5.0)
        except TimeoutError:
            ws_logger.warning("WebSocket 发送超时，断开连接")
            async with self._lock:
                if ws in self._connections:
                    self._connections.remove(ws)
