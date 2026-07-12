# 自定义脚本使用指南

本文档介绍如何使用 Campus-Auth 的自定义脚本功能，通过脚本实现自动化登录，无需启动浏览器。

## 目录

1. [简介](#简介)
2. [创建脚本](#创建脚本)
3. [脚本类型](#脚本类型)
4. [脚本格式](#脚本格式)
5. [示例](#示例)
6. [常见问题](#常见问题)

---

## 简介

自定义脚本功能允许你使用 `py`、`bat`、`ps1`、`sh`、`exe` 五种类型执行自动化任务。与浏览器任务相比，脚本任务：

- **资源占用更低** — 无需启动浏览器
- **执行速度更快** — 直接发送 HTTP 请求
- **灵活性更高** — 可使用多种脚本语言或可执行文件

## 创建脚本

### 通过 Web 界面创建

1. 打开 Campus-Auth Web 界面
2. 进入「自定义脚本」页面
3. 点击「新建脚本」
4. 填写脚本信息：
   - **脚本ID** — 唯一标识符，只能包含字母、数字和下划线
   - **名称** — 脚本显示名称
   - **描述** — 脚本说明（可选）
   - **类型** — 选择脚本类型（py / bat / ps1 / sh / exe）
   - **脚本内容** — 要执行的命令或代码
5. 点击「保存脚本」

### 通过 API 创建

```bash
curl -X PUT http://localhost:50721/api/scripts/my_script \
  -H "Content-Type: application/json" \
  -d '{
    "name": "我的登录脚本",
    "description": "使用 curl 登录校园网",
    "type": "bat",
    "content": "curl -X POST http://10.0.0.1/login -d username=test -d password=123"
  }'
```

## 脚本类型

系统支持以下 5 种脚本类型：

| 类型 | 说明 |
|------|------|
| `py` | Python 脚本，使用项目内置解释器执行 |
| `bat` | Windows 批处理脚本 |
| `ps1` | PowerShell 脚本，使用 powershell.exe (5.1) 执行 |
| `sh` | Unix Shell 脚本 |
| `exe` | 可执行文件，启动即返回（适合 GUI 程序） |

> **注意：** `ps1` 类型使用 Windows 自带的 `powershell.exe`（5.1 版本），而非 `pwsh.exe`（7+ 版本）。如需使用 PowerShell 7 的特性，请编写 `.bat` 包装脚本来调用 `pwsh.exe`。

> **注意：** `sh` 类型在 Windows 上需要安装 Git Bash 等兼容环境。系统不会预先检查是否存在，操作系统会在执行时自然报告错误。

## 脚本格式

脚本任务以 JSON 格式保存。

### 文本脚本（py / bat / ps1 / sh）

```json
{
  "type": "py",
  "name": "脚本名称",
  "description": "脚本描述",
  "content": "要执行的命令或代码"
}
```

### 可执行文件（exe）

```json
{
  "type": "exe",
  "name": "脚本名称",
  "description": "脚本描述",
  "path": "可执行文件路径"
}
```

### 字段说明

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `type` | string | 是 | 脚本类型，枚举值：`py`、`bat`、`ps1`、`sh`、`exe` |
| `name` | string | 否 | 脚本显示名称，默认使用脚本ID |
| `description` | string | 否 | 脚本描述 |
| `content` | string | 是（文本脚本） | 要执行的命令或代码 |
| `path` | string | 是（仅 `exe`） | 可执行文件的完整路径 |

## 示例

### 示例 1: 使用 curl 登录（bat）

```json
{
  "name": "curl 登录",
  "description": "使用 curl 发送 POST 请求登录校园网",
  "type": "bat",
  "content": "curl -X POST http://10.0.0.1/login -d \"username=test&password=123&operator=cmcc\""
}
```

### 示例 2: 使用 PowerShell 登录（ps1）

```json
{
  "name": "PowerShell 登录",
  "description": "使用 PowerShell 的 Invoke-WebRequest 登录",
  "type": "ps1",
  "content": "Invoke-WebRequest -Uri 'http://10.0.0.1/login' -Method POST -Body @{username='test'; password='123'; operator='cmcc'}"
}
```

### 示例 3: 使用 Python 登录（py）

```json
{
  "name": "Python 登录",
  "description": "使用 httpx 发送 POST 请求登录校园网",
  "type": "py",
  "content": "import httpx\nresp = httpx.post('http://10.0.0.1/login', data={'username': 'test', 'password': '123', 'operator': 'cmcc'})\nprint(f'HTTP {resp.status_code}')"
}
```

### 示例 4: 调用外部 Python 脚本文件（py）

```json
{
  "name": "执行外部脚本",
  "description": "通过 subprocess 调用外部 Python 脚本文件",
  "type": "py",
  "content": "import subprocess\nsubprocess.run(['python', 'C:\\\\Users\\\\username\\\\scripts\\\\login.py'])"
}
```

### 示例 5: 使用 PowerShell 执行外部脚本（ps1）

```json
{
  "name": "PowerShell 脚本",
  "description": "使用 PowerShell 执行外部脚本文件",
  "type": "ps1",
  "content": "& 'C:\\Users\\username\\scripts\\login.ps1'"
}
```

### 示例 6: 启动 GUI 应用程序（exe）

```json
{
  "name": "启动登录工具",
  "description": "启动外部 GUI 登录程序",
  "type": "exe",
  "path": "C:\\Program Files\\LoginTool\\LoginTool.exe"
}
```

## 常见问题

### Q: 为什么脚本执行失败？

**A:** 常见原因：

1. **类型选择错误** — 检查 `type` 是否与脚本内容匹配
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

**A:** 可以。对于文本脚本类型，在脚本内容中直接调用其他程序即可。对于可执行文件，使用 `exe` 类型并指定 `path` 字段：

```json
{
  "type": "exe",
  "name": "外部工具",
  "path": "C:\\Program Files\\SomeApp\\app.exe"
}
```

---

## 相关文档

- [任务编写指南](task-writing-guide.md) — 浏览器任务 JSON 编写指南
- [API 文档](../dev/api-reference.md) — 后端 API 接口说明
- [开发文档](../dev/architecture.md) — 系统架构和内部实现
