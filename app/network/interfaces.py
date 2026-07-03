"""网络接口信息数据模型。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class InterfaceInfo:
    """网络接口信息，统一用于 API、探测、代理、UI。"""

    name: str
    ip: str  # IPv4，空串表示无 IPv4
    gateway: str  # 默认网关，空串表示无
    is_up: bool
