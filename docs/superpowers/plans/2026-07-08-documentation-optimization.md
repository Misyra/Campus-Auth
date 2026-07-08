# 文档优化实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 优化项目文档结构，简化README，将具体使用内容分离到独立文档，提高文档的可读性和维护性。

**Architecture:** 将README中的详细内容分离到用户指南，保留README作为项目入口，优化启动文档作为快速入门指南，简化文档索引结构。

**Tech Stack:** Markdown, Git

## Global Constraints

1. README.md行数控制在200-250行
2. 所有原有内容必须完整迁移，不能丢失
3. 文档链接必须正确有效
4. 保持现有文档结构，只做必要调整
5. 中文文档使用中文标点符号

---

## 文件映射

### 创建文件
- `docs/guides/user-guide.md` — 用户指南，包含从README移入的详细内容

### 修改文件
- `README.md` — 简化README，移除详细内容，添加文档导航
- `启动请看我.md` — 优化结构，添加文档导航
- `docs/guides/README.md` — 添加用户指南链接

### 删除文件
- `docs/Index.md` — 删除索引文件，README直接链接到主要文档

---

### Task 1: 创建用户指南文档

**Files:**
- Create: `docs/guides/user-guide.md`

**Interfaces:**
- Consumes: README.md中的详细内容
- Produces: 用户指南文档，供README链接

- [ ] **Step 1: 创建用户指南文件**

创建文件 `docs/guides/user-guide.md`，包含以下结构：

```markdown
# 用户指南

Campus-Auth 用户文档，帮助你快速上手并充分利用所有功能。

## 启动与配置

### 启动参数

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

### 配置说明

#### 配置来源

项目配置存储在 `config/` 目录：

- `config/settings.json`：主配置文件，存储凭证、认证地址、监控设置等。
- `config/profiles/`：配置方案目录，存储多网络配置方案数据。

首次使用时系统会通过初始化向导引导你填写配置，所有配置统一存储在 `config/settings.json` 中。

#### 高级配置

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

## 功能说明

### 任务系统

任务系统使用 JSON 文件描述自动化认证流程，支持多种步骤类型、变量模板、网络检测兜底成功判断和帧上下文。任务文件存放在 `tasks/` 目录，通过 Web 控制台管理（新建、编辑、导入导出、复制、设置活动任务）。

#### 任务类型

1. **浏览器任务** (`tasks/browser/`)：使用 Playwright 执行浏览器自动化操作。
2. **脚本任务** (`tasks/scripts/`)：执行 Python、PowerShell 或 cmd 脚本。
3. **定时任务** (`tasks/scheduled/`)：在指定时间或间隔执行的任务。

- [任务开发参考](../dev/architecture.md) — 架构、步骤类型、变量解析、API 接口
- [任务编写指南](task-writing-guide.md) — 完整示例、最佳实践、常见问题

### 多网络配置方案

配置方案（Profiles）系统允许你为不同的网络环境（如宿舍 WiFi、教学楼 WiFi、有线网络）配置不同的认证参数，系统可以根据当前网络自动切换。

#### 工作原理

1. 每个方案可以设置匹配条件：网关 IP 或 WiFi SSID。
2. 系统检测当前网络的网关 IP 和 WiFi SSID（支持 Windows、macOS、Linux）。
3. 优先按网关 IP 匹配，其次按 SSID 匹配。
4. 匹配成功后自动切换到对应方案的配置。

#### 独立设置

每个方案可以独立配置：

- 凭证（用户名/密码，加密存储）
- 认证地址、运营商
- 检测间隔、暂停时段
- 浏览器参数（无头模式、超时、User-Agent 等）

也可以选择使用全局凭证或全局高级设置。

#### Web 控制台操作

在"配置方案"页面可以：

- 查看所有方案列表及当前活动方案
- 新建、编辑、删除方案（`default` 不可删除）
- 检测当前网络环境（网关 IP、WiFi SSID、匹配的方案）
- 开启/关闭自动切换

#### 自动切换

开启自动切换后，监控核心每 60 秒检测一次网络环境变化。当检测到当前网络匹配到不同的方案时，会自动切换配置并重新加载监控。

### 系统托盘与自启动

#### 系统托盘

系统托盘功能允许程序在后台运行，提供以下操作：

- 打开 Web 控制台
- 查看运行状态
- 退出程序

轻量模式下支持按需唤醒 Web 控制台。

#### 开机自启动

支持在 Windows、macOS 和 Linux 上配置自启动：

```bash
# 启用自启动
python main.py --autostart enable

# 禁用自启动
python main.py --autostart disable

# 查看自启动状态
python main.py --autostart
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

## 高级用法

### 辅助工具

项目根目录提供两个 Go 编译的辅助工具，无需安装 Go 运行时即可使用：

