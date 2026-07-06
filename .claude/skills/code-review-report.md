---
name: code-review-report
description: >-
  Use when the user requests a full project code review, audit, or health check
  ("全项目review"、"代码审查"、"code review"、"审查报告"、"review report"、"项目体检").
  Produces a structured findings report only, no code changes.
# 禁止框架自动触发，仅在用户显式调用时执行（如"全项目review"、"代码审查"）
disable-model-invocation: true
---

# Code Review Report Pipeline

全项目代码审查 → 并行 Review → 汇总发现 → 生成报告（只审不修）。

## 项目背景

Campus-Auth 是一个校园网自动认证工具，采用 Python 后端 + Vue 3 前端的前后端分离架构：

### 核心模块

| 模块 | 语言 | 路径 | 说明 |
|------|------|------|------|
| API 路由层 | Python | `app/api/` | FastAPI 路由，含 monitor、config、tasks、profiles、debug、scheduled_tasks、ws 等 18 个端点模块 |
| 服务层 | Python | `app/services/` | 业务逻辑核心，含 Actor 引擎(engine.py)、登录管线(orchestrator/attempt/runner/session/retry_policy)、调度器(scheduler_service)、监控(monitor_service)、任务执行(task_executor) 等 20 个模块 |
| 网络检测 | Python | `app/network/` | probes（TCP/HTTP/URL 探测）、decision（聚合判定）、detect（网关/SSID）、interfaces（网卡枚举）、proxy（代理检测）、parsers（目标解析） |
| 任务系统 | Python | `app/tasks/` | JSON 驱动的浏览器自动化 DSL，含 manager、models、step_handlers、validator、variable_resolver、browser_runner |
| 工作线程 | Python | `app/workers/` | Playwright Actor 模型(playwright_worker)、脚本运行器(script_runner)、浏览器引导(playwright_bootstrap) |
| 前端 | JavaScript | `frontend/` | Vue 3 全局构建 SPA，零构建步骤，data/methods/tasks 三层分离，HTML partials 模板加载 |

### 基础设施

| 模块 | 路径 | 说明 |
|------|------|------|
| 应用入口 | `app/application.py` | FastAPI 工厂模式 `create_app()`，支持 full/lightweight 双模式，lightweight 可通过 `existing_container` 升级为 full |
| 依赖注入 | `app/container.py` | `ServiceContainer` 五步装配、late-binding 解决循环依赖（Engine↔Orchestrator↔TaskExecutor） |
| 注入别名 | `app/deps.py` | FastAPI `Depends` 类型别名，供路由层使用 |
| 数据模型 | `app/schemas.py` | 全部 Pydantic v2 frozen 模型，含 ProfilesData v5 持久化 Schema（~644 行） |
| 常量 | `app/constants.py` | 路径常量、超时、容量上限、默认网络目标、正则 |
| 版本 | `app/version.py` | 从 pyproject.toml 读取版本号，semver 比较工具 |
| 系统托盘 | `app/system_tray.py` | pystray 实现，延迟导入 |
| 工具模块 | `app/utils/` | cancel_token、browser_registry、crypto、concurrent、config_utils、logging、platform、ports、process、shell_policy、shutdown 等 ~20 个模块 |
| 任务定义 | `tasks/` | JSON 格式认证流程（browser/、scripts/、scheduled/），含 .order.json 排序和 active.txt 标记 |
| 配置持久化 | `config/settings.json` | 单一 JSON 持久化层（ProfilesData v5 Schema），无数据库 |
| Go 工具 | `resources/tools/` | start.exe（启动器）、git-puller.exe（Git 辅助）的 Go 源码 |
| 测试 | `tests/` | 10 个子目录 ~100 个测试文件，分 test_api、test_app、test_config、test_core、test_integration、test_network、test_services、test_tasks、test_utils、test_workers |

### 编码规范执行

| 配置文件 | 作用范围 |
|----------|----------|
| `pyproject.toml [tool.ruff]` | Python lint + format |
| `pyrightconfig.json` | Python 类型检查 |
| `.pre-commit-config.yaml` | Ruff + 其他预提交检查 |
| `.editorconfig` | 全局编辑器配置 |
| `uv.lock` | uv 依赖锁文件 |

## Phase 1: 探索 & 拆分 Review Unit

1. 用 `explore` subagent 扫描项目，确认当前有哪些模块/子目录有实质改动或需要关注
2. 基于下方 **默认 Unit 骨架表** 拆分 Review Unit，explore agent 可根据实际情况增删合并：
   - 每个 Unit 文件范围 ≤ 8 个核心文件
   - 有明确的 review 焦点
   - 提供该模块的背景信息
3. 标注优先级：P0（安全/崩溃/数据损坏）、P1（可靠性/性能/兼容性）、P2（代码质量/可维护性）

### Explore Agent Prompt 模板

