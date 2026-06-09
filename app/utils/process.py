"""进程管理工具 — PID 文件管理 + 进程检测。

从 main.py 提取，提供跨平台的进程管理功能。
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

from app.constants import AUTH_DATA_DIR

__all__ = [
    "cleanup_pid",
    "get_pid_file",
    "get_process_name",
    "is_local_port_in_use",
    "is_service_running",
    "normalize_proc_name",
    "read_pid_file",
    "write_pid",
]


def get_pid_file() -> Path:
    """获取 PID 文件路径。"""
    AUTH_DATA_DIR.mkdir(exist_ok=True)
    return AUTH_DATA_DIR / "campus_network_auth.pid"


def read_pid_file() -> tuple[int | None, str | None, str | None]:
    """读取 PID 文件。返回 (pid, process_name, create_time) 或 (None, None, None)。"""
    pid_file = get_pid_file()
    if not pid_file.exists():
        return None, None, None
    try:
        text = pid_file.read_text(encoding="utf-8").strip()
        if not text:
            return None, None, None
        lines = text.splitlines()
        pid = int(lines[0].strip())
        if pid <= 0:
            return None, None, None
        if len(lines) >= 2:
            parts = lines[1].split("|", 1)
            name = parts[0].strip() or None
            timestamp = (
                parts[1].strip() if len(parts) > 1 and parts[1].strip() else None
            )
            return pid, name, timestamp
        return pid, None, None
    except (ValueError, OSError):
        return None, None, None


def get_process_name(pid: int) -> str | None:
    """获取指定 PID 的进程名。"""
    try:
        if sys.platform == "win32":
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                capture_output=True,
                text=True,
                timeout=5,
                creationflags=subprocess.CREATE_NO_WINDOW
                if hasattr(subprocess, "CREATE_NO_WINDOW")
                else 0,
            )
            if result.returncode != 0 or not result.stdout.strip():
                return None
            # CSV: "image_name","pid","session_name","session#","mem_usage"
            # 注意：tasklist 在 PID 不存在时返回本地化的"无匹配进程"消息而非空输出，
            # 这也会被 CSV 解析。通过检查第二字段是否为数字区分。
            fields = result.stdout.strip().split(",")
            if len(fields) < 2 or not fields[1].strip('"').strip().isdigit():
                return None
            return fields[0].strip('"').strip() or None
        else:
            result = subprocess.run(
                ["ps", "-p", str(pid), "-o", "comm="],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode != 0 or not result.stdout.strip():
                return None
            return result.stdout.strip() or None
    except Exception:
        return None


def normalize_proc_name(name: str) -> str:
    """标准化进程名（小写 + 移除 .exe 后缀）。"""
    return name.lower().removesuffix(".exe")


def is_service_running() -> tuple[bool, int | None]:
    """检查服务是否正在运行。返回 (running, pid)。"""
    pid_file = get_pid_file()
    if not pid_file.exists():
        return False, None

    pid, proc_name, _ = read_pid_file()
    if pid is None:
        pid_file.unlink(missing_ok=True)
        return False, None

    proc_alive = get_process_name(pid)
    if proc_alive is None:
        # 进程不存在（tasklist/ps 查无此 PID）
        pid_file.unlink(missing_ok=True)
        return False, None

    if proc_name is not None and normalize_proc_name(proc_alive) != normalize_proc_name(
        proc_name
    ):
        # PID 存在但进程名不匹配（PID 已被回收重用）
        pid_file.unlink(missing_ok=True)
        return False, None

    # 进程名匹配，进一步验证端口是否在监听（防止 PID 被同名进程复用导致误判）
    from app.application import _resolve_port

    port = _resolve_port()
    if not is_local_port_in_use(port):
        # 进程存在但未监听端口 → 不是本应用实例，清理残留 PID 文件
        pid_file.unlink(missing_ok=True)
        return False, None

    try:
        os.kill(pid, 0)
    except (PermissionError, OSError, SystemError):
        # os.kill(pid,0) 在 Windows 下不可靠（跨会话/Integrity Level 探活会抛异常）
        # 但 get_process_name 已验证 PID 存在且进程名正确，保守视为存活
        pass
    except ProcessLookupError:
        pid_file.unlink(missing_ok=True)
        return False, None
    return True, pid


def is_local_port_in_use(port: int) -> bool:
    """检查本地端口是否被占用。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.4)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def write_pid() -> None:
    """写入当前进程的 PID 文件。"""
    pid_file = get_pid_file()
    proc_name = os.path.basename(sys.executable)
    start_time = time.strftime("%Y-%m-%d %H:%M:%S")
    content = f"{os.getpid()}\n{proc_name}|{start_time}"
    # 原子写入: 临时文件 + 重命名
    tmp = pid_file.with_suffix(".pid.tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(pid_file)


def cleanup_pid() -> None:
    """清理 PID 文件。"""
    get_pid_file().unlink(missing_ok=True)
