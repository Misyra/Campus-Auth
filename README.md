# Campus-Auth 校园网自动认证

基于 Playwright + FastAPI + Vue 的校园网自动认证工具，支持 Web 控制台、自动监控、任务模板、开机自启动与系统托盘。

## 功能特性

### 核心功能
- **Web 控制台** - 初始化向导 + 仪表盘 + 设置 + 任务管理 + 关于页
- **网络监控** - 定时检测网络状态，掉线后自动执行认证
- **自动登录** - 智能识别登录页面，自动填写表单并提交
- **任务系统** - 灵活的 JSON 驱动任务模板，支持自定义认证流程
- **实时日志** - WebSocket 推送日志，前端自动滚动显示
- **开机自启动** - 支持 Windows/macOS/Linux 平台
- **系统托盘** - 可配置最小化到托盘运行

### 高级特性
- **智能检测** - 自动检测已登录状态，避免重复认证
- **暂停时段** - 可配置夜间暂停登录，避免打扰
- **失败重试** - 指数退避重试机制，防止频繁请求
- **异常处理** - 精细化异常分类，便于问题定位
- **配置缓存** - 单例模式管理配置，避免重复读取
- **变量解析缓存** - 任务执行器缓存变量解析结果，提升性能
- **防重复启动** - PID + 端口双重检测

## 快速开始

### 方式 1：Windows 发布包（推荐终端用户）

1. 下载并解压发布包
2. 双击运行可执行文件（或运行目录中的启动脚本）
3. 打开浏览器访问 `http://127.0.0.1:50721`

### 方式 2：源码运行（推荐开发/调试）

**环境要求**
- Python >= 3.10
- uv 包管理器（推荐）或 pip

**安装依赖**
```bash
uv sync
```

**启动服务**
```bash
uv run app.py
```

或使用项目内环境：
```powershell
.\environment\python\python.exe app.py
```

### 方式 3：启动器自动准备环境（Windows）

```powershell
python launcher.py
```

可选参数：
```powershell
python launcher.py --python-version 3.10 --pip-mirror https://mirrors.tuna.tsinghua.edu.cn/simple
python launcher.py --force-reinstall --verbose
```

## 启动参数

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

# 开机自启动管理
python app.py --autostart          # 查看状态
python app.py --autostart enable   # 启用
python app.py --autostart disable  # 禁用
```

## 配置说明

### 初始配置

首次使用可复制 `.env.example` 为 `.env` 后编辑：

```bash
cp .env.example .env
```

或通过 Web 控制台的初始化向导完成配置。

### 核心配置项

| 变量 | 默认值 | 说明 |
|------|--------|------|
| **认证配置** |||
| `USERNAME` | - | 校园网用户名（必填） |
| `PASSWORD` | - | 校园网密码（必填，支持加密存储） |
| `LOGIN_URL` | `http://172.29.0.2` | 认证页面地址 |
| `ISP` | `` | 运营商关键字：`移动/联通/电信/自定义关键字/空` |
| **服务配置** |||
| `APP_PORT` | `50721` | Web 控制台端口 |
| `UVICORN_ACCESS_LOG` | `false` | 是否显示 HTTP 请求日志 |
| `API_TOKEN` | - | API 写操作鉴权令牌（可选） |
| **监控配置** |||
| `AUTO_START_MONITORING` | `false` | 启动后自动开始监控 |
| `MONITOR_INTERVAL` | `300` | 网络检测间隔（秒） |
| `PING_TARGETS` | `8.8.8.8:53,114.114.114.114:53,www.baidu.com:443` | 网络探测目标 |
| `MAX_CONSECUTIVE_FAILURES` | `3` | 连续登录失败次数上限 |
| **暂停时段** |||
| `PAUSE_LOGIN_ENABLED` | `true` | 启用暂停登录时段 |
| `PAUSE_LOGIN_START_HOUR` | `0` | 暂停开始小时（0-23） |
| `PAUSE_LOGIN_END_HOUR` | `6` | 暂停结束小时（0-23） |
| **浏览器配置** |||
| `BROWSER_HEADLESS` | `true` | 无头浏览器模式 |
| `BROWSER_TIMEOUT` | `8000` | 浏览器操作超时（毫秒） |
| `BROWSER_LOW_RESOURCE_MODE` | `true` | 低资源模式 |
| **系统配置** |||
| `MINIMIZE_TO_TRAY` | `true` | 最小化到系统托盘 |
| **自定义变量** |||
| `CUSTOM_VARIABLES` | `{}` | 自定义变量（JSON格式），可在任务模板中使用 |
| `AUTO_INSTALL_PLAYWRIGHT` | `true` | 自动安装 Chromium |
| `PLAYWRIGHT_DOWNLOAD_HOST` | `https://npmmirror.com/mirrors/playwright` | 下载源镜像 |

