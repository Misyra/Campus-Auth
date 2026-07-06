#!/usr/bin/env python3
"""
异常处理工具类
"""


class LoginCancelledError(Exception):
    """登录操作被取消的信号异常"""

    pass
