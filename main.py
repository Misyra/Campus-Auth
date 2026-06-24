#!/usr/bin/env python3
"""Campus-Auth 校园网自动认证 - 统一启动入口"""

import argparse
import asyncio
import atexit
import os
import signal
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

# 确保项目根目录在 sys.path 中（uv 环境下 sys.path 已由 uv 管理，但保留兼容性）
_project_root = Path(__file__).resolve().parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from app.constants import AUTH_DATA_DIR  # noqa: E402, F401 — 测试 fixture 需要
from app.schemas import (  # noqa: E402
    AppConfig,
    ApplicationContext,
    LaunchContext,
    LaunchSource,
    LoginResult,
    RuntimeConfig,
    RuntimeMode,
    StartupAction,
    StartupResult,
    get_runtime_features,
)
from app.utils.platform import CREATE_NO_WINDOW_FLAG, is_windows  # noqa: E402
from app.utils.process import (  # noqa: E402
    cleanup_pid,
    get_pid_file,
    get_process_name,
    is_local_port_in_use,
    is_service_running,
    normalize_proc_name,
    read_pid_file,
    read_pid_mode,
    write_pid,
)
from app.workers.playwright_bootstrap import ensure_playwright_ready  # noqa: E402
from app.workers.playwright_worker import cleanup_orphan_browsers  # noqa: E402
from app.services.profile_service import create_profile_service  # noqa: E402

# ==================== 浏览器控制 ====================


def _open_browser(port: int, setting: bool | None = None) -> None:
    """根据配置决定是否打开浏览器。setting=True 打开，False/None 不打开。"""
    if not setting:
        return

    def _worker():
        time.sleep(1.2)
        webbrowser.open(f"http://127.0.0.1:{port}")

    threading.Thread(target=_worker, daemon=True).start()


# ==================== CLI 命令 ====================


def _cmd_status() -> None:
    pid_file = get_pid_file()
    had_pid_file = pid_file.exists()
    running, pid = is_service_running()
    from app.utils.ports import resolve_port

    port = resolve_port()

    if running:
        mode = read_pid_mode()
        mode_str = f" [{mode}]" if mode else ""
        print(f"服务正在运行 (PID: {pid}){mode_str}")
    elif is_local_port_in_use(port):
        print(f"服务疑似正在运行 (端口: {port})")
    elif had_pid_file:
        # is_service_running() 清理了残留 PID 文件（进程已死或身份不匹配）
        print("服务未运行 (残留 PID 文件已清理)")
    else:
        print("服务未运行")


def _cmd_stop() -> None:
    running, pid = is_service_running()
    if not running or pid is None:
        print("服务未运行")
        return

    print(f"正在停止服务 (PID: {pid})...")
    try:
        _terminate_process(pid)
        # 验证进程已实际退出
        for _ in range(10):
            time.sleep(0.5)
            if not is_service_running()[0]:
                break
        print("服务已停止")
    except OSError:
        print("服务未运行")
    finally:
        cleanup_pid()


def _wait_for_exit(pid: int, max_wait: int = 5) -> bool:
    """等待进程退出，最多 max_wait 秒。

    Args:
        pid: 目标进程 PID。
        max_wait: 最大等待秒数。

    Returns:
        True 表示进程已退出，False 表示超时仍在运行。
    """
    for _ in range(max_wait):
        time.sleep(1)
        if get_process_name(pid) is None:
            return True
    return False


def _terminate_process(pid: int) -> None:
    """终止进程（先 SIGTERM，等待后 SIGKILL）。"""
    if is_windows():
        # Windows: 先尝试 taskkill（无 /F），等待后强制终止
        subprocess.run(
            ["taskkill", "/PID", str(pid)],
            capture_output=True,
            creationflags=CREATE_NO_WINDOW_FLAG,
        )
        if not _wait_for_exit(pid, max_wait=5):
            # 仍未退出，强制终止
            subprocess.run(
                ["taskkill", "/F", "/PID", str(pid)],
                capture_output=True,
                creationflags=CREATE_NO_WINDOW_FLAG,
            )
    else:
        os.kill(pid, signal.SIGTERM)
        if not _wait_for_exit(pid, max_wait=5):
            # SIGTERM 无效，使用 SIGKILL
            os.kill(pid, signal.SIGKILL)


