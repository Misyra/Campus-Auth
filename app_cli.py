#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
校园网自动认证工具 - 核心监控模块
包含完整的监控逻辑，GUI版本复用此模块
"""

import asyncio
import datetime
import logging
import os
import signal
import sys
import time
from pathlib import Path
import argparse
import atexit
from typing import Dict, Any, Optional, Callable

# 添加src目录到Python路径
src_path = Path(__file__).parent / "src"
sys.path.insert(0, str(src_path))

from campus_login import EnhancedCampusNetworkAuth
from network_test import is_network_available
from utils import TimeUtils, LoginAttemptHandler, LoggerSetup, get_runtime_stats, ConfigLoader, ConfigValidator, ConfigAdapter


class NetworkMonitorCore:
    """
    核心网络监控器（完整逻辑）
    可以被 CLI 和 GUI 版本复用
    """
    
    def __init__(self, config: Optional[Dict[str, Any]] = None, log_callback: Optional[Callable[[str], None]] = None):
        """
        初始化网络监控器
        
        参数:
            config: 配置字典，如果为None则从.env加载
            log_callback: 日志回调函数，用于GUI显示
        """
        # 加载配置
        self.config = config or ConfigLoader.load_config_from_env()
        
        # 监控状态
        self.monitoring = False
        self.network_check_count = 0
        self.login_attempt_count = 0
        self.start_time = None
        self.last_check_time: Optional[datetime.datetime] = None
        
        # 日志回调函数
        self.log_callback = log_callback
        
        # 设置日志
        self._setup_logging()
    
    def _setup_logging(self) -> None:
        """设置日志配置"""
        log_config = self.config.get('logging', {})
        self.logger = LoggerSetup.setup_logger(f"{__name__}_core", log_config)
    
    def log_message(self, message: str) -> None:
        """
        记录日志消息
        
        参数:
            message: 日志消息
        """
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        formatted_message = f"[{timestamp}] {message}"
        self.logger.info(formatted_message)
        
        # 如果有日志回调函数，则调用（用于GUI显示）
        if self.log_callback:
            self.log_callback(message)
    
    def start_monitoring(self) -> None:
        """
        开始网络监控
        """
        if self.monitoring:
            self.log_message("监控已在运行中")
            return
        
        self.monitoring = True
        self.start_time = time.time()
        self.network_check_count = 0
        self.login_attempt_count = 0
        
        self.log_message("🚀 开始网络监控")
        
        try:
            self.monitor_network()
        except KeyboardInterrupt:
            self.log_message("用户中断，停止监控")
        except Exception as e:
            self.log_message(f"监控过程中发生错误: {str(e)}")
        finally:
            self.stop_monitoring()
    
    def stop_monitoring(self) -> None:
        """
        停止网络监控
        """
        if not self.monitoring:
            return
        
        self.monitoring = False
        if self.start_time:
            runtime_str, stats_str = get_runtime_stats(self.start_time, self.network_check_count)
            self.log_message(f"监控已停止，总运行时间: {runtime_str}")
            self.log_message(f"总{stats_str}")
        else:
            self.log_message("监控已停止")
    
    def monitor_network(self) -> None:
        """
        网络监控主循环
        """
        consecutive_failures = 0
        monitor_interval = self.config.get('monitor', {}).get('interval', 240)
        
        while self.monitoring:
            try:
                # 首先检查是否在暂停时间段，如果是则跳过所有检测
                pause_config = self.config.get('pause_login', {})
                if TimeUtils.is_in_pause_period(pause_config):
                    current_hour = datetime.datetime.now().hour
                    start_hour = pause_config.get('start_hour', 0)
                    end_hour = pause_config.get('end_hour', 6)
                    self.log_message(f"⏰ 当前时间 {current_hour}:xx 在暂停时段（{start_hour}点-{end_hour}点），暂停网络监控")
                    # 优化：等待10分钟，使用更大的睡眠间隔减少CPU占用
                    pause_sleep_time = 30  # 每30秒检查一次是否需要停止
                    total_pause_time = 600  # 10分钟总暂停时间
                    for i in range(0, total_pause_time, pause_sleep_time):
                        if not self.monitoring:
                            return
                        time.sleep(pause_sleep_time)
                    continue
                
                # 更新检测次数
                self.network_check_count += 1
                self.last_check_time = datetime.datetime.now()
                
                self.log_message(f"第{self.network_check_count}次网络检测")
                
                # 检测网络状态
                try:
                    network_ok = is_network_available()
                except Exception as e:
                    self.log_message(f"网络检测失败: {str(e)}")
                    network_ok = False
                
                if network_ok:
                    self.log_message("✅ 网络连接正常")
                    consecutive_failures = 0
                    self.login_attempt_count = 0
                else:
                    consecutive_failures += 1
                    self.log_message(f"❌ 网络连接异常 (连续失败{consecutive_failures}次)")
                    
                    # 检测到网络异常立即尝试登录
                    self.log_message("🔄 检测到网络异常，立即尝试重新登录")
                    
                    # 尝试登录
                    login_success = self.attempt_login()
                    
                    if login_success:
                        consecutive_failures = 0
                        self.login_attempt_count = 0
                        self.log_message("✅ 登录成功，重置失败计数")
                    else:
                        self.login_attempt_count += 1
                        self.log_message(f"❌ 登录失败 (第{self.login_attempt_count}次)")
                        
                        # 连续登录失败3次后等待2分钟
                        if self.login_attempt_count >= 3:
                            cooldown_time = 120  # 2分钟
                            self.log_message(f"⏳ 登录连续3次失败，等待{cooldown_time//60}分钟后重试")
                            # 优化：等待冷却时间，使用更大的睡眠间隔
                            cooldown_sleep_interval = 10  # 每10秒检查一次
                            for i in range(0, cooldown_time, cooldown_sleep_interval):
                                if not self.monitoring:
                                    return
                                time.sleep(cooldown_sleep_interval)
                            self.login_attempt_count = 0
                            continue
                
                # 等待下次检测 - 优化：使用更大的睡眠间隔减少CPU占用
                next_check = datetime.datetime.now() + datetime.timedelta(seconds=monitor_interval)
                self.log_message(f"⏰ 下次检测时间: {next_check.strftime('%H:%M:%S')}")
                
                # 优化：使用30秒间隔而不是1秒，显著降低CPU占用
                sleep_interval = min(30, monitor_interval // 10)  # 取30秒或监控间隔的1/10，取较小值
                sleep_interval = max(sleep_interval, 5)  # 最小5秒间隔
                
                for i in range(0, monitor_interval, sleep_interval):
                    if not self.monitoring:
                        return
                    time.sleep(sleep_interval)
                    
            except Exception as e:
                self.log_message(f"❌ 监控过程中发生错误: {str(e)}")
                # 发生错误时等待1分钟 - 优化：使用更大的睡眠间隔
                error_sleep_interval = 10  # 每10秒检查一次
                for i in range(0, 60, error_sleep_interval):
                    if not self.monitoring:
                        return
                    time.sleep(error_sleep_interval)
    
    def attempt_login(self) -> bool:
        """
        尝试登录校园网（使用工具类简化）
        注意：此方法不再检查暂停时间，因为在monitor_network中已经检查过了
        
        返回:
            bool: 登录是否成功
        """
        try:
            # 直接使用 LoginAttemptHandler 进行登录，跳过暂停时间检查
            login_handler = LoginAttemptHandler(self.config)
            success = asyncio.run(login_handler.attempt_login(skip_pause_check=True))
            return success
                
        except Exception as e:
            self.log_message(f"❌ 登录过程中发生错误: {str(e)}")
            return False
    
    def attempt_login_with_gui_config(self, gui_config: Dict[str, Any]) -> bool:
        """
        使用GUI配置进行登录（不检查暂停时间）
        
        参数:
            gui_config: GUI配置字典
            
        返回:
            bool: 登录是否成功
        """
        try:
            # 使用 ConfigAdapter 创建认证配置
            base_config = ConfigLoader.load_config_from_env()
            auth_config = ConfigAdapter.create_auth_config(gui_config, base_config)
            
            # 使用 LoginAttemptHandler 进行登录
            login_handler = LoginAttemptHandler(auth_config)
            
            # 执行登录（异步调用），跳过暂停时间检查
            success = asyncio.run(login_handler.attempt_login(skip_pause_check=True))
            return success
                
        except Exception as e:
            self.log_message(f"❌ 登录过程中发生错误: {str(e)}")
            return False
    
    def manual_auth_fallback_with_gui_config(self, gui_config: Dict[str, Any]) -> tuple[bool, str]:
        """
        使用GUI配置进行手动认证备选方案
        
        参数:
            gui_config: GUI配置字典
            
        返回:
            tuple[bool, str]: (是否成功, 详细信息)
        """
        try:
            # 使用 ConfigAdapter 创建认证配置
            base_config = ConfigLoader.load_config_from_env()
            auth_config = ConfigAdapter.create_auth_config(gui_config, base_config)
            
            # 创建认证器实例
            auth = EnhancedCampusNetworkAuth(auth_config)
            
            # 执行手动认证
            success, message = asyncio.run(auth.manual_auth_fallback())
            return success, message
                
        except Exception as e:
            error_msg = f"手动认证发生错误: {str(e)}"
            self.log_message(f"❌ {error_msg}")
            return False, error_msg
    
    def test_connection_with_gui_config(self, gui_config: Dict[str, Any]) -> tuple[bool, str]:
        """
        使用GUI配置测试连接
        
        参数:
            gui_config: GUI配置字典
            
        返回:
            tuple[bool, str]: (是否成功, 详细信息)
        """
        try:
            # 使用 ConfigAdapter 创建认证配置
            base_config = ConfigLoader.load_config_from_env()
            auth_config = ConfigAdapter.create_auth_config(gui_config, base_config)
            
            # 创建认证器实例
            auth = EnhancedCampusNetworkAuth(auth_config)
            
            # 执行连接测试
            success, message = asyncio.run(auth.test_connection())
            return success, message
                
        except Exception as e:
            error_msg = f"连接测试发生错误: {str(e)}"
            self.log_message(f"❌ {error_msg}")
            return False, error_msg


class SimpleNetworkMonitor:
    """
    CLI版本的网络监控器包装器
    继承核心功能并添加CLI特定功能
    """
    
    def __init__(self, daemon_mode=False):
        """
        初始化CLI网络监控器
        
        参数:
            daemon_mode: 是否以守护进程模式运行
        """
        self.daemon_mode = daemon_mode
        
        # 创建核心监控器
        self.monitor_core = NetworkMonitorCore()
        
        # 设置信号处理
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        
        # 守护进程模式下的额外设置
        if self.daemon_mode:
            self._setup_daemon_mode()
    
    def _setup_daemon_mode(self) -> None:
        """
        设置守护进程模式
        """
        # 创建PID文件目录
        pid_dir = Path.home() / '.campus_network_auth'
        pid_dir.mkdir(exist_ok=True)
        
        self.pid_file = pid_dir / 'campus_network_auth.pid'
        
        # 检查是否已有实例在运行
        if self.pid_file.exists():
            try:
                with open(self.pid_file, 'r') as f:
                    old_pid = int(f.read().strip())
                
                # 检查进程是否还在运行
                try:
                    os.kill(old_pid, 0)  # 发送信号0检查进程是否存在
                    print(f"错误: 已有实例在运行 (PID: {old_pid})")
                    sys.exit(1)
                except OSError:
                    # 进程不存在，删除旧的PID文件
                    self.pid_file.unlink()
            except (ValueError, FileNotFoundError):
                # PID文件损坏，删除它
                self.pid_file.unlink()
        
        # 写入当前进程PID
        with open(self.pid_file, 'w') as f:
            f.write(str(os.getpid()))
        
        # 注册退出时清理PID文件
        atexit.register(self._cleanup_pid_file)
        
        # 在守护进程模式下，重定向标准输出到日志
        if self.daemon_mode:
            # 禁用控制台输出，只使用日志文件
            sys.stdout = open(os.devnull, 'w')
            sys.stderr = open(os.devnull, 'w')
    
    def _cleanup_pid_file(self) -> None:
        """
        清理PID文件
        """
        if hasattr(self, 'pid_file') and self.pid_file.exists():
            try:
                self.pid_file.unlink()
            except OSError:
                pass
    
    def _signal_handler(self, signum, frame):
        """
        信号处理器，用于优雅退出
        
        参数:
            signum: 信号编号
            frame: 当前栈帧
        """
        signal_name = signal.Signals(signum).name
        self.monitor_core.log_message(f"收到信号 {signal_name}，正在停止监控...")
        self.monitor_core.monitoring = False
        
        # 清理PID文件
        if hasattr(self, 'pid_file'):
            self._cleanup_pid_file()
    
    @property
    def config(self):
        """获取配置"""
        return self.monitor_core.config
    
    @property
    def logger(self):
        """获取日志器"""
        return self.monitor_core.logger
    
    def log_message(self, message: str) -> None:
        """记录日志消息"""
        self.monitor_core.log_message(message)
    
    def start_monitoring(self) -> None:
        """
        开始网络监控
        """
        if self.monitor_core.monitoring:
            self.log_message("监控已在运行中")
            return
        
        # 显示启动信息
        self.log_message("=" * 50)
        self.log_message("校园网自动认证工具 - 后台监控模式")
        self.log_message("=" * 50)
        self.log_message(f"用户名: {self.config.get('username', 'N/A')}")
        self.log_message(f"认证地址: {self.config.get('auth_url', 'N/A')}")
        self.log_message(f"检测间隔: {self.config.get('monitor', {}).get('interval', 240)}秒")
        self.log_message(f"日志文件: {self.config.get('logging', {}).get('file', 'N/A')}")
        self.log_message("按 Ctrl+C 停止监控")
        self.log_message("=" * 50)
        
        # 委托给核心监控器
        self.monitor_core.start_monitoring()
    
    def stop_monitoring(self) -> None:
        """
        停止网络监控
        """
        self.monitor_core.stop_monitoring()


def check_config() -> bool:
    """
    检查配置是否完整
    
    返回:
        bool: 配置是否完整
    """
    config = ConfigLoader.load_config_from_env()
    
    # 使用统一的验证工具
    is_valid, error_msg = ConfigValidator.validate_env_config(config)
    
    if not is_valid:
        print(f"❌ 配置错误: {error_msg}")
        print("请在 .env 文件中配置:")
        print("CAMPUS_USERNAME=你的学号@cmcc")
        print("CAMPUS_PASSWORD=你的密码")
        print("CAMPUS_AUTH_URL=http://172.29.0.2")
        return False
    
    print("✅ 配置检查通过")
    print(f"用户名: {config.get('username')}")
    print(f"认证地址: {config.get('auth_url')}")
    return True


def parse_arguments():
    """
    解析命令行参数
    """
    parser = argparse.ArgumentParser(
        description='校园网自动认证工具',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""使用示例:
  %(prog)s                    # 前台运行
  %(prog)s --daemon           # 后台守护进程模式运行
  %(prog)s --status           # 查看运行状态
  %(prog)s --stop             # 停止后台运行的服务
        """
    )
    
    parser.add_argument(
        '--daemon', '-d',
        action='store_true',
        help='以守护进程模式在后台运行'
    )
    
    parser.add_argument(
        '--status', '-s',
        action='store_true',
        help='查看服务运行状态'
    )
    
    parser.add_argument(
        '--stop',
        action='store_true',
        help='停止后台运行的服务'
    )
    
    return parser.parse_args()