## 任务系统

任务系统基于 JSON 配置文件，支持自定义认证流程。

### 默认模板

- `default.json` - 默认认证任务
- `sample.json` - 示例任务
- `sample_2.json` - 高级示例

### 任务文件位置

```
tasks/
├── default.json
├── sample.json
├── sample_2.json
└── active.txt          # 当前活动任务标识
```

### 配置示例

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

| 类型 | 说明 | 参数 |
|------|------|------|
| `navigate` | 页面导航 | `url`, `wait_until`, `timeout` |
| `input` | 输入文本 | `selector`, `value`, `clear`, `timeout` |
| `click` | 点击元素 | `selector`, `timeout` |
| `select` | 选择下拉框 | `selector`, `value`, `timeout` |
| `wait` | 等待元素 | `selector`, `timeout` |
| `wait_url` | 等待 URL 匹配 | `pattern`, `timeout` |
| `eval` | 执行 JavaScript | `script`, `store_as` |
| `custom_js` | 执行自定义 JS | `script` |
| `screenshot` | 截图 | `path` |

详细说明见 [doc/task-system.md](doc/task-system.md)

## 项目架构

```
Campus-Auth/
├── app.py                      # 主入口
├── launcher.py                 # Windows 启动器
├── pyproject.toml              # 项目配置
├── requirements.txt            # 依赖列表
│
├── backend/                    # 后端服务
│   ├── main.py                 # FastAPI 主应用
│   ├── monitor_service.py      # 监控服务
│   ├── config_service.py       # 配置服务
│   ├── autostart_service.py    # 自启动服务
│   ├── task_service.py         # 任务服务
│   └── schemas.py              # Pydantic 模型
│
├── frontend/                   # 前端界面
│   ├── index.html              # 主页面
│   ├── app.js                  # 入口
│   ├── js/                     # JS 模块
│   │   ├── app-options.js      # Vue 配置
│   │   ├── logger.js           # 日志工具
│   │   └── methods/            # 方法模块
│   ├── partials/               # HTML 片段
│   └── styles/                 # CSS 样式
│
├── src/                        # 核心模块
│   ├── campus_login.py         # 认证逻辑
│   ├── monitor_core.py         # 监控核心
│   ├── task_executor.py        # 任务执行器
│   ├── network_test.py         # 网络检测
│   ├── playwright_bootstrap.py # Playwright 初始化
│   ├── system_tray.py          # 系统托盘
│   └── utils/                  # 工具模块
│       ├── config.py           # 配置管理（含单例）
│       ├── logging.py          # 日志配置
│       ├── browser.py          # 浏览器管理
│       ├── crypto.py           # 加密工具
│       └── ...
│
├── tasks/                      # 任务模板
├── tests/                      # 测试文件
├── doc/                        # 文档
└── logs/                       # 日志目录
```

## 技术栈

### 后端
- **FastAPI** - 现代 Web 框架
- **Uvicorn** - ASGI 服务器
- **Pydantic** - 数据验证
- **Playwright** - 浏览器自动化
- **WebSocket** - 实时通信

### 前端
- **Vue 3** - 渐进式框架
- **Axios** - HTTP 客户端
- **原生 WebSocket** - 实时日志

