"""脚本任务执行器 — 在子进程中执行 Python 脚本登录任务。"""

from __future__ import annotations

import os
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

    脚本通过环境变量接收登录参数，通过 stdout 输出信息。
    成功与否由网络检测判断，脚本只需发请求。

    环境变量：
        CAMPUS_USERNAME — 用户名
        CAMPUS_PASSWORD — 密码
        CAMPUS_ISP      — 运营商（可为空）
        CAMPUS_URL      — 认证地址
    """

    def __init__(self, script_path: Path, timeout: int = DEFAULT_TIMEOUT):
        self.script_path = script_path
        self.timeout = timeout

    def run(self, env_vars: dict[str, str]) -> tuple[bool, str]:
        """执行脚本并返回 (执行是否成功, 输出信息)。

        注意：这里的 success 表示脚本是否正常执行完毕（exit code 0），
        不代表登录是否成功。登录成功与否由调用方通过网络检测判断。
        """
        start = time.perf_counter()

        safe_env = self._build_safe_env(env_vars)

        try:
            result = subprocess.run(
                [sys.executable, str(self.script_path)],
                capture_output=True,
                text=True,
                timeout=self.timeout,
                env=safe_env,
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

        # 记录 stderr（调试用）
        if result.stderr.strip():
            logger.info("脚本 stderr: %s", result.stderr.strip()[:500])

        # 取 stdout 作为输出信息
        output = result.stdout.strip()[:500] or f"(无输出, exit code {result.returncode})"

        if result.returncode == 0:
            logger.info("脚本执行完成 (%.1fs): %s", elapsed, output)
            return True, output
        else:
            logger.warning("脚本执行失败 (%.1fs, exit %d): %s", elapsed, result.returncode, output)
            return False, output

    @staticmethod
    def _build_safe_env(env_vars: dict[str, str]) -> dict[str, str]:
        """构建子进程安全环境变量。"""
        import platform
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
        # 始终传递，即使为空（脚本用 os.environ.get 安全访问）
        safe["CAMPUS_USERNAME"] = env_vars.get("USERNAME", "")
        safe["CAMPUS_PASSWORD"] = env_vars.get("PASSWORD", "")
        safe["CAMPUS_ISP"] = env_vars.get("ISP", "")
        safe["CAMPUS_URL"] = env_vars.get("LOGIN_URL", "")
        safe["PYTHONIOENCODING"] = "utf-8"
        return safe
