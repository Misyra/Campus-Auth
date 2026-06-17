"""网络工具函数"""

from __future__ import annotations


def parse_url_checks(raw: str | list | None) -> list[tuple[str, str]]:
    """解析网址响应检测 URL 列表，返回 [(url, expected_text), ...]。

    支持两种格式：
    - 字符串：每行一个 "url|expected_text"
    - 列表：[[url, expected_text], ...] 或 [(url, expected_text), ...]

    参数:
        raw: 原始网址响应检测配置

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
            if isinstance(e, list | tuple) and len(e) >= 2 and e[0] and e[1]
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
            raise ValueError(f"格式错误 '{item}'：缺少端口号（请使用 host:port 格式）")

        host_part, port_part = item.rsplit(":", 1)
        host = host_part.strip()
        # 剥离 IPv6 方括号：[::1] → ::1
        if host.startswith("[") and host.endswith("]"):
            host = host[1:-1]
        port_str = port_part.strip()

        if not host:
            raise ValueError(f"'{item}' 中主机名为空")

        if not port_str.isdigit():
            raise ValueError(f"'{item}' 中的端口 '{port_part}' 不是数字")

        port = int(port_str)
        if not (1 <= port <= 65535):
            raise ValueError(f"'{item}' 中的端口 {port} 超出范围（1-65535）")

        result.append((host, port))

    return result


def parse_ping_targets(raw: str | list | None) -> list[tuple[str, int]]:
    """解析 ping_targets 配置为 (host, port) 列表。

    支持字符串（逗号分隔）和列表两种格式。
    缺少端口的项自动补全（IPv4:53, 域名:443）。

    Args:
        raw: 原始配置，可以是逗号分隔字符串、列表或 None

    Returns:
        解析后的 (host, port) 元组列表
    """
    if not raw:
        return []

    if isinstance(raw, str):
        items = [t.strip() for t in raw.split(",") if t.strip()]
    else:
        items = [str(t).strip() for t in raw if str(t).strip()]

    if not items:
        return []

    # 补全缺少端口的项
    targets: list[str] = []
    for item in items:
        if item.startswith("["):
            # 已是 [IPv6]:port 格式，直接传递
            targets.append(item)
        elif ":" in item:
            # 可能是 IPv6 地址（含多个冒号）或 host:port
            colon_count = item.count(":")
            if colon_count >= 2:
                # IPv6 地址，补全端口
                targets.append(f"[{item}]:53")
            else:
                # host:port 格式，直接传递
                targets.append(item)
        else:
            # 无冒号：IPv4 或域名
            parts = item.split(".")
            is_ipv4 = len(parts) == 4 and all(p.isdigit() for p in parts)
            targets.append(f"{item}:{53 if is_ipv4 else 443}")

    return parse_host_port(targets)
