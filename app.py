#!/usr/bin/env python3
"""Campus-Auth 校园网自动认证 - 统一启动入口"""

import argparse
import atexit
import logging
import os
import signal
import sys
import threading
import time
import webbrowser
from pathlib import Path

# 将项目根目录添加到 Python 路径
sys.path.insert(0, str(Path(__file__).parent))

from src.playwright_bootstrap import ensure_playwright_ready


def _setup_logging() -> None:
    from src.utils import ColoredFormatter

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(ColoredFormatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S"
    ))
    root_logger.addHandler(console_handler)


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
        os.kill(pid, 0)
        return True, pid
    except (OSError, ValueError):
        pid_file.unlink(missing_ok=True)
        return False, None


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
    os.environ.setdefault("Campus-Auth_START_EXECUTABLE", str(exe_path))
    os.environ.setdefault("Campus-Auth_PROJECT_ROOT", str(project_root))
    os.environ.setdefault("Campus-Auth_ENV_FILE", str(project_root / ".env"))


# ==================== 浏览器控制 ====================

def _open_browser(port: int) -> None:
    auto_open = os.getenv("Campus-Auth_AUTO_OPEN_BROWSER", "true").strip().lower()
    if auto_open not in {"1", "true", "yes", "on"}:
        return
    def _worker():
        time.sleep(1.2)
        webbrowser.open(f"http://127.0.0.1:{port}")
    threading.Thread(target=_worker, daemon=True).start()


# ==================== CLI 命令 ====================

def _cmd_status() -> None:
    running, pid = _is_service_running()
    if running:
        print(f"服务正在运行 (PID: {pid})")
    else:
        print("服务未运行")


def _cmd_stop() -> None:
    running, pid = _is_service_running()
    if not running or pid is None:
        print("服务未运行")
        return
    try:
        print(f"正在停止服务 (PID: {pid})...")
        os.kill(pid, signal.SIGTERM)
        for _ in range(10):
            time.sleep(1)
            try:
                os.kill(pid, 0)
            except OSError:
                print("服务已停止")
                _cleanup_pid()
                return
        if sys.platform != "win32":
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


# ==================== 主启动 ====================

def _run_server(no_browser: bool = False, tray: bool = False) -> None:
    running, pid = _is_service_running()
    if running:
        print(f"服务已在运行 (PID: {pid})")
        print("请先停止现有服务: python app.py --stop")
        sys.exit(1)

    _write_pid()
    atexit.register(_cleanup_pid)

    def _signal_handler(signum, _frame):
        print(f"\n收到停止信号，正在关闭...")
        _cleanup_pid()
        sys.exit(0)

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    ensure_playwright_ready(print)

    from src.utils import ConfigLoader

    config = ConfigLoader.load_config_from_env()
    minimize_to_tray = tray or bool(config.get("minimize_to_tray", False))

    from backend.main import run, _resolve_port
    port = _resolve_port()

    tray_icon = None
    if minimize_to_tray:
        try:
            from src.system_tray import SystemTray
            tray_icon = SystemTray(port=port, on_exit=lambda: os.kill(os.getpid(), signal.SIGTERM))
            tray_icon.start()
            print(f"系统托盘已启动，双击图标打开控制台")
        except Exception as e:
            print(f"启动系统托盘失败: {e}")

    if not no_browser and not minimize_to_tray:
        _open_browser(port)

    print(f"Web 控制台已启动: http://127.0.0.1:{port}")
    print("按 Ctrl+C 停止服务")

    try:
        run()
    finally:
        if tray_icon:
            tray_icon.stop()


# ==================== 入口 ====================

def main() -> None:
    _setup_logging()

    parser = argparse.ArgumentParser(
        description="Campus-Auth 校园网自动认证",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python app.py                    启动 Web 控制台
  python app.py --no-browser       启动但不打开浏览器
  python app.py --tray             启动到系统托盘
  python app.py --status           查看服务状态
  python app.py --stop             停止服务
  python app.py --autostart        查看开机自启动状态
  python app.py --autostart enable 启用开机自启动
        """
    )

    parser.add_argument("--no-browser", action="store_true", help="启动后不自动打开浏览器")
    parser.add_argument("--tray", action="store_true", help="启动到系统托盘")
    parser.add_argument("--status", action="store_true", help="查看服务状态")
    parser.add_argument("--stop", action="store_true", help="停止服务")
    parser.add_argument("--autostart", nargs="?", const="status", default=None,
                        choices=["status", "enable", "disable"],
                        help="管理开机自启动 (status/enable/disable)")

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

    _run_server(no_browser=args.no_browser, tray=args.tray)


if __name__ == "__main__":
    main()
