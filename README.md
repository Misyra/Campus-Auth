# Campus-Auth 校园网自动认证

Campus-Auth 是一个基于 Playwright、FastAPI 和 Vue 3 的校园网自动认证工具。它既可以作为终端用户直接运行的本地服务，也适合作为开发调试项目使用。项目提供 Web 控制台、自动监控、任务模板、多网络配置方案、系统托盘、自启动与日志可视化，目标是让校园网认证尽量做到"装好即用、断网即连、问题可查"。

## 项目能做什么

Campus-Auth 主要解决三个场景：

1. 开机后自动保持网络在线，避免手动重复登录。
2. 在网络掉线、会话失效或页面失效时，自动回到认证流程并重试。
3. 通过 Web 控制台统一管理配置、任务、日志和运行状态。

### 主要特性

- Web 控制台：初始化向导、仪表盘、设置页、任务页、配置方案页、关于页。
- 多网络配置方案：为不同网络环境创建独立配置，支持按网关 IP 或 WiFi SSID 自动切换。
- 自动监控：定时探测网络可用性，异常时自动触发认证。
- 自动登录：基于 Playwright 的浏览器自动化，按任务定义执行登录流程。
- 任务系统：使用 JSON 描述认证步骤，支持导入导出、复制、安全检测。
- 实时日志：通过 WebSocket 推送运行日志，支持按级别筛选和文本搜索。
- 开机自启动：支持在 Windows、macOS 和 Linux 上配置自启动。
- 系统托盘：可在后台最小化到托盘运行。
- 防重复启动：同时检测 PID 文件和本地端口，避免重复拉起同一实例。
- 智能状态判断：识别已登录状态，减少重复提交和无效请求。
- 暂停时段：支持在夜间或指定时间段暂停自动登录。
- 失败重试：使用退避策略降低短时间内的重复冲击。
- API 鉴权：支持通过 Token 保护写操作接口。

## 运行前准备

### 推荐环境

- Python 3.10 或更高版本。
- Windows 用户建议优先使用仓库自带的启动器或发布包。
- 如果是源码运行，推荐使用 uv 管理依赖。

### 端口与访问地址

默认 Web 控制台端口为 50721，启动后可在浏览器访问：

http://127.0.0.1:50721

如果你修改了 `APP_PORT`，则以实际端口为准。

## 快速开始

### 方式一：直接使用 Windows 发布包

适合不想自己配置 Python 环境的用户。

1. 下载并解压发布包。
2. 直接运行生成的可执行文件，或使用目录内的启动脚本。
3. 首次启动后打开浏览器访问控制台地址。
4. 按初始化向导填写账号、密码、认证地址等信息。

### 方式二：源码运行

适合开发、调试和二次定制。

安装依赖：

```bash
uv sync
```

启动服务：

```bash
uv run app.py
```

如果你希望直接使用仓库自带环境，也可以运行：

```powershell
.\environment\python\python.exe app.py
```

### 方式三：使用 Windows 启动器自动准备环境

如果本机环境不完整，`launcher.py` 会尝试检查并准备 Python、依赖和 Playwright 相关运行条件。

```powershell
python launcher.py
```

常用参数：

```powershell
python launcher.py --python-version 3.10 --pip-mirror https://mirrors.tuna.tsinghua.edu.cn/simple
python launcher.py --force-reinstall --verbose
```

## 首次使用流程

建议第一次使用按下面顺序完成：

1. 启动服务并打开 Web 控制台。
2. 进入初始化向导，填写校园网账号、密码和认证页面地址。
3. 确认运营商字段、监控开关和浏览器模式。
4. 保存配置后执行一次手动登录，确认流程正常。
5. 再开启自动监控，让系统在断网时自动重连。

如果校园网页面结构比较特殊，建议先用非无头模式排查，再切换回无头运行。

如果你有多个网络环境（如宿舍 WiFi 和教学楼 WiFi），可以在"配置方案"页面为每个网络创建独立配置，系统会根据当前网络自动切换。

## 启动参数

