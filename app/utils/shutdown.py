"""退出工具函数 — 强制退出。

force_exit: 执行 atexit 钩子后强制退出，用于无法优雅关闭的场景。
"""

from __future__ import annotations

import atexit
import contextlib
import os
import sys
import threading


def _is_test_environment() -> bool:
    """检测当前是否运行在测试环境中。"""
    return "pytest" in sys.modules


def force_exit(code: int = 0) -> None:
    """强制退出 — 确保 atexit 钩子执行后退出。

    用于无信号处理器或必须立即退出的场景：
    - 轻量模式 finally 块（daemon 线程阻止自然退出）
    - uvicorn 未就绪时的早期退出
    - 完整模式 finally 块（补强清理）

    测试环境下改用 sys.exit，避免 os._exit 杀死 pytest 宿主进程。
    生产环境下使用看门狗定时器防止 atexit 钩子阻塞，
    suppress(BaseException) 确保钩子抛出任何异常时 os._exit 仍会执行。
    """
    if _is_test_environment():
        sys.exit(code)

    # 看门狗：5 秒后强制退出，防止 atexit 钩子阻塞导致进程挂起
    watchdog = threading.Timer(5.0, os._exit, args=(code,))
    watchdog.daemon = True
    watchdog.start()
    try:
        with contextlib.suppress(BaseException):
            atexit._run_exitfuncs()
    finally:
        watchdog.cancel()
    os._exit(code)
