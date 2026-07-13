"""WorkerPort — services 层与 workers 层之间的端口协议。

通过 Protocol 抽象 Worker 接口，services 层依赖此协议而非具体 PlaywrightWorker 实现，
消除 services ↔ workers 双向依赖。

services 层应从本模块导入：
- WorkerPort：协议类型（用于类型注解）
- WorkerResponse：Worker 命令响应数据类
- CMD_* 命令常量：替代从 app.workers.playwright_worker 直接导入
- get_worker / cleanup_orphan_browsers：工厂与清理函数

workers 层（PlaywrightWorker）通过实现此协议对外提供服务。
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

# ── 命令类型常量（services ↔ workers 契约单一来源）──
# 此处定义而非导入，Task 2.3 将让 playwright_worker.py 从本模块导入这些常量

CMD_LOGIN = "login"  # 执行完整登录流程
CMD_BROWSER = "browser"  # 通用浏览器任务（签到/打卡等，非登录）
CMD_DEBUG_START = "debug_start"  # 启动调试会话
CMD_DEBUG_STEP = "debug_step"  # 调试下一步
CMD_DEBUG_STOP = "debug_stop"  # 停止调试会话
CMD_SHUTDOWN = "shutdown"  # 关闭 Worker


# ── WorkerResponse（services ↔ workers 契约数据类）──


class WorkerResponse:
    """Worker 命令执行结果。

    注意：此处为契约定义，PlaywrightWorker 内部使用 @dataclass 定义同名类，
    字段结构兼容（success/data/error）。Task 2.3 将统一为引用此处定义。
    """

    success: bool
    data: Any
    error: str | None

    def __init__(
        self, success: bool, data: Any = None, error: str | None = None
    ) -> None:
        self.success = success
        self.data = data
        self.error = error


# ── WorkerPort 协议 ──


@runtime_checkable
class WorkerPort(Protocol):
    """Worker 端口协议 — services 层依赖此协议访问浏览器自动化 Worker。

    实现方：PlaywrightWorker（app/workers/playwright_worker.py）
    消费方：LoginOrchestrator、BrowserTaskService、DebugService 等
    """

    def start(self) -> None:
        """启动 Worker 消费者线程。"""
        ...

    def stop(self, timeout: float = 5) -> None:
        """停止 Worker 并等待线程结束。"""
        ...

    def is_alive(self) -> bool:
        """检查 Worker 消费者线程是否存活。"""
        ...

    def submit(
        self,
        cmd_type: str,
        data: dict | None = None,
        wait: bool = True,
        timeout: float | None = None,
    ) -> WorkerResponse:
        """提交命令到 Worker 队列并可选等待结果。

        Args:
            cmd_type: 命令类型（CMD_* 常量）
            data: 命令参数字典
            wait: 是否同步等待执行结果
            timeout: 等待超时秒数（None 表示无限制）

        Returns:
            WorkerResponse 对象
        """
        ...


# ── 工厂与清理函数（延迟导入委托给 playwright_worker）──
# services 层通过本模块导入，避免直接依赖 app.workers.playwright_worker


def get_worker() -> WorkerPort:
    """获取全局 Worker 实例（懒加载）。

    实际实现委托给 app.workers.playwright_worker.get_worker。
    """
    from app.workers.playwright_worker import get_worker as _get_worker

    return _get_worker()


def cleanup_orphan_browsers(*, force: bool = False) -> None:
    """清理残留的孤儿浏览器进程。

    实际实现委托给 app.workers.playwright_worker.cleanup_orphan_browsers。
    """
    from app.workers.playwright_worker import cleanup_orphan_browsers as _cleanup

    _cleanup(force=force)
