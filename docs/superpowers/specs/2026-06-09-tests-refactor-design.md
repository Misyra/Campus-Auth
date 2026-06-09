# 测试套件全面优化设计文档

**日期**: 2026-06-09
**状态**: 待审批

## 一、现状分析

### 1.1 规模

| 指标 | 数值 |
|------|------|
| 测试文件数 | 80 |
| 测试用例数 | 1899（1897 通过，2 跳过） |
| 测试代码行数 | 21,332 行 |
| 应用代码行数 | ~5,300 行 |
| 测试/应用代码比 | 4:1 |

### 1.2 核心问题

**问题 1: 大面积重复（最严重）**

之前做过两次合并（将独立文件合并为综合文件），但原独立文件未删除，导致：

- `test_utils.py`（综合）与 10 个独立工具测试文件**完全重复**
- `test_src_utils.py`（综合）与 5 个独立工具测试文件**完全重复**
- `test_backend_services.py`（综合）与 6 个独立服务测试文件**大部分重复**
- 监控层**三重重复**: test_monitor.py + test_monitor_core.py + test_monitor_core_logic.py
- 网络决策层**完全重复**: test_decision.py 与 test_network_probes.py
- 系统服务层**完全包含**: test_system_services.py 包含 test_autostart.py + test_uninstall.py
- 配置/Schema 层**完全包含**: test_config_schemas.py 包含 test_config_validator.py + test_schemas.py

**问题 2: 空壳文件**

- `test_api_config.py`（22 行）— 仅测试常量可导入
- `test_api_history.py`（21 行）— 仅测试类可导入
- `test_api_scripts.py`（19 行）— 仅测试字符串相等

**问题 3: 覆盖盲区**

8 个 API 路由模块缺少独立单元测试（3 个中风险，5 个低风险）。

**问题 4: 命名不一致**

- `test_api_*.py` vs `test_api_*_routes.py` 混用
- `test_utils.py` vs `test_src_utils.py` 职责不清

### 1.3 重复详细清单

| 重复组 | 综合文件 | 被包含的独立文件 | 操作 |
|--------|----------|------------------|------|
| 工具层 | test_utils.py | test_crypto.py, test_config_helpers.py, test_file_helpers.py, test_platform_utils.py, test_network_helpers.py, test_time_utils.py, test_version.py, test_env.py, test_exceptions.py, test_logging_utils.py | 删除独立文件 |
| src 工具层 | test_src_utils.py | test_notify.py, test_browser_utils.py, test_system_tray.py, test_playwright_bootstrap.py, test_playwright_worker.py | 删除独立文件 |
| 服务层 | test_backend_services.py | test_profile_service.py, test_profile_service_logic.py, test_debug_session.py, test_task_service_logic.py, test_network_detect.py | 合并独有测试后删除 |
| 监控层 | test_monitor.py | test_monitor_core.py, test_monitor_core_logic.py, test_login_handler.py | 合并独有测试后删除 |
| 监控服务 | test_monitor_service.py | test_monitor_service_shutdown.py | 合并后删除 |
| 网络决策 | test_network_probes.py | test_decision.py, test_network_probes_utils.py | 合并后删除 |
| 配置/Schema | test_config_schemas.py | test_config_validator.py, test_schemas.py | 删除独立文件 |
| 系统服务 | test_system_services.py | test_autostart.py, test_uninstall.py | 删除独立文件 |
| API 备份 | test_api_backup_routes.py | test_api_backup.py, test_logfiles.py, test_api_logfiles.py | 合并后删除 |
| API 工具 | test_api_tools_routes.py | test_api_tools.py | 合并后删除 |
| 空壳文件 | — | test_api_config.py, test_api_history.py, test_api_scripts.py | 直接删除 |
| 路由综合 | test_routers.py | test_api.py | 合并后保留一个 |

## 二、设计方案

### 2.1 目标结构

