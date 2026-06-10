"""进程管理工具 — PID 文件管理 + 进程检测。

从 main.py 提取，提供跨平台的进程管理功能。
"""

from __future__ import annotations

import os
import socket
import sys
import time
from pathlib import Path

import psutil

from app.constants import AUTH_DATA_DIR

__all__ = [
    "cleanup_pid",
    "get_pid_file",
    "get_process_name",
    "is_local_port_in_use",
    "is_service_running",
    "normalize_proc_name",
    "read_pid_file",
    "read_pid_mode",
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
        return psutil.Process(pid).name()
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
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
    # 轻量模式下不监听端口，跳过端口检查
    mode = read_pid_mode()
    if mode != "lightweight":
        from app.utils.ports import resolve_port

        port = resolve_port()
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


def write_pid(mode: str | None = None) -> None:
    """写入当前进程的 PID 文件。

    Args:
        mode: 运行模式标记，如 "lightweight" 或 "full"。存入 PID 文件第三行。
    """
    pid_file = get_pid_file()
    proc_name = os.path.basename(sys.executable)
    start_time = time.strftime("%Y-%m-%d %H:%M:%S")
    content = f"{os.getpid()}\n{proc_name}|{start_time}"
    if mode:
        content += f"\n{mode}"
    # 原子写入: 临时文件 + 重命名
    tmp = pid_file.with_suffix(".pid.tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(pid_file)


def cleanup_pid() -> None:
    """清理 PID 文件。"""
    get_pid_file().unlink(missing_ok=True)


def read_pid_mode() -> str | None:
    """读取 PID 文件中记录的运行模式。返回模式字符串或 None。"""
    pid_file = get_pid_file()
    if not pid_file.exists():
        return None
    try:
        lines = pid_file.read_text(encoding="utf-8").strip().splitlines()
        if len(lines) >= 3:
            mode = lines[2].strip()
            return mode or None
        return None
    except (OSError, IndexError):
        return None
