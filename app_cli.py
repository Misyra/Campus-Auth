#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""校园网认证 CLI 入口。"""

from __future__ import annotations

import argparse
import atexit
import os
import signal
import sys
import time
from pathlib import Path

from backend.autostart_service import AutoStartService
from src.monitor_core import NetworkMonitorCore
from src.playwright_bootstrap import ensure_playwright_ready
from src.utils import ConfigLoader, ConfigValidator


def get_pid_file_path() -> Path:
    pid_dir = Path.home() / ".campus_network_auth"
    pid_dir.mkdir(exist_ok=True)
    return pid_dir / "campus_network_auth.pid"


class SimpleNetworkMonitor:
    def __init__(self, daemon_mode: bool = False):
        self.daemon_mode = daemon_mode
        self.monitor_core = NetworkMonitorCore()
        self.pid_file = get_pid_file_path()

        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        if daemon_mode:
            self._setup_daemon_mode()

    def _setup_daemon_mode(self) -> None:
        if self.pid_file.exists():
            try:
                old_pid = int(self.pid_file.read_text(encoding="utf-8").strip())
                os.kill(old_pid, 0)
                print(f"错误: 已有实例在运行 (PID: {old_pid})")
                sys.exit(1)
            except OSError:
                self.pid_file.unlink(missing_ok=True)
            except ValueError:
                self.pid_file.unlink(missing_ok=True)

        self.pid_file.write_text(str(os.getpid()), encoding="utf-8")
        atexit.register(self._cleanup_pid_file)
        sys.stdout = open(os.devnull, "w")
        sys.stderr = open(os.devnull, "w")

    def _cleanup_pid_file(self) -> None:
        self.pid_file.unlink(missing_ok=True)

    def _signal_handler(self, signum, _frame) -> None:
        signal_name = signal.Signals(signum).name
        print(f"\n收到信号 {signal_name}，正在停止监控...")
        self.monitor_core.stop_monitoring()
        self._cleanup_pid_file()
        sys.exit(0)

    def start_monitoring(self) -> None:
        config = ConfigLoader.load_config_from_env()
        valid, error = ConfigValidator.validate_env_config(config)
        if not valid:
            print(f"配置错误: {error}")
            print("请检查 .env 中的 CAMPUS_USERNAME / CAMPUS_PASSWORD / CAMPUS_AUTH_URL")
            return

        self.monitor_core.start_monitoring()


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="校园网自动认证 CLI")
    parser.add_argument("--daemon", "-d", action="store_true", help="后台守护进程模式")
    parser.add_argument("--status", "-s", action="store_true", help="查看服务状态")
    parser.add_argument("--stop", action="store_true", help="停止后台服务")
    parser.add_argument("--autostart-enable", action="store_true", help="启用开机自启动")
    parser.add_argument("--autostart-disable", action="store_true", help="关闭开机自启动")
    parser.add_argument("--autostart-status", action="store_true", help="查看开机自启动状态")
    return parser.parse_args()


def check_service_status() -> bool:
    pid_file = get_pid_file_path()
    if not pid_file.exists():
        print("服务未运行")
        return False

    try:
        pid = int(pid_file.read_text(encoding="utf-8").strip())
        os.kill(pid, 0)
        print(f"服务正在运行 (PID: {pid})")
        return True
    except (OSError, ValueError):
        pid_file.unlink(missing_ok=True)
        print("服务未运行")
        return False


def stop_service() -> None:
    pid_file = get_pid_file_path()
    if not pid_file.exists():
        print("服务未运行")
        return

    try:
        pid = int(pid_file.read_text(encoding="utf-8").strip())
    except ValueError:
        pid_file.unlink(missing_ok=True)
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
                pid_file.unlink(missing_ok=True)
                return
        os.kill(pid, signal.SIGKILL)
        print("服务已强制停止")
    except OSError:
        print("服务未运行")
    finally:
        pid_file.unlink(missing_ok=True)


def main() -> None:
    args = parse_arguments()
    autostart = AutoStartService(project_root=Path(__file__).parent.resolve())

    if args.status:
        check_service_status()
        return
    if args.stop:
        stop_service()
        return
    if args.autostart_status:
        status = autostart.status()
        print(
            f"平台: {status['platform']}\n"
            f"状态: {'已启用' if status['enabled'] else '未启用'}\n"
            f"方式: {status['method']}\n"
            f"位置: {status['location'] or '-'}"
        )
        return
    if args.autostart_enable:
        ok, msg = autostart.enable()
        print(msg)
        sys.exit(0 if ok else 1)
    if args.autostart_disable:
        ok, msg = autostart.disable()
        print(msg)
        sys.exit(0 if ok else 1)

    monitor = SimpleNetworkMonitor(daemon_mode=args.daemon)
    if args.daemon:
        print(f"启动守护进程模式... (PID: {os.getpid()})")
        print("使用 'uv run app_cli.py --status' 查看状态")
        print("使用 'uv run app_cli.py --stop' 停止服务")
    else:
        print("校园网自动认证 CLI")
        print("按 Ctrl+C 停止")

    try:
        ensure_playwright_ready(print)
        monitor.start_monitoring()
    except KeyboardInterrupt:
        monitor.monitor_core.stop_monitoring()
        print("\n程序已退出")


if __name__ == "__main__":
    main()
