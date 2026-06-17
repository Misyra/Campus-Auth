"""统一 shell 命令执行的安全策略。

提供 ShellCommandPolicy 类，用于验证执行路径白名单、超时上限钳制、
执行前审计日志。TaskExecutor 和 ScriptRunner 共享此策略。
"""

from __future__ import annotations

import asyncio
import contextlib
import platform
import subprocess
import sys
from collections.abc import Callable

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
        audit_hook: Callable[[list[str], int], None] | None = None,
    ):
        """初始化策略。

        Args:
            allowlist: 允许的执行路径列表（绝对路径）
            default_timeout: 默认超时时间（秒），会被 clamp 到 [1, 3600]
            audit_hook: 可选的审计钩子，执行前调用 (argv, timeout)
        """
        # 统一转为小写路径比较（Windows 路径不区分大小写）
        self._allowlist = {
            p.lower() if sys.platform == "win32" else p for p in allowlist
        }
        self._default_timeout = self._clamp_timeout(default_timeout)
        self._audit_hook = audit_hook

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
        logger.info(
            "Shell 命令执行审计: argv=%s, timeout=%ds",
            argv[:5] if len(argv) > 5 else argv,
            timeout,
        )
        if self._audit_hook:
            try:
                self._audit_hook(argv, timeout)
            except Exception:
                logger.debug("审计钩子执行失败", exc_info=True)

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

    _ALLOWED_SUBPROCESS_KWARGS = {"env", "cwd", "creationflags"}

    async def run(
        self,
        argv: list[str],
        *,
        timeout: int | None = None,
        **kwargs,
    ) -> tuple[int, str, str]:
        """异步执行命令（用于 asyncio 场景）。

        Args:
            argv: 完整命令参数列表，第一个元素为执行路径
            timeout: 超时时间（秒），会被 clamp 到 [1, 3600]
            **kwargs: 传递给 asyncio.create_subprocess_exec 的额外参数（仅 env/cwd/creationflags）

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

        # 白名单过滤，防止 shell=True 等危险参数被透传
        safe_kwargs = {k: v for k, v in kwargs.items() if k in self._ALLOWED_SUBPROCESS_KWARGS}
        if platform.system() == "Windows":
            safe_kwargs.setdefault("creationflags", CREATE_NO_WINDOW_FLAG)

        try:
            proc = await asyncio.create_subprocess_exec(
                *argv,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                **safe_kwargs,
            )
        except FileNotFoundError:
            return -1, "", f"执行文件不存在: {executable}"

        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=effective_timeout
            )
        except TimeoutError:
            await self._kill_process_tree(proc)
            return -1, "", f"命令执行超时 ({effective_timeout}s)"

        stdout_str = stdout.decode("utf-8", errors="replace").strip() if stdout else ""
        stderr_str = stderr.decode("utf-8", errors="replace").strip() if stderr else ""

        return proc.returncode if proc.returncode is not None else -1, stdout_str, stderr_str

    async def _kill_process_tree(self, proc):
        """杀死进程及其所有子进程。"""
        try:
            import psutil
            parent = psutil.Process(proc.pid)
            for child in parent.children(recursive=True):
                with contextlib.suppress(psutil.NoSuchProcess, psutil.AccessDenied):
                    child.kill()
            parent.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess, ProcessLookupError):
            pass
        except Exception:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
        await proc.wait()

    def _kill_process_tree_sync(self, pid: int) -> None:
        """同步版进程树清理。"""
        try:
            import psutil
            parent = psutil.Process(pid)
            for child in parent.children(recursive=True):
                with contextlib.suppress(psutil.NoSuchProcess, psutil.AccessDenied):
                    child.kill()
            parent.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess, ProcessLookupError):
            pass

    def run_sync(
        self,
        argv: list[str],
        *,
        timeout: int | None = None,
        **kwargs,
    ) -> tuple[int, str, str]:
        """同步执行命令（用于 script_runner 的 subprocess.run 场景）。

        Args:
            argv: 完整命令参数列表，第一个元素为执行路径
            timeout: 超时时间（秒），会被 clamp 到 [1, 3600]
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
            stdout_str, stderr_str = proc.communicate(timeout=effective_timeout)
        except subprocess.TimeoutExpired:
            self._kill_process_tree_sync(proc.pid)
            return -1, "", f"命令执行超时 ({effective_timeout}s)"
        except FileNotFoundError:
            return -1, "", f"执行文件不存在: {executable}"

        return proc.returncode, stdout_str.strip(), stderr_str.strip()
