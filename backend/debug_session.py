"""Debug session state as a typed dataclass.

Replaces the plain-dict pattern for _debug in backend/main.py with
a proper DebugSession dataclass, factory function, and serializer.

The module-level _debug_gen counter remains standalone (shared across
sessions) rather than being a dataclass field.
"""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Module-level generation counter (shared across all debug sessions)
# ---------------------------------------------------------------------------

_debug_gen: int = 0


def _next_debug_gen() -> int:
    """Return the next generation number and increment the counter."""
    global _debug_gen
    _debug_gen += 1
    return _debug_gen


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

    session: Any = None
    """The DebugSession browser instance or None."""

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
# Factory
# ---------------------------------------------------------------------------


def empty_debug_session() -> DebugSession:
    """Return a fresh ``DebugSession`` with all default values."""
    return DebugSession()


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
