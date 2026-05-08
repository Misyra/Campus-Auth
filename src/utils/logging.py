import logging
import logging.handlers
import os
import sys
import threading
import time
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


def _normalize_level(level: str | None, default: str = "INFO") -> str:
    raw = str(level or default).upper().strip()
    return raw if raw in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"} else default


def _level_value(level: str | None, default: str = "INFO") -> int:
    return getattr(logging, _normalize_level(level, default), logging.INFO)


def _formatter(pattern: str, colored: bool = False) -> logging.Formatter:
    if colored:
        return ColoredFormatter(pattern, datefmt="%H:%M:%S")
    return logging.Formatter(pattern, datefmt="%Y-%m-%d %H:%M:%S")


# 全局标记：根 logger 是否已完成首次配置
_root_configured = False


def configure_root_logger(
    config: Dict[str, Any] | None = None, side: str = "BACKEND"
) -> logging.Logger:
    """配置根日志器。仅首次调用时完整配置，后续调用跳过以避免重复 handler。"""
    global _root_configured
    config = config or {}
    root = logging.getLogger()

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
    """按日期自动切换的日志处理器 — 当前日志写入 YYYY-MM-DD.log"""

    def __init__(self, log_dir: str, retention_days: int = 7,
                 level: int = logging.INFO, formatter: logging.Formatter | None = None):
        super().__init__(level=level)
        self._log_dir = log_dir
        self._retention = retention_days
        self._current_date: str | None = None
        self._last_cleanup: float = 0
        self._stream = None
        self._emit_lock = threading.Lock()
        if formatter:
            self.setFormatter(formatter)

    def _get_log_path(self) -> str:
        date_str = datetime.now().strftime("%Y-%m-%d")
        return os.path.join(self._log_dir, f"{date_str}.log")

    def _open_file(self, path: str) -> None:
        os.makedirs(self._log_dir, exist_ok=True)
        if self._stream:
            try:
                self._stream.close()
            except Exception:
                pass
        self._stream = open(path, "a", encoding="utf-8")

    def emit(self, record: logging.LogRecord) -> None:
        with self._emit_lock:
            try:
                today = datetime.now().strftime("%Y-%m-%d")
                if today != self._current_date or self._stream is None:
                    self._current_date = today
                    path = self._get_log_path()
                    self._open_file(path)

                # 每小时运行一次过期日志清理
                now = time.time()
                if now - self._last_cleanup > 3600:
                    self._last_cleanup = now
                    cutoff = now - self._retention * 86400
                    for f in Path(self._log_dir).glob("*.log"):
                        try:
                            if f.stat().st_mtime < cutoff:
                                f.unlink()
                        except OSError:
                            pass

                if self._stream:
                    msg = self.format(record)
                    self._stream.write(msg + os.linesep)
                    self._stream.flush()
            except Exception as exc:
                print(f"[LOG ERROR] 写入日志文件失败: {exc}", file=sys.stderr)
                self.handleError(record)

    def close(self) -> None:
        try:
            if self._stream:
                self._stream.close()
                self._stream = None
        except Exception:
            pass
        super().close()


def cleanup_debug_screenshots(debug_dir: str, retention_days: int) -> int:
    """清理 debug/ 下按日期命名的子目录中的过期截图，并删除空目录

    目录结构: debug/{YYYY-MM-DD}/*.png
    """
    import shutil

    base = Path(debug_dir)
    if not base.exists():
        return 0

    cutoff = time.time() - retention_days * 86400
    deleted = 0
    for subdir in sorted(base.iterdir()):
        if not subdir.is_dir():
            continue
        if not subdir.name[:4].isdigit():
            continue
        for f in subdir.glob("*.png"):
            try:
                if f.stat().st_mtime < cutoff:
                    f.unlink()
                    deleted += 1
            except OSError:
                pass
        try:
            if not any(subdir.iterdir()):
                subdir.rmdir()
        except OSError:
            pass
    return deleted


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

    def initialize(self, config: Dict[str, Any] | None = None, side: str = "BACKEND") -> None:
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
            if isinstance(handler, logging.StreamHandler) and not isinstance(handler, _DateRotatingFileHandler):
                handler.setLevel(numeric)
        self._config["level"] = normalized

    def get_config(self) -> Dict[str, Any]:
        return self._config.copy()

    def is_initialized(self) -> bool:
        return self._configured

    def add_file_handler(self, log_dir: str, retention_days: int = 7) -> None:
        """添加按日期存储的日志处理器（始终记录全部级别）"""
        root = logging.getLogger()
        for handler in root.handlers:
            if isinstance(handler, _DateRotatingFileHandler):
                return

        try:
            if root.level > logging.DEBUG and root.level != logging.NOTSET:
                root.setLevel(logging.DEBUG)
            file_handler = _DateRotatingFileHandler(
                log_dir=log_dir,
                retention_days=retention_days,
                level=logging.DEBUG,
                formatter=_formatter(
                    "%(asctime)s | %(levelname)s | %(side)s | %(name)s | %(message)s",
                    colored=False,
                ),
            )
            file_handler.addFilter(SideFilter(side="BACKEND"))
            root.addHandler(file_handler)
            root.info("=" * 54)
            root.info(">>> Campus-Auth 日志系统启动")
            root.info(">>> 日志目录: %s | 保留 %d 天", log_dir, retention_days)
            root.info("=" * 54)
        except Exception as e:
            root.warning("无法启用文件日志 %s: %s", log_dir, e)