def get_pid_file_path():
    """
    获取PID文件路径
    """
    pid_dir = Path.home() / '.campus_network_auth'
    return pid_dir / 'campus_network_auth.pid'


def check_service_status():
    """
    检查服务运行状态
    """
    pid_file = get_pid_file_path()
    
    if not pid_file.exists():
        print("服务未运行")
        return False
    
    try:
        with open(pid_file, 'r') as f:
            pid = int(f.read().strip())
        
        # 检查进程是否还在运行
        try:
            os.kill(pid, 0)
            print(f"服务正在运行 (PID: {pid})")
            return True
        except OSError:
            print("服务未运行 (PID文件存在但进程不存在)")
            # 清理无效的PID文件
            pid_file.unlink()
            return False
    except (ValueError, FileNotFoundError):
        print("服务未运行 (PID文件损坏)")
        pid_file.unlink()
        return False


def stop_service():
    """
    停止后台运行的服务
    """
    pid_file = get_pid_file_path()
    
    if not pid_file.exists():
        print("服务未运行")
        return
    
    try:
        with open(pid_file, 'r') as f:
            pid = int(f.read().strip())
        
        # 尝试优雅地停止进程
        try:
            print(f"正在停止服务 (PID: {pid})...")
            os.kill(pid, signal.SIGTERM)
            
            # 优化：等待进程结束，使用更大的检查间隔
            for i in range(10):  # 最多等待10秒
                time.sleep(1)  # 这里保持1秒间隔，因为进程停止需要精确检测
                try:
                    os.kill(pid, 0)
                except OSError:
                    print("服务已停止")
                    return
            
            # 如果进程仍在运行，强制终止
            print("强制终止服务...")
            os.kill(pid, signal.SIGKILL)
            print("服务已强制停止")
            
        except OSError:
            print("服务未运行")
            # 清理PID文件
            pid_file.unlink()
    except (ValueError, FileNotFoundError):
        print("服务未运行 (PID文件损坏)")
        pid_file.unlink()


def main():
    """
    主函数
    """
    args = parse_arguments()
    
    # 处理状态查询
    if args.status:
        check_service_status()
        return
    
    # 处理停止服务
    if args.stop:
        stop_service()
        return
    
    # 创建监控器实例
    monitor = SimpleNetworkMonitor(daemon_mode=args.daemon)
    
    if args.daemon:
        print(f"启动守护进程模式... (PID: {os.getpid()})")
        print("使用 'python app_cli.py --status' 查看状态")
        print("使用 'python app_cli.py --stop' 停止服务")
    else:
        print("校园网自动认证工具 - 简化命令行版本")
        print("按 Ctrl+C 停止监控")
        print("-" * 50)
    
    try:
        # 启动监控
        asyncio.run(monitor.start_monitoring())
    except KeyboardInterrupt:
        if not args.daemon:
            print("\n程序被用户中断")
    except Exception as e:
        if not args.daemon:
            print(f"程序运行出错: {e}")
        monitor.logger.error(f"程序运行出错: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()