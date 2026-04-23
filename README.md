# Campus-Auth 校园网自动认证

Campus-Auth 是一个基于 Playwright、FastAPI 和 Vue 3 的校园网自动认证工具。它既可以作为终端用户直接运行的本地服务，也适合作为开发调试项目使用。项目提供 Web 控制台、自动监控、任务模板、系统托盘、自启动与日志可视化，目标是让校园网认证尽量做到“装好即用、断网即连、问题可查”。

## 项目能做什么

Campus-Auth 主要解决三个场景：

1. 开机后自动保持网络在线，避免手动重复登录。
2. 在网络掉线、会话失效或页面失效时，自动回到认证流程并重试。
3. 通过 Web 控制台统一管理配置、任务、日志和运行状态。

### 主要特性

- Web 控制台：初始化向导、仪表盘、设置页、任务页、关于页。
- 自动监控：定时探测网络可用性，异常时自动触发认证。
- 自动登录：基于 Playwright 的浏览器自动化，按任务定义执行登录流程。
- 任务系统：使用 JSON 描述认证步骤，便于适配不同校园网页面。
- 实时日志：通过 WebSocket 推送运行日志，前端可实时查看。
- 开机自启动：支持在 Windows、macOS 和 Linux 上配置自启动。
- 系统托盘：可在后台最小化到托盘运行。
- 防重复启动：同时检测 PID 文件和本地端口，避免重复拉起同一实例。
- 智能状态判断：识别已登录状态，减少重复提交和无效请求。
- 暂停时段：支持在夜间或指定时间段暂停自动登录。
- 失败重试：使用退避策略降低短时间内的重复冲击。

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

项目支持两种常见配置方式：

- 通过 `.env` 文件写入环境变量。
- 通过 Web 控制台的初始化向导和设置页面直接保存。

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

#### 系统配置

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `MINIMIZE_TO_TRAY` | `true` | 是否最小化到系统托盘。 |

#### 自定义变量与 Playwright

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `CUSTOM_VARIABLES` | `{}` | 自定义变量，JSON 格式，可在任务模板中引用。 |
| `AUTO_INSTALL_PLAYWRIGHT` | `true` | 是否自动安装 Chromium。 |
| `PLAYWRIGHT_DOWNLOAD_HOST` | `https://npmmirror.com/mirrors/playwright` | Playwright 下载镜像源。 |

## 任务系统

任务系统采用 JSON 文件描述认证流程，适合不同校园网页面、不同按钮名称和不同跳转逻辑。你可以把它理解为一份“自动登录脚本配置”。

### 任务文件位置

项目默认把任务放在 `tasks/` 目录下，常见文件包括：

- `default.json`：默认认证任务。
- `sample.json`：基础示例任务。
- `sample_2.json`：更复杂的示例任务。
- `active.txt`：当前活动任务标识。

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

| 类型 | 说明 | 常见参数 |
|------|------|----------|
| `navigate` | 打开指定页面。 | `url`, `wait_until`, `timeout` |
| `input` | 在输入框中填写文本。 | `selector`, `value`, `clear`, `timeout` |
| `click` | 点击页面元素。 | `selector`, `timeout` |
| `select` | 选择下拉框选项。 | `selector`, `value`, `timeout` |
| `wait` | 等待元素出现。 | `selector`, `timeout` |
| `wait_url` | 等待 URL 匹配指定模式。 | `pattern`, `timeout` |
| `eval` | 执行 JavaScript 并保存结果。 | `script`, `store_as` |
| `custom_js` | 执行自定义 JavaScript。 | `script` |
| `screenshot` | 截图保存。 | `path` |

更完整的任务格式说明请参考 [doc/task-system.md](doc/task-system.md)。

### 编写建议

- 优先给每一步写清楚 `description`，方便日志回溯。
- 选择器尽量写得稳一点，避免只依赖单个脆弱的 CSS 片段。
- 如果页面会跳转，建议在登录后增加 URL 或结果页判断。
- 失败时建议开启截图，便于定位页面变化或表单异常。
- 如果你的认证页面会返回不同结果文案，可以在成功条件里同时配置多个判断依据。

