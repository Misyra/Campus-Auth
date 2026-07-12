"""统一 shell 命令执行的安全策略。

提供 ShellCommandPolicy 类，用于验证执行路径白名单、超时上限钳制、
执行前审计日志。TaskExecutor 和 ScriptRunner 共享此策略。
"""

from __future__ import annotations

import contextlib
import platform
import subprocess
import sys
import threading
import time

import psutil

from .logging import get_logger
from .platform import CREATE_NO_WINDOW_FLAG

logger = get_logger("shell_policy", source="backend")

# 超时上下限
_MIN_TIMEOUT = 1
_MAX_TIMEOUT = 3600


class ShellCommandPolicy:
    """统一 shell 命令执行的安全策略:
    - 执行路径白名单（从外部传入的 allowlist 验证）
    - timeout 上限 clamp（1, 3600）
    - 执行前 audit log
    """

    def __init__(
        self,
        allowlist: list[str],
        default_timeout: int = 60,
    ):
        """初始化策略。

        Args:
            allowlist: 允许的执行路径列表（绝对路径）
            default_timeout: 默认超时时间（秒），会被 clamp 到 [1, 3600]
        """
        # 统一转为小写路径比较（Windows 路径不区分大小写）
        self._allowlist = {
            p.lower() if sys.platform == "win32" else p for p in allowlist
        }
        self._default_timeout = self._clamp_timeout(default_timeout)

    @staticmethod
    def _clamp_timeout(timeout: int) -> int:
        """将超时限制在 [1, 3600] 范围内。"""
        return max(_MIN_TIMEOUT, min(timeout, _MAX_TIMEOUT))

    def _is_allowed(self, path: str) -> bool:
        """检查路径是否在白名单中。"""
        normalized = path.lower() if sys.platform == "win32" else path
        return normalized in self._allowlist

    def _audit(self, argv: list[str], timeout: int) -> None:
        """执行审计日志。"""
        logger.debug(
            "Shell 命令执行审计: argv={}, timeout={}s",
            argv[:5] if len(argv) > 5 else argv,
            timeout,
        )

    def validate_and_prepare(
        self,
        executable: str,
        timeout: int | None = None,
    ) -> tuple[bool, int, str]:
        """验证并准备执行参数。

        Args:
            executable: 要验证的执行路径
            timeout: 超时时间（None 则使用默认值）

        Returns:
            (是否合法, 处理后的超时, 错误信息（合法时为空字符串）)
        """
        if not self._is_allowed(executable):
            return False, 0, f"执行路径不在白名单中: {executable}"

        effective_timeout = self._clamp_timeout(
            timeout if timeout is not None else self._default_timeout
        )
        return True, effective_timeout, ""

    def _kill_process_tree_sync(self, pid: int) -> None:
        """同步版进程树清理。"""
        try:
            parent = psutil.Process(pid)
            for child in parent.children(recursive=True):
                with contextlib.suppress(psutil.NoSuchProcess, psutil.AccessDenied):
                    child.kill()
            parent.kill()
        except (
            psutil.NoSuchProcess,
            psutil.AccessDenied,
            psutil.ZombieProcess,
            ProcessLookupError,
        ):
            pass

    def run_sync(
        self,
        argv: list[str],
        *,
        timeout: int | None = None,
        cancel_event: threading.Event | None = None,
        **kwargs,
    ) -> tuple[int, str, str]:
        """同步执行命令（用于 script_runner 的 subprocess.run 场景）。

        Args:
            argv: 完整命令参数列表，第一个元素为执行路径
            timeout: 超时时间（秒），会被 clamp 到 [1, 3600]
            cancel_event: 可选的取消事件，设置后终止子进程
            **kwargs: 传递给 subprocess.run 的额外参数

        Returns:
            (returncode, stdout_str, stderr_str)

        Raises:
            PermissionError: 执行路径不在白名单中
        """
        if not argv:
            raise ValueError("命令参数列表不能为空")

        executable = argv[0]
        ok, effective_timeout, err = self.validate_and_prepare(executable, timeout)
        if not ok:
            raise PermissionError(err)

        self._audit(argv, effective_timeout)

        popen_kwargs = {
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "text": True,
            "encoding": "utf-8",
            "errors": "replace",
        }
        if platform.system() == "Windows":
            popen_kwargs["creationflags"] = CREATE_NO_WINDOW_FLAG
        # 只允许白名单中的额外参数，防止安全策略被绕过
        _ALLOWED_KWARGS = {"env", "cwd"}
        for key in _ALLOWED_KWARGS:
            if key in kwargs:
                popen_kwargs[key] = kwargs[key]

        try:
            proc = subprocess.Popen(argv, **popen_kwargs)
        except FileNotFoundError:
            return -1, "", f"执行文件不存在: {executable}"

        if cancel_event is not None:
            # 轮询模式：定期检查取消事件
            deadline = time.monotonic() + effective_timeout
            while proc.poll() is None:
                if cancel_event.is_set():
                    self._kill_process_tree_sync(proc.pid)
                    with contextlib.suppress(subprocess.TimeoutExpired):
                        proc.wait(timeout=5)
                    return -1, "", "任务已被取消"
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self._kill_process_tree_sync(proc.pid)
                    with contextlib.suppress(subprocess.TimeoutExpired):
                        proc.wait(timeout=5)
                    return -1, "", f"命令执行超时 ({effective_timeout}s)"
                time.sleep(min(0.3, remaining))
            stdout_str, stderr_str = proc.communicate()
        else:
            try:
                stdout_str, stderr_str = proc.communicate(timeout=effective_timeout)
            except subprocess.TimeoutExpired:
                self._kill_process_tree_sync(proc.pid)
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self._kill_process_tree_sync(proc.pid)
                    logger.warning("终止进程失败: kill 后仍未退出 (pid={})", proc.pid)
                return -1, "", f"命令执行超时 ({effective_timeout}s)"

        return proc.returncode, stdout_str.strip(), stderr_str.strip()
