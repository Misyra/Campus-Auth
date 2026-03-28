#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
异常处理工具类
"""

import logging
from typing import Callable

try:
    from playwright.async_api import TimeoutError as PlaywrightTimeoutError
except Exception:
    class PlaywrightTimeoutError(Exception):
        """Fallback timeout error when playwright is not installed yet."""
        pass


class ExceptionHandler:
    """异常处理增强器 - 按项目规范处理具体异常类型"""
    
    @staticmethod
    def handle_playwright_timeout(e: PlaywrightTimeoutError, operation: str, logger: logging.Logger) -> str:
        """处理Playwright超时异常"""
        error_msg = f"{operation}超时: {str(e)}"
        logger.error(error_msg)
        return error_msg
    
    @staticmethod
    def handle_network_error(e: Exception, operation: str, logger: logging.Logger) -> str:
        """处理网络相关异常"""
        error_msg = f"{operation}网络错误: {str(e)}"
        logger.error(error_msg)
        return error_msg
    
    @staticmethod
    def handle_config_error(e: Exception, operation: str, logger: logging.Logger) -> str:
        """处理配置相关异常"""
        error_msg = f"{operation}配置错误: {str(e)}"
        logger.error(error_msg)
        return error_msg
    
    @staticmethod
    def wrap_with_specific_handling(operation: str, logger: logging.Logger):
        """装饰器：为方法添加具体异常处理"""
        def decorator(func):
            async def wrapper(*args, **kwargs):
                try:
                    return await func(*args, **kwargs)
                except PlaywrightTimeoutError as e:
                    error_msg = ExceptionHandler.handle_playwright_timeout(e, operation, logger)
                    raise PlaywrightTimeoutError(error_msg) from e
                except (ConnectionError, OSError) as e:
                    error_msg = ExceptionHandler.handle_network_error(e, operation, logger)
                    raise ConnectionError(error_msg) from e
                except (ValueError, KeyError, TypeError) as e:
                    error_msg = ExceptionHandler.handle_config_error(e, operation, logger)
                    raise ValueError(error_msg) from e
                except Exception as e:
                    # 最后才使用通用异常处理
                    error_msg = f"{operation}发生未知错误: {str(e)}"
                    logger.error(error_msg)
                    raise RuntimeError(error_msg) from e
            return wrapper
        return decorator
