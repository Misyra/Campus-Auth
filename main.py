#!/usr/bin/env python3
"""Campus-Auth 校园网自动认证 - 统一启动入口"""

import argparse
import sys
import threading
import time
from pathlib import Path

# 确保项目根目录在 sys.path 中（uv 环境下 sys.path 已由 uv 管理，但保留兼容性）
_project_root = Path(__file__).resolve().parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from app.schemas import (  # noqa: E402
    AppConfig,
    ApplicationContext,
    LaunchContext,
    LaunchSource,
    RuntimeMode,
    StartupAction,
)
from app.services.launcher import (  # noqa: E402
    _terminate_process,
    launch_server,
)
from app.utils.process import (  # noqa: E402
    cleanup_pid,
    get_pid_file,
    is_local_port_in_use,
    is_service_running,
    read_pid_mode,
)
from app.services.profile_service import create_profile_service  # noqa: E402


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
        stopped = False
        for _ in range(10):
            time.sleep(0.5)
            if not is_service_running()[0]:
                stopped = True
                break
        if stopped:
            print("服务已停止")
            cleanup_pid()
        else:
            # 超时未退出：保留 PID 文件以便后续重试
            print(f"停止超时：进程 {pid} 仍在运行，PID 文件已保留")
    except OSError:
        print("服务未运行")
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
        logger.warning("加载配置失败，使用默认值", exc_info=True)
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


# ==================== 全局异常钩子 ====================


def _setup_exception_hooks() -> None:
    """设置全局异常钩子，确保线程内未捕获异常被记录到日志。"""
    from app.utils.logging import get_logger

    _hook_logger = get_logger("uncaught", source="backend")

    def _threading_excepthook(args: threading.ExceptHookArgs) -> None:
        _hook_logger.error(
            "线程 {} 未捕获异常",
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

    launch_server(ctx, force=args.force)


if __name__ == "__main__":
    main()
