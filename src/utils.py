#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
公共工具类 - 解决代码重复问题
"""

import datetime
import logging
import logging.handlers
import os
import random
from typing import Dict, Any, Tuple, Type, Optional
from playwright.async_api import TimeoutError as PlaywrightTimeoutError


class ExceptionHandler:
    """异常处理增强器 - 按项目规范处理具体异常类型"""
    
    @staticmethod
    def handle_playwright_timeout(e: PlaywrightTimeoutError, operation: str, logger: logging.Logger) -> str:
        """处理Playwright超时异常"""
        error_msg = f"{operation}超时: {str(e)}"
        logger.error(error_msg)
        return error_msg
    
    @staticmethod
    def handle_network_error(e: Exception, operation: str, logger: logging.Logger) -> str:
        """处理网络相关异常"""
        error_msg = f"{operation}网络错误: {str(e)}"
        logger.error(error_msg)
        return error_msg
    
    @staticmethod
    def handle_config_error(e: Exception, operation: str, logger: logging.Logger) -> str:
        """处理配置相关异常"""
        error_msg = f"{operation}配置错误: {str(e)}"
        logger.error(error_msg)
        return error_msg
    
    @staticmethod
    def wrap_with_specific_handling(operation: str, logger: logging.Logger):
        """装饰器：为方法添加具体异常处理"""
        def decorator(func):
            async def wrapper(*args, **kwargs):
                try:
                    return await func(*args, **kwargs)
                except PlaywrightTimeoutError as e:
                    error_msg = ExceptionHandler.handle_playwright_timeout(e, operation, logger)
                    raise PlaywrightTimeoutError(error_msg) from e
                except (ConnectionError, OSError) as e:
                    error_msg = ExceptionHandler.handle_network_error(e, operation, logger)
                    raise ConnectionError(error_msg) from e
                except (ValueError, KeyError, TypeError) as e:
                    error_msg = ExceptionHandler.handle_config_error(e, operation, logger)
                    raise ValueError(error_msg) from e
                except Exception as e:
                    # 最后才使用通用异常处理
                    error_msg = f"{operation}发生未知错误: {str(e)}"
                    logger.error(error_msg)
                    raise RuntimeError(error_msg) from e
            return wrapper
        return decorator


class SimpleRetryHandler:
    """简化重试处理器 - 使用简单的重试机制"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.retry_settings = config.get('retry_settings', {})
        self.logger = LoggerSetup.setup_logger(f"{__name__}_retry", config.get('logging', {}))
    
    async def retry_with_simple_backoff(self, operation, max_retries: int = None) -> Tuple[bool, Any, str]:
        """
        简单的重试机制
        
        参数:
            operation: 要重试的异步操作
            max_retries: 最大重试次数
            
        返回:
            Tuple[bool, Any, str]: (是否成功, 结果, 错误信息)
        """
        if max_retries is None:
            max_retries = self.retry_settings.get('max_retries', 3)
        
        retry_interval = self.retry_settings.get('retry_interval', 5)
        last_error = None
        
        for attempt in range(max_retries):
            try:
                result = await operation()
                if attempt > 0:
                    self.logger.info(f"✅ 操作在第{attempt + 1}次尝试后成功")
                return True, result, ""
                
            except Exception as e:
                last_error = e
                
                if attempt < max_retries - 1:  # 不是最后一次尝试
                    self.logger.warning(
                        f"❌ 第{attempt + 1}次尝试失败: {str(e)}, "
                        f"{retry_interval}秒后重试..."
                    )
                    
                    # 简单等待
                    import asyncio
                    await asyncio.sleep(retry_interval)
                else:
                    self.logger.error(f"❌ 所有{max_retries}次尝试均失败")
        
        error_msg = f"重试{max_retries}次后仍然失败，最后错误: {str(last_error)}"
        return False, None, error_msg


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
    """登录尝试处理器 - 统一登录逻辑（解决循环依赖）"""
    
    def __init__(self, config: Dict[str, Any]):
        """
        初始化登录处理器
        
        参数:
            config: 配置字典
        """
        self.config = config
        self.logger = LoggerSetup.setup_logger(f"{__name__}_login", config.get('logging', {}))
    
    async def attempt_login(self, skip_pause_check: bool = False) -> bool:
        """
        尝试登录校园网（统一实现）
        
        参数:
            skip_pause_check: 是否跳过暂停时间检查
        
        返回:
            bool: 登录是否成功
        """
        try:
            # 检查当前时间是否在暂停登录时段（如果没有跳过检查）
            if not skip_pause_check:
                pause_config = self.config.get('pause_login', {})
                
                if TimeUtils.is_in_pause_period(pause_config):
                    current_hour = datetime.datetime.now().hour
                    start_hour = pause_config.get('start_hour', 0)
                    end_hour = pause_config.get('end_hour', 6)
                    self.logger.info(f"⏰ 当前时间 {current_hour}:xx 在暂停登录时段（{start_hour}点-{end_hour}点），跳过登录")
                    return False
            
            # 使用延迟导入避免循环依赖 - 但使用更安全的方式
            return await self._perform_login_with_auth_class()
                
        except Exception as e:
            self.logger.error(f"❌ 登录过程中发生错误: {str(e)}")
            return False
    
    async def _perform_login_with_auth_class(self) -> bool:
        """使用认证类执行登录（延迟导入）"""
        try:
            # 延迟导入避免循环依赖
            from campus_login import EnhancedCampusNetworkAuth
            
            # 创建登录实例
            auth = EnhancedCampusNetworkAuth(self.config)
            
            # 尝试登录（异步调用）
            success, message = await auth.authenticate()
            
            if success:
                self.logger.info(f"✅ 校园网登录成功: {message}")
                return True
            else:
                self.logger.error(f"❌ 校园网登录失败: {message}")
                return False
                
        except ImportError as e:
            self.logger.error(f"❌ 无法导入认证模块: {e}")
            return False
        except Exception as e:
            self.logger.error(f"❌ 登录执行失败: {str(e)}")
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
        
        # 添加文件处理器（带轮转功能）
        log_file = config.get("file")
        if log_file:
            try:
                # 确保日志目录存在
                log_dir = os.path.dirname(log_file)
                if log_dir and not os.path.exists(log_dir):
                    os.makedirs(log_dir, exist_ok=True)
                
                # 使用RotatingFileHandler实现日志轮转 - 优化参数减少磁盘占用
                # maxBytes: 1MB = 1 * 1024 * 1024 bytes (从2MB降低到1MB)
                # backupCount: 保疙3个备份文件 (从5个降低到3个)
                file_handler = logging.handlers.RotatingFileHandler(
                    log_file, 
                    maxBytes=1 * 1024 * 1024,  # 1MB
                    backupCount=3,
                    encoding='utf-8'
                )
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
        # 使用固定的User-Agent，简化逻辑
        default_user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        
        return {
            "headless": ConfigLoader._str_to_bool(os.getenv("BROWSER_HEADLESS", "false")),
            "timeout": ConfigLoader._get_int_env("BROWSER_TIMEOUT", 8000),  # 从10000降低到8000ms
            "user_agent": os.getenv("BROWSER_USER_AGENT", default_user_agent),
            "low_resource_mode": ConfigLoader._str_to_bool(os.getenv("BROWSER_LOW_RESOURCE_MODE", "true"))  # 新增低资源模式
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


class BrowserContextManager:
    """浏览器上下文管理器 - 使用异步上下文管理器确保资源正确释放"""
    
    def __init__(self, config: dict):
        """
        初始化浏览器上下文管理器
        
        参数:
            config: 配置字典
        """
        self.config = config
        self.browser_settings = config.get("browser_settings", {})
        self.logger = LoggerSetup.setup_logger(f"{__name__}_browser", config.get('logging', {}))
        
        # 浏览器相关属性
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None
    
    async def __aenter__(self):
        """异步上下文管理器入口"""
        await self._start_browser()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器出口 - 确保资源总是被释放"""
        await self._cleanup_browser()
        # 如果有异常，记录但不抑制
        if exc_type:
            self.logger.error(f"浏览器操作异常: {exc_type.__name__}: {exc_val}")
        return False  # 不抑制异常
    
    async def _start_browser(self) -> None:
        """启动浏览器（内部方法）"""
        try:
            from playwright.async_api import async_playwright
            
            self.playwright = await async_playwright().start()
            headless = self.browser_settings.get("headless", False)
            
            # 统一的浏览器启动参数
            browser_args = self._get_browser_args()
            
            self.browser = await self.playwright.chromium.launch(
                headless=headless,
                args=browser_args
            )
            
            # 创建浏览器上下文 - 优化视口大小减少内存占用
            self.context = await self.browser.new_context(
                viewport={'width': 1024, 'height': 768},  # 从1920x1080缩小到1024x768
                user_agent=self.browser_settings.get("user_agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"),
                extra_http_headers=self._get_default_headers()
            )
            
            # 创建页面
            self.page = await self.context.new_page()

            self.logger.info(f"浏览器已启动，无头模式: {headless}")
            
        except Exception as e:
            self.logger.error(f"启动浏览器失败: {e}")
            # 启动失败时也要清理资源
            await self._cleanup_browser()
            raise
    
    def _get_browser_args(self) -> list[str]:
        """获取优化的浏览器启动参数，减少内存和资源占用"""
        return [
            '--no-sandbox',
            '--disable-web-security',
            '--disable-dev-shm-usage',  # 解决Docker环境下的内存问题
            '--disable-gpu',  # 禁用GPU加速，减少资源占用
            '--disable-extensions',  # 禁用扩展
            '--disable-plugins',  # 禁用插件
            '--disable-images',  # 禁用图片加载，提高性能
            '--memory-pressure-off',  # 关闭内存压力检测
            '--max_old_space_size=256'  # 限制内存使用
        ]
    
    def _get_default_headers(self) -> dict[str, str]:
        """获取简单的HTTP头"""
        return {
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8'
        }
    
    async def _cleanup_browser(self) -> None:
        """清理浏览器资源（内部方法）"""
        cleanup_errors = []
        
        # 按顺序清理资源
        try:
            if self.page:
                await self.page.close()
                self.page = None
        except Exception as e:
            cleanup_errors.append(f"关闭页面失败: {e}")
        
        try:
            if self.context:
                await self.context.close()
                self.context = None
        except Exception as e:
            cleanup_errors.append(f"关闭上下文失败: {e}")
        
        try:
            if self.browser:
                await self.browser.close()
                self.browser = None
        except Exception as e:
            cleanup_errors.append(f"关闭浏览器失败: {e}")
        
        try:
            if self.playwright:
                await self.playwright.stop()
                self.playwright = None
        except Exception as e:
            cleanup_errors.append(f"停止playwright失败: {e}")
        
        # 如果有清理错误，记录但不抛出异常
        if cleanup_errors:
            self.logger.warning(f"浏览器资源清理时出现错误: {'; '.join(cleanup_errors)}")
        else:
            self.logger.debug("浏览器资源已完全清理")
    
    async def navigate_to(self, url: str, timeout: int = None) -> bool:
        """导航到指定URL"""
        if not self.page:
            raise RuntimeError("浏览器未启动，请在上下文管理器中使用")
        
        try:
            timeout = timeout or self.browser_settings.get("timeout", 10000)
            await self.page.goto(url, timeout=timeout)
            await self.page.wait_for_load_state("networkidle", timeout=timeout)
            return True
        except Exception as e:
            self.logger.error(f"导航到 {url} 失败: {e}")
            return False
    
    async def take_screenshot(self, path: str = None) -> str:
        """截图功能"""
        if not self.page:
            raise RuntimeError("浏览器未启动，请在上下文管理器中使用")
        
        if not path:
            import time
            path = f"screenshot_{int(time.time())}.png"
        
        try:
            await self.page.screenshot(path=path)
            self.logger.info(f"截图已保存: {path}")
            return path
        except Exception as e:
            self.logger.error(f"截图失败: {e}")
            raise