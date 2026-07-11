"""时间相关工具函数"""

from __future__ import annotations

import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.schemas import PauseSettings


def _parse_pause_range(raw: str) -> tuple[datetime.time, datetime.time]:
    """解析 HH:MM-HH:MM 格式的暂停时段字符串。"""
    if "-" not in raw:
        raise ValueError(f"暂停时段格式错误 '{raw}'：缺少 '-' 分隔符，应为 HH:MM-HH:MM")
    parts = raw.split("-")
    if len(parts) != 2:
        raise ValueError(f"暂停时段格式错误 '{raw}'：包含多个 '-'，应为 HH:MM-HH:MM")
    start_str, end_str = parts
    start = datetime.datetime.strptime(start_str.strip(), "%H:%M").time()
    end = datetime.datetime.strptime(end_str.strip(), "%H:%M").time()
    return start, end


def _is_in_pause_period(
    now: datetime.datetime, ranges: list[tuple[datetime.time, datetime.time]]
) -> bool:
    """检查指定时间是否在暂停时段内。

    参数:
        now: 要判断的时间点
        ranges: 暂停时段列表，每项为 (start, end) 时间对

    返回:
        是否在暂停时段
    """
    current = now.time()
    for start, end in ranges:
        if start <= end:
            if start <= current <= end:
                return True
        else:
            if current >= start or current <= end:
                return True
    return False


def is_pause_enabled(pause: PauseSettings) -> bool:
    """检查 PauseSettings 是否在当前时间处于暂停状态。"""
    if not pause.enabled:
        return False

    # start == end 且分钟相同时视为全天暂停
    if pause.start_hour == pause.end_hour and pause.start_minute == pause.end_minute:
        return True

    start = datetime.time(pause.start_hour, pause.start_minute)
    end = datetime.time(pause.end_hour, pause.end_minute)
    return _is_in_pause_period(datetime.datetime.now(), [(start, end)])
