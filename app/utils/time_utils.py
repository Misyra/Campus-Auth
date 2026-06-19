"""时间相关工具函数"""

import datetime
from typing import Any


def is_in_pause_period(pause_config: dict[str, Any]) -> bool:
    """检查当前时间是否在暂停时段内。

    当 pause_config 为空字典或缺少 enabled 字段时，默认认为暂停功能已启用。

    参数:
        pause_config: 暂停配置字典

    返回:
        是否在暂停时段
    """
    if not pause_config.get("enabled", True):
        return False

    current_hour = datetime.datetime.now().hour
    start_hour = pause_config.get("start_hour", 0)
    end_hour = pause_config.get("end_hour", 6)

    # start_hour == end_hour 时视为全天暂停（如 "全天不检测" 场景）
    if start_hour == end_hour:
        return True

    # 处理跨天的情况（如23点到6点）
    if start_hour < end_hour:
        # 同一天内的时间段（如0点到6点）
        return start_hour <= current_hour < end_hour
    else:
        # 跨天的时间段（如23点到6点）
        return current_hour >= start_hour or current_hour < end_hour
