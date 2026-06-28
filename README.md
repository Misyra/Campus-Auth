# Campus-Auth 校园网自动认证

Campus-Auth 是一个基于 Playwright、FastAPI 和 Vue 3 的校园网自动认证工具。它既可以作为终端用户直接运行的本地服务，也适合作为开发调试项目使用。项目提供 Web 控制台、自动监控、任务模板、多网络配置方案、系统托盘、自启动与日志可视化，目标是让校园网认证尽量做到"装好即用、断网即连、问题可查"。

新视频
【小刻也能学会的通用校园网自动认证教程】 https://www.bilibili.com/video/BV1d35E6mEVB/?share_source=copy_web&vd_source=db13da6ef2846b31b874687783211f99

## 项目能做什么

Campus-Auth 主要解决三个场景：

1. 开机后自动保持网络在线，避免手动重复登录。
2. 在网络掉线、会话失效或页面失效时，自动回到认证流程并重试。
3. 通过 Web 控制台统一管理配置、任务、日志和运行状态。

### 主要特性

- Web 控制台：初始化向导、仪表盘、设置页、任务页、Python 脚本页、日志页、外观页、配置方案页、关于页。
- 多网络配置方案：为不同网络环境创建独立配置，支持按网关 IP 或 WiFi SSID 自动切换。
- 自动监控：定时探测网络可用性，异常时自动触发认证。
- 自动登录：基于 Playwright 的浏览器自动化，按任务定义执行登录流程。
- 任务系统：使用 JSON 描述认证步骤，支持导入导出、复制、安全检测。
- 实时日志：通过 WebSocket 推送运行日志，支持按级别筛选和文本搜索。
- 开机自启动：支持在 Windows、macOS 和 Linux 上配置自启动。
- 系统托盘：可在后台最小化到托盘运行。轻量模式下支持按需唤醒 Web 控制台。
- 防重复启动：同时检测 PID 文件和本地端口，避免重复拉起同一实例。
- 智能状态判断：识别已登录状态，减少重复提交和无效请求。
- 暂停时段：支持在夜间或指定时间段暂停自动登录。
- 失败重试：使用退避策略降低短时间内的重复冲击。

## 运行前准备

### 推荐环境

- Python 3.12 或更高版本。
- 推荐使用 uv 管理依赖。

### 端口与访问地址

默认 Web 控制台端口为 50721，启动后可在浏览器访问：

http://127.0.0.1:50721

如果你修改了 `APP_PORT`，则以实际端口为准。

## 快速开始

安装依赖：

```bash
uv sync
```

启动服务：

```bash
python main.py
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

`main.py` 支持若干命令行参数，用于控制服务启动、状态查询和自启动管理。

```bash
# 基础启动
python main.py

# 启动但不自动打开浏览器
python main.py --no-browser

# 不启动系统托盘
python main.py --no-tray

# 指定运行模式
python main.py --runtime-mode lightweight   # 轻量模式（无 Web UI，可通过托盘唤醒）

# 查看服务状态
python main.py --status

# 停止服务
python main.py --stop

# 强制启动（杀死已有实例）
python main.py --force

# 自启动管理
python main.py --autostart
python main.py --autostart enable
python main.py --autostart disable

# 指定启动动作
python main.py --startup-action monitor    # 启动后自动开始监控
python main.py --startup-action login_once  # 登录一次后退出

