#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
登录尝试处理器
"""

import datetime
import logging
from typing import Dict, Any

from .logging import LoggerSetup
from .time import TimeUtils


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
    
    async def attempt_login(self, skip_pause_check: bool = False) -> tuple[bool, str]:
        """
        尝试登录校园网（统一实现）
        
        参数:
            skip_pause_check: 是否跳过暂停时间检查
        
        返回:
            tuple[bool, str]: (是否成功, 详细信息)
        """
        try:
            # 检查当前时间是否在暂停登录时段（如果没有跳过检查）
            if not skip_pause_check:
                pause_config = self.config.get('pause_login', {})
                
                if TimeUtils.is_in_pause_period(pause_config):
                    current_hour = datetime.datetime.now().hour
                    start_hour = pause_config.get('start_hour', 0)
                    end_hour = pause_config.get('end_hour', 6)
                    msg = f"当前时间 {current_hour}:xx 在暂停登录时段（{start_hour}点-{end_hour}点），跳过登录"
                    self.logger.info(f"⏰ {msg}")
                    return False, msg
            
            # 使用延迟导入避免循环依赖
            return await self._perform_login_with_auth_class()
                
        except Exception as e:
            error_msg = f"登录过程中发生错误: {str(e)}"
            self.logger.error(f"❌ {error_msg}")
            return False, error_msg
    
    async def _perform_login_with_auth_class(self) -> tuple[bool, str]:
        """使用认证类执行登录（延迟导入）"""
        try:
            from ..campus_login import EnhancedCampusNetworkAuth
            
            auth = EnhancedCampusNetworkAuth(self.config)
            success, message = await auth.authenticate()
            
            if success:
                self.logger.info(f"✅ 校园网登录成功: {message}")
                return True, message
            else:
                self.logger.error(f"❌ 校园网登录失败: {message}")
                return False, message
                
        except ImportError as e:
            error_msg = f"无法导入认证模块: {e}"
            self.logger.error(f"❌ {error_msg}")
            return False, error_msg
        except Exception as e:
            error_msg = f"登录执行失败: {str(e)}"
            self.logger.error(f"❌ {error_msg}")
            return False, error_msg
