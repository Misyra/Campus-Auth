# Campus-Auth 校园网自动认证

Campus-Auth 是一个基于 Playwright、FastAPI 和 Vue 3 的校园网自动认证工具。它既可以作为终端用户直接运行的本地服务，也适合作为开发调试项目使用。项目提供 Web 控制台、自动监控、任务模板、多网络配置方案、系统托盘、自启动与日志可视化，目标是让校园网认证尽量做到"装好即用、断网即连、问题可查"。

新视频
【[适配90%的学校]小刻也能学会的通用校园网自动认证教程】 https://www.bilibili.com/video/BV1d35E6mEVB/?share_source=copy_web&vd_source=db13da6ef2846b31b874687783211f99
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

- `settings.json` 文件：存储多网络配置方案（Profiles）和全局系统设置，由 Web 控制台管理。

首次使用时系统会通过初始化向导引导你填写配置，所有配置统一存储在 `settings.json` 中。

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

#### 监控配置

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `AUTO_START_MONITORING` | `false` | 启动后是否自动开始网络监控。 |
| `MONITOR_INTERVAL` | `300` | 网络检测间隔，单位秒。 |
| `PING_TARGETS` | `8.8.8.8:53,114.114.114.114:53,www.baidu.com:443` | 探测目标列表。 |
| `MAX_CONSECUTIVE_FAILURES` | `3` | 连续登录失败次数上限。 |
| `RETRY_MAX_RETRIES` | `3` | 登录重试最大次数。 |
| `RETRY_INTERVAL` | `5` | 重试间隔，单位秒。 |

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
| `BROWSER_LOW_RESOURCE_MODE` | `false` | 是否启用低资源模式（屏蔽图片、字体、媒体）。 |
| `BROWSER_USER_AGENT` | 内置默认值 | 自定义 User-Agent。 |
| `BROWSER_EXTRA_HEADERS_JSON` | 空 | 额外请求头，JSON 格式。 |
| `BROWSER_DISABLE_WEB_SECURITY` | `false` | 禁用浏览器同源策略。 |

#### 系统配置

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `MINIMIZE_TO_TRAY` | `true` | 是否最小化到系统托盘。 |
| `CUSTOM_VARIABLES` | `{}` | 自定义变量，JSON 格式，可在任务模板中引用。 |
| `AUTO_OPEN_BROWSER` | `false` | 启动后是否自动打开浏览器（可通过 Web 控制台设置覆盖）。 |

#### Playwright 配置

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `AUTO_INSTALL_PLAYWRIGHT` | `true` | 是否自动安装 Chromium。 |
| `PLAYWRIGHT_DOWNLOAD_HOST` | `https://npmmirror.com/mirrors/playwright` | Playwright 下载镜像源。 |

#### settings.json 专有配置

以下配置仅通过 Web 控制台或直接编辑 `settings.json` 设置，不支持环境变量：

| 选项 | 默认值 | 说明 |
|------|--------|------|
| `login_then_exit` | `false` | 登录成功后自动退出程序，适用于只需登录一次的场景。 |
| `proxy` | 空 | 网络代理地址，用于远程任务仓库访问。留空不使用代理。 |
| `browser_args` | 见默认值 | 自定义 Chromium 启动参数，每行一个，用于反检测或浏览器行为定制。 |
| `safe_mode` | `false` | 安全模式，使用纯净 Chromium（无扩展、无自定义参数）。 |
| `access_log` | `false` | 是否输出 Uvicorn HTTP 访问日志。 |
| `log_retention_days` | `7` | 日志文件保留天数（1-365）。 |
| `screenshot_retention_days` | `7` | 截图文件保留天数（1-90）。 |

## 任务系统

任务系统使用 JSON 文件描述浏览器自动化认证流程，支持多种步骤类型、变量模板、网络检测兜底成功判断和帧上下文。任务文件存放在 `tasks/` 目录，通过 Web 控制台管理（新建、编辑、导入导出、复制、设置活动任务）。

