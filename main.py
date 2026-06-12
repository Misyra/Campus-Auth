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
    RuntimeMode,
    StartupAction,
    StartupResult,
    get_runtime_features,
)
from app.utils.platform import is_windows  # noqa: E402
from app.utils.process import (  # noqa: E402
    cleanup_pid,
    get_pid_file,
    get_process_name,
    is_local_port_in_use,
    is_service_running,
    normalize_proc_name,
    read_pid_file,
    write_pid,
)
from app.workers.playwright_bootstrap import ensure_playwright_ready  # noqa: E402
from app.workers.playwright_worker import cleanup_orphan_browsers  # noqa: E402

# ==================== 浏览器控制 ====================


def _open_browser(port: int, setting: bool | None = None) -> None:
    """根据配置决定是否打开浏览器。setting=True 打开，False/None 不打开。"""
    if setting is not None and not setting:
        return
    if setting is None:
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
        print(f"服务正在运行 (PID: {pid})")
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

    # 进程身份验证：新格式 PID 文件中记录的进程名必须匹配实际运行进程
    stored_pid, proc_name, _ = read_pid_file()
    if proc_name is not None:
        actual_name = get_process_name(pid)
        if actual_name is None or normalize_proc_name(
            actual_name
        ) != normalize_proc_name(proc_name):
            print(
                f"警告: PID 文件记录的进程名 '{proc_name}' 与实际进程 "
                f"'{actual_name or 'N/A'}' 不匹配，跳过停服操作"
            )
            cleanup_pid()
            return

    try:
        print(f"正在停止服务 (PID: {pid})...")
        if is_windows():
            # Windows: 直接使用 taskkill /F 强制终止（taskkill 无 /F 对控制台程序无效）
            subprocess.run(
                ["taskkill", "/F", "/PID", str(pid)],
                capture_output=True,
                creationflags=subprocess.CREATE_NO_WINDOW
                if hasattr(subprocess, "CREATE_NO_WINDOW")
                else 0,
            )
        else:
            os.kill(pid, signal.SIGTERM)
            # 等待进程退出
            for _ in range(10):
                time.sleep(1)
                try:
                    os.kill(pid, 0)
                except OSError:
                    print("服务已停止")
                    cleanup_pid()
                    return
            # SIGTERM 无效，使用 SIGKILL
            os.kill(pid, signal.SIGKILL)
        print("服务已停止")
    except OSError:
        print("服务未运行")
    finally:
        cleanup_pid()


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


# ==================== 登录成功后退出 ====================


def _run_login_then_exit(ctx: ApplicationContext, logger) -> bool:
    """登录成功后退出模式。成功返回 True，失败返回 False。"""
    from app.workers.playwright_worker import CMD_LOGIN, get_worker

    # 加载配置
    try:
        from app.services.config_service import (
            build_runtime_config,
            load_runtime_config,
        )
        from app.services.profile_service import ProfileService

        ps = ProfileService(Path(__file__).parent.resolve())
        data = ps.load()
        payload, has_decrypt_error = load_runtime_config(ps)
        if has_decrypt_error:
            print("警告: 部分密码解密失败，可能需要重新配置密码")
        runtime_config = build_runtime_config(payload, data.system)
    except Exception as exc:
        print(f"加载配置失败: {exc}")
        return False

    # 先检测网络状态，已连接则无需登录
    try:
        from app.network.decision import check_network_status

        network_ok, reason = check_network_status(runtime_config)
        if network_ok:
            print("网络已连接，无需登录，正在退出...")
            return True
        print(f"网络未连接 ({reason})，开始登录...")
    except Exception as exc:
        logger.debug("网络检测异常，继续尝试登录: {}", exc)
        print("网络检测异常，开始登录...")

    retry_settings = runtime_config.get("retry_settings", {})
    raw = retry_settings.get("max_retries", 3)
    max_retries = max(1, min(raw, 10))
    retry_interval = int(retry_settings.get("retry_interval", 5))

    attempt = 0
    while True:
        attempt += 1
        # 指数退避：首次间隔 0，后续 interval × 2^(attempt-2)
        if attempt > 1:
            delay = retry_interval * (2 ** (attempt - 2))
            print(f"等待 {delay} 秒后重试第 {attempt} 次...")
            time.sleep(delay)

        success = False
        message = ""
        try:
            result = get_worker().submit(
                CMD_LOGIN,
                data={"config": runtime_config, "skip_pause_check": True},
                timeout=120,
            )
            success = result.success
            message = result.data if result.success else result.error or "登录失败"
        except Exception as exc:
            message = f"登录异常: {exc}"

        if success:
            print(f"登录成功: {message}")
            cleanup_orphan_browsers()
            return True

        print(f"登录失败 (第 {attempt} 次): {message}")
        if max_retries > 0 and attempt >= max_retries:
            break

    cleanup_orphan_browsers()
    print(f"已重试 {max_retries} 次均失败，回退到正常模式")
    logger.warning("login_once 登录失败（已重试 {} 次），回退到正常模式", max_retries)
    return False


