#!/usr/bin/env python3
"""Campus-Auth 校园网自动认证 - 统一启动入口"""

import argparse
import atexit
import errno  # POSIX errno 值，用于跨平台异常处理
import os
import signal
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

# 确保项目根目录在 sys.path 中（嵌入式 Python 不会自动添加）
_project_root = Path(__file__).resolve().parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from src.playwright_bootstrap import ensure_playwright_ready  # noqa: E402 — 需要在 sys.path 插入后导入
from src.utils.platform_utils import is_windows  # noqa: E402 — 同上；跨平台检测：替代 sys.platform == "win32"




# ==================== PID 管理 ====================


def _get_pid_file() -> Path:
    pid_dir = Path.home() / ".campus_network_auth"
    pid_dir.mkdir(exist_ok=True)
    return pid_dir / "campus_network_auth.pid"


def _is_service_running() -> tuple[bool, int | None]:
    pid_file = _get_pid_file()
    if not pid_file.exists():
        return False, None
    try:
        pid = int(pid_file.read_text(encoding="utf-8").strip())
        if pid <= 0:
            pid_file.unlink(missing_ok=True)
            return False, None
        try:
            os.kill(pid, 0)
        except PermissionError:
            # Windows 下可能因权限导致探活失败，此时保守地认为进程仍在运行
            return True, pid
        except ProcessLookupError:
            pid_file.unlink(missing_ok=True)
            return False, None
        except OSError as exc:
            # Windows: winerror=5 表示 Access denied；POSIX: errno=EACCES 表示权限不足，均保守视为存活
            if getattr(exc, "winerror", getattr(exc, "errno", None)) in (5, errno.EACCES):
                return True, pid
            pid_file.unlink(missing_ok=True)
            return False, None
        return True, pid
    except (ValueError, SystemError):
        pid_file.unlink(missing_ok=True)
        return False, None


def _is_local_port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.4)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def _write_pid() -> None:
    _get_pid_file().write_text(str(os.getpid()), encoding="utf-8")


def _cleanup_pid() -> None:
    _get_pid_file().unlink(missing_ok=True)


# ==================== 打包环境 ====================


def _is_packaged() -> bool:
    return bool(getattr(sys, "frozen", False) or globals().get("__compiled__"))


def _setup_packaged_env() -> None:
    if not _is_packaged():
        return
    exe_path = Path(sys.argv[0]).resolve()
    project_root = exe_path.parent
    os.environ.setdefault("CAMPUS_AUTH_START_EXECUTABLE", str(exe_path))
    os.environ.setdefault("CAMPUS_AUTH_PROJECT_ROOT", str(project_root))


# ==================== 浏览器控制 ====================


def _open_browser(port: int, setting: bool | None = None) -> None:
    if setting is not None:
        if not setting:
            return
    else:
        from src.utils import str_to_bool
        if not str_to_bool(os.getenv("CAMPUS_AUTH_AUTO_OPEN_BROWSER", "true")):
            return

    def _worker():
        time.sleep(1.2)
        webbrowser.open(f"http://127.0.0.1:{port}")

    threading.Thread(target=_worker, daemon=True).start()


# ==================== CLI 命令 ====================


def _cmd_status() -> None:
    running, pid = _is_service_running()
    from backend.main import _resolve_port

    port = _resolve_port()

    if running:
        print(f"服务正在运行 (PID: {pid})")
    elif _is_local_port_in_use(port):
        print(f"服务疑似正在运行 (端口: {port})")
    else:
        print("服务未运行")


def _cmd_stop() -> None:
    running, pid = _is_service_running()
    if not running or pid is None:
        print("服务未运行")
        return
    try:
        print(f"正在停止服务 (PID: {pid})...")
        if is_windows():
            # Windows: taskkill 发送 WM_CLOSE 实现优雅关闭
            import subprocess as _sp
            _sp.run(
                ["taskkill", "/PID", str(pid)],
                capture_output=True,
                creationflags=_sp.CREATE_NO_WINDOW if hasattr(_sp, "CREATE_NO_WINDOW") else 0,
            )
        else:
            os.kill(pid, signal.SIGTERM)
        for _ in range(10):
            time.sleep(1)
            try:
                os.kill(pid, 0)
            except OSError:
                print("服务已停止")
                _cleanup_pid()
                return
        if is_windows():
            import subprocess as _sp
            _sp.run(
                ["taskkill", "/F", "/PID", str(pid)],
                capture_output=True,
                creationflags=_sp.CREATE_NO_WINDOW if hasattr(_sp, "CREATE_NO_WINDOW") else 0,
            )
            print("服务已强制停止")
        else:
            os.kill(pid, signal.SIGKILL)
            print("服务已强制停止")
    except OSError:
        print("服务未运行")
    finally:
        _cleanup_pid()


