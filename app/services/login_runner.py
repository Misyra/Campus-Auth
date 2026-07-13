"""login_runner — 自动登录执行器（从 main.py 提取）。"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from app.schemas import LoginResult, RuntimeConfig

if TYPE_CHECKING:
    from app.container import ServiceContainer
    from app.schemas import ApplicationContext


def execute_login_with_retries(
    runtime_config: RuntimeConfig,
    container: ServiceContainer,
    logger,
) -> LoginResult:
    """执行登录（重试由 Worker 内的 LoginSession 负责）。

    通过 Container 的 login_orchestrator 提交登录任务。
    本函数仅做单次 submit，重试循环已收敛到 LoginSession。

    Args:
        runtime_config: 运行时配置。
        container: 服务容器，提供 login_orchestrator。
        logger: 日志记录器。

    Returns:
        LoginResult.SUCCESS — 登录成功
        LoginResult.TEMPORARY_FAILURE — 重试耗尽仍失败
    """
    from app.services.login_orchestrator import validate_login_config
    from app.services.worker_port import cleanup_orphan_browsers

    # B2 修复：预校验凭据完整性
    err = validate_login_config(runtime_config)
    if err is not None:
        logger.warning("登录配置无效: {}", err)
        return LoginResult.CONFIG_ERROR

    try:
        handle = container.login_orchestrator.submit(
            source="login_once", config=runtime_config
        )
        ok, msg = handle.result()
        cleanup_orphan_browsers()
        if ok:
            return LoginResult.SUCCESS
        logger.warning("登录失败: {}", msg)
        return LoginResult.TEMPORARY_FAILURE
    except Exception as exc:
        logger.warning("登录执行异常: {}", exc)
        return LoginResult.TEMPORARY_FAILURE


def run_login_then_exit(
    ctx: ApplicationContext,
    container: ServiceContainer,
    logger,
) -> LoginResult:
    """自动登录，成功后退出模式。

    Args:
        ctx: 应用上下文。
        container: 服务容器，提供 config_service 和 login_orchestrator。
        logger: 日志记录器。

    Returns:
        LoginResult.SUCCESS — 登录成功，应退出进程
        LoginResult.CONFIG_ERROR — 配置错误，应退出进程
        LoginResult.TEMPORARY_FAILURE — 临时失败，继续监控
    """
    # 加载配置
    try:
        runtime_config = container.config_service.get_runtime_config()
    except Exception as exc:
        logger.warning("加载配置失败: {}", exc)
        return LoginResult.CONFIG_ERROR

    # 先检测网络状态，已连接则无需登录
    try:
        from app.network.decision import check_network_status

        network_ok, reason, _ = asyncio.run(
            check_network_status(runtime_config.monitor)
        )
        if network_ok:
            logger.info("网络已连接，无需登录")
            return LoginResult.SUCCESS
        if reason == "all_disabled":
            # 所有检测方式禁用，无法判断网络状态，假定已连接跳过登录
            logger.info("网络检测已禁用，假定网络正常，跳过登录")
            return LoginResult.SUCCESS
        logger.debug("网络未连接 ({})，开始登录", reason)
    except Exception as exc:
        logger.debug("网络检测异常，继续尝试登录: {}", exc)

    return execute_login_with_retries(runtime_config, container, logger)