`app.py` 支持若干命令行参数，用于控制服务启动、状态查询和自启动管理。

```bash
# 基础启动
python app.py

# 启动但不自动打开浏览器
python app.py --no-browser

# 启动到系统托盘
python app.py --tray

# 查看服务状态
python app.py --status

# 停止服务
python app.py --stop

# 自启动管理
python app.py --autostart
python app.py --autostart enable
python app.py --autostart disable
```

## 配置说明

### 配置来源

项目支持两种配置存储：

- `.env` 文件：环境变量形式，存储全局凭证和基础配置。
- `settings.json` 文件：存储多网络配置方案（Profiles），由 Web 控制台管理。

首次使用时系统会自动将 `.env` 中的配置迁移为默认方案。通过 Web 控制台保存配置时，会根据方案设置决定写入 `.env` 还是 `settings.json`。

如果你是首次部署，可以先复制 `.env.example` 为 `.env` 再修改：

```bash
cp .env.example .env
```

### 核心配置项

#### 认证配置

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `USERNAME` | - | 校园网用户名，必填。 |
| `PASSWORD` | - | 校园网密码，必填，支持加密存储。 |
| `LOGIN_URL` | `http://172.29.0.2` | 认证页面地址。 |
| `ISP` | 空 | 运营商关键字，可填移动、联通、电信或自定义关键字。 |

#### 服务配置

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `APP_PORT` | `50721` | Web 控制台端口。 |
| `UVICORN_ACCESS_LOG` | `false` | 是否输出 HTTP 访问日志。 |
| `API_TOKEN` | 空 | API 写操作鉴权令牌，可选。 |

#### 监控配置

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `AUTO_START_MONITORING` | `false` | 启动后是否自动开始网络监控。 |
| `MONITOR_INTERVAL` | `300` | 网络检测间隔，单位秒。 |
| `PING_TARGETS` | `8.8.8.8:53,114.114.114.114:53,www.baidu.com:443` | 探测目标列表。 |
| `MAX_CONSECUTIVE_FAILURES` | `3` | 连续登录失败次数上限。 |

#### 暂停时段

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `PAUSE_LOGIN_ENABLED` | `true` | 是否启用暂停登录时段。 |
| `PAUSE_LOGIN_START_HOUR` | `0` | 暂停开始小时，0 到 23。 |
| `PAUSE_LOGIN_END_HOUR` | `6` | 暂停结束小时，0 到 23。 |

#### 浏览器配置

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `BROWSER_HEADLESS` | `true` | 是否使用无头模式。 |
| `BROWSER_TIMEOUT` | `8000` | 浏览器操作超时时间，单位毫秒。 |
| `BROWSER_LOW_RESOURCE_MODE` | `true` | 是否启用低资源模式。 |
| `BROWSER_USER_AGENT` | 内置默认值 | 自定义 User-Agent。 |
| `BROWSER_EXTRA_HEADERS_JSON` | 空 | 额外请求头，JSON 格式。 |
| `BROWSER_DISABLE_WEB_SECURITY` | `false` | 禁用浏览器同源策略。 |

#### 系统配置

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `MINIMIZE_TO_TRAY` | `true` | 是否最小化到系统托盘。 |
| `CUSTOM_VARIABLES` | `{}` | 自定义变量，JSON 格式，可在任务模板中引用。 |

#### Playwright 配置

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `AUTO_INSTALL_PLAYWRIGHT` | `true` | 是否自动安装 Chromium。 |
| `PLAYWRIGHT_DOWNLOAD_HOST` | `https://npmmirror.com/mirrors/playwright` | Playwright 下载镜像源。 |

## 任务系统

任务系统采用 JSON 文件描述认证流程，适合不同校园网页面、不同按钮名称和不同跳转逻辑。你可以把它理解为一份"自动登录脚本配置"。

### 任务文件位置

项目默认把任务放在 `tasks/` 目录下，常见文件包括：

- `default.json`：默认认证任务（内置，不可删除）。
- `sample.json`：基础示例任务。
- `sample_2.json`：更复杂的示例任务。
- `active.txt`：当前活动任务标识。

