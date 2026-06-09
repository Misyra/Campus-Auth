"""日志系统 — 基于 loguru 的统一日志配置。

提供：
- get_logger(name, side) — 获取绑定 name 和 side 的 logger
- LogConfigCenter — 单例配置中心，支持运行时热更新日志级别
- WebSocketSink — 自定义 sink，将日志推送到前端 WebSocket
- DateRotatingSink — 自定义 sink，按日期目录存储日志
"""

from __future__ import annotations

import contextlib
import logging
import os
import re
import shutil
import sys
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any

from loguru import logger

# 移除 loguru 默认的 stderr handler
logger.remove()

# ==================== 格式定义 ====================


def _console_format(record):
    side = record["extra"].get("side", "-")
    record["extra"]["_side"] = side
    return (
        "<green>{time:HH:mm:ss}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{extra[_side]}</cyan> | "
        "<cyan>{name}</cyan> | "
        "<level>{message}</level>\n"
    )


def _file_format(record):
    side = record["extra"].get("side", "-")
    record["extra"]["_side"] = side
    return "{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {extra[_side]} | {name} | {message}\n"


_WEBSOCKET_FORMAT = "{name} | {message}"

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
_std_handler_added = False


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

VALID_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}


def normalize_level(level: str | None, default: str = "INFO") -> str:
    """标准化日志级别名称，无效值返回 default。"""
    raw = str(level or default).upper().strip()
    return raw if raw in VALID_LOG_LEVELS else default


# ==================== 核心接口 ====================


def get_logger(name: str, side: str = "BACKEND") -> logger:
    """获取绑定 name 和 side 的 logger。

    返回的 logger 支持直接调用 .info()、.warning() 等方法。
    """
    return logger.bind(name=name, side=side)


# ==================== 自定义 sink: WebSocket ====================


class WebSocketSink:
    """将日志推送到 WebSocket 广播队列和 log_store。"""

    # 不转发这些 logger 的日志，避免回声或与 _push_log 重复
    _EXCLUDED_LOGGERS = frozenset(
        {
            "backend.ws_manager",
            "backend.monitor_service",
        }
    )

    _LogEntry: type | None = None  # 延迟初始化，避免循环导入

    def __init__(self, broadcast_queue: deque[dict], log_store: deque | None = None):
        self._queue = broadcast_queue
        self._log_store = log_store

    def write(self, message):
        """loguru sink 接口 — 接收格式化后的消息。"""
        record = message.record
        name = record["extra"].get("name", record["name"])

        # 过滤排除的 logger
        if name in self._EXCLUDED_LOGGERS:
            return

        side = record["extra"].get("side", "BACKEND")
        level = record["level"].name
        text = message.strip()

        stamp = datetime.fromtimestamp(record["time"].timestamp()).strftime(
            "%Y-%m-%d %H:%M:%S"
        )

        log_data = {
            "timestamp": stamp,
            "level": level,
            "source": f"{side}.{name}",
            "message": text,
        }

        self._queue.append({"type": "log", "data": log_data})

        if self._log_store is not None:
            if WebSocketSink._LogEntry is None:
                from app.schemas import LogEntry

                WebSocketSink._LogEntry = LogEntry
            self._log_store.append(WebSocketSink._LogEntry(**log_data))


# ==================== 自定义 sink: 按日期目录存储 ====================


