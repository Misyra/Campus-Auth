"""退出工具函数 — 强制退出。

force_exit: 执行 atexit 钩子后强制退出，用于无法优雅关闭的场景。
"""

from __future__ import annotations

import atexit
import contextlib
import os


def force_exit(code: int = 0) -> None:
    """强制退出 — 确保 atexit 钩子执行后退出。

    用于无信号处理器或必须立即退出的场景：
    - 轻量模式 finally 块（daemon 线程阻止自然退出）
    - uvicorn 未就绪时的早期退出
    - 完整模式 finally 块（补强清理）

    使用 contextlib.suppress 包裹 atexit 调用，即使钩子抛异常，
    os._exit 仍会执行，防止进程挂起。
    """
    with contextlib.suppress(Exception):
        atexit._run_exitfuncs()
    os._exit(code)
