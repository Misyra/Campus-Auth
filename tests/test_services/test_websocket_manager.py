"""websocket_manager.py — WebSocket 管理器单元测试

覆盖 WebSocketManager 的连接管理、消息广播、异常处理。
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from app.services.websocket_manager import WebSocketManager

# =====================================================================
# WebSocketManager — 连接管理
# =====================================================================


class TestWebSocketManagerConnect:
    """连接管理测试。"""

    @pytest.mark.asyncio
    async def test_connect_accepts_and_appends(self):
        mgr = WebSocketManager()
        ws = AsyncMock()
        await mgr.connect(ws)
        ws.accept.assert_awaited_once()
        assert ws in mgr._connections

    @pytest.mark.asyncio
    async def test_connect_multiple(self):
        mgr = WebSocketManager()
        ws1, ws2, ws3 = AsyncMock(), AsyncMock(), AsyncMock()
        await mgr.connect(ws1)
        await mgr.connect(ws2)
        await mgr.connect(ws3)
        assert len(mgr._connections) == 3


class TestWebSocketManagerDisconnect:
    """断开连接测试。"""

    @pytest.mark.asyncio
    async def test_disconnect_removes(self):
        mgr = WebSocketManager()
        ws = AsyncMock()
        await mgr.connect(ws)
        await mgr.disconnect(ws)
        assert ws not in mgr._connections

    @pytest.mark.asyncio
    async def test_disconnect_nonexistent_is_noop(self):
        mgr = WebSocketManager()
        ws = AsyncMock()
        await mgr.disconnect(ws)  # 不在列表中，不抛异常
        assert len(mgr._connections) == 0

    @pytest.mark.asyncio
    async def test_disconnect_only_removes_target(self):
        mgr = WebSocketManager()
        ws1, ws2 = AsyncMock(), AsyncMock()
        await mgr.connect(ws1)
        await mgr.connect(ws2)
        await mgr.disconnect(ws1)
        assert ws1 not in mgr._connections
        assert ws2 in mgr._connections


# =====================================================================
# WebSocketManager — 消息广播
# =====================================================================


class TestWebSocketManagerBroadcast:
    """消息广播测试。"""

    @pytest.mark.asyncio
    async def test_broadcast_empty_connections(self):
        mgr = WebSocketManager()
        await mgr.broadcast("msg")  # 无连接时不抛异常

    @pytest.mark.asyncio
    async def test_broadcast_sends_to_all(self):
        mgr = WebSocketManager()
        ws1, ws2 = AsyncMock(), AsyncMock()
        await mgr.connect(ws1)
        await mgr.connect(ws2)
        await mgr.broadcast("hello")
        ws1.send_text.assert_awaited_once_with("hello")
        ws2.send_text.assert_awaited_once_with("hello")

    @pytest.mark.asyncio
    async def test_broadcast_removes_failed_connection(self):
        mgr = WebSocketManager()
        ws_good = AsyncMock()
        ws_bad = AsyncMock()
        ws_bad.send_text.side_effect = ConnectionError("broken")
        await mgr.connect(ws_good)
        await mgr.connect(ws_bad)
        await mgr.broadcast("msg")
        assert ws_good in mgr._connections
        assert ws_bad not in mgr._connections

    @pytest.mark.asyncio
    async def test_broadcast_removes_already_removed_connection(self):
        """发送失败后，若连接已被其他路径移除，不应报错。"""
        mgr = WebSocketManager()
        ws = AsyncMock()
        ws.send_text.side_effect = RuntimeError("fail")
        await mgr.connect(ws)
        # 先手动移除，模拟并发场景
        mgr._connections.remove(ws)
        # broadcast 仍应正常完成
        await mgr.broadcast("msg")

    @pytest.mark.asyncio
    async def test_send_safe_timeout_removes_connection(self):
        """_send_safe 超时时应移除连接。"""
        mgr = WebSocketManager()
        ws = AsyncMock()
        ws.send_text = AsyncMock(side_effect=TimeoutError)
        await mgr.connect(ws)
        await mgr._send_safe(ws, "msg")
        assert ws not in mgr._connections

    @pytest.mark.asyncio
    async def test_send_safe_timeout_already_removed(self):
        """超时后若连接已不在列表中，不应报错。"""
        mgr = WebSocketManager()
        ws = AsyncMock()
        ws.send_text = AsyncMock(side_effect=TimeoutError)
        # 不 connect，直接调用 _send_safe
        await mgr._send_safe(ws, "msg")

    @pytest.mark.asyncio
    async def test_broadcast_calls_send_safe_for_each(self):
        """broadcast 应为每个连接调用 _send_safe。"""
        mgr = WebSocketManager()
        ws1, ws2 = AsyncMock(), AsyncMock()
        await mgr.connect(ws1)
        await mgr.connect(ws2)
        with patch.object(mgr, "_send_safe", new_callable=AsyncMock) as mock_send:
            await mgr.broadcast("test")
            assert mock_send.call_count == 2


# =====================================================================
# WebSocketManager — close_all
# =====================================================================


class TestWebSocketManagerCloseAll:
    """关闭所有连接测试。"""

    @pytest.mark.asyncio
    async def test_close_all_clears_connections(self):
        mgr = WebSocketManager()
        ws1, ws2 = AsyncMock(), AsyncMock()
        await mgr.connect(ws1)
        await mgr.connect(ws2)
        await mgr.close_all()
        assert len(mgr._connections) == 0

    @pytest.mark.asyncio
    async def test_close_all_calls_close(self):
        mgr = WebSocketManager()
        ws1, ws2 = AsyncMock(), AsyncMock()
        await mgr.connect(ws1)
        await mgr.connect(ws2)
        await mgr.close_all()
        ws1.close.assert_awaited_once_with(code=1001, reason="Server shutting down")
        ws2.close.assert_awaited_once_with(code=1001, reason="Server shutting down")

    @pytest.mark.asyncio
    async def test_close_all_handles_close_error(self):
        """单个连接关闭失败不应影响其他连接。"""
        mgr = WebSocketManager()
        ws_bad = AsyncMock()
        ws_bad.close.side_effect = RuntimeError("close failed")
        ws_good = AsyncMock()
        await mgr.connect(ws_bad)
        await mgr.connect(ws_good)
        await mgr.close_all()  # 不应抛异常
        ws_good.close.assert_awaited_once()
        assert len(mgr._connections) == 0

    @pytest.mark.asyncio
    async def test_close_all_empty(self):
        mgr = WebSocketManager()
        await mgr.close_all()  # 无连接时不抛异常


# =====================================================================
# WebSocketManager — 初始化
# =====================================================================


class TestWebSocketManagerInit:
    """初始化测试。"""

    def test_init_creates_empty_connections(self):
        mgr = WebSocketManager()
        assert mgr._connections == []
        assert isinstance(mgr._lock, asyncio.Lock)


# =====================================================================
# F16 — broadcast 总体超时
# =====================================================================


class TestBroadcastOverallTimeout:
    """F16: asyncio.gather 包裹 wait_for 5s 总体超时。"""

    @staticmethod
    def _make_stuck_ws():
        """创建一个 send_text 永远不会完成的 WebSocket mock。"""
        ws = AsyncMock()

        async def _stuck_send(*args, **kwargs):
            # 使用永远不会 resolve 的 Future，避免协程泄漏警告
            await asyncio.get_running_loop().create_future()

        ws.send_text = AsyncMock(side_effect=_stuck_send)
        return ws

    @pytest.mark.asyncio
    async def test_broadcast_overall_timeout_does_not_hang(self):
        """N 个连接全部卡住时，broadcast 应在 ~5s 内返回而非 N×5s。"""
        import time

        mgr = WebSocketManager()

        # 创建 3 个永远卡住的连接
        stuck_ws = []
        for _ in range(3):
            ws = self._make_stuck_ws()
            stuck_ws.append(ws)
            await mgr.connect(ws)

        start = time.monotonic()
        await mgr.broadcast("msg")
        elapsed = time.monotonic() - start

        # 应在 5s 超时内返回（留 1s 余量给调度）
        assert elapsed < 6.5, f"broadcast 耗时 {elapsed:.1f}s，预期 <6.5s"

    @pytest.mark.asyncio
    async def test_broadcast_timeout_returns_gracefully(self):
        """总体超时后不抛异常。"""
        mgr = WebSocketManager()
        ws = self._make_stuck_ws()
        await mgr.connect(ws)
        # 不应抛异常
        await mgr.broadcast("msg")

    @pytest.mark.asyncio
    async def test_broadcast_fast_path_unchanged(self):
        """正常快速广播行为不变。"""
        mgr = WebSocketManager()
        ws = AsyncMock()
        await mgr.connect(ws)
        await mgr.broadcast("hello")
        ws.send_text.assert_awaited_once_with("hello")


# =====================================================================
# zip strict=True 检测连接/队列长度不一致
# =====================================================================


class TestBroadcastStrictZip:
    """验证 broadcast 中 zip(strict=True) 能检测长度不一致。"""

    @pytest.mark.asyncio
    async def test_strict_zip_raises_on_length_mismatch(self):
        """connections 与 results 长度不一致时应抛出 ValueError。"""
        mgr = WebSocketManager()
        ws1, ws2 = AsyncMock(), AsyncMock()
        await mgr.connect(ws1)
        await mgr.connect(ws2)

        async def bad_wait_for(coro, timeout):
            # 让 gather 正常执行（消费掉 tasks），但返回长度不匹配的结果
            await coro
            return ["only_one"]  # 1 个结果，但 connections 有 2 个

        with (
            patch.object(asyncio, "wait_for", side_effect=bad_wait_for),
            pytest.raises(ValueError),
        ):
            await mgr.broadcast("msg")

    @pytest.mark.asyncio
    async def test_strict_zip_no_error_when_lengths_match(self):
        """connections 与 results 长度一致时不应抛出异常。"""
        mgr = WebSocketManager()
        ws1, ws2 = AsyncMock(), AsyncMock()
        await mgr.connect(ws1)
        await mgr.connect(ws2)

        async def correct_wait_for(coro, timeout):
            # 返回与 connections 等长的结果
            await coro
            return [None, None]

        with patch.object(asyncio, "wait_for", side_effect=correct_wait_for):
            # 不应抛出 ValueError
            await mgr.broadcast("msg")