class DateRotatingSink:
    """按日期自动切换的日志 sink — 当前日志写入 {log_dir}/YYYY-MM-DD/app.log。

    功能：
    - 按日期自动创建子目录
    - 文件超过大小上限时轮转（app.log → app.log.1 → app.log.2 ...）
    - 定期清理超过保留天数的日期目录
    """

    def __init__(
        self,
        log_dir: str,
        retention_days: int = 7,
        file_max_bytes: int = 5 * 1024 * 1024,
        file_backup_count: int = 3,
    ):
        self._log_dir = log_dir
        self._retention = retention_days
        self._current_date: str | None = None
        self._last_cleanup: float = 0
        self._stream = None
        self._emit_lock = threading.Lock()
        self._file_max_bytes = file_max_bytes
        self._file_backup_count = file_backup_count
        self._bytes_written: int = 0

    def _get_log_path(self) -> tuple[str, str]:
        """返回 (日期目录路径, 日志文件路径)"""
        date_str = datetime.now().strftime("%Y-%m-%d")
        date_dir = os.path.join(self._log_dir, date_str)
        return date_dir, os.path.join(date_dir, "app.log")

    def _open_file(self, path: str) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        # 先打开新流，成功后再关闭旧流，避免 open() 失败时丢失日志流
        new_stream = open(path, "a", encoding="utf-8")
        if self._stream:
            try:
                self._stream.close()
            except Exception:
                import sys

                print("[logging] 关闭旧日志流失败", file=sys.stderr)
        self._stream = new_stream
        self._bytes_written = 0
        if os.path.exists(path):
            self._bytes_written = os.path.getsize(path)

    def write(self, message):
        """loguru sink 接口 — 接收格式化后的消息。"""
        with self._emit_lock:
            try:
                today = datetime.now().strftime("%Y-%m-%d")
                if today != self._current_date or self._stream is None:
                    if today != self._current_date:
                        self._current_date = today
                    _, path = self._get_log_path()
                    self._open_file(path)

                # 每小时运行一次过期日期目录清理
                now = time.time()
                if now - self._last_cleanup > 3600:
                    self._last_cleanup = now
                    self._cleanup_old_dirs(now)

                if self._stream is not None:
                    text = str(message).rstrip("\n") + "\n"
                    self._stream.write(text)
                    self._stream.flush()
                    self._bytes_written += len(text.encode("utf-8"))
                    if self._bytes_written >= self._file_max_bytes:
                        self._rotate_file()
            except Exception as exc:
                # 不能用 logger — 本方法是 loguru sink，调用 logger 会触发自身导致无限递归
                print(f"[LOG ERROR] 写入日志文件失败: {exc}", file=sys.stderr)

    def _rotate_file(self) -> None:
        """当日志文件超过大小上限时，滚动备份并重新打开"""
        try:
            if self._stream:
                self._stream.close()
                self._stream = None

            _, path = self._get_log_path()

            # 从大到小遍历，将 app.log.N-1 -> app.log.N
            for i in range(self._file_backup_count - 1, 0, -1):
                src = f"{path}.{i}"
                dst = f"{path}.{i + 1}"
                if os.path.exists(src):
                    os.replace(src, dst)

            # 将 app.log -> app.log.1
            if os.path.exists(path):
                os.replace(path, f"{path}.1")

            self._stream = open(path, "a", encoding="utf-8")
            self._bytes_written = 0
        except Exception as exc:
            # 不能用 logger — 本方法由 write() 调用，同属 sink 内部，调用 logger 会无限递归
            print(f"[LOG ERROR] 日志轮转失败: {exc}", file=sys.stderr)

    def _cleanup_old_dirs(self, now: float) -> None:
        """清理超过保留天数的日期目录（含其中的 app.log 和 screenshots/）"""
        cutoff = now - self._retention * 86400
        base = Path(self._log_dir)
        if not base.exists():
            return
        for d in base.iterdir():
            if not d.is_dir() or not re.match(r"^\d{4}-\d{2}-\d{2}$", d.name):
                continue
            try:
                if d.stat().st_mtime < cutoff:
                    shutil.rmtree(d)
            except OSError as exc:
                # 不能用 logger — 本方法由 write() 调用，同属 sink 内部
                print(
                    f"[LOG ERROR] 清理过期日志目录失败: {d.name}: {exc}",
                    file=sys.stderr,
                )

    def close(self) -> None:
        """关闭文件流。"""
        with self._emit_lock:
            try:
                if self._stream:
                    self._stream.close()
                    self._stream = None
            except Exception:
                # 不能用 logger — 本方法由 write() 调用，同属 sink 内部，调用 logger 会无限递归
                import sys

                print("[logging] 关闭日志流失败", file=sys.stderr)


# ==================== 日志配置中心 ====================


class LogConfigCenter:
    """日志配置中心（单例模式）

    统一管理整个应用的日志配置，避免重复配置和配置不一致问题。
    """

    _instance = None
    _init_lock = threading.Lock()

    DEFAULT_CONFIG = {
        "level": "INFO",
        "file_max_bytes": 5 * 1024 * 1024,
        "file_backup_count": 3,
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
        self._side = "BACKEND"
        self._configured = False
        self._initialized = True
        self._file_sink_id: int | None = None

    @classmethod
    def get_instance(cls) -> LogConfigCenter:
        if cls._instance is None:
            cls()
        return cls._instance

    def initialize(
        self, config: dict[str, Any] | None = None, side: str = "BACKEND"
    ) -> None:
        """初始化日志配置（仅首次调用有效）"""
        with self._init_lock:
            if self._configured:
                return

            if config:
                self._config.update(config)
            self._side = side

            # 设置全局日志级别
            level = normalize_level(self._config.get("level", "INFO"))
            logger.level(level)

            self._configured = True

    def get_logger(self, name: str, side: str | None = None) -> logger:
        """获取配置好的日志器"""
        if not self._configured:
            self.initialize()
        return get_logger(name, side or self._side)

    def set_level(self, level: str) -> None:
        """动态修改全局日志级别（热更新）。

        影响控制台输出和标准 logging 桥接的最低级别。
        文件 sink 始终记录 DEBUG 及以上（由 filter 控制 side）。
        """
        normalized = normalize_level(level)
        logger.level(normalized)
        self._config["level"] = normalized

    def get_config(self) -> dict[str, Any]:
        return self._config.copy()

    def is_initialized(self) -> bool:
        return self._configured

    def add_file_handler(self, log_dir: str, retention_days: int = 7) -> None:
        """添加按日期存储的日志 sink（始终记录全部级别）"""
        # 如果已有文件 sink，先移除
        if self._file_sink_id is not None:
            with contextlib.suppress(ValueError):
                logger.remove(self._file_sink_id)
            self._file_sink_id = None

        try:
            file_sink = DateRotatingSink(
                log_dir=log_dir,
                retention_days=retention_days,
                file_max_bytes=self._config.get("file_max_bytes", 5 * 1024 * 1024),
                file_backup_count=self._config.get("file_backup_count", 3),
            )

            self._file_sink_id = logger.add(
                file_sink.write,
                format=_file_format,
                level="DEBUG",
                filter=lambda record: record["extra"].get("side") == "BACKEND",
            )

            logger.info("日志系统启动 | 目录: {} | 保留 {} 天", log_dir, retention_days)
        except Exception as e:
            logger.warning("无法启用文件日志 {}: {}", log_dir, e)
