"""退出工具函数 — 区分优雅退出与强制退出。

提供两个退出策略：
- request_graceful_exit: 发送 SIGTERM，让信号处理器执行优雅关闭
- force_exit: 执行 atexit 钩子后强制退出，用于无法优雅关闭的场景
"""

from __future__ import annotations

import atexit
import contextlib
import os
import signal


def request_graceful_exit(code: int = 0) -> None:
    """请求优雅退出 — 发送 SIGTERM 触发信号处理器。

    仅在信号处理器已注册的上下文中使用（如 _run_full 模式）。
    Windows 上 SIGTERM 可用但行为不同，此函数仍安全调用。
    """
    if hasattr(signal, "SIGTERM"):
        os.kill(os.getpid(), signal.SIGTERM)
    else:
        # 无 SIGTERM 支持的平台，回退到强制退出
        force_exit(code)


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
