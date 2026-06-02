"""脚本任务执行器 — 在子进程中执行 Python 脚本登录任务。"""

from __future__ import annotations

import os
import platform
import subprocess
import sys
import time
from pathlib import Path

from src.utils.logging import get_logger

logger = get_logger("script_runner", side="BACKEND")

# 默认脚本超时（秒）
DEFAULT_TIMEOUT = 60


class ScriptRunner:
    """执行 Python 脚本任务。

    脚本自行硬编码账号密码等参数，通过 stdout 输出信息。
    成功与否由网络检测判断，脚本只需发请求。
    """

    def __init__(self, script_path: Path, timeout: int = DEFAULT_TIMEOUT):
        self.script_path = script_path
        self.timeout = timeout

    def run(self) -> tuple[bool, str]:
        """执行脚本并返回 (执行是否成功, 输出信息)。

        注意：这里的 success 表示脚本是否正常执行完毕（exit code 0），
        不代表登录是否成功。登录成功与否由调用方通过网络检测判断。
        """
        start = time.perf_counter()
        env = _build_minimal_env()

        try:
            result = subprocess.run(
                [sys.executable, str(self.script_path)],
                capture_output=True,
                text=True,
                timeout=self.timeout,
                env=env,
                cwd=str(self.script_path.parent),
                encoding="utf-8",
                errors="replace",
            )
        except subprocess.TimeoutExpired:
            logger.error("脚本执行超时 (%ds): %s", self.timeout, self.script_path)
            return False, f"脚本执行超时 ({self.timeout}s)"
        except Exception as e:
            elapsed = time.perf_counter() - start
            logger.error("脚本执行异常 (%.1fs): %s", elapsed, e)
            return False, f"脚本执行异常: {e}"

        elapsed = time.perf_counter() - start

        if result.stderr.strip():
            logger.info("脚本 stderr: %s", result.stderr.strip()[:500])

        output = result.stdout.strip()[:500] or f"(无输出, exit code {result.returncode})"

        if result.returncode == 0:
            logger.info("脚本执行完成 (%.1fs): %s", elapsed, output)
            return True, output
        else:
            logger.warning("脚本执行失败 (%.1fs, exit %d): %s", elapsed, result.returncode, output)
            return False, output


def _build_minimal_env() -> dict[str, str]:
    """构建子进程最小环境变量（仅系统基础变量）。"""
    safe: dict[str, str] = {}
    base_keys = {"PATH", "HOME", "USER", "TEMP", "TMP"}
    if platform.system() == "Windows":
        base_keys.update({"SystemRoot", "ComSpec", "windir"})
    else:
        base_keys.update({"LANG", "LC_ALL", "SHELL", "XDG_RUNTIME_DIR"})
    for key in base_keys:
        val = os.environ.get(key)
        if val:
            safe[key] = val
    safe["PYTHONIOENCODING"] = "utf-8"
    return safe
