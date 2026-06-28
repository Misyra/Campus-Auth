"""launcher — 启动器（从 main.py 提取）。"""

from __future__ import annotations

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
from typing import TYPE_CHECKING

import psutil

from app.schemas import (
    ApplicationContext,
    LaunchContext,
    LaunchSource,
    LoginResult,
    RuntimeMode,
    StartupAction,
    StartupResult,
    get_runtime_features,
)
from app.utils.platform import CREATE_NO_WINDOW_FLAG, is_windows
from app.utils.process import (
    cleanup_pid,
    is_local_port_in_use,
    is_service_running,
    read_pid_mode,
    write_pid,
)
from app.utils.shutdown import force_exit

if TYPE_CHECKING:
    pass


# ==================== 内部辅助函数 ====================


def _wait_for_exit(pid: int, max_wait: int = 5) -> bool:
    """等待进程退出，最多 max_wait 秒。

    Args:
        pid: 目标进程 PID。
        max_wait: 最大等待秒数。

    Returns:
        True 表示进程已退出，False 表示超时仍在运行。
    """
    try:
        proc = psutil.Process(pid)
        proc.wait(timeout=max_wait)
        return True
    except psutil.TimeoutExpired:
        return False
    except psutil.NoSuchProcess:
        return True


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


# ==================== 公共 API ====================


def shutdown_container(container, logger, fallback_shutdown: bool = False) -> None:
    """统一关闭容器（幂等安全）。

    Args:
        container: ServiceContainer 实例。
        logger: 日志记录器。
        fallback_shutdown: 当 asyncio.run 失败时是否使用同步降级关闭。
            lightweight 模式为 True（无 uvicorn lifespan 兜底），
            full 模式为 False（lifespan 通常已执行 shutdown）。
    """
    try:
        asyncio.run(asyncio.wait_for(container.shutdown(), timeout=5))
    except RuntimeError:
        if fallback_shutdown:
            container.task_executor.shutdown(wait=False)
            container.engine.shutdown()
        else:
            logger.debug("容器关闭（幂等跳过或超时）")
    except KeyboardInterrupt:
        logger.debug("容器关闭被信号中断")
    except Exception:
        logger.debug("容器关闭（幂等跳过或超时）")


def open_browser(port: int, setting: bool | None = None) -> None:
    """根据配置决定是否打开浏览器。setting=True 打开，False/None 不打开。"""
    if not setting:
        return

    def _worker():
        time.sleep(1.2)
        webbrowser.open(f"http://127.0.0.1:{port}")

    threading.Thread(target=_worker, daemon=True).start()


