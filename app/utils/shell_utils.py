"""Shell 和解释器检测工具 — 供 scheduler 和 script_runner 共用。"""

from __future__ import annotations

import os
import shutil
import sys


def detect_shells() -> list[dict[str, str]]:
    """检测系统可用的 Shell。

    返回格式: [{"name": "bash", "path": "/bin/bash", "description": "Bourne Again Shell"}, ...]
    """
    shells: list[dict[str, str]] = []

    if sys.platform == "win32":
        candidates = [
            ("cmd", "cmd.exe", "Windows 命令提示符"),
            ("powershell", "powershell.exe", "Windows PowerShell"),
            ("pwsh", "pwsh.exe", "PowerShell 7+"),
            ("git-bash", "bash.exe", "Git Bash"),
        ]
    else:
        candidates = [
            ("bash", "bash", "Bourne Again Shell"),
            ("sh", "sh", "POSIX Shell"),
            ("zsh", "zsh", "Z Shell"),
            ("fish", "fish", "Friendly Interactive Shell"),
        ]

    for name, exe, desc in candidates:
        path = shutil.which(exe)
        if path:
            shells.append({"name": name, "path": path, "description": desc})

    return shells


def detect_binaries() -> list[dict[str, str]]:
    """检测系统常用的执行二进制（Shell + Python 解释器）。"""
    binaries: list[dict[str, str]] = []

    # Python（当前运行的解释器）
    if sys.executable:
        binaries.append(
            {
                "name": "Python",
                "path": sys.executable,
                "description": "当前 Python 解释器",
            }
        )

    # Shell
    binaries.extend(detect_shells())

    return binaries


def get_default_shell() -> str:
    """获取默认 Shell 路径。"""
    if sys.platform == "win32":
        pwsh = shutil.which("pwsh.exe")
        if pwsh:
            return pwsh
        powershell = shutil.which("powershell.exe")
        if powershell:
            return powershell
        return "cmd.exe"
    else:
        return os.environ.get("SHELL", "/bin/bash")
