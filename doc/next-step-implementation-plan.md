# Campus-Auth 下一步实施计划（2026-04-15）

## 1. 目标

基于当前代码审查结果，先完成高风险与高收益改造，确保：

- 配置保存不再覆盖用户已有关键配置。
- 任务变量解析不会出现递归死循环。
- 依赖安装路径一致，README 与实际行为一致。
- 任务 ID 处理路径统一，避免潜在路径拼接风险。
- 默认配置行为在前后端保持一致。
- 自启动在跨平台场景下具备可靠兜底。

## 2. 本次落地范围

### 2.1 Critical

1. 任务变量递归保护
- 文件：`src/task_executor.py`
- 改造：为模板变量解析增加循环检测与最大展开深度。
- 验收：`A->B->A` 配置能被明确拒绝并返回可读错误。

### 2.2 High

1. `.env` 增量写回
- 文件：`backend/config_service.py`
- 改造：保留原有注释与未知键，仅更新受 UI 管理的键值。
- 验收：保存配置后，若用户此前自定义 `APP_PORT` 或 `CAMPUS_AUTH_URL`，不被重置。

2. 依赖声明一致性
- 文件：`pyproject.toml`
- 改造：补齐运行时依赖 `Pillow` 与 `cairosvg`。
- 验收：按 `uv sync` 安装后，系统托盘依赖可用。

3. 启动器镜像参数生效
- 文件：`launcher.py`
- 改造：所有 pip 安装流程统一使用 `--pip-mirror` 参数。
- 验收：日志中显示并实际使用用户传入镜像。

4. 任务 ID 统一安全校验
- 文件：`backend/task_service.py`, `src/task_executor.py`
- 改造：统一 `task_id` 白名单规则并在文件层做路径约束。
- 验收：非法 `task_id` 不能触发任务读写。

### 2.3 Medium

1. 默认值一致性
- 文件：`src/utils/config.py`, `backend/schemas.py`
- 改造：统一 `MINIMIZE_TO_TRAY` 默认值策略。
- 验收：首次运行时 UI 默认与后端实际配置一致。

2. 自启动跨平台兜底
- 文件：`backend/autostart_service.py`
- 改造：当内置 Python 不存在时，优先使用运行时解释器路径作为兜底。
- 验收：非 Windows 或非内置环境仍可生成有效启动命令。

### 2.4 文档一致性

1. README 模板列表与实际对齐
- 文件：`README.md`
- 改造：修正内置模板描述，避免误导。
- 验收：README 与 `tasks/` 目录一致。

## 3. 不在本轮范围（后续迭代）

- API 鉴权与安全强化（本地 token、Origin 校验、敏感操作确认）。
- 自动化测试体系与 CI 全量引入。
- 任务模板 schema 版本化与迁移工具。

## 4. 实施顺序

1. `src/task_executor.py`：递归保护 + 任务 ID 约束。
2. `backend/config_service.py`：`.env` 增量写回。
3. `pyproject.toml` + `launcher.py`：依赖与镜像修复。
4. `backend/task_service.py`：统一任务 ID 校验。
5. `src/utils/config.py` + `backend/autostart_service.py`：默认值与自启动兜底。
6. `README.md`：文档对齐。
7. 全量错误检查并整理变更说明。

## 5. 交付标准

- 所有改动文件通过静态错误检查（至少 `get_errors` 无新增问题）。
- 关键逻辑在代码中有清晰边界处理（循环、非法输入、兜底路径）。
- 文档与代码行为一致，不出现明显冲突说明。
