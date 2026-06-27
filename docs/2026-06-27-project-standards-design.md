# 项目规范体系建设设计文档

> **日期**: 2026-06-27
> **状态**: 已确认

## 1. 背景

Campus-Auth 已有 Ruff lint/format、Pyright 类型检查、CI 流水线和 pre-commit hook，但缺少以下规范资产：

- 正式的代码风格与注释风格文档
- PR 模板、Issue 模板
- 贡献者指南（CONTRIBUTING.md）
- Commit Message 约定文档
- docs 目录整理

## 2. 核心决策

| 决策项 | 选择 |
|--------|------|
| 文档语言 | 全部中文 |
| Commit Message 格式 | Conventional Commits（`<type>: <subject>`） |
| 执行方式 | 仅文档约定，不引入工具强制拦截 |
| 文档结构 | 集中式主规范文档 + 独立 GitHub 模板文件 |
| 编辑器配置 | 不添加 .editorconfig |

## 3. 交付物清单

### 3.1 新建文件

| 文件路径 | 用途 |
|----------|------|
| `docs/code-style-guide.md` | 主规范文档：代码风格 + 注释风格 + Commit 约定 + 目录约定 |
| `.github/PULL_REQUEST_TEMPLATE.md` | PR 模板 |
| `.github/ISSUE_TEMPLATE/bug_report.md` | Bug 反馈模板 |
| `.github/ISSUE_TEMPLATE/feature_request.md` | 功能请求模板 |
| `CONTRIBUTING.md` | 贡献者指南 |

### 3.2 文档整理

| 操作 | 说明 |
|------|------|
| `api-conventions.md` 合并到 `api-doc.md` | 内容仅 30 行，与 API 文档强相关，合并到 `api-doc.md` 头部作为规范说明段 |
| `2026-06-27-code-quality-optimization-design.md` 保留原位 | 一次性设计文档，保留在 docs/ 根目录（superpowers/ 被 gitignore） |
| 删除 `docs/api-conventions.md` | 内容已合并 |

## 4. 主规范文档内容设计（`docs/code-style-guide.md`）

### 4.1 代码风格规范

- **格式化工具**：Ruff format（已在 pre-commit 中配置），开发者无需手动格式化
- **命名约定**：
  - 变量 / 函数：`snake_case`
  - 类名：`PascalCase`
  - 常量：`UPPER_SNAKE_CASE`
  - 私有成员：单下划线前缀 `_name`
- **导入排序**：标准库 → 第三方库 → 本项目模块（Ruff `I` 规则自动处理）
- **类型注解**：公共函数必须有参数和返回值类型注解；Pyright basic 模式
- **字符串**：双引号为主（Ruff format 默认）；docstring 用三双引号

### 4.2 注释与文档规范

- **语言**：中文
- **模块级 docstring**：每个 `.py` 文件第一行必须是模块摘要（一句话说明用途）
  - 示例：`"""FastAPI 应用入口 — 工厂模式：create_app() 延迟加载 FastAPI。"""`
- **类 / 函数 docstring**：公共 API 必须有 docstring，说明用途和关键参数语义；内部辅助函数可省略
- **行内注释**：解释"为什么"而非"是什么"，写在代码上方而非行尾
- **标记约定**：`# TODO: 描述` / `# FIXME: 描述` / `# HACK: 描述`（全大写 + 冒号）

### 4.3 Commit Message 约定

- **格式**：`<type>: <subject>`，subject 用中文描述，句末不加句号
- **type 列表**：
  - `feat` — 新功能
  - `fix` — 缺陷修复
  - `refactor` — 重构（不改变外部行为）
  - `docs` — 文档变更
  - `style` — 代码格式调整（不影响逻辑）
  - `test` — 测试相关
  - `chore` — 构建 / 工具链 / 依赖
  - `perf` — 性能优化
  - `ci` — CI 配置变更
  - `build` — 构建系统变更
- **示例**：
  - `feat: 新增定时任务调度模块`
  - `fix: 修复监控循环退出后重试策略未重置`
  - `docs: 补充 API 接口文档`

### 4.4 目录与模块约定

- 新增 API 路由放 `app/api/`，服务逻辑放 `app/services/`，工具函数放 `app/utils/`
- 新增模块必须配套测试文件 `tests/test_<模块>/test_<文件名>.py`
- 前端静态资源放 `frontend/`，不放 `app/` 下

## 5. PR 模板设计

包含以下区块：
1. **变更说明** — 文本描述
2. **变更类型** — 单选 checklist（feat/fix/refactor/docs/style/test/chore/perf）
3. **关联 Issue** — 填写 Issue 编号
4. **测试情况** — 本地测试 + 测试用例补充确认
5. **补充信息** — 可选

## 6. Issue 模板设计

### 6.1 Bug 反馈（`bug_report.md`）

包含：问题描述、复现步骤、期望行为、实际行为、环境信息（OS / Python / 版本）、日志截图

### 6.2 功能请求（`feature_request.md`）

包含：功能描述、使用场景、建议实现方式（可选）、补充信息（可选）

## 7. CONTRIBUTING.md 设计

轻量级贡献者指南，核心内容：
1. **开发环境搭建** — `uv sync` 安装依赖 + `pre-commit install`
2. **开发流程** — fork → branch → code → test → PR
3. **规范引用** — 指向 `docs/code-style-guide.md`
4. **测试要求** — 提交前必须通过 `uv run pytest`
5. **PR 要求** — 使用 PR 模板，确保 CI 通过

## 8. 整理后的 docs 目录结构

```
docs/
├── api-doc.md              ← 合并 api-conventions 内容
├── code-style-guide.md     ← 新增：代码 / 注释 / Commit 规范
├── custom-script-guide.md
├── login.md
├── task-manual.md
├── task-writing-guide.md
├── update_log.md
└── superpowers/           ← gitignore，仅本地使用
    └── specs/
        └── 2026-06-27-code-quality-optimization-design.md
```
