# API 接口文档

> 本文档汇总 Campus-Auth 所有 HTTP API 和 WebSocket 接口，供开发联调或前后端扩展时查阅。当前版本：v4.1.0。
>
> 后端基于 FastAPI，所有 API 端点（除 `/` 外）均在 OpenAPI schema 中暴露，可访问 `/docs` 查看 Swagger 文档。

## 错误响应规范

| 场景 | 响应方式 | HTTP 状态码 |
|------|----------|:-----------:|
| 资源不存在 | `HTTPException` | 404 |
| 参数非法 / 校验失败 | `HTTPException` / `ValueError` 异常处理 | 400 / 422 |
| 业务可预期失败 | `ApiResponse(success=False)` | 200 |
| 程序异常（未捕获） | 全局异常处理器 → `JSONResponse` | 500 |
| 文件被占用 | `HTTPException` | 409 |

**区分说明：**
- **业务失败**：登录认证失败、任务执行超时、配置验证不通过 — 正常业务流程的一部分
- **程序异常**：配置写入失败、文件系统错误、未处理的 TypeError — 程序 bug

**关键原则：**
1. `ApiResponse(success=False)` 只用于业务可预期失败，返回 HTTP 200
2. 未捕获异常统一返回 500，不要用 `ApiResponse(success=False, message=str(e))` 掩盖
3. 资源不存在用 404，不要返回 200 + `success=false`
4. `ValueError` 在路由层统一捕获为 400（通过 `_handle_config_error` 或 `ValueError` 异常处理器）

**前端处理：**
- 4xx/5xx 状态码 → Axios 拦截器统一处理
- 200 + `success=false` → 业务层处理

**统一响应模型 `ApiResponse`：**
```python
class ApiResponse(BaseModel):
    success: bool
    message: str = ""
    data: dict | None = None  # 可选附加数据
```

---

## 目录

