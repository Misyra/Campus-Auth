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
uv run app.py
```

如果你希望直接使用仓库自带环境，也可以运行：

```powershell
.\environment\python\python.exe app.py
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

### 高级配置

项目的所有配置现已统一通过 Web 控制台管理，配置数据存储在项目目录下的 `settings.json` 文件中。首次使用时，Web 控制台的初始化向导会引导你完成配置。如需高级配置（端口、代理等），可直接编辑 `settings.json` 或通过 Web 控制台"设置"页面操作。

以下配置仅通过 Web 控制台或直接编辑 `settings.json` 设置，不支持环境变量：

| 选项 | 默认值 | 说明 |
|------|--------|------|
| `login_then_exit` | `false` | 登录成功后自动退出程序，适用于只需登录一次的场景。 |
| `proxy` | 空 | 网络代理地址，用于远程任务仓库访问。留空不使用代理。 |
| `browser_args` | 见默认值 | 自定义 Chromium 启动参数，每行一个，用于反检测或浏览器行为定制。 |
| `pure_mode` | `false` | 纯净模式，使用 Chromium 原始设置，不注入自定义参数。 |
| `access_log` | `false` | 是否输出 Uvicorn HTTP 访问日志。 |
| `log_retention_days` | `7` | 日志与截图保留天数（1-365），过期日期目录整体删除。 |

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
│       ├── time_utils.py     # 时间工具
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
├── logs/                     # 日志与截图（按日期归档）
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

## API 接口

详见 [doc/api-doc.md](doc/api-doc.md)。

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

详见 [doc/update_log.md](doc/update_log.md)。

## 致谢

- [ddddocr](https://github.com/sml2h3/ddddocr) — 验证码识别引擎，本项目使用它处理图形验证码。

## 许可证

详见 [LICENSE](LICENSE)。
