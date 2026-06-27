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

> 上述为常见目录，项目中还有 `app/network/`（网络检测）、`app/workers/`（Playwright 工作进程）、`app/core/`（核心模块）、`app/ui/`（系统托盘界面）等模块，请参考实际目录结构。

### 4.2 测试配套

新增模块必须配套测试文件，路径规则：

```
app/services/engine.py       →  tests/test_services/test_engine.py
app/utils/crypto.py          →  tests/test_utils/test_crypto.py
app/network/detector.py      →  tests/test_network/test_detector.py
```

通用规则：`app/<模块名>/<文件>.py` → `tests/test_<模块名>/test_<文件>.py`

### 4.3 前端资源

前端静态资源统一放在 `frontend/` 目录，不放在 `app/` 下。
