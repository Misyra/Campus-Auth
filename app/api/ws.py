"""WebSocket 处理 — 从 application.py 提取。"""

from __future__ import annotations

import json

from app.utils.logging import get_logger

ws_logger = get_logger("ws", source="backend")


async def websocket_logs_handler(websocket, ws_manager, engine):
    """WebSocket /ws/logs 处理逻辑。"""
    from fastapi import WebSocketDisconnect

    await ws_manager.connect(websocket)
    try:
        while True:
            raw = await websocket.receive_text()
            # WebSocket 消息大小预检，防止超大消息导致内存问题
            if len(raw) > 65536:
                ws_logger.warning(
                    "WebSocket 消息过大 ({} bytes)，断开连接", len(raw)
                )
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
                        engine.record_log(
                            message=f"[{scope}] {message_text}",
                            level=str(d.get("level", "INFO"))[:20],
                            source="frontend",
                        )
            except json.JSONDecodeError:
                ws_logger.debug("WebSocket 消息解析失败", exc_info=True)
            except Exception:
                ws_logger.debug("WebSocket 消息处理异常", exc_info=True)
    except WebSocketDisconnect:
        await ws_manager.disconnect(websocket)
    except Exception:
        ws_logger.exception("WebSocket 通信异常")
        await ws_manager.disconnect(websocket)