### 工具
- **httpx** / **socket** - 网络检测
- **pystray** - 系统托盘
- **cryptography** - 密码加密

## 开发指南

### 运行测试

```bash
# 运行所有测试
uv run pytest

# 运行特定测试
uv run pytest tests/test_task_executor.py -v
```

### 代码规范

项目使用 Ruff 进行代码检查和格式化：

```bash
# 检查代码
uv run ruff check .

# 格式化代码
uv run ruff format .
```

### 关键类说明

#### ConfigManager（配置管理单例）

```python
from src.utils import ConfigManager

# 获取配置（自动缓存）
config = ConfigManager.get_config()

# 强制重新加载
config = ConfigManager.reload_config()
```

#### LogConfigCenter（日志配置中心）

```python
from src.utils.logging import LogConfigCenter

# 初始化日志
center = LogConfigCenter.get_instance()
center.initialize(config, side="BACKEND")

# 获取日志器
logger = center.get_logger("my_module")
```

#### TaskExecutor（任务执行器）

```python
from src.task_executor import TaskExecutor, TaskConfig

config = TaskConfig(task_dict)
executor = TaskExecutor(config, env_vars)
success, message = await executor.execute(page)
```

## API 概览

### 健康检查
```
GET /api/health
```

### 配置管理
```
GET    /api/config          # 获取配置
PUT    /api/config          # 保存配置
GET    /api/init-status     # 初始化状态
```

### 监控控制
```
GET    /api/status          # 监控状态
POST   /api/monitor/start   # 启动监控
POST   /api/monitor/stop    # 停止监控
```

### 操作
```
POST   /api/actions/login       # 手动登录
POST   /api/actions/test-network # 网络测试
```

### 日志
```
GET    /api/logs?limit=200  # 获取历史日志
WS     /ws/logs             # WebSocket 实时日志
```

### 任务管理
```
GET    /api/tasks                  # 列出任务
GET    /api/tasks/{id}             # 获取任务
PUT    /api/tasks/{id}             # 保存任务
DELETE /api/tasks/{id}             # 删除任务
GET    /api/tasks/active           # 获取活动任务
POST   /api/tasks/active/{id}      # 设置活动任务
```

### 自启动
```
GET    /api/autostart/status   # 自启动状态
POST   /api/autostart/enable   # 启用自启动
POST   /api/autostart/disable  # 禁用自启动
```

### 服务控制
```
POST   /api/shutdown         # 关闭服务
```

## 常见问题

### 1. 报错 `No module named dotenv`

通常是解释器用错了。请确认使用的是项目环境 Python：

```powershell
.\environment\python\python.exe app.py
```

### 2. Playwright/Chromium 下载失败

项目会按以下顺序尝试下载源：

1. `PLAYWRIGHT_DOWNLOAD_HOST`（若设置）
2. `https://npmmirror.com/mirrors/playwright`
3. `https://playwright.azureedge.net`

可在 `.env` 中设置镜像：

```env
PLAYWRIGHT_DOWNLOAD_HOST=https://npmmirror.com/mirrors/playwright
```

### 3. 服务提示已启动

项目有重复启动保护。可先查看状态或停止：

```bash
python app.py --status
python app.py --stop
```

### 4. 认证不成功

建议依次检查：

1. 账号/密码是否正确
2. `LOGIN_URL` 是否可访问
3. `ISP` 是否匹配
4. 在 Web 控制台查看实时日志
5. 尝试使用 `headless=false` 查看浏览器操作

### 5. 日志不显示或延迟

- 检查 WebSocket 连接状态（浏览器开发者工具）
- 确认后端服务正常运行
- 刷新页面重新连接

## 更新日志

### v3.1.0
- 优化 WebSocket 实时日志推送
- 添加日志自动滚动功能
- 精细化异常处理
- 添加配置管理单例模式
- 任务执行器变量解析缓存

### v3.0.1
- 初始稳定版本
- Web 控制台
- 任务系统
- 系统托盘支持

## 许可证

详见 [LICENSE](LICENSE)。
