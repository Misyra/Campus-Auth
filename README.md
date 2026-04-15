# Campus-Auth 校园网自动认证

基于 Playwright + FastAPI + Vue 的校园网自动认证工具，当前以 Web 控制台为主入口，支持自动监控、任务模板、开机自启动与系统托盘。

## 当前能力

- Web 控制台（初始化向导 + 仪表盘 + 设置 + 任务管理 + 关于页）
- 网络监控与自动重连（定时检测网络，掉线后自动执行认证）
- 手动操作（手动登录、网络测试）
- 任务系统（内置 default/sample/sample_2，可在 UI 新建/编辑/切换）
- 实时日志（WebSocket 推送日志）
- 开机自启动（Windows/macOS/Linux）
- 系统托盘（可配置最小化到托盘）
- Playwright 自检与 Chromium 自动安装（含下载源回退）
- 防重复启动（PID + 端口检测）

## 快速开始

### 方式 1：Windows 发布包（推荐终端用户）

1. 下载并解压发布包。
2. 双击运行可执行文件（或运行目录中的启动脚本）。
3. 打开浏览器访问 `http://127.0.0.1:50721`（端口可由 `APP_PORT` 配置）。

### 方式 2：源码运行（推荐本仓库开发/调试）

1. 安装依赖：

```bash
uv sync
```

2. 启动：

```bash
uv run app.py
```

或直接使用项目内环境：

```powershell
.\environment\python\python.exe app.py
```

### 方式 3：用启动器自动准备环境（Windows）

启动器会检查并初始化 `environment/python`、安装依赖、尝试安装 Playwright 浏览器后再拉起服务：

```powershell
python launcher.py
```

可选参数：

```powershell
python launcher.py --python-version 3.10 --pip-mirror https://mirrors.tuna.tsinghua.edu.cn/simple
python launcher.py --force-reinstall --verbose
```

## 启动参数

`app.py` 支持以下参数：

```bash
# 启动但不自动打开浏览器
python app.py --no-browser

# 启动到系统托盘
python app.py --tray

# 查看服务状态
python app.py --status

# 停止服务
python app.py --stop

# 开机自启动管理
python app.py --autostart
python app.py --autostart enable
python app.py --autostart disable
```

## 配置说明

首次可复制 `.env.example` 为 `.env` 后编辑，或通过 Web 控制台保存配置。

```bash
cp .env.example .env
```

核心配置项如下：

| 变量 | 默认值 | 说明 |
|---|---|---|
| `CAMPUS_USERNAME` | - | 校园网用户名（必填） |
| `CAMPUS_PASSWORD` | - | 校园网密码（必填） |
| `CAMPUS_AUTH_URL` | `http://172.29.0.2` | 认证页地址 |
| `CAMPUS_ISP` | `@cmcc` | 运营商后缀：`@cmcc/@unicom/@telecom/@xyw/空` |
| `APP_PORT` | `50721` | Web 控制台端口 |
| `AUTO_START_MONITORING` | `false` | 启动后自动开始监控 |
| `MONITOR_INTERVAL` | `300` | 网络检测间隔（秒） |
| `PING_TARGETS` | `8.8.8.8:53,114.114.114.114:53,www.baidu.com:443` | 网络探测目标 |
| `PAUSE_LOGIN_ENABLED` | `true` | 启用暂停登录时段 |
| `PAUSE_LOGIN_START_HOUR` | `0` | 暂停开始小时 |
| `PAUSE_LOGIN_END_HOUR` | `6` | 暂停结束小时 |
| `BROWSER_HEADLESS` | `false` | 无头浏览器模式 |
| `BROWSER_TIMEOUT` | `8000` | 浏览器超时（毫秒） |
| `UVICORN_ACCESS_LOG` | `false` | 是否显示 HTTP 请求日志 |
| `MINIMIZE_TO_TRAY` | `false` | 是否最小化到系统托盘 |
| `AUTO_INSTALL_PLAYWRIGHT` | `true` | 启动时自动确保 Chromium 可用 |
| `PLAYWRIGHT_DOWNLOAD_HOST` | `https://npmmirror.com/mirrors/playwright` | Playwright 下载源 |

## 任务系统

任务系统由 tasks 目录下的 JSON 文件驱动，支持在 Web 控制台中管理任务模板并切换活动任务。

默认模板：

- default.json
- sample.json
- sample_2.json

详细说明（字段定义、步骤类型、变量替换、示例与调试）见：

- [doc/task-system.md](doc/task-system.md)


## 常见问题

### 1) 报错 `No module named dotenv`

通常是解释器用错了：请确认运行时使用的是项目环境 Python，而不是系统全局 Python。

```powershell
.\environment\python\python.exe app.py
```

### 2) Playwright/Chromium 下载失败

项目会按下载源顺序尝试：

1. `PLAYWRIGHT_DOWNLOAD_HOST`（若设置）
2. `https://npmmirror.com/mirrors/playwright`
3. `https://playwright.azureedge.net`

可在 `.env` 中显式设置：

```env
PLAYWRIGHT_DOWNLOAD_HOST=https://npmmirror.com/mirrors/playwright
```

### 3) 服务提示已启动

项目有重复启动保护。可先查看状态或停止：

```bash
python app.py --status
python app.py --stop
```

### 4) 认证不成功

建议依次检查：

1. 账号/密码是否正确。
2. `CAMPUS_AUTH_URL` 是否可访问。
3. `CAMPUS_ISP` 是否匹配。
4. 在 Web 控制台查看实时日志。

## 目录结构（核心）

```text
.
├── app.py
├── launcher.py
├── backend/
├── frontend/
├── src/
├── tasks/
├── requirements.txt
├── pyproject.toml
└── .env.example
```

## 技术栈

- 后端：FastAPI, Uvicorn, Pydantic
- 前端：Vue 3, Axios
- 自动化：Playwright
- 网络检测：httpx, socket
- 打包：PyInstaller / Nuitka

## 许可证

详见 [LICENSE](LICENSE)。