#### start.exe — 一键启动

自动下载 uv、安装依赖并启动应用。适合首次部署或不想手动管理环境的用户。

```bash
# 启动应用（自动安装依赖）
start.exe

# 仅安装依赖，不启动应用
start.exe --install-only

# 透传参数给 main.py
start.exe --no-browser --runtime-mode lightweight

# 静默模式（CI 环境，不等待按键）
start.exe --no-pause
```

工作流程：检测 PATH 中的 uv → 检查本地 `.uv/` 目录 → 从镜像源下载 uv → `uv sync` 安装依赖 → `uv run main.py` 启动应用。

#### update.exe — 仓库克隆/更新

自动检测/安装 Git，从镜像源克隆或更新仓库。适合需要快速获取最新代码或部署多台机器的场景。

```bash
# 在项目根目录运行（已克隆则更新，未克隆则初始化）
update.exe
```

功能特性：
- 自动检测 PATH 中的 Git，未找到时下载便携版（仅 Windows）
- 支持 4 个镜像源自动轮询（GitClone、CNPMJS、GHProxy、GitHub 官方）
- 已有仓库：fetch + reset --hard 到远程最新，支持切换分支
- 新目录：git init + remote add + fetch + reset，交互式选择分支

### 项目结构

```text
Campus-Auth/
├── main.py                   # 统一启动入口（CLI + 启动编排）
├── start.exe / git-puller.exe # Go 工具（编译产物，.gitignore）
├── start.sh                  # macOS/Linux 启动脚本
├── pyproject.toml            # 项目元数据与依赖
├── config/                   # 运行时配置
│   ├── settings.json         # 主配置文件
│   └── profiles/             # 配置方案文件
├── app/                      # Python 后端
├── frontend/                 # 前端控制台（Vue 3 SPA，无构建步骤）
├── tasks/                    # 任务定义
├── tests/                    # pytest 测试
├── docs/                     # 文档
├── dev/                      # 开发笔记
├── resources/                # 资源文件
├── debug/                    # 日志与截图（按日期归档）
└── release/                  # 发布产物
```

### 技术栈

#### 后端

- FastAPI：HTTP API 和 WebSocket。
- Uvicorn：ASGI 服务运行器。
- Pydantic：配置与请求数据校验。
- Playwright：浏览器自动化执行。
- socket + httpx：网络检测（TCP 探测 + HTTP 探测）。
- psutil：网络检测（网关 IP 和 WiFi SSID 检测）。
- cryptography：密码加密。
- loguru：日志系统。
- ddddocr：验证码 OCR 识别（任务步骤中使用）。

#### 前端

- Vue 3：控制台界面（单文件，无构建工具）。
- Axios：后端 API 通信。
- 原生 WebSocket：实时日志流。

#### 工具与辅助

- pystray / Pillow / cairosvg：系统托盘。
- pytest：测试框架。

## 相关文档

- [任务编写指南](task-writing-guide.md) — 如何编写浏览器自动登录任务
- [自定义脚本指南](custom-script-guide.md) — 使用 Python/PowerShell/cmd 脚本直接登录
- [系统架构](../dev/architecture.md) — 内部架构概览
- [API 接口参考](../dev/api-reference.md) — 全部 HTTP/WebSocket 端点文档
- [更新日志](../changelog.md) — 版本变更记录
```

- [ ] **Step 2: 验证用户指南内容**

检查用户指南是否包含以下内容：
1. 启动参数说明
2. 配置说明（配置来源和高级配置）
3. 任务系统说明
4. 多网络配置方案说明
5. 系统托盘与自启动说明
6. 常见问题
7. 高级用法（辅助工具、项目结构、技术栈）

- [ ] **Step 3: 提交用户指南**

```bash
git add docs/guides/user-guide.md
git commit -m "docs: 添加用户指南文档"
```

---

### Task 2: 简化README文档

**Files:**
- Modify: `README.md`

**Interfaces:**
- Consumes: 原README.md内容
- Produces: 简化后的README.md，链接到用户指南

- [ ] **Step 1: 备份原README**

```bash
cp README.md README.md.backup
```

- [ ] **Step 2: 创建简化后的README**

将README.md替换为以下内容：

```markdown
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

## 文档导航

- [用户指南](docs/guides/user-guide.md) — 详细使用说明、配置、任务系统、常见问题
- [开发者文档](docs/dev/) — 架构、API、贡献指南
- [更新日志](docs/changelog.md) — 版本变更记录

## 许可证

