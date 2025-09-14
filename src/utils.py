#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
公共工具类 - 解决代码重复问题
"""

import datetime
import logging
import os
import random
from typing import Dict, Any, Tuple


class TimeUtils:
    """时间相关工具类"""
    
    @staticmethod
    def is_in_pause_period(pause_config: Dict[str, Any]) -> bool:
        """
        检查当前时间是否在暂停时段内
        
        参数:
            pause_config: 暂停配置字典
            
        返回:
            bool: 是否在暂停时段
        """
        if not pause_config.get('enabled', True):
            return False
            
        current_hour = datetime.datetime.now().hour
        start_hour = pause_config.get('start_hour', 0)
        end_hour = pause_config.get('end_hour', 6)
        
        # 处理跨天的情况（如23点到6点）
        if start_hour <= end_hour:
            # 同一天内的时间段（如0点到6点）
            return start_hour <= current_hour < end_hour
        else:
            # 跨天的时间段（如23点到6点）
            return current_hour >= start_hour or current_hour < end_hour


class ConfigAdapter:
    """配置适配器类"""
    
    @staticmethod
    def create_auth_config(gui_config: Dict[str, Any], base_config: Dict[str, Any]) -> Dict[str, Any]:
        """
        将GUI配置转换为认证配置
        
        参数:
            gui_config: GUI配置字典
            base_config: 基础配置字典
            
        返回:
            Dict[str, Any]: 认证配置字典
        """
        # 创建认证配置的副本
        auth_config = base_config.copy()
        
        # 用户名保持原样，不添加任何后缀
        username = gui_config.get('username', '')
        # 运营商通过下拉框单独处理，不添加到用户名
        full_username = username
        
        # 更新认证配置
        auth_config.update({
            'username': full_username,
            'password': gui_config.get('password', ''),
        })
        
        # 更新浏览器设置
        if 'browser_settings' in auth_config:
            auth_config['browser_settings']['headless'] = gui_config.get('headless', False)
        
        return auth_config


class LoginAttemptHandler:
    """登录尝试处理器 - 统一登录逻辑"""
    
    def __init__(self, config: Dict[str, Any]):
        """
        初始化登录处理器
        
        参数:
            config: 配置字典
        """
        self.config = config
        self.logger = logging.getLogger(__name__)
    
    async def attempt_login(self) -> bool:
        """
        尝试登录校园网（统一实现）
        
        返回:
            bool: 登录是否成功
        """
        try:
            # 检查当前时间是否在暂停登录时段
            pause_config = self.config.get('pause_login', {})
            
            if TimeUtils.is_in_pause_period(pause_config):
                current_hour = datetime.datetime.now().hour
                start_hour = pause_config.get('start_hour', 0)
                end_hour = pause_config.get('end_hour', 6)
                self.logger.info(f"⏰ 当前时间 {current_hour}:xx 在暂停登录时段（{start_hour}点-{end_hour}点），跳过登录")
                return False
            
            # 动态导入以避免循环依赖
            from campus_login import EnhancedCampusNetworkAuth
            
            # 创建登录实例
            auth = EnhancedCampusNetworkAuth(self.config)
            
            # 尝试登录（异步调用）
            try:
                success, message = await auth.authenticate()
            except Exception as e:
                self.logger.error(f"❌ 校园网登录失败: {str(e)}")
                return False
            
            if success:
                self.logger.info(f"✅ 校园网登录成功: {message}")
                return True
            else:
                self.logger.error(f"❌ 校园网登录失败: {message}")
                return False
                
        except Exception as e:
            self.logger.error(f"❌ 登录过程中发生错误: {str(e)}")
            return False


class LoggerSetup:
    """日志设置工具类 - 避免重复的日志设置代码"""
    
    @staticmethod
    def setup_logger(name: str, config: Dict[str, Any]) -> logging.Logger:
        """
        设置日志记录器
        
        参数:
            name: logger名称
            config: 日志配置
            
        返回:
            logging.Logger: 配置好的logger
        """
        logger = logging.getLogger(name)
        
        # 如果logger已经有处理器，说明已经配置过，直接返回
        if logger.handlers:
            return logger
            
        # 设置日志级别
        log_level = config.get("level", "INFO")
        logger.setLevel(getattr(logging, log_level.upper()))
        
        # 创建格式器
        formatter = logging.Formatter(
            config.get("format", "%(asctime)s - %(levelname)s - %(message)s")
        )
        
        # 添加文件处理器
        log_file = config.get("file")
        if log_file:
            try:
                # 确保日志目录存在
                log_dir = os.path.dirname(log_file)
                if log_dir and not os.path.exists(log_dir):
                    os.makedirs(log_dir, exist_ok=True)
                    
                file_handler = logging.FileHandler(log_file, encoding='utf-8')
                file_handler.setFormatter(formatter)
                logger.addHandler(file_handler)
            except Exception as e:
                # 日志文件创建失败时，使用控制台输出
                print(f"警告: 无法创建日志文件 {log_file}: {e}")
        
        # 防止日志传播到根logger，避免重复输出
        logger.propagate = False
        
        return logger


def get_runtime_stats(start_time: float, check_count: int) -> Tuple[str, str]:
    """
    获取运行时统计信息
    
    参数:
        start_time: 开始时间戳
        check_count: 检测次数
        
    返回:
        Tuple[str, str]: (运行时间字符串, 统计信息字符串)
    """
    if start_time:
        elapsed = int(datetime.datetime.now().timestamp() - start_time)
        hours = elapsed // 3600
        minutes = (elapsed % 3600) // 60
        seconds = elapsed % 60
        runtime_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    else:
        runtime_str = "00:00:00"
    
    stats_str = f"检测次数: {check_count}"
    
    return runtime_str, stats_str


class ConfigLoader:
    """配置加载工具类 - 统一管理所有配置加载逻辑"""
    
    @staticmethod
    def _str_to_bool(value: str) -> bool:
        """将字符串转换为布尔值"""
        return value.lower() in ('true', '1', 'yes', 'on')

    @staticmethod
    def _get_int_env(key: str, default: int) -> int:
        """安全获取整数环境变量"""
        try:
            return int(os.getenv(key, str(default)))
        except ValueError:
            return default

    @staticmethod
    def _load_basic_config() -> dict:
        """加载基础配置"""
        return {
            "username": os.getenv("CAMPUS_USERNAME", ""),
            "password": os.getenv("CAMPUS_PASSWORD", ""),
            "auth_url": os.getenv("CAMPUS_AUTH_URL", "http://172.29.0.2"),
            "isp": os.getenv("CAMPUS_ISP", "@cmcc"),
            "auto_start_monitoring": ConfigLoader._str_to_bool(os.getenv("AUTO_START_MONITORING", "false"))
        }

    @staticmethod
    def _load_browser_config() -> dict:
        """加载浏览器配置"""
        # 随机User-Agent池，避免被识别为机器人
        user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/121.0",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:109.0) Gecko/20100101 Firefox/121.0"
        ]
        
        default_user_agent = random.choice(user_agents)
        
        return {
            "headless": ConfigLoader._str_to_bool(os.getenv("BROWSER_HEADLESS", "false")),
            "timeout": ConfigLoader._get_int_env("BROWSER_TIMEOUT", 10000),
            "user_agent": os.getenv("BROWSER_USER_AGENT", default_user_agent),
            "user_agents": user_agents
        }

    @staticmethod
    def _load_other_configs() -> dict:
        """加载其他配置项"""
        return {
            "retry_settings": {
                "max_retries": ConfigLoader._get_int_env("RETRY_MAX_RETRIES", 3),
                "retry_interval": ConfigLoader._get_int_env("RETRY_INTERVAL", 5)
            },
            "logging": {
                "level": os.getenv("LOG_LEVEL", "INFO"),
                "format": os.getenv("LOG_FORMAT", "%(asctime)s - %(levelname)s - %(message)s"),
                "file": os.getenv("LOG_FILE", "logs/campus_auth.log") or None
            },
            "pause_login": {
                "enabled": ConfigLoader._str_to_bool(os.getenv("PAUSE_LOGIN_ENABLED", "true")),
                "start_hour": ConfigLoader._get_int_env("PAUSE_LOGIN_START_HOUR", 0),
                "end_hour": ConfigLoader._get_int_env("PAUSE_LOGIN_END_HOUR", 6)
            },
            "monitor": {
                "interval": ConfigLoader._get_int_env("MONITOR_INTERVAL", 240),
                "ping_targets": [target.strip() for target in os.getenv("PING_TARGETS", "8.8.8.8,114.114.114.114,baidu.com").split(",") if target.strip()]
            }
        }

    @staticmethod
    def load_config_from_env() -> dict:
        """从环境变量加载配置"""
        config = ConfigLoader._load_basic_config()
        config["browser_settings"] = ConfigLoader._load_browser_config()
        config.update(ConfigLoader._load_other_configs())
        return config


class ConfigValidator:
    """配置验证工具类 - 统一管理配置验证逻辑"""
    
    @staticmethod
    def validate_gui_config(username: str, password: str, check_interval: str) -> tuple[bool, str]:
        """
        验证GUI配置是否有效
        
        参数:
            username: 用户名
            password: 密码
            check_interval: 检测间隔
            
        返回:
            tuple[bool, str]: (是否有效, 错误信息)
        """
        # 验证必填字段
        username = username.strip()
        password = password.strip()
        
        if not username:
            return False, "账号不能为空"
        if not password:
            return False, "密码不能为空"
            
        # 验证账号格式（基本验证）
        if len(username) < 2:
            return False, "账号长度不能少于2位"
            
        # 验证密码格式（基本验证）
        if len(password) < 2:
            return False, "密码长度不能少于2位"
        
        # 验证检测间隔
        check_interval = check_interval.strip()
        try:
            interval_int = int(check_interval)
            if interval_int < 1:
                return False, "检测间隔必须大于0"
            if interval_int > 1440:  # 24小时
                return False, "检测间隔不能超过1440分钟（24小时）"
        except ValueError:
            return False, "检测间隔必须是正整数"
        
        return True, ""
    
    @staticmethod
    def validate_env_config(config: dict) -> tuple[bool, str]:
        """
        验证环境配置是否完整
        
        参数:
            config: 配置字典
            
        返回:
            tuple[bool, str]: (是否有效, 错误信息)
        """
        # 检查必要配置
        username = config.get('username')
        password = config.get('password')
        auth_url = config.get('auth_url')
        
        if not username or not password:
            return False, "缺少用户名或密码"
        
        if not auth_url:
            return False, "缺少认证地址"
        
        return True, ""


class BrowserManager:
    """浏览器管理工具类 - 统一管理浏览器启动和清理"""
    
    def __init__(self, config: dict):
        """
        初始化浏览器管理器
        
        参数:
            config: 配置字典
        """
        self.config = config
        self.browser_settings = config.get("browser_settings", {})
        self.logger = logging.getLogger(__name__)
        
        # 浏览器相关属性
        self.playwright = None
        self.browser = None
        self.page = None
    
    async def start_browser(self) -> bool:
        """
        启动浏览器
        
        返回:
            bool: 是否启动成功
        """
        try:
            from playwright.async_api import async_playwright
            
            self.playwright = await async_playwright().start()
            headless = self.browser_settings.get("headless", False)
            
            # 启动浏览器时添加更多反检测参数
            browser_args = [
                '--no-sandbox',
                '--disable-blink-features=AutomationControlled',
                '--disable-features=VizDisplayCompositor',
                '--disable-web-security',
                '--disable-features=TranslateUI',
                '--disable-ipc-flooding-protection',
                '--no-first-run',
                '--no-default-browser-check',
                '--disable-default-apps',
                '--disable-popup-blocking',
                '--disable-extensions',
                '--disable-plugins',
                '--disable-images',
                '--disable-javascript',
                '--disable-plugins-discovery',
                '--disable-preconnect',
                '--disable-background-timer-throttling',
                '--disable-backgrounding-occluded-windows',
                '--disable-renderer-backgrounding'
            ]
            
            self.browser = await self.playwright.chromium.launch(
                headless=headless,
                args=browser_args
            )
            
            # 创建页面时添加反检测上下文
            context = await self.browser.new_context(
                viewport={'width': 1920, 'height': 1080},
                user_agent=self._get_random_user_agent(),
                extra_http_headers={
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
                    'Accept-Encoding': 'gzip, deflate',
                    'DNT': '1',
                    'Connection': 'keep-alive',
                    'Upgrade-Insecure-Requests': '1',
                }
            )
            
            self.page = await context.new_page()
            
            # 注入反检测脚本
            await self.page.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined,
                });
                
                Object.defineProperty(navigator, 'plugins', {
                    get: () => [1, 2, 3, 4, 5],
                });
                
                Object.defineProperty(navigator, 'languages', {
                    get: () => ['zh-CN', 'zh', 'en'],
                });
                
                window.chrome = {
                    runtime: {},
                };
            """)

            self.logger.info(f"浏览器已启动，无头模式: {headless}")
            return True
            
        except Exception as e:
            self.logger.error(f"启动浏览器失败: {e}")
            return False
    
    def _get_random_user_agent(self) -> str:
        """获取随机User-Agent"""
        user_agents = self.browser_settings.get("user_agents", [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ])
        return random.choice(user_agents)
    
    async def cleanup(self) -> None:
        """清理浏览器资源"""
        try:
            if self.browser:
                await self.browser.close()
                self.browser = None
            if self.playwright:
                await self.playwright.stop()
                self.playwright = None
            self.page = None
        except Exception as e:
            self.logger.warning(f"清理浏览器资源时发生错误: {e}")