```
你是 Campus-Auth 项目的探索分析员。扫描项目结构，返回以下信息：

1. 项目模块清单（目录名 + 核心文件 + 简述职责）
2. 近期有实质改动的模块（结合 git log 或文件修改时间）
3. 建议的 Review Unit 划分方案（15-20 个 Unit）

每个 Unit 包含：
- name: Unit 名称
- module: 所属模块
- files: 核心文件列表（≤ 8 个）
- focus: 审查焦点（1-2 句话）
- priority: P0 / P1 / P2
- background: 该模块的背景信息（帮助审查员理解上下文）

输出格式：JSON 数组，每个元素包含上述字段。
```

### 默认 Unit 骨架表

explore agent 应基于此骨架调整，而非从零开始：

| Unit 名称 | 模块 | 默认焦点 | 默认优先级 |
|-----------|------|----------|-----------|
| api-routes | API 路由层 | 路由注册、输入验证、错误处理、响应模型一致性、deps 注入正确性 | P1 |
| api-websocket | API 路由层 | WebSocket 连接管理(ws.py + websocket_manager.py)、日志广播、异常断开 | P1 |
| service-engine | 服务层 | Actor 引擎(engine.py)、监控循环(monitor_service.py)、命令队列、关闭顺序 | P0 |
| service-login | 服务层 | 登录管线(orchestrator→attempt→runner→session)、去重/抢占、重试策略(retry_policy)、历史记录 | P0 |
| service-scheduler | 服务层 | 定时调度(scheduler_service)、任务注册(task_registry)、任务执行(task_executor) | P1 |
| service-config | 服务层 | 配置构建(config_builder)、Profile CRUD(profile_service)、Pydantic frozen 模型(schemas.py) | P1 |
| service-debug | 服务层 | 调试会话(debug_service + debug_session)、状态机正确性、线程安全 | P2 |
| service-launcher | 服务层 | 进程生命周期(launcher.py)、PID 管理、full/lightweight 双模式启动 | P0 |
| network-probes | 网络检测 | TCP/HTTP/URL 探测判定逻辑、超时处理、shutdown_probes 清理 | P1 |
| network-detect | 网络检测 | 网关/SSID 检测(detect.py)、网卡枚举(interfaces.py)、代理检测(proxy.py)、解析器(parsers.py) | P1 |
| tasks-system | 任务系统 | JSON Schema 验证(validator)、变量解析安全性(variable_resolver)、步骤执行(step_handlers) | P0 |
| tasks-browser | 任务系统 | BrowserTaskRunner 执行流程、Playwright 交互、资源释放 | P1 |
| workers-playwright | 工作线程 | Playwright Actor 模型(playwright_worker)、线程安全、浏览器引导(bootstrap)、资源泄漏 | P0 |
| frontend-app | 前端 | Vue 3 初始化(app.js)、组件(components.js)、API 服务(api-service.js)、data 状态模块 | P1 |
| frontend-pages | 前端 | HTML partials 模板、methods 模块、任务编辑器(tasks/)、WebSocket 通信 | P1 |
| go-tools | Go 工具 | 启动器(resources/tools/start/)、Git 辅助(resources/tools/git-puller/)、进程管理、跨平台 | P2 |
| utils-core | 工具模块 | cancel_token、crypto(加密安全)、concurrent(异步睡眠)、browser_registry、logging | P0 |
| utils-platform | 工具模块 | 平台检测(platform.py)、进程管理(process.py)、Shell 策略(shell_policy)、端口(ports)、关闭(shutdown) | P1 |
| infra-di | 基础设施 | ServiceContainer(container.py) 装配顺序、late-binding、deps.py 注入别名 | P1 |
| test-coverage | 测试 | 覆盖率、Mock 正确性、异步测试稳定性、集成测试(test_integration/) | P2 |

### 各模块 Review 焦点

**Actor 引擎 (`app/services/engine.py` + `monitor_service.py`)**：

- Actor 模型正确性（专属 daemon 线程 + asyncio 事件循环 + asyncio.Queue 命令队列）
- 命令分发（EngineCommand.data 弱类型 dict 的线程安全性）
- 监控循环状态机（网络状态判定、定时触发、手动触发去重）
- 关闭顺序（Engine→Monitor→Worker→Probes 严格逆序）
- 轻量/完整模式切换（existing_container 复用）

**登录管线 (`app/services/login_*.py` + `retry_policy.py`)**：

- LoginOrchestrator 入口（去重、抢占、cancel_token 协作取消）
- 登录尝试生命周期（attempt→runner→session 调用链）
- MonitoredPolicy 重试策略（退避计算、attempt 计数、预算削减风险）
- 登录历史持久化（login_history_service 写入正确性）
- 跨线程安全（回调从线程池写引擎线程字段，GIL 保护但需验证）

