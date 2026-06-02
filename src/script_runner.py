"""自定义脚本执行器 — 在子进程中执行脚本任务。"""

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


def get_default_binary() -> str:
    """获取默认执行二进制（当前运行的 Python）。"""
    return sys.executable


def detect_available_binaries() -> list[dict[str, str]]:
    """检测系统常用的执行二进制。"""
    import shutil
    binaries = []

    # Python（当前运行的解释器）
    if sys.executable:
        binaries.append({"name": "Python", "path": sys.executable, "description": "当前 Python 解释器"})

    # Shell
    if platform.system() == "Windows":
        candidates = [
            ("cmd", "cmd.exe", "Windows 命令提示符"),
            ("powershell", "powershell.exe", "Windows PowerShell"),
            ("pwsh", "pwsh.exe", "PowerShell 7+"),
        ]
    else:
        candidates = [
            ("bash", "bash", "Bourne Again Shell"),
            ("sh", "sh", "POSIX Shell"),
            ("zsh", "zsh", "Z Shell"),
        ]

    for name, exe, desc in candidates:
        path = shutil.which(exe)
        if path:
            binaries.append({"name": name, "path": path, "description": desc})

    return binaries


class ScriptRunner:
    """执行自定义脚本任务。

    脚本自行硬编码账号密码等参数，通过 stdout 输出信息。
    成功与否由网络检测判断，脚本只需发请求。
    """

    def __init__(
        self,
        script_path: Path,
        timeout: int = DEFAULT_TIMEOUT,
        binary_path: str = "",
    ):
        self.script_path = script_path
        self.timeout = timeout
        self.binary_path = binary_path or get_default_binary()

    def _build_cmd(self) -> list[str]:
        """构建执行命令。"""
        script = str(self.script_path)
        binary = self.binary_path.lower()

        # Shell 类型使用 -c 参数
        if platform.system() == "Windows":
            if "powershell" in binary or "pwsh" in binary:
                return [self.binary_path, "-File", script]
            elif "cmd" in binary:
                return [self.binary_path, "/c", script]
        else:
            # Linux/macOS Shell
            shell_names = ["bash", "sh", "zsh", "fish"]
            if any(shell in binary for shell in shell_names):
                return [self.binary_path, script]

        # 默认：将脚本路径作为参数传递
        return [self.binary_path, script]

    def run(self) -> tuple[bool, str]:
        """执行脚本并返回 (执行是否成功, 输出信息)。

        注意：这里的 success 表示脚本是否正常执行完毕（exit code 0），
        不代表登录是否成功。登录成功与否由调用方通过网络检测判断。
        """
        if not self.binary_path:
            return False, "未指定执行二进制"

        start = time.perf_counter()
        env = _build_minimal_env()
        cmd = self._build_cmd()

        try:
            result = subprocess.run(
                cmd,
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
        except FileNotFoundError:
            logger.error("执行二进制不存在: %s", self.binary_path)
            return False, f"执行二进制不存在: {self.binary_path}"
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