```
tests/
├── conftest.py                    # 共享 fixtures
├── test_routers.py                # API 路由综合测试（TestClient 集成测试）
├── test_api_backup_routes.py      # 备份路由
├── test_api_logfiles_routes.py    # 日志文件路由（原 test_api_logfiles.py）
├── test_api_scripts_routes.py     # 脚本路由
├── test_api_scheduled_tasks_routes.py  # 定时任务路由
├── test_api_system_routes.py      # 系统路由
├── test_api_tools_routes.py       # 工具路由
├── test_api_config_routes.py      # 配置路由（新）
├── test_api_tasks_routes.py       # 任务路由（新）
├── test_api_debug_routes.py       # 调试路由（新）
├── test_api_profiles_routes.py    # 方案路由（新）
├── test_api_monitor_routes.py     # 监控路由（新）
├── test_api_history_routes.py     # 历史路由（新）
├── test_api_repo_routes.py        # 仓库路由（新）
├── test_api_autostart_routes.py   # 自启动路由（新）
├── test_backend_services.py       # 后端服务层综合
├── test_config_schemas.py         # 配置与 Schema 综合
├── test_monitor.py                # 监控与登录综合
├── test_monitor_service.py        # 监控服务（含 shutdown 测试）
├── test_network_probes.py         # 网络探测与决策综合
├── test_network_detect_internals.py  # 网络检测内部实现
├── test_system_services.py        # 系统服务综合
├── test_utils.py                  # 工具模块综合
├── test_src_utils.py              # src 工具模块综合
├── test_main.py                   # 应用入口
├── test_application_logic.py      # 应用逻辑
├── test_container.py              # 服务容器
├── test_deps.py                   # 依赖注入
├── test_ws_manager.py             # WebSocket 管理
├── test_constants.py              # 常量
├── test_debug_session_manager.py  # 调试会话管理器
├── test_backup.py                 # 备份路由验证
├── test_task_executor.py          # 任务执行器
├── test_task_models.py            # 任务模型
├── test_task_validator.py         # 任务验证
├── test_task_manager_logic.py     # 任务管理器逻辑
├── test_variable_resolver.py      # 变量解析器
├── test_step_handlers.py          # 步骤处理器
├── test_script_runner.py          # 脚本运行器
├── test_script_task.py            # 脚本任务
├── test_scheduled_tasks.py        # 定时任务
├── test_scheduler_service.py      # 调度服务
├── test_shell_policy.py           # Shell 策略
├── test_shell_utils.py            # Shell 工具
├── test_process.py                # 进程管理
├── test_repo_proxy.py             # 仓库代理
├── test_system_shutdown.py        # 系统关机
└── test_login_history.py          # 登录历史
```

**文件数: 80 → 49（减少约 40%，其中 8 个为新增）**

### 2.2 命名规范

- API 路由测试统一后缀 `_routes.py`
- 综合测试文件不加后缀（如 `test_utils.py`）
- 模块测试文件以被测模块命名（如 `test_task_executor.py`）

### 2.3 分阶段实施

#### 阶段 1: 删除纯重复文件（无风险）

直接删除以下文件，因为其全部测试已被综合文件覆盖：

- `test_api_config.py`（22 行，仅 import 检查）
- `test_api_history.py`（21 行，仅 import 检查）
- `test_api_scripts.py`（19 行，仅类型断言）
- `test_config_validator.py`（已含于 test_config_schemas.py）
- `test_schemas.py`（已含于 test_config_schemas.py）
- `test_autostart.py`（已含于 test_system_services.py）
- `test_uninstall.py`（已含于 test_system_services.py）
- `test_profile_service_logic.py`（仅 2 个用例，已含于 test_backend_services.py）

#### 阶段 2: 合并独有测试后删除独立文件

对于独立文件中有综合文件未覆盖的独有测试，先合并到综合文件，再删除独立文件：

