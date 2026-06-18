"""并发竞态工具 — 提取 futures "首个成功/首个失败" 的通用模式。

probes.py 中 3 个网络检测函数和 decision.py 中 1 个认证可达性检测
共享相同的 OR 语义竞态模式：提交多个 future，首个成功即取消其余并返回 True。
decision.py 的 is_network_available 使用 AND 语义（首个失败即返回 False），
使用 cancel_pending 辅助函数消除内联取消循环。
"""

from __future__ import annotations

from concurrent.futures import Future, as_completed

from app.utils.logging import get_logger

logger = get_logger("concurrent", source="backend")


def race_first_success(
    futures: dict[Future, object],
    timeout: float,
    label: str,
    *,
    success_prefix: str = "",
    fail_prefix: str = "",
) -> bool:
    """OR 语义竞态：首个成功的 future 即返回 True，取消其余。

    future 的结果协议：
    - 3-tuple ``(result_label, ok, detail)``：ok 为 True 表示成功，
      result_label 和 detail 用于日志。probes.py 的 worker 返回此格式。
    - ``bool``：直接以 bool 值判断成败。

    Args:
        futures: ``{future: key}`` 字典，由调用方通过 executor.submit 构建。
        timeout: ``as_completed`` 的总超时秒数。
        label: 日志中的上下文标签（如 "TCP"、"HTTP"）。
        success_prefix: 成功时的日志前缀。空字符串表示不记录成功日志。
        fail_prefix: 失败时的日志前缀。空字符串表示不记录失败日志。

    Returns:
        True 如果至少一个 future 返回成功，否则 False。
    """
    try:
        for future in as_completed(futures, timeout=timeout):
            result = future.result(timeout=1)

            # 解析结果：3-tuple (label, ok, detail) 或 bool
            if isinstance(result, tuple) and len(result) == 3:
                result_label, ok, detail = result
            else:
                result_label, ok, detail = label, bool(result), ""

            if ok:
                if success_prefix:
                    logger.debug(
                        "{} 成功: {} {}", success_prefix, result_label, detail
                    )
                for f in futures:
                    if not f.done():
                        f.cancel()
                return True

            if fail_prefix:
                logger.debug("{} 失败: {} -- {}", fail_prefix, result_label, detail)

    except TimeoutError:
        logger.warning("{} 检测超时 ({:.1f}s)", label, timeout)
        return False

    logger.warning("所有 {} 目标均不可达 ({} 个)", label, len(futures))
    return False


def cancel_pending(futures: dict[Future, object]) -> None:
    """取消字典中所有尚未完成的 future。

    用于 AND 语义竞态（如 is_network_available）：
    任一检测方法失败即取消其余 future 并提前返回。
    """
    for f in futures:
        if not f.done():
            f.cancel()
