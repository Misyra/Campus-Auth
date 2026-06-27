# 项目规范体系建设实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 Campus-Auth 建立完整的规范体系，包括代码/注释/Commit 规范文档、GitHub 模板和贡献者指南，并整理现有文档。

**Architecture:** 集中式主规范文档 (`docs/code-style-guide.md`) + 独立 GitHub 模板文件 + 贡献者指南。所有文档使用中文。文档整理涉及将 `api-conventions.md` 合并到 `api-doc.md`。

**Tech Stack:** Markdown 文档、GitHub 模板格式

**Spec:** `docs/2026-06-27-project-standards-design.md`

---

### Task 1: 创建主规范文档 `docs/code-style-guide.md`

**Files:**
- Create: `docs/code-style-guide.md`

- [ ] **Step 1: 创建代码风格 + 注释风格 + Commit 约定 + 目录约定文档**

写入完整内容：

```markdown
# 代码与提交规范

> 本文档定义 Campus-Auth 项目的代码风格、注释规范和 Commit Message 约定。

---

## 1. 代码风格规范

### 1.1 格式化工具

使用 **Ruff** 自动格式化（已配置在 pre-commit hook 中）。提交代码前运行：

```bash
# 自动格式化
ruff format .
# 自动修复 lint 问题
ruff check --fix .
```

开发者无需手动调整缩进、行宽、引号风格等细节。

### 1.2 命名约定

| 类型 | 风格 | 示例 |
|------|------|------|
| 变量 / 函数 | `snake_case` | `get_profile`, `check_interval` |
| 类名 | `PascalCase` | `RuntimeConfig`, `NetworkMonitorCore` |
| 常量 | `UPPER_SNAKE_CASE` | `DEFAULT_TIMEOUT`, `PROJECT_ROOT` |
| 私有成员 | 单下划线前缀 | `_internal_state`, `_cleanup()` |
| 模块级私有 | 单下划线前缀 | `_TEMP_MAX_AGE = 7` |

### 1.3 导入排序

三个分组，按空行分隔（Ruff `I` 规则自动处理）：

1. 标准库（`os`, `time`, `asyncio` 等）
2. 第三方库（`fastapi`, `loguru`, `pydantic` 等）
3. 本项目模块（`app.xxx`）

### 1.4 类型注解

- **公共函数**：必须有参数类型和返回值类型注解
- **内部辅助函数**：建议添加，不做强制要求
- 类型检查工具：Pyright（basic 模式），配置见 `pyrightconfig.json`

```python
# 正确
def resolve_port(config: AppConfig, default: int = 50721) -> int:
    ...

# 避免（缺少类型注解）
def resolve_port(config, default=50721):
    ...
```

### 1.5 字符串

- 普通字符串：双引号（Ruff format 默认）
- Docstring：三双引号 `"""..."""`
- 包含双引号的字符串：使用单引号或转义

---

## 2. 注释与文档规范

### 2.1 语言

所有注释、docstring、文档均使用 **中文**。

### 2.2 模块级 docstring

每个 `.py` 文件的第一行必须是模块摘要，用一句话说明该模块的用途：

```python
"""FastAPI 应用入口 — 工厂模式：create_app() 延迟加载 FastAPI。"""

"""步骤处理器 — 10 个内置步骤处理器和注册表。"""

"""ScheduleEngine — 统一的后台服务引擎。"""
```

### 2.3 类 / 函数 docstring

公共 API（被其他模块调用的类和函数）**必须**有 docstring，说明用途和关键参数语义。内部辅助函数可以省略。

```python
class RuntimeConfig(BaseModel, frozen=True):
    """运行时配置根模型 — 替代旧 dict[str, Any]。

    组合所有子集模型。
    frozen=True 保证线程安全，无需 deepcopy。
    """
```

### 2.4 行内注释

- 解释 **"为什么"** 而非 "是什么"
- 写在代码 **上方**，不要写在行尾（除非极短的标注）

```python
# 正确：解释原因
# Windows 上 mimetypes 模块可能无法正确识别 .js 的 MIME 类型
mimetypes.add_type("application/javascript", ".js")