# 指定运行模式
python main.py --runtime-mode lightweight   # 轻量模式（无 Web UI）
```

## 配置说明

### 配置来源

项目配置存储在 `config/` 目录：

- `config/settings.json`：主配置文件，存储凭证、认证地址、监控设置等。
- `config/profiles/`：配置方案目录，存储多网络配置方案数据。

首次使用时系统会通过初始化向导引导你填写配置，所有配置统一存储在 `config/settings.json` 中。

### 高级配置

项目的所有配置现已统一通过 Web 控制台管理。首次使用时，Web 控制台的初始化向导会引导你完成配置。如需高级配置（端口、代理等），可直接编辑 `config/settings.json` 或通过 Web 控制台"设置"页面操作。

以下配置仅通过 Web 控制台或直接编辑 `config/settings.json` 设置，不支持环境变量：

| 选项 | 默认值 | 说明 |
|------|--------|------|
| `startup_action` | `monitor` | 启动后执行的动作。`monitor`：自动监控；`login_once`：登录一次后退出。 |
| `proxy` | 空 | 网络代理地址，用于远程任务仓库访问。留空不使用代理。 |
| `browser_args` | 见默认值 | 自定义 Chromium 启动参数，每行一个，用于反检测或浏览器行为定制。 |
| `pure_mode` | `true` | 纯净模式，使用 Chromium 原始设置，不注入自定义参数。 |
| `block_proxy` | `true` | 阻止系统代理设置，使用直连网络。 |
| `access_log` | `false` | 是否输出 Uvicorn HTTP 访问日志。 |
| `log_retention_days` | `7` | 日志与截图保留天数（1-365），过期日期目录整体删除。 |

## 任务系统

任务系统使用 JSON 文件描述自动化认证流程，支持多种步骤类型、变量模板、网络检测兜底成功判断和帧上下文。任务文件存放在 `tasks/` 目录，通过 Web 控制台管理（新建、编辑、导入导出、复制、设置活动任务）。

### 任务类型

1. **浏览器任务** (`tasks/browser/`)：使用 Playwright 执行浏览器自动化操作。
2. **脚本任务** (`tasks/scripts/`)：执行 Python、PowerShell 或 cmd 脚本。
3. **定时任务** (`tasks/scheduled/`)：在指定时间或间隔执行的任务。

- [任务开发参考](docs/task-manual.md) — 架构、步骤类型、变量解析、API 接口
- [任务编写指南](docs/task-writing-guide.md) — 完整示例、最佳实践、常见问题

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
├── main.py                   # 统一启动入口（CLI + 启动编排）
├── start.go / start.exe      # Go 启动程序
├── start.sh                  # macOS/Linux 启动脚本
├── pyproject.toml            # 项目元数据与依赖
├── config/                   # 运行时配置
│   ├── settings.json         # 主配置文件
│   └── profiles/             # 配置方案文件
├── app/                      # Python 后端
│   ├── application.py        # FastAPI 主应用
│   ├── container.py          # ServiceContainer 依赖注入
│   ├── schemas.py            # Pydantic 数据模型
│   ├── constants.py          # 共享常量
│   ├── deps.py               # FastAPI 依赖注入
│   ├── api/                  # API 路由
│   │   ├── monitor.py        # 监控控制
│   │   ├── config.py         # 配置管理
│   │   ├── tasks.py          # 任务管理
│   │   ├── profiles.py       # 配置方案
│   │   ├── debug.py          # 调试会话
│   │   ├── repo.py           # 仓库代理
│   │   ├── system.py         # 系统管理
│   │   ├── tools.py          # 工具下载
│   │   ├── scripts.py        # 脚本管理
│   │   ├── scheduled_tasks.py # 定时任务
│   │   ├── history.py        # 登录历史
│   │   ├── autostart.py      # 自启动管理
│   │   └── ocr.py            # OCR 管理
│   ├── services/             # 业务服务层
│   │   ├── engine.py         # 统一后台引擎（监控 + 调度）
│   │   ├── task_executor.py  # 任务执行（双线程池）
│   │   ├── task_service.py   # 任务 CRUD
│   │   ├── config_service.py # 配置读写
│   │   ├── profile_service.py # 配置方案管理
│   │   ├── runtime_config.py # 运行时配置合并
│   │   ├── monitor_service.py # 网络监控核心
│   │   ├── websocket_manager.py # WebSocket 管理
│   │   ├── autostart.py      # 自启动服务
│   │   ├── login_history_service.py # 登录历史
│   │   ├── debug_service.py  # 调试会话管理
│   │   ├── debug_session.py  # 调试会话状态
│   │   ├── task_registry.py  # 定时任务注册表
│   │   └── uninstall.py      # 卸载功能
│   ├── network/              # 网络检测
│   │   ├── probes.py         # TCP/HTTP/URL 探测
│   │   ├── decision.py       # 网络决策层
│   │   └── detect.py         # 网关/SSID 检测
│   ├── tasks/                # 任务模型
│   │   └── models.py         # TaskConfig, StepConfig 等
│   ├── workers/              # 工作线程
│   │   ├── playwright_worker.py  # Playwright Actor 工作线程
│   │   ├── playwright_bootstrap.py # Playwright 环境准备
│   │   └── script_runner.py  # 脚本执行器
│   ├── ui/                   # 系统 UI
│   │   └── system_tray.py    # 系统托盘
│   └── utils/                # 工具模块
│       ├── login.py          # 登录尝试处理
│       ├── browser.py        # 浏览器上下文管理
│       ├── crypto.py         # 密码加密
│       ├── logging.py        # 日志系统
│       └── ...               # 其他工具
├── frontend/                 # 前端控制台（Vue 3 SPA，无构建步骤）
├── tasks/                    # 任务定义
│   ├── browser/              # 浏览器任务（JSON）
│   ├── scripts/              # 脚本任务（JSON/.py）
│   └── scheduled/            # 定时任务（JSON）
├── tests/                    # pytest 测试
├── docs/                     # 文档
├── dev/                      # 开发笔记
├── resources/                # 资源文件
│   ├── icons/                # 图标
│   └── tools/                # 辅助工具（油猴脚本）
├── debug/                    # 日志与截图（按日期归档）
└── release/                  # 发布产物
```

### 主要模块说明

