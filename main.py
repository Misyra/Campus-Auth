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

from app.constants import AUTH_DATA_DIR  # noqa: E402  — 测试 fixture 需要
from app.utils.platform_utils import is_windows  # noqa: E402
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
    if setting is not None:
        if not setting:
            return
    else:
        from app.utils import str_to_bool

        if not str_to_bool(os.getenv("CAMPUS_AUTH_AUTO_OPEN_BROWSER", "true")):
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

    # 清理轻量模式触发文件
    (AUTH_DATA_DIR / ".start-web").unlink(missing_ok=True)

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


def _run_login_then_exit(logger) -> None:
    """登录成功后退出模式：先检测网络，已连接则直接退出；否则循环重试登录。"""
    from app.workers.playwright_worker import CMD_LOGIN, get_worker

    # 加载配置
    try:
        from app.services.profile import ProfileService

        ps = ProfileService(Path(__file__).parent.resolve())
        data = ps.load()

        # 构建运行时配置
        from app.services.config import build_runtime_config, load_runtime_config

        payload, has_decrypt_error = load_runtime_config(ps)
        if has_decrypt_error:
            print("警告: 部分密码解密失败，可能需要重新配置密码")
        runtime_config = build_runtime_config(payload, data.system)
    except Exception as exc:
        print(f"加载配置失败: {exc}")
        sys.exit(1)

    # 先检测网络状态，已连接则无需登录，直接退出
    try:
        from app.network.decision import check_network_status

        network_ok, reason = check_network_status(runtime_config)
        if network_ok:
            print("网络已连接，无需登录，正在退出...")
            cleanup_pid()
            sys.exit(0)
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
            # 通过 PlaywrightWorker 提交登录任务（替代原来的 asyncio.new_event_loop() 模式）
            result = get_worker().submit(
                CMD_LOGIN,
                data={
                    "config": runtime_config,
                    "skip_pause_check": True,
                },
                timeout=120,
            )
            success = result.success
            message = result.data if result.success else result.error or "登录失败"
        except Exception as exc:
            message = f"登录异常: {exc}"

        if success:
            print(f"登录成功: {message}")
            print("登录完成，正在退出...")
            # 清理可能残留的浏览器进程
            cleanup_orphan_browsers()
            cleanup_pid()
            sys.exit(0)

        print(f"登录失败 (第 {attempt} 次): {message}")

        if max_retries > 0 and attempt >= max_retries:
            break

    # 超过最大重试次数，回退到正常启动
    # 在回退之前清理可能残留的浏览器进程
    cleanup_orphan_browsers()
    print(f"已重试 {max_retries} 次均失败，回退到正常模式启动服务器")
    logger.warning(
        "login_then_exit 登录失败（已重试 {} 次），回退到正常模式启动服务器",
        max_retries,
    )


# ==================== 轻量模式 ====================


