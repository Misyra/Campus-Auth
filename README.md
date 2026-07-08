# Campus-Auth 校园网自动认证

Campus-Auth 是一个基于 Playwright、FastAPI 和 Vue 3 的校园网自动认证工具。它既可以作为终端用户直接运行的本地服务，也适合作为开发调试项目使用。项目提供 Web 控制台、自动监控、任务模板、多网络配置方案、系统托盘、自启动与日志可视化，目标是让校园网认证尽量做到"装好即用、断网即连、问题可查"。

新视频
【小刻也能学会的通用校园网自动认证教程】 https://www.bilibili.com/video/BV1d35E6mEVB/?share_source=copy_web&vd_source=db13da6ef2846b31b874687783211f99

## 主要特性

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

## 快速开始

### 运行前准备

- Python 3.12 或更高版本。
- 推荐使用 uv 管理依赖。

### 安装与启动

安装依赖：

```bash
uv sync
```

启动服务：

```bash
python main.py
```

启动后可在浏览器访问 Web 控制台：http://127.0.0.1:50721

### 端口与访问地址

默认 Web 控制台端口为 50721，启动后可在浏览器访问：

http://127.0.0.1:50721

如果你修改了 `APP_PORT`，则以实际端口为准。

### 辅助工具

项目根目录提供两个 Go 编译的辅助工具，无需安装 Go 运行时即可使用：

**start.exe — 一键启动**

自动下载 uv、安装依赖并启动应用。适合首次部署或不想手动管理环境的用户。

```bash
# 启动应用（自动安装依赖）
start.exe

# 仅安装依赖，不启动应用
start.exe --install-only
```

**update.exe — 仓库克隆/更新**

自动检测/安装 Git，从镜像源克隆或更新仓库。适合需要快速获取最新代码或部署多台机器的场景。

```bash
# 在项目根目录运行（已克隆则更新，未克隆则初始化）
update.exe
```

### 首次使用流程

建议第一次使用按下面顺序完成：

1. 启动服务并打开 Web 控制台。
2. 进入初始化向导，填写校园网账号、密码和认证页面地址。
3. 确认运营商字段、监控开关和浏览器模式。
4. 保存配置后执行一次手动登录，确认流程正常。
5. 再开启自动监控，让系统在断网时自动重连。

如果校园网页面结构比较特殊，建议先用非无头模式排查，再切换回无头运行。

如果你有多个网络环境（如宿舍 WiFi 和教学楼 WiFi），可以在"配置方案"页面为每个网络创建独立配置，系统会根据当前网络自动切换。

## 配置说明

项目配置存储在 `config/` 目录：

- `config/settings.json`：主配置文件，存储凭证、认证地址、监控设置等。
- `config/profiles/`：配置方案目录，存储多网络配置方案数据。

首次使用时系统会通过初始化向导引导你填写配置，所有配置统一存储在 `config/settings.json` 中。

项目的所有配置现已统一通过 Web 控制台管理。首次使用时，Web 控制台的初始化向导会引导你完成配置。如需高级配置（端口、代理等），可直接编辑 `config/settings.json` 或通过 Web 控制台"设置"页面操作。

更多配置说明请参考 [用户指南](docs/guides/user-guide.md#配置说明)。

## 项目结构

```text
Campus-Auth/
├── main.py                   # 统一启动入口
├── start.exe / git-puller.exe # Go 辅助工具
├── start.sh                  # macOS/Linux 启动脚本
├── pyproject.toml            # 项目元数据与依赖
├── config/                   # 运行时配置
├── app/                      # Python 后端
├── frontend/                 # 前端控制台（Vue 3 SPA）
├── tasks/                    # 任务定义
├── tests/                    # pytest 测试
├── docs/                     # 文档
├── resources/                # 资源文件
├── debug/                    # 日志与截图
└── release/                  # 发布产物
```

## 技术栈

| 层级 | 技术 |
|------|------|
| 运行时 | Python 3.12 |
| Web 框架 | FastAPI + Uvicorn |
| 浏览器自动化 | Playwright（Chromium） |
| 数据校验 | Pydantic v2 |
| 前端 | Vue 3 SPA（无构建步骤） |
| 包管理 | uv |
| 代码检查 | Ruff |
| 测试 | pytest |
| 日志 | loguru |

## 开发与调试

```bash
# 安装依赖
uv sync

# 启动服务
python main.py

# 运行测试
uv run pytest

# 代码检查
uv run ruff check .
uv run ruff format .
```

更多开发信息请参考 [开发者文档](docs/dev/)。

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

更多常见问题请参考 [用户指南](docs/guides/user-guide.md#常见问题)。

## 文档导航

- [用户指南](docs/guides/user-guide.md) — 详细使用说明、配置、任务系统、常见问题
- [开发者文档](docs/dev/) — 架构、API、贡献指南
- [更新日志](docs/changelog.md) — 版本变更记录

## 更新日志

详见 [docs/changelog.md](docs/changelog.md)。

## 致谢

- [ddddocr](https://github.com/sml2h3/ddddocr) — 验证码识别引擎，本项目使用它处理图形验证码。

## 许可证

详见 [LICENSE](LICENSE)。