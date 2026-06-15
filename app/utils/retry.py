"""重试间隔计算工具。"""


def get_retry_intervals(
    retry_interval: int,
    max_retries: int,
    *,
    exponential: bool = False,
) -> list[int]:
    """计算重试间隔列表。

    exponential=True 时使用指数退避（间隔翻倍），否则使用固定间隔。
    """
    if exponential:
        return [retry_interval * (2**i) for i in range(max_retries)]
    return [retry_interval] * max_retries
