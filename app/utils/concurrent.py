"""可中断的异步等待工具。"""

from __future__ import annotations

import asyncio
import threading
import time


async def interruptible_sleep(
    seconds: float,
    cancel_event: threading.Event,
    *,
    poll_interval: float = 0.2,
) -> bool:
    """可中断的异步等待。

    用于 LoginSession 重试间隔、未来 Engine / Scheduler / NetworkMonitor 等
    需要可中断等待的场景。

    Args:
        seconds: 等待秒数。≤ 0 时立即返回 True。
        cancel_event: 取消事件，set 后立即返回 False。
        poll_interval: 轮询间隔（秒），决定取消响应延迟上界。默认 0.2s。

    Returns:
        True 表示等待完成；False 表示被 cancel_event 中断。

    Notes:
        - 与 CompositeCancelEvent.wait(timeout) 区别：wait 是同步阻塞，
          需 asyncio.to_thread 包装；本函数是纯异步，行为更直观。
        - CompositeCancelEvent 继承 threading.Event，is_set() 兼容，可直接传入。
    """
    if seconds <= 0:
        return True

    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if cancel_event.is_set():
            return False
        await asyncio.sleep(poll_interval)
    return True