- [任务开发参考](doc/task-manual.md) — 架构、步骤类型、变量解析、API 接口
- [任务编写指南](doc/task-writing-guide.md) — 完整示例、最佳实践、常见问题

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
├── backend/                  # 后端服务
│   ├── main.py               # FastAPI 主应用
│   ├── config_service.py     # 配置读写与初始化状态
│   ├── profile_service.py    # 多网络配置方案管理
│   ├── monitor_service.py    # 网络监控与认证触发
│   ├── task_service.py       # 任务读写与活动任务管理
│   ├── autostart_service.py  # 开机自启动管理
│   ├── uninstall_service.py  # 卸载功能服务
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
│       ├── time.py           # 时间工具
│       ├── time.py           # 时间工具
│       ├── notify.py         # 跨平台桌面通知
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
│   ├── task-manual.md        # 任务开发参考
│   └── task-writing-guide.md # 任务编写指南
├── tools/                    # 辅助工具
│   └── task-recorder.user.js # Tampermonkey 任务录制脚本
├── debug/                    # 调试截图输出
├── logs/                     # 运行日志
└── release/                  # 发布产物
```

### 主要模块说明

- `app.py`：统一启动入口，负责服务启动、状态查询、自启动控制和浏览器打开。
- `backend/main.py`：FastAPI 主应用，提供 HTTP API 和 WebSocket。
- `backend/config_service.py`：配置读写、初始化状态管理。
- `backend/profile_service.py`：多网络配置方案管理，网关/SSID 检测，自动切换。
- `backend/monitor_service.py`：网络监控、认证触发、WebSocket 日志广播。
- `backend/task_service.py`：任务读写、活动任务管理、危险步骤检测。
- `backend/autostart_service.py`：跨平台开机自启动（Windows VBS / macOS LaunchAgent / Linux systemd）。
- `backend/uninstall_service.py`：卸载功能，扫描并清理程序文件、配置、日志等。
- `src/task_executor.py`：任务执行器，负责按 JSON 步骤逐条执行浏览器操作。
- `src/monitor_core.py`：监控核心，网络探测循环与 Profile 自动切换。
- `src/network_test.py`：网络连通性检测（TCP 探测 + HTTP 探测，自动降级）。
- `src/playwright_bootstrap.py`：Playwright 运行环境检查与自动安装。
- `src/system_tray.py`：系统托盘图标与菜单。
- `src/utils/notify.py`：跨平台桌面通知（登录成功/失败提醒）。
- `src/utils/`：工具模块集（配置、日志、加密、浏览器、重试等）。

## 技术栈

### 后端

- FastAPI：HTTP API 和 WebSocket。
- Uvicorn：ASGI 服务运行器。
- Pydantic：配置与请求数据校验。
- Playwright：浏览器自动化执行。
- socket + httpx：网络检测（TCP 探测 + HTTP 探测）。
- cryptography：密码加密。
- ddddocr：验证码 OCR 识别（任务步骤中使用）。

### 前端

- Vue 3：控制台界面（单文件，无构建工具）。
- Axios：后端 API 通信。
- 原生 WebSocket：实时日志流。

### 工具与辅助

- pystray / Pillow / cairosvg：系统托盘。
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

这是因为任务中包含 `eval` 步骤，该步骤可以执行任意 JavaScript 代码。系统会显示代码内容要求确认。确认代码安全后点击确认即可。

### 自启动被杀毒软件拦截

Windows 自启动使用 VBS 脚本，部分杀毒软件可能会拦截。建议将程序目录添加到杀毒软件白名单，或暂时关闭杀毒软件后重试 `python app.py --autostart enable`。

## 更新日志

### v3.6.7

- **隐藏输入框处理全面重构**：新增 `reveal_hidden` 配置，执行前自动显示所有隐藏输入框；普通 fill/click 失败后自动降级到 force 模式，无需手动配置
- **任务录制器重大升级**：智能检测统一模式、成功条件下拉选择、步骤可编辑；点击高亮元素弹出步骤选择菜单；新增显示隐藏模式（绿色虚线高亮 + 浮动标签 + 左侧独立面板）
- **成功条件判断逻辑重构**：移除录制器中的成功条件判断，统一由后端网络检测兜底；修复 success_conditions 空数组被静默丢弃的问题
- **环境变量命名规范化**：所有 `Campus-Auth_` 前缀改为 `CAMPUS_AUTH_`，移除 python-dotenv 依赖和 .env 文件加载
- **登录流程优化**：提取 `build_login_env_vars` 为共享工具；修复浏览器初始化时 `browser_manager` 未绑定警告；页面弹窗拦截并延迟 1.5s 关闭，记录内容到日志
- **性能优化**：普通 fill/click 首次超时从 3s 降到 1.5s；URL 稳定检测上限从 5s 降至 3s；导航后页面稳定等待从 2s 降至 1s；登录成功后等待 2s 再做网络检测；监控循环增加 2s 缓冲
- **设置页支持 `app_port` 配置**：修复 shutdown 和端口解析问题
- **新增核心模块单元测试覆盖**
- **修复嵌入式 Python 启动报错**：启动时自动将项目根目录加入 `sys.path`

### v3.6.4

- **`login_then_exit` 改为重试直到成功**：不再一次失败就退出，指数退避重试（最多 3 次），超限后回退到正常模式启动服务器，避免误判导致服务停止。
- **新增 `--no-auto` 启动参数**：跳过自动登录和自动启动监控，用于 `login_then_exit` 开启后无法进入 Web 控制台的恢复场景。
- **设置页新增重试配置**：最大登录重试次数（1~5）和重试间隔秒数（1~300），`monitor_core` 侧强制限幅 1~5 防止异常配置。
- **任务录制器改为生成 AI 提示词**：移除直接导出 JSON/Markdown，改为复制结构化提示词，发送给 AI 模型即可生成任务 JSON。提示词自动汇总步骤类型映射、隐藏输入框警告、验证码说明和成功条件。
- **任务录制器快捷键改为 `Ctrl+Shift+E`**：避免与浏览器强制刷新快捷键冲突。
- ~~**任务执行器新增 `skip` 条件类型**~~：等价于空成功条件，步骤完成即成功。外加步骤 ID 格式校验。（已计划，未发布）
- **任务编写指南禁止硬编码 URL**：分享/提交任务时 `url` 字段须留空或使用 `{{LOGIN_URL}}`，由用户自行配置认证地址。
- 文档/打包/环境脚本配套更新。

### v3.6.3

- **`input` 步骤新增 `force` 参数**：支持对 `display:none` 的隐藏输入框强制填入值，通过 JS 原生 setter + 事件派发实现，解决深澜/Sangfor 系校园网门户密码框隐藏的问题。
- **任务录制器（油猴脚本）隐藏输入框检测**：统一检测深澜/Sangfor（假 type=text 占位）和杭州康工 HK Posi（readonly tip + 容器 div）两类隐藏输入框模式，同时覆盖账号和密码输入框；检测到后导出自动生成 click 占位 + force 输入步骤。
- **任务录制器（油猴脚本）独立功能开关**：新增「多步录制」和「隐藏检测」两个独立按钮，多步录制开启后每次点击记录一步不自动停止，隐藏检测控制是否自动扫描 `display:none` 输入框；Enter 键在录制模式下可记录悬停元素而不触发页面 click；面板内建可折叠详细说明和使用手册弹窗。
- **任务录制器（油猴脚本）DOM 守护**：MutationObserver + 定时轮询双保险，防止门户 JS 在 `document-idle` 后冲刷 `body.innerHTML` 导致浮动按钮/面板消失。
- 修复部分校园网门户录制时密码步骤选择器指向假输入框导致填表失败的问题。

### v3.6.2

- 重构配置读写分离：设置页面始终展示和修改全局设置，方案页面管理方案独立设置。
- 修复方案启用"使用全局高级设置"时，设置页面修改 headless 等高级选项保存后刷新又变回默认值的问题。
- 修复网络状态 UI 不能准确反映实际连接状态的问题。
- 反检测脚本改为默认关闭，修复首页一键登录页面空白问题。

### v3.6.1

- Mac/Linux 支持下载嵌入式 Python 3.10，与 Windows 保持一致。
- 物理网络断开时跳过登录，避免无意义的浏览器启动。
- Playwright 检测同步检查 chromium_headless_shell，确保完整浏览器环境就绪。
- 修复登录失败时前端重复渲染截图的问题。
- 修复日志自动滚动失效的问题。

### v3.6.0

- 新增 OCR 验证码自动识别（ddddocr），支持截图识别并填入输入框。
- 新增任务步骤支持 `<frame>` 上下文（frameset/iframe 页面）。
- 新增录制器支持 `<frame>` 元素检测和事件绑定。
- 新增远程任务仓库导入，支持浏览、搜索、一键下载社区适配方案。
- 新增卸载功能，支持前端界面和命令行两种方式，清理自启动、加密密钥、浏览器缓存等外部残留。
- 新增关于页面检查更新功能。
- 新增登录请求超时设置。
- 重构任务系统，优化任务编辑器和 JSON 配置体验。
- 重构日志系统，打通前端日志到后端链路，支持 WebSocket 实时推送和按级别筛选。
- 监控重试时复用浏览器实例，避免重复开关。
- 浏览器复用前添加健康检查，避免使用已崩溃的实例。
- 改进网络连接检测：支持有线/无线网络实际连接状态检查，避免无网络时徒增功耗。
- HTTP 网络检测仅将 2xx 状态码视为成功（修复认证门户 302 重定向误判）。
- Windows 网关检测改用 PowerShell Get-NetRoute（结构化输出，不受系统语言影响）。
- macOS SSID 检测添加 networksetup 回退方案。
- Windows SSID 检测修复非 ASCII SSID 的编码问题。
- Linux 自启动修复路径含空格时的引号处理问题。
- 改进浏览器反检测脚本：模拟真实 PluginArray、完善 chrome 对象属性、覆盖 languages。
- 改进低资源模式：除图片外同时屏蔽字体和媒体文件。
- setup/launcher 镜像源优先级改为 CERNET，Python 下载添加多源回退和进度条。
- 前端 UI 优化：任务页标题改为"任务列表"，关于页标题分行显示中英文。
- 移除 API_TOKEN 鉴权功能（本地项目无需对外鉴权）。
- 修复复制任务时 ID 覆盖问题。
- 修复危险确认对话框页面切换后 Promise 永久挂起问题。
- 修复 CORS 端口与实际服务端口不一致问题。
- 修复代码审查发现的多项 Bug。

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
- 新增任务导入导出、复制功能。
- 新增 eval 步骤安全确认对话框。
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

## 致谢

- [ddddocr](https://github.com/sml2h3/ddddocr) — 验证码识别引擎，本项目使用它处理图形验证码。

## 许可证

详见 [LICENSE](LICENSE)。
