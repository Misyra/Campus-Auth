import logging
import logging.handlers
import os
import re
import shutil
import sys
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any, Dict


class ColoredFormatter(logging.Formatter):
    COLORS = {
        "DEBUG": "\033[36m",
        "INFO": "\033[32m",
        "WARNING": "\033[33m",
        "ERROR": "\033[31m",
        "CRITICAL": "\033[35m",
    }
    RESET = "\033[0m"

    def format(self, record):
        original_levelname = record.levelname
        log_color = self.COLORS.get(original_levelname, self.RESET)
        record.levelname = f"{log_color}{original_levelname}{self.RESET}"
        try:
            return super().format(record)
        finally:
            record.levelname = original_levelname


class SideFilter(logging.Filter):
    """为日志记录附加 side 属性（BACKEND / FRONTEND）"""

    def __init__(self, side: str):
        super().__init__()
        self.side = side

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "side"):
            record.side = self.side
        return True


_VALID_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}


def _normalize_level(level: str | None, default: str = "INFO") -> str:
    raw = str(level or default).upper().strip()
    return raw if raw in _VALID_LOG_LEVELS else default


def _level_value(level: str | None, default: str = "INFO") -> int:
    return getattr(logging, _normalize_level(level, default), logging.INFO)


def _formatter(pattern: str, colored: bool = False) -> logging.Formatter:
    if colored:
        return ColoredFormatter(pattern, datefmt="%H:%M:%S")
    return logging.Formatter(pattern, datefmt="%Y-%m-%d %H:%M:%S")


# 全局标记：根 logger 是否已完成首次配置
_root_configured = False
_root_configured_lock = threading.Lock()


def configure_root_logger(
    config: Dict[str, Any] | None = None, side: str = "BACKEND"
) -> logging.Logger:
    """配置根日志器。仅首次调用时完整配置，后续调用跳过以避免重复 handler。"""
    global _root_configured
    config = config or {}
    root = logging.getLogger()

    if _root_configured:
        return root

    with _root_configured_lock:
        if _root_configured:
            return root

        level = _level_value(config.get("level", "INFO"))
        pattern = str(
            config.get(
                "format",
                "%(asctime)s | %(levelname)s | %(side)s | %(name)s | %(message)s",
            )
        )
        root.setLevel(level)

        context_filter = SideFilter(side=side)

        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(level)
        console_handler.setFormatter(_formatter(pattern, colored=True))
        console_handler.addFilter(context_filter)
        root.addHandler(console_handler)

        # 压制第三方库的 DEBUG 日志，避免文件日志膨胀
        for noisy in ("httpcore", "httpx", "urllib3", "http.client"):
            logging.getLogger(noisy).setLevel(logging.WARNING)

        _root_configured = True
    return root


def _attach_side_filter(logger: logging.Logger, side: str) -> None:
    for filt in logger.filters:
        if isinstance(filt, SideFilter) and filt.side == side:
            return
    logger.addFilter(SideFilter(side))


def get_logger(name: str, side: str = "BACKEND") -> logging.Logger:
    logger = logging.getLogger(name)
    _attach_side_filter(logger, side)
    return logger


def setup_logger(name: str, config: Dict[str, Any] | None = None) -> logging.Logger:
    config = config or {}
    configure_root_logger(config, side="BACKEND")

    logger = get_logger(name, side="BACKEND")
    logger.handlers.clear()
    logger.propagate = True
    logger.setLevel(_level_value(config.get("level", "INFO")))
    return logger


class _DateRotatingFileHandler(logging.Handler):
    """按日期自动切换的日志处理器 — 当前日志写入 {log_dir}/YYYY-MM-DD/app.log"""

    def __init__(
        self,
        log_dir: str,
        retention_days: int = 7,
        level: int = logging.INFO,
        formatter: logging.Formatter | None = None,
        file_max_bytes: int = 5 * 1024 * 1024,
        file_backup_count: int = 3,
    ):
        super().__init__(level=level)
        self._log_dir = log_dir
        self._retention = retention_days
        self._current_date: str | None = None
        self._last_cleanup: float = 0
        self._stream = None
        self._emit_lock = threading.Lock()
        self._file_max_bytes = file_max_bytes
        self._file_backup_count = file_backup_count
        self._bytes_written: int = 0
        if formatter:
            self.setFormatter(formatter)

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
                pass
        self._stream = new_stream
        self._bytes_written = 0
        if os.path.exists(path):
            self._bytes_written = os.path.getsize(path)

    def emit(self, record: logging.LogRecord) -> None:
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
                    msg = self.format(record)
                    self._stream.write(msg + "\n")
                    self._stream.flush()
                    self._bytes_written += len(msg.encode("utf-8")) + 1
                    if self._bytes_written >= self._file_max_bytes:
                        self._rotate_file()
            except Exception as exc:
                print(f"[LOG ERROR] 写入日志文件失败: {exc}", file=sys.stderr)
                self.handleError(record)

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
            except OSError:
                pass

    def close(self) -> None:
        with self._emit_lock:
            try:
                if self._stream:
                    self._stream.close()
                    self._stream = None
            except Exception:
                pass
        super().close()


