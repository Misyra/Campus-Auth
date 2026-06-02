#!/usr/bin/env python3
# name: HTTP 登录测试
# description: 使用 httpx 发送 POST 请求登录校园网
import httpx

# 按实际情况修改以下参数
LOGIN_URL = "http://10.0.0.1/login"
USERNAME = "your_username"
PASSWORD = "your_password"
ISP = "cmcc"  # 运营商：cmcc / unicom / telecom，无则留空

try:
    resp = httpx.post(LOGIN_URL, data={
        "username": USERNAME,
        "password": PASSWORD,
        "operator": ISP,
    }, timeout=30)
    print(f"HTTP {resp.status_code}")
except Exception as e:
    print(str(e))
    exit(1)
