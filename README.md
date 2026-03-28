# Campus-Auth 校园网自动认证

基于 `Playwright + FastAPI + Vue` 的通用校园网自动认证工具，支持 Web 控制台和 CLI 模式，适配多种校园网认证系统。

## 特性

- 🚀 **前后端分离** - FastAPI + Vue 3，响应式布局
- 🔄 **自动监控** - 定时检测网络状态，自动重连
- 📊 **实时日志** - Web 控制台实时查看运行状态
- ⚙️ **配置热更新** - 保存配置后自动重启监控
- 🖥️ **跨平台** - 支持 Windows、macOS、Linux
- 📦 **开箱即用** - 单文件可执行，无需安装 Python

---

## 快速开始

### 终端用户

**Windows**

1. 下载 `Campus-Auth.exe`
2. 双击运行（首次启动会自动下载环境，约 2-5 分钟）
3. 浏览器自动打开 http://127.0.0.1:50721

**macOS / Linux**

```bash
# 赋予执行权限
chmod +x Campus-Auth

# 运行
./Campus-Auth
```

> 💡 首次运行会自动创建 `environment/` 目录并下载 Python 环境和依赖。

---

### 开发者

**前置要求**
- Python 3.10+
- [uv](https://github.com/astral-sh/uv) 包管理器

**安装和运行**

```bash
# 安装依赖
uv sync

# 安装 Playwright 浏览器
uv run playwright install chromium

# 启动程序
uv run app.py        # Web 控制台
uv run app_cli.py    # CLI 模式
```

---

## 使用方法

### Web 控制台模式

启动后自动打开浏览器访问 http://127.0.0.1:50721

### CLI 模式

```bash
# 终端用户
.\environment\python\python.exe app_cli.py

# 开发者
uv run app_cli.py
```

### 命令行参数

```bash
# 启动但不打开浏览器
Campus-Auth --no-browser

# 查看服务状态
Campus-Auth --status

# 停止服务
Campus-Auth --stop

# 开机自启动管理
Campus-Auth --autostart          # 查看状态
Campus-Auth --autostart enable   # 启用
Campus-Auth --autostart disable  # 关闭
```

---

## 配置说明

### 环境变量

首次运行自动生成 `.env` 文件，或复制 `.env.example` 手动配置：

```env
# 必填项
CAMPUS_USERNAME=你的学号
CAMPUS_PASSWORD=你的密码
CAMPUS_AUTH_URL=http://172.29.0.2

# 可选项
CAMPUS_ISP=@cmcc        # 运营商后缀
APP_PORT=50721          # Web 端口
BROWSER_HEADLESS=false  # 无头模式
```

### 配置项列表

**必填配置**

| 环境变量 | 说明 | 示例 |
|----------|------|------|
| `CAMPUS_USERNAME` | 用户名/学号 | `2024001` |
| `CAMPUS_PASSWORD` | 密码 | `******` |
| `CAMPUS_AUTH_URL` | 认证地址 | `http://172.29.0.2` |

**可选配置**

| 环境变量 | 说明 | 默认值 |
|----------|------|--------|
| `CAMPUS_ISP` | 运营商后缀 | `@cmcc` |
| `APP_PORT` | Web 端口 | `50721` |
| `BROWSER_HEADLESS` | 无头模式 | `false` |
| `BROWSER_TIMEOUT` | 超时时间(ms) | `8000` |
| `MONITOR_INTERVAL` | 检测间隔(秒) | `240` |
| `PAUSE_LOGIN_ENABLED` | 启用暂停时段 | `true` |
| `PAUSE_LOGIN_START_HOUR` | 暂停开始时间 | `0` |
| `PAUSE_LOGIN_END_HOUR` | 暂停结束时间 | `6` |
| `LOG_LEVEL` | 日志级别 | `INFO` |
| `LOG_FILE` | 日志文件路径 | `logs/campus_auth.log` |
| `UVICORN_ACCESS_LOG` | 显示HTTP请求日志 | `false` |

### 运营商后缀

| 运营商 | 后缀 |
|--------|------|
| 中国移动 | `@cmcc` |
| 中国联通 | `@unicom` |
| 中国电信 | `@telecom` |
| 教育网 | `@xyw` |
| 无 | 留空 |

---

## 目录结构

```
.
├── Campus-Auth.exe          # Windows 可执行文件
├── Campus-Auth              # macOS/Linux 可执行文件
├── app.py                   # 统一入口（Web + CLI）
├── backend/
│   ├── main.py              # FastAPI 应用
│   ├── monitor_service.py   # 监控服务
│   ├── config_service.py    # 配置服务
│   ├── schemas.py           # 数据模型
│   └── autostart_service.py # 自启动服务
├── frontend/
│   ├── index.html           # 界面
│   ├── style.css            # 样式
│   └── app.js               # 逻辑
├── src/
│   ├── monitor_core.py      # 监控核心
│   ├── campus_login.py      # 认证模块
│   ├── network_test.py      # 网络检测
│   ├── playwright_bootstrap.py # Playwright 初始化
│   └── utils/               # 工具类
│       ├── __init__.py      # 统一导出
│       ├── logging.py       # 日志管理
│       ├── exceptions.py    # 异常处理
│       ├── retry.py         # 重试机制
│       ├── time.py          # 时间工具
│       ├── config.py        # 配置管理
│       ├── browser.py       # 浏览器管理
│       └── login.py         # 登录处理
├── environment/             # 自动创建的 Python 环境
├── logs/                    # 日志目录
├── .env.example             # 配置模板
├── requirements.txt         # 依赖列表
└── README.md                # 本文件
```

---

## 架构说明

```
┌─────────────────────────────────────────────────────────┐
│                    Web 浏览器                            │
│              (Vue 3 + Axios 前端)                        │
└─────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│                  FastAPI 后端                            │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────┐ │
│  │ Config API  │  │ Monitor API │  │ Autostart API   │ │
│  └─────────────┘  └─────────────┘  └─────────────────┘ │
└─────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│                  核心业务层                              │
│  ┌─────────────────────────────────────────────────────┐│
│  │              NetworkMonitorCore                     ││
│  │  (定时检测 → 网络异常 → 自动登录 → 状态上报)         ││
│  └─────────────────────────────────────────────────────┘│
│                           │                             │
│           ┌───────────────┴───────────────┐            │
│           ▼                               ▼            │
│  ┌─────────────────┐            ┌─────────────────┐   │
│  │  NetworkTest    │            │  CampusLogin    │   │
│  │  (httpx/socket) │            │  (Playwright)   │   │
│  └─────────────────┘            └─────────────────┘   │
└─────────────────────────────────────────────────────────┘
```

---

## 故障排查

### 首次运行卡住

首次运行需要下载 Python 环境（约 100MB），请确保网络通畅。如长时间无响应：

1. 检查网络连接
2. 删除 `environment/` 目录后重新运行
3. 查看日志 `logs/setup_launcher.log`

### 依赖安装失败

```bash
# 删除 environment 目录后重新运行
rm -rf environment
./Campus-Auth
```

### Playwright 浏览器下载失败

```bash
# 设置国内镜像后重新运行
export PLAYWRIGHT_DOWNLOAD_HOST="https://npmmirror.com/mirrors/playwright"
./Campus-Auth
```

### 认证失败

1. 检查 `.env` 中用户名密码是否正确
2. 检查认证地址是否可达
3. 检查运营商后缀是否正确
4. 查看日志文件 `logs/campus_auth.log`

### 端口被占用

```env
# 修改 .env 文件中的端口
APP_PORT=50722
```

### Windows SmartScreen 警告

首次运行可能显示"Windows 已保护你的电脑"，点击"更多信息" → "仍要运行"即可。

---

## 常用镜像源

| 镜像源 | 地址 |
|--------|------|
| 清华大学 | `https://pypi.tuna.tsinghua.edu.cn/simple` |
| 阿里云 | `https://mirrors.aliyun.com/pypi/simple` |
| 中科大 | `https://pypi.mirrors.ustc.edu.cn/simple` |

---

## 卸载

直接删除项目目录即可，不会污染系统 Python 环境。

如需清除开机自启动：

```bash
# 关闭自启动
Campus-Auth --autostart disable

# 然后删除项目目录
```

---

## 技术栈

- **后端**: FastAPI, Uvicorn, Pydantic
- **前端**: Vue 3, Axios
- **自动化**: Playwright
- **网络检测**: httpx, socket
- **打包**: PyInstaller / Nuitka

---

## 许可证

详见 [LICENSE](LICENSE) 文件。