class LogConfigCenter:
    """
    日志配置中心（单例模式）

    统一管理整个应用的日志配置，避免重复配置和配置不一致问题
    """

    _instance = None
    _init_lock = threading.Lock()

    DEFAULT_CONFIG = {
        "level": "INFO",
        "format": "%(asctime)s | %(levelname)s | %(side)s | %(name)s | %(message)s",
        "date_format": "%Y-%m-%d %H:%M:%S",
        "console_colored": True,
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

    @classmethod
    def get_instance(cls) -> "LogConfigCenter":
        if cls._instance is None:
            cls()
        return cls._instance

    def initialize(
        self, config: Dict[str, Any] | None = None, side: str = "BACKEND"
    ) -> None:
        """初始化日志配置（仅首次调用有效）"""
        with self._init_lock:
            if self._configured:
                return

            if config:
                self._config.update(config)
            self._side = side

            configure_root_logger(self._config, side)
            self._configured = True

    def get_logger(self, name: str, side: str | None = None) -> logging.Logger:
        """获取配置好的日志器"""
        if not self._configured:
            self.initialize()
        return get_logger(name, side or self._side)

    def set_level(self, level: str) -> None:
        """动态修改根日志器和控制台 handler 的级别（热更新）"""
        normalized = _normalize_level(level)
        numeric = _level_value(normalized)
        root = logging.getLogger()
        root.setLevel(numeric)
        for handler in root.handlers:
            if isinstance(handler, logging.StreamHandler) and not isinstance(
                handler, _DateRotatingFileHandler
            ):
                handler.setLevel(numeric)
        self._config["level"] = normalized

    def get_config(self) -> Dict[str, Any]:
        return self._config.copy()

    def is_initialized(self) -> bool:
        return self._configured

    def add_file_handler(self, log_dir: str, retention_days: int = 7) -> None:
        """添加按日期存储的日志处理器（始终记录全部级别）"""
        root = logging.getLogger()
        for handler in list(root.handlers):
            if isinstance(handler, _DateRotatingFileHandler):
                if str(handler._log_dir) == str(log_dir):
                    return  # 相同目录，无需替换
                # 不同目录，移除旧 handler
                root.removeHandler(handler)
                handler.close()
                break

        try:
            file_handler = _DateRotatingFileHandler(
                log_dir=log_dir,
                retention_days=retention_days,
                level=logging.DEBUG,
                formatter=_formatter(
                    "%(asctime)s | %(levelname)s | %(side)s | %(name)s | %(message)s",
                    colored=False,
                ),
                file_max_bytes=self._config.get("file_max_bytes", 5 * 1024 * 1024),
                file_backup_count=self._config.get("file_backup_count", 3),
            )
            file_handler.addFilter(SideFilter(side="BACKEND"))
            root.addHandler(file_handler)
            root.info("=" * 54)
            root.info(">>> Campus-Auth 日志系统启动")
            root.info(">>> 日志目录: %s | 保留 %d 天", log_dir, retention_days)
            root.info("=" * 54)
        except Exception as e:
            root.warning("无法启用文件日志 %s: %s", log_dir, e)


class WebSocketLogHandler(logging.Handler):
    """将 Python 日志记录转发到 WebSocket 广播队列，使前端能显示完整后端日志。

    同时将日志存入 log_store（deque），使 /api/logs 能返回完整后端日志，
    避免刷新前端后丢失 Python logging 系统产生的日志。

    用法：
        handler = WebSocketLogHandler(broadcast_queue, log_store=monitor_service.logs)
        logging.getLogger().addHandler(handler)
    """

    # 不转发这些 logger 的日志，避免回声或与 _push_log 重复
    _EXCLUDED_LOGGERS = frozenset({
        "backend.ws_manager",
        "backend.monitor_service",
    })

    _LogEntry: type | None = None  # 延迟初始化，避免循环导入

    def __init__(self, broadcast_queue: deque[dict], log_store: deque | None = None):
        super().__init__()
        self._queue = broadcast_queue
        self._log_store = log_store

    def emit(self, record: logging.LogRecord) -> None:
        if record.name in self._EXCLUDED_LOGGERS:
            return
        try:
            msg = self.format(record)
            stamp = datetime.fromtimestamp(record.created).strftime("%Y-%m-%d %H:%M:%S")
            side = getattr(record, "side", "BACKEND")
            log_data = {
                "timestamp": stamp,
                "level": record.levelname,
                "source": f"{side}.{record.name}",
                "message": msg,
            }
            self._queue.append({"type": "log", "data": log_data})
            if self._log_store is not None:
                if WebSocketLogHandler._LogEntry is None:
                    from backend.schemas import LogEntry
                    WebSocketLogHandler._LogEntry = LogEntry
                self._log_store.append(WebSocketLogHandler._LogEntry(**log_data))
        except Exception:
            self.handleError(record)