def _cmd_autostart(action: str) -> None:
    from app.services.autostart import AutoStartService

    autostart = AutoStartService(project_root=Path(__file__).parent.resolve())

    if action == "status":
        status = autostart.status()
        print(f"平台: {status['platform']}")
        print(f"状态: {'已启用' if status['enabled'] else '未启用'}")
        print(f"方式: {status['method']}")
        print(f"位置: {status['location'] or '-'}")
    elif action == "enable":
        ok, msg = autostart.enable()
        print(msg)
        sys.exit(0 if ok else 1)
    elif action == "disable":
        ok, msg = autostart.disable()
        print(msg)
        sys.exit(0 if ok else 1)


# ==================== 自动登录，成功后退出 ====================


def _load_login_config(logger):
    """加载登录所需的运行时配置。

    Returns:
        (RuntimeConfig, None) — 成功时返回 RuntimeConfig 和 None。
        (None, LoginResult.CONFIG_ERROR) — 失败时返回 None 和错误结果。
    """
    ps = create_profile_service()
    runtime_config = ps.get_runtime_config()
    return runtime_config, None


def _execute_login_with_retries(runtime_config: RuntimeConfig, logger) -> LoginResult:
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
    from app.workers.playwright_worker import get_worker

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


def _run_login_then_exit(ctx: ApplicationContext, logger) -> LoginResult:
    """自动登录，成功后退出模式。

    返回:
        LoginResult.SUCCESS — 登录成功，应退出进程
        LoginResult.CONFIG_ERROR — 配置错误，应退出进程
        LoginResult.TEMPORARY_FAILURE — 临时失败，继续监控
    """
    # 加载配置
    try:
        runtime_config, error = _load_login_config(logger)
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

    return _execute_login_with_retries(runtime_config, logger)


# ==================== 启动辅助函数 ====================


def _build_app_config(
    cli_startup_action: str | None = None,
    cli_runtime_mode: str | None = None,
    cli_no_browser: bool = False,
    cli_browser: bool = False,
    cli_tray: bool = False,
    cli_no_tray: bool = False,
) -> AppConfig:
    """合并 Default → Settings → CLI 为最终 AppConfig"""
    from app.utils.logging import get_logger

    logger = get_logger("startup", source="backend")
    # 从 settings.json 加载
    try:
        _ps = create_profile_service()
        _data = _ps.load()
        config = AppConfig.from_runtime_config(_data.global_config)
    except Exception:
        logger.debug("加载配置失败，使用默认值", exc_info=True)
        config = AppConfig()

    # CLI 覆盖
    if cli_startup_action is not None:
        config.startup_action = StartupAction(cli_startup_action)
    if cli_runtime_mode is not None:
        config.runtime_mode = RuntimeMode(cli_runtime_mode)
    if cli_browser:
        config.auto_open_browser = True
    if cli_no_browser:
        config.auto_open_browser = False
    if cli_tray:
        config.minimize_to_tray = True
        config.lightweight_tray = True
    if cli_no_tray:
        config.minimize_to_tray = False
        config.lightweight_tray = False

    return config


def handle_startup_action(
    ctx: ApplicationContext, logger
) -> tuple[StartupResult, bool]:
    """第一层状态机：处理启动动作。返回 (结果, 是否需要启动监控引擎)。

    注意：should_boot_engine 仅用于完整模式。轻量模式始终自动启动监控。
    """
    match ctx.config.startup_action:
        case StartupAction.NONE:
            return StartupResult.CONTINUE, False
        case StartupAction.MONITOR:
            return StartupResult.CONTINUE, True
        case StartupAction.LOGIN_ONCE:
            result = _run_login_then_exit(ctx, logger)
            if result == LoginResult.SUCCESS:
                return StartupResult.EXIT, False
            if result == LoginResult.CONFIG_ERROR:
                # 配置错误无法自动恢复，退出让用户修正
                return StartupResult.EXIT, False
            # TEMPORARY_FAILURE → 网络等临时性问题，继续监控等待恢复
            return StartupResult.CONTINUE, True
        case _:
            return StartupResult.CONTINUE, False


def _handle_existing_instance(ctx: ApplicationContext, force: bool = False):
    """检测已运行实例，根据模式处理"""
    running, pid = is_service_running()
    if not running:
        return

    if force:
        print(f"强制模式：正在终止已运行的实例 (PID: {pid})...")
        _terminate_process(pid)
        cleanup_pid()
        print("已终止，继续启动...")
        return

    from app.utils.ports import resolve_port

    port = resolve_port()
    if ctx.config.runtime_mode == RuntimeMode.FULL:
        print(f"服务已运行 (PID: {pid})，正在打开 Web 控制台...")
        webbrowser.open(f"http://127.0.0.1:{port}")
    else:
        print(f"服务已运行 (PID: {pid})")
    sys.exit(0)