# 避免：描述代码本身
mimetypes.add_type("application/javascript", ".js")  # 添加 JS MIME 类型
```

### 2.5 标记约定

使用全大写关键字 + 冒号，便于全局搜索：

```python
# TODO: 支持自定义检测目标
# FIXME: 并发场景下偶现竞态条件
# HACK: 绕过 Playwright 的可见性检查
```

---

## 3. Commit Message 约定

### 3.1 格式

```
<type>: <subject>
```

- `type`：变更类型（见下表）
- `subject`：中文描述，句末 **不加句号**

### 3.2 Type 列表

| Type | 含义 | 示例 |
|------|------|------|
| `feat` | 新功能 | `feat: 新增定时任务调度模块` |
| `fix` | 缺陷修复 | `fix: 修复监控循环退出后重试策略未重置` |
| `refactor` | 重构（不改变外部行为） | `refactor: 提取公共启动逻辑为独立函数` |
| `docs` | 文档变更 | `docs: 补充 API 接口文档` |
| `style` | 代码格式调整（不影响逻辑） | `style: 统一导入排序` |
| `test` | 测试相关 | `test: 补充网络检测模块测试` |
| `chore` | 构建 / 工具链 / 依赖 | `chore: 升级 ruff 至 0.12.0` |
| `perf` | 性能优化 | `perf: 优化配置加载减少重复 IO` |
| `ci` | CI 配置变更 | `ci: 添加 Python 3.13 测试矩阵` |
| `build` | 构建系统变更 | `build: 迁移到 uv 包管理器` |

### 3.3 补充说明

- 一次 commit 只做一件事，保持原子性
- 如有 BREAKING CHANGE，在 subject 后加 `!`：`feat!: 重构配置结构`

---

## 4. 目录与模块约定

### 4.1 后端模块放置

| 职责 | 目录 |
|------|------|
| API 路由 | `app/api/` |
| 业务服务 | `app/services/` |
| 工具函数 | `app/utils/` |
| 任务定义 | `app/tasks/` |
| 数据模型 | `app/schemas.py` |
| 常量 | `app/constants.py` |

### 4.2 测试配套

新增模块必须配套测试文件，路径规则：

```
app/services/engine.py       →  tests/test_services/test_engine.py
app/utils/crypto.py          →  tests/test_utils/test_crypto.py
```

### 4.3 前端资源

前端静态资源统一放在 `frontend/` 目录，不放在 `app/` 下。
```

- [ ] **Step 2: 验证文件创建成功**

运行: `cat docs/code-style-guide.md | head -5`
预期: 显示 `# 代码与提交规范` 标题

- [ ] **Step 3: 提交**

```bash
git add docs/code-style-guide.md
git commit -m "docs: 添加代码风格与提交规范文档"
```

---

### Task 2: 创建 PR 模板

**Files:**
- Create: `.github/PULL_REQUEST_TEMPLATE.md`

- [ ] **Step 1: 创建 PR 模板文件**

```markdown
## 变更说明

<!-- 简要描述这个 PR 做了什么 -->

## 变更类型

- [ ] 新功能（feat）
- [ ] 缺陷修复（fix）
- [ ] 重构（refactor）
- [ ] 文档（docs）
- [ ] 样式/格式（style）
- [ ] 测试（test）
- [ ] 构建/CI（chore）
- [ ] 性能优化（perf）

## 关联 Issue

<!-- 如有，填写 Issue 编号，如 Closes #123 -->

## 测试情况

- [ ] 已在本地运行测试（`uv run pytest`）
- [ ] 已补充/更新相关测试用例

## 补充信息

<!-- 截图、日志、特殊说明等（可选） -->
```

- [ ] **Step 2: 提交**

```bash
git add .github/PULL_REQUEST_TEMPLATE.md
git commit -m "docs: 添加 PR 模板"
```

---

### Task 3: 创建 Issue 模板

**Files:**
- Create: `.github/ISSUE_TEMPLATE/bug_report.md`
- Create: `.github/ISSUE_TEMPLATE/feature_request.md`

- [ ] **Step 1: 创建 Bug 反馈模板**

创建 `.github/ISSUE_TEMPLATE/bug_report.md`：

```markdown
---
name: Bug 反馈
about: 报告一个缺陷，帮助改进项目
title: "[Bug] "
labels: bug
---

## 问题描述

<!-- 简要描述遇到的问题 -->

## 复现步骤

1.
2.
3.

## 期望行为

<!-- 描述你认为应该发生什么 -->

## 实际行为

<!-- 描述实际发生了什么 -->

## 环境信息

- 操作系统：
- Python 版本：
- Campus-Auth 版本：

## 日志/截图

<!-- 如有相关日志或截图，请粘贴在此 -->
```

- [ ] **Step 2: 创建功能请求模板**

创建 `.github/ISSUE_TEMPLATE/feature_request.md`：

```markdown
---
name: 功能请求
about: 提出一个新功能建议
title: "[Feature] "
labels: enhancement
---

## 功能描述

<!-- 简要描述你希望添加的功能 -->

## 使用场景

<!-- 说明这个功能在什么场景下有用 -->

## 建议实现方式

<!-- 如果有想法，可以描述建议的实现方式（可选） -->

## 补充信息

<!-- 其他相关信息（可选） -->
```

- [ ] **Step 3: 提交**

```bash
git add .github/ISSUE_TEMPLATE/
git commit -m "docs: 添加 Bug 反馈和功能请求 Issue 模板"
```

