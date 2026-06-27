"""login_runner — 自动登录执行器（从 main.py 提取）。"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from app.schemas import LoginResult, RuntimeConfig

if TYPE_CHECKING:
    from app.schemas import ApplicationContext


def load_login_config(logger):
    """加载登录所需的运行时配置。

    Returns:
        (RuntimeConfig, None) — 成功时返回 RuntimeConfig 和 None。
        (None, LoginResult.CONFIG_ERROR) — 失败时返回 None 和错误结果。
    """
    from app.services.profile_service import create_profile_service

    ps = create_profile_service()
    runtime_config = ps.get_runtime_config()
    return runtime_config, None


def execute_login_with_retries(runtime_config: RuntimeConfig, logger) -> LoginResult:
    """执行登录，含固定间隔重试。

    用 ImmediatePolicy + LoginOrchestrator，不再自己写重试/超时/历史。

    Args:
        runtime_config: 运行时配置。
        logger: 日志记录器。

    Returns:
        LoginResult.SUCCESS — 登录成功
        LoginResult.TEMPORARY_FAILURE — 重试耗尽仍失败
    """
    from app.constants import AUTH_DATA_DIR
    from app.services.login_history_service import LoginHistoryService
    from app.services.login_orchestrator import LoginOrchestrator
    from app.services.profile_service import create_profile_service
    from app.services.retry_policy import ImmediatePolicy
    from app.workers.playwright_worker import cleanup_orphan_browsers, get_worker

    # 构造一次性 Orchestrator（login_once 在容器创建前运行）
    profile_service = create_profile_service()
    history = LoginHistoryService(AUTH_DATA_DIR)
    orchestrator = LoginOrchestrator(
        worker_getter=get_worker,
        login_history=history,
        profile_service=profile_service,
    )

    policy = ImmediatePolicy(
        max_retries=runtime_config.retry.max_retries,
        interval=runtime_config.retry.retry_interval,
    )

    try:
        for attempt in policy.attempts():
            delay = policy.delay_before(attempt)
            if delay > 0:
                print(f"等待 {int(delay)} 秒后重试第 {attempt} 次...")
                time.sleep(delay)

            handle = orchestrator.submit(source="login_once", config=runtime_config)
            ok, msg = handle.result()
            if ok:
                print(f"登录成功: {msg}")
                cleanup_orphan_browsers()
                return LoginResult.SUCCESS
            print(f"登录失败 (第 {attempt} 次): {msg}")

        cleanup_orphan_browsers()
        print(f"已重试 {policy.max_retries} 次均失败，回退到正常模式")
        logger.warning("登录失败（已重试 {} 次），回退到正常模式", policy.max_retries)
        return LoginResult.TEMPORARY_FAILURE
    finally:
        orchestrator.shutdown(wait=False)


def run_login_then_exit(ctx: ApplicationContext, logger) -> LoginResult:
    """自动登录，成功后退出模式。

    返回:
        LoginResult.SUCCESS — 登录成功，应退出进程
        LoginResult.CONFIG_ERROR — 配置错误，应退出进程
        LoginResult.TEMPORARY_FAILURE — 临时失败，继续监控
    """
    # 加载配置
    try:
        runtime_config, error = load_login_config(logger)
        if error is not None:
            return error
    except Exception as exc:
        logger.error("加载配置失败: {}", exc)
        return LoginResult.CONFIG_ERROR

    # 先检测网络状态，已连接则无需登录
    try:
        from app.network.decision import check_network_status

        network_ok, reason, _ = check_network_status(runtime_config.monitor)
        if network_ok:
            print("网络已连接，无需登录，正在退出...")
            return LoginResult.SUCCESS
        if reason == "all_disabled":
            # 所有检测方式禁用，无法判断网络状态，假定已连接跳过登录
            print("网络检测已禁用，假定网络正常，跳过登录")
            return LoginResult.SUCCESS
        print(f"网络未连接 ({reason})，开始登录...")
    except Exception as exc:
        logger.debug("网络检测异常，继续尝试登录: {}", exc)
        print("网络检测异常，开始登录...")

    return execute_login_with_retries(runtime_config, logger)
