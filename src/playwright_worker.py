"""
Playwright Worker — Actor 模型浏览器自动化工作线程

架构说明:
  PlaywrightWorker 采用与 MonitorService 相同的 Actor 模型:
    - 外部调用者通过 submit() 提交 WorkerCommand 到内部队列
    - 消费者守护线程从队列取出命令并执行
    - submit() 支持同步等待（通过 response_event）
    - 所有 Playwright 操作限制在工作线程内，避免跨线程竞争

  此模块当前为骨架阶段，后续逐步实现具体操作逻辑。
"""

from __future__ import annotations

import logging
import queue
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from typing import Any


logger = logging.getLogger(__name__)


# ── 命令类型常量 ──

CMD_LOGIN = "login"  # 执行完整登录流程
CMD_DEBUG_START = "debug_start"  # 启动调试会话
CMD_DEBUG_STEP = "debug_step"  # 调试下一步
CMD_DEBUG_STOP = "debug_stop"  # 停止调试会话
CMD_BROWSER_HEALTH_CHECK = "browser_health_check"  # 浏览器健康检查
CMD_SHUTDOWN = "shutdown"  # 关闭 Worker


# ── 数据结构 ──


@dataclass
class WorkerCommand:
    """从 API/服务线程提交到 Worker 线程的命令单元。"""

    type: str  # 命令类型，对应 CMD_* 常量
    data: dict = field(default_factory=dict)  # 命令参数
    response_event: threading.Event | None = None  # 调用方等待此事件以获取结果
    response_data: Any = None  # 消费者线程设置返回数据


@dataclass
class WorkerResponse:
    """Worker 命令执行结果。"""

    success: bool
    data: Any = None
    error: str | None = None


# ── Worker 类 ──


class PlaywrightWorker:
    """浏览器自动化工作线程。

    通过 Actor 模型的消息队列，将 Playwright 操作隔离在独立线程中执行。
    外部模块通过 submit() 提交任务，可选择同步等待执行结果。
    """

    def __init__(self) -> None:
        self._cmd_queue: queue.Queue[WorkerCommand] = queue.Queue(maxsize=50)
        self._stop_event = threading.Event()
        self._consumer_thread: threading.Thread | None = None

    def start(self) -> None:
        """启动消费者守护线程。"""
        # TODO: 启动 daemon 消费者线程，从 _cmd_queue 取命令执行
        raise NotImplementedError

    def stop(self) -> None:
        """发送关闭信号并等待线程结束。"""
        # TODO: 设置 _stop_event，向队列放入 CMD_SHUTDOWN，等待线程退出
        raise NotImplementedError

    def submit(
        self,
        cmd_type: str,
        data: dict | None = None,
        wait: bool = True,
        timeout: float | None = None,
    ) -> WorkerResponse:
        """提交命令到 Worker 队列。

        参数:
            cmd_type: 命令类型（CMD_* 常量）
            data: 命令参数
            wait: 是否同步等待执行结果
            timeout: 等待超时秒数（None 表示无限制）

        返回:
            WorkerResponse 对象
        """
        # TODO: 创建 WorkerCommand，放入队列，等待 response_event 后返回结果
        raise NotImplementedError


# ── 模块级单例 ──

_worker: PlaywrightWorker | None = None
"""模块级全局 Worker 实例，首次调用 get_worker() 时创建。"""


def get_worker() -> PlaywrightWorker:
    """获取全局 PlaywrightWorker 单例。

    首次调用时创建实例并自动 start()。
    后续调用返回已有实例。
    """
    global _worker  # noqa: PLW0603
    if _worker is None:
        _worker = PlaywrightWorker()
        _worker.start()
    return _worker


# ── 孤儿浏览器清理 ──


def cleanup_orphan_browsers() -> None:
    """清理孤儿 Chromium 浏览器进程

    扫描并杀掉由 Campus-Auth 启动但已失去 Python 父进程的 Chromium 实例。
    仅清理 Playwright 管理的浏览器（可执行路径包含 "ms-playwright"），
    不会误杀用户自行安装的 Chrome/Edge/Brave 等浏览器。

    平台差异:
    - Windows: 使用 wmic 枚举进程, taskkill 终止
    - Linux/macOS: 使用 ps 枚举进程, kill 终止
    """
    if sys.platform == "win32":
        _cleanup_windows()
    else:
        _cleanup_posix()


def _cleanup_windows() -> None:
    """Windows 平台: 通过 wmic 查找并终止 Playwright Chromium 进程"""
    try:
        # 使用 wmic 获取所有 chrome.exe 的 PID 和执行路径
        result = subprocess.run(
            [
                "wmic",
                "process",
                "where",
                "name='chrome.exe'",
                "get",
                "processid,executablepath",
                "/format:csv",
            ],
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW
            if hasattr(subprocess, "CREATE_NO_WINDOW")
            else 0,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return

        pids_to_kill: list[str] = []
        for line in result.stdout.strip().splitlines()[1:]:  # 跳过 CSV 表头
            line = line.strip()
            if not line:
                continue
            # CSV 格式: Node,ExecutablePath,ProcessId
            parts = line.split(",")
            if len(parts) < 3:
                continue
            exe_path = parts[1].strip().strip('"') if len(parts) > 1 else ""
            pid_str = parts[2].strip().strip('"') if len(parts) > 2 else ""
            # 仅匹配 Playwright 管理的 Chromium（路径包含 ms-playwright）
            if "ms-playwright" in exe_path.lower() and pid_str.isdigit():
                pids_to_kill.append(pid_str)

        if not pids_to_kill:
            logger.debug("未发现孤儿 Playwright Chromium 进程")
            return

        logger.info("发现 %d 个孤儿 Playwright Chromium 进程，正在清理...", len(pids_to_kill))
        for pid in pids_to_kill:
            try:
                subprocess.run(
                    ["taskkill", "/F", "/PID", pid],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    creationflags=subprocess.CREATE_NO_WINDOW
                    if hasattr(subprocess, "CREATE_NO_WINDOW")
                    else 0,
                )
                logger.debug("已终止 Chromium 进程 PID=%s", pid)
            except Exception:
                logger.warning("终止 Chromium 进程 PID=%s 失败", pid)
    except Exception:
        logger.warning("扫描孤儿 Chromium 进程时出现异常", exc_info=True)


def _cleanup_posix() -> None:
    """Linux/macOS 平台: 通过 ps 查找并终止 Playwright Chromium 进程"""
    try:
        result = subprocess.run(
            ["ps", "-eo", "pid=,args="],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return

        pids_to_kill: list[str] = []
        for line in result.stdout.strip().splitlines():
            line = line.strip()
            if not line:
                continue
            # 格式: "PID ARGS"
            parts = line.split(None, 1)
            if len(parts) < 2:
                continue
            pid_str, args = parts[0], parts[1]
            # 仅匹配 Playwright 管理的 Chromium（路径包含 ms-playwright）
            if "ms-playwright" in args.lower() and "chrom" in args.lower():
                pids_to_kill.append(pid_str)

        if not pids_to_kill:
            logger.debug("未发现孤儿 Playwright Chromium 进程")
            return

        logger.info("发现 %d 个孤儿 Playwright Chromium 进程，正在清理...", len(pids_to_kill))
        for pid in pids_to_kill:
            try:
                subprocess.run(
                    ["kill", "-9", pid],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                logger.debug("已终止 Chromium 进程 PID=%s", pid)
            except Exception:
                logger.warning("终止 Chromium 进程 PID=%s 失败", pid)
    except Exception:
        logger.warning("扫描孤儿 Chromium 进程时出现异常", exc_info=True)