**定时调度 (`app/services/scheduler_service.py` + `task_registry.py` + `task_executor.py`)**：

- 定时任务注册与触发（TaskRegistry + TaskHistoryStore）
- 任务执行正确性（TaskExecutor 调度 browser/script/shell 三类任务）
- CMD_LOGIN 复用风险（定时任务是否绕过 Orchestrator 直接提交 Worker）
- 历史记录持久化（scheduled/history/ JSON 写入）

**配置 & 依赖注入 (`app/container.py` + `schemas.py` + `config_builder.py`)**：

- ServiceContainer 五步装配顺序（late-binding 解决循环依赖的正确性）
- Pydantic v2 frozen 模型（不可变性保证、字段同步）
- RuntimeConfig 原子替换（getter 注入零停机热更新）
- 配置构建器（config_builder 从 profiles + settings.json 组装 RuntimeConfig）
- ProfileService 持久化（settings.json 读写一致性）

**FastAPI 路由 (`app/api/`)**：

- 路由注册完整性（18 个端点模块，重复注册、缺失端点）
- 响应模型一致性（Pydantic 模型与实际返回匹配）
- deps.py 注入别名正确性（Annotated 类型别名与 ServiceContainer 对齐）
- WebSocket 连接管理（ws.py + websocket_manager.py，连接泄漏、日志广播）
- 错误处理（HTTP 异常传播、全局异常捕获）

**网络模块 (`app/network/`)**：

- 探测策略准确性（TCP/HTTP/URL 探测判定逻辑，shutdown_probes 清理）
- 网关/SSID 检测可靠性（detect.py 跨平台实现差异）
- 网卡枚举（interfaces.py，psutil 接口类型缺失的已知限制）
- 代理检测（proxy.py）
- 聚合判定（decision.py 网络状态机正确性、边界条件）

**任务系统 (`app/tasks/`)**：

- JSON 任务定义 Schema 合规性（validator.py）
- 变量模板解析安全性（variable_resolver.py 注入风险）
- 浏览器自动化步骤正确性（step_handlers.py 各步骤类型）
- BrowserTaskRunner 执行流程（browser_runner.py，Playwright 交互、资源释放）
- 定时任务调度可靠性（与 scheduler_service 的交互）

**前端 (`frontend/`)**：

- Vue 3 全局构建初始化（app.js，无 SFC/编译器/构建步骤）
- data/ 响应式状态模块（14 个模块：config、dashboard、profiles、tasks 等）
- methods/ 行为模块（11 个模块：actions、config、profiles、lifecycle 等）
- tasks/ 任务编辑器子系统（core、debug、editor、index）
- HTML partials 模板加载（template-loader.js + data-include）
- API 调用错误处理（api-service.js，网络异常、超时）
- WebSocket 实时通信稳定性（websocket.js）
- XSS 防护（用户输入、动态内容渲染）

**Go 工具 (`resources/tools/`)**：

- 启动器进程管理（start/：子进程生命周期、信号处理、PID 文件）
- Git 辅助工具（git-puller/：网络操作安全性）
- 跨平台路径处理、依赖下载安全性

**测试 (`tests/`)**：

- 测试覆盖率（10 个子目录，关键路径是否覆盖）
- Mock 正确性（外部依赖隔离，特别是 Playwright、网络探测）
- 异步测试稳定性（超时、竞态、Actor 线程关闭）
- 集成测试完整性（test_integration/ 含 full/lightweight/login/network 等场景）

## Phase 2: 并行 Review

按优先级批次启动 subagent（若某优先级无 Unit 则跳过该批次）：

```
第一批：P0 Unit（3-5 个并行）
第二批：P1 Unit（5-7 个并行）
第三批：P2 Unit（剩余全部）
```

每个 review subagent 使用 `agent()` 调用，并通过 `schema` 参数强制输出结构。

### Prompt 模板

```
你是 Campus-Auth 项目的代码审查员。审查以下文件，找出：
1. Bug（逻辑错误、边界条件、竞态、崩溃风险）
2. 安全问题（注入、信息泄露、认证绕过）
3. 性能问题（不必要的内存分配、阻塞调用、O(n²) 算法）
4. 跨平台兼容性（Windows/macOS/Linux 差异处理）
5. 可维护性（巨型函数、重复代码、缺少错误处理）

项目语言：{language}
文件范围：{files}
背景：{background}
重点关注：{focus_areas}

输出格式：按严重性排序的问题列表（最多 Top 8）。每个问题包含：
- severity: "Critical" | "Major" | "Minor"
- file: 文件路径
- line_range: 行号范围（如 "42-58"）
- title: 问题标题（一句话）
- description: 问题描述
- impact: 会导致什么后果
- suggestion: 修复方向（一句话）
- code_snippet: 相关代码（可选，使用 ```startLine:endLine:filepath``` 格式）
```

