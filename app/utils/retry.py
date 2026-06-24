"""重试间隔计算工具。"""


def get_retry_intervals(
    retry_interval: int,
    max_retries: int,
    *,
    exponential: bool = False,
    max_interval: int = 300,
) -> list[int]:
    """计算重试间隔列表。

    exponential=True 时使用指数退避（间隔翻倍），否则使用固定间隔。
    max_interval 限制指数退避的单次最大间隔（秒），防止间隔过大。
    """
    # BUG-053 修复：防御性上限，防止极大 max_retries 产生巨型列表
    max_retries = min(max_retries, 1000)
    if exponential:
        return [min(retry_interval * (2**i), max_interval) for i in range(max_retries)]
    return [retry_interval] * max_retries
