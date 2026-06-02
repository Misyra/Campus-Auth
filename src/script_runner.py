"""自定义脚本执行器 — 在子进程中执行脚本任务。"""

from __future__ import annotations

import os
import platform
import subprocess
import sys
import time
from pathlib import Path

from src.utils.logging import get_logger
from src.utils.shell_policy import ShellCommandPolicy

logger = get_logger("script_runner", side="BACKEND")

# 默认脚本超时（秒）
DEFAULT_TIMEOUT = 60


def _escape_ps_single_quote(s: str) -> str:
    """转义 PowerShell 单引号字符串中的单引号（' → ''）。

    PowerShell 单引号字符串规则：内部单引号用两个连续单引号转义。
    """
    return s.replace("'", "''")


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
    支持 .py 文件和 JSON 格式（包含 content 字段）。
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
        self._script_content: str | None = None

    def _load_script_content(self) -> str | None:
        """从 JSON 文件加载脚本内容。"""
        if self._script_content is not None:
            return self._script_content

        if self.script_path.suffix.lower() == ".json":
            try:
                import json
                data = json.loads(self.script_path.read_text(encoding="utf-8"))
                self._script_content = data.get("content", "")
                return self._script_content
            except Exception as e:
                logger.error("无法读取脚本 JSON %s: %s", self.script_path, e)
                return None
        # .py 文件直接返回 None，由 _build_cmd 处理
        return None

    def _build_cmd(self) -> list[str]:
        """构建执行命令。"""
        script = str(self.script_path)
        binary = self.binary_path.lower()

        # JSON 格式脚本：从 content 字段读取命令内容
        content = self._load_script_content()
        if content is not None:
            if platform.system() == "Windows":
                if "powershell" in binary or "pwsh" in binary:
                    return [self.binary_path, "-NoProfile", "-WindowStyle", "Hidden", "-Command", content]
                elif "cmd" in binary:
                    return [self.binary_path, "/c", content]
            else:
                shell_names = ["bash", "sh", "zsh", "fish"]
                if any(shell in binary for shell in shell_names):
                    return [self.binary_path, "-c", content]
            # Python 或其他解释器：用 -c 执行内容
            return [self.binary_path, "-c", content]

        # .py 或其他文件：按原逻辑处理
        if platform.system() == "Windows":
            if "powershell" in binary or "pwsh" in binary:
                return [self.binary_path, "-NoProfile", "-WindowStyle", "Hidden", "-Command", f"& '{_escape_ps_single_quote(script)}'"]
            elif "cmd" in binary:
                return [self.binary_path, "/c", script]
        else:
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

        # 使用 ShellCommandPolicy 进行安全校验和执行
        available = [b["path"] for b in detect_available_binaries()]
        policy = ShellCommandPolicy(allowlist=available)

        # Windows 下隐藏窗口
        kwargs: dict = {
            "cwd": str(self.script_path.parent),
        }
        if platform.system() == "Windows":
            kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
        else:
            kwargs["env"] = env

        try:
            returncode, stdout_str, stderr_str = policy.run_sync(
                cmd, timeout=self.timeout, **kwargs,
            )
        except PermissionError as e:
            logger.error("脚本执行被拒绝: %s", e)
            return False, str(e)

        elapsed = time.perf_counter() - start

        if stderr_str:
            logger.info("脚本 stderr: %s", stderr_str[:500])

        output = stdout_str[:500] or f"(无输出, exit code {returncode})"

        if returncode == 0:
            logger.info("脚本执行完成 (%.1fs): %s", elapsed, output)
            return True, output
        else:
            logger.warning("脚本执行失败 (%.1fs, exit %d): %s", elapsed, returncode, output)
            return False, output


def _build_minimal_env() -> dict[str, str]:
    """构建子进程最小环境变量（仅系统基础变量）。"""
    safe: dict[str, str] = {}
    base_keys = {"PATH", "HOME", "USER", "TEMP", "TMP"}
    if platform.system() == "Windows":
        base_keys.update({"SystemRoot", "ComSpec", "windir", "USERPROFILE", "APPDATA", "LOCALAPPDATA"})
    else:
        base_keys.update({"LANG", "LC_ALL", "SHELL", "XDG_RUNTIME_DIR"})
    for key in base_keys:
        val = os.environ.get(key)
        if val:
            safe[key] = val
    safe["PYTHONIOENCODING"] = "utf-8"
    return safe