## 项目结构

```text
Campus-Auth/
├── app.py                  # 统一启动入口
├── launcher.py             # Windows 启动器
├── pyproject.toml          # 项目元数据与依赖配置
├── requirements.txt        # 依赖列表
├── backend/                # 后端服务
├── frontend/               # 前端控制台
├── src/                    # 核心逻辑与工具模块
├── tasks/                  # 任务模板
├── tests/                  # 测试
├── doc/                    # 任务与系统文档
└── logs/                   # 日志目录
```

### 主要模块说明

- `app.py`：统一启动入口，负责服务启动、状态查询、自启动控制和浏览器打开。
- `backend/main.py`：FastAPI 主应用，提供 API 和 WebSocket。
- `backend/config_service.py`：配置读写与初始化状态管理。
- `backend/monitor_service.py`：网络监控与认证触发。
- `backend/task_service.py`：任务读写与活动任务管理。
- `src/campus_login.py`：登录执行链路。
- `src/task_executor.py`：任务执行器，负责按 JSON 步骤逐条执行。
- `src/playwright_bootstrap.py`：Playwright 运行环境准备。
- `src/system_tray.py`：系统托盘集成。
- `frontend/`：控制台页面、样式和前端逻辑。

## 技术栈

### 后端

- FastAPI：提供 HTTP API 和 WebSocket。
- Uvicorn：ASGI 服务运行器。
- Pydantic：配置与请求数据校验。
- Playwright：浏览器自动化执行。
- WebSocket：推送实时日志。

### 前端

- Vue 3：构建控制台界面。
- Axios：与后端 API 通信。
- 原生 WebSocket：订阅实时日志流。

### 工具与辅助

- httpx / socket：网络检测。
- pystray：系统托盘。
- cryptography：密码加密。

## API 概览

以下是当前项目的主要接口分组，适合开发联调或前后端扩展时快速查阅。

### 健康检查

```text
GET /api/health
```

### 配置管理

```text
GET /api/config        # 获取配置
PUT /api/config        # 保存配置
GET /api/init-status   # 初始化状态
```

### 监控控制

```text
GET  /api/status           # 监控状态
POST /api/monitor/start    # 启动监控
POST /api/monitor/stop      # 停止监控
```

### 手动操作

```text
POST /api/actions/login        # 手动登录
POST /api/actions/test-network # 网络测试
```

### 日志

```text
GET /api/logs?limit=200   # 获取历史日志
WS  /ws/logs              # WebSocket 实时日志
```

### 任务管理

```text
GET    /api/tasks               # 列出任务
GET    /api/tasks/{id}          # 获取任务
PUT    /api/tasks/{id}          # 保存任务
DELETE /api/tasks/{id}          # 删除任务
GET    /api/tasks/active        # 获取活动任务
POST   /api/tasks/active/{id}   # 设置活动任务
```

### 自启动

```text
GET  /api/autostart/status   # 自启动状态
POST /api/autostart/enable   # 启用自启动
POST /api/autostart/disable  # 禁用自启动
```

### 服务控制

```text
POST /api/shutdown   # 关闭服务
```

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

### 常用调试对象

#### ConfigManager

配置管理采用单例缓存，适合在多处读取同一份运行配置：

```python
from src.utils import ConfigManager

config = ConfigManager.get_config()
config = ConfigManager.reload_config()
```

#### LogConfigCenter

日志中心统一管理不同组件的日志器：

```python
from src.utils.logging import LogConfigCenter

center = LogConfigCenter.get_instance()
center.initialize(config, side="BACKEND")
logger = center.get_logger("my_module")
```

#### TaskExecutor

任务执行器负责读取任务配置、解析变量并逐步执行页面操作：

```python
from src.task_executor import TaskExecutor, TaskConfig

config = TaskConfig(task_dict)
executor = TaskExecutor(config, env_vars)
success, message = await executor.execute(page)
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

## 更新日志

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
