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


def setup_logger(name: str, config: Dict[str, Any] | None = None) -> logging.Logger:
    if config is None:
        config = {}

    logger = logging.getLogger(name)

    if logger.handlers:
        return logger

    log_level = config.get("level", "INFO")
    logger.setLevel(getattr(logging, log_level.upper()))

    console_formatter = ColoredFormatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s", datefmt="%H:%M:%S"
    )
    file_formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)

    log_file = config.get("file")
    if log_file:
        try:
            log_dir = os.path.dirname(log_file)
            if log_dir and not os.path.exists(log_dir):
                os.makedirs(log_dir, exist_ok=True)

            file_handler = logging.handlers.RotatingFileHandler(
                log_file, maxBytes=1 * 1024 * 1024, backupCount=3, encoding="utf-8"
            )
            file_handler.setFormatter(file_formatter)
            logger.addHandler(file_handler)
        except Exception as e:
            logger.warning(f"无法创建日志文件 {log_file}: {e}")

    logger.propagate = False
    return logger


class LoggerSetup:
    @staticmethod
    def setup_logger(name: str, config: Dict[str, Any]) -> logging.Logger:
        return setup_logger(name, config)
