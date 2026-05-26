"""网络工具函数"""


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
                f"Malformed target '{item}': missing port (use host:port format)"
            )

        host_part, port_part = item.rsplit(":", 1)
        host = host_part.strip()
        port_str = port_part.strip()

        if not host:
            raise ValueError(f"Malformed target '{item}': empty host")

        if not port_str.isdigit():
            raise ValueError(
                f"Invalid port '{port_part}' in target '{item}': not a number"
            )

        port = int(port_str)
        if not (1 <= port <= 65535):
            raise ValueError(
                f"Invalid port '{port}' in target '{item}': out of range (1-65535)"
            )

        result.append((host, port))

    return result