### 输出 Schema

```json
{
  "type": "object",
  "properties": {
    "findings": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "severity": { "type": "string", "enum": ["Critical", "Major", "Minor"] },
          "file": { "type": "string" },
          "line_range": { "type": "string" },
          "title": { "type": "string" },
          "description": { "type": "string" },
          "impact": { "type": "string" },
          "suggestion": { "type": "string" },
          "code_snippet": { "type": "string" }
        },
        "required": ["severity", "file", "line_range", "title", "description", "impact", "suggestion"]
      }
    }
  },
  "required": ["findings"]
}
```

## Phase 3: 汇总 & 生成报告

收集所有 Unit 的发现，按以下步骤生成报告：

1. **去重合并**：同一 bug 在多个 Unit 被发现时，保留最详细的描述
2. **分类归类**：

| 分类 | 含义 | 图标 |
|------|------|------|
| 崩溃/安全 | 可导致崩溃或被利用 | 🔴 |
| 可靠性 | 影响功能正确性 | 🟠 |
| 性能 | 影响运行效率 | 🟡 |
| 兼容性 | 跨平台/版本兼容问题 | 🔵 |
| 代码质量 | 可维护性与规范 | ⚪ |

3. **按模块和严重性排序**
4. **生成统计摘要**

### 报告模板

将报告输出到项目根目录的 `code-review-report.md`，使用以下模板：

```markdown
# Campus-Auth 代码审查报告

> 审查时间：{date}
> 审查范围：{modules_reviewed}
> Review Unit 数量：{unit_count}

## 摘要

| 严重性 | 数量 |
|--------|------|
| 🔴 Critical | {n} |
| 🟠 Major | {n} |
| 🟡 Minor | {n} |
| 总计 | {total} |

| 模块 | Critical | Major | Minor |
|------|----------|-------|-------|
| （根据实际审查的 Unit 动态生成模块行） |

## 🔴 Critical 问题

### [{序号}] {问题标题}

- **模块**：{module}
- **文件**：`{file}:{line_range}`
- **分类**：{category}
- **描述**：{description}
- **影响**：{impact}
- **建议修复方向**：{suggestion}

{code_snippet（可选）}

---

## 🟠 Major 问题

### [{序号}] {问题标题}
...

## 🟡 Minor 问题

### [{序号}] {问题标题}
...

## 审查覆盖范围

| Review Unit | 模块 | 焦点 | 优先级 | 文件数 |
|-------------|------|------|--------|--------|
| {unit_name} | {module} | {focus} | {priority} | {file_count} |
| ... | ... | ... | ... | ... |

## 附注

- 本报告仅列出发现，未执行任何修复
- 建议按 Critical → Major → Minor 顺序处理
- 部分问题可能需要跨模块协同修复
```

## 红线 — 违反即失败

- **必须并行**：每个 Review Unit 必须用独立 `agent()` 调用，禁止单 agent 串行审查全部模块
- **必须用 Schema**：所有 review subagent 必须通过 `schema` 参数输出 JSON，禁止自由格式
- **必须按模板生成报告**：最终报告必须使用「报告模板」的结构（摘要表 → Critical → Major → Minor → 审查覆盖范围），禁止自创分类
- **只审不修**：本 skill 不修改任何代码，所有发现仅记录到报告
- **报告语言**：所有 finding 内容（title、description、impact、suggestion）必须使用中文，与报告模板一致

## 常见借口与应对

| 借口 | 事实 |
|------|------|
| "环境不支持并行 agent 调用" | `agent()` 工具始终可用。尝试调用，不要假设不可用 |
| "模块太少，不需要并行" | 即使只有 2 个 Unit，也必须用 2 个并行 agent |
| "串行和并行结果一样" | 并行减少审查时间，且 Schema 约束只在 subagent 中生效 |
| "报告格式差不多就行" | 模板是硬性要求，不得自创分类或结构 |
| "这个发现太重要了，我顺手修了" | 只审不修，修复留给用户决定 |

## 执行要点

- **只审不修**：本 skill 不修改任何代码，所有发现仅记录到报告
- **报告语言**：所有 finding 内容使用中文，代码片段保留原文
- **报告路径**：默认输出到 `code-review-report.md`，用户可指定其他路径
- **增量 vs 全量**：如用户指定范围（如"只看网络模块"），相应缩减 Unit 拆分
- **subagent 并行上限**：每批不超过 7 个，避免上下文竞争
- **Schema 强校验**：所有 review subagent 必须通过 `schema` 参数约束输出格式，确保 Phase 3 可靠解析
- **代码片段引用**：统一使用 `` ```startLine:endLine:filepath`` `` 格式，prompt 模板和报告模板保持一致
- **并行必须执行**：必须实际调用 `agent()` 并行审查，不得以任何理由跳过
