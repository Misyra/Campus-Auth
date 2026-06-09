"""WebSocket 管理器测试 — WebSocketManager

覆盖：connect / disconnect / broadcast / close_all / _send_safe / 断开连接清理
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.ws_manager import WebSocketManager

# =====================================================================
# WebSocketManager
# =====================================================================


class TestWebSocketManager:
    @pytest.fixture
    def manager(self) -> WebSocketManager:
        return WebSocketManager()

    # ── connect / disconnect ──

    @pytest.mark.asyncio
    async def test_connect_accepts_and_adds(self, manager: WebSocketManager):
        ws = AsyncMock()
        await manager.connect(ws)
        ws.accept.assert_awaited_once()
        assert ws in manager._connections

    @pytest.mark.asyncio
    async def test_disconnect_removes(self, manager: WebSocketManager):
        ws = AsyncMock()
        await manager.connect(ws)
        await manager.disconnect(ws)
        assert ws not in manager._connections

    @pytest.mark.asyncio
    async def test_disconnect_nonexistent_no_error(self, manager: WebSocketManager):
        ws = AsyncMock()
        # 未连接时断开不应抛异常
        await manager.disconnect(ws)

    @pytest.mark.asyncio
    async def test_multiple_connections(self, manager: WebSocketManager):
        ws1, ws2, ws3 = AsyncMock(), AsyncMock(), AsyncMock()
        await manager.connect(ws1)
        await manager.connect(ws2)
        await manager.connect(ws3)
        assert len(manager._connections) == 3

    # ── broadcast ──

    @pytest.mark.asyncio
    async def test_broadcast_sends_to_all(self, manager: WebSocketManager):
        ws1, ws2 = AsyncMock(), AsyncMock()
        await manager.connect(ws1)
        await manager.connect(ws2)
        await manager.broadcast("hello")
        ws1.send_text.assert_awaited_once_with("hello")
        ws2.send_text.assert_awaited_once_with("hello")

    @pytest.mark.asyncio
    async def test_broadcast_empty_connections(self, manager: WebSocketManager):
        # 无连接时不应抛异常
        await manager.broadcast("hello")

    @pytest.mark.asyncio
    async def test_broadcast_removes_failed_connections(
        self, manager: WebSocketManager
    ):
        ws_ok = AsyncMock()
        ws_fail = AsyncMock()
        ws_fail.send_text.side_effect = Exception("connection lost")
        await manager.connect(ws_ok)
        await manager.connect(ws_fail)
        await manager.broadcast("hello")
        assert ws_ok in manager._connections
        assert ws_fail not in manager._connections

    # ── close_all ──

    @pytest.mark.asyncio
    async def test_close_all_closes_connections(self, manager: WebSocketManager):
        ws1, ws2 = AsyncMock(), AsyncMock()
        await manager.connect(ws1)
        await manager.connect(ws2)
        await manager.close_all()
        ws1.close.assert_awaited_once()
        ws2.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_close_all_clears_list(self, manager: WebSocketManager):
        ws = AsyncMock()
        await manager.connect(ws)
        await manager.close_all()
        assert len(manager._connections) == 0

    @pytest.mark.asyncio
    async def test_close_all_handles_close_error(self, manager: WebSocketManager):
        ws = AsyncMock()
        ws.close.side_effect = Exception("already closed")
        await manager.connect(ws)
        # 不应抛异常
        await manager.close_all()
        assert len(manager._connections) == 0

    # ── _send_safe ──

    @pytest.mark.asyncio
    async def test_send_safe_success(self, manager: WebSocketManager):
        ws = AsyncMock()
        await manager._send_safe(ws, "test")
        ws.send_text.assert_awaited_once_with("test")

    @pytest.mark.asyncio
    async def test_send_safe_timeout_removes(self, manager: WebSocketManager):
        ws = AsyncMock()
        ws.send_text.side_effect = TimeoutError()
        await manager.connect(ws)
        await manager._send_safe(ws, "test")
        assert ws not in manager._connections
