"""日志系统 — 基于 loguru 的统一日志配置。

提供：
- get_logger(name, source) — 获取绑定 name 和 source 的 logger
- LogConfigCenter — 单例配置中心，支持运行时热更新日志级别
- DashboardSink — 自定义 sink，维护内存环形缓冲区 + WebSocket 广播队列
"""

from __future__ import annotations

import contextlib
import logging
import os
import sys
import threading
from collections import deque
from datetime import datetime
from collections.abc import Callable
from typing import Any

from loguru import logger

from app.constants import LOG_BUFFER_MAXLEN, STATUS_LOG_MAXLEN

# 移除 loguru 默认的 stderr handler
logger.remove()

# ==================== 格式定义 ====================


def _console_format(record):
    source = record["extra"].get("source", "-")
    record["extra"]["_source"] = source
    return (
        "<green>[{time:HH:mm:ss}]</green>"
        "<level>[{level}]</level>"
        "<cyan>[{extra[_source]}]</cyan>"
        "<cyan>[{name}]</cyan> "
        "<level>{message}</level>\n"
    )


def _file_format(record):
    source = record["extra"].get("source", "-")
    record["extra"]["_source"] = source
    return "[{time:YYYY-MM-DD HH:mm:ss}][{level}][{extra[_source]}][{name}] {message}\n"


# 默认添加控制台 handler
logger.add(
    sys.stdout,
    format=_console_format,
    level="DEBUG",
    colorize=True,
)

# ==================== 标准 logging 桥接 ====================


# 为了让 pytest caplog 等标准 logging 工具能捕获 loguru 的日志，
# 添加一个 sink 将日志转发到标准 logging。
def _to_std_logging(message):
    """将 loguru 消息转发到标准 logging。"""
    record = message.record
    name = record["extra"].get("name", record["name"])
    level = record["level"].name

    # 映射 loguru 级别到标准 logging 级别
    level_map = {
        "DEBUG": logging.DEBUG,
        "INFO": logging.INFO,
        "WARNING": logging.WARNING,
        "ERROR": logging.ERROR,
        "CRITICAL": logging.CRITICAL,
    }
    std_level = level_map.get(level, logging.INFO)

    # 获取标准 logging logger
    std_logger = logging.getLogger(name)
    std_logger.log(std_level, str(message).strip())


# 添加标准 logging 桥接 sink
logger.add(_to_std_logging, level="DEBUG", format="{message}")

# ==================== 日志级别标准化 ====================

VALID_LOG_LEVELS = frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})


def normalize_level(level: str | None, default: str = "INFO") -> str:
    """标准化日志级别名称，无效值返回 default。"""
    raw = str(level or default).upper().strip()
    return raw if raw in VALID_LOG_LEVELS else default


# ==================== 核心接口 ====================

VALID_SOURCES = frozenset({"backend", "network", "task", "frontend", "debug"})


def get_logger(name: str, source: str = "backend") -> logger:
    """获取绑定 name 和 source 的 logger。

    返回的 logger 支持直接调用 .info()、.warning() 等方法。
    source 可选值: backend, network, task, frontend, debug
    非法 source 值自动降级为 "backend"。
    """
    if source not in VALID_SOURCES:
        source = "backend"
    return logger.bind(name=name, source=source)


# ==================== 自定义 sink: Dashboard（内存 + 广播）====================


class DashboardSink:
    """loguru sink — 维护内存环形缓冲区 + WebSocket 广播队列。

    替代原 LogBroadcastSink（仅广播）+ MonitorService._logs（仅内存）的双路径。
    """

    _MAX_MSG_LEN = 2000  # 消息截断上限，防止单条日志携带大量 traceback
    _MAX_SRC_LEN = 64  # source 字段防异常膨胀

    def __init__(self, maxlen: int = LOG_BUFFER_MAXLEN, broadcast_maxlen: int = STATUS_LOG_MAXLEN):
        self.buffer: deque[dict] = deque(maxlen=maxlen)
        self.broadcast_queue: deque[dict] = deque(maxlen=broadcast_maxlen)
        self._lock = threading.Lock()
        self._drain_notifier: Callable[[], None] | None = None
        # 获取配置中心实例
        self._config_center = LogConfigCenter.get_instance()

    def set_drain_notifier(self, notifier: Callable[[], None]) -> None:
        """设置 drain 通知器（由 WebSocketManager 注入）。"""
        self._drain_notifier = notifier

    def write(self, message) -> None:
        """loguru sink 接口 — 接收格式化后的消息。"""
        record = message.record
        name = record["extra"].get("name", record["name"])
        source = str(record["extra"].get("source", "backend"))[: self._MAX_SRC_LEN]
        level = record["level"].name

        # 根据 source 级别过滤
        if not self._config_center.should_emit(source, level):
            return

        text = str(message).strip()[: self._MAX_MSG_LEN]

        stamp = datetime.fromtimestamp(record["time"].timestamp()).strftime(
            "%Y-%m-%d %H:%M:%S"
        )

        entry = {
            "timestamp": stamp,
            "level": level,
            "source": source,
            "name": name,
            "message": text,
        }

        with self._lock:
            self.buffer.append(entry)
            self.broadcast_queue.append(
                {
                    "type": "log",
                    "data": entry,
                }
            )
        if self._drain_notifier is not None:
            self._drain_notifier()

    def list_logs(self, limit: int = 200) -> list[dict]:
        """返回最近 limit 条日志（供 dashboard API 读取）。"""
        with self._lock:
            return list(self.buffer)[-limit:]