---

### Task 4: 创建贡献者指南

**Files:**
- Create: `CONTRIBUTING.md`

- [ ] **Step 1: 创建 CONTRIBUTING.md**

```markdown
# 贡献指南

感谢你对 Campus-Auth 的关注！本文档帮助你快速搭建开发环境并提交贡献。

## 开发环境搭建

### 前置要求

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) 包管理器（推荐）

### 安装依赖

```bash
# 克隆仓库
git clone https://github.com/<your-fork>/Campus-Auth.git
cd Campus-Auth

# 安装 Python 依赖
uv sync

# 安装 pre-commit hook（自动格式化和 lint 检查）
pre-commit install

# 安装 Playwright 浏览器（测试需要）
uv run playwright install chromium
```

## 开发流程

1. **创建分支**：从 `dev` 分支创建功能分支
   ```bash
   git checkout dev
   git checkout -b feat/my-feature
   ```

2. **编写代码**：遵循 [代码与提交规范](docs/code-style-guide.md)

3. **运行测试**：确保所有测试通过
   ```bash
   uv run pytest
   ```

4. **提交代码**：使用 Conventional Commits 格式
   ```bash
   git commit -m "feat: 你的变更描述"
   ```

5. **发起 PR**：向 `dev` 分支提交 Pull Request，使用 PR 模板填写变更说明

## 代码规范

详见 [docs/code-style-guide.md](docs/code-style-guide.md)，涵盖：

- 代码风格（Ruff 自动格式化）
- 注释与文档规范（中文）
- Commit Message 约定（Conventional Commits）
- 目录与模块约定

## 测试要求

- 提交前必须通过全部测试：`uv run pytest`
- 新增模块必须配套测试文件
- CI 必须全部通过（绿勾）

## PR 要求

- 使用 PR 模板填写变更说明
- 关联相关 Issue（如有）
- 确保 CI 流水线通过
- 一个 PR 聚焦一个功能或修复
```

- [ ] **Step 2: 提交**

```bash
git add CONTRIBUTING.md
git commit -m "docs: 添加贡献者指南"
```

---

### Task 5: 文档整理 — 合并 api-conventions 并清理

**Files:**
- Modify: `docs/api-doc.md`
- Delete: `docs/api-conventions.md`

- [ ] **Step 1: 将 api-conventions.md 内容合并到 api-doc.md 头部**

在 `docs/api-doc.md` 的标题和描述之后、目录之前，插入 API 错误响应规范内容：

在 `docs/api-doc.md` 第 3 行（`> 本文档汇总...`）之后，`---` 之前，插入：

```markdown

## API 错误响应规范

| 场景 | 响应方式 | 状态码 |
|------|----------|:------:|
| 资源不存在 | `HTTPException` | 404 |
| 参数非法 | `HTTPException` | 422 |
| 权限问题 | `HTTPException` | 403 |
| 业务可预期失败 | `ActionResponse(success=False)` | 200 |
| 程序异常（未捕获） | `HTTPException` | 500 |

**关键原则：**
1. `ActionResponse(success=False)` 只用于业务可预期失败
2. 未捕获异常统一返回 500，不要用 `ActionResponse(success=False, message=str(e))` 掩盖
3. 资源不存在用 404，不要返回 200 + `success=false`

**前端处理：**
- 4xx/5xx 状态码 → Axios 拦截器统一处理
- 200 + `success=false` → 业务层处理

```

- [ ] **Step 2: 删除 api-conventions.md**

```bash
git rm docs/api-conventions.md
```

- [ ] **Step 3: 提交**

```bash
git add docs/api-doc.md
git commit -m "docs: 合并 API 错误响应规范到接口文档，删除独立文件"
```

---

### Task 6: 最终验证

- [ ] **Step 1: 检查所有新文件存在**

```bash
# 验证所有交付物
test -f docs/code-style-guide.md && echo "OK: code-style-guide.md"
test -f .github/PULL_REQUEST_TEMPLATE.md && echo "OK: PULL_REQUEST_TEMPLATE.md"
test -f .github/ISSUE_TEMPLATE/bug_report.md && echo "OK: bug_report.md"
test -f .github/ISSUE_TEMPLATE/feature_request.md && echo "OK: feature_request.md"
test -f CONTRIBUTING.md && echo "OK: CONTRIBUTING.md"
test ! -f docs/api-conventions.md && echo "OK: api-conventions.md 已删除"
```

预期: 全部输出 OK

- [ ] **Step 2: 验证 api-doc.md 包含合并内容**

```bash
grep "API 错误响应规范" docs/api-doc.md
```

预期: 匹配到标题行

- [ ] **Step 3: 确认 git 状态干净**

```bash
git status
```

预期: `nothing to commit, working tree clean`