def _run_lightweight(
    logger, port, no_browser=False, minimize_to_tray=False, auto_open_browser=None
) -> None:
    """轻量模式：启动时不加载 FastAPI，用户访问时按需加载。"""
    from app.application import create_app, run
    from app.container import ServiceContainer

    container = ServiceContainer(Path(__file__).parent.resolve())
    # 仅启动引擎（监控 + 定时任务），不启动 Web 服务
    container.engine.boot()
    if container.engine.has_enabled_tasks():
        container.engine.start_scheduler()
    logger.info("轻量模式启动: 仅监控，Web 服务未加载")

    # uvicorn server 引用
    _uvicorn_server = [None]

    # 信号处理器（覆盖 _run_server 的，闭包引用本函数的 _uvicorn_server）
    _shutdown = False

    def _signal_handler(signum, _frame):
        nonlocal _shutdown
        if _shutdown:
            cleanup_pid()
            os._exit(1)
        _shutdown = True
        logger.info("收到退出信号，正在关闭...")
        cleanup_pid()
        if _uvicorn_server[0] is not None:
            _uvicorn_server[0].should_exit = True

    signal.signal(signal.SIGINT, _signal_handler)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _signal_handler)

    # 系统托盘
    tray_icon = None
    if minimize_to_tray:
        try:
            from app.core.system_tray import SystemTray

            tray_icon = SystemTray(
                port=port,
                on_exit=lambda: os.kill(os.getpid(), signal.SIGTERM)
                if hasattr(signal, "SIGTERM")
                else cleanup_pid() or os._exit(0),
            )
            tray_icon.start()
        except Exception as e:
            logger.warning("启动系统托盘失败: {}", e)

    if not no_browser:
        _open_browser(port, setting=auto_open_browser)

    # 占位服务器等待用户访问
    _web_wakeup = threading.Event()
    _start_wakeup_server(port, logger, _web_wakeup)

    while not _web_wakeup.is_set() and not _shutdown:
        time.sleep(1)

    if _shutdown:
        logger.info("正在关闭服务...")
        loop = asyncio.new_event_loop()
        loop.run_until_complete(container.shutdown())
        loop.close()
        return

    logger.info("检测到 Web 访问，加载 FastAPI...")
    time.sleep(0.5)

    # 创建 FastAPI 并启动 uvicorn（阻塞直到关机）
    _app = create_app(existing_container=container)

    try:
        try:
            _sys = container.profile_service.load().system
            _al = bool(_sys.access_log)
            _lr = max(1, int(_sys.log_retention_days))
        except Exception:
            _al, _lr = False, 7

        run(
            access_log_enabled=_al,
            log_retention=_lr,
            existing_container=container,
            server_ref=_uvicorn_server,
            app_instance=_app,
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


def _run_server(
    no_browser: bool = False, tray: bool = False, no_auto: bool = False
) -> None:
    from app.utils.logging import get_logger

    startup_logger = get_logger("startup", source="backend")
    startup_begin = time.perf_counter()
    running, pid = is_service_running()
    from app.utils.ports import resolve_port

    port = resolve_port()

    if running or is_local_port_in_use(port):
        print(f"软件已启动 (PID: {pid})，正在打开 Web 控制台...")
        webbrowser.open(f"http://127.0.0.1:{port}")
        sys.exit(0)

    write_pid()
    atexit.register(cleanup_pid)

    # 读取系统设置
    auto_open_browser = None
    try:
        from app.services.profile import ProfileService

        _ps = ProfileService(Path(__file__).parent.resolve())
        _sys_settings = _ps.load().system
        minimize_to_tray = tray or bool(_sys_settings.minimize_to_tray)
        login_then_exit = bool(_sys_settings.login_then_exit)
        auto_open_browser = bool(_sys_settings.auto_open_browser)
        lightweight_mode = bool(_sys_settings.lightweight_mode)
    except Exception:
        _sys_settings = None
        minimize_to_tray = tray or False
        login_then_exit = False
        lightweight_mode = False

    # uvicorn server 引用（信号处理器和完整模式共用）
    _uvicorn_server = [None]

    # 信号处理器
    _shutdown_initiated = False

    def _signal_handler(signum, _frame):
        nonlocal _shutdown_initiated
        if _shutdown_initiated:
            cleanup_pid()
            os._exit(1)
        _shutdown_initiated = True
        startup_logger.info("收到退出信号，正在关闭...")
        cleanup_pid()
        if _uvicorn_server[0] is not None:
            _uvicorn_server[0].should_exit = True
        else:
            os._exit(0)

    signal.signal(signal.SIGINT, _signal_handler)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _signal_handler)

    # Playwright 检查
    stage_begin = time.perf_counter()
    startup_logger.info("启动阶段: 开始检查 Playwright 运行环境")
    ensure_playwright_ready(print)
    startup_logger.info(
        "启动阶段: Playwright 检查完成，耗时 {:.3f}s",
        time.perf_counter() - stage_begin,
    )

    # 登录成功后退出模式
    is_autostart = os.environ.get("CAMPUS_AUTH_AUTOSTART") == "1"
    if login_then_exit and is_autostart and not no_auto:
        _run_login_then_exit(startup_logger)

    if no_auto:
        os.environ["CAMPUS_AUTH_NO_AUTO"] = "1"

    # ── 轻量模式：不加载 FastAPI，仅运行监控 ──
    if lightweight_mode:
        _run_lightweight(
            startup_logger, port,
            no_browser=no_browser,
            minimize_to_tray=minimize_to_tray,
            auto_open_browser=auto_open_browser,
        )
        return

    # 创建容器（生命周期独立于 uvicorn）
    from app.application import create_app, run
    from app.container import ServiceContainer

    container = ServiceContainer(Path(__file__).parent.resolve())
    _app = create_app(existing_container=container)

    # 系统托盘
    tray_icon = None
    if minimize_to_tray:
        try:
            from app.core.system_tray import SystemTray

            tray_icon = SystemTray(
                port=port,
                on_exit=lambda: os.kill(os.getpid(), signal.SIGTERM)
                if hasattr(signal, "SIGTERM")
                else cleanup_pid() or os._exit(0),
            )
            tray_icon.start()
            startup_logger.info("系统托盘已启动，双击图标打开控制台")
        except Exception as e:
            startup_logger.warning("启动系统托盘失败: {}", e)

    if not no_browser:
        _open_browser(port, setting=auto_open_browser)

    startup_logger.info("Web 控制台: http://127.0.0.1:{}", port)
    startup_logger.info("日志文件:   {}", Path.cwd() / "logs")
    startup_logger.info("按 Ctrl+C 停止服务")
    startup_logger.info(
        "启动阶段: 启动准备完成，总耗时 {:.3f}s，开始启动 Uvicorn",
        time.perf_counter() - startup_begin,
    )

    try:
        # 启动 uvicorn（阻塞直到关机）
        try:
            _al = bool(_sys_settings.access_log)
            _lr = max(1, int(_sys_settings.log_retention_days))
        except (AttributeError, TypeError, ValueError):
            _al, _lr = False, 7

        run(
            access_log_enabled=_al,
            log_retention=_lr,
            existing_container=container,
            server_ref=_uvicorn_server,
            app_instance=_app,
        )
    except KeyboardInterrupt:
        startup_logger.info("收到退出信号，正在关闭...")
    finally:
        if tray_icon:
            tray_icon.stop()

    # ── 进程退出清理 ──
    startup_logger.info("正在关闭服务...")
    loop = asyncio.new_event_loop()
    loop.run_until_complete(container.shutdown())
    loop.close()