### Web 控制台操作

在任务页面可以：

- 查看任务列表（内置任务显示"内置"标签）
- 新建、编辑、删除任务
- 导入/导出任务（JSON 文件）
- 复制任务（创建 `_copy` 后缀的副本）
- 设置活动任务
- 保存包含 `eval` / `custom_js` 步骤的任务时，会弹出安全确认对话框

### 任务结构示例

```json
{
  "name": "校园网认证",
  "description": "自动登录校园网",
  "version": "1.0",
  "url": "http://172.29.0.2",
  "timeout": 10000,
  "variables": {
    "username": "{{USERNAME}}",
    "password": "{{PASSWORD}}"
  },
  "steps": [
    {
      "type": "navigate",
      "url": "{{url}}",
      "description": "打开认证页面"
    },
    {
      "type": "input",
      "selector": "input[name='DDDDD']",
      "value": "{{username}}",
      "description": "填写用户名"
    },
    {
      "type": "input",
      "selector": "input[name='upass']",
      "value": "{{password}}",
      "description": "填写密码"
    },
    {
      "type": "click",
      "selector": "input[name='0MKKey']",
      "description": "点击登录"
    }
  ],
  "success_conditions": [
    {
      "type": "url_contains",
      "pattern": "success"
    }
  ],
  "on_success": {
    "message": "登录成功"
  },
  "on_failure": {
    "message": "登录失败",
    "screenshot": true
  }
}
```

### 支持的步骤类型

| 类型 | 说明 | 关键参数 |
|------|------|----------|
| `navigate` | 打开指定页面。 | `url`, `wait_until`, `timeout` |
| `input` | 在输入框中填写文本。 | `selector`, `value`, `clear`, `timeout` |
| `click` | 点击页面元素。 | `selector`, `timeout` |
| `select` | 选择下拉框选项。value 为空或元素不存在时自动跳过，支持按选项文本模糊匹配。 | `selector`, `value`, `timeout` |
| `wait` | 等待元素出现。 | `selector`, `timeout` |
| `wait_url` | 等待 URL 匹配指定模式。 | `pattern`, `timeout` |
| `eval` | 执行 JavaScript 并保存结果。`code` 为已废弃别名。 | `script`, `store_as` |
| `custom_js` | 执行自定义 JavaScript。`code` 为已废弃别名。 | `script` |
| `screenshot` | 截图保存。 | `path` |
| `sleep` | 等待指定时间。 | `duration` |

更完整的任务格式说明请参考 [doc/task-manual.md](doc/task-manual.md)。

### 编写建议

- 优先给每一步写清楚 `description`，方便日志回溯。
- 选择器尽量写得稳一点，避免只依赖单个脆弱的 CSS 片段。
- 如果页面会跳转，建议在登录后增加 URL 或结果页判断。
- 失败时建议开启截图，便于定位页面变化或表单异常。
- 如果第一个步骤不是 `navigate`，执行器会自动导航到任务的 `url` 字段，无需显式添加导航步骤。
- 简单任务可以留空 `success_conditions`，所有步骤完成即为成功。

## 多网络配置方案

配置方案（Profiles）系统允许你为不同的网络环境（如宿舍 WiFi、教学楼 WiFi、有线网络）配置不同的认证参数，系统可以根据当前网络自动切换。

### 工作原理

1. 每个方案可以设置匹配条件：网关 IP 或 WiFi SSID。
2. 系统检测当前网络的网关 IP 和 WiFi SSID（支持 Windows、macOS、Linux）。
3. 优先按网关 IP 匹配，其次按 SSID 匹配。
4. 匹配成功后自动切换到对应方案的配置。

### 独立设置

每个方案可以独立配置：

- 凭证（用户名/密码，加密存储）
- 认证地址、运营商
- 检测间隔、暂停时段
- 浏览器参数（无头模式、超时、User-Agent 等）
- 自定义变量

也可以选择使用全局凭证或全局高级设置。

### Web 控制台操作

在"配置方案"页面可以：

