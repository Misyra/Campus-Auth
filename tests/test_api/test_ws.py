"""WebSocket 消息大小限制与 frontend_log 测试。"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import WebSocketDisconnect

from app.api.ws import _fe_logger, websocket_logs_handler, ws_logger


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


class TestFrontendLog:
    """frontend_log 消息处理测试 — 验证模块级 logger 复用。"""

    def test_module_level_logger_is_singleton(self):
        """模块级 _fe_logger 是单例实例，不会每次调用重新创建。"""
        from app.api.ws import _fe_logger as logger1
        from app.api.ws import _fe_logger as logger2

        assert logger1 is logger2

    @pytest.mark.asyncio
    async def test_frontend_log_with_default_level(self):
        """frontend_log 消息默认使用 INFO 级别。"""
        msg = json.dumps({
            "type": "frontend_log",
            "data": {"message": "test log", "scope": "test"},
        })
        ws = _make_ws([msg])
        mgr = _make_manager()

        with patch.object(_fe_logger, "info") as mock_info:
            await websocket_logs_handler(ws, mgr)
            mock_info.assert_called_once_with("[{}] {}", "test", "test log")

    @pytest.mark.asyncio
    async def test_frontend_log_with_explicit_level(self):
        """frontend_log 消息使用指定的日志级别。"""
        msg = json.dumps({
            "type": "frontend_log",
            "data": {"message": "warning msg", "scope": "auth", "level": "WARNING"},
        })
        ws = _make_ws([msg])
        mgr = _make_manager()

        with patch.object(_fe_logger, "warning") as mock_warning:
            await websocket_logs_handler(ws, mgr)
            mock_warning.assert_called_once_with("[{}] {}", "auth", "warning msg")

    @pytest.mark.asyncio
    async def test_frontend_log_with_invalid_level_falls_back_to_info(self):
        """frontend_log 消息使用无效级别时降级为 INFO。"""
        msg = json.dumps({
            "type": "frontend_log",
            "data": {"message": "msg", "scope": "s", "level": "INVALID"},
        })
        ws = _make_ws([msg])
        mgr = _make_manager()

        with patch.object(_fe_logger, "info") as mock_info:
            await websocket_logs_handler(ws, mgr)
            mock_info.assert_called_once()

    @pytest.mark.asyncio
    async def test_frontend_log_empty_message_not_logged(self):
        """frontend_log 空消息不触发日志调用。"""
        msg = json.dumps({
            "type": "frontend_log",
            "data": {"message": "", "scope": "test"},
        })
        ws = _make_ws([msg])
        mgr = _make_manager()

        with patch.object(_fe_logger, "info") as mock_info:
            await websocket_logs_handler(ws, mgr)
            mock_info.assert_not_called()

    @pytest.mark.asyncio
    async def test_frontend_log_missing_data_not_logged(self):
        """frontend_log 缺少 data 字段时不触发日志调用。"""
        msg = json.dumps({"type": "frontend_log"})
        ws = _make_ws([msg])
        mgr = _make_manager()

        with patch.object(_fe_logger, "info") as mock_info:
            await websocket_logs_handler(ws, mgr)
            mock_info.assert_not_called()

    @pytest.mark.asyncio
    async def test_frontend_log_message_truncated_to_10000(self):
        """frontend_log 消息超过 10000 字符时被截断。"""
        long_msg = "x" * 15000
        msg = json.dumps({
            "type": "frontend_log",
            "data": {"message": long_msg, "scope": "test"},
        })
        ws = _make_ws([msg])
        mgr = _make_manager()

        with patch.object(_fe_logger, "info") as mock_info:
            await websocket_logs_handler(ws, mgr)
            call_args = mock_info.call_args
            # 消息被截断为 10000 字符
            assert len(call_args[0][2]) == 10000

    @pytest.mark.asyncio
    async def test_frontend_log_scope_truncated_to_200(self):
        """frontend_log scope 超过 200 字符时被截断。"""
        long_scope = "y" * 300
        msg = json.dumps({
            "type": "frontend_log",
            "data": {"message": "test", "scope": long_scope},
        })
        ws = _make_ws([msg])
        mgr = _make_manager()

        with patch.object(_fe_logger, "info") as mock_info:
            await websocket_logs_handler(ws, mgr)
            call_args = mock_info.call_args
            # scope 被截断为 200 字符
            assert len(call_args[0][1]) == 200


class TestUnknownMessageType:
    """未知 WebSocket 消息类型记录警告日志。"""

    @pytest.mark.asyncio
    async def test_unknown_type_logs_warning(self):
        """未知消息类型触发 warning 日志。"""
        msg = json.dumps({"type": "unknown_type"})
        ws = _make_ws([msg])
        mgr = _make_manager()

        with patch.object(ws_logger, "warning") as mock_warning:
            await websocket_logs_handler(ws, mgr)
            mock_warning.assert_called_once_with(
                "收到未知 WebSocket 消息类型: {}", "unknown_type"
            )

    @pytest.mark.asyncio
    async def test_none_type_logs_warning(self):
        """type 为 null 时记录警告。"""
        msg = json.dumps({"type": None})
        ws = _make_ws([msg])
        mgr = _make_manager()

        with patch.object(ws_logger, "warning") as mock_warning:
            await websocket_logs_handler(ws, mgr)
            mock_warning.assert_called_once_with(
                "收到未知 WebSocket 消息类型: {}", None
            )

    @pytest.mark.asyncio
    async def test_missing_type_logs_warning(self):
        """缺少 type 字段时记录警告。"""
        msg = json.dumps({"data": "something"})
        ws = _make_ws([msg])
        mgr = _make_manager()

        with patch.object(ws_logger, "warning") as mock_warning:
            await websocket_logs_handler(ws, mgr)
            mock_warning.assert_called_once_with(
                "收到未知 WebSocket 消息类型: {}", None
            )

    @pytest.mark.asyncio
    async def test_known_types_do_not_log_warning(self):
        """已知消息类型不触发未知类型警告。"""
        ping_msg = json.dumps({"type": "ping"})
        log_msg = json.dumps({
            "type": "frontend_log",
            "data": {"message": "test", "scope": "s"},
        })
        ws = _make_ws([ping_msg, log_msg])
        mgr = _make_manager()

        with patch.object(ws_logger, "warning") as mock_warning:
            await websocket_logs_handler(ws, mgr)
            # warning 不应被调用（ping 和 frontend_log 是已知类型）
            mock_warning.assert_not_called()
