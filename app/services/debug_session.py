"""调试会话状态数据模型。

使用 dataclass 替代原有的 plain-dict 模式，提供:
- DebugSession 数据类
- 工厂函数和序列化器
- 模块级代数计数器（所有会话共享）
"""

from __future__ import annotations

import asyncio
import itertools
import threading
from collections import deque
from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# 模块级代数计数器（所有调试会话共享，线程安全）
# ---------------------------------------------------------------------------

_debug_gen = itertools.count(1)
_current_gen: int = 0
_gen_lock = threading.Lock()


def _next_debug_gen() -> int:
    """返回下一个代数编号（线程安全，使用锁保护全局状态）。"""
    global _current_gen
    with _gen_lock:
        _current_gen = next(_debug_gen)
        return _current_gen


# ---------------------------------------------------------------------------
# DebugSession dataclass — mirrors the 10 mutable fields of the old _debug dict
# ---------------------------------------------------------------------------


@dataclass
class DebugSession:
    """Typed representation of a debug session's runtime state.

    Fields correspond 1:1 to the ``_debug`` dict keys in ``backend/main.py``,
    except ``_debug_gen`` which is kept as a standalone module-level counter
    so that stale generation checks work correctly across session boundaries.
    """

    _browser_active: bool = False
    """Whether the debug browser session is active."""

    task_id: str | None = None
    """The task identifier being debugged."""

    executor: Any = None
    """The TaskExecutor instance driving step execution."""

    current_step: int = 0
    """Index of the next step to execute."""

    steps: list = field(default_factory=list)
    """List of step-info dicts (index, id, type, description)."""

    results: deque = field(default_factory=lambda: deque(maxlen=1000))
    """Step execution results, capped at 1000 entries."""

    screenshot_url: str | None = None
    """URL of the latest debug screenshot, or None."""

    running: bool = False
    """Whether the debug session is currently active."""

    _last_activity: float = 0.0
    """Monotonic timestamp of the last user activity."""

    _timer_task: asyncio.Task | None = None
    """The asyncio timeout-watcher task, or None."""


# ---------------------------------------------------------------------------
# Serializer
# ---------------------------------------------------------------------------


def debug_to_response(session: DebugSession) -> dict:
    """Serialize a ``DebugSession`` to the response dict used by debug API
    endpoints.

    This function mirrors the structure of ``_debug_response()`` in
    ``backend/main.py`` — it strips out internal-only fields (executor,
    _last_activity, _timer_task) and converts the ``results`` deque to a
    plain list so the response is JSON-safe.
    """
    return {
        "running": session.running,
        "task_id": session.task_id,
        "current_step": session.current_step,
        "total_steps": len(session.steps),
        "steps": session.steps,
        "results": list(session.results),
        "screenshot_url": session.screenshot_url,
    }