# ==================== 运行模式 ====================


def _create_tray(
    port: int,
    on_exit,
    on_open_console=None,
):
    """创建并启动系统托盘图标。

    Args:
        port: Web 服务端口，用于"打开控制台"的默认 URL。
        on_exit: 退出回调（无参数），通常为发送 SIGTERM 或 os._exit。
        on_open_console: 打开控制台回调（无参数）。
            轻量模式传入按需启动 Web 服务的回调；
            完整模式为 None（使用默认 webbrowser.open 行为）。

    Returns:
        SystemTray 实例（已 start），失败时返回 None。
    """
    try:
        from app.ui.system_tray import SystemTray

        tray_icon = SystemTray(
            port=port,
            on_exit=on_exit,
            on_open_console=on_open_console,
        )
        tray_icon.start()
        return tray_icon
    except Exception as e:
        from app.utils.logging import get_logger
        get_logger("startup", source="backend").warning(
            "启动系统托盘失败: {}", e
        )
        return None



def _run_lightweight(ctx: ApplicationContext, logger):
    """轻量模式：始终启动监控 + 定时任务，可选托盘，支持按需唤醒 WebUI。"""
    from app.container import ServiceContainer
    from app.utils.ports import resolve_port

    container = ServiceContainer(
        Path(__file__).parent.resolve(), mode="lightweight"
    )
    container.engine.boot()
    container.engine.sync_scheduler_state()
    logger.info("轻量模式启动: 仅监控 + 定时任务，按 Ctrl+C 停止")

    # Web 服务状态
    _web_server_lock = threading.Lock()
    _web_server_state = {"started": False, "server_ref": [None]}
    _web_server_shutdown_event = threading.Event()

    def _start_web_server():
        """按需启动 Web 服务（在子线程中运行）。"""
        with _web_server_lock:
            if _web_server_state["started"]:
                return
            _web_server_state["started"] = True

        def _worker():
            try:
                from app.application import run
                run(
                    existing_container=container,
                    server_ref=_web_server_state["server_ref"],
                )
            except Exception as e:
                logger.error("Web 服务启动失败: {}", e)
                _web_server_state["started"] = False
            finally:
                # Web 服务退出后通知主循环
                _web_server_shutdown_event.set()

        threading.Thread(target=_worker, daemon=True).start()

    def _open_console():
        """托盘回调：启动 Web 服务并打开浏览器。"""
        port = resolve_port()
        _start_web_server()
        # 等待服务就绪
        for _ in range(30):
            if is_local_port_in_use(port):
                break
            time.sleep(0.5)
        # BUG-059 修复：端口未就绪时不打开浏览器
        if is_local_port_in_use(port):
            webbrowser.open(f"http://127.0.0.1:{port}")
        else:
            logger.warning("Web 服务未在 15s 内就绪，跳过打开浏览器")

    # 系统托盘（可选）
    features = get_runtime_features(
        RuntimeMode.LIGHTWEIGHT,
        ctx.config.minimize_to_tray,
        ctx.config.auto_open_browser,
        ctx.config.lightweight_tray,
    )
    tray_icon = None
    if features.tray_enabled:
        port = resolve_port()
        tray_icon = _create_tray(
            port=port,
            on_exit=lambda: (
                os.kill(os.getpid(), signal.SIGTERM) if hasattr(signal, "SIGTERM") else os._exit(0)
            ),
            on_open_console=_open_console,
        )
        if tray_icon:
            logger.info("系统托盘已启动")

    try:
        while True:
            # 等待 web 服务关闭事件或 60 秒超时
            if _web_server_shutdown_event.wait(timeout=60):
                logger.info("Web 服务已退出，轻量模式即将关闭")
                break
    except KeyboardInterrupt:
        logger.info("收到退出信号，正在关闭服务...")
    finally:
        if tray_icon:
            tray_icon.stop()
        # BUG-009/032 修复：无论 Web 服务状态如何，强制执行 container.shutdown()
        # 容器已有 _shutdown_done 守卫保证幂等性
        try:
            asyncio.run(asyncio.wait_for(container.shutdown(), timeout=5))
        except RuntimeError:
            # 无可用 event loop，跳过异步 shutdown
            container.task_executor.shutdown(wait=False)
            container.engine.shutdown()
        except KeyboardInterrupt:
            # asyncio.run 在信号处理上下文中可能重新抛出 KeyboardInterrupt
            logger.debug("容器关闭被信号中断")
        except Exception:
            logger.debug("容器关闭（幂等跳过或超时）")
        cleanup_pid()
        os._exit(0)