# ==================== 启动辅助函数 ====================


def _detect_launch_context() -> LaunchContext:
    """检测启动来源（仅用于日志和 UI 体验，不参与业务逻辑）"""
    source = (
        LaunchSource.AUTOSTART
        if os.environ.get("CAMPUS_AUTH_AUTOSTART") == "1"
        else LaunchSource.MANUAL
    )
    return LaunchContext(source=source)


def _build_app_config(
    cli_startup_action: str | None = None,
    cli_runtime_mode: str | None = None,
    cli_no_browser: bool = False,
    cli_browser: bool = False,
    cli_tray: bool = False,
    cli_no_tray: bool = False,
) -> AppConfig:
    """合并 Default → Settings → CLI 为最终 AppConfig"""
    config = AppConfig()

    # 从 settings.json 加载
    try:
        from app.services.profile_service import ProfileService
        _ps = ProfileService(Path(__file__).parent.resolve())
        _data = _ps.load()
        _sys = _data.system
        config.startup_action = StartupAction(getattr(_sys, "startup_action", "none"))
        config.runtime_mode = RuntimeMode(getattr(_sys, "runtime_mode", "full"))
        config.minimize_to_tray = bool(getattr(_sys, "minimize_to_tray", True))
        config.auto_open_browser = bool(getattr(_sys, "auto_open_browser", False))
    except Exception:
        pass  # 使用默认值

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
    if cli_no_tray:
        config.minimize_to_tray = False

    return config


def handle_startup_action(ctx: ApplicationContext, logger) -> tuple[StartupResult, bool]:
    """第一层状态机：处理启动动作。返回 (结果, 是否需要启动监控引擎)"""
    match ctx.config.startup_action:
        case StartupAction.NONE:
            return StartupResult.CONTINUE, False
        case StartupAction.MONITOR:
            return StartupResult.CONTINUE, True
        case StartupAction.LOGIN_ONCE:
            success = _run_login_then_exit(ctx, logger)
            if success:
                return StartupResult.EXIT, False
            return StartupResult.CONTINUE, False
        case _:
            return StartupResult.CONTINUE, False


def _handle_existing_instance(ctx: ApplicationContext):
    """检测已运行实例，根据模式处理"""
    running, pid = is_service_running()
    if not running:
        return
    from app.utils.ports import resolve_port
    port = resolve_port()
    match ctx.config.runtime_mode:
        case RuntimeMode.FULL:
            print(f"服务已运行 (PID: {pid})，正在打开 Web 控制台...")
            webbrowser.open(f"http://127.0.0.1:{port}")
        case RuntimeMode.LIGHTWEIGHT:
            print(f"服务已运行 (PID: {pid})")
    sys.exit(0)


# ==================== 运行模式 ====================


_shutdown_event = threading.Event()


def _wait_for_shutdown():
    """阻塞等待关闭信号"""
    _shutdown_event.wait()


def _run_lightweight(ctx: ApplicationContext, logger):
    """轻量模式：仅监控 + 定时任务，无 Web 服务"""
    from app.container import ServiceContainer

    container = ServiceContainer(Path(__file__).parent.resolve())
    container.engine.boot()
    if container.engine.has_enabled_tasks():
        container.engine.start_scheduler()
    logger.info("轻量模式启动: 仅监控 + 定时任务")

    # 信号处理器
    def _signal_handler(signum, _frame):
        _shutdown_event.set()
        logger.info("收到退出信号，正在关闭...")
        cleanup_pid()

    signal.signal(signal.SIGINT, _signal_handler)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _signal_handler)

    # 系统托盘
    tray_icon = None
    features = get_runtime_features(ctx.config.runtime_mode, ctx.config.minimize_to_tray, ctx.config.auto_open_browser)
    if features.tray_enabled:
        try:
            from app.ui.system_tray import SystemTray
            tray_icon = SystemTray(
                port=0,
                on_exit=lambda: os.kill(os.getpid(), signal.SIGTERM)
                if hasattr(signal, "SIGTERM")
                else cleanup_pid() or os._exit(0),
            )
            tray_icon.start()
        except Exception as e:
            logger.warning("启动系统托盘失败: {}", e)

    _wait_for_shutdown()

    if tray_icon:
        tray_icon.stop()
    logger.info("正在关闭服务...")
    loop = asyncio.new_event_loop()
    loop.run_until_complete(container.shutdown())
    loop.close()