# ==================== 日志配置中心 ====================


class LogConfigCenter:
    """日志配置中心（单例模式）

    统一管理整个应用的日志配置，避免重复配置和配置不一致问题。
    """

    _instance = None
    _init_lock = threading.Lock()
    _LEVEL_ORDER = {"DEBUG": 0, "INFO": 1, "WARNING": 2, "ERROR": 3, "CRITICAL": 4}

    DEFAULT_CONFIG = {
        "level": "INFO",
    }

    def __new__(cls):
        if cls._instance is None:
            with cls._init_lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._config = self.DEFAULT_CONFIG.copy()
        self._source = "backend"
        self._configured = False
        self._initialized = True
        self._file_sink_id: int | None = None
        self._frontend_file_sink_id: int | None = None
        # source 级别配置（读写均需 _source_levels_lock 保护）
        self._source_levels: dict[str, str] = {}
        self._source_levels_lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> LogConfigCenter:
        if cls._instance is None:
            cls()
        return cls._instance

    def initialize(
        self, config: dict[str, Any] | None = None, source: str = "backend"
    ) -> None:
        """初始化日志配置（仅首次调用有效）"""
        with self._init_lock:
            if self._configured:
                return

            if config:
                self._config.update(config)
            self._source = source

            # 设置全局日志级别
            level = normalize_level(self._config.get("level", "INFO"))
            logger.level(level)

            self._configured = True

    def set_level(self, level: str) -> None:
        """动态修改全局日志级别（热更新）。

        影响控制台输出和标准 logging 桥接的最低级别。
        文件 sink 始终记录 DEBUG 及以上（由 filter 控制 side）。
        """
        normalized = normalize_level(level)
        logger.level(normalized)
        with self._source_levels_lock:
            self._config["level"] = normalized

    def get_config(self) -> dict[str, Any]:
        return self._config.copy()

    def add_file_handler(self, log_dir: str, retention_days: int = 7) -> None:
        """添加按日期存储的日志 sink（loguru 原生轮转）"""
        # 移除旧的 sink
        if self._file_sink_id is not None:
            with contextlib.suppress(ValueError):
                logger.remove(self._file_sink_id)
            self._file_sink_id = None
        if self._frontend_file_sink_id is not None:
            with contextlib.suppress(ValueError):
                logger.remove(self._frontend_file_sink_id)
            self._frontend_file_sink_id = None

        try:
            os.makedirs(log_dir, exist_ok=True)

            # 后端日志 -> app.log
            backend_path = os.path.join(log_dir, "app.log")
            self._file_sink_id = logger.add(
                backend_path,
                rotation="00:00",
                retention=f"{retention_days} days",
                encoding="utf-8",
                format=_file_format,
                level="DEBUG",
                filter=lambda record: record["extra"].get("source") != "frontend",
            )

            # 前端日志 -> frontend.log
            frontend_path = os.path.join(log_dir, "frontend.log")
            self._frontend_file_sink_id = logger.add(
                frontend_path,
                rotation="00:00",
                retention=f"{retention_days} days",
                encoding="utf-8",
                format=_file_format,
                level="DEBUG",
                filter=lambda record: record["extra"].get("source") == "frontend",
            )

            logger.info("日志系统启动 | 目录: {} | 保留 {} 天", log_dir, retention_days)
        except Exception as e:
            logger.warning("无法启用文件日志 {}: {}", log_dir, e)

    # ==================== source 级别管理 ====================

    def set_source_level(self, source: str, level: str) -> None:
        """设置指定 source 的日志级别

        Args:
            source: 日志来源（backend/network/task/frontend/debug）
            level: 日志级别（DEBUG/INFO/WARNING/ERROR/CRITICAL）
        """
        if source not in VALID_SOURCES:
            raise ValueError(f"无效的 source: {source}，有效值: {VALID_SOURCES}")
        normalized = normalize_level(level)
        with self._source_levels_lock:
            self._source_levels[source] = normalized

    def get_source_level(self, source: str) -> str:
        """获取指定 source 的日志级别

        如果未设置，返回全局级别
        """
        with self._source_levels_lock:
            return self._source_levels.get(source, self._config.get("level", "INFO"))

    def should_emit(self, source: str, level: str) -> bool:
        """判断是否应该输出日志

        Args:
            source: 日志来源
            level: 日志级别
        Returns:
            True 表示应该输出，False 表示应该过滤
        """
        source_level = self.get_source_level(source)
        return self._LEVEL_ORDER.get(level, 0) >= self._LEVEL_ORDER.get(source_level, 0)

    def get_all_source_levels(self) -> dict[str, str]:
        """获取所有 source 级别配置"""
        with self._source_levels_lock:
            return self._source_levels.copy()
