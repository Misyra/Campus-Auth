"""路由包 — 按功能领域拆分的 API 路由模块。"""

from app.schemas import ActionResponse
from app.utils.logging import get_logger

_api_logger = get_logger("api", source="backend")


def logged_action(ok: bool, message: str, log_fmt: str, *args) -> ActionResponse:
    """带日志的 ActionResponse 构造器。

    Args:
        ok: 操作是否成功
        message: 返回消息
        log_fmt: 日志格式字符串（使用 {} 占位符）
        *args: 日志格式参数（ok 和 message 会自动追加到末尾）
    """
    _api_logger.info(log_fmt, *args, ok, message)
    return ActionResponse(success=ok, message=message)