- 查看所有方案列表及当前活动方案
- 新建、编辑、删除方案（`default` 不可删除）
- 检测当前网络环境（网关 IP、WiFi SSID、匹配的方案）
- 开启/关闭自动切换

### 自动切换

开启自动切换后，监控核心每 60 秒检测一次网络环境变化。当检测到当前网络匹配到不同的方案时，会自动切换配置并重新加载监控。

## 项目结构

```text
Campus-Auth/
├── app.py                    # 统一启动入口
├── launcher.py               # Windows 启动器（自动准备环境）
├── pyproject.toml            # 项目元数据与依赖配置
├── requirements.txt          # 依赖列表（兼容 pip）
├── settings.json             # 多网络配置方案数据
├── .env.example              # 环境变量模板
├── backend/                  # 后端服务
│   ├── main.py               # FastAPI 主应用
│   ├── config_service.py     # 配置读写与初始化状态
│   ├── profile_service.py    # 多网络配置方案管理
│   ├── monitor_service.py    # 网络监控与认证触发
│   ├── task_service.py       # 任务读写与活动任务管理
│   ├── autostart_service.py  # 开机自启动管理
│   └── schemas.py            # Pydantic 数据模型
├── src/                      # 核心逻辑与工具模块
│   ├── task_executor.py      # 任务执行器（按 JSON 步骤执行）
│   ├── monitor_core.py       # 监控核心（网络探测与自动切换）
│   ├── network_test.py       # 网络连通性检测
│   ├── playwright_bootstrap.py # Playwright 运行环境准备
│   ├── system_tray.py        # 系统托盘集成
│   ├── version.py            # 版本号读取
│   └── utils/                # 工具模块
│       ├── config.py         # 配置加载与管理
│       ├── logging.py        # 日志系统
│       ├── crypto.py         # 密码加密
│       ├── browser.py        # 浏览器上下文管理
│       ├── login.py          # 登录尝试处理
│       ├── retry.py          # 重试策略
│       ├── time.py           # 时间工具
│       └── exceptions.py     # 异常处理
├── frontend/                 # 前端控制台
│   ├── index.html            # 入口页面
│   ├── app.js                # Vue 应用主文件
│   ├── template-loader.js    # 模板加载器
│   ├── js/                   # JavaScript 模块
│   │   ├── methods/          # 业务方法（按功能拆分）
│   │   ├── app-options.js    # Vue 应用配置
│   │   ├── bootstrap.js      # 应用初始化
│   │   ├── constants.js      # 常量定义
│   │   └── logger.js         # 前端日志
│   ├── partials/pages/       # 页面模板
│   │   ├── dashboard.html    # 仪表盘
│   │   ├── settings.html     # 设置页
│   │   ├── tasks.html        # 任务管理
│   │   ├── profiles.html     # 配置方案
│   │   └── about.html        # 关于页
│   └── styles/               # 样式文件
├── tasks/                    # 任务模板
├── tests/                    # 测试
├── doc/                      # 文档
│   └── task-manual.md        # 任务编写手册
├── debug/                    # 调试截图输出
├── logs/                     # 运行日志
└── release/                  # 发布产物
```

### 主要模块说明

- `app.py`：统一启动入口，负责服务启动、状态查询、自启动控制和浏览器打开。
- `backend/main.py`：FastAPI 主应用，提供 HTTP API 和 WebSocket。
- `backend/config_service.py`：配置读写、`.env` 原子写入、初始化状态管理。
- `backend/profile_service.py`：多网络配置方案管理，网关/SSID 检测，自动切换。
- `backend/monitor_service.py`：网络监控、认证触发、WebSocket 日志广播。
- `backend/task_service.py`：任务读写、活动任务管理、危险步骤检测。
- `backend/autostart_service.py`：跨平台开机自启动（Windows VBS / macOS LaunchAgent / Linux systemd）。
- `src/task_executor.py`：任务执行器，负责按 JSON 步骤逐条执行浏览器操作。
- `src/monitor_core.py`：监控核心，网络探测循环与 Profile 自动切换。
- `src/network_test.py`：网络连通性检测（TCP 探测）。
- `src/playwright_bootstrap.py`：Playwright 运行环境检查与自动安装。
- `src/system_tray.py`：系统托盘图标与菜单。
- `src/utils/`：工具模块集（配置、日志、加密、浏览器、重试等）。