# ==================== 占位服务器（空闲时响应用户访问）====================

# 加载页面 HTML（模块级常量，避免重复创建）
_WAKEUP_HTML = """<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>Campus-Auth</title>
<meta http-equiv="refresh" content="3">
<style>
body{font-family:system-ui;display:flex;justify-content:center;align-items:center;
height:100vh;margin:0;background:#1a1a2e;color:#e0e0e0}
.box{text-align:center}
.spinner{width:40px;height:40px;border:3px solid #333;border-top-color:#6c63ff;
border-radius:50%;animation:spin 1s linear infinite;margin:0 auto 20px}
@keyframes spin{to{transform:rotate(360deg)}}
</style></head><body>
<div class="box">
<div class="spinner"></div>
<p>正在唤醒 Web 控制台...</p>
<p style="font-size:0.85em;color:#888">页面将自动刷新</p>
</div></body></html>"""


def _start_wakeup_server(port: int, logger, web_wakeup: threading.Event) -> None:
    """启动占位 HTTP 服务器：用户访问时返回加载页面并触发唤醒。"""
    from http.server import BaseHTTPRequestHandler, HTTPServer

    _server_ref = [None]

    class WakeupHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            body = _WAKEUP_HTML.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            # 通知主线程唤醒
            web_wakeup.set()
            # 延迟关闭服务器（让响应发完）
            def _close():
                time.sleep(0.5)
                if _server_ref[0]:
                    _server_ref[0].server_close()
            threading.Thread(target=_close, daemon=True).start()

        def log_message(self, format, *args):
            pass

    server = HTTPServer(("127.0.0.1", port), WakeupHandler)
    _server_ref[0] = server
    server.timeout = 1

    def _serve():
        try:
            while not web_wakeup.is_set():
                server.handle_request()
        except OSError:
            pass  # 服务器已关闭

    threading.Thread(target=_serve, daemon=True).start()
    logger.info("占位服务器已启动: http://127.0.0.1:{}", port)


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
        epilog="""
示例:
  python main.py                    启动 Web 控制台
  python main.py --no-browser       启动但不打开浏览器
  python main.py --no-auto          跳过自动登录和自动启动（用于恢复设置）
  python main.py --tray             启动到系统托盘
  python main.py --status           查看服务状态
  python main.py --stop             停止服务
  python main.py --autostart        查看开机自启动状态
  python main.py --autostart enable 启用开机自启动
        """,
    )

    parser.add_argument(
        "--no-browser", action="store_true", help="启动后不自动打开浏览器"
    )
    parser.add_argument(
        "--no-auto",
        action="store_true",
        help="跳过自动登录（login_then_exit）和自动启动监控（auto_start），"
        "用于 login_then_exit 开启后无法进入 Web 控制台的恢复场景",
    )
    parser.add_argument("--tray", action="store_true", help="启动到系统托盘")
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

    if args.status:
        _cmd_status()
        return

    if args.stop:
        _cmd_stop()
        return

    if args.autostart:
        _cmd_autostart(args.autostart)
        return

    _run_server(no_browser=args.no_browser, tray=args.tray, no_auto=args.no_auto)


if __name__ == "__main__":
    main()
