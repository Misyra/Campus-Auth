import logging
import logging.handlers
import os
import sys
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
        # 仅在控制台渲染时着色，避免污染同一条记录的文件输出
        original_levelname = record.levelname
        log_color = self.COLORS.get(original_levelname, self.RESET)
        record.levelname = f"{log_color}{original_levelname}{self.RESET}"
        try:
            return super().format(record)
        finally:
            record.levelname = original_levelname


class _DefaultContextFilter(logging.Filter):
    def __init__(self, side: str = "BACKEND"):
        super().__init__()
        self.side = side

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "side"):
            record.side = self.side
        return True


class _SideFilter(logging.Filter):
    def __init__(self, side: str):
        super().__init__()
        self.side = side

    def filter(self, record: logging.LogRecord) -> bool:
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

    # 一旦完成过一次完整配置就永远不再重新配置
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

    for handler in list(root.handlers):
        root.removeHandler(handler)

    context_filter = _DefaultContextFilter(side=side)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(_formatter(pattern, colored=True))
    console_handler.addFilter(context_filter)
    root.addHandler(console_handler)

    log_file = config.get("file")
    if log_file:
        try:
            log_dir = os.path.dirname(log_file)
            if log_dir and not os.path.exists(log_dir):
                os.makedirs(log_dir, exist_ok=True)

            file_handler = logging.handlers.RotatingFileHandler(
                log_file,
                maxBytes=1 * 1024 * 1024,
                backupCount=5,
                encoding="utf-8",
            )
            file_handler.setLevel(level)
            file_handler.setFormatter(_formatter(pattern, colored=False))
            file_handler.addFilter(context_filter)
            root.addHandler(file_handler)
        except Exception as e:
            root.warning(f"无法创建日志文件 {log_file}: {e}")

    _root_configured = True
    return root


def _attach_side_filter(logger: logging.Logger, side: str) -> None:
    for filt in logger.filters:
        if isinstance(filt, _SideFilter) and filt.side == side:
            return
    logger.addFilter(_SideFilter(side))


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


class LoggerSetup:
    @staticmethod
    def setup_logger(name: str, config: Dict[str, Any]) -> logging.Logger:
        return setup_logger(name, config)
