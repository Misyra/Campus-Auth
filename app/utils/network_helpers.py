"""网络工具函数"""

from __future__ import annotations


def parse_portal_checks(raw: str | list | None) -> list[tuple[str, str]]:
    """解析 Portal 检测 URL 列表，返回 [(url, expected_text), ...]。

    支持两种格式：
    - 字符串：每行一个 "url|expected_text"
    - 列表：[[url, expected_text], ...] 或 [(url, expected_text), ...]

    参数:
        raw: 原始 Portal 检测配置

    返回: 解析后的 (url, expected_text) 元组列表
    """
    if not raw:
        return []

    if isinstance(raw, str):
        entries = []
        for line in raw.splitlines():
            line = line.strip()
            if "|" in line:
                url, _, expected = line.partition("|")
                url = url.strip()
                expected = expected.strip()
                if url and expected:
                    entries.append((url, expected))
        return entries

    if isinstance(raw, list):
        return [
            (e[0], e[1])
            for e in raw
            if isinstance(e, (list, tuple)) and len(e) >= 2 and e[0] and e[1]
        ]

    return []


def parse_host_port(targets: list[str]) -> list[tuple[str, int]]:
    """解析 'host:port' 字符串列表为 (host, port) 元组列表。

    Args:
        targets: 格式为 "host:port" 的字符串列表，
                 例如 ["8.8.8.8:53", "[::1]:8080", "example.com:80"]

    Returns:
        解析后的 (host, port) 元组列表。输入为空列表时返回空列表。

    Raises:
        ValueError: 如果输入格式无效：
            - 缺少冒号（没有指定端口）
            - 端口不是数字
            - 端口不在 1-65535 范围内
            - 主机名为空
    """
    result: list[tuple[str, int]] = []
    for item in targets:
        if ":" not in item:
            raise ValueError(
                f"格式错误 '{item}'：缺少端口号（请使用 host:port 格式）"
            )

        host_part, port_part = item.rsplit(":", 1)
        host = host_part.strip()
        port_str = port_part.strip()

        if not host:
            raise ValueError(f"'{item}' 中主机名为空")

        if not port_str.isdigit():
            raise ValueError(
                f"'{item}' 中的端口 '{port_part}' 不是数字"
            )

        port = int(port_str)
        if not (1 <= port <= 65535):
            raise ValueError(
                f"'{item}' 中的端口 {port} 超出范围（1-65535）"
            )

        result.append((host, port))

    return result