| 独立文件 | 独有测试 | 合并目标 |
|----------|----------|----------|
| test_crypto.py | TestSimpleObfuscate, TestDecryptionError | test_utils.py |
| test_config_helpers.py | 无独有（完全重复） | 直接删除 |
| test_file_helpers.py | 无独有（完全重复） | 直接删除 |
| test_platform_utils.py | 无独有（完全重复） | 直接删除 |
| test_network_helpers.py | 无独有（完全重复） | 直接删除 |
| test_time_utils.py | 无独有（完全重复） | 直接删除 |
| test_version.py | TestCompareVersions | test_utils.py |
| test_env.py | 无独有（完全重复） | 直接删除 |
| test_exceptions.py | 无独有（完全重复） | 直接删除 |
| test_logging_utils.py | TestDashboardSink, TestValidLogLevels | test_utils.py |
| test_notify.py | 无独有（完全重复） | 直接删除 |
| test_browser_utils.py | TestIsCancelled, TestBrowserContextManagerInit/Aexit | test_src_utils.py |
| test_system_tray.py | TestLoadIcon, TestGetStatusLabel, TestCreateMenu, TestQuit, TestStartStop, TestUpdateStatus | test_src_utils.py |
| test_playwright_bootstrap.py | TestBootstrapState | test_src_utils.py |
| test_playwright_worker.py | TestSubmitAliveCheck | test_src_utils.py |
| test_monitor_core.py | 无独有（完全重复） | 直接删除 |
| test_monitor_core_logic.py | TestExponentialBackoff, TestNegativeRetries 等 | test_monitor.py |
| test_login_handler.py | TestLoginAttemptHandlerInit, TestAttemptLogin 流程 | test_monitor.py |
| test_monitor_service_shutdown.py | 5 个队列行为测试 | test_monitor_service.py |
| test_decision.py | 无独有（完全重复） | 直接删除 |
| test_network_probes_utils.py | 无独有（完全重复） | 直接删除 |
| test_profile_service.py | TestProfileServiceTocFix（TOCTOU 修复） | test_backend_services.py |
| test_debug_session.py | 无独有（完全重复） | 直接删除 |
| test_task_service_logic.py | _DANGEROUS_STEP_TYPES 测试 | test_backend_services.py |
| test_login_history.py | 无独有（但用例更多，保留为独立文件） | 保留 |
| test_network_detect.py | 无独有（完全重复） | 直接删除 |
| test_api_backup.py | 无独有（完全重复） | 直接删除 |
| test_api_tools.py | TestConstants | test_api_tools_routes.py |
| test_logfiles.py | 无独有（完全重复） | 直接删除 |
| test_api_logfiles.py | 重命名 → test_api_logfiles_routes.py | — |
| test_api.py | 部分端点测试 | test_routers.py |

#### 阶段 3: 补充缺失的 API 路由测试

为 8 个缺少独立测试的 API 路由模块创建测试文件：

**中风险（优先）**：

1. `test_api_config_routes.py` — 配置读取/保存/校验端点
2. `test_api_tasks_routes.py` — 任务 CRUD 端点
3. `test_api_debug_routes.py` — 调试会话端点

**低风险**：

4. `test_api_profiles_routes.py` — 方案 CRUD 端点
5. `test_api_monitor_routes.py` — 监控启停端点
6. `test_api_history_routes.py` — 登录历史端点
7. `test_api_repo_routes.py` — 仓库代理端点
8. `test_api_autostart_routes.py` — 自启动端点

每个文件包含：
- 正常路径测试（200 响应）
- 错误路径测试（4xx/5xx 响应）
- 参数校验测试
- 依赖注入 mock

#### 阶段 4: 提升测试质量

- 修复 3 个 RuntimeWarning 警告（coroutine 未 await）
- 改进弱断言（`is not None` → 有意义的值断言）
- 增加 `@pytest.mark.parametrize` 使用场景
- 清理 conftest.py 中未使用的 fixtures

### 2.4 实施注意事项

- **独有测试需逐个验证**: 阶段 2 表中的"独有测试"列基于静态分析，实施时需逐个确认综合文件中是否已覆盖，避免遗漏
- **合并策略**: 对于需合并的文件，先用 `diff` 或手动比对确认独有测试，再追加到综合文件末尾对应 class 中
- **test_login_history.py 保留**: 虽然 test_backend_services.py 有 2 个 LoginHistoryService 测试，但 test_login_history.py 有 20+ 个完整 CRUD 用例，保留为独立文件
- **test_scheduled_tasks.py 与 test_scheduler_service.py**: 两者有部分重叠（_execute_shell），但各有独有测试，暂不合并
- **test_script_task.py 与 test_script_runner.py**: 两者有部分重叠，但各有独有测试，暂不合并

### 2.5 风险控制

- 每个阶段完成后运行 `uv run pytest` 确认全部通过
- 阶段 1 和 2 仅删除/合并，不修改被测代码
- 阶段 3 新增测试独立编写，不影响现有测试
- 如遇不确定的重叠，保留更完整的版本

### 2.6 预期成果

| 指标 | 优化前 | 优化后（预期） |
|------|--------|----------------|
| 测试文件数 | 80 | 49 |
| 测试用例数 | 1899 | ~1850（删除重复后）+ ~100（新增覆盖） |
| 重复测试 | ~40% | < 5% |
| API 路由覆盖 | 8/16 有独立测试 | 16/16 有独立测试 |
| RuntimeWarning | 3 | 0 |
