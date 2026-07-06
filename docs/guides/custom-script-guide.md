# 自定义脚本使用指南

本文档介绍如何使用 Campus-Auth 的自定义脚本功能，通过脚本实现自动化登录，无需启动浏览器。

## 目录

1. [简介](#简介)
2. [创建脚本](#创建脚本)
3. [执行程序选择](#执行程序选择)
4. [脚本格式](#脚本格式)
5. [示例](#示例)
6. [常见问题](#常见问题)

---

## 简介

自定义脚本功能允许你使用 Python、PowerShell、cmd 或其他程序执行自动化任务。与浏览器任务相比，脚本任务：

- **资源占用更低** — 无需启动浏览器
- **执行速度更快** — 直接发送 HTTP 请求
- **灵活性更高** — 可使用任意编程语言或工具

## 创建脚本

### 通过 Web 界面创建

1. 打开 Campus-Auth Web 界面
2. 进入「自定义脚本」页面
3. 点击「新建脚本」
4. 填写脚本信息：
   - **脚本ID** — 唯一标识符，只能包含字母、数字和下划线
   - **名称** — 脚本显示名称
   - **描述** — 脚本说明（可选）
   - **执行程序** — 选择用于执行脚本的程序
   - **脚本内容** — 要执行的命令或代码
5. 点击「保存脚本」

### 通过 API 创建

```bash
curl -X PUT http://localhost:50721/api/scripts/my_script \
  -H "Content-Type: application/json" \
  -d '{
    "name": "我的登录脚本",
    "description": "使用 curl 登录校园网",
    "content": "curl -X POST http://10.0.0.1/login -d username=test -d password=123",
    "binary_path": "C:\\Windows\\System32\\cmd.exe"
  }'
```

## 执行程序选择

### Windows

| 程序 | 路径 | 适用场景 |
|------|------|----------|
| Python | `C:\Users\...\python.exe` | 执行 Python 代码 |
| PowerShell 7 | `C:\Program Files\PowerShell\7\pwsh.exe` | 执行 PowerShell 命令 |
| Windows PowerShell | `C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe` | 执行 PowerShell 命令（旧版） |
| cmd | `C:\Windows\System32\cmd.exe` | 执行批处理命令 |

### Linux / macOS

| 程序 | 路径 | 适用场景 |
|------|------|----------|
| Python | `/usr/bin/python3` | 执行 Python 代码 |
| Bash | `/bin/bash` | 执行 Shell 脚本 |
| Sh | `/bin/sh` | 执行 POSIX Shell 命令 |

### 选择建议

- **Python 脚本** → 选择 Python 解释器
- **PowerShell 命令** → 选择 PowerShell
- **cmd 命令** → 选择 cmd
- **Shell 脚本** → 选择 bash 或 sh

## 脚本格式

脚本任务以 JSON 格式保存，包含以下字段：

```json
{
  "type": "script",
  "name": "脚本名称",
  "description": "脚本描述",
  "binary_path": "执行程序路径",
  "content": "要执行的命令或代码"
}
```

### 字段说明

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `type` | string | 是 | 固定值 `"script"` |
| `name` | string | 否 | 脚本显示名称，默认使用脚本ID |
| `description` | string | 否 | 脚本描述 |
| `binary_path` | string | 否 | 执行程序完整路径，留空则使用 Campus-Auth 内置的 Python 解释器 |
| `content` | string | 是 | 要执行的命令或代码 |

## 示例

### 示例 1: 使用 curl 登录（cmd）

```json
{
  "name": "curl 登录",
  "description": "使用 curl 发送 POST 请求登录校园网",
  "content": "curl -X POST http://10.0.0.1/login -d \"username=test&password=123&operator=cmcc\"",
  "binary_path": "C:\\Windows\\System32\\cmd.exe"
}
```

### 示例 2: 使用 PowerShell 登录

```json
{
  "name": "PowerShell 登录",
  "description": "使用 PowerShell 的 Invoke-WebRequest 登录",
  "content": "Invoke-WebRequest -Uri 'http://10.0.0.1/login' -Method POST -Body @{username='test'; password='123'; operator='cmcc'}",
  "binary_path": "C:\\Program Files\\PowerShell\\7\\pwsh.exe"
}
```

### 示例 3: 使用 Python 登录

```json
{
  "name": "Python 登录",
  "description": "使用 httpx 发送 POST 请求登录校园网",
  "content": "import httpx\nresp = httpx.post('http://10.0.0.1/login', data={'username': 'test', 'password': '123', 'operator': 'cmcc'})\nprint(f'HTTP {resp.status_code}')",
  "binary_path": "C:\\Users\\username\\AppData\\Local\\Programs\\Python\\Python310\\python.exe"
}
```

### 示例 4: 执行外部脚本文件

```json
{
  "name": "执行外部脚本",
  "description": "调用外部 Python 脚本文件",
  "content": "C:\\Users\\username\\scripts\\login.py",
  "binary_path": "C:\\Users\\username\\AppData\\Local\\Programs\\Python\\Python310\\python.exe"
}
```

### 示例 5: 使用 PowerShell 执行外部脚本

```json
{
  "name": "PowerShell 脚本",
  "description": "使用 PowerShell 执行外部脚本文件",
  "content": "C:\\Users\\username\\scripts\\login.ps1",
  "binary_path": "C:\\Program Files\\PowerShell\\7\\pwsh.exe"
}
```

## 常见问题

### Q: 为什么脚本执行失败？

**A:** 常见原因：

1. **执行程序路径错误** — 检查 `binary_path` 是否正确
2. **脚本内容语法错误** — 检查命令或代码是否正确
3. **权限不足** — 某些操作需要管理员权限
4. **网络问题** — 检查网络连接和目标服务器状态

### Q: 如何查看脚本执行日志？

**A:** 在 Web 界面的「日志」页面查看，或通过 API 获取：

```bash
curl http://localhost:50721/api/logs
```

### Q: 脚本执行时会弹出窗口吗？

**A:** 在 Windows 上，系统会自动隐藏子进程窗口，不会弹出控制台窗口。

### Q: 如何测试脚本？

**A:** 在 Web 界面的「自定义脚本」页面，点击脚本右侧的「运行」按钮即可测试。

### Q: 脚本可以使用环境变量吗？

**A:** 可以。系统会传递以下环境变量给子进程：

- `PATH` — 系统路径
- `HOME` / `USERPROFILE` — 用户目录
- `TEMP` / `TMP` — 临时目录
- `PYTHONIOENCODING` — Python 编码（固定为 `utf-8`）

此外，Campus-Auth 还会自动注入登录相关变量（`USERNAME`、`PASSWORD`、`ISP`、`LOGIN_URL`），可在脚本中直接使用。

### Q: 如何设置脚本超时时间？

**A:** 在 Web 界面的「系统设置」页面中修改「脚本超时」参数，默认为 60 秒。

### Q: 脚本可以调用其他程序吗？

**A:** 可以。在脚本内容中直接调用其他程序的完整路径即可。例如：

```json
{
  "content": "C:\\Program Files\\SomeApp\\app.exe --arg1 --arg2",
  "binary_path": "C:\\Windows\\System32\\cmd.exe"
}
```

---

## 相关文档

- [任务编写指南](task-writing-guide.md) — 浏览器任务 JSON 编写指南
- [API 文档](../dev/api-reference.md) — 后端 API 接口说明
- [开发文档](../dev/architecture.md) — 系统架构和内部实现