def _run_full(
    ctx: ApplicationContext, should_boot_engine: bool, logger, startup_begin: float
):
    """完整模式：Web 服务 + 监控 + 定时任务"""
    from app.application import run
    from app.container import ServiceContainer
    from app.utils.ports import resolve_port

    port = resolve_port()
    container = ServiceContainer(Path(__file__).parent.resolve())

    features = get_runtime_features(
        RuntimeMode.FULL,
        ctx.config.minimize_to_tray,
        ctx.config.auto_open_browser,
    )

    # 信号处理器
    _uvicorn_server = [None]
    _shutdown_initiated = False

    def _signal_handler(signum, _frame):
        nonlocal _shutdown_initiated
        if _shutdown_initiated:
            # 双击 Ctrl+C：强制退出（cleanup_pid 在首次信号时已完成）
            cleanup_pid()
            os._exit(1)
        _shutdown_initiated = True
        logger.info("收到退出信号，正在关闭服务...")
        cleanup_pid()
        if _uvicorn_server[0] is not None:
            _uvicorn_server[0].should_exit = True
        else:
            # uvicorn 未就绪，PID 已清理，直接退出
            os._exit(0)

    signal.signal(signal.SIGINT, _signal_handler)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _signal_handler)

    # 系统托盘
    tray_icon = None
    if features.tray_enabled:
        tray_icon = _create_tray(
            port=port,
            on_exit=lambda: (
                os.kill(os.getpid(), signal.SIGTERM) if hasattr(signal, "SIGTERM") else os._exit(0)
            ),
        )
        if tray_icon:
            logger.info("系统托盘已启动，双击图标打开控制台")

    if features.browser_enabled:
        _open_browser(port, setting=True)

    logger.info("Web 控制台: http://127.0.0.1:{}", port)
    logger.info(
        "启动准备完成，耗时 {:.3f}s，正在启动 Uvicorn",
        time.perf_counter() - startup_begin,
    )

    try:
        try:
            _ps = create_profile_service()
            _data = _ps.load()
            _logging = _data.global_config.logging
            _al = bool(_logging.access_log)
            _lr = max(1, int(_logging.log_retention_days))
        except (AttributeError, TypeError, ValueError):
            _data = None
            _al, _lr = False, 7

        run(
            access_log_enabled=_al,
            log_retention=_lr,
            existing_container=container,
            server_ref=_uvicorn_server,
            boot_engine=should_boot_engine,
            logging_settings=_logging if _data else None,
        )
    except KeyboardInterrupt:
        logger.info("收到退出信号，正在关闭服务...")
    finally:
        if tray_icon:
            tray_icon.stop()
        # lifespan 通常已执行 shutdown，此处为防御性补调（幂等安全）
        try:
            asyncio.run(asyncio.wait_for(container.shutdown(), timeout=5))
        except Exception:
            logger.debug("容器关闭（幂等跳过或超时）")
        cleanup_pid()
        os._exit(0)


# ==================== 主启动 ====================


