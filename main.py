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
        print("服务已停止")
    except OSError:
        print("服务未运行")
    finally:
        cleanup_pid()


def _terminate_process(pid: int) -> None:
    """终止进程（先 SIGTERM，等待后 SIGKILL）。"""
    if is_windows():
        # Windows: 先尝试 taskkill（无 /F），等待后强制终止
        subprocess.run(
            ["taskkill", "/PID", str(pid)],
            capture_output=True,
            creationflags=CREATE_NO_WINDOW_FLAG,
        )
        # 等待进程退出
        for _ in range(5):
            time.sleep(1)
            if get_process_name(pid) is None:
                return
        # 仍未退出，强制终止
        subprocess.run(
            ["taskkill", "/F", "/PID", str(pid)],
            capture_output=True,
            creationflags=CREATE_NO_WINDOW_FLAG,
        )
    else:
        os.kill(pid, signal.SIGTERM)
        # 等待进程退出
        for _ in range(5):
            time.sleep(1)
            try:
                os.kill(pid, 0)
            except OSError:
                return
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


def _run_login_then_exit(ctx: ApplicationContext, logger) -> LoginResult:
    """自动登录，成功后退出模式。

    返回:
        LoginResult.SUCCESS — 登录成功，应退出进程
        LoginResult.CONFIG_ERROR — 配置错误，应退出进程
        LoginResult.TEMPORARY_FAILURE — 临时失败，继续监控
    """
    from app.workers.playwright_worker import CMD_LOGIN, get_worker

    # 加载配置
    try:
        from app.services.config_service import build_runtime_config
        from app.services.runtime_config import load_runtime_config
        from app.services.profile_service import ProfileService

        ps = ProfileService(Path(__file__).parent.resolve())
        data = ps.load()
        payload, has_decrypt_error = load_runtime_config(ps)
        if has_decrypt_error:
            logger.warning("密码解密失败，请检查配置")
            return LoginResult.CONFIG_ERROR
        runtime_config = build_runtime_config(payload, global_settings=data.global_settings)
    except Exception as exc:
        logger.error("加载配置失败: {}", exc)
        return LoginResult.CONFIG_ERROR

    # 先检测网络状态，已连接则无需登录
    try:
        from app.network.decision import check_network_status

        network_ok, reason = check_network_status(runtime_config)
        if network_ok:
            print("网络已连接，无需登录，正在退出...")
            return LoginResult.SUCCESS
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
            delay = min(retry_interval * (2 ** (attempt - 2)), 300)
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
            return LoginResult.SUCCESS

        print(f"登录失败 (第 {attempt} 次): {message}")
        if attempt >= max_retries:
            break

    cleanup_orphan_browsers()
    print(f"已重试 {max_retries} 次均失败，回退到正常模式")
    logger.warning("登录失败（已重试 {} 次），回退到正常模式", max_retries)
    return LoginResult.TEMPORARY_FAILURE


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
    config = AppConfig()

    # 从 settings.json 加载
    try:
        from app.services.profile_service import ProfileService

        _ps = ProfileService(Path(__file__).parent.resolve())
        _data = _ps.load()
        _sys = _data.global_settings
        config.startup_action = StartupAction(getattr(_sys, "startup_action", "none"))
        config.minimize_to_tray = bool(getattr(_sys, "minimize_to_tray", True))
        config.auto_open_browser = bool(getattr(_sys, "auto_open_browser", False))
    except Exception:
        logger.debug("加载配置失败，使用默认值", exc_info=True)

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
            return StartupResult.CONTINUE, False
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



def _run_lightweight(ctx: ApplicationContext, logger):
    """轻量模式：始终启动监控 + 定时任务，无 Web 服务、无托盘。"""
    from app.container import ServiceContainer

    container = ServiceContainer(
        Path(__file__).parent.resolve(), mode="lightweight"
    )
    container.engine.boot()
    if container.engine.has_enabled_tasks():
        container.engine.start_scheduler()
    logger.info("轻量模式启动: 仅监控 + 定时任务，按 Ctrl+C 停止")

    try:
        while True:
            time.sleep(60)  # 长间隔等待，可被 Ctrl+C 中断
    except KeyboardInterrupt:
        logger.info("收到退出信号，正在关闭服务...")
    finally:
        loop = asyncio.new_event_loop()
        loop.run_until_complete(container.shutdown())
        loop.close()


def _run_full(
    ctx: ApplicationContext, should_boot_engine: bool, logger, startup_begin: float
):
    """完整模式：Web 服务 + 监控 + 定时任务"""
    from app.application import run
    from app.container import ServiceContainer
    from app.utils.ports import resolve_port

    port = resolve_port()
    container = ServiceContainer(Path(__file__).parent.resolve())

    if should_boot_engine:
        container.engine.boot()

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
        try:
            from app.ui.system_tray import SystemTray

            tray_icon = SystemTray(
                port=port,
                on_exit=lambda: (
                    os.kill(os.getpid(), signal.SIGTERM) if hasattr(signal, "SIGTERM") else os._exit(0)
                ),
            )
            tray_icon.start()
            logger.info("系统托盘已启动，双击图标打开控制台")
        except Exception as e:
            logger.warning("启动系统托盘失败: {}", e)

    if features.browser_enabled:
        _open_browser(port, setting=True)

    logger.info("Web 控制台: http://127.0.0.1:{}", port)
    logger.info(
        "启动准备完成，耗时 {:.3f}s，正在启动 Uvicorn",
        time.perf_counter() - startup_begin,
    )

    try:
        try:
            from app.services.profile_service import ProfileService

            _ps = ProfileService(Path(__file__).parent.resolve())
            _sys = _ps.load().global_settings
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
        logger.info("收到退出信号，正在关闭服务...")
    finally:
        if tray_icon:
            tray_icon.stop()
    # container.shutdown() 由 lifespan 管理，此处不再重复调用


# ==================== 主启动 ====================


def _run_server(ctx: ApplicationContext, force: bool = False) -> None:
    """主启动流程：两层正交状态机（StartupAction → RuntimeMode）"""
    from app.utils.logging import get_logger

    startup_logger = get_logger("startup", source="backend")
    startup_begin = time.perf_counter()

    # 检测已运行实例
    _handle_existing_instance(ctx, force=force)

    write_pid(ctx.config.runtime_mode.value)
    atexit.register(cleanup_pid)

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
