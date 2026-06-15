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
| API 路由层 | Python | `app/api/` | FastAPI 路由，含 monitor、config、tasks、profiles 等模块 |
| 服务层 | Python | `app/services/` | 业务逻辑，含 engine、task_executor、monitor_service 等 |
| 网络检测 | Python | `app/network/` | probes（TCP/HTTP/URL 探测）、decision（决策层）、detect（网关/SSID） |
| 任务系统 | Python | `app/tasks/` | JSON 驱动的自动化流程，含 models、manager、step_handlers 等 |
| 工作线程 | Python | `app/workers/` | Playwright Actor 模型、脚本运行器 |
| 前端 | JavaScript | `frontend/` | Vue 3 SPA，无构建步骤，直接由 FastAPI 静态服务提供 |
| 启动器 | Go / Shell | `start.go` / `start.sh` | 自动下载 uv、安装依赖、启动应用 |

### 基础设施

| 模块 | 路径 | 说明 |
|------|------|------|
| 应用入口 | `app/application.py` | FastAPI 工厂模式 `create_app()` |
| 依赖注入 | `app/container.py` | ServiceContainer 服务生命周期管理 |
| 数据模型 | `app/schemas.py` | Pydantic 模型定义 |
| 工具模块 | `app/utils/` | browser、crypto、logging、login、network 等约 15 个模块 |
| UI 托盘 | `app/ui/` | 系统托盘实现 |
| 任务定义 | `tasks/` | JSON 格式认证流程（browser、scripts、scheduled） |
| 测试 | `tests/` | 约 70 个测试文件，分 test_api、test_app、test_config 等 |

### 编码规范执行

| 配置文件 | 作用范围 |
|----------|----------|
| `pyproject.toml [tool.ruff]` | Python lint + format |
| `pyrightconfig.json` | Python 类型检查 |
| `.pre-commit-config.yaml` | Ruff + 其他预提交检查 |
| `.editorconfig` | 全局编辑器配置 |

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
3. 建议的 Review Unit 划分方案（8-15 个 Unit）

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
| api-routes | API 路由层 | 路由注册、输入验证、错误处理、响应模型一致性 | P1 |
| api-websocket | API 路由层 | WebSocket 连接管理、异常断开处理 | P1 |
| service-core | 服务层 | 业务逻辑正确性、依赖注入生命周期 | P1 |
| service-async | 服务层 | async/await 正确性、事件循环阻塞、并发竞态 | P0 |
| network-probes | 网络检测 | TCP/HTTP/URL 探测判定逻辑、超时处理 | P1 |
| network-decision | 网络检测 | 网关/SSID 检测、网络状态机正确性 | P1 |
| tasks-system | 任务系统 | JSON Schema 验证、变量模板解析安全性、步骤执行顺序 | P0 |
| workers-playwright | 工作线程 | Playwright Actor 模型、线程安全、资源泄漏 | P0 |
| frontend-vue | 前端 | Vue 3 组件状态、API 错误处理、XSS 防护 | P1 |
| frontend-ws | 前端 | WebSocket 实时通信稳定性 | P1 |
| starter-go | Go 启动器 | 进程管理、依赖下载安全性、跨平台路径 | P2 |
| utils-crypto | 工具模块 | 加密/解密安全性、密钥管理 | P0 |
| utils-general | 工具模块 | 其他工具模块代码质量 | P2 |
| test-coverage | 测试 | 测试覆盖率、Mock 正确性、异步测试稳定性 | P2 |

### 各模块 Review 焦点

**Python 后端 (`app/`)**：

- 异步安全（async/await 正确性、事件循环阻塞、并发竞态）
- 依赖注入生命周期（ServiceContainer 初始化顺序、单例/瞬态混用）
- API 安全（输入验证、认证绕过、敏感信息泄露）
- 网络探测可靠性（超时处理、重试策略、探测目标可达性）
- Playwright Actor 模型（线程安全、资源泄漏、浏览器实例管理）
- 任务系统正确性（JSON Schema 验证、变量解析、步骤执行顺序）
- 跨平台兼容（路径处理、进程管理、自启动配置）

**FastAPI 路由 (`app/api/`)**：

- 路由注册完整性（重复注册、缺失端点）
- 响应模型一致性（Pydantic 模型与实际返回匹配）
- WebSocket 连接管理（连接泄漏、异常断开处理）
- 错误处理（HTTP 异常传播、全局异常捕获）

**网络模块 (`app/network/`)**：

- 探测策略准确性（TCP/HTTP/URL 探测判定逻辑）
- 网关/SSID 检测可靠性（跨平台实现差异）
- 决策层逻辑（网络状态机正确性、边界条件）

**任务系统 (`app/tasks/`)**：

- JSON 任务定义 Schema 合规性
- 变量模板解析安全性（注入风险）
- 浏览器自动化步骤正确性
- 定时任务调度可靠性

**前端 (`frontend/`)**：

- Vue 3 组件状态管理（响应式数据正确性）
- API 调用错误处理（网络异常、超时重试）
- WebSocket 实时通信稳定性
- XSS 防护（用户输入、动态内容渲染）
- 跨浏览器兼容性

**Go 启动器 (`start.go`)**：

- 进程管理（子进程生命周期、信号处理）
- 依赖下载安全性（校验和验证、HTTPS）
- 跨平台路径处理

**测试 (`tests/`)**：

- 测试覆盖率（关键路径是否覆盖）
- Mock 正确性（外部依赖隔离）
- 异步测试稳定性（超时、竞态）

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