def create_tray(
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
        from app.system_tray import SystemTray

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


def handle_startup_action(
    ctx: ApplicationContext, logger
) -> tuple[StartupResult, bool]:
    """第一层状态机：处理启动动作。返回 (结果, 是否需要启动监控引擎)。

    注意：should_boot_engine 仅用于完整模式。轻量模式始终自动启动监控。
    """
    from app.services.login_runner import run_login_then_exit

    match ctx.config.startup_action:
        case StartupAction.NONE:
            return StartupResult.CONTINUE, False
        case StartupAction.MONITOR:
            return StartupResult.CONTINUE, True
        case StartupAction.LOGIN_ONCE:
            result = run_login_then_exit(ctx, logger)
            if result == LoginResult.SUCCESS:
                return StartupResult.EXIT, False
            if result == LoginResult.CONFIG_ERROR:
                # 配置错误无法自动恢复，退出让用户修正
                return StartupResult.EXIT, False
            # TEMPORARY_FAILURE → 网络等临时性问题，继续监控等待恢复
            return StartupResult.CONTINUE, True
        case _:
            return StartupResult.CONTINUE, False


def handle_existing_instance(ctx: ApplicationContext, force: bool = False):
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


def _start_web_server(
    container,
    logger,
    _web_server_lock,
    _web_server_state,
    _web_server_shutdown_event,
):
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


def _open_console(
    container,
    logger,
    _web_server_lock,
    _web_server_state,
    _web_server_shutdown_event,
):
    """托盘回调：启动 Web 服务并打开浏览器。"""
    from app.utils.ports import resolve_port

    port = resolve_port()
    _start_web_server(
        container,
        logger,
        _web_server_lock,
        _web_server_state,
        _web_server_shutdown_event,
    )
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


def launch_lightweight(ctx: ApplicationContext, logger):
    """轻量模式：始终启动监控 + 定时任务，可选托盘，支持按需唤醒 WebUI。"""
    from app.container import ServiceContainer
    from app.utils.ports import resolve_port

    container = ServiceContainer(
        Path(__file__).parent.parent.parent.resolve(), mode="lightweight"
    )
    container.engine.boot()
    container.engine.sync_scheduler_state()
    logger.info("轻量模式启动: 仅监控 + 定时任务，按 Ctrl+C 停止")

    # Web 服务状态
    _web_server_lock = threading.Lock()
    _web_server_state = {"started": False, "server_ref": [None]}
    _web_server_shutdown_event = threading.Event()

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
        tray_icon = create_tray(
            port=port,
            on_exit=lambda: (
                os.kill(os.getpid(), signal.SIGTERM) if hasattr(signal, "SIGTERM") else os._exit(0)
            ),
            on_open_console=lambda: _open_console(
                container,
                logger,
                _web_server_lock,
                _web_server_state,
                _web_server_shutdown_event,
            ),
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
        shutdown_container(container, logger, fallback_shutdown=True)
        cleanup_pid()
        # daemon 线程（web server worker）阻止自然退出，强制退出
        force_exit(0)


def launch_full(
    ctx: ApplicationContext, should_boot_engine: bool, logger, startup_begin: float
):
    """完整模式：Web 服务 + 监控 + 定时任务"""
    from app.application import run
    from app.container import ServiceContainer
    from app.utils.ports import resolve_port

    port = resolve_port()
    container = ServiceContainer(Path(__file__).parent.parent.parent.resolve())

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
            # 用户双击 Ctrl+C 紧急退出 — 绕过所有清理，立即退出
            os._exit(1)
        _shutdown_initiated = True
        logger.info("收到退出信号，正在关闭服务...")
        cleanup_pid()
        if _uvicorn_server[0] is not None:
            _uvicorn_server[0].should_exit = True
        else:
            # uvicorn 未就绪，PID 已清理，强制退出
            force_exit(0)

    signal.signal(signal.SIGINT, _signal_handler)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _signal_handler)

    # 系统托盘
    tray_icon = None
    if features.tray_enabled:
        tray_icon = create_tray(
            port=port,
            on_exit=lambda: (
                os.kill(os.getpid(), signal.SIGTERM) if hasattr(signal, "SIGTERM") else os._exit(0)
            ),
        )
        if tray_icon:
            logger.info("系统托盘已启动，双击图标打开控制台")

    if features.browser_enabled:
        open_browser(port, setting=True)

    logger.info("Web 控制台: http://127.0.0.1:{}", port)
    logger.info(
        "启动准备完成，耗时 {:.3f}s，正在启动 Uvicorn",
        time.perf_counter() - startup_begin,
    )

    try:
        try:
            _data = container.profile_service.load()
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
        shutdown_container(container, logger)
        cleanup_pid()
        # uvicorn 已退出但 daemon 线程可能存活，强制退出
        force_exit(0)


# ==================== 主启动 ====================


def launch_server(ctx: ApplicationContext, force: bool = False) -> None:
    """主启动流程：两层正交状态机（StartupAction → RuntimeMode）"""
    from app.utils.logging import get_logger
    from app.workers.playwright_bootstrap import ensure_playwright_ready

    startup_logger = get_logger("startup", source="backend")
    startup_begin = time.perf_counter()

    # 检测已运行实例
    handle_existing_instance(ctx, force=force)

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
        launch_lightweight(ctx, startup_logger)
    else:
        launch_full(ctx, should_boot_engine, startup_logger, startup_begin)
