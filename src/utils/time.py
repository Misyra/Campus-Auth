#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
时间相关工具类
"""

import datetime
from typing import Dict, Any, Tuple


class TimeUtils:
    """时间相关工具类"""
    
    @staticmethod
    def is_in_pause_period(pause_config: Dict[str, Any]) -> bool:
        """
        检查当前时间是否在暂停时段内
        
        参数:
            pause_config: 暂停配置字典
            
        返回:
            bool: 是否在暂停时段
        """
        if not pause_config.get('enabled', True):
            return False
            
        current_hour = datetime.datetime.now().hour
        start_hour = pause_config.get('start_hour', 0)
        end_hour = pause_config.get('end_hour', 6)
        
        # 处理跨天的情况（如23点到6点）
        if start_hour <= end_hour:
            # 同一天内的时间段（如0点到6点）
            return start_hour <= current_hour < end_hour
        else:
            # 跨天的时间段（如23点到6点）
            return current_hour >= start_hour or current_hour < end_hour


def get_runtime_stats(start_time: float, check_count: int) -> Tuple[str, str]:
    """
    获取运行时统计信息
    
    参数:
        start_time: 开始时间戳
        check_count: 检测次数
        
    返回:
        Tuple[str, str]: (运行时间字符串, 统计信息字符串)
    """
    if start_time:
        elapsed = int(datetime.datetime.now().timestamp() - start_time)
        hours = elapsed // 3600
        minutes = (elapsed % 3600) // 60
        seconds = elapsed % 60
        runtime_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    else:
        runtime_str = "00:00:00"
    
    stats_str = f"检测次数: {check_count}"
    
    return runtime_str, stats_str
