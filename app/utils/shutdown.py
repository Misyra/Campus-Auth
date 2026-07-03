"""退出工具函数 — 强制退出。

force_exit: 执行退出钩子后强制退出，用于无法优雅关闭的场景。
register_exit_handler: 注册退出钩子，在 force_exit 时执行。
"""

from __future__ import annotations

import contextlib
import os
import sys
import threading
from collections.abc import Callable
from typing import Any


# 手动维护的退出钩子列表，替代 atexit._run_exitfuncs() 私有 API
_exit_handlers: list[tuple[Callable[..., Any], tuple[Any, ...], dict[str, Any]]] = []


def register_exit_handler(
    func: Callable[..., Any], *args: Any, **kwargs: Any
) -> None:
    """注册退出钩子，在 force_exit 时按注册顺序执行。

    用于需要在 os._exit 前执行的清理逻辑（如关闭线程池、断开连接）。
    注意：此钩子仅在 force_exit 时执行，正常进程退出时不会触发。
    如需正常退出时也执行，请同时使用 atexit.register()。
    """
    _exit_handlers.append((func, args, kwargs))


def _is_test_environment() -> bool:
    """检测当前是否运行在测试环境中。"""
    return "pytest" in sys.modules


def _run_exit_handlers() -> None:
    """执行所有已注册的退出钩子，单个钩子异常不阻止后续钩子执行。"""
    for func, args, kwargs in _exit_handlers:
        with contextlib.suppress(BaseException):
            func(*args, **kwargs)


def force_exit(code: int = 0) -> None:
    """强制退出 — 确保退出钩子执行后退出。

    用于无信号处理器或必须立即退出的场景：
    - 轻量模式 finally 块（daemon 线程阻止自然退出）
    - uvicorn 未就绪时的早期退出
    - 完整模式 finally 块（补强清理）

    测试环境下改用 sys.exit，避免 os._exit 杀死 pytest 宿主进程。
    生产环境下使用看门狗定时器防止退出钩子阻塞，
    suppress(BaseException) 确保钩子抛出任何异常时 os._exit 仍会执行。
    """
    if _is_test_environment():
        sys.exit(code)

    # 看门狗：5 秒后强制退出，防止退出钩子阻塞导致进程挂起
    watchdog = threading.Timer(5.0, os._exit, args=(code,))
    watchdog.daemon = True
    watchdog.start()
    try:
        with contextlib.suppress(BaseException):
            _run_exit_handlers()
    finally:
        watchdog.cancel()
    os._exit(code)