**入口与启动：**
- `main.py`：统一启动入口，负责 CLI 参数解析、服务启动、状态查询、自启动控制和浏览器打开。
- `start.go` / `start.exe`：Go 启动程序，自动下载 uv、安装依赖、启动应用。
- `start.sh`：macOS/Linux 启动脚本，功能同上。

**后端服务：**
- `app/application.py`：FastAPI 主应用，提供 HTTP API 和 WebSocket。
- `app/container.py`：ServiceContainer 依赖注入，统一管理服务生命周期。
- `app/services/config_service.py`：配置读写、初始化状态管理。
- `app/services/profile_service.py`：多网络配置方案管理，网关/SSID 检测，自动切换。
- `app/services/engine.py`：统一后台引擎，整合监控与调度。
- `app/services/monitor_service.py`：网络监控核心，网络探测循环与 Profile 自动切换。
- `app/services/task_service.py`：任务读写、活动任务管理、危险步骤检测。
- `app/services/task_executor.py`：任务执行器，双线程池架构。
- `app/services/login_history_service.py`：登录历史记录服务。
- `app/services/autostart.py`：跨平台开机自启动（Windows VBS / macOS LaunchAgent / Linux systemd）。
- `app/services/uninstall.py`：卸载功能，扫描并清理程序文件、配置、日志等。

**核心逻辑：**
- `app/network/probes.py`：网络探测实现（TCP/HTTP/URL），并发执行。
- `app/network/decision.py`：网络决策层，封装暂停检查、网络状态检查、登录前置检查。
- `app/network/detect.py`：网关 IP 和 WiFi SSID 检测。
- `app/workers/playwright_worker.py`：Playwright Actor 模型工作线程，所有浏览器操作统一收归。
- `app/workers/script_runner.py`：自定义脚本执行器，支持 Python/PowerShell/cmd 等外部程序。
- `app/tasks/models.py`：任务配置数据模型（TaskConfig, StepConfig 等）。

**工具模块：**
- `app/utils/browser.py`：浏览器上下文管理与反检测脚本注入。
- `app/utils/login.py`：登录尝试处理，浏览器任务和脚本任务编排。
- `app/utils/crypto.py`：密码加密（Fernet），密钥管理。
- `app/utils/logging.py`：日志系统（文件轮转、WebSocket 推送、控制台输出，基于 loguru）。

## 技术栈

### 后端

- FastAPI：HTTP API 和 WebSocket。
- Uvicorn：ASGI 服务运行器。
- Pydantic：配置与请求数据校验。
- Playwright：浏览器自动化执行。
- socket + httpx：网络检测（TCP 探测 + HTTP 探测）。
- psutil：网络检测（网关 IP 和 WiFi SSID 检测）。
- cryptography：密码加密。
- loguru：日志系统。
- ddddocr：验证码 OCR 识别（任务步骤中使用）。

### 前端

- Vue 3：控制台界面（单文件，无构建工具）。
- Axios：后端 API 通信。
- 原生 WebSocket：实时日志流。

### 工具与辅助

- pystray / Pillow / cairosvg：系统托盘。
- pytest：测试框架。

## API 接口

详见 [docs/api-doc.md](docs/api-doc.md)。

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

### 编译启动程序

`start.exe` 由 `start.go` 编译生成，需要 Go 1.20+：

```bash
go build -ldflags="-s -w" -o start.exe start.go
```

### 常用调试入口

#### 日志

```python
from app.utils.logging import get_logger

logger = get_logger("my_module")
```

#### 任务执行

```python
from app.tasks.models import TaskConfig
from app.services.task_executor import TaskExecutor

config = TaskConfig(task_dict)
executor = TaskExecutor(config, env_vars)
success, message = await executor.execute(page)
```

#### 多网络方案

```python
from app.services.profile_service import ProfileService

service = ProfileService(settings_path, env_path)
gateway_ip = service.get_gateway_ip()
ssid = service.get_wifi_ssid()
matched = service.match_profile(gateway_ip, ssid)
```

## 常见问题

### Playwright 或 Chromium 下载失败

项目会自动尝试多个镜像源下载 Playwright 和 Chromium。如果下载仍然失败，可以手动设置环境变量指定下载源：

```env
PLAYWRIGHT_DOWNLOAD_HOST=https://npmmirror.com/mirrors/playwright
```

### 服务提示已启动

项目带有重复启动保护。如果你怀疑已经有实例在运行，可以先查看状态再决定是否停止：

```bash
python main.py --status
python main.py --stop
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

Windows 自启动使用 VBS 脚本，部分杀毒软件可能会拦截。建议将程序目录添加到杀毒软件白名单，或暂时关闭杀毒软件后重试 `python main.py --autostart enable`。

## 更新日志

详见 [docs/update_log.md](docs/update_log.md)。

## 致谢

- [ddddocr](https://github.com/sml2h3/ddddocr) — 验证码识别引擎，本项目使用它处理图形验证码。

## 许可证

详见 [LICENSE](LICENSE)。
