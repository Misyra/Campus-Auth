"""进程管理工具 — PID 文件管理 + 进程检测。

从 main.py 提取，提供跨平台的进程管理功能。
"""

from __future__ import annotations

import json
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
    "verify_process_identity",
    "write_pid",
]


def get_pid_file() -> Path:
    """获取 PID 文件路径。"""
    return AUTH_DATA_DIR / "campus_network_auth.pid"


def read_pid_file() -> dict | None:
    """读取 PID 文件。返回解析后的字典或 None。

    返回格式：
    {
        "pid": int,
        "create_time": float,  # psutil.Process.create_time()
        "mode": str | None,
        "proc_name": str
    }
    """
    pid_file = get_pid_file()
    if not pid_file.exists():
        return None
    try:
        text = pid_file.read_text(encoding="utf-8").strip()
        if not text:
            return None

        data = json.loads(text)
        pid = data.get("pid")
        if not isinstance(pid, int) or pid <= 0:
            return None
        return data
    except (json.JSONDecodeError, ValueError, OSError):
        return None


def get_process_name(pid: int) -> str | None:
    """获取指定 PID 的进程名。"""
    try:
        return psutil.Process(pid).name()
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return None


def get_process_create_time(pid: int) -> float | None:
    """获取指定 PID 的创建时间。返回时间戳或 None。"""
    try:
        return psutil.Process(pid).create_time()
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return None


def normalize_proc_name(name: str) -> str:
    """标准化进程名（小写 + 移除 .exe 后缀）。"""
    return name.lower().removesuffix(".exe")


def verify_process_identity(pid: int, stored_create_time: float | None = None) -> bool:
    """验证进程身份。检查 PID 是否存活且 create_time 匹配。

    Args:
        pid: 进程 PID
        stored_create_time: PID 文件中记录的创建时间

    Returns:
        True 如果进程存活且身份匹配
    """
    proc_name = get_process_name(pid)
    if proc_name is None:
        return False

    if stored_create_time is not None:
        actual_create_time = get_process_create_time(pid)
        if actual_create_time is None:
            return False
        # 允许 1 秒误差
        if abs(actual_create_time - stored_create_time) > 1.0:
            return False

    return True


def is_service_running() -> tuple[bool, int | None]:
    """检查服务是否正在运行。返回 (running, pid)。"""
    pid_file = get_pid_file()
    if not pid_file.exists():
        return False, None

    data = read_pid_file()
    if data is None:
        pid_file.unlink(missing_ok=True)
        return False, None

    pid = data["pid"]

    # 验证进程身份（PID + create_time）
    if not verify_process_identity(pid, data.get("create_time")):
        pid_file.unlink(missing_ok=True)
        return False, None

    # 完整模式下进一步验证端口是否在监听
    mode = data.get("mode")
    if mode != "lightweight":
        from app.utils.ports import resolve_port

        port = resolve_port()
        if not is_local_port_in_use(port):
            # 宽限期：进程刚启动时端口可能还未就绪
            create_time = data.get("create_time")
            if create_time and (time.time() - create_time) < 30:
                return True, pid  # 刚启动，跳过端口检查
            # 进程存在但未监听端口 → 不是本应用实例，清理残留 PID 文件
            pid_file.unlink(missing_ok=True)
            return False, None

    return True, pid


def is_local_port_in_use(port: int) -> bool:
    """检查本地端口是否被占用。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.4)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def write_pid(mode: str | None = None) -> None:
    """写入当前进程的 PID 文件（JSON 格式）。"""
    from app.utils.files import atomic_write

    AUTH_DATA_DIR.mkdir(exist_ok=True)
    pid_file = get_pid_file()

    data = {
        "pid": os.getpid(),
        "create_time": psutil.Process().create_time(),
        "proc_name": os.path.basename(sys.executable),
        "mode": mode,
    }
    atomic_write(pid_file, json.dumps(data, ensure_ascii=False))


def cleanup_pid() -> None:
    """清理 PID 文件。"""
    get_pid_file().unlink(missing_ok=True)


def read_pid_mode() -> str | None:
    """读取 PID 文件中记录的运行模式。返回模式字符串或 None。"""
    data = read_pid_file()
    if data is None:
        return None
    return data.get("mode") or None