- [健康检查与系统](#健康检查与系统)
- [配置管理](#配置管理)
- [配置方案](#配置方案)
- [监控控制](#监控控制)
- [手动操作](#手动操作)
- [网络接口](#网络接口)
- [浏览器管理](#浏览器管理)
- [纯净模式](#纯净模式)
- [任务管理](#任务管理)
- [脚本管理](#脚本管理)
- [定时任务](#定时任务)
- [日志](#日志)
- [登录历史](#登录历史)
- [自启动](#自启动)
- [OCR 文字识别](#ocr-文字识别)
- [卸载](#卸载)
- [调试](#调试)
- [仓库代理](#仓库代理)
- [工具与文档](#工具与文档)
- [背景图片](#背景图片)
- [图标](#图标)
- [WebSocket 协议](#websocket-协议)
- [静态资源](#静态资源)
- [附录：配置字段结构](#附录配置字段结构)

---

## 健康检查与系统

| 方法 | 路径 | 请求参数 | 响应模型 |
|------|------|----------|---------|
| GET | `/api/health` | — | `HealthResponse` |
| GET | `/api/check-update` | — | `UpdateCheckResponse` |
| GET | `/api/init-status` | — | `InitStatusResponse` |
| POST | `/api/agree` | — | `ApiResponse` |
| POST | `/api/shutdown` | — | `ApiResponse` |

### GET /api/health

健康检查。返回服务状态、版本、Python 版本、内存和进程信息。

**响应 `HealthResponse`：**
```json
{
  "status": "ok",
  "version": "4.2.1",
  "python_version": "3.12.9",
  "memory": { "rss_mb": 85.2, "vms_mb": 320.1 },
  "process": { "threads": 12, "open_files": [...], "pid": 12345 }
}
```

### GET /api/check-update

检查 GitHub 上是否有新版本发布。内部使用 12 小时缓存以避免 GitHub API 速率限制。

**响应 `UpdateCheckResponse`：**
```json
{
  "current": "4.1.0",
  "latest": "4.2.0",
  "has_update": true,
  "url": "https://github.com/Misyra/Campus-Auth/releases/latest",
  "body": "发布说明...",
  "published_at": "2026-07-01T00:00:00Z",
  "cached": false,
  "error": null
}
```

### GET /api/init-status

获取初始化状态，用于前端判断是否需要引导配置。

**响应 `InitStatusResponse`：**
```json
{
  "initialized": false,
  "agreed": false,
  "password_decryption_failed": false
}
```

- `initialized` — 用户名和密码是否已配置
- `agreed` — 用户是否已同意使用协议
- `password_decryption_failed` — 上次密码解密是否失败

### POST /api/agree

同意使用协议。在 `config/.agree` 生成标记文件。

### POST /api/shutdown

关闭服务。停止监控、清理 PID 文件、触发 FastAPI lifespan 关闭事件。

---

## 配置管理

| 方法 | 路径 | 请求体 | 响应模型 |
|------|------|--------|---------|
| GET | `/api/config` | — | `ConfigResponse` |
| PUT | `/api/config` | `ConfigSaveRequest` | `ApiResponse` |
| PATCH | `/api/config` | `ConfigPatchRequest` | `ApiResponse` |
| GET | `/api/config/log-levels` | — | `LogLevelResponse` |
| PUT | `/api/config/log-level` | `LogLevelRequest` | `ApiResponse` |
| GET | `/api/config/default-stealth-script` | — | `StealthScriptResponse` |
| GET | `/api/config/defaults` | — | `dict` |

### GET /api/config

获取完整配置（含凭据脱敏）。

**响应 `ConfigResponse`：** 包含 `browser`、`monitor`、`retry`、`pause`、`logging`、`app_settings` 六个子对象（`dict` 格式），以及 `username`、`password`（始终为空串）、`has_password`（布尔值）、`auth_url`、`isp`、`carrier_custom`、`active_task`。

### PUT /api/config

全量保存配置。

**请求体 `ConfigSaveRequest`：**
```json
{
  "browser": { "headless": true, "timeout": 8, ... },
  "monitor": { "check_interval_seconds": 300, ... },
  "retry": { "max_retries": 3, "retry_interval": 5 },
  "pause": { "enabled": true, "start_hour": 0, "start_minute": 0, "end_hour": 6, "end_minute": 0 },
  "logging": { "level": "INFO", "log_retention_days": 7, "access_log": false },
  "app_settings": { "block_proxy": true, "startup_action": "none", ... },
  "username": "user",
  "password": "pass",
  "auth_url": "http://10.0.0.1",
  "isp": "中国移动",
  "carrier_custom": "",
  "active_task": ""
}
```

**字段说明：**
- `password` 为 `None` 表示不修改，`""` 表示清空密码
- `browser`、`monitor` 等嵌套对象必须完整提供（PATCH 方式使用下方增量接口）

### PATCH /api/config

增量更新配置。所有字段均为 `Optional`，仅修改 `payload` 中非 `None` 的字段。嵌套对象（`browser`、`monitor` 等）采用浅合并。

**请求体 `ConfigPatchRequest`：** 所有字段可选，结构与 `ConfigSaveRequest` 一致。

### GET /api/config/log-levels

获取当前日志级别配置。

**响应 `LogLevelResponse`：**
```json
{ "level": "INFO" }
```

### PUT /api/config/log-level

设置日志级别。同步更新 `LogConfigCenter`、持久化配置和引擎运行时配置。

**请求体 `LogLevelRequest`：**
```json
{ "level": "DEBUG" }
```

支持级别：`DEBUG`、`INFO`、`WARNING`、`ERROR`。无效级别返回 400。

### GET /api/config/default-stealth-script

获取默认反检测脚本（`navigator.webdriver` 隐藏等）。

### GET /api/config/defaults

获取所有配置子模型的默认值。

```json
{
  "browser": { "headless": true, "timeout": 8, ... },
  "monitor": { "check_interval_seconds": 300, ... },
  "retry": { "max_retries": 3, "retry_interval": 5 },
  "pause": { "enabled": true, "start_hour": 0, "start_minute": 0, ... },
  "logging": { "level": "INFO", "log_retention_days": 7, "access_log": false },
  "app_settings": { "block_proxy": true, "startup_action": "none", ... }
}
```

---

## 配置方案

> 方案（Profile）是包含完整认证凭据和匹配规则的配置单元。每个方案有独立的 `username`、`password`、`auth_url`、运营商信息和关联任务。

| 方法 | 路径 | 请求体 | 响应模型 |
|------|------|--------|---------|
| GET | `/api/profiles` | — | `ProfileListResponse` |
| GET | `/api/profiles/{profile_id}` | — | `ProfileDetailResponse` |
| PUT | `/api/profiles/{profile_id}` | `Profile` | `ApiResponse` |
| DELETE | `/api/profiles/{profile_id}` | — | `ApiResponse` |
| POST | `/api/profiles/active/{profile_id}` | — | `ApiResponse` |
| POST | `/api/profiles/detect` | — | `NetworkDetectResponse` |
| POST | `/api/profiles/auto-switch` | `AutoSwitchRequest` | `ApiResponse` |

### GET /api/profiles

列出所有方案。

**响应 `ProfileListResponse`：**
```json
{
  "profiles": {
    "default": {
      "name": "默认方案",
      "match_gateway_ip": "",
      "match_ssid": "",
      "carrier": "无",
      "carrier_custom": "",
      "auth_url": "http://10.0.0.1",
      "active_task": ""
    },
    "dormitory": { ... }
  },
  "active_profile": "default",
  "auto_switch": false
}
```

### GET /api/profiles/{profile_id}

获取指定方案详情。密码始终返回空串（前端显示掩码）。

**响应 `ProfileDetailResponse`：**
```json
{
  "profile_id": "default",
  "settings": {
    "name": "默认方案",
    "match_gateway_ip": "",
    "match_ssid": "",
    "username": "user",
    "password": "",
    "auth_url": "http://10.0.0.1",
    "carrier": "无",
    "carrier_custom": "",
    "active_task": ""
  }
}
```

### PUT /api/profiles/{profile_id}

创建或更新方案。如果是活动方案，保存后自动应用（热重载）。

**请求体 `Profile`（Pydantic `frozen=True`）：**
```json
{
  "name": "宿舍网络",
  "match_gateway_ip": "10.0.0.1",
  "match_ssid": "Campus-WiFi",
  "username": "2024001",
  "password": "mypassword",
  "auth_url": "http://10.0.0.1",
  "carrier": "中国移动",
  "carrier_custom": "",
  "active_task": ""
}
```

- `password` 为 `None` 表示不修改，`""` 表示清空，`"ENC:..."` 表示已加密
- `default` 方案不可删除（DELETE 返回业务失败）

### DELETE /api/profiles/{profile_id}

删除方案。删除后自动通知引擎重载配置。`default` 方案不可删除。

### POST /api/profiles/active/{profile_id}

设置活动方案。引擎立即应用该方案的配置和凭据。

### POST /api/profiles/detect

检测当前网络环境（网关 IP、WiFi SSID），并返回匹配的方案。

**响应 `NetworkDetectResponse`：**
```json
{
  "gateway_ip": "10.0.0.1",
  "ssid": "Campus-WiFi",
  "matched_profile_id": "dormitory",
  "matched_profile_name": "宿舍网络"
}
```

### POST /api/profiles/auto-switch

切换自动方案切换开关。

**请求体 `AutoSwitchRequest`：**
```json
{ "enabled": true }
```

- 启用时，立即执行一次网络检测，如匹配非活动方案则自动切换
- 禁用时，停止自动方案切换行为

---

## 监控控制

| 方法 | 路径 | 响应模型 |
|------|------|---------|
| GET | `/api/status` | `MonitorStatusResponse` |
| POST | `/api/monitor/start` | `ApiResponse` |
| POST | `/api/monitor/stop` | `ApiResponse` |

### GET /api/status

获取监控状态。

**响应 `MonitorStatusResponse`：**
```json
{
  "monitoring": true,
  "network_check_count": 42,
  "login_attempt_count": 3,
  "last_check_time": "2026-07-06 14:30:00",
  "runtime_seconds": 3600,
  "network_connected": true,
  "status_detail": "正常",
  "network_state": "connected"
}
```

- `network_state` 取值：`"connected"`、`"disconnected"`、`"unknown"`、`"paused"`

### POST /api/monitor/start

启动监控（Actor 模型命令派发）。

### POST /api/monitor/stop

停止监控。

---

## 手动操作

| 方法 | 路径 | 响应模型 |
|------|------|---------|
| POST | `/api/actions/login` | `ApiResponse` |
| POST | `/api/actions/cancel-login` | `ApiResponse` |
| POST | `/api/actions/test-network` | `ApiResponse` |

### POST /api/actions/login

手动触发登录。异步执行（通过 `asyncio.to_thread`），不会长时间阻塞 HTTP 连接。

### POST /api/actions/cancel-login

取消当前正在执行的登录操作。

### POST /api/actions/test-network

测试网络连通性。返回结果在 `message` 中描述。

---

## 网络接口

| 方法 | 路径 | 响应模型 |
|------|------|---------|
| GET | `/api/network/interfaces` | `list[dict]` |

### GET /api/network/interfaces

枚举可用物理网卡（用于网卡绑定配置）。

**响应：**
```json
[
  {
    "id": "以太网",
    "name": "以太网",
    "ip": "10.0.0.5",
    "gateway": "10.0.0.1",
    "is_up": true
  }
]
```

---

## 浏览器管理

| 方法 | 路径 | 响应模型 |
|------|------|---------|
| GET | `/api/browsers` | `BrowserListResponse` |
| POST | `/api/browsers/install-playwright` | `ApiResponse` |

### GET /api/browsers

获取系统已安装浏览器列表和当前配置的浏览器通道。

**响应 `BrowserListResponse`：**
```json
{
  "browsers": [
    { "channel": "playwright", "name": "Playwright Chromium", "icon": "", "installed": true, "needs_download": false, "description": "" },
    { "channel": "msedge", "name": "Microsoft Edge", "icon": "edge.svg", "installed": true, "needs_download": false, "description": "" }
  ],
  "current": "msedge"
}
```

### POST /api/browsers/install-playwright

安装 Playwright Chromium 浏览器。异步执行（通过 `asyncio.create_subprocess_exec` 调用 `playwright install chromium`），带有 5 分钟空闲超时保护。安装进行中时重复请求会被拒绝。

---

## 纯净模式

| 方法 | 路径 | 响应模型 |
|------|------|---------|
| GET | `/api/pure-mode` | `PureModeResponse` |
| POST | `/api/pure-mode` | `ApiResponse` |

### GET /api/pure-mode

获取纯净模式状态。

**响应 `PureModeResponse`：**
```json
{ "enabled": true }
```

### POST /api/pure-mode

切换纯净模式开关。成功返回 `data.enabled` 显示新状态。

---

## 任务管理

> 任务（Task）是浏览器自动化或脚本的执行单元。浏览器任务包含一系列步骤（Step），脚本任务关联外部可执行文件。

| 方法 | 路径 | 请求体 | 响应模型 |
|------|------|--------|---------|
| GET | `/api/tasks` | — | `list[TaskSummary]` |
| GET | `/api/tasks/active` | — | `dict` |
| GET | `/api/tasks/{task_id}` | — | `dict` |
| PUT | `/api/tasks/{task_id}` | `dict` | `ApiResponse` |
| DELETE | `/api/tasks/{task_id}` | — | `ApiResponse` |
| POST | `/api/tasks/active/{task_id}` | — | `ApiResponse` |
| POST | `/api/tasks/order` | `TaskOrderRequest` | `ApiResponse` |

**路由注册顺序注意：** `GET /api/tasks/active` 必须在 `GET /api/tasks/{task_id}` 之前定义，否则 `active` 会被匹配为 `task_id`。当前定义顺序正确。

### GET /api/tasks

列出所有任务。

**响应 `list[TaskSummary]`：**
```json
[
  { "id": "login", "name": "校园网登录", "description": "校园网认证登录", "type": "browser", "binary_path": "" }
]
```

### GET /api/tasks/active

获取当前活动任务 ID。

**响应：** `{ "task_id": "login" }`

### GET /api/tasks/{task_id}

获取任务详情（含完整步骤配置）。

### PUT /api/tasks/{task_id}

创建或更新任务。请求体为完整的任务配置 JSON（含 `steps` 数组）。

### DELETE /api/tasks/{task_id}

删除任务。`default` 任务不可删除。

### POST /api/tasks/active/{task_id}

设置活动任务。

### POST /api/tasks/order

保存任务排序。**请求体 `TaskOrderRequest`：** `{ "order": ["login", "health_check", ...] }`

---

## 脚本管理

| 方法 | 路径 | 请求体 | 响应模型 |
|------|------|--------|---------|
| GET | `/api/scripts` | — | `list[TaskSummary]` |
| GET | `/api/scripts/binaries` | — | `list[BinaryInfo]` |
| GET | `/api/scripts/{task_id}` | — | `dict` |
| PUT | `/api/scripts/{task_id}` | `dict` | `ApiResponse` |
| DELETE | `/api/scripts/{task_id}` | — | `ApiResponse` |
| POST | `/api/scripts/{task_id}/run` | — | `ApiResponse` |

### GET /api/scripts/binaries

获取系统可用的脚本解释器列表。

**响应 `list[BinaryInfo]`：**
```json
[
  { "path": "C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe", "name": "PowerShell" }
]
```

### POST /api/scripts/{task_id}/run

手动执行脚本任务（测试用）。使用独立的 `ThreadPoolExecutor(max_workers=2)` 执行，从配置读取 `script_timeout` 作为超时。

---

## 定时任务

> 定时任务支持三种类型：`script`（脚本任务）、`browser`（浏览器任务）、`shell`（Shell 命令）。执行历史存储在 `tasks/scheduled/history/` 目录。

| 方法 | 路径 | 请求体 | 响应模型 |
|------|------|--------|---------|
| GET | `/api/scheduled-tasks` | — | `list[dict]` |
| POST | `/api/scheduled-tasks` | `ScheduledTaskConfig` | `ApiResponse` |
| PUT | `/api/scheduled-tasks/{task_id}` | `dict` | `ApiResponse` |
| DELETE | `/api/scheduled-tasks/{task_id}` | — | `ApiResponse` |
| POST | `/api/scheduled-tasks/{task_id}/run` | — | `ApiResponse` |
| POST | `/api/scheduled-tasks/{task_id}/toggle` | — | `ApiResponse` |
| GET | `/api/scheduled-tasks/{task_id}/history` | — | `list[dict]` |

### POST /api/scheduled-tasks

创建定时任务。自动生成 `task_{uuid_hex[:12]}` 格式的 ID。

**请求体 `ScheduledTaskConfig`：**
```json
{
  "name": "每日登录",
  "description": "每天早上 8 点执行登录",
  "type": "browser",
  "target_id": "login",
  "command": "",
  "shell_path": "",
  "enabled": true,
  "schedule": { "hour": 8, "minute": 0 },
  "timeout": 60
}
```

- `type` 取值：`"script"`、`"browser"`、`"shell"`
- `type == "shell"` 时必需 `command`
- `type == "script"` 或 `"browser"` 时必需 `target_id`
- `timeout` 范围：5~3600 秒

### PUT /api/scheduled-tasks/{task_id}

更新定时任务。`schedule` 子对象采用浅合并。保留 `last_run` 和 `last_status`。

### POST /api/scheduled-tasks/{task_id}/run

手动执行定时任务（后台异步执行，不阻塞 HTTP 响应）。使用 `BackgroundTasks`。

### POST /api/scheduled-tasks/{task_id}/toggle

启用/禁用定时任务。自动同步调度器状态。

### GET /api/scheduled-tasks/{task_id}/history

获取定时任务执行历史。

---

## 日志

| 方法 | 路径 | 查询参数 | 响应模型 |
|------|------|----------|---------|
| GET | `/api/logs` | `limit` (默认 200, 最大 1000) | `list[LogEntry]` |
| WS | `/ws/logs` | — | WebSocket |

### GET /api/logs

获取后端日志缓冲区中的历史日志条目。

**响应 `list[LogEntry]`：**
```json
[
  { "timestamp": "2026-07-06 14:30:00", "level": "INFO", "source": "backend", "name": "engine", "message": "监控启动成功" }
]
```

- `level` 验证：仅 `DEBUG`、`INFO`、`WARNING`、`ERROR` 有效
- 日志来源：`backend`（后端日志）、`frontend`（前端日志，通过 WebSocket 上报）

---

## 登录历史

| 方法 | 路径 | 查询参数 | 响应模型 |
|------|------|----------|---------|
| GET | `/api/login-history` | `limit` (默认 30, 范围 1~500) | `list[LoginHistoryEntry]` |
| DELETE | `/api/login-history` | — | `ApiResponse` |

### GET /api/login-history

**响应 `list[LoginHistoryEntry]`：**
```json
[
  {
    "id": "a1b2c3d4",
    "timestamp": "2026-07-06T14:30:00",
    "success": true,
    "duration_ms": 3200,
    "profile_name": "默认方案",
    "task_name": "校园网登录",
    "error": ""
  }
]
```

登录历史存储在 `~/.campus_network_auth/login_history.jsonl`，最多 200 条记录。

---

## 自启动

| 方法 | 路径 | 请求体 | 响应模型 |
|------|------|--------|---------|
| GET | `/api/shells` | — | `ShellListResponse` |
| GET | `/api/autostart/status` | — | `AutoStartStatusResponse` |
| POST | `/api/autostart/enable` | — | `ApiResponse` |
| POST | `/api/autostart/disable` | — | `ApiResponse` |
| POST | `/api/autostart/mode` | `AutostartModeRequest` | `ApiResponse` |

### GET /api/shells

获取系统可用 Shell 列表。

**响应 `ShellListResponse`：**
```json
{
  "shells": [
    { "name": "PowerShell 7", "path": "C:\\Program Files\\PowerShell\\7\\pwsh.exe", "description": "PowerShell 7" }
  ],
  "default": "pwsh"
}
```

### GET /api/autostart/status

**响应 `AutoStartStatusResponse`：**
```json
{
  "platform": "win32",
  "enabled": true,
  "method": "startup_folder",
  "location": "C:\\Users\\...\\Startup\\campus-auth.bat",
  "runtime_mode": "lightweight"
}
```

- `runtime_mode` 从配置中读取，默认 `lightweight`

### POST /api/autostart/mode

切换自启动运行模式（仅保存配置，不重新生成启动脚本）。

**请求体 `AutostartModeRequest`：**
```json
{ "runtime_mode": "lightweight" }
```

模式：`"full"`（完整模式）或 `"lightweight"`（轻量模式）。

---

## OCR 文字识别

| 方法 | 路径 | 响应模型 |
|------|------|---------|
| GET | `/api/ocr/status` | `OcrStatusResponse` |
| POST | `/api/ocr/install` | `ApiResponse` |
| POST | `/api/ocr/uninstall` | `ApiResponse` |

### GET /api/ocr/status

**响应 `OcrStatusResponse`：**
```json
{
  "installed": true,
  "size_mb": 85.5
}
```

检测依据：`pyproject.toml` 的 `dependencies` 中是否包含 `ddddocr`。

### POST /api/ocr/install

通过 `uv add ddddocr onnxruntime` 安装 OCR 依赖（超时 5 分钟）。

### POST /api/ocr/uninstall

通过 `uv remove ddddocr onnxruntime` 卸载 OCR 依赖。

---

## 卸载

| 方法 | 路径 | 请求体 | 响应模型 |
|------|------|--------|---------|
| GET | `/api/uninstall/detect` | — | `list[UninstallItem]` |
| POST | `/api/uninstall` | `UninstallRequest` | `ApiResponse` |

### GET /api/uninstall/detect

检测可清理的外部残留项目（旧版本遗留文件、配置文件等）。

**响应 `list[UninstallItem]`：**
```json
[
  { "key": "old_config", "label": "旧版配置文件", "exists": true, "path": "C:\\...", "size_mb": 0.5 }
]
```

### POST /api/uninstall

执行卸载清理。

**请求体 `UninstallRequest`：** `{ "keys": ["old_config", "temp_files"] }`

**响应 `ApiResponse` 的 `data` 字段：**
```json
{
  "results": [
    { "key": "old_config", "label": "旧版配置文件", "success": true, "message": "已删除" }
  ]
}
```

---

## 调试

> 调试会话（Debug Session）用于测试浏览器任务。启动后打开浏览器并逐步骤执行，支持截图回传。

| 方法 | 路径 | 响应模型 |
|------|------|---------|
| POST | `/api/debug/start` | `DebugSessionResponse` |
| POST | `/api/debug/next` | `DebugSessionResponse` |
| POST | `/api/debug/run-all` | `DebugSessionResponse` |
| POST | `/api/debug/stop` | `DebugSessionResponse` |

所有调试端点共享统一的响应模型 `DebugSessionResponse`：

```json
{
  "running": true,
  "task_id": "login",
  "current_step": 2,
  "total_steps": 10,
  "steps": [...],
  "results": [...],
  "screenshot_url": "/temp/screenshot_abc123.png",
  "message": "步骤 2/10 执行成功"
}
```

---

## 仓库代理

> 用于前端从远程任务仓库获取任务索引和配置，避免跨域问题。

| 方法 | 路径 | 查询参数 | 响应模型 |
|------|------|----------|---------|
| GET | `/api/repo/fetch` | `url` (必需) | `list` |
| GET | `/api/repo/task` | `url` (必需) | `dict` |

内部通过 `httpx.AsyncClient` 发起 HTTP GET 请求，使用 `validate_url` 做安全校验。

---

## 工具与文档

| 方法 | 路径 | 响应 |
|------|------|------|
| GET | `/api/tools/task-recorder.user.js` | `FileResponse` (text/javascript) |
| GET | `/api/docs/task-writing-guide` | `FileResponse` (text/markdown) |
| GET | `/api/docs/task-manual` | `FileResponse` (text/markdown) |

- 任务录制器脚本：`resources/tools/task-recorder.user.js`
- 任务编写指南：`docs/guides/task-writing-guide.md`
- 任务操作手册：`docs/dev/architecture.md`

---

## 背景图片

> 背景图片存储在 `resources/background/` 目录，最多保留一张（上传新图片时自动清理旧文件）。

| 方法 | 路径 | 请求体 | 响应模型 |
|------|------|--------|---------|
| POST | `/api/background/upload` | `file` (multipart) | `ApiResponse` |
| POST | `/api/background/fetch-url` | `FetchUrlRequest` | `ApiResponse` |
| GET | `/api/background/{filename}` | — | `FileResponse` |
| DELETE | `/api/background/{filename}` | — | `ApiResponse` |

**支持格式：** JPG、PNG、GIF、WebP、SVG  
**文件大小限制：** 5MB  
**文件名安全检查：** 防止路径遍历攻击

### POST /api/background/upload

上传背景图片。自动清理旧文件（同一时间只保留一张背景图）。

### POST /api/background/fetch-url

从远程 URL 下载背景图片。流式读取，超限立即中断。

**请求体 `FetchUrlRequest`：** `{ "url": "https://example.com/bg.jpg" }`

---

## 图标

| 方法 | 路径 | 响应 |
|------|------|------|
| GET | `/api/icons/{filename}` | `Response` (image/svg+xml) |

- 图标文件存储在 `resources/icons/`
- 仅支持 `.svg` 文件
- 路径遍历安全检查
- 缓存头部：`Cache-Control: public, max-age=86400`

---

## WebSocket 协议

### 端点

```
WS /ws/logs
```

### 连接生命周期

1. 客户端发起 WebSocket 连接
2. 服务端通过 `WebSocketManager` 注册连接
3. 双向通信直到断开

### 消息格式

#### 客户端 → 服务端

| type | data | 说明 |
|------|------|------|
| `ping` | — | 应用层心跳，服务端回复 `pong` |
| `frontend_log` | `{ level, scope, message }` | 上报前端日志到后端 |

**心跳示例：**
```json
// 客户端发送
{ "type": "ping" }
// 服务端回复
{ "type": "pong" }
```

**前端日志上报示例：**
```json
{
  "type": "frontend_log",
  "data": {
    "level": "INFO",
    "scope": "App.vue",
    "message": "用户点击了登录按钮"
  }
}
```

#### 服务端 → 客户端

服务端通过 `WebSocketManager` 广播日志条目，格式与 HTTP 日志接口一致：

```json
{
  "timestamp": "2026-07-06 14:30:00",
  "level": "INFO",
  "source": "backend",
  "name": "engine",
  "message": "网络状态: connected"
}
```

### 安全限制

- 消息大小限制：65536 字节（UTF-8 字节长度）
- `message` 截断：10000 字符
- `scope` 截断：200 字符
- 超限消息会导致连接断开

---

## 静态资源

| 路径 | 类型 | 目录 |
|------|------|------|
| `/` | 首页（Vue 3 SPA 入口） | `frontend/index.html` |
| `/static` | 静态文件（Vue 3 前端资源） | `frontend/` |
| `/debug/` | 调试截图日目录 | `debug/` |
| `/temp/` | 调试截图临时目录 | `temp/` |

- 首页 `/` 不在 OpenAPI schema 中暴露（`include_in_schema=False`）
- VUE 3 SPA 为无构建步骤模式，通过 FastAPI 静态文件服务托管

---

## 附录：配置字段结构

### MonitorSettings

```python
class MonitorSettings(BaseModel, frozen=True):
    check_interval_seconds: int = Field(default=300, ge=10, le=86400)  # 检测间隔（秒）
    network_check_timeout: int = Field(default=2, ge=1, le=30)         # 检测超时（秒）
    ping_targets: list[str] = Field(default_factory=lambda: _parse_targets(DEFAULT_NETWORK_TARGETS))  # TCP 检测目标
    enable_tcp_check: bool = False          # 启用 TCP 检测
    enable_http_check: bool = False         # 启用 HTTP 检测
    enable_local_check: bool = True         # 启用本地网络检测
    test_urls: list[str]                    # HTTP 检测 URL
    check_auth_url: bool = False            # 启用认证地址检测
    auth_url_targets: list[str]             # 认证地址检测目标
    url_check_urls: list[str]               # URL 检测目标
    script_timeout: int = Field(default=60, ge=5, le=600)  # 脚本超时（秒）
    bind_interface_name: str = ""           # 绑定网卡名称
```

### BrowserSettings

```python
class BrowserSettings(BaseModel, frozen=True):
    headless: bool = True                           # 无头模式
    timeout: int = Field(default=8, ge=1, le=60)    # 浏览器操作超时（秒）
    navigation_timeout: int = Field(default=8, ge=3, le=60)   # 页面加载超时（秒）
    login_timeout: int = Field(default=90, ge=10, le=600)     # 登录总超时（秒）
    user_agent: str = "Mozilla/5.0 ..."             # 用户代理
    low_resource_mode: bool = False                 # 低资源模式
    disable_web_security: bool = False              # 禁用同源策略
    extra_headers_json: str = ""                    # 附加请求头（JSON）
    browser_args: str = "--disable-blink-features=..."  # 浏览器启动参数
    stealth_mode: bool = False                      # 反检测模式
    stealth_custom_script: str = ""                 # 自定义反检测脚本
    locale: str = "zh-CN"                           # 浏览器语言
    timezone_id: str = "Asia/Shanghai"              # 时区
    viewport_width: int = Field(default=1280, ge=320, le=3840)
    viewport_height: int = Field(default=720, ge=240, le=2160)
    pure_mode: bool = True                          # 纯净模式
    browser_channel: BrowserChannel = BrowserChannel.MSEdge  # 浏览器通道
    browser_custom_path: str = ""                   # 自定义浏览器路径
    custom_browser_engine: str = "auto"             # 自定义浏览器引擎
    persistent_context: bool = False                # 持久化上下文
```

### PauseSettings

```python
class PauseSettings(BaseModel, frozen=True):
    enabled: bool = True
    start_hour: int = Field(default=0, ge=0, le=23)
    start_minute: int = Field(default=0, ge=0, le=59)
    end_hour: int = Field(default=6, ge=0, le=23)
    end_minute: int = Field(default=0, ge=0, le=59)
```

**暂停时段语义：** `start_hour == end_hour` 且 `start_minute == end_minute` 时为全天暂停。`start_hour > end_hour` 时为跨天暂停（如 23:00~06:00）。

### LoggingSettings

```python
class LoggingSettings(BaseModel, frozen=True):
    level: str = Field(default="INFO", pattern=r"^(DEBUG|INFO|WARNING|ERROR)$")
    log_retention_days: int = Field(default=7, ge=1, le=365)
    access_log: bool = False  # 是否记录 HTTP 访问日志
```

### RetrySettings

```python
class RetrySettings(BaseModel, frozen=True):
    max_retries: int = Field(default=3, ge=0, le=10)       # 最大重试次数
    retry_interval: int = Field(default=5, ge=1, le=300)    # 重试间隔（秒）
```

### AppSettings

```python
class AppSettings(BaseModel, frozen=True):
    block_proxy: bool = True            # 屏蔽系统代理
    shell_path: str = ""                # Shell 路径
    startup_action: StartupAction = StartupAction.NONE       # 启动后动作
    runtime_mode: RuntimeMode = RuntimeMode.FULL             # 运行模式
    lightweight_tray: bool = True       # 轻量模式系统托盘
    minimize_to_tray: bool = True       # 最小化到托盘
    auto_open_browser: bool = False     # 自动打开浏览器
    proxy: str = ""                     # 代理设置
    app_port: int = Field(default=50721, ge=1, le=65535)    # Web 端口
```

---

## 附录：API 统计

| 类别 | 数量 |
|------|:----:|
| HTTP 路由总数 | 67 |
| WebSocket 路由 | 1 |
| 静态挂载 | 3 |
| GET 路由 | 24 |
| POST 路由 | 28 |
| PUT 路由 | 6 |
| PATCH 路由 | 1 |
| DELETE 路由 | 6 |
| 请求模型 | 9 |
| 响应模型 | 25 |
| 路由文件数 | 16 |