def _run_server(ctx: ApplicationContext, force: bool = False) -> None:
    """主启动流程：两层正交状态机（StartupAction → RuntimeMode）"""
    from app.utils.logging import get_logger

    startup_logger = get_logger("startup", source="backend")
    startup_begin = time.perf_counter()

    # 检测已运行实例
    _handle_existing_instance(ctx, force=force)

    # Playwright 检查
    stage_begin = time.perf_counter()
    startup_logger.info("正在检查 Playwright 环境")

    def _log_playwright_ready(msg: str):
        startup_logger.info(msg)

    ensure_playwright_ready(_log_playwright_ready)
    startup_logger.info(
        "Playwright 环境检查完成 ({:.3f}s)",
        time.perf_counter() - stage_begin,
    )

    # BUG-040 修复：在 Playwright 安装完成后再写入 PID 文件
    write_pid(ctx.config.runtime_mode.value)
    atexit.register(cleanup_pid)

    # 启动摘要
    _label = {"manual": "手动", "autostart": "自启动"}
    startup_logger.info(
        "启动摘要: 来源={}, 动作={}, 模式={}, 托盘={}, 浏览器={}",
        _label.get(ctx.launch.source.value, ctx.launch.source.value),
        ctx.config.startup_action.value,
        ctx.config.runtime_mode.value,
        ctx.config.minimize_to_tray,
        ctx.config.auto_open_browser,
    )

    # 第一层：启动动作
    result, should_boot_engine = handle_startup_action(ctx, startup_logger)
    if result == StartupResult.EXIT:
        cleanup_pid()
        return

    # 第二层：运行模式
    if ctx.config.runtime_mode == RuntimeMode.LIGHTWEIGHT:
        _run_lightweight(ctx, startup_logger)
    else:
        _run_full(ctx, should_boot_engine, startup_logger, startup_begin)


# ==================== 全局异常钩子 ====================


def _setup_exception_hooks() -> None:
    """设置全局异常钩子，确保线程内未捕获异常被记录到日志。"""
    from app.utils.logging import get_logger

    _hook_logger = get_logger("uncaught", source="backend")

    def _threading_excepthook(args: threading.ExceptHookArgs) -> None:
        _hook_logger.error(
            "线程 %s 未捕获异常",
            args.thread.name if args.thread else "unknown",
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )

    threading.excepthook = _threading_excepthook


# ==================== 入口 ====================


def main() -> None:
    _setup_exception_hooks()

    parser = argparse.ArgumentParser(
        description="Campus-Auth 校园网自动认证",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""常用示例:
  python main.py                              启动 Web 控制台
  python main.py --runtime-mode lightweight   轻量模式（无 Web 界面，覆盖自启动模式）
  python main.py --startup-action monitor     启动后自动开始监控
  python main.py --startup-action login_once  自动登录，成功后退出
  python main.py --no-browser                 不自动打开浏览器
  python main.py --status                     查看运行状态
  python main.py --stop                       停止后台服务
  python main.py --autostart                  查看开机自启动状态
  python main.py --autostart enable           启用开机自启动""",
    )

    parser.add_argument(
        "--startup-action",
        choices=["none", "monitor", "login_once"],
        default=None,
        help="覆盖启动动作",
    )
    parser.add_argument(
        "--runtime-mode",
        choices=["full", "lightweight"],
        default=None,
        help="覆盖自启动运行模式（手动启动时始终为 full）",
    )
    parser.add_argument("--browser", action="store_true", help="自动打开浏览器")
    parser.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    parser.add_argument("--tray", action="store_true", help="最小化到系统托盘")
    parser.add_argument("--force", action="store_true", help="强制启动，清理残留 PID 文件")
    parser.add_argument("--no-tray", action="store_true", help="不最小化到系统托盘")
    parser.add_argument("--status", action="store_true", help="查看服务状态")
    parser.add_argument("--stop", action="store_true", help="停止服务")
    parser.add_argument(
        "--autostart",
        nargs="?",
        const="status",
        default=None,
        choices=["status", "enable", "disable"],
        help="管理开机自启动 (status/enable/disable)",
    )
    parser.add_argument(
        "--source",
        choices=["manual", "autostart"],
        default="manual",
        help=argparse.SUPPRESS,
    )
    args = parser.parse_args()

    # 互斥参数检测
    if args.browser and args.no_browser:
        parser.error("--browser 和 --no-browser 不能同时使用")
    if args.tray and args.no_tray:
        parser.error("--tray 和 --no-tray 不能同时使用")

    # CLI 命令
    if args.status:
        _cmd_status()
        return

    if args.stop:
        _cmd_stop()
        return

    if args.autostart:
        _cmd_autostart(args.autostart)
        return

    # 构建配置和上下文
    config = _build_app_config(
        cli_startup_action=args.startup_action,
        cli_runtime_mode=args.runtime_mode,
        cli_no_browser=args.no_browser,
        cli_browser=args.browser,
        cli_tray=args.tray,
        cli_no_tray=args.no_tray,
    )
    launch_ctx = LaunchContext(source=LaunchSource(args.source))
    ctx = ApplicationContext(config=config, launch=launch_ctx)

    _run_server(ctx, force=args.force)


if __name__ == "__main__":
    main()