def _cmd_autostart(action: str) -> None:
    from backend.autostart_service import AutoStartService

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
    from src.utils import LoginAttemptHandler

    print("登录成功后退出模式：正在登录...")

    try:
        from backend.profile_service import ProfileService
        ps = ProfileService(Path(__file__).parent.resolve())
        data = ps.load()

        # 构建运行时配置
        from backend.config_service import build_runtime_config, load_runtime_config
        payload = load_runtime_config(ps)
        runtime_config = build_runtime_config(payload, data.system)
    except Exception as exc:
        print(f"加载配置失败: {exc}")
        sys.exit(1)

    retry_settings = runtime_config.get("retry_settings", {})
    raw = retry_settings.get("max_retries", 3)
    max_retries = max(0, min(raw, 10))
    retry_interval = int(retry_settings.get("retry_interval", 5))

    handler = LoginAttemptHandler(runtime_config)

    import asyncio
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
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                success, message = loop.run_until_complete(
                    handler.attempt_login(skip_pause_check=True)
                )
            finally:
                # 取消待处理任务，避免 loop.close() 因未完成任务而报错
                pending = asyncio.all_tasks(loop)
                for task in pending:
                    task.cancel()
                if pending:
                    try:
                        loop.run_until_complete(
                            asyncio.gather(*pending, return_exceptions=True)
                        )
                    except Exception:
                        pass
                loop.close()
        except Exception as exc:
            message = f"登录异常: {exc}"

        if success:
            print(f"登录成功: {message}")
            print("登录完成，正在退出...")
            _cleanup_pid()
            sys.exit(0)

        print(f"登录失败 (第 {attempt} 次): {message}")

        if max_retries > 0 and attempt >= max_retries:
            break

    # 超过最大重试次数，回退到正常启动
    print(f"已重试 {max_retries} 次均失败，回退到正常模式启动服务器")
    logger.warning(
        "login_then_exit 登录失败（已重试 %d 次），回退到正常模式启动服务器", max_retries
    )


# ==================== 主启动 ====================


def _run_server(no_browser: bool = False, tray: bool = False, no_auto: bool = False) -> None:
    from src.utils.logging import get_logger

    startup_logger = get_logger("startup", side="APP")
    startup_begin = time.perf_counter()
    running, pid = _is_service_running()
    from backend.main import _resolve_port

    port = _resolve_port()

    if running or _is_local_port_in_use(port):
        print(f"软件已启动 (PID: {pid})，正在打开 Web 控制台...")
        webbrowser.open(f"http://127.0.0.1:{port}")
        sys.exit(0)

    _write_pid()
    atexit.register(_cleanup_pid)

    def _signal_handler(signum, _frame):
        print("\n收到停止信号，正在关闭...")
        try:
            from backend.main import service
            service.stop_monitoring()
        except Exception:
            pass
        _cleanup_pid()
        os._exit(0)

    signal.signal(signal.SIGINT, _signal_handler)
    # SIGTERM 在 Windows 上不存在（仅有 SIGINT/SIGBREAK），需要守卫以避免 AttributeError
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _signal_handler)

    stage_begin = time.perf_counter()
    startup_logger.info("启动阶段: 开始检查 Playwright 运行环境")
    ensure_playwright_ready(print)
    startup_logger.info(
        "启动阶段: Playwright 检查完成，耗时 %.3fs",
        time.perf_counter() - stage_begin,
    )


    # 优先从 settings.json 读取（Web 控制台可修改），回退到 .env
    auto_open_browser = None
    try:
        from backend.profile_service import ProfileService
        _ps = ProfileService(Path(__file__).parent.resolve())
        _sys_settings = _ps.load().system
        minimize_to_tray = tray or bool(_sys_settings.minimize_to_tray)
        login_then_exit = bool(_sys_settings.login_then_exit)
        auto_open_browser = bool(_sys_settings.auto_open_browser)
    except Exception:
        minimize_to_tray = tray or False
        login_then_exit = False

    # 登录成功后退出模式：循环重试直到登录成功，成功后退出进程
    # --no-auto 可跳过此模式，用于 login_then_exit 开启后无法进入 Web 控制台的恢复场景
    if login_then_exit and not no_auto:
        _run_login_then_exit(startup_logger)
        # 登录成功会 sys.exit(0)，不会到达这里；失败超限则回退到正常启动

    # 通过环境变量传递 --no-auto 标志给后端，跳过 auto_start
    if no_auto:
        os.environ["CAMPUS_AUTH_NO_AUTO"] = "1"

    from backend.main import run

    tray_icon = None
    if minimize_to_tray:
        try:
            from src.system_tray import SystemTray

            tray_icon = SystemTray(
                port=port,
                # 托盘退出回调：优先发送 SIGTERM 优雅关闭；无 SIGTERM 时直接终止进程（Windows 上 taskkill 替代）
                on_exit=lambda: os.kill(os.getpid(), signal.SIGTERM) if hasattr(signal, "SIGTERM") else os._exit(0),
            )
            tray_icon.start()
            print("系统托盘已启动，双击图标打开控制台")

            # 将托盘实例引用传递给 backend，确保 shutdown 时能正确停止
            from backend.main import _set_tray_icon
            _set_tray_icon(tray_icon)
        except Exception as e:
            print(f"启动系统托盘失败: {e}")

    if not no_browser:
        _open_browser(port, setting=auto_open_browser)

    print(f"Web 控制台: http://127.0.0.1:{port}")
    print(f"日志文件:   {Path.cwd() / 'logs'}")
    print("按 Ctrl+C 停止服务")
    startup_logger.info(
        "启动阶段: 启动准备完成，总耗时 %.3fs，开始启动 Uvicorn",
        time.perf_counter() - startup_begin,
    )

    try:
        run()
    finally:
        if tray_icon:
            tray_icon.stop()


# ==================== 入口 ====================


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Campus-Auth 校园网自动认证",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python app.py                    启动 Web 控制台
  python app.py --no-browser       启动但不打开浏览器
  python app.py --no-auto          跳过自动登录和自动启动（用于恢复设置）
  python app.py --tray             启动到系统托盘
  python app.py --status           查看服务状态
  python app.py --stop             停止服务
  python app.py --autostart        查看开机自启动状态
  python app.py --autostart enable 启用开机自启动
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

    _setup_packaged_env()

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
