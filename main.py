#!/usr/bin/env python3
"""Campus-Auth 校园网自动认证 - 统一启动入口"""

import argparse
import atexit
import contextlib
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

from app.constants import AUTH_DATA_DIR  # noqa: F401, E402  — 测试 fixture 需要
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
    from app.application import _resolve_port

    port = _resolve_port()

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


def _run_login_then_exit(logger) -> None:
    """登录成功后退出模式：循环重试登录，直到成功后退出进程。"""
    from app.workers.playwright_worker import CMD_LOGIN, get_worker

    print("登录成功后退出模式：正在登录...")

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


# ==================== 主启动 ====================


def _run_server(
    no_browser: bool = False, tray: bool = False, no_auto: bool = False
) -> None:
    from app.utils.logging import get_logger

    startup_logger = get_logger("startup", side="APP")
    startup_begin = time.perf_counter()
    running, pid = is_service_running()
    from app.application import _resolve_port

    port = _resolve_port()

    if running or is_local_port_in_use(port):
        print(f"软件已启动 (PID: {pid})，正在打开 Web 控制台...")
        webbrowser.open(f"http://127.0.0.1:{port}")
        sys.exit(0)

    write_pid()
    atexit.register(cleanup_pid)

    def _signal_handler(signum, _frame):
        cleanup_pid()
        with contextlib.suppress(Exception):
            from app.workers.playwright_worker import get_worker

            get_worker().stop(timeout=3)
        with contextlib.suppress(Exception):
            cleanup_orphan_browsers()
        os._exit(0)

    signal.signal(signal.SIGINT, _signal_handler)
    # SIGTERM 在 Windows 上不存在（仅有 SIGINT/SIGBREAK），需要守卫以避免 AttributeError
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _signal_handler)

    stage_begin = time.perf_counter()
    startup_logger.info("启动阶段: 开始检查 Playwright 运行环境")
    ensure_playwright_ready(print)
    startup_logger.info(
        "启动阶段: Playwright 检查完成，耗时 {:.3f}s",
        time.perf_counter() - stage_begin,
    )

    # 优先从 settings.json 读取（Web 控制台可修改），回退到 .env
    auto_open_browser = None
    try:
        from app.services.profile import ProfileService

        _ps = ProfileService(Path(__file__).parent.resolve())
        _sys_settings = _ps.load().system
        minimize_to_tray = tray or bool(_sys_settings.minimize_to_tray)
        login_then_exit = bool(_sys_settings.login_then_exit)
        auto_open_browser = bool(_sys_settings.auto_open_browser)
    except Exception:
        minimize_to_tray = tray or False
        login_then_exit = False
        # auto_open_browser 保持 None，让 _open_browser 走环境变量默认值

    # 登录成功后退出模式：循环重试直到登录成功，成功后退出进程
    # --no-auto 可跳过此模式，用于 login_then_exit 开启后无法进入 Web 控制台的恢复场景
    if login_then_exit and not no_auto:
        _run_login_then_exit(startup_logger)
        # 登录成功会 sys.exit(0)，不会到达这里；失败超限则回退到正常启动

    # 通过环境变量传递 --no-auto 标志给后端，跳过 auto_start
    if no_auto:
        os.environ["CAMPUS_AUTH_NO_AUTO"] = "1"

    from app.application import run

    tray_icon = None
    if minimize_to_tray:
        try:
            from app.core.system_tray import SystemTray

            tray_icon = SystemTray(
                port=port,
                # 托盘退出回调：优先发送 SIGTERM 优雅关闭；无 SIGTERM 时直接终止进程（Windows 上 taskkill 替代）
                on_exit=lambda: os.kill(os.getpid(), signal.SIGTERM)
                if hasattr(signal, "SIGTERM")
                else cleanup_pid() or os._exit(0),
            )
            tray_icon.start()
            print("系统托盘已启动，双击图标打开控制台")

        except Exception as e:
            print(f"启动系统托盘失败: {e}")

    if not no_browser:
        _open_browser(port, setting=auto_open_browser)

    print(f"Web 控制台: http://127.0.0.1:{port}")
    print(f"日志文件:   {Path.cwd() / 'logs'}")
    print("按 Ctrl+C 停止服务")
    startup_logger.info(
        "启动阶段: 启动准备完成，总耗时 {:.3f}s，开始启动 Uvicorn",
        time.perf_counter() - startup_begin,
    )

    try:
        run()
    finally:
        if tray_icon:
            tray_icon.stop()


# ==================== 全局异常钩子 ====================


def _setup_exception_hooks() -> None:
    """设置全局异常钩子，确保线程内未捕获异常被记录到日志。"""
    import threading

    from app.utils.logging import get_logger

    _hook_logger = get_logger("uncaught", side="APP")

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
