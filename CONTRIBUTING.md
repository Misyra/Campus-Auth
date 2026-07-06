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
uvx pre-commit install

# 安装 Playwright 浏览器（测试需要）
uv run playwright install chromium
```

## 开发流程

1. **创建分支**：从 `dev` 分支创建功能分支
   ```bash
   git checkout dev
   git checkout -b feat/my-feature
   ```

2. **编写代码**：遵循 [代码与提交规范](docs/dev/code-style-guide.md)

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

详见 [docs/dev/code-style-guide.md](docs/dev/code-style-guide.md)，涵盖：

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
