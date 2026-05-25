#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
异常处理工具类
"""


class LoginCancelledError(Exception):
    """登录操作被取消的信号异常"""

    pass


class DecryptionError(Exception):
    """密码解密失败异常（密钥变更或数据损坏）"""

    pass
