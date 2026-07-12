"""login_runner — 自动登录执行器（从 main.py 提取）。"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from app.schemas import LoginResult, RuntimeConfig

if TYPE_CHECKING:
    from app.schemas import ApplicationContext


def execute_login_with_retries(runtime_config: RuntimeConfig, logger) -> LoginResult:
    """执行登录（重试由 Worker 内的 LoginSession 负责）。

    本函数仅做单次 submit，重试循环已收敛到 LoginSession（单次会话内
    复用浏览器，失败重试间隔由 RetrySettings.retry_interval 控制）。

    Args:
        runtime_config: 运行时配置。
        logger: 日志记录器。

    Returns:
        LoginResult.SUCCESS — 登录成功
        LoginResult.TEMPORARY_FAILURE — 重试耗尽仍失败
    """
    from concurrent.futures import ThreadPoolExecutor

    from app.constants import AUTH_DATA_DIR
    from app.services.login_history_service import LoginHistoryService
    from app.services.login_orchestrator import LoginOrchestrator
    from app.services.profile_service import get_profile_service
    from app.workers.playwright_worker import cleanup_orphan_browsers, get_worker

    profile_service = get_profile_service()
    history = LoginHistoryService(AUTH_DATA_DIR)
    # login_once 是单次登录后退出，用一次性 executor 即可
    one_shot_executor = ThreadPoolExecutor(
        max_workers=1, thread_name_prefix="login-once"
    )
    orchestrator = LoginOrchestrator(
        worker_getter=get_worker,
        executor=one_shot_executor,
        login_history=history,
        profile_service=profile_service,
    )

    try:
        handle = orchestrator.submit(source="login_once", config=runtime_config)
        ok, msg = handle.result()
        cleanup_orphan_browsers()
        if ok:
            return LoginResult.SUCCESS
        logger.warning("登录失败: {}", msg)
        return LoginResult.TEMPORARY_FAILURE
    finally:
        orchestrator.shutdown(wait=False)
        one_shot_executor.shutdown(wait=False)


def run_login_then_exit(ctx: ApplicationContext, logger) -> LoginResult:
    """自动登录，成功后退出模式。

    返回:
        LoginResult.SUCCESS — 登录成功，应退出进程
        LoginResult.CONFIG_ERROR — 配置错误，应退出进程
        LoginResult.TEMPORARY_FAILURE — 临时失败，继续监控
    """
    # 加载配置
    try:
        from app.services.profile_service import get_profile_service

        ps = get_profile_service()
        runtime_config = ps.get_runtime_config()
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

    return execute_login_with_retries(runtime_config, logger)
