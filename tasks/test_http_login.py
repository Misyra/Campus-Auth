#!/usr/bin/env python3
# name: HTTP 登录测试
# description: 使用 urllib 发送 POST 请求登录校园网，无需第三方库
import os
import urllib.request
import urllib.parse

# 从环境变量获取登录参数
username = os.environ.get("CAMPUS_USERNAME", "")
password = os.environ.get("CAMPUS_PASSWORD", "")
isp = os.environ.get("CAMPUS_ISP", "")
login_url = os.environ.get("CAMPUS_URL", "")

if not login_url:
    print("CAMPUS_URL 未设置，请先在设置中配置认证地址")
    exit(1)

if not username:
    print("CAMPUS_USERNAME 未设置，请先在设置中配置用户名")
    exit(1)

# 构建 POST 数据（根据实际校园网认证接口调整字段名）
post_data = urllib.parse.urlencode({
    "username": username,
    "password": password,
    "operator": isp,
}).encode("utf-8")

try:
    req = urllib.request.Request(
        login_url,
        data=post_data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        print(f"HTTP {resp.status}")
except urllib.error.HTTPError as e:
    print(f"HTTP {e.code}: {e.reason}")
    exit(1)
except Exception as e:
    print(str(e))
    exit(1)
