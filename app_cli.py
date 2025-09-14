#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
校园网自动认证工具 - 简化命令行版本
直接读取.env配置，启动后自动进入后台监控模式
"""

import asyncio
import datetime
import logging
import os
import signal
import sys
import time
from pathlib import Path

# 添加src目录到Python路径
src_path = Path(__file__).parent / "src"
sys.path.insert(0, str(src_path))

from campus_login import EnhancedCampusNetworkAuth
from network_test import is_network_available
from utils import TimeUtils, LoginAttemptHandler, LoggerSetup, get_runtime_stats, ConfigLoader, ConfigValidator


class SimpleNetworkMonitor:
    """
    简化的校园网网络监控器
    自动从.env加载配置，启动后直接进入监控模式
    """
    
    def __init__(self):
        """
        初始化网络监控器
        """
        # 加载配置
        self.config = ConfigLoader.load_config_from_env()
        
        # 监控状态
        self.monitoring = False
        self.network_check_count = 0
        self.login_attempt_count = 0
        self.start_time = None
        
        # 设置日志
        self._setup_logging()
        
        # 信号处理
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
    
    def _setup_logging(self) -> None:
        """设置日志配置（使用工具类）"""
        log_config = self.config.get('logging', {})
        
        # 使用 LoggerSetup 工具类
        self.logger = LoggerSetup.setup_logger(__name__, log_config)
    
    def _signal_handler(self, signum, frame):
        """
        信号处理器，用于优雅退出
        
        参数:
            signum: 信号编号
            frame: 当前栈帧
        """
        self.logger.info(f"收到信号 {signum}，正在停止监控...")
        self.stop_monitoring()
    
    def log_message(self, message: str) -> None:
        """
        记录日志消息
        
        参数:
            message: 日志消息
        """
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        formatted_message = f"[{timestamp}] {message}"
        self.logger.info(formatted_message)
    
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
            # 使用 get_runtime_stats 获取统计信息
            runtime_str, stats_str = get_runtime_stats(self.start_time, self.network_check_count)
            self.log_message("=" * 50)
            self.log_message(f"监控已停止，总运行时间: {runtime_str}")
            self.log_message(f"总{stats_str}")
            self.log_message("=" * 50)
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
                # 更新检测次数
                self.network_check_count += 1
                
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
                            # 等待冷却时间
                            for i in range(cooldown_time):
                                if not self.monitoring:
                                    return
                                time.sleep(1)
                            self.login_attempt_count = 0
                            continue
                
                # 等待下次检测
                next_check = datetime.datetime.now() + datetime.timedelta(seconds=monitor_interval)
                self.log_message(f"⏰ 下次检测时间: {next_check.strftime('%H:%M:%S')}")
                
                for i in range(monitor_interval):
                    if not self.monitoring:
                        return
                    time.sleep(1)
                    
            except Exception as e:
                self.log_message(f"❌ 监控过程中发生错误: {str(e)}")
                # 发生错误时等待1分钟
                for i in range(60):
                    if not self.monitoring:
                        return
                    time.sleep(1)
    
    def attempt_login(self) -> bool:
        """
        尝试登录校园网（使用工具类简化）
        
        返回:
            bool: 登录是否成功
        """
        try:
            # 使用 TimeUtils 检查暂停时段
            pause_config = self.config.get('pause_login', {})
            if TimeUtils.is_in_pause_period(pause_config):
                current_hour = datetime.datetime.now().hour
                start_hour = pause_config.get('start_hour', 0)
                end_hour = pause_config.get('end_hour', 6)
                self.log_message(f"⏰ 当前时间 {current_hour}:xx 在暂停登录时段（{start_hour}点-{end_hour}点），跳过登录")
                return False
            
            # 使用 LoginAttemptHandler 进行登录
            login_handler = LoginAttemptHandler(self.config)
            success = asyncio.run(login_handler.attempt_login())
            return success
                
        except Exception as e:
            self.log_message(f"❌ 登录过程中发生错误: {str(e)}")
            return False


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


def main():
    """
    主函数
    """
    try:
        print("校园网自动认证工具 - 简化命令行版本")
        print("正在检查配置...")
        
        # 检查配置
        if not check_config():
            print("\n请修复配置后重新运行")
            sys.exit(1)
        
        print("\n正在启动监控...")
        
        # 创建监控器并启动
        monitor = SimpleNetworkMonitor()
        monitor.start_monitoring()
    
    except KeyboardInterrupt:
        print("\n用户中断，程序退出")
        sys.exit(0)
    except Exception as e:
        print(f"程序运行出错: {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    main()