def _run_full(ctx: ApplicationContext, should_boot_engine: bool, logger, startup_begin: float):
    """完整模式：Web 服务 + 监控 + 定时任务"""
    from app.application import run
    from app.container import ServiceContainer
    from app.utils.ports import resolve_port

    port = resolve_port()
    container = ServiceContainer(Path(__file__).parent.resolve())

    if should_boot_engine:
        container.engine.boot()

    features = get_runtime_features(ctx.config.runtime_mode, ctx.config.minimize_to_tray, ctx.config.auto_open_browser)

    # 信号处理器
    _uvicorn_server = [None]
    _shutdown_initiated = False

    def _signal_handler(signum, _frame):
        nonlocal _shutdown_initiated
        if _shutdown_initiated:
            cleanup_pid()
            os._exit(1)
        _shutdown_initiated = True
        logger.info("收到退出信号，正在关闭...")
        cleanup_pid()
        if _uvicorn_server[0] is not None:
            _uvicorn_server[0].should_exit = True
        else:
            os._exit(0)

    signal.signal(signal.SIGINT, _signal_handler)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _signal_handler)

    # 系统托盘
    tray_icon = None
    if features.tray_enabled:
        try:
            from app.ui.system_tray import SystemTray
            tray_icon = SystemTray(
                port=port,
                on_exit=lambda: os.kill(os.getpid(), signal.SIGTERM)
                if hasattr(signal, "SIGTERM")
                else cleanup_pid() or os._exit(0),
            )
            tray_icon.start()
            logger.info("系统托盘已启动，双击图标打开控制台")
        except Exception as e:
            logger.warning("启动系统托盘失败: {}", e)

    if features.browser_enabled:
        _open_browser(port, setting=True)

    logger.info("Web 控制台: http://127.0.0.1:{}", port)
    logger.info("日志文件:   {}", Path.cwd() / "logs")
    logger.info("按 Ctrl+C 停止服务")
    logger.info(
        "启动阶段: 启动准备完成，总耗时 {:.3f}s，开始启动 Uvicorn",
        time.perf_counter() - startup_begin,
    )

    try:
        try:
            from app.services.profile_service import ProfileService
            _ps = ProfileService(Path(__file__).parent.resolve())
            _sys = _ps.load().system
            _al = bool(_sys.access_log)
            _lr = max(1, int(_sys.log_retention_days))
        except (AttributeError, TypeError, ValueError):
            _al, _lr = False, 7

        run(
            access_log_enabled=_al,
            log_retention=_lr,
            existing_container=container,
            server_ref=_uvicorn_server,
        )
    except KeyboardInterrupt:
        logger.info("收到退出信号，正在关闭...")
    finally:
        if tray_icon:
            tray_icon.stop()

    logger.info("正在关闭服务...")
    loop = asyncio.new_event_loop()
    loop.run_until_complete(container.shutdown())
    loop.close()


# ==================== 主启动 ====================


def _run_server(ctx: ApplicationContext) -> None:
    """主启动流程：两层正交状态机（StartupAction → RuntimeMode）"""
    from app.utils.logging import get_logger

    startup_logger = get_logger("startup", source="backend")
    startup_begin = time.perf_counter()

    # 检测已运行实例
    _handle_existing_instance(ctx)

    write_pid()
    atexit.register(cleanup_pid)

    # Playwright 检查
    stage_begin = time.perf_counter()
    startup_logger.info("启动阶段: 开始检查 Playwright 运行环境")
    ensure_playwright_ready(print)
    startup_logger.info(
        "启动阶段: Playwright 检查完成，耗时 {:.3f}s",
        time.perf_counter() - stage_begin,
    )

    startup_logger.info(
        "启动来源: {}, 启动动作: {}, 运行模式: {}",
        ctx.launch.source.value,
        ctx.config.startup_action.value,
        ctx.config.runtime_mode.value,
    )

    # 第一层：启动动作
    result, should_boot_engine = handle_startup_action(ctx, startup_logger)
    if result == StartupResult.EXIT:
        cleanup_pid()
        return

    # 第二层：运行模式
    match ctx.config.runtime_mode:
        case RuntimeMode.LIGHTWEIGHT:
            _run_lightweight(ctx, startup_logger)
        case _:
            _run_full(ctx, should_boot_engine, startup_logger, startup_begin)


# ==================== 全局异常钩子 ====================


def _setup_exception_hooks() -> None:
    """设置全局异常钩子，确保线程内未捕获异常被记录到日志。"""
    import threading

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
  python main.py --runtime-mode lightweight   轻量模式（无 Web 界面）
  python main.py --startup-action monitor     启动后自动开始监控
  python main.py --startup-action login_once  登录成功后退出
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
        help="覆盖运行模式",
    )
    parser.add_argument("--browser", action="store_true", help="自动打开浏览器")
    parser.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    parser.add_argument("--tray", action="store_true", help="最小化到系统托盘")
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
    launch_ctx = _detect_launch_context()
    ctx = ApplicationContext(config=config, launch=launch_ctx)

    _run_server(ctx)


if __name__ == "__main__":
    main()
