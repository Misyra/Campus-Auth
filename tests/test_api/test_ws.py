"""WebSocket 消息大小限制测试 — 验证按 UTF-8 字节计算。"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import WebSocketDisconnect

from app.api.ws import websocket_logs_handler


def _make_ws(messages: list[str]) -> MagicMock:
    """构造 mock WebSocket，按顺序返回指定消息，最后抛出 WebSocketDisconnect 终止循环。"""
    ws = MagicMock()
    ws.receive_text = AsyncMock(side_effect=[*messages, WebSocketDisconnect()])
    ws.send_text = AsyncMock()
    return ws


def _make_manager() -> MagicMock:
    """构造 mock WsManager。"""
    mgr = MagicMock()
    mgr.connect = AsyncMock()
    mgr.disconnect = AsyncMock()
    return mgr


class TestMessageSizeLimit:
    """WebSocket 消息大小按 UTF-8 字节计算。"""

    @pytest.mark.asyncio
    async def test_ascii_within_limit_processed_normally(self):
        """ASCII ping 消息在限制内，正常回复 pong。"""
        msg = json.dumps({"type": "ping"})
        ws = _make_ws([msg])
        mgr = _make_manager()

        await websocket_logs_handler(ws, mgr)

        # ping 正常处理并回复 pong
        ws.send_text.assert_called_once_with('{"type":"pong"}')

    @pytest.mark.asyncio
    async def test_ascii_exceeds_limit_disconnects_immediately(self):
        """ASCII 消息超过 65536 字节时立即断开，不处理消息内容。"""
        big_msg = "x" * 65537
        ws = _make_ws([big_msg])
        mgr = _make_manager()

        await websocket_logs_handler(ws, mgr)

        # 超限后立即断开，且未尝试回复任何内容
        mgr.disconnect.assert_called_once_with(ws)
        ws.send_text.assert_not_called()

    @pytest.mark.asyncio
    async def test_multibyte_within_char_limit_exceeds_byte_limit(self):
        """中文消息：字符数在限制内，但 UTF-8 字节数超出时应断开。

        3 字节/字符，22000 个中文字符 = 66000 字节 > 65536。
        """
        big_msg = "中" * 22000
        ws = _make_ws([big_msg])
        mgr = _make_manager()

        await websocket_logs_handler(ws, mgr)

        # 字节数超限，立即断开
        mgr.disconnect.assert_called_once_with(ws)
        ws.send_text.assert_not_called()

    @pytest.mark.asyncio
    async def test_multibyte_within_byte_limit_not_disconnected(self):
        """中文消息：字节数在限制内，走正常 JSON 解析流程。"""
        # 20000 个中文字符 = 60000 字节 < 65536
        msg = "中" * 20000
        ws = _make_ws([msg])
        mgr = _make_manager()

        await websocket_logs_handler(ws, mgr)

        # 消息在字节限制内，正常进入 JSON 解析（虽然不是合法 JSON）
        # 不会因大小超限而提前断开
        ws.send_text.assert_not_called()

    @pytest.mark.asyncio
    async def test_exact_boundary_65536_bytes_not_disconnected(self):
        """恰好 65536 字节的消息正常处理。"""
        msg = json.dumps({"type": "ping"})
        # 替换为恰好 65536 字节的 ASCII 字符串
        msg = "a" * 65536
        ws = _make_ws([msg])
        mgr = _make_manager()

        await websocket_logs_handler(ws, mgr)

        # 65536 字节不超限，走正常解析流程（JSONDecodeError 分支）
        ws.send_text.assert_not_called()

    @pytest.mark.asyncio
    async def test_exact_boundary_65537_bytes_disconnected(self):
        """恰好 65537 字节的消息立即断开。"""
        msg = "a" * 65537
        ws = _make_ws([msg])
        mgr = _make_manager()

        await websocket_logs_handler(ws, mgr)

        mgr.disconnect.assert_called_once_with(ws)
        ws.send_text.assert_not_called()
