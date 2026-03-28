#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
重试处理工具类
"""

import asyncio
import logging
from typing import Dict, Any, Tuple, Callable

from .logging import LoggerSetup


class SimpleRetryHandler:
    """简化重试处理器 - 使用简单的重试机制"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.retry_settings = config.get('retry_settings', {})
        self.logger = LoggerSetup.setup_logger(f"{__name__}_retry", config.get('logging', {}))
    
    async def retry_with_simple_backoff(self, operation: Callable, max_retries: int = None) -> Tuple[bool, Any, str]:
        """
        简单的重试机制
        
        参数:
            operation: 要重试的异步操作
            max_retries: 最大重试次数
            
        返回:
            Tuple[bool, Any, str]: (是否成功, 结果, 错误信息)
        """
        if max_retries is None:
            max_retries = self.retry_settings.get('max_retries', 3)
        
        retry_interval = self.retry_settings.get('retry_interval', 5)
        last_error = None
        
        for attempt in range(max_retries):
            try:
                result = await operation()
                if attempt > 0:
                    self.logger.info(f"✅ 操作在第{attempt + 1}次尝试后成功")
                return True, result, ""
                
            except Exception as e:
                last_error = e
                
                if attempt < max_retries - 1:  # 不是最后一次尝试
                    self.logger.warning(
                        f"❌ 第{attempt + 1}次尝试失败: {str(e)}, "
                        f"{retry_interval}秒后重试..."
                    )
                    
                    # 简单等待
                    await asyncio.sleep(retry_interval)
                else:
                    self.logger.error(f"❌ 所有{max_retries}次尝试均失败")
        
        error_msg = f"重试{max_retries}次后仍然失败，最后错误: {str(last_error)}"
        return False, None, error_msg
