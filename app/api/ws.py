"""WebSocket 处理 — 从 application.py 提取。"""

from __future__ import annotations

import json

from app.utils.logging import get_logger

ws_logger = get_logger("ws", source="backend")
_fe_logger = get_logger("frontend", source="frontend")


async def websocket_logs_handler(websocket, ws_manager):
    """WebSocket /ws/logs 处理逻辑。"""
    from fastapi import WebSocketDisconnect

    await ws_manager.connect(websocket)
    try:
        while True:
            raw = await websocket.receive_text()
            # WebSocket 消息大小预检，按 UTF-8 字节长度计算，防止超大消息导致内存问题
            msg_bytes = len(raw.encode("utf-8"))
            if msg_bytes > 65536:
                ws_logger.warning("WebSocket 消息过大 ({} bytes)，断开连接", msg_bytes)
                await ws_manager.disconnect(websocket)
                return
            try:
                msg = json.loads(raw)
                msg_type = msg.get("type")
                if msg_type == "ping":
                    # 应用层 ping/pong，防止代理切断空闲连接
                    await websocket.send_text('{"type":"pong"}')
                elif msg_type == "frontend_log":
                    d = msg.get("data", {})
                    message_text = str(d.get("message", ""))[:10000]
                    scope = str(d.get("scope", "?"))[:200]
                    if message_text:
                        _ALLOWED_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
                        level_name = str(d.get("level", "INFO")).upper()
                        if level_name not in _ALLOWED_LEVELS:
                            level_name = "INFO"
                        log_func = getattr(
                            _fe_logger, level_name.lower(), _fe_logger.info
                        )
                        log_func("[{}] {}", scope, message_text)
                else:
                    ws_logger.warning("收到未知 WebSocket 消息类型: {}", msg_type)
            except json.JSONDecodeError as e:
                ws_logger.warning("WebSocket 消息解析失败: {}", e, exc_info=True)
            except Exception as e:
                ws_logger.exception("WebSocket 消息处理异常: {}", e)
    except WebSocketDisconnect:
        try:
            await ws_manager.disconnect(websocket)
        except Exception as e:
            ws_logger.warning("WebSocket 断开连接失败: {}", e, exc_info=True)
    except Exception as e:
        ws_logger.exception("WebSocket 通信异常: {}", e)
        try:
            await ws_manager.disconnect(websocket)
        except Exception:
            pass