## 技术栈

### 后端

- FastAPI：HTTP API 和 WebSocket。
- Uvicorn：ASGI 服务运行器。
- Pydantic：配置与请求数据校验。
- Playwright：浏览器自动化执行。
- httpx：网络检测。
- cryptography：密码加密。

### 前端

- Vue 3：控制台界面（单文件，无构建工具）。
- Axios：后端 API 通信。
- 原生 WebSocket：实时日志流。

### 工具与辅助

- pystray / Pillow / cairosvg：系统托盘。
- python-dotenv：环境变量加载。
- pytest：测试框架。

## API 概览

以下是当前项目的主要接口分组，适合开发联调或前后端扩展时快速查阅。

### 健康检查与系统

```text
GET  /api/health             # 健康检查，返回状态和版本
POST /api/shutdown           # 关闭服务（停止监控、托盘、进程）
```

### 配置管理

```text
GET  /api/config             # 获取当前配置
PUT  /api/config             # 保存配置
GET  /api/init-status        # 初始化状态（是否已设置账号密码）
```

### 配置方案

```text
GET    /api/profiles              # 列出所有方案
GET    /api/profiles/active       # 获取活动方案详情
GET    /api/profiles/{id}         # 获取指定方案
PUT    /api/profiles/{id}         # 创建/更新方案（活动方案自动热重载）
DELETE /api/profiles/{id}         # 删除方案（default 不可删除）
POST   /api/profiles/active/{id}  # 设置活动方案
POST   /api/profiles/detect       # 检测当前网络环境（网关 IP、SSID、匹配方案）
POST   /api/profiles/auto-switch  # 切换自动切换开关
```

### 监控控制

```text
GET  /api/status             # 监控状态
POST /api/monitor/start      # 启动监控
POST /api/monitor/stop       # 停止监控
```

### 手动操作

```text
POST /api/actions/login          # 手动触发登录
POST /api/actions/test-network   # 测试网络连通性
```

### 任务管理

```text
GET    /api/tasks               # 列出所有任务
GET    /api/tasks/{id}          # 获取指定任务
PUT    /api/tasks/{id}          # 创建/更新任务
DELETE /api/tasks/{id}          # 删除任务（default 不可删除）
GET    /api/tasks/active        # 获取当前活动任务
POST   /api/tasks/active/{id}   # 设置活动任务
```

### 日志

```text
GET  /api/logs?limit=200     # 获取历史日志（内存缓冲区，最多 1200 条）
WS   /ws/logs                # WebSocket 实时日志流
```

### 自启动

```text
GET  /api/autostart/status   # 自启动状态（平台、方式、位置）
POST /api/autostart/enable   # 启用自启动
POST /api/autostart/disable  # 禁用自启动
```

### 静态资源

```text
GET  /debug/{filename}       # 调试截图文件访问
```

### API 鉴权

设置 `API_TOKEN` 环境变量后，所有写操作（POST/PUT/DELETE）需要在请求头中携带 `X-API-Token`。未设置时不需要鉴权。

## 开发与调试

### 运行测试

```bash
uv run pytest
uv run pytest tests/test_task_executor.py -v
```

### 代码检查与格式化

```bash
uv run ruff check .
uv run ruff format .
```

### 常用调试入口

#### 配置加载

```python
from src.utils import ConfigLoader

config = ConfigLoader.load_config_from_env()
```

#### 配置管理（单例缓存）

```python
from src.utils import ConfigManager

config = ConfigManager.get_config()
config = ConfigManager.reload_config()
```

#### 日志

```python
from src.utils.logging import get_logger

logger = get_logger("my_module")
```

#### 任务执行

```python
from src.task_executor import TaskExecutor, TaskConfig

config = TaskConfig(task_dict)
executor = TaskExecutor(config, env_vars)
success, message = await executor.execute(page)
```

