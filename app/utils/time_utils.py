"""时间相关工具函数"""

from __future__ import annotations

import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.schemas import PauseSettings


def is_in_pause_period(pause: PauseSettings) -> bool:
    """检查当前时间是否在暂停时段内。

    参数:
        pause: PauseSettings 模型实例

    返回:
        是否在暂停时段
    """
    if not pause.enabled:
        return False

    current_hour = datetime.datetime.now().hour
    start_hour = pause.start_hour
    end_hour = pause.end_hour

    # start_hour == end_hour 时视为全天暂停
    if start_hour == end_hour:
        return True

    # 处理跨天的情况（如23点到6点）
    if start_hour < end_hour:
        return start_hour <= current_hour < end_hour
    else:
        return current_hour >= start_hour or current_hour < end_hour
