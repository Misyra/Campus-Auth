"""网络工具函数"""

from __future__ import annotations

from app.utils.logging import get_logger

logger = get_logger("parsers")


def parse_url_checks(raw: str | list | None) -> list[tuple[str, str]]:
    """解析网址响应检测 URL 列表，返回 [(url, expected_text), ...]。

    支持三种格式：
    - 字符串：每行一个 "url|expected_text"
    - 列表：[[url, expected_text], ...] 或 [(url, expected_text), ...]
    - 字符串列表：["url|expected_text", ...]

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
        entries = []
        for e in raw:
            if isinstance(e, dict):
                url = e.get("url", "")
                expected = e.get("expected", "")
                if url and expected:
                    entries.append((url, expected))
            elif isinstance(e, list | tuple) and len(e) >= 2 and e[0] and e[1]:
                entries.append((e[0], e[1]))
            elif isinstance(e, str) and "|" in e:
                url, _, expected = e.partition("|")
                url = url.strip()
                expected = expected.strip()
                if url and expected:
                    entries.append((url, expected))
        return entries

    return []


def _parse_single_host_port(item: str) -> tuple[str, int]:
    """解析单个 'host:port' 字符串为 (host, port) 元组。

    Args:
        item: 格式为 "host:port" 的字符串

    Returns:
        解析后的 (host, port) 元组

    Raises:
        ValueError: 如果格式无效（缺少端口、端口非数字、端口超范围、主机名为空）
    """
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

    return (host, port)


def parse_host_port(targets: list[str]) -> list[tuple[str, int]]:
    """解析 'host:port' 字符串列表为 (host, port) 元组列表。

    跳过格式无效的条目并记录警告，不会因单条错误丢弃全部目标。

    Args:
        targets: 格式为 "host:port" 的字符串列表，
                 例如 ["8.8.8.8:53", "[::1]:8080", "example.com:80"]

    Returns:
        解析后的 (host, port) 元组列表。输入为空列表时返回空列表。
    """
    result: list[tuple[str, int]] = []
    for item in targets:
        try:
            result.append(_parse_single_host_port(item))
        except ValueError as exc:
            logger.warning("忽略无效探测目标 '{}': {}", item, exc)
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
            # [IPv6] 或 [IPv6]:port 格式
            if "]" in item and not item.split("]", 1)[1].startswith(":"):
                # 无端口，补全默认 DNS 端口
                targets.append(f"{item}:53")
            else:
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