#### 多网络方案

```python
from backend.profile_service import ProfileService

service = ProfileService(settings_path, env_path)
gateway_ip = service.get_gateway_ip()
ssid = service.get_wifi_ssid()
matched = service.match_profile(gateway_ip, ssid)
```

## 常见问题

### 报错 No module named dotenv

这通常表示 Python 解释器选错了。请优先使用项目环境中的解释器：

```powershell
.\environment\python\python.exe app.py
```

### Playwright 或 Chromium 下载失败

项目会优先使用环境变量里配置的下载源，其次使用默认镜像地址。如果网络环境比较特殊，可以手动设置：

```env
PLAYWRIGHT_DOWNLOAD_HOST=https://npmmirror.com/mirrors/playwright
```

如果你使用的是发布包，也建议确认启动日志里是否已经完成浏览器准备。

### 服务提示已启动

项目带有重复启动保护。如果你怀疑已经有实例在运行，可以先查看状态再决定是否停止：

```bash
python app.py --status
python app.py --stop
```

### 认证不成功

建议按这个顺序排查：

1. 账号和密码是否正确。
2. `LOGIN_URL` 是否能正常打开。
3. `ISP` 是否和当前网络运营商匹配。
4. 在 Web 控制台查看实时日志和失败截图。
5. 暂时关闭无头模式，观察浏览器具体执行了什么操作。

### 日志不显示或有延迟

- 确认后端服务本身在运行。
- 检查浏览器开发者工具中的 WebSocket 连接状态。
- 刷新页面后重新订阅日志流。

### 多个校园网怎么配置

使用"配置方案"页面为每个网络创建独立的 Profile，设置匹配条件（网关 IP 或 WiFi SSID），并开启自动切换。系统会在检测到网络变化时自动切换到匹配的方案。

### 保存任务时弹出安全警告

这是因为任务中包含 `eval` 或 `custom_js` 步骤，这些步骤可以执行任意 JavaScript 代码。系统会显示代码内容要求确认。确认代码安全后点击确认即可。

### 自启动被杀毒软件拦截

Windows 自启动使用 VBS 脚本，部分杀毒软件可能会拦截。建议将程序目录添加到杀毒软件白名单，或暂时关闭杀毒软件后重试 `python app.py --autostart enable`。

## 更新日志

### v3.3.0

- 替换项目 Logo 为新图标。
- 全面更新文档：合并任务文档、同步新特性、清理过时内容。
- 清理仓库：移除废弃代码、更新 .gitignore。

### v3.2.0

- 新增多网络配置方案（Profiles）系统：支持为不同网络环境创建独立配置，按网关 IP 或 WiFi SSID 自动切换。
- 新增配置方案管理页面（profiles.html）。
- 新增网关 IP 和 WiFi SSID 跨平台检测。
- 优化任务执行器序列化（to_dict），输出更紧凑。
- 规范化 eval 步骤字段：统一使用 script，兼容已废弃的 code。
- 改进任务来源管理：API 保存的任务自动保留原有 builtin/signed 来源。
- 新增任务导入导出、复制功能。
- 新增 eval/custom_js 步骤安全确认对话框。
- 新增 API 写操作鉴权（API_TOKEN）。
- 新增日志按级别筛选和文本搜索。
- 新增截图链接点击查看。
- 新增 WebSocket 断线重连（指数退避）。
- 新增未保存配置检测提醒。
- 新增服务关闭 API（/api/shutdown）。
- 移除未使用的骨架屏动画和代码预览样式。
- 新增 step/condition 的 to_dict 方法，优化任务存储格式。
- 添加任务执行器单元测试覆盖。

### v3.1.0

- 优化 WebSocket 实时日志推送。
- 添加日志自动滚动功能。
- 精细化异常处理。
- 添加配置管理单例模式。
- 添加任务执行器变量解析缓存。

### v3.0.1

- 初始稳定版本。
- Web 控制台。
- 任务系统。
- 系统托盘支持。

## 许可证

详见 [LICENSE](LICENSE)。