详见 [LICENSE](LICENSE)。
```

- [ ] **Step 3: 验证README行数**

```bash
wc -l README.md
```

预期输出：行数在200-250行之间

- [ ] **Step 4: 验证README内容**

检查README是否包含：
1. 项目简介
2. 主要特性
3. 快速开始
4. 配置说明（简化版）
5. 文档导航
6. 许可证

- [ ] **Step 5: 提交简化后的README**

```bash
git add README.md
git commit -m "docs: 简化README文档，移除详细内容"
```

---

### Task 3: 优化启动文档

**Files:**
- Modify: `启动请看我.md`

**Interfaces:**
- Consumes: 原启动请看我.md内容
- Produces: 优化后的启动请看我.md，添加文档导航

- [ ] **Step 1: 读取原启动文档**

读取 `启动请看我.md` 文件，了解当前内容。

- [ ] **Step 2: 优化启动文档结构**

在文档末尾添加文档导航部分：

```markdown
## 相关文档

- [用户指南](docs/guides/user-guide.md) — 详细使用说明、配置、任务系统、常见问题
- [开发者文档](docs/dev/) — 架构、API、贡献指南
- [更新日志](docs/changelog.md) — 版本变更记录
```

- [ ] **Step 3: 验证启动文档**

检查启动文档是否：
1. 保留了所有原有内容
2. 添加了文档导航部分
3. 链接正确有效

- [ ] **Step 4: 提交优化后的启动文档**

```bash
git add 启动请看我.md
git commit -m "docs: 优化启动文档，添加文档导航"
```

---

### Task 4: 清理文档索引

**Files:**
- Delete: `docs/Index.md`
- Modify: `docs/guides/README.md`

**Interfaces:**
- Consumes: docs/Index.md, docs/guides/README.md
- Produces: 更新后的docs/guides/README.md

- [ ] **Step 1: 删除docs/Index.md**

```bash
rm docs/Index.md
```

- [ ] **Step 2: 更新docs/guides/README.md**

读取当前 `docs/guides/README.md` 文件，添加用户指南链接：

```markdown
# 用户指南

Campus-Auth 用户文档，帮助你快速上手并充分利用所有功能。

## 入门

- [快速开始](../../启动请看我.md) — 安装、首次配置、日常使用、命令行参数、常见问题
- [README](../../README.md) — 项目概述、特性介绍、快速开始

## 功能指南

- [用户指南](user-guide.md) — 详细使用说明、配置、任务系统、常见问题
- [任务编写指南](task-writing-guide.md) — 如何编写浏览器自动登录任务（JSON 格式详解、步骤类型、变量系统、完整示例）
- [自定义脚本指南](custom-script-guide.md) — 使用 Python/PowerShell/cmd 脚本直接登录，无需浏览器

## 相关链接

- [更新日志](../changelog.md) — 版本变更记录
- [贡献指南](../dev/contributing.md) — 想参与开发？从这里开始
```

- [ ] **Step 3: 验证文档链接**

检查所有文档链接是否正确：
1. README中的链接
2. 启动文档中的链接
3. 用户指南中的链接
4. docs/guides/README.md中的链接

- [ ] **Step 4: 提交清理结果**

```bash
git add docs/Index.md docs/guides/README.md
git commit -m "docs: 清理文档索引，更新用户指南导航"
```

---

### Task 5: 最终验证与清理

**Files:**
- None

**Interfaces:**
- Consumes: 所有修改的文档
- Produces: 验证报告

- [ ] **Step 1: 验证README行数**

```bash
wc -l README.md
```

预期：行数在200-250行之间

- [ ] **Step 2: 验证文档完整性**

检查所有原有内容是否完整迁移：
1. 启动参数说明 → 用户指南
2. 配置说明 → 用户指南
3. 任务系统说明 → 用户指南
4. 多网络配置方案 → 用户指南
5. 常见问题 → 用户指南
6. 辅助工具 → 用户指南
7. 项目结构 → 用户指南
8. 技术栈 → 用户指南

- [ ] **Step 3: 验证文档链接**

检查所有文档链接是否正确有效：
1. README → 用户指南
2. README → 开发者文档
3. README → 更新日志
4. 启动文档 → 用户指南
5. 启动文档 → 开发者文档
6. 启动文档 → 更新日志
7. 用户指南内部链接

- [ ] **Step 4: 清理备份文件**

```bash
rm README.md.backup
```

- [ ] **Step 5: 提交最终验证**

```bash
git add -A
git commit -m "docs: 完成文档优化，验证所有链接"
```

---

## 验证标准

1. README.md行数在200-250行之间
2. 所有原有内容都能在对应文档中找到
3. 所有文档链接正确有效
4. 文档结构清晰，易于导航
5. 用户指南和开发者文档分离清晰

## 风险与缓解

### 风险1：文档链接失效

**缓解**：实施后检查所有文档链接，确保正确指向

### 风险2：内容遗漏

**缓解**：对比原README和新文档，确保所有内容都被迁移

### 风险3：用户找不到信息

**缓解**：在README中提供清晰的文档导航，在启动文档中添加链接