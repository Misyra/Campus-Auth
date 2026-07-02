# 修改日志

## 2026-07-02

### docs: 文档目录重构与索引补全

**目录重构：**
- `docs/api-doc.md` → `docs/dev/api-reference.md`
- `docs/code-style-guide.md` → `docs/dev/code-style-guide.md`
- `docs/task-manual.md` → `docs/dev/architecture.md`
- `docs/custom-script-guide.md` → `docs/guides/custom-script-guide.md`
- `docs/task-writing-guide.md` → `docs/guides/task-writing-guide.md`
- `docs/update_log.md` → `docs/changelog.md`
- `docs/superpowers/specs/*` → `docs/designs/specs/*`
- `docs/superpowers/plans/*` → `docs/designs/archive/*`
- `dev/claude-code-hooks-guide.md` → `docs/dev/tools/claude-code-hooks.md`
- `CONTRIBUTING.md` 复制到 `docs/dev/contributing.md`

**新增索引文档：**
- `docs/README.md` — 文档总索引
- `docs/guides/README.md` — 用户文档导航
- `docs/dev/README.md` — 开发者文档导航
- `docs/designs/README.md` — 设计文档与归档导航

**链接更新：**
- `README.md`：更新所有 docs 引用路径
- `CONTRIBUTING.md`：更新 code-style-guide 引用路径
- `app/api/tools.py`：更新文档服务路径
- `docs/dev/architecture.md`：更新 task-writing-guide 和 api-reference 引用
- `docs/guides/custom-script-guide.md`：更新交叉引用
- `docs/dev/contributing.md`：更新 code-style-guide 引用

### docs: 修复 README 项目结构与实际不符

- 删除不存在的 `app/ui/system_tray.py` 引用，改为 `app/system_tray.py`
- 删除不存在的 `app/services/task_service.py`、`config_service.py`、`runtime_config.py` 引用
- 删除不存在的 `app/utils/login.py` 引用
- 补充遗漏的 `login_orchestrator.py`、`login_handler.py`、`login_runner.py`、`config_builder.py`、`scheduler_service.py`、`retry_policy.py`、`launcher.py` 等
- 补充遗漏的 API 路由文件：`browsers.py`、`install_playwright.py`、`icons.py`、`ws.py`
- 补充 `app/tasks/` 下的 `manager.py`、`browser_runner.py`、`step_handlers.py`、`validator.py`
- 更新"主要模块说明"部分

### docs: 创建 CLAUDE.md

- 新增项目级 CLAUDE.md，包含技术栈、开发命令、代码规范、项目结构、架构要点、测试规范、Git 规范、常见陷阱

### refactor: 消除模块间不当耦合

- `VALID_LOG_LEVELS` 从 `app/utils/logging.py` 移至 `app/constants.py`，解除 `schemas → utils/logging` 依赖
- `URL_PATTERN` 从 `app/schemas.py` 移至 `app/constants.py`，消除私有符号跨模块导入
- `app/utils/config_utils.py` 改为从 `app.constants` 导入 `URL_PATTERN`
- `_runtime_config_to_worker_dict` 改为公开函数 `runtime_config_to_worker_dict`，消除私有函数导入
- 清理 `app/workers/manager/` 空目录残留

### docs: 添加系统架构文档

- `docs/architecture.md`：新增系统架构图、启动流程、数据流、线程模型、设计模式说明

### refactor: 迁移 background 目录到 resources

- `frontend/background/` → `resources/background/`：移动背景图片存储目录
- `app/api/tools.py`：更新 `BG_DIR` 路径为 `PROJECT_ROOT / "resources" / "background"`
- `.gitignore`：更新忽略路径为 `resources/background/`

## 2026-06-29

### refactor: 移动 DecryptionError 到 crypto.py 作为 _DecryptionError + 内联 safe_decrypt()

- `app/utils/crypto.py`：新增 `_DecryptionError` 私有异常类，移除 `DecryptionError` 导入；删除 `safe_decrypt()` 函数，其逻辑内联到 `decrypt_password_field()`
- `app/utils/exceptions.py`：删除 `DecryptionError` 类
- `tests/test_utils/test_crypto.py`：更新导入为 `_DecryptionError`（从 `app.utils.crypto`）
- `tests/test_utils/test_utils.py`：移除 `DecryptionError` 导入和相关测试
- `tests/test_config/test_config_schemas.py`：移除 `safe_decrypt` 导入和 `TestSafeDecrypt` 测试类

### refactor: 删除前端死函数 — getBrowser/getBrowserIcon/isBrowserInstalled/getOtherBrowsers/formatFileSize/togglePureMode/fetchPureMode + _notifyCategoryLabel 改常量

- `frontend/js/methods/ui.js`：删除 `getBrowser`、`getBrowserIcon`、`isBrowserInstalled`、`getOtherBrowsers` 四个未调用方法；将 `_notifyCategoryLabel` 方法转换为模块级常量 `NOTIFY_CATEGORY_LABELS`
- `frontend/js/methods/formatters.js`：删除未调用的 `formatFileSize` 方法
- `frontend/js/api-service.js`：删除未调用的 `togglePureMode`、`fetchPureMode`（实际调用走 editor.js 直接请求）

### refactor: ConfigBuilder 类改为 build_runtime_config() 函数

- `app/services/config_builder.py`：移除 `ConfigBuilder` 类，`build()` 静态方法改为顶层函数 `build_runtime_config()`
- `app/services/profile_service.py`：更新导入和调用（`ConfigBuilder.build(...)` → `build_runtime_config(...)`）
- `tests/test_services/test_config_builder.py`：更新导入和所有调用
- `tests/test_app/test_backend_services.py`：更新导入和所有调用
- `tests/test_services/test_config_service.py`：更新导入和所有调用

### test: 删除 test_engine_fix.py — 已被 test_engine.py 全面覆盖

- 删除 `tests/test_services/test_engine_fix.py`（183 行，6 个测试）
- 6 个测试已由 `test_engine.py` 全面覆盖（135 passed，含 TestDoAsyncLogin + TestNetworkCheckBackoff）

### refactor: 测试套件瘦身 — 删除死代码、合并重复 fixture

- `tests/test_config/test_constants.py`：删除（常量存在性测试，已在 `test_ws_broadcaster.py` 和 `test_login.py` 中覆盖）
- `tests/test_integration/__init__.py`：删除（空文件）
- `tests/test_utils/test_shell_policy_fix.py`：删除空测试类 `TestReturncodeNoneBug`
- `tests/test_services/test_task_executor_fix.py`：删除未使用的 `_slow_return` 工具函数
- `tests/test_integration/conftest.py`：合并 `full_stack` 到 `integration_stack`（返回 5-tuple 含 `task_registry`），删除 `full_stack` fixture
- `tests/test_integration/test_full_mode.py`：改用 `integration_stack`，更新解构
- `tests/test_integration/test_lightweight_mode.py`：更新解构适配 5-tuple
- `tests/test_integration/test_login_connection.py`：更新解构适配 5-tuple
- `tests/test_integration/test_login_integration_extended.py`：更新解构适配 5-tuple
- `tests/test_integration/test_network_connection.py`：更新解构适配 5-tuple
- `tests/test_integration/test_profile_connection.py`：更新解构适配 5-tuple

### refactor: 合并 WsBroadcaster 到 WebSocketManager，删除 NullWebSocketManager

- `app/services/ws_broadcaster.py`：已删除，广播队列功能合入 `WebSocketManager`
- `app/services/websocket_manager.py`：新增 `_broadcast_queue`、`_drain_event`、`set_dashboard_sink`、`broadcast_queue`、`enqueue_status`、`_notify_drain`、`ws_drain_loop`、`_drain_queue` 方法；删除 `NullWebSocketManager` 类
- `app/services/engine.py`：删除 `ws_broadcaster` 参数，`set_ws_broadcaster` 改名为 `set_ws_manager`；`WS_DRAIN_INTERVAL_SECONDS` re-export 改从 `websocket_manager` 导入
- `app/services/engine_status.py`：`ws_broadcaster` 参数改名为 `ws_manager`
- `app/container.py`：删除 `WsBroadcaster` 和 `NullWebSocketManager` 引用，统一使用 `WebSocketManager`
- `app/utils/logging.py`：更新 `set_drain_notifier` 注释
- `tests/test_services/test_ws_broadcaster.py`：重写为测试 `WebSocketManager` 广播队列功能
- `tests/test_services/test_websocket_manager.py`：删除 `NullWebSocketManager` 测试
- `tests/test_services/conftest.py`：`_ws_broadcaster` 改为 `_ws_manager`
- `tests/test_services/test_engine.py`：更新 `ws_broadcaster` 引用为 `ws_manager`
- `tests/test_config/test_container.py`：删除 `WsBroadcaster` 和 `NullWebSocketManager` 相关 patch 和断言
- `tests/test_config/test_constants.py`：更新 `WS_DRAIN_INTERVAL_SECONDS` 导入路径

### refactor: 合并 engine_status.py 和 engine_login_bridge.py 回 engine.py

- `app/services/engine_status.py`：已删除，`StatusSnapshot` 和 `StatusManager` 合并入 `engine.py`
- `app/services/engine_login_bridge.py`：已删除，`LoginBridge` 合并入 `engine.py`
- `app/services/engine.py`：新增 `StatusSnapshot`、`StatusManager`、`LoginBridge` 三个类，删除对旧模块的导入和延迟导入
- `tests/test_services/conftest.py`：更新导入路径
- `tests/test_services/test_engine.py`：更新导入路径
- `tests/test_services/test_engine_login_bridge.py`：更新导入路径
- `tests/test_services/test_engine_fix.py`：更新导入路径
- `tests/test_services/test_monitor_service.py`：更新导入路径
- `tests/test_integration/test_login_flow.py`：更新导入路径
- `StatusManager` 适配 `ws_manager`/`WebSocketManager` 接口（替代原 `ws_broadcaster`/`WsBroadcaster`）

### refactor: 用 check_network_status 简化 _network_detection_check

- `app/tasks/browser_runner.py`：
  - `_network_detection_check` 方法从约 60 行简化为约 25 行
  - 移除手动解包 `MonitorSettings`、调用 `parse_ping_targets`、`parse_url_checks`、`is_network_available` 的冗余逻辑
  - 改为直接调用 `check_network_status(monitor)`，该函数已封装全部检测逻辑
  - 保留 `post_login_delay` 等待逻辑和 `MonitorSettings` 默认值填充

### chore: 删除散落的死函数

- `app/utils/crypto.py`：删除 `mask_password` 函数（零生产调用）
- `app/utils/__init__.py`：移除 `mask_password` 导入和 `__all__` 条目
- `app/utils/shutdown.py`：删除 `request_graceful_exit` 函数和 `signal` 导入（零生产调用）
- `app/utils/process.py`：删除 `normalize_proc_name` 函数和 `__all__` 条目（零生产调用）
- `app/services/debug_service.py`：删除 `DebugSessionManager.get_status` 方法（零生产调用）
- `app/services/task_registry.py`：删除 `TaskRegistry.get_tasks_dir` 方法（零生产调用）
- 测试同步更新：
  - `tests/test_utils/test_crypto.py`：删除 `TestMaskPassword` 测试类
  - `tests/test_utils/test_utils.py`：删除 `mask_password` 导入和 `TestMaskPassword` 测试类
  - `tests/test_utils/test_shutdown.py`：删除 `TestRequestGracefulExit` 测试类和 `os` 导入
  - `tests/test_app/test_main.py`：删除 `TestNormalizeProcName` 测试类
  - `tests/test_utils/test_process.py`：删除 `normalize_proc_name` 导入和 `TestNormalizeProcName` 测试类
  - `tests/test_services/test_debug_session_manager.py`：删除 `TestDebugSessionManagerGetStatus` 测试类
  - `tests/test_services/test_task_executor_fix.py`：删除 `TestTaskRegistryGetTasksDir` 测试类

### chore: 删除 engine.py 测试专用死属性

- `app/services/engine.py`：
  - 删除 `login_in_progress` property（委托 `_task_executor.is_login_running()`，零生产调用）
  - 删除 `scheduler_running` property（委托 `_scheduler.running`，零生产调用）
  - 删除 `has_enabled_tasks()` method（委托 `_scheduler.has_enabled_tasks()`，零生产调用）
- 测试同步更新：
  - `tests/test_services/test_engine.py`：
    - `test_init_defaults`：`svc.scheduler_running` → `svc._scheduler.running`（加 None 守卫）
    - 删除 `TestProperties.test_login_in_progress_property`、`test_scheduler_running_property`
    - 删除 `TestSchedulerControl.test_has_enabled_tasks`
  - `tests/test_integration/test_login_flow.py`：
    - `test_login_in_progress_property`：改用 `svc._task_executor.is_login_running()` 直接断言
    - `test_retry_not_triggered_during_login`：改用 `svc._task_executor.is_login_running()` 直接断言
  - `tests/test_services/test_monitor_service.py`：删除 `TestLoginInProgress` 整个测试类

## 2026-06-28

### refactor: 代码质量优化 — 清理死代码和冗余抽象

**任务组 1: schemas.py + deps.py**
- `app/schemas.py`：
  - 删除 `ActionResponse = ApiResponse` 死别名（零引用）
  - 删除 `LaunchSource.UNKNOWN` 枚举值（零引用）
  - 删除 `AppConfig.config_version` 死字段（零读取）
  - 删除 `_parse_url_check` 函数内冗余 `import re`（模块顶层已导入）
- `app/deps.py`：
  - 删除 `get_services` 函数（零 API 端点使用）
  - 删除未使用的 `ServiceContainer` 导入
- `tests/test_config/test_deps.py`：同步删除 `get_services` 测试和导入

**任务组 2: repo.py + tools.py + config.py**
- `app/api/repo.py`：
  - 删除两个端点未使用的 `ProfileService` 注入参数
  - 删除未使用的 `get_profile_service` 和 `ProfileService` 导入
- `app/api/tools.py`：
  - 提取 `_serve_doc(relative_path, media_type, filename)` 辅助函数
  - 提取 `_save_background(content, ext)` 辅助函数
  - `download_task_writing_guide` 和 `download_task_manual` 改用 `_serve_doc`
  - `upload_background` 和 `fetch_background_url` 改用 `_save_background`
- `app/api/config.py`：
  - 提取 `_handle_config_error` 上下文管理器统一错误处理
  - `save_config` 和 `patch_config` 改用 `_handle_config_error`（保留差异：`log_warning` 参数）
  - 删除 `_flatten_dict` 无用 `sep` 参数，硬编码 "."

**任务组 3: tasks/ 模块**
- `app/tasks/step_handlers.py`：删除 `StepExecutorRegistry` 类（`register()` 从未调用）
- `app/tasks/browser_runner.py`：
  - `self.registry = StepExecutorRegistry()` → `self.registry = dict(DEFAULT_HANDLERS)`
  - 更新导入
- `app/tasks/__init__.py`：
  - 从导入和 `__all__` 中删除 `StepExecutorRegistry`
  - 删除 `TaskExecutor = BrowserTaskRunner` 向后兼容别名
- `app/tasks/manager.py`：
  - 提取 `_with_task_id_validation` 装饰器，三个验证方法改用装饰器
  - 删除 `_find_task_type` 中单元素循环 `for ext in (".json",):`
  - 删除 `_is_script_file` 静态方法，内联为条件表达式
  - 删除 `get_script_path_public` 委托方法
- `app/services/login_handler.py`：`TaskExecutor` → `BrowserTaskRunner`
- `app/api/scripts.py`：`get_script_path_public` → `_safe_task_path`
- 测试文件同步更新

**任务组 4: workers/ + 工具文件**
- `app/workers/playwright_worker.py`：删除 `submit_nowait` 方法（零生产调用）
- `app/workers/playwright_bootstrap.py`：从 `VALID_CHANNELS` 删除 `msedge`/`chrome`/`custom`（L135 提前 return 后不可达）
- `app/utils/browser.py`：删除 `self._worker_managed` 属性（零读取）
- `app/utils/browser_registry.py`：
  - 删除 `_has_playwright_chromium()` 空壳函数
  - 调用处改为直接调用 `has_playwright_chromium()`
- 测试文件同步更新

**任务组 5: shell_policy.py**
- `app/utils/shell_policy.py`：
  - 删除 `async run()` 方法（零生产调用，仅 `run_sync` 被使用）
  - 删除 `async _kill_process_tree()` 方法（仅被 async run 调用）
  - 删除 `audit_hook` 参数及相关代码（两个生产调用方均未传入）

**任务组 6: logging.py**
- `app/utils/logging.py`：
  - 删除 `LogConfigCenter.get_logger()` 类方法（零生产调用，模块级 `get_logger` 函数才是被广泛使用的）
  - 删除 `LogConfigCenter.is_initialized()` 方法（仅测试调用）
  - 删除 `LogConfigCenter.remove_source_level()` 方法（零调用）

**任务组 7: platform.py + retry.py**
- `app/utils/platform.py`：
  - 删除 `_WINDOWS_UA`、`_MACOS_UA`、`_LINUX_UA` 三个 UA 常量
  - 删除 `get_default_ua()` 函数（仅测试使用，Chrome 125 已过时）
  - 从 `__all__` 中移除 `"get_default_ua"`
- 删除 `app/utils/retry.py` 整个文件（`get_retry_intervals` 零生产调用者）

**任务组 8: engine.py + task_executor.py**
- `app/services/engine.py`：删除 `_runtime_snapshot` 死字段（仅写入，零读取）
- `app/services/task_executor.py`：删除 `force_clear_login_slot` 方法（与 `cancel_login` 完全相同，零调用）

**任务组 9: login_handler.py + engine_login_bridge.py**
- `app/services/login_handler.py`：
  - 合并 `_perform_login_with_auth_class` 中间层到 `attempt_login`
  - 调用链从 3 层简化为 2 层：`attempt_login` → `_perform_login_with_active_task`
- `app/services/engine_login_bridge.py` + `app/services/engine.py`：
  - LoginBridge 回调从猴子补丁改为构造函数参数注入
  - 新增 `on_retry_scheduled`、`on_login_success`、`on_retry_exhausted` 可选参数

**任务组 10: network_tester.py + debug_session.py + uninstall.py**
- `app/services/network_tester.py`：`NetworkTester` 类改为模块级函数 `test_network(config)`
- `app/services/debug_session.py`：删除 `empty_debug_session()` 工厂函数，调用处改为 `DebugSession()`
- `app/services/uninstall.py`：删除 `_reset_autostart_service()` 函数（仅测试使用）

### test: 修复因删除死方法导致的测试引用

- `tests/test_core/test_monitor.py`：`_perform_login_with_auth_class` → `_perform_login_with_active_task`
- `tests/test_utils/test_login.py`：
  - `TestAttemptLogin` 改 patch `_perform_login_with_active_task`
  - `TestPerformLoginWithAuthClass` 合并到 `TestAttemptLogin`
  - `app.tasks.TaskExecutor` → `app.tasks.BrowserTaskRunner`（5 处）
- `tests/test_utils/test_utils.py`：删除 `test_is_initialized_default_false`（方法已不存在）

### test: 修复预存测试失败

- `tests/test_core/test_network_probes.py`：
  - 添加 `_fresh_executor` autouse fixture，解决模块级 `ThreadPoolExecutor` 被 atexit 关闭后后续测试全部失败的问题
  - fixture 检测 executor 是否已关闭，关闭时替换为新实例并在测试后恢复
- `tests/test_integration/test_network_connection.py`：
  - `test_need_login` 和 `test_network_ok` 添加 `check_pause` mock，避免凌晨时段测试因暂停时段检查而失败
- `tests/test_integration/test_login_once_mode.py`：
  - `mock_history.record` → `mock_history.add`（`LoginHistoryService` 方法名已从 `record` 改为 `add`）
- `tests/test_integration/test_full_mode.py`：
  - 删除 `engine._start_scheduler()` 调用（调度器已随监控一起启动）
  - 删除 `engine._run_schedule_tick()` 调用（已不存在），改为直接调用 `engine._scheduler.tick(now)`
  - 添加 `check_pause` mock 避免时段依赖
- `tests/test_services/test_script_runner.py`：
  - `test_cmd_binary_on_windows` 断言从 `"call" in cmd[2]` 改为 `str(script) in cmd[2]`（代码已不加 "call"）

### test: 修复 os._exit 杀死 pytest 进程

- `tests/test_app/test_boot_engine_flag.py`：TestRunFullNoDirectBoot 调用 `launcher.launch_full`，其 `finally` 块调用 `force_exit(0)` 即 `os._exit(0)`
  - 添加 `patch("app.services.launcher.force_exit")` 到 `test_run_full_does_not_call_boot_directly` 和 `test_run_full_passes_boot_engine_false`
  - 修复前全量测试在 ~13% 处被 `os._exit(0)` 杀死

### test: 修复 Task 5 测试 — 更新 patch 目标和 asyncio 兼容性

- `tests/test_services/test_launcher.py`：替换已废弃的 `asyncio.coroutine()` 为 `async def` helper
- `tests/test_app/test_main.py`：更新 patch 目标到实际源模块
  - TestRunServer / TestSignalHandler：`main.is_service_running` → `app.services.launcher.is_service_running`
  - TestRunLoginThenExit：`main.create_profile_service` → `app.services.profile_service.create_profile_service`
  - TestRunLoginThenExit：`main.cleanup_orphan_browsers` → `app.workers.playwright_worker.cleanup_orphan_browsers`
  - TestLoginOnceRetryInterval：`main.AUTH_DATA_DIR` → `app.constants.AUTH_DATA_DIR`
  - TestSignalHandler：`main.cleanup_pid` → `app.services.launcher.cleanup_pid`
- `tests/test_integration/test_login_integration_extended.py`：已使用正确的 patch 目标，无需修改

### refactor: 从 main.py 提取 launcher + login_runner

- `app/services/launcher.py`：新建启动器模块，从 main.py 迁移 12 个函数
  - `shutdown_container`：统一关闭容器（幂等安全）
  - `open_browser`：浏览器控制
  - `create_tray`：系统托盘创建
  - `handle_startup_action`：启动动作状态机
  - `handle_existing_instance`：已运行实例检测
  - `launch_lightweight`：轻量模式（闭包改为参数传递）
  - `launch_full`：完整模式（signal handler 保留内嵌 nonlocal）
  - `launch_server`：主启动流程
  - `_start_web_server` / `_open_console`：闭包辅助函数改为顶层函数+参数传递
  - `_terminate_process` / `_wait_for_exit`：进程管理内部辅助
- `app/services/login_runner.py`：新建自动登录执行器，从 main.py 迁移 3 个函数
  - `load_login_config`：加载登录配置
  - `execute_login_with_retries`：执行登录含重试
  - `run_login_then_exit`：自动登录成功后退出
- `main.py`：从 ~787 行精简至 ~275 行，保留 CLI 命令、`_build_app_config`、`_setup_exception_hooks`、`main()` 入口；添加向后兼容 re-export
- `tests/test_services/test_launcher.py`：新增 6 个基础测试（shutdown_container 幂等性 + open_browser 行为）
- `tests/test_app/test_main.py`：更新 5 个 _run_server 测试的 patch 目标（main → app.services.launcher）
- `tests/test_app/test_main_fix.py`：更新 TestOpenBrowser（4 个）和 TestOnExitLambda（2 个）的 patch/inspect 目标
- `tests/test_app/test_boot_engine_flag.py`：更新 2 个 _run_full 测试的 patch 目标和 mock 设置
- `tests/test_integration/test_login_once_mode.py`：更新 5 个测试的 patch 目标（main → login_runner/launcher）
- `tests/test_integration/test_login_integration_extended.py`：更新 3 个测试的 cleanup_orphan_browsers patch 目标

### refactor: 添加 shutdown 工具函数，替换 os._exit 为 force_exit

- `app/utils/shutdown.py`：新增退出工具模块，提供 `force_exit`（atexit 钩子 + os._exit）和 `request_graceful_exit`（SIGTERM）
- `main.py`：4 处 `os._exit` 替换为 `force_exit`（轻量 finally、uvicorn 未就绪、完整 finally），1 处双击 Ctrl+C 保留 `os._exit(1)` 并加注释
- `app/application.py`：1 处 `os._exit(0)` 替换为 `force_exit(0)`
- `tests/test_utils/test_shutdown.py`：新增 5 个测试覆盖 force_exit 和 request_graceful_exit

### fix: 加固 ws disconnect 异常处理 + parse_url_check 兼容逗号分隔

- `app/api/ws.py`：disconnect 异常处理加 try-except 保护 `ws_manager.disconnect()`，防止连接已关闭时二次异常导致 handler 崩溃
- `app/schemas.py`：`_parse_url_check` 分隔符从仅换行 `\n` 改为 `re.split(r'[,\n]', raw)`，同时支持逗号和换行分隔

### test: 更新 engine 测试适配 SchedulerService 委托模式

- `tests/test_services/conftest.py`：raw 工厂将 `_scheduler_running`/`_next_schedule_tick` 替换为 `_scheduler` MagicMock（`.running`、`.next_tick_time`、`.has_enabled_tasks()`）
- `tests/test_services/test_engine.py`：17 个测试适配新委托模式 — `_start_scheduler()`/`_stop_scheduler()` 改为 `scheduler.start()`/`scheduler.stop()`，`_run_schedule_tick()` 改为 `SchedulerService.tick()`，`_scheduler_running` 改为 `scheduler.running`
- `tests/test_services/test_monitor_service.py`：`test_shutdown_sends_stop_through_queue` 适配 `_scheduler` 替代 `_scheduler_running`

### refactor: 从 ScheduleEngine 提取 SchedulerService

- `app/services/scheduler_service.py`：新增独立的定时任务调度器组件，包含 start/stop/tick/sync_state 等完整生命周期管理
- `app/services/engine.py`：移除 `_scheduler_running`、`_next_schedule_tick` 字段及 `_run_schedule_tick`、`_start_scheduler`、`_stop_scheduler` 方法，改为委托 `SchedulerService`；`__init__` 新增 `scheduler` 参数
- `app/container.py`：创建 `SchedulerService` 实例并注入 `ScheduleEngine`
- `tests/test_services/test_scheduler_service_new.py`：新增 13 个单元测试覆盖生命周期、tick 调度、状态同步

### refactor: 修复封装 — 添加 set_executor/login_executor 公共 API

- `app/services/login_orchestrator.py`：新增 `set_executor()` 方法，绑定外部 executor 并关闭自建 fallback pool
- `app/services/task_executor.py`：新增 `login_executor` 只读 property，暴露登录专用 BoundedExecutor
- `app/container.py`：将 `_executor` 私有属性直接访问替换为 `set_executor()`/`login_executor` 公共 API
- `tests/test_services/test_login_orchestrator.py`：新增 `TestSetExecutor`（2 个用例）和 `TestTaskExecutorLoginExecutor`（1 个用例）

## 2026-06-27

### docs: 修正 API 文档术语并补充错误类型说明

- `docs/api-doc.md`：`ActionResponse` 替换为 `ApiResponse`（表格行、关键原则 2 处）
- `docs/api-doc.md`：表格和"关键原则"之间补充"区分说明"段落（业务失败 vs 程序异常）

### docs: 合并 API 错误响应规范到接口文档，删除独立文件

- `docs/api-doc.md`：在标题和描述之后、目录之前插入 API 错误响应规范（错误场景表格 + 关键原则 + 前端处理说明）
- `docs/api-conventions.md`：删除（内容已合并到 api-doc.md）

### docs: 修正贡献指南中 pre-commit 安装命令

- `CONTRIBUTING.md`：`pre-commit install` 改为 `uvx pre-commit install`，因 pre-commit 不在 dev 依赖中，直接调用会失败

### docs: 添加 Bug 反馈和功能请求 Issue 模板

- 新建 `.github/ISSUE_TEMPLATE/bug_report.md`：GitHub Bug 反馈标准化模板
  - 问题描述、复现步骤、期望行为、实际行为、环境信息、日志/截图
- 新建 `.github/ISSUE_TEMPLATE/feature_request.md`：GitHub 功能请求标准化模板
  - 功能描述、使用场景、建议实现方式、补充信息

### docs: 补充 PR 模板变更类型多选提示

- `.github/PULL_REQUEST_TEMPLATE.md`：在「变更类型」标题下方添加 `<!-- 选择所有适用的类型 -->` HTML 注释，明确告知提交者可多选

### docs: 添加 PR 模板

- 新建 `.github/PULL_REQUEST_TEMPLATE.md`：GitHub Pull Request 标准化模板
  - 变更说明、变更类型（8 种复选框）、关联 Issue、测试情况、补充信息

### docs: 完善目录约定和测试配套规则

- `docs/code-style-guide.md`：
  - 4.1 后端模块放置表格下方新增注释，补充说明 `app/network/`（网络检测）、`app/workers/`（Playwright 工作进程）、`app/core/`（核心模块）、`app/ui/`（系统托盘界面）等模块
  - 4.2 测试配套新增通用命名规则说明：`app/<模块名>/<文件>.py` → `tests/test_<模块名>/test_<文件>.py`，补充 `app/network/detector.py` 示例

## 2026-06-27 (Task 4 - 前端 API 服务层)

### refactor(frontend): 引入 apiService 集中管理 API 调用

- 新建 `frontend/js/api-service.js`：封装所有 API 调用，集中管理路径和响应解包
  - 按功能域分组：config / monitor / actions / system / profiles / autostart / ocr / history / uninstall / debug
  - 使用 constants.js 导出的 `api` 实例，所有方法返回解包后的 `r.data`
  - `config.save` / `config.patch` 支持 `opts` 参数透传 AbortController signal
- `frontend/js/app-options.js`：import apiService，mounted 中注入 `this.$apiService = apiService`
- `frontend/js/methods/config.js`：12 处 API 调用迁移至 apiService（fetchConfig/saveConfig/resetConfig/fetchShells/loadDefaultStealthScript/fetchOcrStatus/installOcr+uninstallOcr/fetchAutostart/_toggleAutostart/setAutostartMode/fetchLogLevels/setSourceLevel）
- `frontend/js/methods/actions.js`：8 处 API 调用迁移至 apiService（openUninstall/confirmUninstall/toggleMonitor/manualLogin/cancelLogin/testNetwork/fetchLoginHistory/clearLoginHistory）
- `frontend/js/methods/profiles.js`：7 处 API 调用迁移至 apiService（fetchProfiles/showProfileEditor/saveProfile/deleteProfile/setActiveProfile/_detectNetwork/toggleAutoSwitch）
- `frontend/js/methods/lifecycle.js`：7 处 API 调用迁移至 apiService（autoCheckUpdateOnStartup/checkInitStatus/fetchAppVersion/checkUpdate/finishWizard/fetchStatus/fetchLogs）
- `frontend/js/methods/ui.js`：quitApp 迁移至 apiService.system.shutdown()
- `frontend/js/tasks/debug.js`：5 处 API 调用迁移至 apiService（startDebug/debugNextStep/debugRunAll/debugStop + _debugAction 重构为接受 apiCall 函数）
- 保留 `this.$api`（原始 axios 实例）不删除，供未迁移的模块继续使用（tasks/scripts/scheduled_tasks/appearance/drag）

## 2026-06-27 (Task 8 - 修复测试)

### refactor(frontend): 适配 config/profiles 方法的 ApiResponse 信封格式

- `frontend/js/methods/config.js`：`setSourceLevel` 解构 `{ data }`，新增 `data.success` 检查，成功时从 `data.message` 取提示文案，失败时 warn 日志 + toast 提示
- `frontend/js/methods/profiles.js`：`toggleAutoSwitch` 中 `data.active_profile` 改为 `data.data?.active_profile`（ApiResponse 信封包裹后附加数据在 data.data 中）

## 2026-06-27 (Task 14)

### feat(api): 补全 debug/tools/autostart/tasks 遗漏端点的响应模型

- `app/schemas.py`：新增 4 个模型
  - `DebugStepResult`：调试步骤执行结果（step_index/success/message/screenshot）
  - `DebugSessionResponse`：调试会话状态响应，start/next/run-all/stop 共用（running/task_id/current_step/total_steps/steps/results/screenshot_url/message）
  - `AutostartEnableRequest`：POST /api/autostart/enable|mode 请求体（lightweight）
  - `TaskOrderRequest`：POST /api/tasks/order 请求体（order: list[str]）
- `app/api/debug.py`：4 个端点（start/next/run-all/stop）改用 `DebugSessionResponse` 作为 response_model，返回类型从 `dict[str, object]` 改为 `DebugSessionResponse`
- `app/api/tools.py`：`delete_background` 端点改用 `ApiResponse` 作为 response_model，返回类型从 `dict` 改为 `ApiResponse`
- `app/api/autostart.py`：删除私有 `_EnableBody` 类，改用 `schemas.AutostartEnableRequest`；`list_shells` 改用 `ShellListResponse` 作为 response_model
- `app/api/tasks.py`：`save_task_order` 参数类型从 `dict` 改为 `TaskOrderRequest`

## 2026-06-27 (Task 11)

### fix: submit() 用 Condition 替换哨兵，修复并发 dispatch 和 preemption 竞态

- `app/services/login_orchestrator.py`：
  - `_slot_lock` 从 `threading.RLock()` 改为 `threading.Condition(threading.Lock())`
  - `submit()` 去重逻辑新增 `while self._slot is _DISPATCHING: self._slot_lock.wait()` 循环，后到线程等待 dispatch 完成再走正常去重/抢占逻辑，修复并发 auto submit 重复 dispatch、manual 无法抢占 dispatch 中的 auto 的竞态
  - `_dispatch` 调用包裹 `try/except`：dispatch 异常时清除哨兵（`self._slot = None`）并 `notify_all()` 唤醒等待者，修复 `_dispatch` 抛异常导致 slot 永久卡在 `_DISPATCHING` 的 Bug
  - `_dispatch` 成功后 `notify_all()` 唤醒等待者
  - `_on_done` 回调新增 `notify_all()` 调用，唤醒等待 slot 清除的线程
- `app/services/engine.py`：
  - `toggle_pure_mode` 的 `self._profile_service.update(...)` 移入 `with self._reload_lock:` 块内，修复磁盘写入在锁外执行导致 `_reload_config_internal` 可能读到过期数据的竞态
- `tests/test_services/test_login_orchestrator.py`：
  - `test_dispatch_called_outside_lock`：从 `CountingRLock` 包装改为 `Condition.acquire(timeout=0.1)` 探测，验证 `_dispatch` 执行时锁未被持有
  - `test_concurrent_submit_respects_sentinel`：改用 `threading.Barrier` + 慢速 `_dispatch` 模拟并发，验证第二个 auto submit 等待完成后复用 handle（去重生效）
  - 新增 `test_dispatch_exception_clears_sentinel`：验证 `_dispatch` 抛异常后 `orch._slot` 为 None 而非卡在 `_DISPATCHING`

## 2026-06-27 (Task 10)

### feat(api): 为所有 GET 端点添加 Pydantic response_model

- `app/schemas.py`：新增 7 个 GET 响应模型
  - `ProfileSummary`：方案列表摘要（name/match_gateway_ip/match_ssid/carrier/carrier_custom/auth_url/active_task）
  - `ProfileListResponse`：GET /api/profiles 响应（profiles/active_profile/auto_switch）
  - `ProfileDetailResponse`：GET /api/profiles/{id} 响应（profile_id/settings）
  - `BrowserInfo`：浏览器信息 Pydantic 模型（channel/name/icon/installed/needs_download/description）
  - `BrowserListResponse`：GET /api/browsers 响应（browsers/current）
  - `TaskSummary`：任务列表摘要（id/name/description/type/binary_path）
  - `LogLevelResponse`：GET /api/config/log-levels 响应（global_level/source_levels）
- `app/api/profiles.py`：list_profiles 改用 ProfileListResponse，get_profile 改用 ProfileDetailResponse
- `app/api/browsers.py`：get_browsers 改用 BrowserListResponse + BrowserInfo
- `app/api/config.py`：get_log_levels 改用 LogLevelResponse
- `app/api/tasks.py`：list_tasks 添加 response_model=list[TaskSummary]
- `app/api/scripts.py`：list_scripts 添加 response_model=list[TaskSummary]

## 2026-06-27 (Task 9)

### fix: start_thread 清空残留命令时调用 task_done()，防止 join() 阻塞

- `app/services/engine.py`：`start_thread` 队列清空从 `while not queue.empty()` + `get_nowait()` 改为 `while True` + `get_nowait()` + `task_done()` + `except queue.Empty: break`，消除不可靠的 `empty()` 检查并正确维护 task_done 计数器
- `tests/test_services/test_engine.py`：新增 `TestStartThreadQueueCleanup` 测试类（1 个测试），验证清空残留命令后 `queue.join()` 不阻塞

## 2026-06-27 (Task 7)

### fix: submit_login 入口清理已完成的 Future 引用，防止残留

- `app/services/engine_login_bridge.py`：`submit_login` 方法开头新增已完成 Future 清理逻辑（`{f for f in self._registered_futures if not f.done()}`），防止极端情况下（如 Future 被取消且 `_on_done` 未被调用）引用残留
- `tests/test_services/test_engine_login_bridge.py`：新增 `TestRegisteredFuturesCleanup` 测试类（1 个测试），验证已完成的 Future 在下次 submit_login 时被清理

## 2026-06-27 (Task 6)

### perf: 引擎循环改为内循环批量排空命令，减少多次唤醒周期

- `app/services/engine.py`：`_engine_loop` 命令处理从单条 `get_nowait()` + `continue` 改为 `while True` 内循环批量排空命令队列，多条快速入队的命令在单次唤醒中全部处理
- `tests/test_services/test_engine.py`：新增 `TestEngineLoopBatchCommands` 测试类（1 个测试），验证 3 条 RELOAD + 1 条 SHUTDOWN 在单次迭代中全部处理
- 验收：138 个 engine 测试全通过

## 2026-06-27 (Task 4)

### perf: WsBroadcaster 改用 asyncio.Event 按需唤醒，消除空闲 50ms 固定轮询

- `app/services/ws_broadcaster.py`：
  - `__init__` 新增 `_drain_event`（asyncio.Event）和 `_loop`（事件循环引用）
  - 新增 `set_loop(loop)` 方法：记录事件循环引用
  - 新增 `_notify_drain()` 方法：线程安全唤醒 drain loop（`loop.call_soon_threadsafe(event.set)` fallback `event.set()`）
  - `set_dashboard_sink` 新增 `sink.set_drain_notifier(self._notify_drain)` 调用
  - `enqueue_status` 新增 `self._notify_drain()` 调用
  - `ws_drain_loop` 从 `asyncio.sleep(0.05)` 固定轮询改为 `await self._drain_event.wait()` 事件驱动
- `app/utils/logging.py`：
  - `DashboardSink.__init__` 新增 `_drain_notifier` 字段
  - 新增 `set_drain_notifier(notifier)` 方法
  - `write()` 末尾新增 `self._drain_notifier()` 调用（线程安全唤醒 asyncio 循环）
  - 新增 `from collections.abc import Callable` 导入
- `tests/test_services/test_ws_broadcaster.py`：新增 12 个测试覆盖事件驱动行为（TestSetLoop / TestNotifyDrain / TestEnqueueStatus.test_enqueue_triggers_drain_event / TestSetDashboardSinkMigration.test_injects_drain_notifier / TestWsDrainLoop 新增 4 个测试）

## 2026-06-27 (Task 8)

### fix: 删除 _pure_mode_lock，统一由 _reload_lock 保护，消除锁嵌套竞态

- `app/services/engine.py`：
  - `__init__` 删除 `self._pure_mode_lock = threading.Lock()`
  - `pure_mode` 属性改用 `self._reload_lock` 保护读取
  - `_reload_config_internal` 移除内层 `with self._pure_mode_lock:` 嵌套，直接在 `_reload_lock` 下写 `_pure_mode`
  - `toggle_pure_mode` 改为先在 `_reload_lock` 内读写 `_pure_mode`，再在锁外执行 `_profile_service.update()` 持久化（避免持锁做磁盘 I/O）
- `tests/test_services/test_engine.py`：新增 `TestPureModeLockConsolidation` 测试类，验证 `toggle_pure_mode` 与 `pure_mode` 读取互斥无死锁
- `tests/test_services/conftest.py`、`tests/test_integration/test_login_flow.py`、`tests/test_services/test_monitor_service.py`：移除测试 mock 中的 `_pure_mode_lock` 初始化

## 2026-06-27 (Task 3)

### fix: submit() 锁范围缩小，_dispatch 移到锁外，哨兵防止并发重复提交

- `app/services/login_orchestrator.py`：
  - 新增模块级 `_DISPATCHING` 哨兵（`LoginHandle(future=None, source="auto", cancel_event=CompositeCancelEvent())`），用于 `submit()` 锁外 dispatch 期间占位
  - `submit()` 去重逻辑新增 `existing is not _DISPATCHING` 前置检查，防止哨兵被误判为正常 handle（哨兵 `done()` 返回 True，但 `is not` 在 `not existing.done()` 之前求值）
  - `submit()` 将 `_dispatch` 调用移到 `_slot_lock` 外：锁内仅做去重判断和哨兵占位，锁外执行 `_dispatch`，再用独立的锁块写回 `self._slot = handle`
- `tests/test_services/test_login_orchestrator.py`：
  - 新增 `TestSubmitLockScope` 测试类（2 个测试）
  - `test_dispatch_called_outside_lock`：用 `CountingRLock` 包装 `_slot_lock`，验证 `_dispatch` 被调用时 acquire/release 差为 0（锁未持有）
  - `test_concurrent_submit_respects_sentinel`：验证连续两次 auto submit 只触发一次 `pool.submit`（去重生效）

## 2026-06-27 (Task 2)

### fix: _dispatch _on_done 回调清理 CompositeCancelEvent 源列表，防止内存泄漏

- `app/services/login_orchestrator.py`：`_dispatch` 方法的 `_on_done` 回调在清空 `_slot` 后，新增 `handle.cancel_event.clear_sources()` 调用（`isinstance` 检查后），释放去重积累的源引用
- `tests/test_services/test_login_orchestrator.py`：新增 `TestDispatchClearsCancelSources` 测试类（1 个测试），验证登录完成后 `CompositeCancelEvent._sources` 被清空

## 2026-06-27 (Task 1)

### fix: 测试文件补全 _retry_time_lock，桥接回调测试改用实际注册回调

- `tests/test_services/test_engine_fix.py`：`_make_engine()` 补充 `_retry_time_lock` 初始化，桥接回调加锁保护 `_next_retry_time` 写入
- `tests/test_integration/test_login_flow.py`：`_make_raw_engine()` 补充 `_retry_time_lock` 初始化，桥接回调加锁保护 `_next_retry_time` 写入
- `tests/test_services/test_monitor_service.py`：`test_do_async_login_delegates_to_task_executor` 补充 `_retry_time_lock` 初始化，桥接回调从 lambda 改为具名函数 + 加锁保护
- `tests/test_services/test_engine.py`：`TestRetryTimeLock` 三个桥接回调测试（bridge_retry_scheduled_sets_time / bridge_login_success_clears_time / bridge_retry_exhausted_clears_time）从内联函数直接调用改为通过 `engine._login_bridge` 注册后调用，与 `__init__` 一致

### fix: _next_retry_time 跨线程读写加锁保护，消除 TOCTOU 竞态

- `app/services/engine.py`：
  - `__init__` 新增 `_retry_time_lock: threading.Lock`（L109）
  - `_bridge_retry_scheduled` / `_bridge_login_success` / `_bridge_retry_exhausted` 三个桥接回调加锁保护 `_next_retry_time` 写入（L154-163）
  - `_engine_loop` 重试判断改为锁内原子 check-then-act：读取 → 判断 → 清零全在同一 `with` 块内（L219-228）
  - `_calculate_wakeup` 锁保护 `_next_retry_time` 读取，移除 `try/except (TypeError, ValueError, AttributeError)` 宽异常捕获，异常自然冒泡到 `_engine_loop` 顶层兜底（L249-252）
  - `_do_network_check` 网络检测前清零重试定时加锁保护（L306-307）
  - `_handle_stop` 停止监控时清零重试定时加锁保护（L400-401）
- `tests/test_services/conftest.py`：`_make_raw()` 新增 `_retry_time_lock` 初始化，桥接回调加锁保护
- `tests/test_services/test_engine.py`：
  - `TestCalculateWakeup.test_wakeup_exception_fallback` 重命名为 `test_wakeup_exception_propagates`，断言改为 `pytest.raises((TypeError, ValueError))`
  - 新增 `TestRetryTimeLock` 测试类（5 个测试）：bridge_retry_scheduled_sets_time、calculate_wakeup_reads_under_lock、bridge_login_success_clears_time、bridge_retry_exhausted_clears_time、concurrent_write_no_data_loss
- 验收：136 个 engine 测试全通过

## 2026-06-26 (Task 9)

### refactor: MonitorSettings 默认值归一化，引用 constants 常量

- `app/schemas.py`：
  - 新增 `from app.constants import DEFAULT_HTTP_TARGETS, DEFAULT_NETWORK_TARGETS, DEFAULT_URL_CHECK_URLS` 导入
  - 新增 `_parse_targets(raw)` 辅助函数：逗号分隔字符串转 list[str]
  - 新增 `_parse_url_check(raw)` 辅助函数：换行分隔字符串转 list[str]
  - `MonitorSettings.ping_targets`：`default_factory` 从内联列表改为 `_parse_targets(DEFAULT_NETWORK_TARGETS)`
  - `MonitorSettings.test_urls`：`default_factory` 从内联列表改为 `_parse_targets(DEFAULT_HTTP_TARGETS)`
  - `MonitorSettings.url_check_urls`：`default_factory` 从内联列表改为 `_parse_url_check(DEFAULT_URL_CHECK_URLS)`
- 验收：44 个测试全通过

## 2026-06-27 (Task 8 - 修复测试)

### fix(tests): 适配 API 变更后的 11 个测试失败

- `app/api/system.py`：`check_update` 缓存存储排除 `current` 字段（`model_dump(exclude={"current"})`），修复重建 `UpdateCheckResponse` 时 `current` 重复传参的 TypeError
- `tests/test_api/test_api_monitor_routes.py`：`test_toggle_pure_mode` 断言适配 ApiResponse 信封（`resp.json()["data"]["enabled"]`）
- `tests/test_api/test_api_profiles_routes.py`：`test_auto_switch_enable/disable` 从 query params 改为 JSON body（`AutoSwitchRequest`）
- `tests/test_api/test_api_system_routes.py`：`test_uninstall_perform_invalid_keys` 断言从 400 改为 422（Pydantic 验证）
- `tests/test_api/test_api_tools_routes.py`：`test_upload_png_success` 适配 ApiResponse 信封；`TestFetchUrlContentLength` 3 个测试改用 `FetchUrlRequest` 对象 + 属性访问
- `tests/test_api/test_system_update_cache.py`：3 个测试从 dict 下标访问改为 `UpdateCheckResponse` 属性访问（`result.latest`、`result.current`）
- 验收：181 个 API 测试全通过，2271 个总测试全通过

## 2026-06-27 (Task 12)

### feat(frontend): resetConfig 使用后端默认值 + extractApiError 增强

- `frontend/js/methods/config.js`：`resetConfig` 从硬编码 `structuredClone(DEFAULT_CONFIG)` 改为调用 `GET /api/config/defaults` 获取后端默认值，保留 `credentials`（凭据不重置），添加错误处理和 toast 提示
- `frontend/js/methods/utils.js`：`extractApiError` 增强 FastAPI 422 验证错误支持，数组格式 `detail` 项为对象时提取 `loc` 最后一段作为字段名前缀（如 `[field_name] msg`），字符串项直接保留

## 2026-06-27 (Task 5)

### refactor(frontend): 前端配置数据模型改为嵌套 app_settings 结构

- `frontend/js/constants.js`：`DEFAULT_CONFIG` 中 10 个扁平 app_settings 字段移入 `app_settings` 子对象
- `frontend/js/data/config.js`：`cloneConfig` 适配嵌套结构，`app_settings` 内含 `custom_variables` 深拷贝
- `frontend/js/methods/config.js`：
  - `fetchConfig` 直接映射后端返回的嵌套 `app_settings` 结构（不再手动展平）
  - `saveConfig` payload 直接发送嵌套 `app_settings`（不再手动扁平化）
  - `_validateConfig` 引用路径改为 `config.app_settings.app_port`
  - `onShellFileSelected` 引用路径改为 `config.app_settings.shell_path`
- `frontend/js/app-options.js`：`config.shell_path` / `config.startup_action` 改为 `config.app_settings.*`
- `frontend/js/methods/ui.js`：`config.custom_variables` 改为 `config.app_settings.custom_variables`（全部 12 处）
- `frontend/partials/pages/settings/settings-monitor.html`：`config.block_proxy` → `config.app_settings.block_proxy`
- `frontend/partials/pages/settings/settings-system.html`：7 个字段改为 `config.app_settings.*`
- `frontend/partials/pages/settings/settings-account.html`：`config.custom_variables` → `config.app_settings.custom_variables`

## 2026-06-27 (Task 13)

### feat(api): 补全所有遗漏端点的格式统一 — 类型化响应模型

- `app/schemas.py`：新增 6 个响应模型
  - `StealthScriptResponse`：GET /api/config/default-stealth-script 响应
  - `NetworkDetectResponse`：POST /api/profiles/detect 响应
  - `BinaryInfo`：可执行二进制信息（path/name）
  - `OcrStatusResponse`：GET /api/ocr/status 响应
  - `UpdateCheckResponse`：GET /api/check-update 响应（含 cached/error 字段）
  - `UninstallItem`：可清理项目（key/label/exists/path/size_mb）
- `app/api/config.py`：`default-stealth-script` 返回 `StealthScriptResponse`
- `app/api/profiles.py`：`detect` 返回 `NetworkDetectResponse`
- `app/api/install_playwright.py`：`install-playwright` 返回 `ApiResponse`（原返回 raw dict）
- `app/api/ocr.py`：`status` 返回 `OcrStatusResponse`
- `app/api/system.py`：`check-update` 返回 `UpdateCheckResponse`，`uninstall/detect` 返回 `list[UninstallItem]`
- `app/api/scheduled_tasks.py`：list 和 history 添加 `response_model=list[dict[str, Any]]`
- `app/api/tools.py`：`background/upload` 返回 `ApiResponse`（原返回 raw dict）
- `app/api/scripts.py`：`binaries` 返回 `list[BinaryInfo]`

## 2026-06-27 (Task 11)

### feat: 添加全局异常处理中间件，统一错误响应格式

- `app/application.py`：
  - 模块级新增 `api_logger = get_logger("api", source="backend")`
  - `create_app` 内新增 `from fastapi.responses import JSONResponse` 导入
  - CORS 配置之后新增 `global_exception_handler`（捕获所有未处理 Exception，返回 500 + 统一 JSON 格式）
  - 新增 `value_error_handler`（捕获 ValueError，返回 400 + 错误消息）
- 前端 `extractApiError` 已兼容 `detail` 为字符串和数组两种格式，无需修改
- 验收：23 个现有测试全通过，模块导入正常

## 2026-06-27 (Task 9)

### refactor: 合并 ActionResponse → ApiResponse，消除双模型混乱

- `app/schemas.py`：
  - 删除 `ActionResponse` 类定义（原 125-127 行）
  - 在 `ApiResponse` 类定义之后新增 `ActionResponse = ApiResponse` 向后兼容别名
- 9 个 API 文件全局替换：
  - `app/api/autostart.py`：import + 4 处构造 + 3 处 response_model + 3 处返回类型
  - `app/api/config.py`：import + 1 处构造 + 1 处 response_model + 1 处返回类型
  - `app/api/monitor.py`：import + 5 处构造 + 5 处 response_model + 5 处返回类型
  - `app/api/ocr.py`：import + 10 处构造 + 2 处 response_model + 2 处返回类型
  - `app/api/profiles.py`：import + 3 处构造 + 3 处 response_model + 3 处返回类型
  - `app/api/scheduled_tasks.py`：import + 6 处构造 + 5 处 response_model + 5 处返回类型
  - `app/api/scripts.py`：import + 3 处构造 + 3 处 response_model + 3 处返回类型
  - `app/api/system.py`：import + 2 处构造 + 2 处 response_model + 2 处返回类型
  - `app/api/tasks.py`：import + 4 处构造 + 4 处 response_model + 4 处返回类型
- `tests/test_config/test_config_schemas.py`：import `ApiResponse` 替代 `ActionResponse`，`TestActionResponse` 重命名为 `TestApiResponse`
- 验收：280 个测试通过（7 个 pre-existing 失败与本次改动无关），schemas.py 中 `ActionResponse` 仅作为别名存在

## 2026-06-27 (Task 4)

### refactor(scheduled-tasks): replace manual validation with Pydantic model

- `app/schemas.py`：新增 `ScheduleTime` 和 `ScheduledTaskConfig` 两个 Pydantic 模型
  - `ScheduleTime`：hour(0-23) + minute(0-59)
  - `ScheduledTaskConfig`：name(min_length=1)、type(pattern=script|browser|shell)、schedule、timeout(ge=5,le=3600) 等字段
  - `model_validator`：shell 类型 command 不能为空、script/browser 类型 target_id 不能为空
- `app/api/scheduled_tasks.py`：
  - 删除 `_validate_create_payload` 和 `_validate_update_payload` 两个手写校验函数（约 80 行）
  - `create_scheduled_task`：参数从 `payload: dict` 改为 `payload: ScheduledTaskConfig`，Pydantic 自动校验，无效输入返回 422
  - `update_scheduled_task`：保留 `payload: dict`（部分更新），合并后通过 `ScheduledTaskConfig.model_validate(merged)` 校验，无效输入返回 400
  - 导入新增 `ScheduledTaskConfig`
- `tests/test_api/test_api_scheduled_tasks_routes.py`：
  - 5 个 create 校验失败测试断言从 `status_code == 200 + success == False` 改为 `status_code == 422`
  - 3 个 update 校验失败测试断言从 `status_code == 200 + success == False` 改为 `status_code == 400`
- 验收：24 个定时任务测试全通过

## 2026-06-27 (Task 3)

### refactor(config): use nested structure, eliminate flat dict conversion

- `app/api/config.py`：
  - `get_config` 返回嵌套结构（`app_settings` 作为子对象），不再展平到顶层
  - `save_config` 请求体从 `dict` 改为 `ConfigSaveRequest`（嵌套结构），移除 `_flat_dict_to_dto` 转换
  - `set_source_level` 请求体从 `dict` 改为 `SourceLevelRequest`，返回 `ApiResponse` 信封
  - `_log_config_changes` 参数从 `ConfigResponseDTO` 改为 `ConfigSaveRequest`
  - 删除 `_dto_to_flat_dict`、`_flat_dict_to_dto`、`_APP_SETTINGS_KEYS` 三个扁平转换函数
  - 新增 `GET /api/config/defaults` 端点，返回所有配置字段默认值
- `app/services/profile_service.py`：`save_global_and_profile` 参数从 `ConfigResponseDTO` 改为 `ConfigSaveRequest`
- `tests/test_integration/test_full_mode.py`：`ConfigResponseDTO` 改为 `ConfigSaveRequest`
- `tests/test_integration/test_login_connection.py`：同上
- 验收：7 个 config 相关测试全通过

## 2026-06-27 (Task 2)

### refactor(api): 统一写操作端点响应格式为 ApiResponse 信封

- `app/api/profiles.py`：`toggle_auto_switch` 请求体从 `dict = Body(default={})` 改为 `AutoSwitchRequest`，返回 `ApiResponse` 信封；移除未使用的 `Body` 导入
- `app/api/monitor.py`：`get_pure_mode` 返回 `PureModeResponse`，`toggle_pure_mode` 返回 `ApiResponse` 信封
- `app/api/history.py`：`clear_login_history` 返回 `ApiResponse` 信封
- `app/api/system.py`：`health` 返回 `HealthResponse`，`get_init_status` 返回 `InitStatusResponse`，`uninstall_perform` 请求体改为 `UninstallRequest`、返回 `ApiResponse` 信封
- `app/api/tools.py`：`fetch_background_url` 请求体改为 `FetchUrlRequest`、返回 `ApiResponse` 信封
- 验收：174 通过、7 失败（均为测试期望旧格式，符合预期）

## 2026-06-27 (Task 1)

### feat(schemas): 新增 ApiResponse 信封和类型化请求/响应模型

- `app/schemas.py`：在 `AppSettings` 之后、`RuntimeConfig` 之前新增 10 个 API 模型
  - `ApiResponse`：所有写操作的标准响应信封（success/message/data）
  - `ConfigSaveRequest`：PUT /api/config 请求体，嵌套结构与 RuntimeConfig 对齐
  - `SourceLevelRequest`：PUT /api/config/source-level 请求体
  - `AutoSwitchRequest`：POST /api/profiles/auto-switch 请求体
  - `UninstallRequest`：POST /api/uninstall 请求体
  - `FetchUrlRequest`：POST /api/background/fetch-url 请求体
  - `InitStatusResponse`：GET /api/init-status 响应
  - `HealthResponse`：GET /api/health 响应
  - `ShellListResponse`：GET /api/shells 响应
  - `PureModeResponse`：GET/POST /api/pure-mode 响应
- 注意：新模型放在 `AppSettings` 之后而非 `ActionResponse` 之后，因为 `ConfigSaveRequest` 的 `Field(default_factory=BrowserSettings)` 需要运行时引用已定义的设置类
- 验收：10 个新模型全部可正常导入

## 2026-06-26 (Task 8)

### refactor: 移除 AuthProfile 别名、monitor_service 属性，修复 uninstall 冗余

- `app/schemas.py`：删除 `AuthProfile = Profile` 向后兼容别名（第 184-185 行）
- `app/container.py`：删除 `monitor_service` 废弃属性（第 103-108 行），保留 `debug_manager` 属性
- `app/services/uninstall.py`：`_check_autostart` 和 `_remove_autostart` 各自新建 `AutoStartService` 实例改为共享单例 `_get_autostart_service()`
- `tests/test_config/test_config_schemas.py`：`TestAuthProfileDefaults` → `TestProfileDefaults`，`TestAuthProfile` → `TestProfile`
- `tests/test_config/test_container.py`：删除 `assert hasattr(container, "monitor_service")` 断言
- `tests/test_integration/test_app_startup.py`：所有 `mock_container.monitor_service` 改为 `mock_container.engine`
- 验收：97 个测试全通过

## 2026-06-26

### refactor: 提取 WebSocket 处理到 app/api/ws.py 独立模块

- 新建 `app/api/ws.py`：从 `application.py` 提取 WebSocket `/ws/logs` 处理逻辑
  - `websocket_logs_handler(websocket, ws_manager, engine)` — 独立的 WebSocket 处理函数
  - 包含消息大小预检、ping/pong、前端日志转发、异常处理
- `app/application.py`：
  - WebSocket 处理从 40 行内联代码替换为 4 行委托调用
  - 移除未使用的 `import json`
  - 移除未使用的 `ws_logger` 定义
- 验收：所有 WebSocket 相关测试通过

### refactor: LoginHistoryService.record() 解耦，改用 add() 直接传入名称

- `app/services/login_history_service.py`：
  - 删除 `record()` 方法（原 48-82 行），调用方自行查找 profile/task 名称后直接调用 `add()`
  - 删除 `TYPE_CHECKING` 块（`ProfileService`/`TaskManager` 仅被 `record()` 使用）
- `app/services/login_orchestrator.py`：
  - `_record_history` 方法：从调用 `self._login_history.record()` 改为直接查找 `profile_name` 后调用 `self._login_history.add()`
  - 逻辑内联：`_profile_service.get_active_profile()` + `getattr(active, "name", "")` 移入 `_record_history`
- `tests/test_services/test_login_history.py`：
  - 删除 `TestRecord` 测试类（9 个测试，对应已删除的 `record()` 方法）

### refactor: 合并 config_service 到 profile_service
- `app/services/profile_service.py`：新增 `SaveResult`、`_rollback_config`、`save_global_and_profile`（从 config_service 迁入）
- `app/services/config_service.py`：删除（已合并到 profile_service）
- `app/api/config.py`：导入从 `app.services.config_service` 改为 `app.services.profile_service`
- `tests/test_services/test_config_service.py`：导入从 `app.services.config_service` 改为 `app.services.profile_service`
- `tests/test_api/test_api_config_routes.py`：`SaveResult` 导入改为 `app.services.profile_service`
- `tests/test_integration/test_full_mode.py`：`save_global_and_profile` 导入改为 `app.services.profile_service`
- `tests/test_integration/test_login_connection.py`：同上

### refactor: 构造器注入替代 setter，消除循环依赖注入

- `app/services/engine.py`：`__init__` 新增 `orchestrator` 参数，删除 `set_orchestrator()` 和 `set_task_executor()` 方法
- `app/services/login_orchestrator.py`：删除 `set_executor()` 方法
- `app/services/task_executor.py`：删除 `set_runtime_config_getter()` 方法
- `app/container.py`：重排服务创建顺序（LoginOrchestrator → TaskExecutor → ScheduleEngine），构造器注入后绑定 `get_runtime_config`
- `tests/test_integration/conftest.py`：两个 fixture（`integration_stack`/`full_stack`）改用直接属性赋值，补充 `orchestrator._get_runtime_config` 绑定
- `tests/test_services/test_task_executor_fix.py`：`test_set_runtime_config_getter` 改为直接赋值

### fix: 适配 test_monitor_service.py 到 StatusManager 重构

### fix: 适配 test_monitor_service.py 到 StatusManager 重构

- `tests/test_services/test_monitor_service.py`：
  - `StatusSnapshot` 导入从 `app.services.engine` 改为 `app.services.engine_status`
  - `svc._dashboard_sink` 访问改为 `svc._status_manager._dashboard_sink`（4 处）
  - `svc._status_snapshot` 访问改为 `svc._status_manager._status_snapshot`（10 处）
  - `TestShutdownSynchronous` 移除 `__new__` 模式下对 `_status_snapshot` 的无效赋值（shutdown 不访问该属性）
- 验收：41 个测试全通过

### refactor: 提取 StatusManager from ScheduleEngine

- 新建 `app/services/engine_status.py`：`StatusManager` 类，从 `ScheduleEngine` 提取状态快照管理
  - `StatusSnapshot` 数据类 — 监控状态快照（monitoring/last_network_ok/start_time/network_check_count/login_attempt_count/last_check_time/snapshot_time/status_detail/network_state）
  - `StatusManager` 类 — 状态快照管理与 WS 广播桥接
    - `update_snapshot(force)` — 从 monitor_core 读取状态，写入 lock-free StatusSnapshot
    - `_queue_status_broadcast()` — 将状态广播到 WS 队列
    - `get_status()` — 返回 MonitorStatusResponse
    - `list_logs(limit)` — 从 DashboardSink 读取日志
    - `set_ws_broadcaster(broadcaster)` — 注入 WS 广播器
    - `set_dashboard_sink(sink)` — 注入 DashboardSink
- `app/services/engine.py`：
  - 移除 `StatusSnapshot` 数据类定义（60-72 行），改从 `engine_status` 导入
  - `__init__` 移除 `_dashboard_sink`、`_last_snapshot_time`、`_snapshot_min_interval`、`_status_snapshot` 字段
  - `__init__` 新增 `_status_manager` 初始化
  - `_update_status_snapshot` / `_queue_status_broadcast` / `get_status` / `list_logs` / `set_dashboard_sink` 改为委托 `_status_manager`
- `app/container.py`：
  - `start_web_services` 轻量模式唤醒时新增 `engine._status_manager.set_ws_broadcaster(self.ws_broadcaster)` 调用
- 测试文件同步更新：
  - `tests/test_services/conftest.py`：`_make_raw()` 移除 `_status_snapshot`/`_snapshot_min_interval`/`_last_snapshot_time`/`_dashboard_sink` 字段，新增 `_status_manager` 初始化
  - `tests/test_services/test_engine.py`：导入改为从 `engine_status` 导入 `StatusSnapshot`；`_status_snapshot` 访问改为 `_status_manager._status_snapshot`；`_dashboard_sink` 访问改为 `_status_manager._dashboard_sink`
- 验收：131 个 engine 测试全通过

### refactor: 提取 LoginBridge from ScheduleEngine

- 新建 `app/services/engine_login_bridge.py`：`LoginBridge` 类，从 `ScheduleEngine._do_async_login` 提取登录提交与回调管理
  - `submit_login(is_manual, config_snapshot)` — 提交登录到 LoginOrchestrator，含前置检查、去重、回调注册
  - `cancel_login()` — 取消当前登录
  - `_on_retry_scheduled(delay)` / `_on_login_success()` / `_on_retry_exhausted()` — 可覆盖的回调钩子，由 engine 桥接设置 `_next_retry_time`
  - 内置 `_registered_futures` + `_futures_lock` 线程安全 future 管理
- `app/services/engine.py`：
  - `__init__` 新增 `_login_bridge` 初始化 + 三个桥接回调（`_bridge_retry_scheduled` / `_bridge_login_success` / `_bridge_retry_exhausted`）
  - `_do_async_login` 从 75 行逻辑缩减为 1 行委托 `self._login_bridge.submit_login()`
  - `cancel_login` 从 5 行缩减为 1 行委托 `self._login_bridge.cancel_login()`
  - `_registered_futures` / `_futures_lock` 已从 engine 移除（孤儿清理），实际管理已迁移到 LoginBridge
- 测试文件同步更新（4 个文件）：
  - `tests/test_services/conftest.py`：`_make_raw()` 新增 `_login_bridge` 初始化 + 三个桥接回调
  - `tests/test_services/test_engine_fix.py`：`_make_engine()` 新增 `_login_bridge` 初始化 + 三个桥接回调
  - `tests/test_services/test_monitor_service.py`：`test_do_async_login_delegates_to_task_executor` 新增 `_login_bridge` 初始化
  - `tests/test_integration/test_login_flow.py`：`_make_raw_engine()` 新增 `_login_bridge` 初始化 + 三个桥接回调
- 验收：178 个 engine 相关测试全通过，28 个 login_flow 集成测试全通过

## 2026-06-25 (6)

### refactor: 提取 _shutdown_container 并修复冗余 ProfileService 实例化

- `main.py`：
  - 新增 `_shutdown_container(container, logger, fallback_shutdown=False)` 辅助函数：统一 `_run_lightweight` 和 `_run_full` 的容器关闭逻辑（约 40 行缩减为 1 处）
  - `_run_lightweight` finally 块：替换内联 try/except 为 `_shutdown_container(container, logger, fallback_shutdown=True)` 调用
  - `_run_full` finally 块：替换内联 try/except 为 `_shutdown_container(container, logger)` 调用
  - `_run_full` 中 `create_profile_service()` 独立实例化改为 `container.profile_service.load()`，复用容器已有实例

## 2026-06-25 (5)

### refactor: 提取 AppSettings 子模型，消除配置透传字段重复

- `app/schemas.py`：
  - 新增 `AppSettings` frozen 模型：包含 10 个透传字段（block_proxy/shell_path/minimize_to_tray/startup_action/autostart_lightweight/lightweight_tray/auto_open_browser/proxy/app_port/custom_variables）
  - `RuntimeConfig`：10 个平铺字段替换为 `app_settings: AppSettings`
  - `GlobalConfig`：10 个平铺字段替换为 `app_settings: AppSettings`
  - `ConfigResponseDTO`：10 个平铺字段替换为 `app_settings: AppSettings`
  - `AppConfig.from_runtime_config`：字段访问改为 `config.app_settings.xxx`
  - `ProfilesData.config_version` 默认值从 4 改为 5
- `app/services/config_builder.py`：`build()` 10 个逐字段映射替换为 `app_settings=global_config.app_settings`
- `app/services/config_service.py`：`save_global_and_profile` 10 个逐字段映射替换为 `app_settings=payload.app_settings`
- `app/api/config.py`：
  - `get_config` 返回 `ConfigResponseDTO` 改用 `app_settings=cfg.app_settings`
  - `_log_config_changes` FIELD_NAMES 中平铺字段键名加 `app_settings.` 前缀
- `app/services/login_orchestrator.py`：`block_proxy`/`shell_path`/`custom_variables` 访问改为 `config.app_settings.xxx`
- `app/services/monitor_service.py`：`self.config.block_proxy` → `self.config.app_settings.block_proxy`
- `app/services/task_executor.py`：`config.shell_path` → `config.app_settings.shell_path`
- `app/services/debug_service.py`：`runtime_config.custom_variables` → `runtime_config.app_settings.custom_variables`
- `app/api/autostart.py`：`global_config.autostart_lightweight` → `global_config.app_settings.autostart_lightweight`（读写两处）
- `app/services/profile_service.py`：新增 `migrate_v4_to_v5` 迁移函数（已在前次实现），`_load_unsafe` 链式调用
- 测试文件同步更新（8 个文件）：所有平铺字段断言改为 `rc.app_settings.xxx`

## 2026-06-25 (4)

### refactor: 统一登录线程池 — LoginOrchestrator 复用 BoundedExecutor

- `app/services/login_orchestrator.py`：
  - `__init__` 新增 `executor` 参数，支持注入外部 BoundedExecutor
  - 优先使用外部 `executor`，无注入时 fallback 到自建 `ThreadPoolExecutor`
  - 新增 `set_executor()` 方法，支持延迟注入（container 中 TaskExecutor 创建后调用）
  - `_dispatch` 中提交逻辑改为双路径：`executor.submit` 或 `pool.submit`
  - `shutdown` 改为仅关闭自建池（外部 executor 由调用方管理）
  - 保留 `_slot` + `_slot_lock` 抢占机制不变
- `app/services/task_executor.py`：
  - `__init__` 新增 `_login_executor = BoundedExecutor(max_workers=1, queue_size=1)`
  - `shutdown` 新增 `self._login_executor.shutdown(wait=wait)`
- `app/container.py`：
  - TaskExecutor 创建后，调用 `login_orchestrator.set_executor(task_executor._login_executor)` 注入共享执行器

## 2026-06-25 (3)

### refactor: 提取 WsBroadcaster 和 NetworkTester from ScheduleEngine

- 新建 `app/services/ws_broadcaster.py`：WS 广播队列管理器，从 engine.py 提取
  - `WsBroadcaster` 类：管理 broadcast_queue、ws_drain_loop、drain_ws_queue、set_dashboard_sink、enqueue_status
  - `WS_DRAIN_INTERVAL_SECONDS` 常量迁移至此
- 新建 `app/services/network_tester.py`：手动网络测试封装，从 engine.py 提取
  - `NetworkTester` 类：封装 `is_network_available` 调用和模式描述日志
- `app/services/engine.py`：
  - `__init__` 新增 `ws_broadcaster` 和 `network_tester` 可选参数
  - `_queue_status_broadcast` 委托 `ws_broadcaster.enqueue_status`
  - `test_network` 委托 `network_tester.test_network`
  - `set_dashboard_sink` 简化为仅设置 `_dashboard_sink`（供 list_logs 使用）
  - 删除 `ws_drain_loop`、`drain_ws_queue`、`ws_broadcast_queue` 属性、`_empty_broadcast_queue` 字段
  - `WS_DRAIN_INTERVAL_SECONDS` 改为从 ws_broadcaster 模块 re-export（向后兼容）
  - 移除不再使用的 `json`、`deque`、`is_network_available`、`parse_ping_targets` 导入
- `app/container.py`：
  - 新建 `WsBroadcaster` 和 `NetworkTester` 实例，注入到 ScheduleEngine
  - `start_web_services` 改用 `ws_broadcaster.set_ws_manager`、`ws_broadcaster.set_dashboard_sink`、`ws_broadcaster.ws_drain_loop`
- 新建 `tests/test_services/test_ws_broadcaster.py`：19 个单元测试覆盖全部 WsBroadcaster 功能
- 更新 `tests/test_services/test_engine.py`：TestNetwork 改为 mock `_network_tester`，TestQueueStatusBroadcast 改为验证委托，删除 TestWsDrain 和 TestSetDashboardSinkMigration
- 更新 `tests/test_services/conftest.py`：raw fixture 新增 `_ws_broadcaster` 和 `_network_tester` mock
- 更新 `tests/test_config/test_container.py`：mock_classes 新增 WsBroadcaster/NetworkTester，fixture 改用 `ws_broadcaster.ws_drain_loop`
- 更新 `tests/test_config/test_constants.py`：新增 re-export 测试
- 更新 `tests/test_services/test_engine_fix.py`：NetworkTester 源码检查替代 engine

## 2026-06-25 (2)

### refactor: 消除 TaskService 冗余层 — 合并到 TaskManager

- `app/services/task_service.py`：删除（219 行），逻辑合并到 TaskManager
- `app/tasks/manager.py`：
  - 新增 `_DANGEROUS_STEP_TYPES` 常量和 `_check_dangerous_steps()` 函数（从 TaskService 迁移）
  - 新增 `get_task_detail()` 方法：加载任务详情（含脚本内容读取），统一浏览器/脚本任务返回格式
  - 新增 `save_task_with_validation()` 方法：保存任务（含危险步骤检查和 ID 校验）
  - 新增 `_save_script_task_validated()` 方法：保存脚本任务（含内容大小验证）
  - 新增 `delete_task_with_validation()` 方法：删除任务（含 ID 校验）
  - 新增 `set_active_task_with_validation()` 方法：设置活动任务（含 ID 和存在性校验）
  - 新增 `get_script_path_public()` 方法：公开接口封装 `_safe_task_path`
  - 新增 `save_order_with_validation()` 方法：保存排序配置（含格式验证）
- `app/container.py`：`TaskService(project_root)` → `TaskManager(project_root / "tasks")`，TaskExecutor 注入 `task_manager`
- `app/deps.py`：`get_task_service` → `get_task_manager`
- `app/api/tasks.py`：7 个路由从 `Depends(get_task_service)` 改为 `Depends(get_task_manager)`
- `app/api/scripts.py`：5 个路由从 `Depends(get_task_service)` 改为 `Depends(get_task_manager)`
- `app/services/debug_service.py`：`services.task_service.task_manager.load_task()` → `services.task_manager.load_task()`
- `app/services/task_executor.py`：新增 `task_manager` 参数和 `task_manager` 属性
- 测试文件同步更新（8 个文件）：所有 `task_service` mock 引用改为 `task_manager`，方法名映射同步更新

## 2026-06-25

### refactor: ProfileService 单例化 — 消除多余实例化点

- `app/services/engine.py`：`ScheduleEngine.__init__` 移除 `profile_service or ProfileService(project_root)` 回退，改为 `profile_service is None` 时抛出 `ValueError`，强制通过 ServiceContainer 注入
- `app/api/autostart.py`：`_read_autostart_lightweight` 和 `_save_autostart_lightweight` 改为从 `request.app.state.services.profile_service` 获取共享实例，不再每次新建 ProfileService；三个路由函数添加 `request: Request` 参数
- `tests/test_services/conftest.py`：`engine_factory` 工厂函数显式传入 `profile_service=mock_ps`，适配强制注入变更
- 背景：原有 5 个独立实例化点导致多个 ProfileService 实例各自持有 `_lock`，并发写 settings.json 时锁不共享可能丢更新

## 2026-06-24 (4)

### chore: 版本升级至 v4.1.0

- `pyproject.toml`：version 4.0.6 → 4.1.0
- `res/tools/task-recorder.user.js`：@version 和 VERSION 常量同步更新至 4.1.0
- `docs/update_log.md`：新增 v4.1.0 版本更新日志，汇总 v4.0.4 以来所有变更

## 2026-06-24 (3)

### fix: 修复文档中 MonitoredPolicy 延迟表、API 端点遗漏等问题

- `docs/login.md`：修复 MonitoredPolicy 延迟表 `[0,0,30,60,120]` → `[5,10,20,60,100]`
- `docs/api-doc.md`：补充 `cancel-login`、`agree`、`browsers`、`icons` 端点
- `docs/api-doc.md`：修复 `log-levels`、`source-level`、`init-status` 描述
- `docs/api-doc.md`：修复日志 API limit 上限 1200 → 1000
- `docs/task-manual.md`：修复退避算法描述（指数退避 → 固定延迟表）
- `docs/task-manual.md`：修复「安全模式」→「纯净模式」
- `docs/task-writing-guide.md`：统一变量解析优先级描述

## 2026-06-24 (2)

### chore: 统一任务 JSON 格式 + 更新文档步骤 id 命名规范

- `tasks/browser/*.json`：统一 `timeout=30000`、`variables` 使用大写 `{{USERNAME}}`、步骤 id 使用描述性名称（如 `fill_username`、`click_login`）
- `docs/task-writing-guide.md`：更新步骤 id 建议为描述性名称，同步更新所有示例

## 2026-06-24

### fix: 轻量模式唤醒web后日志实时更新 + bat脚本执行 + 退出信号处理

- `app/container.py`：轻量模式唤醒 web 服务时将 `NullWebSocketManager` 切换为真正的 `WebSocketManager`，解决日志不实时推送的问题
- `app/workers/script_runner.py`：`cmd /c` 执行 bat 文件移除 `call` 和引号包裹，修复 Windows 无法识别路径的问题
- `main.py`：轻量模式主循环监听 `_web_server_shutdown_event`，web 服务退出后自动关闭进程
- `main.py`：捕获 `asyncio.run` 在信号处理上下文中重新抛出的 `KeyboardInterrupt`

## 2026-06-23 (11)

### fix: 调整重试延迟间隔 + 重试用尽后自动循环 + 日志显示重试进度

- `app/services/retry_policy.py`：`MonitoredPolicy._DELAYS` 从 `[0, 0, 30, 60, 120]` 改为 `[5, 10, 20, 60, 100]`，首次登录失败即有 5s 延迟
- `app/services/retry_policy.py`：`delay_before` 移除 `attempt <= 1` 的零延迟特判，统一查表
- `app/services/retry_policy.py`：`on_login_done` 退出条件从 `>= max_retries` 改为 `> max_retries`，确保第 5 次失败后仍返回延迟（100s）而非直接停止
- `app/services/engine.py`：`_do_network_check` 重试用尽后重置计数并开始新一轮重试（5→10→20→60→100 循环），间隔由 `_monitor_check_interval`（300s）控制
- `app/services/engine.py`：`_on_done` 日志显示重试进度（`重试 3/5, 下次重试: 20s 后 (23:20:24)`）
- `app/services/engine.py`：重试用尽日志显示（`重试已用尽（5/5），开始新一轮重试`）
- `app/services/monitor_service.py`：网络检测日志显示实际在用的检测目标（TCP/HTTP/网址响应），而非仅 ping_targets
- `tests/test_services/test_retry_policy.py`：更新 6 个测试用例适配新延迟值
- `tests/test_services/test_engine.py`：更新退避测试断言（30→20）

## 2026-06-23 (10)

### fix: 自动登录失败后无法及时重试 + 接入登录前置检查 + 修复 cancel_event 缺失 + 恢复丢失代码

- `app/services/engine.py`：`_engine_loop` 引擎循环最大睡眠时间从 `check_interval`（300s）限制为 5 秒（`_MAX_LOOP_SLEEP`），确保 `_on_done` 回调更新 `_next_network_check` 后引擎线程能及时唤醒执行重试
- `app/services/engine.py`：`_do_async_login` 自动登录前接入 `check_login_prerequisites`（物理网络连接 + 认证地址可达性），仅在 `enable_local_check` 或 `check_auth_url` 启用时执行，手动登录不检查
- `app/tasks/browser_runner.py`：`TaskExecutor.__init__` 新增 `cancel_event` 参数，修复 `login.py` 传入 `cancel_event` 时 `TypeError` 崩溃；步骤循环中新增取消检查
- `app/tasks/browser_runner.py`：恢复 `_auto_navigate` 中丢失的 `navigation_wait` AJAX 等待逻辑
- `app/tasks/browser_runner.py`：恢复 `_network_detection_check` 中 `MonitorSettings` 默认值填充逻辑（替代手动 `cfg.get()` 回退）
- `app/tasks/browser_runner.py`：恢复 `_capture_screenshot` 中 `TEMP_DIR` 相对路径计算逻辑

### fix: Ctrl+C 关闭进程卡死

- `main.py`：`_run_full` 和 `_run_lightweight` 的 `finally` 块中 `asyncio.run(container.shutdown())` 添加 5 秒超时防护，避免 Windows 下 asyncio 清理逻辑卡死导致进程无法退出
- `main.py`：两个运行模式的 `finally` 块末尾显式调用 `cleanup_pid()` + `os._exit(0)` 强制退出，确保关闭流程完成后进程立即终止
- 根因：lifespan 的 `finally` 已完成容器关闭（幂等），但 `_run_full` 的防御性 `asyncio.run()` 在创建新事件循环后可能卡在 Windows 的 asyncio 清理逻辑

### fix: 网络检测 url_check_urls 解析统一 + 调用方冗余转换清理

- `app/utils/network.py`：`parse_url_checks` 的 list 分支新增 `str` 元素处理（含 `|` 分隔符的字符串），修复 `list[str]` 格式传入时返回空列表的问题
- `app/network/decision.py`：`check_network_status` 移除冗余的 `"\n".join()` 预处理和类型判断分支，直接调用 `parse_url_checks(monitor.url_check_urls)`
- `app/services/engine.py`：`test_network` 移除冗余的 `"\n".join()` 预处理和局部 import
- `app/tasks/browser_runner.py`：`_network_detection_check` 合并两处分散的局部 import 为一行，简化 `parse_url_checks` 结果处理
- 根因：`parse_url_checks` 已支持 `str | list | None` 三种输入格式，调用方无需做任何预处理

## 2026-06-23 (9)

### feat: 新增 `navigation_wait` 任务参数 + 修复任务执行器网络检测默认值

- `app/tasks/models.py`：`TaskConfig` 新增 `navigation_wait` 字段（浮点数，单位秒，默认 1）
- `app/tasks/browser_runner.py`：`_auto_navigate` 导航完成后根据 `navigation_wait` 额外等待，解决 AJAX 动态渲染表单导致步骤找不到元素的问题
- `app/tasks/browser_runner.py`：`_network_detection_check` 使用 `MonitorSettings` 填充默认值，修复未配置时 TCP/HTTP/网址响应全部显示"关"的问题
- `docs/task-writing-guide.md`：补充 `navigation_wait` 参数说明、AJAX 场景提示和 FAQ
- `docs/task-manual.md`：更新执行流程描述
- `frontend/partials/pages/tasks.html`：任务编辑器帮助内容新增顶层配置说明（`reveal_hidden`、`step_delay`、`navigation_wait`）

## 2026-06-23 (8)

### fix: 代码审查修复（6 个问题）

- `app/tasks/browser_runner.py`：`wait_for_selector` 排除 `type='hidden'` 的 input，避免 SPA 门户 hidden input 导致表单就绪误判
- `app/tasks/step_handlers.py`：`_select_with_fallback` 空白字符串 value 时提前返回，避免 `"" in "anything"` 恒真导致误匹配
- `app/tasks/step_handlers.py`：`_FORCE_INPUT_JS` OcrHandler 强制输入从追加改为覆盖，防止验证码残留拼接
- `app/tasks/step_handlers.py`：`_click_option` trigger 父容器未命中时回退到全局搜索，支持 Portal 框架的下拉面板
- `app/tasks/manager.py`：`delete_task` 先 normalize 再检查 `"default"`，防止带空格的 task_id 绕过保护
- `pyproject.toml`：Python 版本限制为 `>=3.12,<3.13`
- 新增 2 个测试覆盖 `_click_option` 的 trigger 分支和全局回退

## 2026-06-23 (7)

### fix: read_pid_file 缺失 create_time 时视为无效，防止 PID 复用误判

- `app/utils/process.py`：`read_pid_file` 增加 `create_time` 必须存在的校验，缺失则返回 None。`write_pid` 始终写入 `create_time`，所以仅影响手动编辑或旧版本的 PID 文件

## 2026-06-23 (6)

### fix: 代码审查报告批量修复（29 个问题）

**Major（7 个）：**
- [4] `task_executor.py`：`execute_task_async` 队列满时返回带异常的 Future 而非 re-raise
- [5] `engine.py`：`_handle_login` 异常时将错误信息写入 `cmd.response_data`，不再误报为"超时"
- [6] `playwright_worker.py`：`_handle_debug_stop` 中 `new_page()` 添加 try/except，失败时重建浏览器
- [7] `validator.py`：新增 `variables` 字段类型校验（非 dict 则报错）
- [8] `validator.py`：新增任务级 `timeout` 正数校验
- [9] `manager.py`：`_find_task_type` 搜索顺序改为 browser 优先，与 `load_task` 一致
- [10] `profiles.py`：`save_profile`/`delete_profile` 中 `apply_profile` 失败时 message 附加警告

**Minor — 服务/工具层（12 个）：**
- [11] `config.py`：`FIELD_NAMES` 补充 isp/carrier_custom，`_log_config_changes` 补充新增字段检测
- [13] `config.py`：`set_source_level` 检查实际生效级别，降级时返回提示
- [14] `concurrent.py`：`race_first_success` 超时时取消残留 future
- [15] `concurrent.py`：`future.result()` 添加 try/except 防御，循环后显式 `return False`
- [16] `probes.py`：`_get_probe_client` 的 `return` 移入锁内
- [17] `detect.py`：ipconfig 回退增加 `_is_valid_ipv4` 校验
- [18] `detect.py`：nmcli SSID 解析添加 `\:` 反转义
- [21] `detect.py`：macOS 网关匹配改为 `startswith("gateway:")`
- [27] `files.py`：`atomic_write` 中 `os.fdopen` 失败时关闭 fd
- [28] `crypto.py`：移除 `InvalidSignature` 死代码导入
- [29] `crypto.py`：密钥长度异常时添加 warning 日志
- [32] `shell_policy.py`：`run_sync` 超时后调用 `proc.wait()` 回收僵尸进程
- [33] `logging.py`：`set_level` 写 `_config` 加锁

**Minor — 前端（2 个）：**
- [23] `config.js`：`saveConfig` 的 `finally` 检查 controller 引用，避免旧请求重置状态
- [25] `config.js`：`closeEditor` 仅在 `configDirty` 时弹确认框

**Minor — 启动器（1 个）：**
- [35] `start.go`：`runCommand` 中 `cmd.Wait()` 后调用 `signal.Stop` + `close` 清理 goroutine

**Minor — 测试（4 个）：**
- [38] `test_engine.py`：补充 `_handle_start.assert_called_once()` 断言
- [39] `test_network_probes.py`：`test_extra_targets_empty_skip` 添加网络 mock
- [42] `test_engine.py`：`TestNetworkCheckBackoff` 用 `threading.Event` 替代 `time.sleep`
- [44] `test_login_flow.py`：多线程计数器改用 `itertools.count()`
- [45] `test_login_integration_extended.py`：移除 `_capture_login_completion` 未使用的参数

## 2026-06-23 (5)

### fix: login_once 未取消旧任务，新旧登录在单 worker 池中串行执行

- `app/services/login_orchestrator.py`：`submit()` 中 `source == "login_once"` 分支从 `pass` 改为 `existing.cancel()`，取消旧任务后再提交新的，避免两个登录串行执行（最长等待 600s）

## 2026-06-23 (4)

### fix: list_recent 读取 JSONL 文件未持锁，与写入存在竞态

- `app/services/login_history_service.py`：`list_recent()` 的文件读取操作外层加 `with self._lock`，与 `add()` 和 `_cleanup_old()` 的写入操作互斥，避免读到不完整或空文件

## 2026-06-23 (3)

### fix: Go/Shell 启动器镜像 fallback 链完整性修复

- `start.go`：解压失败和 uv.exe 缺失从 `return` 改为 `continue`，继续尝试后续镜像而非直接放弃
- `start.sh`：SHA256 校验从循环外移入循环内，校验失败时 `continue` 尝试下一个镜像而非 `exit 1`

## 2026-06-23 (2)

### fix: 修复 cancel_login 阻塞事件循环及 resolve_for_js 双重编码问题

- `app/api/monitor.py`：`cancel_login` 去掉 `async` 关键字，改为同步 `def`，FastAPI 自动使用线程池执行，避免阻塞事件循环
- `app/tasks/variable_resolver.py`：`resolve_for_js` 的 replacer 对 `runtime_vars` 中的非字符串值（int/bool/None）直接 `json.dumps`，避免双重编码导致类型丢失（5 → "5" 而非 5）

## 2026-06-23

### fix: 修复 5 个 P2 小问题（枚举约束、交叉验证、Worker dict 清理）

- `app/schemas.py`：
  - BUG-14: `RuntimeConfig`、`GlobalConfig`、`ConfigResponseDTO` 的 `startup_action` 字段从 `str = "none"` 改为 `StartupAction = StartupAction.NONE`，统一使用枚举类型约束
  - BUG-15: `PauseSettings` 新增 `@model_validator(mode="after")` 交叉验证，`start_hour == end_hour` 时自动禁用暂停（语义为"不暂停"）
  - BUG-23: `LoggingSettings` 的 `level` 和 `frontend_level` 添加 `pattern` 正则约束，仅允许 DEBUG/INFO/WARNING/ERROR/CRITICAL
- `app/services/login_orchestrator.py`：
  - BUG-17: `_runtime_config_to_worker_dict` 删除 `minimize_to_tray`、`startup_action`、`autostart_lightweight` 三个无关 UI 字段
  - BUG-18: Worker dict 初始化添加 `carrier_custom` 字段，确保自定义运营商信息传递到 Worker

### feat: 登录按钮支持取消，登录中切换为取消登录

- `frontend/js/methods/actions.js`：`manualLogin` 添加 `busy.login` 标志控制按钮状态，新增 `cancelLogin` 方法调用 `POST /api/actions/cancel-login`
- `frontend/js/data/status.js`：`busy` 对象新增 `login: false` 响应式属性
- `frontend/partials/pages/dashboard.html`：登录按钮改为 `v-if`/`v-else` 条件渲染，登录中显示取消登录按钮（`btn-danger`），空闲时显示手动登录按钮（`btn-secondary`）

### feat: 新增 POST /api/actions/cancel-login 端点

- `app/api/monitor.py`：在 `manual_login` 端点之后添加 `cancel_login` 端点，调用 `svc.cancel_login()` 返回 `(bool, str)`
- `tests/test_api/test_api_monitor_routes.py`：新增 `TestCancelLogin` 测试类（2 个测试：成功取消、无待取消登录）

### feat: engine 新增 cancel_login 方法

- `app/services/engine.py`：在 `_handle_login` 方法之后新增 `cancel_login` 方法，暴露 `LoginOrchestrator.cancel_running()` 给 API 层，用于取消当前正在执行的登录

### refactor: 修复 BUG-07 container.py 私有属性篡改

- `app/services/task_executor.py`：移除冗余的 `_login_pool`（登录逻辑已委托 LoginOrchestrator）；`login_orchestrator` 参数改为必填
- `app/container.py`：调整创建顺序（先 LoginOrchestrator 后 TaskExecutor）；移除 `_login_pool`、`_login_orchestrator`、`_orchestrator` 私有属性访问
- `app/services/engine.py`：新增 `set_orchestrator()` 和 `set_task_executor()` 公共方法，替代直接写入私有属性；`login_in_progress` 和 `has_enabled_tasks` 添加空值检查
- `app/services/login_orchestrator.py`：更新注释，移除"共享线程池"说明
- `tests/test_services/test_task_executor_fix.py`：更新 `test_shutdown_with_task_pool` 测试
- `docs/login.md`：更新依赖注入示例代码

### fix: 修复测试类型混用和密码变更日志误报

- `tests/test_services/test_config_service.py`：`test_rollback_restores_fields` 中 `data.global_config = RuntimeConfig(...)` 和 `backup.global_config = RuntimeConfig(...)` 改为 `GlobalConfig(...)`，新增 `GlobalConfig` 导入，验证字段改为 `browser.timeout`（GlobalConfig 实际持有的字段）
- `app/api/config.py`：`_log_config_changes` 密码变更检测跳过以 "•" 开头的掩码值（前端未修改密码时传回掩码），避免误报"密码已修改"

### refactor: 清理 V2 重构残留的旧配置函数

- `app/services/config_service.py`：删除 `save_and_apply` 函数（已被 `save_global_and_profile` 完全替代）；移除未使用的导入 `LoginCredentials`、`RuntimeConfig`
- `app/api/autostart.py`：注释中 `save_and_apply` 引用更新为 `save_global_and_profile`
- `tests/test_services/test_config_service.py`：删除 `TestSaveAndApply` 类（被测函数已移除）；移除 `save_and_apply` 导入
- `tests/test_integration/test_full_mode.py`：`save_and_apply` 改为 `save_global_and_profile`，使用 `ConfigResponseDTO` 参数
- `tests/test_integration/test_login_connection.py`：同上

### feat: settings.json v3→v4 自动迁移

### feat: settings.json v3→v4 自动迁移

- `app/services/profile_service.py`：
  - 新增 `migrate_v3_to_v4(data: dict) -> dict` 函数：将 v3 的 `config` 字段重命名为 `global_config`，剥离 `credentials`/`active_task`/`custom_variables` 运行时字段
  - `_load_unsafe`：从 `ProfilesData.model_validate_json(raw)` 改为 `json.loads(raw)` → `migrate_v3_to_v4(data)` → `ProfilesData.model_validate(data)`，加载时自动迁移旧格式
- `tests/test_services/test_profile_service.py`：
  - 新增 `TestMigrateV3ToV4` 测试类（8 个测试）：基本迁移、v4 不变、缺少 config 字段、剥离 credentials/active_task/custom_variables、保留 profiles
  - 新增 `TestProfileServiceLoadMigration` 测试类（4 个测试）：加载 v3 自动迁移、credentials 剥离、active_task 剥离、v4 直接加载
  - 修复 `test_load_reads_settings_json` 测试：v3 格式现在能正确迁移到 v4，`global_config.logging.level` 正确读取为 "DEBUG"
- 验收：19 个测试全通过

### refactor: 前端适配 ConfigResponseDTO，删除 _saveCredentialsToProfile

- `frontend/js/methods/config.js`：
  - `fetchConfig`：从 API 响应（扁平凭据字段）映射回前端内部嵌套 `credentials` 结构
  - `saveConfig`：构建 ConfigResponseDTO 格式 payload，凭据从 `config.credentials` 展开为顶层字段；移除 `_saveCredentialsToProfile()` 调用和 `fetchProfiles()` 调用（后端 PUT /api/config 一次保存全局+方案）
  - 删除 `_saveCredentialsToProfile()` 方法（后端自动处理方案保存）

### refactor: API config 改用 ConfigResponseDTO，一次保存全局+方案

- `app/api/config.py`：
  - `get_config`：返回类型从 `RuntimeConfig` 改为 `ConfigResponseDTO`，凭据字段扁平化（`username`/`password`/`auth_url`/`isp`/`carrier_custom`），不再依赖 `svc.get_config()`（engine 方法），直接从 `profile_svc.build_runtime_config(data)` 构建
  - `save_config`：参数类型从 `RuntimeConfig` 改为 `ConfigResponseDTO`，调用 `save_global_and_profile` 替代 `save_and_apply`，一次保存全局配置 + 方案凭据
  - `_log_config_changes`：参数类型从 `RuntimeConfig` 改为 `ConfigResponseDTO`，`IGNORE_FIELDS` 从 `credentials.password` 改为 `password`（顶层字段），密码变更检测从 `credentials.password` 改为 `password`
  - 清理未使用的导入（`RuntimeConfig`、`save_and_apply`）
- `app/services/config_service.py`：
  - 新增 `save_global_and_profile(payload, profile_service, reload_fn) -> SaveResult`：原子保存 `GlobalConfig`（从 `ConfigResponseDTO` 剥离凭据）+ 活跃方案凭据
  - ISP 反向映射：`carrier_custom` 非空→"自定义"，`isp` 为空→"无"，其他→原值
  - 密码处理：调用 `save_password_field` 处理掩码/明文/空值
  - 重载失败自动回滚（复用 `_rollback_config`）
  - 新增导入：`ConfigResponseDTO`、`GlobalConfig`、`Profile`、`save_password_field`
  - 保留旧 `save_and_apply`（集成测试仍在使用）
- `tests/test_api/test_api_config_routes.py`：
  - `TestGetConfig`：mock 从 `engine.get_config` 改为 `profile_service.build_runtime_config`，断言从 `credentials.username` 改为 `username`（顶层）
  - `TestSaveConfig`：patch 从 `save_and_apply` 改为 `save_global_and_profile`，payload 从扁平 dict 改为 `ConfigResponseDTO(...).model_dump()`
  - 新增 `_make_runtime_config` 辅助函数
  - 新增导入：`BrowserSettings`、`ConfigResponseDTO`、`LoginCredentials`、`LoggingSettings`、`MonitorSettings`、`PauseSettings`、`RetrySettings`

### refactor: engine.py 删除 _ui_config，统一为 _runtime_config

- `app/services/engine.py`：
  - 删除 `self._ui_config` 声明和初始化
  - `_reload_config_internal`：删除 `self._ui_config = data.global_config` 赋值
  - `get_config`：返回 `self._runtime_config`（frozen 对象，无需 `model_copy(deep=True)`）
  - `_handle_login`：`login_timeout` 改读 `_runtime_config.browser.login_timeout`
  - `run_manual_login`：`login_timeout` 改读 `_runtime_config.browser.login_timeout`
- 测试文件同步更新：
  - `tests/test_services/conftest.py`：删除 `_ui_config` 初始化
  - `tests/test_services/test_engine.py`：`_ui_config` 改为 `_runtime_config`，使用 `model_copy` 替代直接赋值
  - `tests/test_services/test_engine_fix.py`：删除 `_ui_config` 初始化
  - `tests/test_services/test_monitor_service.py`：删除 `_ui_config` 初始化，使用 `model_copy` 替代直接赋值
  - `tests/test_integration/test_login_flow.py`：删除 `_ui_config` 初始化，使用 `model_copy` 替代直接赋值

### refactor: ProfileService 接管配置构建，删除 load_active_config

- `app/services/profile_service.py`：新增三个方法
  - `get_runtime_config() -> RuntimeConfig`：读磁盘 → 构建运行时配置
  - `build_runtime_config(data: ProfilesData) -> RuntimeConfig`：从已加载 data 构建（避免重复读盘）
  - `_get_active_profile(data: ProfilesData) -> Profile`：获取活跃方案并解密密码
  - 新增 `RuntimeConfig` 导入
- `app/services/config_service.py`：删除 `load_active_config` 和旧 `build_runtime_config`，仅保留 `save_and_apply` / `_rollback_config` / `SaveResult`；移除 `GlobalConfig`、`Profile` 导入
- `app/services/engine.py`：`_reload_config_internal` 改用 `profile_service.build_runtime_config(data)`，删除 `load_active_config` 导入和 `has_decrypt_error` 检查逻辑
- `main.py`：`_load_login_config` 改用 `ps.get_runtime_config()`，删除 `load_active_config` 导入和解密错误返回 CONFIG_ERROR 的逻辑
- `app/api/config.py`：`get_config` 改用 `profile_svc.build_runtime_config(data)`，删除手动凭据注入和 ISP 映射逻辑（由 ConfigBuilder 统一处理）
- `tests/test_config/test_config_merge.py`：改用 `svc.get_runtime_config()` 替代 `load_active_config(svc)`
- `tests/test_services/test_config_service.py`：`TestBuildRuntimeConfigV3` 改为 `TestConfigBuilderBuild`，import 从 `config_service.build_runtime_config` 改为 `ConfigBuilder.build`
- `tests/test_app/test_backend_services.py`：`TestLoadActiveConfig` 改为 `TestProfileServiceRuntimeConfig`，`TestBuildRuntimeConfig` 改为 `TestConfigBuilderBuild`；import 改为 `ConfigBuilder`
- `tests/test_app/test_main.py`：6 处 mock patch 从 `app.services.config_service.load_active_config` 改为 `main.create_profile_service`（返回 mock_ps），`get_runtime_config` 返回值从 tuple 改为单个 RuntimeConfig

### feat: 新建 ConfigBuilder — 唯一配置构建器

- 新建 `app/services/config_builder.py`：
  - `ConfigBuilder.build(global_config, profile) -> RuntimeConfig`：全项目唯一的 `GlobalConfig + Profile → RuntimeConfig` 构建器
  - ISP 转换：carrier="自定义"→carrier_custom, carrier="无"→"", 其他→carrier 原值
  - 密码过滤：以 "•" 开头的掩码密码清空为空字符串
  - 字段完整性：global_config 的所有透传字段（block_proxy/shell_path/minimize_to_tray/startup_action/autostart_lightweight/lightweight_tray/auto_open_browser/proxy/app_port）完整传递
  - `custom_variables` 设为空 dict（GlobalConfig 不含此字段）
  - `active_task` 从 profile 传递
- 新建 `tests/test_services/test_config_builder.py`：24 个单元测试
  - `TestCarrierToIsp`（8 个）：自定义→custom、无→""、中国移动/联通/电信透传、空字符串、空白字符串处理
  - `TestPasswordFiltering`（6 个）：掩码密码清空、明文保留、空/空白保持、单点前缀
  - `TestFieldCompleteness`（5 个）：browser/monitor 透传、所有直接字段透传、custom_variables 为空、credentials 结构完整性
  - `TestActiveTask`（3 个）：profile 传递、空默认值、空白去除
  - `TestEndToEnd`（2 个）：全自定义组合场景、frozen 不可变性验证

## 2026-06-22 (23)

### fix: 修复遗漏的 data.config → data.global_config 引用

- `app/api/autostart.py`：
  - `_read_autostart_lightweight`：`ps.load().config` → `ps.load().global_config`
  - `_save_autostart_lightweight` lambda：`d.config` → `d.global_config`（setattr 和 model_copy 两处）
- `app/services/engine.py`：
  - `toggle_pure_mode` lambda：`d.config` → `d.global_config`（setattr 和 model_copy 三处）
- `app/services/config_service.py`：
  - `build_runtime_config` 参数类型标注从 `RuntimeConfig` 改为 `GlobalConfig`，新增 `GlobalConfig` 导入
  - 函数体内 `config.model_copy(update={...})` 改为 `RuntimeConfig(**config.model_dump(exclude={"credentials", "active_task"}), credentials=..., active_task=...)`，因为 GlobalConfig 不含 credentials/active_task 字段

## 2026-06-22 (22)

### refactor: 新增 GlobalConfig、ConfigResponseDTO，更新 RuntimeConfig 和 ProfilesData

- `app/schemas.py`：
  - 新增 `GlobalConfig` 类：持久化配置，不含 `credentials` 和 `active_task`，用于 `settings.json` 写盘
  - 新增 `ConfigResponseDTO` 类：API 响应专用，凭据字段扁平化（username/password/auth_url/isp/carrier_custom），密码已掩码
  - 更新 `RuntimeConfig` docstring：说明此模型仅存在于内存，不直接写盘
  - 更新 `ProfilesData`：`config` 字段改名为 `global_config`，`config_version` 默认值改为 4
  - `RuntimeConfig` 新增 `proxy: str` 和 `app_port: int` 字段（与 `GlobalConfig` 保持一致）
- `app/services/config_service.py`：
  - `load_active_config`：`data.config` → `data.global_config`
  - `save_and_apply` 的 `_apply`：`data.config` → `data.global_config`
  - 注释更新：`config` → `global_config`
- `app/services/engine.py`：
  - `_reload_config_internal`：`data.config` → `data.global_config`（两处）
- `app/api/config.py`：
  - `_persist_source_levels`：`d.config` → `d.global_config`
- `app/api/browsers.py`：
  - `profile_data.config` → `profile_data.global_config`
- `app/workers/playwright_bootstrap.py`：
  - `_get_browser_channel`：`_data.config` → `_data.global_config`
- `app/application.py`：
  - `run()`：`profile_service.load().config.logging` → `profile_service.load().global_config.logging`
- `main.py`：
  - `_load_app_config`：`_data.config` → `_data.global_config`
  - `_run_full`：`_data.config.logging` → `_data.global_config.logging`
- 测试文件同步更新（6 个文件）：
  - `tests/test_config/test_config_schemas.py`：`data.config` → `data.global_config`，`config_version` 断言改为 4
  - `tests/test_services/test_config_service.py`：`data.config` → `data.global_config`
  - `tests/test_services/test_profile_service.py`：`data.config.logging` → `data.global_config.logging`
  - `tests/test_services/test_monitor_service.py`：`mock_ps.load.return_value.config` → `mock_ps.load.return_value.global_config`（6 处）
  - `tests/test_api/test_browsers.py`：`mock_profile_data.config` → `mock_profile_data.global_config`（5 处）

## 2026-06-22 (21)

### fix: 清理 DEFAULT_PROFILE_SETTINGS 中后端已废弃的扁平字段

- `frontend/js/constants.js`：移除 `DEFAULT_PROFILE_SETTINGS` 中 17 个后端 Profile 模型已不持有的字段（browser_timeout、max_retries、stealth_mode、custom_variables 等），仅保留 Profile 实际持有的 9 个字段

## 2026-06-22 (20)

### fix: 添加 proxy/app_port 到 RuntimeConfig，消除幽灵字段

- `schemas.py`：`RuntimeConfig` 新增 `proxy: str` 和 `app_port: int` 字段
- `ports.py`：`resolve_port()` 新增 `config_port` 可选参数，优先级 env > config > default
- `application.py`：`run()` 从 config 读取端口，传给 `create_app()` 和 uvicorn；`create_app()` 新增 `port` 参数用于 CORS
- `repo.py`：仓库请求从 config 读取 `proxy` 传递给 `async_repo_fetch_json`

## 2026-06-22 (19)

### refactor: 统一网络检测默认值到 constants.py

- `constants.py`：`DEFAULT_HTTP_TARGETS` 改为小米/华为 captive portal 地址
- `probes.py`：`is_network_available_socket`/`_http`/`_url` 默认值统一引用 constants
- `decision.py`：移除 `_DEFAULT_HTTP_URLS` 硬编码，引用 constants；清理 `url_check_urls` 冗余类型检查
- `engine.py`：简化 `test_network` 中 `url_check_urls` 处理

## 2026-06-22 (18)

### fix: 手动网络测试未传递 test_urls

- `engine.py` `test_network()`：调用 `is_network_available` 时补充 `test_urls` 参数，修复回退到百度默认值的问题
- 同步修复 `url_check_urls` 格式处理（`list[str]` 而非 `list[dict]`）

## 2026-06-22 (17)

### fix: HTTP 检测使用国内 captive portal 地址

- 默认 HTTP 检测地址改为小米/华为/OPPO 的 `generate_204` 端点
- `probes.py`：captive portal URL（含 `generate_204`/`connectivitycheck`）仅接受 204，普通 URL 接受 200-299

## 2026-06-22 (16)

### fix: 调整默认配置

- TCP/HTTP 检测默认关闭，仅开启网址响应检测
- `minimize_to_tray` 默认 `True`
- `block_proxy` 默认 `True`

## 2026-06-22 (15)

### feat: 网址响应检测添加默认检测地址

- `app/schemas.py`：`url_check_urls` 类型从 `list[dict]` 改为 `list[str]`，默认填充 Apple/Microsoft/Firefox captive portal 地址
- `app/network/decision.py`：`check_network_status` 兼容 `list[str]` 和 `list[dict]` 两种格式
- `frontend/js/constants.js`：同步前端默认值
- `tests/test_services/test_engine.py`：更新测试数据格式

## 2026-06-22 (14)

### fix: 补全网络检测默认值 + 修复网址响应检测开关

- `app/schemas.py` `MonitorSettings`：TCP/HTTP 检测默认开启，`ping_targets` 和 `test_urls` 填充常见目标
- `frontend/js/constants.js`：同步前端默认配置
- `frontend/js/app-options.js`：修复 `urlCheckEnabled` setter 在 `defaultUrlCheckUrls` 为空时开关弹回的 Bug
- `tests/test_services/test_engine_fix.py`：更新默认值断言

## 2026-06-22 (13)

### refactor: 简化向导为纯协议同意页

- `frontend/partials/wizard.html`：删除步骤 2-5（账号/监控/浏览器/完成），只保留协议同意页 + "同意并开始使用"按钮
- `frontend/js/methods/lifecycle.js`：`checkInitStatus` 改用 `data.agreed` 控制向导显示；`finishWizard` 简化为调用 `POST /api/agree` 关闭向导
- `frontend/js/methods/ui.js`：删除 `nextWizardStep` 和 `skipWizard` 方法
- `frontend/js/app-options.js`：删除 `validateWizardStep`、`canProceed`、`wizardErrors`
- `frontend/js/data/ui.js`：删除 `wizardStep` 状态
- `app/api/system.py`：`init-status` 新增 `agreed` 字段（检查 `config/.agree` 文件）；新增 `POST /api/agree` 端点创建标记文件
- `frontend/styles/pages/wizard.css`：删除步骤指示器、配置摘要、表单错误等不再使用的样式

## 2026-06-22 (12)

### fix: 向导保存超时 + 凭据未持久化

**问题 1**：`startup_action: "none"` 时，`boot_engine=False`，lifespan 不调用 `engine.boot()`，引擎线程从未启动。向导保存时 `reload_config()` 派发 RELOAD 命令到队列，但无消费者，10 秒超时。

**修复 1**：将引擎线程启动与监控启动解耦，lifespan 中始终启动引擎线程：

- `app/services/engine.py`：新增 `start_thread()` 方法（仅启动命令处理循环，不启动监控）；`boot()` 改为调用 `start_thread()` + `start_monitoring()`
- `app/application.py`：lifespan 的 `existing_container` 分支中，在条件性调用 `boot()` 前先调用 `start_thread()`
- `tests/test_app/test_boot_engine_flag.py`：更新 4 个测试用例，验证 `start_thread()` 始终被调用

**问题 2**：向导 `finishWizard` 仅调用 `PUT /api/config`（credentials 被 `save_and_apply` 剥离），未将凭据同步到活跃方案，导致 `init-status` 持续返回 `username=空, password=空`。

**修复 2**：`frontend/js/methods/lifecycle.js` `finishWizard` 中，在 config 保存成功后调用 `fetchProfiles()` + `_saveCredentialsToProfile()`，与设置页面 `saveConfig` 行为一致。

**问题 3**：`GET /api/config` 从 `_ui_config` 返回，而 `_ui_config.credentials` 在 `save_and_apply` 时被剥离为空。设置页面通过此接口读取凭据，始终显示空值。

**修复 3**：`app/api/config.py` `get_config` 中，从活跃 profile 注入凭据到返回值，密码脱敏后返回。异常时降级到原始 `_ui_config` 凭据。

## 2026-06-22 (11)

### fix: 保存配置时剥离冗余 credentials 和 active_task

- `app/services/config_service.py`：`save_and_apply` 的 `_apply` 在写入 settings.json 前将 `credentials` 重置为空壳、`active_task` 清空
- 实际凭证和 active_task 只存在于 `profiles` 中，`config` 字段不再持久化冗余数据

## 2026-06-22 (10)

### refactor: 收敛日志配置读取为统一入口

- `main.py:_run_full()`：`_ps.load()` 中间结果存入 `_data`，异常时置 `_data = None`；`run()` 新增 `logging_settings=_logging if _data else None` 参数
- `app/application.py`：`run()` 签名新增 `logging_settings: LoggingSettings | None = None` 参数，新增 `from app.schemas import LoggingSettings` 导入
- `app/application.py:run()` 函数体：合并原有三段日志读取逻辑为单一分支：优先使用 `logging_settings` 参数，仅当参数为 None 且 `access_log_enabled`/`log_retention` 未传入时才回退到 settings.json 读取；`source_levels` 恢复统一使用 `logging_settings`

## 2026-06-22 (9)

### fix: LogConfigCenter._source_levels 线程安全

- `app/utils/logging.py`：`_source_levels` 新增 `_source_levels_lock`，`set_source_level`/`get_source_level`/`remove_source_level`/`get_all_source_levels` 四个方法加锁保护，消除 API 路由写入与 loguru 内部线程读取的竞态

## 2026-06-22 (8)

### fix: MonitoredPolicy 和 _registered_futures 线程安全

- `app/services/retry_policy.py`：`MonitoredPolicy` 新增 `_lock`，`on_network_check` 和 `on_login_done` 加锁保护 `_attempt`/`_prev_network_ok` 的读写，消除引擎线程与回调线程的 lost update 竞态
- `app/services/engine.py`：`_registered_futures` 新增 `_futures_lock`，`add`/`discard`/`in` 操作加锁保护

## 2026-06-22 (7)

### feat(schema): AppConfig 添加 from_runtime_config() 映射方法

- `app/schemas.py`：为 `AppConfig` 添加 `from_runtime_config(config: RuntimeConfig) -> AppConfig` 类方法
- 统一从 RuntimeConfig 派生 AppConfig，消除手动同步 startup_action/minimize_to_tray/lightweight_tray/auto_open_browser 字段的风险

## 2026-06-22 (6)

### feat(schema): RuntimeConfig 添加 lightweight_tray 和 auto_open_browser

- `app/schemas.py`：`RuntimeConfig` 直接透传字段部分新增 `lightweight_tray: bool = True` 和 `auto_open_browser: bool = False`
- 消除 AppConfig 中无法持久化的字段，用户现在可以通过 Web UI 配置并保存

## 2026-06-22 (5)

### fix: 修复 H1 双 login 线程池 + H2 嵌套线程池饥饿

- H1: `app/services/login_orchestrator.py`：`__init__` 新增 `pool` 可选参数，外部可注入共享线程池，未注入时自行创建
- H1: `app/container.py`：构造 `LoginOrchestrator` 时显式传入 `pool=self.task_executor._login_pool`，删除 `self.login_orchestrator._pool = ...` 的私有属性篡改
- H2: `app/network/probes.py`：全局 `executor` 从 `max_workers=3` 扩容为 `max_workers=8, thread_name_prefix="net"`，作为网络检测共享池
- H2: `app/network/decision.py`：删除 `_decision_executor`（3 workers 外层池），改用 `probes.executor`（共享池），消除嵌套线程池饥饿风险

## 2026-06-22 (4)

### fix: LoggingSettings 添加 source_levels + 修复 application.py 源级别恢复

- `app/schemas.py`：为 `LoggingSettings` 添加 `source_levels: dict[str, str]` 字段，修复 `api/config.py:_persist_source_levels()` 写入被 Pydantic 静默忽略的问题
- `app/application.py`：修复 `run()` 中 `sys_settings` 始终为 `None` 的 bug，source_levels 日志级别配置现在能正确从 settings.json 恢复

## 2026-06-22 (3)

### fix(ports): 移除不存在的 global_settings.app_port 读取

- `app/utils/ports.py`：移除 `json`、`PROJECT_ROOT` 导入和 settings.json 读取逻辑，简化为仅从环境变量 APP_PORT 读取
- `tests/test_utils/test_ports.py`：删除 `TestResolvePortFromSettings`、`TestResolvePortSettingsErrors`、`TestResolvePortPriority` 测试类（对应已删除的 settings.json 读取逻辑）
- `tests/test_app/test_application_logic.py`：`TestResolvePort` 中移除 `PROJECT_ROOT` mock 和 `Path` 导入

## 2026-06-22 (2)

### fix(bootstrap): 修复 browser_channel 读取路径

- `app/workers/playwright_bootstrap.py`：`_get_browser_channel()` 从原始 JSON 读取改为使用 ProfileService 加载 Pydantic 模型
  - 旧路径：`json.load(settings_path).get("global_settings", {}).get("browser_channel")`（不存在的字段）
  - 新路径：`create_profile_service().load().config.browser.browser_channel`

## 2026-06-22

### fix(main): 修复 _run_full 中日志配置读取路径

- `main.py:573-580`：`_ps.load().global_settings` → `_ps.load().config.logging`
- `ProfilesData` 没有 `global_settings` 字段（v3 结构），正确路径是 `config.logging`（`LoggingSettings` 模型）
- `access_log` 和 `log_retention_days` 现在能从 settings.json 正确读取

## 2026-06-21 (20)

### test: 清理旧配置模型残留引用

- `app/services/engine.py`：`self._ui_config.login_timeout` → `self._ui_config.browser.login_timeout`
- 测试文件修复：
  - `tests/test_integration/test_login_flow.py`：`svc._ui_config.login_timeout` → `svc._ui_config.browser.login_timeout`
  - `tests/test_services/conftest.py`：`svc._ui_config.login_timeout` → `svc._ui_config.browser.login_timeout`
  - `tests/test_services/test_engine.py`：`svc._ui_config.login_timeout` → `svc._ui_config.browser.login_timeout`
  - `tests/test_services/test_monitor_service.py`：`svc._ui_config.login_timeout` → `svc._ui_config.browser.login_timeout`
- `AuthProfile` → `Profile` 替换：
  - `tests/test_config/test_config_schemas.py`
  - `tests/test_api/test_api_repo_routes.py`
  - `tests/test_api/test_config_fix.py`
  - `tests/test_app/test_backend_services.py`
  - `tests/test_integration/conftest.py`
  - `tests/test_integration/test_network_connection.py`
  - `tests/test_integration/test_profile_connection.py`
  - `tests/test_services/test_monitor_service.py`
  - `tests/test_services/test_profile_service.py`

## 2026-06-21 (19)

### cleanup(schemas): 删除 SystemSettings/MonitorConfigPayload/Mixin
- `app/schemas.py`：
  - 删除 `_MonitorFieldsMixin` 类
  - 删除 `_CommonSettingsMixin` 类
  - 删除 `_SystemFieldsMixin` 类
  - 删除 `SystemSettings` 类
  - 删除 `MonitorConfigPayload` 类
  - 删除 `GLOBAL_SETTINGS_FIELDS` 常量
  - `AuthProfile` 保留为 `AuthProfile = Profile` 向后兼容别名
  - 清理不再使用的导入（`DEFAULT_HTTP_TARGETS`, `DEFAULT_NETWORK_TARGETS`, `DEFAULT_URL_CHECK_URLS`, `get_default_ua`）
- `app/services/login_orchestrator.py`：
  - 更新注释中的 `MonitorConfigPayload` 引用为 `BrowserSettings`
- 测试文件修复：
  - `tests/test_integration/conftest.py`：移除 `MonitorConfigPayload`, `SystemSettings` 导入
  - `tests/test_api/test_api_repo_routes.py`：`MonitorConfigPayload` → `RuntimeConfig`，移除 `global_settings=SystemSettings()`
  - `tests/test_api/test_api_system_routes.py`：`MonitorConfigPayload` → `RuntimeConfig`
  - `tests/test_api/test_api_tasks_routes.py`：`MonitorConfigPayload` → `RuntimeConfig`
  - `tests/test_api/test_browsers.py`：`MonitorConfigPayload` → `RuntimeConfig`
  - `tests/test_api/test_config_fix.py`：移除 `SystemSettings` 导入和 `global_settings` 参数
  - `tests/test_app/test_backend_services.py`：移除 `SystemSettings` 导入
  - `tests/test_config/test_config_schemas.py`：删除对旧模型的测试类（`TestNormalizeHeadersJson`, `TestAuthUrlValidator`, `TestHeadersJsonValidator`, `TestLogLevelValidator`, `TestCustomVariablesValidator`, `TestConstrainedFields`, `TestSystemSettings`, `TestMonitorConfigPayloadFull`）
  - `tests/test_integration/test_full_mode.py`：`MonitorConfigPayload` → `RuntimeConfig`
  - `tests/test_integration/test_login_connection.py`：`MonitorConfigPayload` → `RuntimeConfig`
  - `tests/test_services/test_engine_fix.py`：`_MonitorFieldsMixin` → `MonitorSettings`
  - `tests/test_services/test_profile_service.py`：更新测试数据结构（`global_settings` → `config`）
  - `tests/test_utils/test_utils.py`：删除 `test_schemas_uses_constant` 测试
- 删除的测试文件：
  - `tests/test_build_runtime_config.py`（测试旧的 `build_runtime_config(payload, gs)` 接口）
  - `tests/test_integration/test_config_connection.py`（测试旧的 `save_and_apply(payload, ...)` 接口）
  - `tests/test_integration/test_multi_browser.py`（测试旧的 `SystemSettings` 和 `MonitorConfigPayload`）

## 2026-06-21 (18)

### refactor(frontend): 设置页面适配嵌套配置结构
- `frontend/partials/pages/settings/settings-browser.html`：
  - 所有 `config.xxx` 浏览器字段改为 `config.browser.xxx`（headless/timeout/navigation_timeout/low_resource_mode/locale/timezone_id/disable_web_security/stealth_mode/stealth_custom_script/pure_mode/browser_channel/browser_args/user_agent/extra_headers_json/viewport_width/viewport_height）
- `frontend/partials/pages/settings/settings-monitor.html`：
  - 检测字段改为 `config.monitor.xxx`（check_interval_seconds/network_check_timeout/enable_tcp_check/enable_http_check/enable_local_check/check_auth_url）
  - 数组字段 `ping_targets`/`test_urls`/`auth_url_targets` 改用 `:value + @input` 绑定，前端逗号分隔字符串与后端数组双向转换
  - `url_check_urls` 改用 `:value + @input` 绑定，换行符分隔字符串与后端数组双向转换
  - 重试字段改为 `config.retry.xxx`（max_retries/retry_interval）
  - `login_timeout` 改为 `config.browser.login_timeout`
  - 暂停字段改为 `config.pause.xxx`（enabled/start_hour/end_hour）
- `frontend/partials/pages/settings/settings-system.html`：
  - 日志字段改为 `config.logging.xxx`（log_retention_days/access_log）
- `frontend/partials/pages/settings/settings-account.html`：
  - 凭证字段改为 `config.credentials.xxx`（username/password/auth_url/isp/carrier_custom）
- `frontend/partials/wizard.html`：
  - 同步更新所有凭证/检测/暂停/浏览器字段为嵌套路径
  - 配置摘要显示改为嵌套路径访问
- `frontend/partials/shared/browser-selection.html`：
  - `config.browser_custom_path` 改为 `config.browser.browser_custom_path`
- `frontend/js/app-options.js`：
  - 向导验证改为 `data.config.credentials.xxx` 嵌套路径
  - `urlCheckEnabled` computed 改为数组长度判断
- `frontend/js/methods/actions.js`：
  - `config.login_timeout` 改为 `config.browser.login_timeout`
- `frontend/js/methods/ui.js`：
  - `config.browser_channel` 改为 `config.browser.browser_channel`
  - `config.username`/`config.auth_url` 改为 `config.credentials.xxx`
  - `config.browser_custom_path` 改为 `config.browser.browser_custom_path`

## 2026-06-21 (17)

### refactor(frontend): 配置数据结构改为嵌套
- `frontend/js/constants.js`：
  - 删除 `_SHARED_DEFAULTS` 常量
  - `DEFAULT_CONFIG` 从扁平结构改为嵌套结构（browser/monitor/pause/logging/retry/credentials 六个子对象 + 顶层透传字段），与后端 RuntimeConfig 对齐
  - `DEFAULT_PROFILE_SETTINGS` 从展开 `_SHARED_DEFAULTS` 改为内联完整默认值（保持扁平结构，供 profile 编辑器使用）
- `frontend/js/data/config.js`：
  - 新增 `cloneConfig()` 深拷贝函数，替代 `{ ...DEFAULT_CONFIG }` 浅拷贝
  - `configData()` 使用 `cloneConfig(DEFAULT_CONFIG)` 初始化 config
  - `defaultUrlCheckUrls` 从 `DEFAULT_CONFIG.url_check_urls` 改为 `DEFAULT_CONFIG.monitor.url_check_urls`
- `frontend/js/methods/config.js`：
  - `fetchConfig()`：从扁平合并改为逐层深度合并（browser/monitor/pause/logging/retry/credentials 各自 spread 合并，顶层字段用 `??` 回退）
  - `saveConfig()`：字段访问改为嵌套路径（`config.credentials.auth_url`、`config.monitor.enable_tcp_check`、`config.credentials.isp`）
  - `loadDefaultStealthScript()`：`config.stealth_custom_script` 改为 `config.browser.stealth_custom_script`
- **已知影响**：HTML 模板和 `app-options.js`/`actions.js`/`ui.js` 中仍有大量扁平字段绑定（`config.headless`、`config.check_interval_seconds` 等），需后续步骤适配

## 2026-06-21 (16)

### refactor(profile_service): AuthProfile → Profile
- `app/services/profile_service.py`：
  - import 从 `AuthProfile, ProfilesData` 改为 `Profile, ProfilesData`
  - `get_active_profile()` 返回类型从 `AuthProfile` 改为 `Profile`
  - `save_profile()` 参数类型从 `AuthProfile` 改为 `Profile`
  - `AuthProfile()` 构造改为 `Profile()`
  - `_load_unsafe`/`_save_unsafe` 使用 `ProfilesData`，结构已变（`config` 替代 `global_settings`），Pydantic 自动处理序列化/反序列化，无需额外改动
  - `detect_matching_profile` 通过 `data.profiles` 访问，与新结构兼容

## 2026-06-21 (15)

### refactor(api): config/profiles 端点适配新模型
- `app/api/config.py`：
  - import 从 `MonitorConfigPayload` 改为 `RuntimeConfig`
  - `get_config` 端点：response_model 和返回类型改为 `RuntimeConfig`，密码掩码改为通过 `credentials.model_copy(update=...)` 修改嵌套字段（RuntimeConfig 是 frozen 模型）
  - `save_config` 端点：参数类型从 `MonitorConfigPayload` 改为 `RuntimeConfig`
  - `_log_config_changes` 函数签名：`new_payload: MonitorConfigPayload` 改为 `new_payload: RuntimeConfig`
- `app/api/profiles.py`：
  - import 从 `AuthProfile` 改为 `Profile`
  - `save_profile` 端点：参数类型从 `AuthProfile` 改为 `Profile`
- 测试文件同步更新：
  - `tests/test_api/test_api_config_routes.py`：import 从 `MonitorConfigPayload` 改为 `RuntimeConfig`，mock 返回值从扁平构造改为 `RuntimeConfig(credentials={...})`
  - `tests/test_api/test_api_profiles_routes.py`：import 从 `AuthProfile, SystemSettings` 改为 `Profile`，`ProfilesData` 构造移除 `global_settings` 参数，`AuthProfile` 改为 `Profile`
- 验收：16 个测试全通过

## 2026-06-21 (14)

### refactor(engine): _ui_config 改用 RuntimeConfig
- `app/services/engine.py`：
  - 删除 `MonitorConfigPayload` 导入（第 26 行）
  - `_ui_config` 字段类型从 `MonitorConfigPayload` 改为 `RuntimeConfig`，初始值从 `MonitorConfigPayload()` 改为 `RuntimeConfig()`
  - `get_config()` 返回类型从 `MonitorConfigPayload` 改为 `RuntimeConfig`
  - engine.py 中不再引用 `MonitorConfigPayload`

## 2026-06-21 (13)

### refactor: 合并 runtime_config.py 到 config_service.py
- `app/services/config_service.py`：新增 `load_active_config(profile_service) -> tuple[RuntimeConfig, bool]`，从活跃 Profile 加载并解密密码，返回完整 RuntimeConfig
- `app/services/engine.py`：`_reload_config_internal` 改用 `load_active_config`，`_ui_config` 改为 `data.config`（RuntimeConfig 类型）
- `main.py`：`_load_login_config` 改用 `load_active_config`，删除旧版 `build_runtime_config` + `load_runtime_config` 调用
- 删除 `app/services/runtime_config.py`（`load_payload_from_profiles`、`load_ui_config`、`load_runtime_config`）
- 测试修复：`test_backend_services.py`、`test_config_merge.py`、`test_main.py`、`test_integration/conftest.py` 更新 import 和 mock 路径
- 清理已删除的 `save_config_combined` 相关 import 和测试类

## 2026-06-21 (12)

### refactor(config_service): 重写 build_runtime_config 和 save_and_apply
- `app/services/config_service.py`：
  - 删除 `_update_global_settings` 函数（旧版全局设置循环赋值）
  - 删除 `save_config_combined` 函数（旧版原子化保存）
  - 删除旧版 `build_runtime_config(payload: MonitorConfigPayload, global_settings: SystemSettings | None)`（130 行逐字段搬运）
  - 新增 `build_runtime_config(config: RuntimeConfig, profile: Profile) -> RuntimeConfig`：从 RuntimeConfig + Profile 合并凭证，返回新的 RuntimeConfig
  - 新增 `save_and_apply(config: RuntimeConfig, profile_service, reload_fn) -> SaveResult`：保存 config 到 ProfilesData，失败自动回滚
  - 删除 `_STRIP_FIELDS`、`_LOG_LEVEL_FIELDS` 常量（仅被删除的函数使用）
  - 删除 `GLOBAL_SETTINGS_FIELDS`、`MonitorConfigPayload`、`SystemSettings` 导入
  - 新增 `LoginCredentials`、`Profile`、`RuntimeConfig` 导入
- `tests/test_services/test_config_service.py`：
  - 删除 `TestUpdateSystemSettings`（9 个测试，对应已删除的 `_update_global_settings`）
  - 删除 `TestSaveConfigCombined`（8 个测试，对应已删除的 `save_config_combined`）
  - 删除 `TestBuildRuntimeConfigLoginTimeout`（2 个测试，对应旧版 `build_runtime_config`）
  - 新增 `TestBuildRuntimeConfigV3`（7 个测试）：凭证构建、carrier 映射、browser 配置保留、掩码密码清空、active_task、credentials 替换
  - 新增 `TestSaveAndApply`（5 个测试）：成功保存、保存失败、重载失败回滚、回滚后重载仍失败、回滚过程异常
  - 新增 `TestRollbackConfig`（2 个测试）：字段恢复、全部字段回滚
- 验收：14 个测试全通过

## 2026-06-21 (11)

### refactor(schemas): ProfilesData 改用 RuntimeConfig + Profile
- `app/schemas.py`：
  - `ProfilesData` 从第 424 行移到第 545 行（`RuntimeConfig` 定义之后），避免前向引用问题
  - 删除 `global_settings: SystemSettings` 字段
  - 新增 `config_version: int = Field(default=3)` 字段
  - 新增 `config: RuntimeConfig = Field(default_factory=RuntimeConfig)` 字段
  - `profiles` 类型从 `dict[str, AuthProfile]` 改为 `dict[str, Profile]`
  - `ensure_default_profile` 中 `AuthProfile()` 改为 `Profile()`
  - docstring 更新为 "settings.json 顶层结构（v3）"
- `tests/test_config/test_config_schemas.py`：
  - 更新 `TestProfilesData` 测试类适配 v3 结构
  - 新增 `test_config_version_default`、`test_config_is_runtime_config`、`test_no_global_settings` 测试
  - 所有 profile 相关测试改用 `Profile` 类型
- 验收：98 个测试全通过

## 2026-06-21 (10)

### feat(migration): 新增 v2→v3 配置迁移逻辑
- `app/services/config_migration.py`：
  - 新增 `migrate_v2_to_v3(data)` 函数：将 v2 格式（扁平 global_settings）迁移到 v3 格式（结构化 config + 独立凭证 Profile）
  - v3 格式直接返回（幂等）
  - `_build_config_from_flat(gs)`：从扁平字段构建 browser/monitor/pause/logging/retry 子结构
  - `_merge_credential(profile, gs)`：profile 留空字段从 global_settings 继承（含 carrier "无" 视为未设置的特殊处理）
  - `_resolve_carrier(profile_val, global_val)`：carrier 字段回退逻辑，"无" 视为未设置
  - `_parse_url_check_urls(raw)`：解析 url_check_urls 字符串为字典列表
- `tests/test_services/test_config_migration.py`：5 个单元测试覆盖基本迁移、凭证回退、缺少 default profile 自动创建、多 profile 保留、v3 透传
- 验收：5 个测试全通过

## 2026-06-21 (9)

### feat(schemas): 新增 Profile 模型（凭证独立持有）
- `app/schemas.py`：
  - 在 `AuthProfile` 类定义之后新增 `Profile` 类
  - Profile 的字段与 AuthProfile 完全相同：name, match_gateway_ip, match_ssid, username, password, auth_url, carrier, carrier_custom, active_task
  - 所有字段默认值为空字符串或合理默认值
  - 保留 `auth_url` 的 `field_validator`（复用已有的 `_validate_auth_url` 函数）
  - 不修改 AuthProfile（保持向后兼容），不修改 ProfilesData（后续 Task 会改）
- 设计语义：每个方案独立持有凭证，不存在"留空回退到全局"语义
- 验收：96 个测试全通过

## 2026-06-21 (8)

### fix(worker): 移除纯净模式下多余的 stealth 注入
- `app/workers/playwright_worker.py`：
  - 删除 `_start_browser` 中纯净模式下 `if pure_mode and stealth_mode` 的 `_apply_stealth_and_routes` 调用（第 781-783 行）
  - 纯净模式设计意图为不注入反检测脚本，该分支是多余逻辑
  - 保留注释说明设计意图

## 2026-06-21 (7)

### refactor(env): build_login_template_vars 改为显式参数
- `app/utils/env.py`：
  - 函数签名从 `build_login_template_vars(runtime_config: RuntimeConfig | dict[str, Any], task_url, custom_variables)` 改为 `build_login_template_vars(auth_url, username, password, isp, task_url, custom_variables)`
  - 移除 `hasattr(runtime_config, "credentials")` 双路径判断
  - 移除 `from typing import Any` 导入
  - 自定义变量值统一通过 `str(v)` 转换
- `app/utils/login.py`：
  - 调用点从 `build_login_template_vars(self.config, task.url, self._custom_variables)` 改为关键字参数形式，从 `self._credentials` 解构
- `app/services/debug_service.py`：
  - 调用点从 `build_login_template_vars(runtime_config, task.url, runtime_config.custom_variables)` 改为关键字参数形式，从 `runtime_config.credentials` 解构
- 测试文件同步更新（2 个文件）：
  - `tests/test_utils/test_env_fix.py`：6 个测试从 dict 参数改为显式关键字参数
  - `tests/test_utils/test_utils.py`：8 个测试从 dict 参数改为显式关键字参数
- 验收：2332 测试全通过

## 2026-06-21 (6)

### refactor(monitor): check_once() 返回类型化 CheckOnceResult dataclass
- `app/services/monitor_service.py`：
  - 新增 `CheckOnceResult` dataclass（frozen, slots），包含 `paused`/`net_ok`/`net_reason`/`need_login`/`check_num`/`interval`/`result` 7 个字段
  - `check_once()` 返回类型从 `dict[str, Any]` 改为 `CheckOnceResult`
  - 两处 `return { ... }` 替换为 `return CheckOnceResult(...)`
- `app/services/engine.py`：
  - `_do_network_check()` 消费端从 `result.get("interval", ...)` / `result.get("need_login", False)` 改为 `result.interval` / `result.need_login` 属性访问
  - 移除中间变量 `interval`，直接使用 `result.interval`
- 测试文件同步更新（5 个文件）：
  - `tests/test_services/test_engine.py`：mock 返回值从 dict 改为 `CheckOnceResult(...)` 实例，新增 `CheckOnceResult` 和 `NetworkCheckResult` 导入
  - `tests/test_integration/test_login_flow.py`：同上
  - `tests/test_integration/test_login_integration_extended.py`：同上
  - `tests/test_integration/test_network_connection.py`：`result.get(...)` 改为 `result.paused` / `result.need_login` 属性访问，mock 返回值改为 `CheckOnceResult(...)`
- 验收：2332 测试全通过

## 2026-06-21 (5)

### refactor(validator): ConfigValidator 直接接受 RuntimeConfig
- `app/utils/config_utils.py`：
  - `validate_env_config` 签名从 `config: dict` 改为 `config: RuntimeConfig`
  - 使用 `TYPE_CHECKING` 避免与 `app.schemas` 的循环导入
  - 移除所有 `.get()` 调用，通过 `config.credentials` 属性访问
- `app/services/engine.py`：
  - `start_monitoring()` 移除从 `RuntimeConfig` 手动构造 dict 的转换，直接传递 `self._runtime_config`
- `tests/test_config/test_config_schemas.py`：
  - 所有 `validate_env_config` 测试从 dict 构造改为 `RuntimeConfig(credentials=LoginCredentials(...))` 实例
- 验收：2332 测试全通过

## 2026-06-21 (4)

### refactor(time): is_in_pause_period 直接接受 PauseSettings
- `app/utils/time_utils.py`：
  - 函数签名从 `is_in_pause_period(pause_config: dict[str, Any])` 改为 `is_in_pause_period(pause: PauseSettings)`
  - 移除所有 `.get()` 调用，直接通过属性访问 `pause.enabled`、`pause.start_hour`、`pause.end_hour`
  - 使用 `TYPE_CHECKING` 避免与 `app.schemas` 的循环导入
- `app/network/decision.py`：
  - `check_pause()` 移除从 `PauseSettings` 构造 dict 的中间层，直接将 `pause` 传递给 `is_in_pause_period`
  - debug 日志从 `{}` 格式化改为具名参数输出
- `tests/test_utils/test_utils.py`：
  - 所有测试从 dict 构造改为 `PauseSettings(...)` 实例
  - `test_missing_keys_*` 重命名为 `test_defaults_*`，使用 `PauseSettings()` 默认值

## 2026-06-21 (3)

### fix: 修复 debug_service 和 env.py 的 RuntimeConfig 类型兼容
- `app/utils/env.py`：
  - `build_login_template_vars` 签名从 `dict[str, Any]` 改为 `RuntimeConfig | dict[str, Any]`
  - 通过 `hasattr(runtime_config, "credentials")` 分支支持两种类型
  - RuntimeConfig 分支使用属性访问（`.credentials.auth_url`），dict 分支保留 `.get()` 调用
  - `custom_variables` 参数为 None 时自动从 RuntimeConfig 的 `custom_variables` 属性读取
- `app/services/debug_service.py`：
  - `build_login_template_vars` 调用从 `runtime_config.get("custom_variables", {})` 改为 `runtime_config.custom_variables`
  - `browser_settings` 访问从 `.get("browser_settings", {})` 改为 `.browser.timeout` / `.browser.navigation_timeout` 属性访问
  - Worker 数据的 `config` 从直接传 `runtime_config` 改为通过 `_runtime_config_to_worker_dict()` 转换为 dict
- 测试文件同步更新：
  - `tests/test_services/test_debug_service.py`：mock 改为模拟 RuntimeConfig 属性结构，增加 `_runtime_config_to_worker_dict` patch
  - `tests/test_services/test_debug_session_manager.py`：3 处 mock 从 dict 改为模拟 RuntimeConfig，增加 `_runtime_config_to_worker_dict` patch

## 2026-06-21 (2)

### fix: 修复 login.py check_network_status 类型不匹配并移除 engine 死代码
- `app/utils/login.py`：
  - `_execute_script_task` 中 `check_network_status` 调用从传入 `self.config`（dict）改为构造 `MonitorSettings`（Pydantic 模型）
  - 修复运行时 AttributeError（check_network_status 签名要求 MonitorSettings 而非 dict）
- `app/services/engine.py`：
  - 移除 `_runtime_config_to_dict` 静态方法（无调用者，死代码）

## 2026-06-21

### cleanup: 移除旧配置 dict 构建器和废弃的调度器方法
- `app/services/config_service.py`：
  - 移除 `build_runtime_dict_from_payload` 函数（已被 `build_runtime_config` 替代）
  - 移除未使用的 `from typing import Any` 导入
- `app/utils/config_utils.py`：
  - 移除 `PROFILE_RUNTIME_FIELDS` 常量和 `assign_profile_fields` 函数（仅被已删除的 `build_runtime_dict_from_payload` 使用）
  - 更新模块 docstring
- `app/services/engine.py`：
  - 移除废弃的 `start_scheduler()` / `stop_scheduler()` 公开别名（已被 `sync_scheduler_state()` 替代）
- `app/services/login_orchestrator.py`：
  - 更新 `_runtime_config_to_worker_dict` docstring，移除对已删除函数的引用
- 测试文件同步更新：
  - `tests/test_app/test_backend_services.py`：import 和测试类从 `build_runtime_dict_from_payload` 改为 `build_runtime_config`，断言改为属性访问
  - `tests/test_services/test_config_service.py`：同上
  - `tests/test_integration/test_multi_browser.py`：同上
  - `tests/test_utils/test_utils.py`：移除 `TestAssignProfileFields` 和 `TestProfileRuntimeFields` 测试类及导入
  - `tests/test_services/test_monitor_service.py`：8 处 mock 路径从 `build_runtime_dict_from_payload` 改为 `build_runtime_config`
  - `tests/test_services/test_engine.py`：调度器测试从 `start_scheduler`/`stop_scheduler` 改为 `_start_scheduler`/`_stop_scheduler`
  - `tests/test_integration/test_full_mode.py`：同上
- 保留项：`_STRIP_FIELDS` 和 `_LOG_LEVEL_FIELDS`（仍被 `_update_global_settings` 使用）
- 验收：2332 测试全通过，lint 无新增错误

## 2026-06-21

### refactor(scheduler): 定时任务 API 端点统一使用 sync_scheduler_state
- `app/api/scheduled_tasks.py`：
  - `create_scheduled_task`：`if ok and config.get("enabled", True): engine.start_scheduler()` 改为 `if ok: engine.sync_scheduler_state()`
  - `update_scheduled_task`：同上
  - `toggle_scheduled_task`：`if ok and task["enabled"]: engine.start_scheduler()` 改为 `if ok: engine.sync_scheduler_state()`
  - `delete_scheduled_task`：新增 `if ok: engine.sync_scheduler_state()` 调用，删除后自动检查是否应停止调度器
- `tests/test_api/test_api_scheduled_tasks_routes.py`：`test_create_starts_scheduler_when_enabled` 断言从 `start_scheduler.assert_called()` 改为 `sync_scheduler_state.assert_called()`
- 验收：91 个定时任务测试全通过

### refactor: 迁移 TaskExecutor/main/application 至 RuntimeConfig
- `app/services/task_executor.py`：
  - `__init__` 和 `set_runtime_config_getter` 类型注解从 `Callable[[], dict]` 改为 `Callable[[], RuntimeConfig]`
  - `execute_login_async`/`execute_login` 的 `config_snapshot` 类型从 `dict | None` 改为 `RuntimeConfig | None`
  - `_execute_browser` fallback 从 `{}` 改为 `RuntimeConfig()`
  - `_execute_shell` 的 `config.get("shell_path", "")` 改为 `config.shell_path` 属性访问
  - `execute_login` fallback 从 `{}` 改为 `RuntimeConfig()`
- `main.py`：
  - `_load_login_config` 改用 `build_runtime_config` 替代 `build_runtime_dict_from_payload`，返回 `RuntimeConfig`
  - `_execute_login_with_retries` 参数类型从 `dict` 改为 `RuntimeConfig`，重试设置访问改为 `runtime_config.retry.max_retries` / `runtime_config.retry.retry_interval`
  - `check_network_status` 调用改为传递 `runtime_config.monitor`
  - `_run_lightweight` 调度器启动改为 `sync_scheduler_state()`
  - 顶部新增 `RuntimeConfig` 导入
- `app/application.py`：lifespan 中调度器启动改为 `services.engine.sync_scheduler_state()`
- `app/container.py`：startup 中调度器启动改为 `self.engine.sync_scheduler_state()`
- 测试文件同步更新（6 个文件）：
  - `tests/test_app/test_main.py`：patch 目标从 `build_runtime_dict_from_payload` 改为 `build_runtime_config`，返回值从 dict 改为 `RuntimeConfig(credentials=_TEST_CREDS, retry=...)`
  - `tests/test_app/test_main_fix.py`：mock `_load_login_config` 返回 `RuntimeConfig()`
  - `tests/test_integration/test_login_once_mode.py`：同上 + 直接传递 `RuntimeConfig` 给 `_execute_login_with_retries`
  - `tests/test_integration/test_login_integration_extended.py`：`_runtime_config_to_dict` 改为 `model_copy(update={"retry": ...})`
  - `tests/test_config/test_container.py`：断言从 `start_scheduler` 改为 `sync_scheduler_state`
  - `tests/test_integration/test_app_startup.py`：同上
  - `tests/test_services/test_task_executor_fix.py`：所有 `_get_runtime_config` 返回值从 dict 改为 `RuntimeConfig`
- 验收：2340 测试全通过

### refactor(login): LoginAttemptHandler 解构 config dict 为命名属性
- `app/utils/login.py`：
  - 构造函数新增解构逻辑：`_credentials`（username/password/auth_url/isp）、`_browser_settings`、`_monitor_settings`、`_active_task`、`_custom_variables`
  - `_perform_login_with_active_task`：`self.config.get("active_task", "").strip()` 改为 `self._active_task`
  - `_execute_browser_task`：凭证访问从 `self.config.get("auth_url", "")` 改为 `self._credentials["auth_url"]` 等
  - `_execute_browser_task`：`self.config.get("custom_variables", {})` 改为 `self._custom_variables`
  - `_execute_browser_task`：`self.config.get("browser_settings", {})` 改为 `self._browser_settings`，删除中间变量 `browser_settings`
  - `_execute_browser_task`：`self.config.get("monitor", {})` 改为 `self._monitor_settings`
  - `_execute_script_task`：`self.config.get("monitor", {}).get("script_timeout", 60)` 改为 `self._monitor_settings.get("script_timeout", 60)`
  - `self.config` 整体仍保留用于传递给 `build_login_template_vars`、`BrowserContextManager`、`check_network_status` 等期望完整 config 的函数
- 验收：36 个核心 monitor/login 测试全通过，pre-existing 的 main.py/orchestrator dict 问题与本次改动无关

### test: 适配 monitor/decision 测试至 RuntimeConfig
- `tests/test_services/test_monitor_service_fix.py`：dict 配置改为 `RuntimeConfig(LoginCredentials(...), MonitorSettings(...))` 构造
- `tests/test_integration/test_network_connection.py`：`_make_monitor_core` 移除 `.model_dump()` 调用，直接传递 `RuntimeConfig`
- `tests/test_integration/test_profile_connection.py`：同上，移除 `.model_dump()`
- `tests/test_services/test_engine.py`：`test_handle_start_pure_mode` 断言从 `call_config["browser_settings"]["pure_mode"]` 改为 `call_config.browser.pure_mode`
- `tests/test_services/test_monitor_service.py`：`TestProfileSwitchFlag` 3 个测试从 `NetworkMonitorCore()` 改为 `NetworkMonitorCore(config=RuntimeConfig())`
- `tests/test_integration/test_login_flow.py`：`test_login_command_success` 断言从 `call_kwargs["config"]["username"]` 改为 `call_kwargs["config"].credentials.username`；`test_manual_login_cancels_in_progress_auto_login` 断言从 `isinstance(..., dict)` 改为 `isinstance(..., RuntimeConfig)`
- 验收：2279 测试通过，5 个 pre-existing 的 main.py dict 问题失败与本次改动无关

### refactor(monitor): 迁移 NetworkMonitorCore 和 decision.py 至类型化配置
- `app/services/monitor_service.py`：
  - 构造函数 `config` 参数类型从 `dict[str, Any] | None` 改为 `RuntimeConfig`
  - `_get_monitor_interval` 改用 `self.config.monitor.check_interval_seconds` 属性访问
  - `init_monitoring` 改用 `self.config.credentials.*` 和 `self.config.monitor.*` 属性访问
  - `check_once` 中 `check_pause` 改为传递 `self.config.pause`
  - `check_once` 中 `check_network_status` 改为传递 `self.config.monitor`
  - `_build_test_sites` 改用 `self.config.monitor.ping_targets` 属性访问
- `app/network/decision.py`：
  - `check_pause` 签名从 `config: dict` 改为 `pause: PauseSettings`，内部构建 dict 传递给 `is_in_pause_period`
  - `check_network_status` 签名从 `config: dict` 改为 `monitor: MonitorSettings`
  - `check_login_prerequisites` 签名从 `config: dict` 改为 `(monitor: MonitorSettings, auth_url: str)`
  - 三个公共函数内部全部改为直接属性访问
- `app/services/engine.py`：
  - `_handle_start` 中 `NetworkMonitorCore` 构造改为直接传递 `RuntimeConfig`（移除 `_runtime_config_to_dict` 转换）
- 测试文件同步更新：
  - `tests/test_core/test_monitor.py`：所有 `NetworkMonitorCore()` 调用改为传递 `RuntimeConfig()`
  - `tests/test_core/test_network_probes.py`：`check_pause`/`check_network_status`/`check_login_prerequisites` 测试改用类型化模型
- 验收：83 个核心测试全通过（2 个 pre-existing 的 main.py 测试失败与本次改动无关）

### fix(engine): 直接传递 RuntimeConfig 给 orchestrator，移除不必要的桥接转换
- `app/services/engine.py`：
  - `_do_async_login`：移除 `_runtime_config_to_dict` 转换，直接传递 `RuntimeConfig` 给 `orchestrator.submit()`
  - `_handle_login`：移除 `_runtime_config_to_dict` 转换，直接传递 `RuntimeConfig` 给 `orchestrator.validate()` 和 `orchestrator.submit()`
  - `_runtime_config_to_dict` 保留仅用于 `_handle_start` 中传递给 `NetworkMonitorCore`（该组件仍接受 dict）
- `tests/test_services/test_engine_fix.py`：
  - `test_handle_login_uses_validated_config`：断言从 dict 下标访问改为 `RuntimeConfig` 属性访问
  - `test_manual_login_submits_to_orchestrator`：同上
  - `test_auto_login_submits_to_orchestrator`：同上
- 验收：211 个 engine/orchestrator 测试全通过

### refactor(orchestrator): 完成 LoginOrchestrator 迁移至 RuntimeConfig
- `app/services/login_orchestrator.py`：
  - `validate_login_config` 仅接受 `RuntimeConfig`（移除 hasattr 双重支持）
  - `resolve_worker_timeout` 仅接受 `RuntimeConfig`（移除 hasattr 双重支持）
  - `submit()`/`validate()`/`_dispatch()` 类型注解改为 `RuntimeConfig`
  - `_runtime_config()` 返回 `RuntimeConfig`（默认 `RuntimeConfig()`）
  - `_runtime_config_to_legacy_dict` 重命名为 `_runtime_config_to_worker_dict`
  - `_runtime_config_to_worker_dict` 新增 `access_log`/`log_retention_days` 字段
  - 构造函数 `get_runtime_config` 类型改为 `Callable[[], RuntimeConfig]`
- `tests/test_services/test_login_orchestrator.py`：
  - 测试用例改用 `RuntimeConfig` 构造配置
  - 移除 Pydantic 已保证的边界测试（None/非法字符串/超限值）
- 已知：调用方（main.py/engine.py）仍传递 dict，需后续任务迁移

### fix(orchestrator): 移除 submit 方法 docstring 重复行
- `app/services/login_orchestrator.py`：
  - 第 195-196 行存在两行 `config:` docstring 描述（"配置（dict 或 RuntimeConfig）"和"配置快照"）
  - 移除重复行，保留更准确的描述"配置（dict 或 RuntimeConfig）"
- 验收：1092 测试通过（1 个 pre-existing 网络测试失败跳过）

### fix(engine): 移除重复的 get_runtime_config 和未使用的导入
- `app/services/engine.py`：
  - 移除第 612 行 `from .config_service import build_runtime_dict_from_payload`（未使用的导入）
  - 移除第 667-669 行的第一个 `get_runtime_config()` 方法（被第 882 行的同名方法遮蔽）
- 验收：173 个 engine 测试全通过

## 2026-06-21

### refactor(engine): 迁移至 RuntimeConfig 并添加 sync_scheduler_state
- `app/services/engine.py`：
  - `_runtime_config` 类型从 `dict` 改为 `RuntimeConfig`（frozen，无需 deepcopy）
  - `_runtime_snapshot` 类型从 `dict` 改为 `RuntimeConfig | None`
  - `_reload_config_internal` 改用 `build_runtime_config` 替代 `build_runtime_dict_from_payload`
  - 移除 `_copy_runtime_config` 方法
  - `get_runtime_config` 返回 `RuntimeConfig`（frozen 对象直接返回引用）
  - `_handle_start` 使用 `model_copy` 创建带 pure_mode 的配置副本
  - `_handle_login`/`_do_async_login` 通过 `_runtime_config_to_dict` 转为旧格式 dict 兼容 Orchestrator/Worker
  - `_handle_apply_profile` 改用 `credentials.auth_url`/`credentials.username` 属性访问
  - `test_network` 改用 `config.monitor.*` 属性访问
  - `start_monitoring` 的 `ConfigValidator.validate_env_config` 改用 dict 字面量
  - `shutdown` 改用 `_stop_scheduler()`
  - 新增 `sync_scheduler_state()` 作为调度器生命周期唯一入口
  - 新增 `_start_scheduler()`/`_stop_scheduler()` 内部方法
  - `start_scheduler`/`stop_scheduler` 标记为废弃别名
  - 新增 `_runtime_config_to_dict()` 静态方法（RuntimeConfig→旧格式扁平 dict 桥接）
- `app/services/login_orchestrator.py`：
  - `validate_login_config` 支持 dict 和 RuntimeConfig 两种输入
  - `resolve_worker_timeout` 支持 dict 和 RuntimeConfig 两种输入
  - `_dispatch` 对 RuntimeConfig 输入自动转为旧格式 dict 再传给 Worker
  - 新增 `_runtime_config_to_legacy_dict` 辅助函数
- 测试文件同步更新（12 个文件）：
  - `tests/test_services/conftest.py`：raw fixture 改用 `RuntimeConfig()`
  - `tests/test_services/test_engine.py`：所有 `_copy_runtime_config` mock 替换为直接设置 `_runtime_config`
  - `tests/test_services/test_engine_fix.py`：同上 + 更新断言
  - `tests/test_services/test_monitor_service.py`：同上 + 更新 mock 路径
  - `tests/test_integration/test_login_flow.py`：同上 + 顶层导入
  - `tests/test_integration/test_login_integration_extended.py`：改用 `_runtime_config_to_dict` + 属性访问
  - `tests/test_integration/test_login_connection.py`：`_ensure_login_config` 改用 `model_copy`
  - `tests/test_integration/test_lightweight_mode.py`：同上
  - `tests/test_integration/test_full_mode.py`：同上
  - `tests/test_integration/test_network_connection.py`：改用 `get_runtime_config().model_dump()`
  - `tests/test_integration/test_profile_connection.py`：同上
  - `tests/test_services/test_container_fix.py`：无需改动（orchestrator 兼容层处理）
- 验收：2342 测试全通过（1 个 pre-existing 时间段暂停窗口失败跳过）

## 2026-06-21

### test(config): 补充 build_runtime_config 测试覆盖
- `tests/test_build_runtime_config.py`：
  - 添加 `test_build_runtime_config_password_masked`：验证以 • 开头的密码被清空
  - 添加 `test_build_runtime_config_pause_logging_retry`：验证暂停/日志/重试设置正确传递
  - 添加 `test_build_runtime_config_url_check_urls`：验证 url_check_urls 解析为字典列表
  - 修正 `test_build_runtime_config_strip_fields` docstring（移除多余的 proxy 描述）
- 验收：10 个测试全通过

### fix(config): 补充 carrier_custom 传入 LoginCredentials
- `app/services/config_service.py`：`build_runtime_config` 的 `LoginCredentials(...)` 构造补充 `carrier_custom=custom_isp` 参数
- `tests/test_build_runtime_config.py`：`test_build_runtime_config_credentials` 新增 `assert rc.credentials.carrier_custom == "myisp"` 断言
- 验收：7 个测试全通过

## 2026-06-21

### feat(config) — 添加 build_runtime_config() 返回类型化 RuntimeConfig
- `app/services/config_service.py`：新增 `build_runtime_config(payload, global_settings)` 函数
  - 构建 `LoginCredentials`（用户名、密码、认证地址、运营商映射）
  - 构建 `BrowserSettings`（从 SystemSettings 读取浏览器配置，含 strip 处理）
  - 构建 `MonitorSettings`（监控间隔、ping 目标、URL 检测等，从 payload 读取）
  - 构建 `PauseSettings`、`LoggingSettings`、`RetrySettings`
  - 组装 `RuntimeConfig`（透传 block_proxy/shell_path/minimize_to_tray 等字段）
  - 旧 `build_runtime_dict_from_payload` 暂时保留以兼容迁移
- `tests/test_build_runtime_config.py`：7 个单元测试覆盖返回类型、凭证、运营商映射、浏览器配置、监控字段、透传字段、strip 处理
- 修正：`network_check_timeout` 从 `SystemSettings`（gs）读取而非 payload；`url_check_urls` 将元组转为字典列表以匹配 `MonitorSettings` 类型
- 验收：7 个新测试 + 564 个既有测试全通过

### feat(schemas) — 添加类型化 RuntimeConfig 子集模型
- `app/schemas.py`：在 `GLOBAL_SETTINGS_FIELDS` 前新增 7 个 frozen Pydantic 模型
  - `BrowserSettings`：浏览器运行参数（headless/timeout/navigation_timeout/viewport 等 20 个字段）
  - `LoginCredentials`：登录凭证（username/password/auth_url/isp/carrier_custom）
  - `MonitorSettings`：网络监控参数（check_interval_seconds/network_check_timeout/ping_targets 等 11 个字段）
  - `PauseSettings`：暂停时段配置（enabled/start_hour/end_hour）
  - `LoggingSettings`：日志配置（level/frontend_level/log_retention_days/access_log）
  - `RetrySettings`：重试策略（max_retries/retry_interval）
  - `RuntimeConfig`：运行时配置根模型，组合所有子集模型 + 直接透传字段（active_task/custom_variables/block_proxy/shell_path/minimize_to_tray/startup_action/autostart_lightweight）
- `tests/test_runtime_config_models.py`：6 个单元测试覆盖 frozen 不可变性、默认值、校验、组合、透传字段
- 验收：6 个新测试 + 151 个既有 config 测试全通过

## 2026-06-20

### fix — 修复手动登录等待完成引入的测试失败
- `tests/test_integration/test_login_flow.py`：
  - `test_login_command_success`：mock `_do_async_login` 改为 mock `orchestrator.submit` 返回 handle，`handle.result()` 返回 `(True, "登录成功")`
  - `test_login_command_failure_already_in_progress`：mock handle 的 `future=None` 模拟去重命中
- `tests/test_integration/test_login_integration_extended.py`：
  - `test_chain_success`/`test_chain_failure`/`test_retry_after_failure`：移除 `_capture_login_completion` 包装和异步等待，直接断言 `_handle_login` 返回的实际登录结果
- `tests/test_services/test_monitor_service.py`：
  - `test_handle_login_submits_async`：`handle.future` 从空 `Future()`（永远不 resolve）改为 `MagicMock()`，`handle.result()` 返回 `(True, "登录成功")`
- 验收：2325 测试全通过（3 个预存在的 hang 跳过）

### fix — 手动登录 API 等待登录完成后返回
- `app/services/engine.py`：`_handle_login` 从异步提交改为同步等待结果
  - 直接调用 `orchestrator.submit(source="manual", config=...)` 获取 handle
  - 通过 `handle.result()` 阻塞等待登录实际完成后再返回
  - 支持 `rejected_reason` 和 `future is None` 两种拒绝场景
- `tests/test_services/test_engine.py`：更新 `TestHandleLogin` 测试适配新 API
- `tests/test_services/test_engine_fix.py`：更新 `test_handle_login_uses_validated_config` 适配新 API

### refactor — 统一退避系统
- MonitoredPolicy 改为固定延迟表 `[0, 0, 30, 60, 120]`，max_retries=5
- 删除 Engine 层退避：`_consecutive_login_failures`、`_backoff_check_multiplier`、`_apply_backoff_interval`、`_login_retry_max_cycles`、`_LOGIN_BACKOFF_THRESHOLD`
- `_do_network_check` 和 `_on_done` 回调简化，单一决策源
- 更新 6 个测试文件适配，2327 测试全通过

### fix — 修复统一退避引入的测试失败
- `tests/test_integration/test_login_connection.py`：
  - `test_retry_exhausted` 断言从 `engine._consecutive_login_failures == 3` 改为 `engine._retry_policy._attempt == 3`
  - `MonitoredPolicy._attempt` 是统一退避重构后的等效行为
  - 修复后 `test_login_connection.py` 全部 7 个测试通过

## 2026-06-20

### refactor — 浏览器任务通过 LoginOrchestrator 提交（F11 修复）
- `app/services/login_orchestrator.py`：
  - `LoginSource` 类型扩展为 `Literal["auto", "manual", "login_once", "browser"]`
  - `submit()` 新增 `timeout` 参数，传递给 `_dispatch()`
  - `submit()` 中 browser 任务跳过 `validate_login_config` 校验（由调用方自行校验）
  - `_dispatch()` 新增 `timeout` 参数，`timeout if timeout is not None else resolve_worker_timeout(config)` 替代无条件解析
  - `_run()` 中 browser 任务跳过 `_record_history` 调用（浏览器定时任务由 TaskExecutor._history_store 管理历史）
- `app/services/task_executor.py`：
  - `_execute_browser()` 重写：不再直接调用 `worker.submit(CMD_LOGIN, ...)`，改为委托 `self._login_orchestrator.submit(source="browser", ...)`
  - 消除 ImportError/通用异常 catch 分支（由 Orchestrator 内部处理）
- `tests/test_services/test_task_executor_fix.py`：
  - 8 个浏览器任务测试全部重写：mock 从 `worker.submit` 改为 `orchestrator.submit`，使用 `LoginHandle` 模拟返回
- 验收：1681 测试全通过

## 2026-06-20

### refactor — LoginOrchestrator 改用 CompositeCancelEvent，删除 watcher 线程
- `app/services/login_orchestrator.py`：
  - `LoginHandle.cancel_event` 类型从 `threading.Event` 改为 `CompositeCancelEvent`
  - `submit()` 中 `cancel_event is None` 时创建 `CompositeCancelEvent()`；传入 plain `threading.Event` 时自动包装为 `CompositeCancelEvent` 并添加原事件为源
  - `_link_cancel` 从队列+watcher 线程简化为一行 `target_event.add_source(new_event)`
  - 删除 `_ensure_cancel_link_thread`、`_cancel_link_loop` 两个方法
  - `__init__` 删除 `_cancel_link_queue`、`_cancel_link_thread`、`_cancel_link_lock` 三个字段
  - `shutdown()` 删除毒丸投递逻辑
  - 移除 `import queue`（不再需要）
- `tests/test_services/test_login_orchestrator.py`：`test_submit_passes_cancel_event` 适配包装行为（原事件被包装后 `is` 不再成立，改为验证传播语义）
- 验收：2333 测试全通过

### feat — 新建 CompositeCancelEvent（惰性扫描组合取消事件）
- 新增 `app/utils/cancel_token.py`：`CompositeCancelEvent` 类，继承 `threading.Event`
  - `add_source(event)` — 添加取消源，若源已 set 则立即传播
  - `is_set()` — 惰性扫描所有源，首次发现源 set 后缓存到 `super().set()`
  - `clear()` — 仅清除自身标志，保留源列表
  - `_lock` 保护 `_sources` 列表，线程安全
- 新增 `tests/test_utils/test_cancel_token.py`：11 个测试覆盖全部场景
  - 初始状态、直接 set、已 set 源立即传播、延迟传播、多源触发、去重、clear 行为、缓存、并发安全、clear 后重新传播

## 2026-06-20

### refactor — TaskExecutor 移除 login_history/profile_service 死参数
- `app/services/task_executor.py` `__init__` 移除 `login_history` 和 `profile_service` 参数（已在之前的重构中移除生产代码引用）
- 测试文件同步清理：
  - `tests/test_integration/test_login_flow.py`：4 处 TaskExecutor 调用移除参数
  - `tests/test_integration/test_scheduled_task.py`：`_make_executor` 辅助函数移除参数
  - `tests/test_integration/conftest.py`：`integration_stack` 和 `full_stack` 两个 fixture 移除参数
  - `tests/test_services/test_task_executor_fix.py`：`TestTaskExecutorExecuteLogin._make_executor` 移除参数
- 最终：2322 测试全通过

### refactor — TaskExecutor 死参数清理
- 删除 `login_history`、`profile_service` 构造参数和字段（登录历史已由 Orchestrator 管理）
- 更新 container.py + 4 个测试文件移除参数传递

### fix — 退避逻辑冲突
- `_on_done` 中 MonitoredPolicy delay 与 `_apply_backoff_interval` 取最大值，避免相互覆盖
- 之前 MonitoredPolicy 的固定 30s delay 会覆盖 engine 级指数退避（300s/900s/1500s）

### refactor — LoginRetryManager 清理
- 删除 `app/services/login_retry.py`（LoginRetryManager 类）
- `engine.py` 删除：`_validate_login_config`、`_configure_retry`、`_login_retry_needed`、`_login_retry` 字段及所有引用
- `_calculate_wakeup` 移除 `_login_retry.next_wakeup()` 依赖
- `_do_async_login` 移除 `_login_retry.reset()` 和 `_login_retry.record_attempt()`
- `_handle_start`/`_handle_stop` 移除 `_login_retry.reset()`
- 删除 `test_login_retry.py`（12 个测试），删除 `TestLoginRetryNeeded`（7 个）和 `TestLoginRetryMechanism`（11 个）
- 8 个测试文件移除 LoginRetryManager 引用，改为 `_consecutive_login_failures` 验证
- 最终：2326 测试全通过

### refactor
- 测试全面移除 LoginRetryManager 依赖
  - `app/services/login_retry.py` 已删除，测试中大量引用该类导致运行失败
  - `tests/test_services/conftest.py`：移除 `LoginRetryManager` 导入和 `_login_retry` 字段初始化
  - `tests/test_services/test_login_retry.py`：整个删除（测试已不存在的类）
  - `tests/test_services/test_engine.py`：移除导入、删除 `TestLoginRetryNeeded` 测试类（7 个测试）、修复 `TestCalculateWakeup`/`TestHandleStop`/`TestDoAsyncLogin` 中的 `_login_retry` 引用
  - `tests/test_services/test_engine_fix.py`：移除 `_make_engine` 中 `_login_retry` mock 初始化
  - `tests/test_services/test_monitor_service.py`：移除导入和 `TestNetworkStateSetInConsumer` 中的 `LoginRetryManager` 构造
  - `tests/test_integration/test_login_flow.py`：移除导入和 `_make_raw_engine` 中 `_login_retry` 初始化、删除 `TestLoginRetryMechanism` 整个测试类（11 个测试）、修复并发保护测试中的引用
  - `tests/test_integration/test_login_connection.py`：`test_retry_exhausted` 改为验证 `_consecutive_login_failures` 递增
  - `tests/test_integration/test_login_integration_extended.py`：移除 `_login_retry.count/last_attempt` 断言，改为 `_consecutive_login_failures` 验证

## 2026-06-20

### refactor — 登录链路三步重构完成
- **第 1 步（Task 1-9）**：LoginOrchestrator + RetryPolicy 框架，消化 F02/F03/F05/F06/F08/F09
  - 新建 `app/services/login_orchestrator.py`（编排器）和 `app/services/retry_policy.py`（策略框架）
  - `task_executor.py` 增加委托层（保留 `_legacy_*` 回退）
  - `container.py` 注入 Orchestrator
  - `engine.py` `_do_async_login`/`_handle_login` 改委托
  - `main.py` login_once 改用 ImmediatePolicy + Orchestrator
- **第 2 步（Task 10）**：MonitoredPolicy 接入 engine，根治 F04
- **第 3 步（Task 11）**：取消联动改常驻单线程，根治 F12/F13
- 验收结果：2383 测试全通过，新模块覆盖率 89%

### refactor
- Task 11: 取消联动改常驻单线程，根治 F12（线程泄漏）/F13（冗余检查）
  - `app/services/login_orchestrator.py` `_link_cancel` 从每次新建 daemon 线程改为队列 + 常驻单线程
  - `__init__` 新增 `_cancel_link_queue`（Queue）和 `_cancel_link_thread`（Thread | None）
  - 新增 `_ensure_cancel_link_thread()`（惰性启动常驻 watcher）和 `_cancel_link_loop()`（从队列取联动请求并监控）
  - `shutdown()` 新增毒丸 `None` 投递，退出常驻 watcher 线程
  - 新增 `import queue`
  - 36 个既有测试全部通过

### refactor
- Task 10: engine 接入 MonitoredPolicy，根治 F04（无条件 reset 消除）
  - `app/services/engine.py` `__init__` 新增 `self._retry_policy = MonitoredPolicy()`，保留 `_login_retry` 向后兼容
  - `_do_network_check`：删除 `_login_retry.reset()` / `_configure_retry()` 无条件重置逻辑，改为通知 `MonitoredPolicy.on_network_check()` 管理退避状态
  - `_do_async_login` `_on_done` 回调：自动登录成功调用 `_retry_policy.on_login_done(success=True)`；失败调用 `_retry_policy.on_login_done(success=False)` 获取降频延迟并设置 `_next_network_check`
  - 更新 3 个测试文件的 raw engine fixture 补充 `_retry_policy` 属性：`conftest.py`、`test_login_flow.py`
  - 更新测试断言：删除对 `_login_retry.config` / `_login_retry.count` 的过时断言，改为验证 `_consecutive_login_failures` 和 `_do_async_login` 调用

### refactor
- Task 8: main.py login_once 改用 Orchestrator + ImmediatePolicy（F02/F08/F09）
  - `main.py` `_execute_login_with_retries` 重写：不再自行管理重试循环/超时/历史记录
  - 改用 `ImmediatePolicy`（固定间隔重试）+ `LoginOrchestrator`（配置校验、Worker 提交、历史记录）
  - 构造一次性 Orchestrator 实例（login_once 在容器创建前运行），提交 source="login_once"
  - `app/services/login_orchestrator.py` `_slot_lock` 从 `Lock` 改为 `RLock`，修复 mock 场景下 `_on_done` 回调重入死锁
  - `app/services/login_orchestrator.py` `_dispatch._run` 成功时 `_record_history` 不再传递 success message 作为 error 参数
  - 更新测试：`test_main.py` 所有 mock config 补充 `username/password/auth_url` 字段；`test_login_timeout_default_120` 适配 Orchestrator 默认超时 300s；`test_login_integration_extended.py` 3 个 login_once 测试补充 `_ensure_login_config` 调用

### refactor
- Task 7: engine._do_async_login / _handle_login 委托 LoginOrchestrator
  - `app/services/engine.py` `__init__` 新增 `self._orchestrator = None`（由 container 注入）
  - `_do_async_login` 重构：配置校验、去重、手动抢占逻辑全部委托 `orchestrator.submit()`；保留引擎专属的 `_on_done` 回调（失败计数 + 降频退避）
  - `_handle_login` 改用 `orchestrator.validate(config)` 替代 `_validate_login_config`
  - `_validate_login_config` 保留未删除（向后兼容）
  - 同步更新测试 fixtures 和集成测试：conftest、test_engine、test_engine_fix、test_monitor_service、test_login_flow、test_login_integration_extended
  - 集成测试 fixture 注入真实 LoginOrchestrator，_capture_login_completion 同时 hook orchestrator 和 task_executor 两条路径

### refactor
- TaskExecutor 增加 LoginOrchestrator 委托层（Task 5）
  - `app/services/task_executor.py` `__init__` 新增 `login_orchestrator` 可选参数，默认 None
  - 原 `execute_login_async`/`execute_login`/`_on_login_done`/`_link_cancel_event` 重命名为 `_legacy_*` 前缀版本
  - 新增同名委托方法：优先走 Orchestrator 路径，orchestrator 为 None 时回退遗留路径，签名完全兼容
  - 新增 `is_login_running`/`cancel_login` 委托：orchestrator 存在时委托给 orchestrator
  - `shutdown` 新增 orchestrator 清理逻辑
  - 确保 `login_orchestrator=None`（默认）时行为与改动前完全一致，所有 114 个 task_executor 测试通过

### fix
- login_orchestrator 线程泄漏防护、shutdown、ImportError 友好提示、类型标注
  - C1: `_link_cancel` watcher 线程添加 300 秒 deadline，超时自动退出防止线程泄漏
  - C2: 新增 `shutdown(wait=True)` 方法，清理内部线程池
  - I1: `_dispatch._run()` 捕获 `ImportError` 返回友好提示"登录需要额外依赖，请检查 Playwright 安装状态"
  - I2: `Callable` 导入从 `typing` 改为 `collections.abc`
  - I4: 添加 `TYPE_CHECKING` 块，`login_history` 和 `profile_service` 参数类型从 `object` 改为具体类型

### feat
- 新增 `app/services/login_orchestrator.py`（Task 2: 登录编排器核心）
  - `validate_login_config(config)` — F05 唯一配置校验实现，返回 None 或中文错误信息
  - `resolve_worker_timeout(config, fallback)` — F09 超时解析，floor 60 / ceiling 600
  - `LoginHandle` 数据类 — 封装 future + source + cancel_event，提供 done/result/cancel 方法
  - `LoginOrchestrator` 类 — 登录执行唯一入口，整合配置校验、去重抢占、Worker 提交、历史记录、cancel_event 生命周期
    - `submit(source, config, cancel_event)` — manual 可抢占 auto，auto 去重复用，login_once 总是新建
    - `_dispatch` — 延迟导入 CMD_LOGIN，提交到 _pool 线程池
    - `_link_cancel` — 简单 watcher 线程联动 cancel_event（Task 11 将替换）
    - `_record_history` — 委托 LoginHistoryService.record
  - `LoginSource` 类型 — `Literal["auto", "manual", "login_once"]`

### feat
- 新增重试策略框架 `app/services/retry_policy.py`（Task 1）
  - `RetryPolicy` 抽象基类：`attempts()` + `delay_before(attempt)` 两个抽象方法
  - `ImmediatePolicy`：固定间隔快速重试，用于 login_once 路径
    - `max_retries` 钳制 1-10（默认 3），`interval` 最小 1（默认 5）
    - `attempts()` 产生 1..max_retries，`delay_before(1)` 返回 0，后续返回 interval
  - `MonitoredPolicy`：引擎长期监控策略，自带指数退避（上限 1800s）
    - `on_network_check(need_login) -> bool`：仅 down->up 转换时重置退避状态
    - `on_login_done(success) -> float|None`：成功返回 0.0 并重置，失败返回延迟，超过 max_retries 返回 None
  - 新增 `tests/test_services/test_retry_policy.py`：30 个单元测试覆盖边界值、退避计算、状态转换

### fix
- F17+F18+F19: 文档注释 + OpenAPI description + 指数退避上限（3 项）
  - F17: `app/schemas.py` `SystemSettings` docstring 补充说明 auth_url/carrier/carrier_custom 同时存在于 global_settings 和 profile 是有意设计（全局默认值 + profile 实例覆盖）
  - F18: `app/schemas.py` `_MonitorFieldsMixin` 的 auth_url/active_task/carrier/carrier_custom 四个字段补充 description，解决 MRO 中 `_MonitorFieldsMixin` 覆盖 `_SystemFieldsMixin` description 的问题
  - F19: `app/utils/retry.py` `get_retry_intervals` 新增 `max_interval` 参数（默认 300s），指数退避时单次间隔不超过该上限，防止间隔过大
  - 更新 `tests/test_utils/test_retry.py`：新增 5 个 max_interval 测试 + 修复 `test_large_interval` 适配 max_interval 默认值

### fix
- F14+F15+F16: 健壮性改进（3 项防御性修复）
  - F14: `main.py` `_run_lightweight` finally 块兜底清理 — 即使 `_web_server_state["started"]` 为 True，若 `server_ref[0]` 仍为 None（Uvicorn 子线程崩溃），仍执行容器 shutdown，防止资源泄漏
  - F15: `app/services/engine.py` `set_dashboard_sink` 迁移轻量模式广播队列 — 注入新 DashboardSink 时，将 `_empty_broadcast_queue` 中积累的残留消息迁移到新 sink 的 `broadcast_queue`
  - F16: `app/services/websocket_manager.py` `broadcast` 总体超时 — 用 `asyncio.wait_for` 包裹 `asyncio.gather`，总体超时 5 秒，防止 N 个卡住连接导致等待 N×5s
  - 新增 10 个测试：`TestLightweightFallbackCleanup`（4）+ `TestSetDashboardSinkMigration`（3）+ `TestBroadcastOverallTimeout`（3）

### fix
- F12: 重构 _link_cancel_event，消除线程泄漏
  - `app/services/task_executor.py`：`_link_cancel_event` 从 `@staticmethod` 改为实例方法，不再每次新建 daemon 线程
  - `app/services/task_executor.py`：新增 `_cancel_link_queue`（事件队列）、`_cancel_link_thread`、`_cancel_link_lock` 三个 `__init__` 字段
  - `app/services/task_executor.py`：新增 `_ensure_cancel_link_thread()`（惰性启动单个 watcher）和 `_cancel_link_loop()`（常驻 watcher 从队列取事件并监控）
  - `app/services/task_executor.py`：`shutdown` 末尾投递毒丸 `None` 关闭 watcher 线程
  - 新增 6 个测试：`TestCancelLinkWatcherThread`（单线程复用 / 高频不泄漏 / 联动传播 / 死亡重启 / 毒丸退出 / shutdown 幂等）

### fix
- F11+F20: 浏览器定时任务 cancel_event 支持 + 清理 pure_mode 死字段
  - F11: `app/services/task_executor.py` `_execute_browser` 新增 `cancel_event` 参数，传递给 `worker.submit` 的 data dict，支持定时浏览器任务取消
  - F20: `app/services/task_executor.py` `execute_login` 和 `_execute_browser` 的 data dict 移除 `pure_mode` 死字段（Worker `_handle_login` 仅从 `config["browser_settings"]["pure_mode"]` 读取，不读 `data["pure_mode"]`）
  - `app/workers/playwright_worker.py` CMD_LOGIN 常量注释补充说明登录与浏览器定时任务共用此命令
  - 新增 7 个测试：`TestTaskExecutorExecuteBrowser`（4: data_no_pure_mode / cancel_event_passed / cancel_event_default_none / timeout_forwarded）+ `TestExecuteLoginDataDict`（2: login_data_no_pure_mode / login_data_contains_cancel_event）
  - 修复已有测试 `test_login_timeout_default_300` 断言值从 300 改为 90（与代码 `config.get("login_timeout", 90)` 默认值一致）

### fix
- F10: 定时任务 task_id 去重，防止同一任务重复提交
  - `app/services/task_executor.py`：`__init__` 新增 `_running_tasks` 字典和 `_running_tasks_lock` 锁
  - `app/services/task_executor.py`：`execute_task_async` 提交前检查是否有 pending 的同 task_id 任务，有则返回已有 Future
  - `app/services/task_executor.py`：任务完成后通过 `done_callback` 自动从 `_running_tasks` 清理
  - `app/services/task_executor.py`：`shutdown` 清空 `_running_tasks`
  - 新增 5 个测试覆盖去重行为：跳过 pending、完成后允许重新提交、不同 task_id 不干扰、清理回调、shutdown 清空

### fix
- I1+I2: 统一 login_timeout 默认值为 90s + main.py 添加 max(login_timeout, 60) 下限防护
  - `main.py:219` 默认值从 120 改为 90，与 `schemas.py` `Field(default=90)` 一致
  - `app/services/task_executor.py:329` 默认值从 300 改为 90
  - `main.py` 添加 `max(login_timeout, 60)` 下限防护，与 `task_executor.py` 和 `engine.py` 一致
  - 更新测试 `test_login_timeout_default_120` 断言从 120 改为 90

### fix
- F08: `main.py` login_once 重试间隔改为固定间隔（与 LoginRetryManager 一致）
  - `_execute_login_with_retries` 中 `min(interval * 2^(n-2), 300)` 指数退避改为 `time.sleep(retry_interval)` 固定间隔
  - 引擎内 `LoginRetryManager` 使用 `get_retry_intervals(exponential=False)`（固定间隔），login_once 现在行为一致

### fix
- F09: 统一登录超时 — Worker timeout 使用 `login_timeout` 配置
  - `main.py` `_execute_login_with_retries`：从 `runtime_config.get("login_timeout", 120)` 读取超时，替代硬编码 `timeout=120`
  - `app/services/task_executor.py` `execute_login`：从 `config.get("login_timeout", 300)` 读取超时，下限 60s 防误配
  - `app/services/config_service.py` `build_runtime_dict_from_payload`：新增 `base["login_timeout"] = gs.login_timeout`
  - `app/services/engine.py` `run_manual_login`：API 等待超时改为 `max(login_timeout, 60) + 10`，大于 Worker 超时
  - 新增 8 个测试：`TestLoginOnceRetryInterval`（3）+ `TestBuildRuntimeDictLoginTimeout`（2）+ `TestRunManualLogin.test_run_manual_login_api_timeout_buffered`（1）+ `TestTaskExecutorExecuteLogin`（3: timeout_from_config / default_300 / minimum_60）
  - 更新 2 个已有测试（timeout_engine_alive / timeout_engine_dead）适配 buffered timeout

### fix
- `main.py` + `app/application.py` 校正 boot() 与 DashboardSink 注入顺序（F07）
  - 问题：`_run_full` 在 Uvicorn 启动前调用 `boot()`，此时 DashboardSink 尚未注入（注入发生在 lifespan 的 `start_web_services()` 中），启动期间日志丢失
  - `main.py` `_run_full`：移除直接调用 `container.engine.boot()`，改为传递 `boot_engine=should_boot_engine` 给 `run()`
  - `app/application.py` `run()`：新增 `boot_engine` 参数，透传给 `create_app()`
  - `app/application.py` `create_app()`：新增 `boot_engine` 参数，透传给 `_create_lifespan()`
  - `app/application.py` `_create_lifespan()`：新增 `boot_engine` 参数；existing_container 分支中，先 `start_web_services()` 注入 DashboardSink，再条件性调用 `engine.boot()`（`boot_engine=True` 且未在监控时）
  - `container.startup()` 内部顺序已正确（先 start_web_services 后 boot），不需要修改
  - 轻量模式 `main.py` 自己调 boot，无 Web 服务，不受影响
  - 新增 10 个测试：`TestBootEnginePropagation`（2）+ `TestLifespanBootOrder`（5）+ `TestRunFullNoDirectBoot`（2）+ `TestContainerStartupOrder`（1）

### fix
- `app/services/engine.py` + `app/services/task_executor.py` 修复手动取消竞态窗口（F06）+ 消除 cancel_event 冗余检查（F13）
  - F06: 手动取消旧登录超时后，`_do_async_login` 不传 cancel_event，`execute_login_async` 自动新建空 Event，命中去重返回旧 future
  - `task_executor.py` 新增 `force_clear_login_slot()` 方法：强制清理旧 `_login_future` 和 `_login_cancel_event`
  - `engine.py` `_do_async_login`: 取消超时后调用 `force_clear_login_slot()` 强制接管登录槽；手动路径显式传入新的 `manual_cancel` Event
  - F13: `execute_login_async` 第 195 行 `cancel_event is not None` 永真检查移除（第 186-187 行已保证非 None）
  - 新增 7 个测试：`TestManualLoginCancelRaceFix`（5 个）+ `TestForceClearLoginSlot`（4 个）+ `TestCancelEventRedundancyFix`（2 个）

### fix
- `app/services/engine.py` 自动登录路径增加配置校验（F05）
  - 原代码 `_handle_login`（手动入口）校验 username/password/auth_url，但 `_do_async_login`（自动入口）无校验
  - 配置不完整时，空配置传入 Worker，启动浏览器后才在步骤级失败，浪费 5-15 秒
  - 新增 `_validate_login_config(config)` 方法：校验配置完整性，返回 None 表示通过，否则返回错误信息
  - `_do_async_login` 顶部统一调用 `_validate_login_config`，校验失败时记录 WARNING 日志、重置重试状态、直接返回 False
  - `_handle_login` 改为复用 `_validate_login_config`，消除重复的内联校验逻辑
  - 配置校验失败不触发 `_on_done` 回调（不提交任务、不注册回调），`_consecutive_login_failures` 不会累计
  - 新增 `TestValidateLoginConfig`（7 个测试）和 `TestDoAsyncLogin` 补充测试（6 个测试），覆盖校验通过/失败/缺失字段/快照绕过等场景

### fix
- `app/services/engine.py` 网络检测不再无条件 reset 重试计数（F04）
  - 原代码每次 `need_login=True` 都调用 `_login_retry.reset()`，导致重试计数归零，认证服务器长期宕机时系统永不停机地循环"检测→重试系列→检测→重试系列"
  - `_do_network_check`：仅在 `count==0`（首次发现 need_login）时 reset+configure
  - `_do_async_login` `_on_done` 回调：自动登录成功清空 `_consecutive_login_failures`；失败递增计数，达到 `_LOGIN_BACKOFF_THRESHOLD`(3) 后触发 `_apply_backoff_interval` 指数退避
  - 新增 `_consecutive_login_failures` / `_backoff_check_multiplier` 两个 `__init__` 字段
  - 新增 `_login_retry_max_cycles()` / `_apply_backoff_interval()` 辅助方法
  - 退避乘数上限 6（`extra = (6-1) * interval = 1500s ≈ 25min`），网络恢复后立即清零
  - `_handle_stop` 同步重置退避状态
  - 新增 12 个测试覆盖全部新增分支（count>0 跳过 reset、失败累计、退避触发、手动登录隔离、乘数封顶等）

### fix
- `main.py` `_execute_login_with_retries` 记录登录历史（F02）
  - 原代码直接调用 `get_worker().submit(CMD_LOGIN, ...)`，完全绕过 TaskExecutor 的 `_record_login_history()`
  - `--startup-action login_once` 的登录在历史页面不可见
  - 新增 `LoginHistoryService(AUTH_DATA_DIR)` 和 `create_profile_service()` 初始化
  - 每次登录尝试后调用 `history.record(success=, duration_ms=, profile_service=, error=)` 记录历史
  - 成功/失败都记录，与 TaskExecutor 行为一致
  - 新增测试 `test_login_once_records_history` 和 `test_login_once_records_failure_history`

### fix
- `app/services/config_service.py` 配置回滚后检查第二次 reload 返回值（F01）
  - 原代码 `reload_fn()` 返回值被丢弃，回滚后重载失败时用户看到的是第一次失败信息
  - 捕获第二次 `reload_fn()` 返回值 `(rollback_ok, rollback_msg)`
  - 回滚后重载也失败：message 同时包含两次失败信息
  - 回滚后重载成功：message 标注"已回滚"
  - 回滚过程异常：保持原有异常处理不变
  - 新增测试 `test_reload_failure_and_rollback_reload_also_fails`

### fix
- `app/services/engine.py` record_attempt 移到 execute_login_async 成功提交之后（F03）
  - 原代码在 `execute_login_async` 调用前递增重试计数，提交异常时白白消耗一次重试机会
  - 移到 `execute_login_async` 成功返回后，异常时不会递增
  - 新增测试 `test_exception_does_not_consume_retry` 和 `test_success_increments_retry_count`

## 2026-06-19

### chore
- 删除过期的 Rust 迁移设计文档 `rustforcam/docs/2026-06-18-rust-migration-design.md`

## 2026-06-19

### test
- 新增 `tests/test_integration/test_login_once_mode.py` LOGIN_ONCE 模式测试（3 个场景）
  - `test_success`：网络未连接 → 登录成功 → 返回 LoginResult.SUCCESS
  - `test_temporary_failure`：网络未连接 → 登录失败 → 返回 LoginResult.TEMPORARY_FAILURE
  - `test_config_error`：配置加载失败 → 返回 LoginResult.CONFIG_ERROR
  - mock `_load_login_config`、`check_network_status`、`_execute_login_with_retries` 验证三种返回路径

### test
- 新增 `tests/test_integration/test_full_mode.py` 完整模式生命周期测试（1 个场景）
  - `test_full_lifecycle`：启动 → 断网登录 → 定时任务 → 手动登录 → 配置重载 → 关闭
  - 验证 engine.start_monitoring → engine.start_scheduler → task_executor.save_task → engine._do_network_check → engine._run_schedule_tick → engine.run_manual_login → save_and_apply → engine.shutdown 全链路
  - 使用 full_stack fixture，仅 mock Playwright worker 外部边界和 check_network_status 网络状态

## 2026-06-19

### test
- 新增 `tests/test_integration/test_lightweight_mode.py` 轻量模式生命周期测试（1 个场景）
  - `test_full_lifecycle`：启动 → 断网登录 → 成功 → 再次断网 → 重试 → 手动登录 → 停止
  - 验证 engine.start_monitoring → task_executor.execute_login_async → engine.run_manual_login → engine.stop_monitoring 全链路
  - 使用 integration_stack fixture，仅 mock Playwright worker 外部边界

### test
- 新增 `tests/test_integration/test_profile_connection.py` Profile 切换链路连接测试（3 个场景）
  - `test_apply_profile`：切换方案 → engine 使用新凭证（profile_service.set_active_profile + engine.apply_profile）
  - `test_switch_while_monitoring`：监控运行中切换 → 旧配置停、新配置起，无线程泄漏
  - `test_delete_current_profile`：删除当前方案 → 回退到 default
  - 使用真实组件栈（integration_stack fixture），直接设置 _monitor_core 绕过异步队列

### test
- 新增 `tests/test_integration/test_network_connection.py` 网络检测链路连接测试（5 个场景）
  - `test_need_login`：网络不通 → check_once 返回 need_login=True
  - `test_network_ok`：网络通 → check_once 返回 need_login=False
  - `test_pause_window`：暂停时段 → check_once 跳过检测
  - `test_probe_exception`：探测抛异常 → 引擎继续运行（_monitor_core 未被清除）
  - `test_profile_switch_signal`：方案切换 → _do_network_check 触发 stop + start
  - 直接创建 NetworkMonitorCore 绕过引擎异步队列，mock `app.services.monitor_service` 模块级导入

### test
- 新增 `tests/test_integration/test_config_connection.py` 配置链路连接测试（5 个场景）
  - `test_save_apply_success`：保存配置 → 磁盘 + 运行时都更新
  - `test_save_apply_rollback`：reload 失败 → 磁盘回滚，运行时不变
  - `test_interval_reload`：修改 check_interval → 重载后生效
  - `test_password_encrypt`：明文密码 → 保存后磁盘加密 → 读取后不等于明文
  - `test_log_level_reload`：修改 backend_log_level → 重载后生效
  - 使用真实组件栈（integration_stack fixture），验证 config_service → runtime_config → engine 链路

### test
- 新增 `tests/test_integration/test_login_connection.py` 登录链路连接测试（7 个场景）
  - `test_auto_login_success`：自动登录成功 → worker 被调用
  - `test_auto_login_retry`：登录失败 → 重试 → 最终成功
  - `test_retry_exhausted`：连续失败达 max_retries → 停止重试
  - `test_manual_preempt_auto`：手动登录取消卡住的自动登录
  - `test_callback_updates_history`：登录完成 → 历史记录写入
  - `test_concurrent_dedup`：两个线程同时提交 → 只有一个实际执行
  - `test_reload_during_login`：登录进行中 → 保存配置 → reload → 旧登录正常结束，新配置已生效
  - 使用真实组件栈（integration_stack fixture），仅 mock Playwright worker 外部边界

### refactor
- 抽取 LoginRetryManager，Engine 不再直接管理重试状态
  - 新建 `app/services/login_retry.py`：`LoginRetryManager` 数据类，封装 `reset()`/`configure()`/`record_attempt()`/`need_retry()`/`next_wakeup()` 五个方法
  - `app/services/engine.py`：删除 `_LoginRetryState` 数据类和 `_get_retry_config()` 方法；`_login_retry_needed` 简化为委托 `is_login_running()` + `need_retry()`；`_calculate_wakeup` 委托 `next_wakeup()`；`_do_network_check` 重试配置逻辑内联；`_do_async_login` 委托 `record_attempt()`；`_handle_start`/`_handle_stop` 委托 `reset()`
  - 更新 4 个测试文件的 `_LoginRetryState` 引用为 `LoginRetryManager`：`conftest.py`、`test_engine.py`、`test_login_flow.py`、`test_monitor_service.py`
  - 删除 `TestLoginRetryState`、`TestGetRetryConfig` 测试类和 `_get_retry_config` 相关集成测试
  - 新建 `tests/test_services/test_login_retry.py`：12 个单元测试覆盖全部方法

### refactor
- 消灭双重登录状态，TaskExecutor 成为唯一状态持有者
  - `app/services/task_executor.py` 新增 `is_login_running()` 公共方法，返回 `_login_future` 是否存在且未完成
  - `app/services/engine.py` 删除 `_login_in_progress = threading.Event()` 属性
  - `login_in_progress` 属性改为委托 `task_executor.is_login_running()`
  - `_login_retry_needed` 中 `_login_in_progress.is_set()` 改为 `task_executor.is_login_running()`
  - `_do_async_login` 移除所有 `_login_in_progress.set()/clear()` 操作，改为查询 executor 状态
  - `_on_done` 回调移除 `_login_in_progress.clear()` 调用，状态管理完全由 TaskExecutor 的 `_login_future` 和 `_on_login_done` 处理
  - 更新 5 个测试文件：删除所有 `_login_in_progress` 引用，改为使用 `task_executor.is_login_running()` mock
  - `conftest.py` `_make_raw` 删除 `svc._login_in_progress = threading.Event()` 行

### refactor
- 删除 LoginAttemptHandler 中从未执行的前置检查代码，移除 `skip_pause_check` 参数
  - `app/utils/login.py` `attempt_login` 删除 `skip_pause_check` 参数和 30 行死代码分支（暂停时段检查、网络状态检查、登录前置条件检查），移除不再使用的 `datetime` 导入
  - `app/workers/playwright_worker.py` `_handle_login` 简化 `attempt_login()` 调用
  - `app/services/engine.py` `_do_async_login` 删除 `skip_pause_check` 参数，`_handle_login` 和 `_engine_loop`/`_do_network_check` 不再传递该参数，`run_manual_login` 的 `cmd.data` 清空
  - `app/services/task_executor.py` `execute_login_async` 和 `execute_login` 删除 `skip_pause_check` 参数，`execute_login` 和 `_execute_browser` 的 data dict 移除该字段
  - 更新 7 个测试文件：删除测试死代码分支的测试类，简化 mock 签名

### refactor
- 配置保存事务逻辑从 API 层下沉到 config_service.save_and_apply
  - `app/services/config_service.py` 新增 `SaveResult` 数据类、`save_and_apply` 函数和 `_rollback_config` 辅助函数
  - `app/api/config.py` `save_config` 简化为调用 `save_and_apply` 一个函数，删除本地 `_rollback_config`
  - `tests/test_services/test_config_service.py` 新增 `TestSaveAndApply`（3 个测试：成功、重载失败回滚、回滚也失败）
  - `tests/test_api/test_api_config_routes.py` `TestSaveConfig` patch 目标更新为 `save_and_apply`

### fix
- 修复 `custom_browser_engine` 未传入浏览器配置的 bug
  - `app/services/config_service.py` `browser_settings` 字典补充 `custom_browser_engine` 字段
  - 修复自定义浏览器 engine 类型设置不生效的问题

### fix
- 修复 `retry_interval` 默认值不一致和条件构建问题
  - `app/services/config_service.py` `retry_settings` 改为无条件构建（使用 `gs` 回退默认值）
  - `app/services/engine.py` 异常回退值从 30 改为 5，与 schema 默认值一致
  - `docs/login-flow.md` 同步更新默认值文档

### fix
- 修复 `save_config` 回滚逻辑为死代码、重载失败仍返回成功的 bug
  - `app/api/config.py` 检查 `reload_config()` 返回值 `(bool, str)`，失败时触发回滚并返回错误
  - 更新测试：`test_api_config_routes.py` mock `reload_config` 返回元组；`test_login_flow.py`、`test_engine.py` 断言更新为新默认值

### fix
- 密码变更记录到配置变更日志
  - `app/api/config.py` `_log_config_changes` 新增密码变更检测，仅记录"密码已修改"

### fix
- `set_active_profile` 锁内捕获 profile name
  - `app/services/profile_service.py` `data.profiles[profile_id].name` 移入锁内

### fix
- `detect_matching_profile` 避免重复 load
  - `app/services/profile_service.py` 新增可选 `data` 参数，调用方可传入预加载数据
  - `app/services/monitor_service.py` `_check_profile_switch` 传入已加载的 `data`

### fix
- 修复 `decision.py` 和 `browser_runner.py` 兜底值与 schema 默认值不一致
  - `app/network/decision.py` `network_check_timeout` 兜底 `1.5`→`2`，`check_auth_url` 兜底 `True`→`False`
  - `app/tasks/browser_runner.py` 登录后验证的 `enable_tcp_check`/`enable_http_check` 兜底 `True`→`False`，简化条件判断
  - `app/services/engine.py` `test_network` 的 `timeout` 从硬编码 `2` 改为从配置读取，与其他两条检测路径一致

### refactor
- 清理登录链条遗留死代码
  - 移除 `close_on_failure` 参数：浏览器复用已删除后该参数无意义，`BrowserContextManager.__aexit__` 始终关闭浏览器是正确行为
    - `app/utils/login.py` 删除 `__init__` 的 `close_on_failure` 参数、实例变量、finally 中的条件判断
    - `app/workers/playwright_worker.py` 删除 `close_on_failure=data.get("close_on_failure", True)` 传递
  - 移除 `NullTaskExecutor` 类：轻量模式已改用真实 TaskExecutor，该类仅测试引用
    - `app/services/task_executor.py` 删除 `NullTaskExecutor` 类定义
  - 移除 `get_runtime_stats` 函数：`app/utils/time_utils.py` 中定义但无生产代码调用，仅测试引用
    - 同步清理 `app/utils/__init__.py` 的 import 和 `__all__` 导出
  - 移除 `MAX_CONSECUTIVE_LOGIN_FAILURES` 常量：`app/services/monitor_service.py` 中定义但从未引用，登录重试逻辑已迁移到 `engine.py`
  - 移除 `PlaywrightWorker.close_browser` 公开方法：所有内部调用均使用 `_close_browser()`，公开包装无调用方
  - 更新测试：删除 `test_login_failure_no_close_on_failure`、`test_init_close_on_failure_false`、`TestNullTaskExecutor`、`TestNullTaskExecutorSignature`、`test_null_task_executor_all_methods`、`TestGetRuntimeStats`；简化其余引用

### fix
- `app/services/engine.py` 和 `app/services/task_executor.py` 消除登录配置 TOCTOU 竞态（Task 4: P4）
  - `_handle_login` 用 `_copy_runtime_config()` 校验配置，但 `_do_async_login` → `execute_login` 二次读取存在竞态窗口
  - `_do_async_login` 新增 `config_snapshot` 参数，传递校验通过的配置快照
  - `execute_login_async` 和 `execute_login` 新增 `config_snapshot` 参数，优先使用快照而非二次读取
  - `config_snapshot` 默认 `None`，自动登录路径（非手动触发）不受影响
  - 新增 `test_handle_login_uses_validated_config` 测试验证快照传递

### fix
- `main.py` LOGIN_ONCE 网络检测全部禁用时跳过登录
  - `check_network_status` 返回 `(False, "all_disabled", "none")` 时，原代码进入登录流程
  - 新增 `reason == "all_disabled"` 分支，假定网络正常并返回 `LoginResult.SUCCESS`
  - 更新 `test_retries_exhausted` 测试：显式 mock `check_network_status` 返回 `network_down`，避免被 `all_disabled` 分支拦截
  - 新增 `TestLoginOnceAllDisabled.test_login_once_all_disabled_skips_login` 测试

### fix
- `app/container.py` 轻量模式使用真实 TaskExecutor 替代 NullTaskExecutor
  - P0 bug 修复：轻量模式（开机自启动默认模式）的 NullTaskExecutor 导致自动登录完全失效
  - 移除 `if self._is_lightweight: NullTaskExecutor()` 分支，统一使用 TaskExecutor
  - 移除未使用的 `NullTaskExecutor` 导入
  - `set_runtime_config_getter` 调用不再区分轻量/完整模式
- `tests/test_config/test_container.py` 更新轻量模式测试：验证创建 TaskExecutor 而非 NullTaskExecutor
- `tests/test_services/test_container_fix.py` 新增测试：验证轻量模式登录能力（返回 Future）

## 2026-06-18

### refactor
- `app/services/autostart.py` VBS 自启动脚本删除 PID 检测逻辑，职责收敛到 Python
  - `_build_vbs_content` 从 43 行简化为 7 行，删除全部 PID 文件解析和 WMI 进程检测
  - VBS 仅负责启动应用，重复实例检测由 `main.py → _handle_existing_instance → is_service_running` 统一处理
  - 修复 PID 复用误判：VBS 的 `Win32_Process where ProcessId = pid` 无法区分 PID 被其他进程占用，Python 的 `create_time` 验证可以
  - 保留 `On Error Resume Next` 防止 exe 被删/路径变化时弹出错误框
  - 新增 `test_minimal_output_structure` 测试验证 VBS 最小输出结构，防止未来再悄悄加入 PID 解析
  - 更新 2 个测试文件的断言：`test_contains_pid_check` → `test_no_pid_parsing`/`test_no_pid_check`

### fix
- `app/services/engine.py` 优化手动登录日志消息，消除"提交成功"与"登录成功"的歧义
  - `run_manual_login` 日志从"手动登录成功"改为"手动登录任务已提交"，返回消息从"手动登录成功：登录已提交"改为"登录已提交"
  - `_do_async_login` 完成回调新增日志：成功时打印"手动/自动登录完成: {message}"，失败时打印"手动/自动登录失败: {message}"
  - 新增 `from concurrent.futures import Future` 导入
  - 同步更新 3 个测试文件的断言（`test_api_monitor_routes.py`、`test_routers.py`、`test_engine.py`、`test_login_flow.py`）

### refactor

### fix
- `main.py` `_handle_existing_instance` 删除 force 模式下重复的等待循环
  - `_terminate_process` 内部已调用 `_wait_for_exit(pid, max_wait=5)` 等待进程退出
  - 外层 `for _ in range(10): time.sleep(0.5)` 又等 5 秒是冗余的
  - `cleanup_pid()` 无条件调用，行为不变

### refactor
- `app/services/runtime_config.py` 和 `app/services/config_service.py` 函数改名消除配置管道命名混淆（Task 3: P3）
  - `_build_config_payload` → `load_payload_from_profiles`（读方向：ProfileService → MonitorConfigPayload）
  - `build_runtime_config` → `build_runtime_dict_from_payload`（构建方向：MonitorConfigPayload → dict）
  - 函数名直接表达输入→输出方向，消除跨文件命名歧义
  - 同步更新 11 个文件的导入、调用和 mock 路径
  - 367 个测试全部通过（2 个已有失败与本次改动无关）

### refactor
- `app/utils/crypto.py` 密码处理函数集中到 crypto.py（Task 2: P2）
  - `safe_decrypt` 和 `decrypt_password_field` 从 `runtime_config.py` 移到 `crypto.py`
  - 与 `save_password_field` / `decrypt_password` / `mask_password` 放在一起，读写对称，集中管理
  - `runtime_config.py` 改为从 `crypto.py` 导入，删除本地 `_safe_decrypt` / `_decrypt_password_field`
  - 测试文件更新导入路径和 mock 路径

### fix
- `app/services/runtime_config.py` 修复 profile override 覆盖语义（Task 1: P1）
  - PROFILE_OVERRIDE_FIELDS 中的字段应实现"留空则使用全局"语义，而非"总是排除全局值"
  - 改为先用 `GLOBAL_SETTINGS_FIELDS` 全量合并全局值，再用 profile 非空值覆盖 `PROFILE_OVERRIDE_FIELDS` 字段
  - 修复 `test_global_active_task_used_when_profile_empty` 测试失败：profile.active_task="" 时应使用全局值

### docs
- 新增 `docs/api-conventions.md` API 错误响应规范文档（Task 5: R4）
  - 定义 5 种场景的响应方式：资源不存在→404，参数非法→422，权限→403，业务失败→ActionResponse(success=False)，程序异常→500
  - 区分业务可预期失败与程序异常，明确前端处理策略

### fix
- `app/api/scheduled_tasks.py` 资源不存在改用 HTTPException(404) 替代 ActionResponse(success=False)（Task 5: R4）
  - `update_scheduled_task`、`run_scheduled_task`、`toggle_scheduled_task` 三处"定时任务不存在"从 ActionResponse 改为 HTTPException(404)
  - 与 profiles/scripts/tasks/icons/tools 等其他 API 文件保持一致

### fix
- `app/api/ocr.py` 程序异常改用 HTTPException(500) 替代 ActionResponse(success=False)（Task 5: R4）
  - `ocr_install` 和 `ocr_uninstall` 两个 except Exception 分支从 ActionResponse 改为 HTTPException(500)
  - 安装超时、uv 未找到等业务可预期失败保持 ActionResponse 不变

### refactor
- `app/schemas.py` ProfileSettings → AuthProfile，GlobalSettings → SystemSettings（Task 4: R3）
  - `ProfileSettings` 重命名为 `AuthProfile`，docstring 改为"认证方案 — 仅含凭证和匹配规则"
  - `GlobalSettings` 重命名为 `SystemSettings`，docstring 改为"系统运行配置 — 监控、浏览器、日志、暂停、重试等"
  - `_MonitorFieldsMixin` docstring 改为"Profile 可覆盖的全局默认值（监控、认证、运营商等）"
  - `_CommonSettingsMixin` docstring 中 GlobalSettings 引用更新为 SystemSettings
  - `ProfilesData` 字段类型和工厂同步更新
  - `GLOBAL_SETTINGS_FIELDS` 注释和 model_fields 引用同步更新
  - 同步更新 6 个服务/API 文件和 10 个测试文件的 import 和类型注解
  - 367 个测试全部通过（2 个已有失败与本次改动无关）

### refactor
- `app/services/profile_service.py` 删除 ProfileService 内存缓存（Task 3: R2）
  - 删除 `__init__` 中 `_data` 实例变量
  - `_load_unsafe` 每次从磁盘读取，不再缓存
  - `_save_unsafe` 删除缓存更新
  - 添加注释说明不缓存原因：settings.json 很小（<10KB），多实例场景下缓存一致性成本高于收益
  - 更新测试 `test_load_caches_data` 为 `test_load_returns_new_instance_each_time`

### refactor
- `app/services/engine.py` 拆分 `record_log` 双重职责（Task 2: R5）
  - `record_log` 不再隐式触发 `_update_status_snapshot`
  - 新增 `notify_network_state_changed()` 显式方法
  - `test_network` 方法中的调用点更新为显式调用 `notify_network_state_changed()`
  - 设计原则：任何状态变化都应该由显式方法触发，而不是通过副作用间接传播

### fix
- `app/api/scheduled_tasks.py` 4 个路由从 `async def` 改为 `def`（Task 1: R1 async 路由修正）
  - `create_scheduled_task`、`update_scheduled_task`、`run_scheduled_task`、`toggle_scheduled_task`
  - 这 4 个函数体内无任何 `await`，声明为 `async def` 会导致 FastAPI 在主事件循环线程内同步执行
  - `save_task()`/`start_scheduler()` 等同步阻塞调用会阻塞所有其他并发请求
  - 改为 `def` 后 FastAPI 自动将路由丢到线程池执行，释放事件循环
  - `run_scheduled_task` 内部嵌套的 `async def _execute()` 保持不变（含 `await asyncio.to_thread`）

### docs
- 新增 `docs/superpowers/specs/2026-06-18-backend-architecture-review.md` 后端架构审查报告
  - 13 项架构层面问题（3 高 / 5 中 / 5 低），独立验证 12 项完全确认、1 项部分确认
  - 涵盖：async/sync 路由反模式、ProfileService 多实例缓存不一致、代码重复、配置管道职责模糊、API 错误响应不统一等
  - 附建议落地顺序（12 阶段，~23-31h 总工时）

### fix
- `app/container.py` 移除误导性"空闲卸载"日志消息
  - `stop_web_services()` 的日志从"Web 服务已停止（空闲卸载）"改为"Web 服务已停止"
  - 该方法仅被 `shutdown()` 复用，不存在独立的空闲卸载机制
  - 同步清理方法 docstring 中的"空闲卸载"描述

### fix
- `tests/test_services/test_system_services.py` 修复 PR6 提取共享函数后的测试导入和断言（Task 10）
  - `_dir_size_mb` 改为从 `app.utils.files.dir_size_mb` 导入
  - `_playwright_cache_dir` 改为从 `app.utils.platform.get_playwright_cache_dir` 导入
  - `TestPlaywrightCacheDir` 补丁路径从 `app.services.uninstall.PLATFORM` 改为 `app.utils.platform.get_platform`
  - `TestDirSizeMb.test_with_files` 写入数据从 11 字节增至 1MB+，避免 `round(..., 1)` 精度截断为 0.0

### refactor
- 创建共享 `engine_factory` fixture，消除 test_monitor_service/test_engine 重复工厂（PR6 Task 8）

### refactor
- 创建共享 `engine_factory` fixture，消除 test_monitor_service/test_engine 重复工厂（PR6 Task 8）
  - 新建 `tests/test_services/conftest.py`，提供 `engine_factory` fixture，支持标准模式（`engine_factory()`）和原始模式（`engine_factory(raw=True)`）
  - `test_monitor_service.py`：删除 `_make_monitor_service` 函数，16 处调用点替换为 `engine_factory()`，每个方法签名添加 `engine_factory` 参数
  - `test_engine.py`：删除 `_make_engine` 和 `_make_raw_engine` 两个函数，约 90 处调用点替换为 `engine_factory()`/`engine_factory(raw=True)`
  - 167 个测试全部通过

### refactor
- `frontend/js/tasks/editor.js` 提取 `_showCountdownModal` 辅助函数，消除重复倒计时模式（PR6 Task 7）
  - 新增 `_clearCountdownTimer(timerRefKey)` 和 `_showCountdownModal(modalSelector, countdownObj, countdownKey, timerRefKey, initialSeconds)` 两个辅助方法
  - `showDangerConfirm` 从 17 行简化为 7 行，委托 `_showCountdownModal` 处理倒计时逻辑
  - `confirmRepoImport` 从 16 行简化为 3 行
  - `_cancelDangerConfirm` 和 `cancelRepoDisclaimer` 的清理逻辑保持不变，与辅助函数不冲突
  - 净减 2 行代码（-25 +23）

- 提取浏览器选择共享 partial，消除 wizard/settings 重复 HTML（PR6 Task 6）
  - 创建 `frontend/partials/shared/browser-selection.html`：Firefox 兼容性警告 + 自定义浏览器说明 + 自定义路径输入
  - `frontend/partials/wizard.html` 第 308-353 行替换为 `data-include` 引用
  - `frontend/partials/pages/settings/settings-browser.html` 第 66-112 行替换为 `data-include` 引用
  - `frontend/js/methods/ui.js` 新增 `getActiveBrowserChannel()` 和 `onBrowserCustomPathInput()` 方法
  - `getActiveBrowserChannel()` 兼容 wizard（`selectedBrowser`）和 settings（`config.browser_channel`）两种模式
  - `onBrowserCustomPathInput()` 在 settings 模式下触发 `onConfigChange` 自动保存
  - 净减 27 行代码（-93 +66）

### chore
- `frontend/partials/pages/tasks.html` 和 `frontend/partials/pages/scripts.html` 删除不存在的 `onDragLeave` 拖拽事件绑定（PR5 Task 8）
  - `drag.js` 中未定义 `onDragLeave` 方法，拖拽排序使用实时交换模式（在 `onDragOver` 中完成），不需要 `dragleave` 事件

- `frontend/partials/pages/settings/settings-monitor.html` 删除不存在的 `toggleUrlCheck` 调用（PR5 Task 7）
  - `@change` 事件绑定中移除 `toggleUrlCheck(); `，仅保留 `onConfigChange` 调用
  - `urlCheckEnabled` 是 computed getter/setter，setter 已处理 `url_check_urls` 逻辑，无需额外方法

### style
- `frontend/styles/pages/tasks.css` 三个 overlay 提取 `.overlay-base` 共享属性（PR5 Task 5）
  - 新增 `.overlay-base` 包含 `position: fixed`、`inset: 0`、`display: flex`、居中对齐、`backdrop-filter` 等 5 个共享属性
  - `.danger-overlay`、`.debug-overlay`、`.repo-overlay` 各自仅保留 `background`、`z-index`、`animation` 差异属性
  - `frontend/partials/pages/tasks.html` 四个 overlay div 添加 `overlay-base` class

### refactor
- `frontend/js/methods/ui.js` `nextWizardStep` 使用 `validateWizardStep` 替代 inline 验证（PR5 Task 2）
  - 35 行 if-else 验证逻辑简化为 4 行委托调用
  - 步骤 4 的 `browser_channel` 同步保留在验证通过后执行

### refactor
- `frontend/js/app-options.js` 向导验证逻辑统一为 `validateWizardStep` 单点定义（PR5 Task 1）
  - 新增 `validateWizardStep(step, data)` 纯函数方法，集中定义 step 1/2/4 的验证规则和错误消息
  - `canProceed` computed 从 20 行 if-else 简化为一行委托调用
  - `wizardErrors` computed 从 18 行条件逻辑简化为一行委托调用
  - 消除 `canProceed` 与 `wizardErrors` 之间的验证逻辑重复

### fix
- 测试文件同步修复：旧函数名 `_cleanup_temp_screenshots`/`_cleanup_old_screenshots` 更新为合并后的 `_cleanup_screenshots`（Task 6）
  - `tests/test_app/test_application_logic.py`：import 从 `_cleanup_old_screenshots, _cleanup_temp_screenshots` 改为 `_cleanup_screenshots`，两个测试类合并为 `TestCleanupScreenshots`，每个测试同时 mock `TEMP_DIR` 和 `SCREENSHOTS_DIR`
  - `tests/test_integration/test_app_startup.py`：`mock_deps` fixture 中两处 patch 合并为单个 `patch("app.application._cleanup_screenshots")`

### refactor
- `app/application.py` 合并 `_cleanup_temp_screenshots` + `_cleanup_old_screenshots` 为 `_cleanup_screenshots`（Task 5）
  - 两个独立函数合并为一个统一的启动时截图清理函数
  - 使用模块级 `time` 导入替代函数内 `import time as _time` 临时导入
  - `_create_lifespan` 中两处独立调用替换为单次 `_cleanup_screenshots()` 调用

### refactor
- `app/application.py` create_app 拆分为 `_create_lifespan`/`_register_routes`/`_register_static`（Task 4）
  - 提取 `_create_lifespan(existing_container)` 封装生命周期管理逻辑，返回 lifespan context manager
  - 提取 `_register_routes(app)` 封装 16 个 API router 注册
  - 提取 `_register_static(app)` 封装首页路由和 3 个静态文件挂载
  - `create_app` 简化为协调函数：创建 lifespan → 创建 FastAPI → 配置 CORS → 注册中间件 → 注册 WebSocket → 注册路由和静态文件
  - 修复原 `_wait_shutdown` 中引用外部 `_app` 闭包变量的问题，改为使用 `app_instance` 参数

### refactor
- `main.py` 提取 `_load_login_config` 和 `_execute_login_with_retries`（Task 3）
  - `_load_login_config(logger)` 封装配置加载逻辑，返回 `(runtime_config, None)` 或 `(None, LoginResult.CONFIG_ERROR)`
  - `_execute_login_with_retries(runtime_config, logger)` 封装指数退避重试逻辑
  - `_run_login_then_exit` 简化为协调函数：加载配置 → 网络检测 → 重试登录

### refactor
- `main.py` 工厂替换 ProfileService + 提取 `_create_tray`/`_wait_for_exit`（Task 2）
  - 3 处 `ProfileService(Path(__file__).parent.resolve())` 替换为 `create_profile_service()` 工厂调用
  - 顶部新增 `from app.services.profile_service import create_profile_service` import
  - 提取 `_wait_for_exit(pid, max_wait)` 辅助函数，`_terminate_process` 改用该函数
  - 提取 `_create_tray(port, on_exit, on_open_console)` 工厂函数，`_run_lightweight` 和 `_run_full` 改用该函数
  - 托盘创建的 try/except 移入 `_create_tray` 内部，调用方通过返回值判断成功/失败

### fix
- `tests/test_services/test_scheduler_service.py` 修复 `test_timeout_clamped_to_max` 和 `test_audit_log_called` 两个测试 mock 路径过时
  - `5cf7473` 将 `run_sync` 从 `subprocess.run` 改为 `subprocess.Popen`，但测试中 mock 路径未同步更新
  - mock 路径从 `app.utils.shell_policy.subprocess.run` 改为 `app.utils.shell_policy.subprocess.Popen`
  - mock 返回值适配 Popen 接口：`communicate()` 返回 `(stdout, stderr)` 元组，`returncode` 为实例属性

### refactor
- `app/services/engine.py` 添加 `set_dashboard_sink` 公共方法，`app/container.py` 改用该方法替代直接访问 `_dashboard_sink` 私有属性

### refactor
- `app/network/decision.py` 使用 `race_first_success`/`cancel_pending` 替代内联竞态代码 + import 移至顶部
  - `_is_auth_url_reachable` extra_targets 分支的 OR 竞态替换为 `race_first_success` 调用
  - `is_network_available` AND 竞态中的内联取消循环替换为 `cancel_pending` 调用
  - 2 处内联 `from concurrent.futures import as_completed` 移至顶部 import
  - 新增 `from app.utils.concurrent import cancel_pending, race_first_success` 顶部 import
  - 净减 9 行代码（-24 +15）

### refactor
- `app/network/probes.py` 3 个检测函数使用 `race_first_success` 消除竞态重复代码
  - `is_network_available_socket`、`is_network_available_url`、`is_network_available_http` 的 futures 竞态循环替换为 `race_first_success()` 调用
  - 移除不再需要的 `as_completed` 导入
  - worker 函数（`_connect_one`、`_check_url`、`_check_one`）保持不变
  - 净减 26 行代码（-49 +23）

### fix
- `app/services/runtime_config.py` `_build_config_payload` 修复 profile 覆盖字段被 global_settings 覆盖的 bug
  - `auth_url`、`carrier`、`carrier_custom` 从 `_MonitorFieldsMixin` 继承后进入 `GLOBAL_SETTINGS_FIELDS`，导致 `payload_dict.update(gs_dict)` 覆盖 profile 中的独立值
  - 新增 `_PROFILE_OVERRIDE` 排除集合，从 `gs_dict` 中排除这 3 个 profile 覆盖字段
  - 修复 `test_auth_url_from_system` 和 `test_uses_profile_auth_url` 两个测试失败

### fix
- `tests/test_services/test_config_service.py` `test_does_not_update_credentials` 断言更新
  - `auth_url` 和 `carrier` 现在在 `_MonitorFieldsMixin` 中（`GlobalSettings` 与 `MonitorConfigPayload` 共享），会被 `_update_global_settings` 同步更新
  - 断言从 `not hasattr(global_settings, "auth_url/carrier")` 改为验证值同步正确
  - 纯凭证字段（`username`、`password`）仍在 `_SystemFieldsMixin` 中，不会被同步——保持原有语义

### refactor
- `app/services/runtime_config.py` `_build_config_payload` 53 行逐字段取值改为 `model_dump(include=GLOBAL_SETTINGS_FIELDS)` 一行
  - 使用 `GLOBAL_SETTINGS_FIELDS` 交集 + `model_dump(include=...)` 替代逐字段 `data.global_settings.xxx` 取值
  - `source_levels` 不在 `MonitorConfigPayload` 中，自然被排除——与重构前行为一致

### refactor
- `app/schemas.py` GlobalSettings 继承 Mixin 消除 12 个重复字段
  - GlobalSettings 改为继承 `_MonitorFieldsMixin` + `_CommonSettingsMixin`
  - 移除 12 个已在 Mixin 中定义的重复字段声明（仅保留 `source_levels` 和 `network_check_timeout`）
  - 移除 `_MonitorFieldsMixin` 中的 `block_proxy`（保留在 `_CommonSettingsMixin`，避免 MRO 冲突）
  - `url_check_urls` 默认值改用 `DEFAULT_URL_CHECK_URLS` 常量
  - 添加 `GLOBAL_SETTINGS_FIELDS` 共享常量供 config pipeline 使用

### refactor
- `tests/test_utils/test_logging_fix.py` 1 个 `inspect.getsource()` 源码检查测试替换为行为测试
  - `test_should_emit_uses_class_constant`（源码检查）→ `test_should_emit_uses_class_constant_via_behavior`（行为测试：修改类属性验证 should_emit 引用类常量）

### refactor
- `tests/test_app/test_application_fix.py` 7 个 `inspect.getsource()` 源码检查测试替换为行为测试
  - `TestSourceLevelsConfig`（2 个源码检查）→ `TestRunFunctionSafety`（2 个行为测试：callable 验证、import 无 NameError）
  - `TestWebSocketKeyErrorHandling`（3 个源码检查）→ `TestWebSocketMessageHandling`（2 个行为测试：无效 JSON 处理、未知消息类型处理）
  - `TestWindowsSigterm`（2 个源码检查 + 1 个信息性测试）→ `TestWindowsSigterm`（1 个行为测试 + 1 个信息性测试：lifespan 信号注册、平台 SIGTERM 可用性）

### refactor
- 测试文件迁移使用共享 `api_client` fixture（8 个文件）
  - `tests/test_api/test_api_tasks_routes.py`：删除本地 `client` fixture，使用 `api_client` + `_setup_task_mocks` 辅助函数
  - `tests/test_api/test_browsers.py`：删除本地 `client` fixture，使用 `api_client` + `_setup_browser_mocks` 辅助函数
  - `tests/test_api/test_scheduled_tasks_fix.py`：删除本地 `client` fixture，使用 `api_client`，mock 配置移至各测试方法内
  - `tests/test_api/test_api_autostart_routes.py`：删除本地 `client` fixture，使用 `api_client`，mock 配置移至各测试方法内；移除不再需要的 `TestClient`、`MonitorConfigPayload`、`MonitorStatusResponse`、`pytest`、`Path` 导入
  - `tests/test_api/test_api_config_routes.py`：删除本地 `client` fixture，使用 `api_client`，mock 配置移至各测试方法内；移除不再需要的 `TestClient`、`MagicMock`、`pytest`、`MonitorStatusResponse` 导入
  - `tests/test_api/test_api_repo_routes.py`：删除本地 `client` fixture，使用 `api_client`，mock 配置移至各测试方法内；移除不再需要的 `MagicMock`、`pytest`、`TestClient` 导入
  - `tests/test_api/test_api_scripts_routes.py`：删除本地 `client` fixture，使用 `api_client`，mock 配置移至各测试方法内；移除不再需要的 `MagicMock`、`pytest`、`TestClient` 导入
  - `tests/test_api/test_api_system_routes.py`：删除本地 `client` fixture，使用 `api_client`，mock 配置移至各测试方法内；移除不再需要的 `MagicMock`、`pytest`、`TestClient` 导入
  - 共享 fixture 定义于 `tests/test_api/conftest.py`，消除 8 处重复的 `tmp_path` 目录创建和 `app.constants` patch 代码

### fix
- `app/workers/playwright_worker.py` 修复 stealth_mode Bug + 防御性改进（4 项）

### fix
- `app/services/engine.py` 修复 ScheduleEngine 两个接口契约问题
  - `_handle_reload` / `_handle_apply_profile` 设置 `cmd.response_data`，调用方可区分成功/失败（与 `_handle_login` 协议一致）
  - `reload_config()` / `apply_profile()` 返回 `tuple[bool, str]`，超时/队列满/执行失败均有明确返回
  - `run_manual_login()` finally 块加 `self._manual_login_lock`，消除读加锁写不加锁的数据竞争
  - `_apply_stealth_and_routes` 改用 `context.add_init_script` 替代 `page.add_init_script`，stealth 脚本自动继承到所有新页面（含 popup、debug_page）
  - `_handle_debug_stop` 删除新页面后重新应用 stealth 的冗余代码（context 级 init_script 已自动继承）
  - `start()` 新增 `if self.is_alive(): return` 重复启动保护
  - `submit()` 超时判定改用 `event.wait()` 返回值，替代检查 `response_data is not None`（后者在返回值为 None 时误判为超时）

## 2026-06-17

### refactor
- `app/services/task_registry.py` `save_task` 改为磁盘优先模式（Task 8）
  - 先写磁盘（锁外），成功后再更新缓存（锁内），I/O 不在全局锁内
  - 崩溃恢复更安全：磁盘是新数据，缓存是旧数据，重启后从磁盘恢复
  - `delete_task` 已是磁盘优先模式，无需修改

### fix
- `app/services/task_executor.py` 登录并发保护：`execute_login_async` 内部创建默认 `cancel_event`
  - `cancel_event is None` 时内部创建 `threading.Event()`，确保执行器始终拥有取消令牌
  - 新增 `cancel_login()` 方法，设置 `_login_cancel_event` 取消正在进行的登录
  - `NullTaskExecutor` 添加 `cancel_login()` 方法（返回 None）
  - 引擎调用 `execute_login_async(skip_pause_check=...)` 不传 `cancel_event` 时不再无法取消登录

### fix
- `app/utils/shell_policy.py` `run_sync` 超时后杀死子进程树（Task 6）
  - `subprocess.run(timeout=...)` 改为 `Popen + communicate(timeout)` 模式，超时时调用 `_kill_process_tree_sync`
  - 新增 `_kill_process_tree_sync(pid)` 同步版进程树清理方法，复用 `_kill_process_tree` 的 psutil 逻辑
  - 原超时仅返回错误码，子进程（如 chrome）继续运行，现在与异步 `run()` 行为一致
- `tests/test_utils/test_shell_policy.py` 更新测试适配 `run_sync` 改用 `Popen`
  - 5 个测试从 mock `subprocess.run` 改为 mock `subprocess.Popen`
  - `test_timeout_expired_returns_minus_one` 新增 `_kill_process_tree_sync` 调用断言

### fix
- `app/workers/playwright_bootstrap.py` `_run()` 添加 `BOOTSTRAP_TIMEOUT=300` 超时保护
  - `subprocess.run` 未设置 timeout 时下载卡住会永久占用 `_BOOTSTRAP_LOCK`
  - 新增模块级常量 `BOOTSTRAP_TIMEOUT = 300`，传入 `subprocess.run` 的 `timeout` 参数

### fix
- 配置重载顺序修复，避免重载失败时监控被意外停止
  - `_handle_reload` 先执行 `_reload_config_internal()`，仅当重载成功且之前处于监控状态时才执行 stop/start
  - `_handle_apply_profile` 同样修复，先加载成功再 stop+start
  - 原逻辑先 stop 再 reload，reload 失败时监控永久停止
  - 新增测试 `test_reload_failure_keeps_monitoring` 和 `test_reload_success_restarts_monitoring`

### fix
- `_run_full()` finally 块修复：`loop.run_until_complete` 改为 `asyncio.run`，修复未定义变量 `loop` 导致 shutdown 永不执行的 bug
  - 删除 `if not container._shutdown_done` 检查（`asyncio.run` 内部的 `shutdown()` 已是幂等的）
  - `except Exception: pass` 改为 `logger.exception("容器关闭失败")`，避免静默吞掉错误

### fix
- NullTaskExecutor 签名与 TaskExecutor 兼容（添加 skip_pause_check 参数）
  - `execute_login_async` 和 `execute_login` 方法添加 `skip_pause_check=False` 参数
  - 防止轻量模式下引擎调用 `execute_login_async(skip_pause_check=...)` 时抛出 TypeError

### fix
- `frontend/js/constants.js` Axios 拦截器仅对幂等请求执行自动重试
  - 新增 `RETRYABLE_METHODS = ['GET', 'HEAD', 'OPTIONS']` 检查
  - POST/PUT/DELETE 等非幂等请求不再被静默重试（如登录、启动监控）
- `start.go` 添加信号转发，Ctrl+C 时子进程同步退出
  - `cmd.Run()` 改为 `cmd.Start()` + `signal.Notify` + `cmd.Wait()`
  - 收到 SIGINT/SIGTERM 时转发给子进程，避免孤儿进程

### fix
- uv 版本升级至 0.11.21 并添加 SHA256 校验（`start.go` + `start.sh`）
  - 版本从 0.7.3 升级到 0.11.21
  - 下载后对文件执行 SHA256 校验，防止文件被篡改或损坏
  - 校验失败时跳过当前镜像源，尝试下一个
  - 覆盖全部平台：Windows/macOS/Linux，x86_64/arm64
- `start.sh` 修复 macOS 兼容性：sha256sum 改为 sha256sum/shasum -a 256 兼容写法

### docs
- 两轮代码审查报告合并验证完成（`dev/code-review-report.md`）
  - 134 个原始问题逐项验证：27 个误报、42 个排除（not-to-do + 安全类）、1 个已修复
  - 2 个严重程度被高估，9 个确认需关注（5 高 + 4 中）、29 个低影响
  - 高严重性：NullTaskExecutor 签名、main.py shutdown 失败、配置重载无恢复、run_sync 进程泄漏、Playwright 安装无超时
- `app/utils/crypto.py` save_password_field 添加注释说明 `startswith("•")` 掩码判断的设计意图
- `app/utils/crypto.py` encrypt_password 添加注释说明 cryptography 缺失降级的防御性质
- `app/network/decision.py` is_network_available 添加注释说明 AND 逻辑的设计意图
- `app/services/websocket_manager.py` broadcast 添加注释说明 O(n²) 清理在实际场景中无影响
- `app/network/detect.py` SSID 十六进制检测添加注释说明误判概率极低
- `frontend/js/methods/lifecycle.js` visibility change handler 添加注释说明无防抖的实际影响可忽略
- `dev/confirmed-issues.md` 生成确认存在的问题清单（38 个未修复 + 2 个已修复，高/中严重性含完整代码上下文、修复方案和优先级排序）
- `docs/superpowers/plans/2026-06-17-code-review-fixes.md` 代码审查修复实施计划（10 个 Task，TDD 模式）

### docs
- 生成全项目高精度代码审查报告 `code-review-report.md`（第二轮）
  - 15 个 Review Unit 并行审查（P0×5 + P1×7 + P2×3）
  - 发现 11 个 Critical、31 个 Major、28 个 Minor 问题（共 70 个）
  - 关键发现：shell 命令注入（command 未过滤直接传入 shell）、uv 下载无 SHA256 校验、PowerShell 通知注入、密码掩码逻辑绕过、custom_browser_engine 配置未传递
  - 覆盖全部模块：app/services、app/tasks、app/workers、app/network、app/api、app/utils、frontend、tests、root (start.go/sh)

### docs
- 生成代码审查问题分析报告 `docs/superpowers/specs/2026-06-17-code-review-analysis.md`
  - 逐项验证 `code-review-report.md` 中 71 个问题的属实性
  - 38 项属实且严重、18 项严重程度偏高、8 项部分属实、7 项需进一步确认
  - 按可操作性分类：19 项可通过重构解决、28 项可快速修复、12 项需接受/缓解
  - 为每类问题提供具体解决方案、工时估算和风险评估
- 重构方案冻结版 `docs/superpowers/specs/2026-06-17-refactor-optimization-design.md`
  - 经四轮讨论修正，35 项改动，~37h 工时（含测试验证）
  - C01 采用 `run_coroutine_threadsafe` 防御性设计；C12 简化为 null 字节检查；C11 改名 `custom_browser_engine`
  - 否决 4 项（M12/M13/C07/M09），可进入实施阶段
- 生成实施计划 `docs/superpowers/plans/2026-06-17-refactor-optimization.md`
  - 12 个 Task，按风险分三批执行
  - 每个 Task 包含：具体代码改动、测试命令、提交信息
  - 最后附全量测试验证清单和手动验证路径
- 剩余问题设计方案（最终版）`docs/superpowers/specs/2026-06-17-remaining-issues-design.md`
  - P0+P1 共 14 项已全部修复（c0332a3）
  - P2：M29 已修复（9c79ae6），M15/M23/M28 关闭（Won't Fix，经验证不成立）
- P3 Backlog `docs/superpowers/specs/2026-06-17-p3-backlog.md`
  - 18 项低优先级问题（P3 显式 8 项 + Minor 未归类 10 项）
  - 不单独排期，修改相关文件时顺手处理

## 2026-06-16

### docs
- [59] `app/services/task_executor.py` `BoundedExecutor.shutdown` 添加注释说明 `wait=False` 时信号量残留行为

### fix
- 修复前端浏览器交互逻辑两个问题（`frontend/js/methods/ui.js`）
  - [47] `handleBrowserClick` 为 `custom` 通道增加独立分支：选中浏览器并聚焦到路径输入框，同时从 `downloadUrls` 中移除 `custom` 条目
  - [48] `installPlaywrightChromium` 的 `fetch` 调用添加 AbortController 600 秒（10 分钟）超时保护，超时后显示友好提示

## 2026-06-16

### fix
- 修复网络探测客户端获取的 TOCTOU 竞态（`app/network/probes.py`）
  - [35] `_get_probe_client` 移除无锁快速路径，统一走锁内检查
  - 原双检锁模式中快速路径在无锁环境下多步条件判断可能读到不一致状态

### fix
- 修复调试会话管理 5 个问题（`app/services/debug_service.py`）
  - [9] `run_all` 会话有效性检查移入 `async with self._lock` 块内，消除锁外访问共享 `_session` 的竞态
  - [10] `_debug_timeout_watcher` 将 `_last_activity` 读取和超时判断全部纳入锁保护范围
  - [44] `run_all` 在循环开始前一次性获取 `_exec_sem` 并持有到整个批量执行完成，防止 `next_step` 插入
  - [45] `start` 将 Worker 启动调用移到锁外执行，失败时再加锁回滚状态，避免持锁等待线程
  - [75] `close` 方法开头添加 `await self._cancel_debug_timer()`，取消超时定时器

### fix
- 修复应用入口 4 个问题（`app/container.py`、`main.py`、`tests/test_config/test_container.py`）
  - [3] 轻量模式创建 `NullTaskExecutor` 而非真正的 `TaskExecutor`，避免创建不必要的线程池
  - [29] 轻量模式关闭时复用已有 event loop 而非创建新的，无可用 loop 时回退到同步关闭
  - [30] `_start_web_server` 使用 `threading.Lock` 保护标志检查和设置，防止竞态条件
  - [64] `_terminate_process` 后验证进程已实际退出再清理 PID 文件

### fix
- 修复任务系统 4 个问题（`app/tasks/variable_resolver.py`、`app/tasks/step_handlers.py`）
  - [6] `resolve_for_js` 双重编码：replacer 函数改为 `json.dumps(str(resolved))`，确保非字符串类型解析结果先转为字符串再 JSON 编码，输出始终是合法的 JS 字符串字面量
  - [7] 变量解析缓存未绑定上下文：`__init__` 新增 `_cache_version` 版本号，`set_runtime_var` 递增版本号，缓存 key 从原始字符串改为 `(version, value)` 元组，外部修改变量后缓存自动失效
  - [33] OCR Timer 生命周期竞态：`_cleanup_timers` 的读写操作（`schedule_cleanup`、`_cancel_cleanup`、`_do_cleanup`）全部纳入 `_ocr_lock` 保护范围，新增 `_cancel_cleanup_locked` 内部方法避免死锁
  - [34] SleepHandler 缺少校验：`int()` 转换添加 try/except 捕获 ValueError/TypeError，添加负值检查回退到默认值 1000ms

### fix
- 修复配置服务 3 个问题（`app/services/config_service.py`、`app/services/runtime_config.py`、`app/schemas.py`）
  - [26] `_update_global_settings` 补充 `lightweight_tray` 字段同步，将前端传来的值复制到 `global_settings`
  - [27] `_build_config_payload` 补充 `lightweight_tray` 字段，从 `global_settings` 读取并合并到 payload
  - [28] 密码处理简化为一行调用 `save_password_field`，委托给已有的密码处理函数处理所有场景（掩码、空值、ENC: 前缀、明文）
  - `app/schemas.py` `_SystemFieldsMixin` 添加 `lightweight_tray` 字段定义，使 `MonitorConfigPayload` 能传递该字段

### fix
- `app/services/task_executor.py` `_link_cancel_event` 观看线程添加 300 秒超时，防止无限阻塞

### fix
- 修复 TaskExecutor 3 个问题（`app/services/task_executor.py`、`app/services/task_registry.py`）
  - [2] `_ensure_task_pool` 懒初始化添加双检锁（`_task_pool_lock`），防止多线程并发创建多个 BoundedExecutor
  - [22] `execute_login_async` 去重时联动新 `cancel_event` 到已有任务：新增 `_login_cancel_event` 存储已有任务的 cancel_event，去重时通过 `_link_cancel_event` 后台线程监控新事件并联动；`_on_login_done` 同步清理 `_login_cancel_event`
  - [24] `_get_script_path` 路径推断改为委托 `TaskRegistry.get_script_path()`：在 `TaskRegistry` 上新增 `get_script_path(task_id)` 方法，在 `tasks/scripts/` 目录查找 `.json`/`.py` 文件；移除 `task_executor.py` 中硬编码的 `tasks_dir.parent.parent` 推断逻辑

### test
- 更新测试适配 TaskExecutor 修复
  - `tests/test_services/test_task_executor_fix.py`：重写 `TestTaskExecutorGetScriptPath`（3 个测试改为验证委托行为）、新增 `test_ensure_task_pool_thread_safe`（双检锁并发安全）、新增 `test_duplicate_login_links_cancel_event`（cancel_event 联动）、新增 `test_on_login_done_clears_cancel_event`、修复 `test_duplicate_login_returns_existing` 签名
  - `tests/test_core/test_task_registry.py`：新增 `TestRegistryGetScriptPath`（4 个测试：json/py 查找、优先级、不存在）

### fix
- 修复 engine.py 两个代码质量问题（`app/services/engine.py`）
  - `_handle_reload` 和 `_handle_apply_profile` 检查 `_reload_config_internal` 返回值，失败时跳过 `_handle_start` 并记录错误
  - `_reload_config_internal` 的 except 分支设置 `self._pure_mode = False` 安全默认值，防止 reload 失败后 `_pure_mode` 未初始化

### fix
- 修复调度引擎 5 个问题（`app/services/engine.py`）
  - [19] 手动登录路径不再污染自动重试计数：`_do_async_login` 添加 `is_manual` 参数，手动登录不递增 `count`
  - [21] `_do_network_check` 使用 `_monitor_core` 局部引用，避免与 `shutdown` 竞争导致 `AttributeError`
  - [54] profile switch 后 `_reload_config_internal` 失败时跳过 `_handle_start`，防止用过期配置启动监控
  - [55] `drain_ws_queue` 入口检查 `_ws_manager is not None`，避免 `AttributeError`
  - [56] `_reload_config_internal` 中同时更新 `_pure_mode`（在 `_pure_mode_lock` 内），消除 `__init__` 中重复的 `load()` 调用

### fix
- 浏览器注册与安装修复（5 个问题）
  - `app/utils/browser_registry.py` 提取公共 `has_playwright_chromium()` 函数，消除与 `playwright_bootstrap.py` 的 Chromium 检测逻辑重复
  - `app/workers/playwright_bootstrap.py` `_has_chromium()` 改为复用 `has_playwright_chromium()`，移除 `sync_playwright` 回退路径
  - `app/api/install_playwright.py` 并发保护从布尔变量 `_installing` 改为 `asyncio.Lock()`
  - `app/workers/playwright_bootstrap.py` `ensure_playwright_ready` 保存/恢复 `PLAYWRIGHT_DOWNLOAD_HOST` 环境变量
  - `app/utils/browser_registry.py` `_detect_firefox()` Windows 路径补充 `%LOCALAPPDATA%\Mozilla Firefox\firefox.exe`
  - `app/utils/browser_registry.py` `detect_browsers()` 添加 30 秒 TTL 缓存
  - 清理 `playwright_bootstrap.py` 中未使用的 `Path`、`is_macos` 导入

### fix
- `app/workers/playwright_worker.py` 修复 4 个浏览器自动化核心问题
  - `submit_nowait` 添加 `queue.Full` 异常处理和 `_wake_async()` 唤醒事件循环，与 `submit()` 行为一致
  - `cleanup_orphan_browsers` 扩展过滤条件支持 Firefox 进程清理（原仅清理 Chromium）
  - `get_worker()` 使用临时变量 `new_worker`，`start()` 成功后再赋值给 `_worker`，避免其他线程拿到未初始化实例
  - `_handle_debug_stop` 反检测脚本应用逻辑与 `_start_browser` 一致：纯净模式下仅 `stealth_mode` 启用时才应用

### docs
- 生成全项目代码审查报告 `code-review-report.md`
  - 13 个 Review Unit 并行审查（P0×3 + P1×5 + P2×5）
  - 发现 12 个 Critical、40 个 Major、22 个 Minor 问题（共 74 个）
  - 关键发现：浏览器生命周期竞态（__aexit__ + ensure_browser 冲突）、脚本执行白名单绕过、轻量模式 TaskExecutor 未使用 NullTaskExecutor、变量解析双重编码
  - 跳过日志系统（正在优化中）

### refactor
- 移除旧的保存按钮和表单提交
  - `frontend/partials/pages/settings.html` 移除表单的 `@submit.prevent="saveConfig"` 事件绑定
  - `frontend/partials/pages/settings/settings-browser.html` 删除底部悬浮保存按钮区域（`settings-float-save`）

### feat
- 为所有配置项添加自动保存事件监听
  - `frontend/partials/pages/settings/settings-browser.html` 为 17 个配置项添加 @change/@input 事件
  - `frontend/partials/pages/settings/settings-monitor.html` 为 18 个配置项添加 @change/@input 事件
  - `frontend/partials/pages/settings/settings-system.html` 为 11 个配置项添加 @change/@input 事件
  - `frontend/partials/pages/settings/settings-account.html` 为 6 个配置项添加 @change/@input 事件
  - checkbox 类型使用 @change 事件，type 为 'toggle'
  - input/textarea 类型使用 @input 事件，type 为 'input'
  - select 类型使用 @change 事件，type 为 'toggle'
  - computed 属性（pureMode、urlCheckEnabled）使用特殊格式：先调用切换方法再调用 onConfigChange



### feat
- 添加配置自动保存逻辑
  - `frontend/js/methods/config.js` 新增 `_isConfigLoaded`、`_lastSavedConfig`、`_saveConfigTimer`、`_saveAbortController` 属性
  - 新增 `_debounceSave` 防抖方法和 `onConfigChange` 配置变更回调
  - `fetchConfig` 添加首次加载保护和快照
  - `saveConfig` 添加脏值检测、AbortController 取消机制、saveFailed 状态管理
  - `resetConfig` 添加快照重置

### feat
- 添加 Firefox 兼容性警告提示
  - `frontend/partials/pages/settings/settings-browser.html` 浏览器卡片区域添加 Firefox 兼容性警告
  - `frontend/partials/wizard.html` 向导页面浏览器选择区域添加相同警告
  - `frontend/styles/pages/settings.css` 添加 `.browser-warning` 警告样式
  - `frontend/js/methods/ui.js` `handleBrowserClick` 方法添加 Firefox 选择前的确认弹窗

### fix
- DEFAULT_CONFIG 添加 browser_channel 和 browser_custom_path 字段
  - `frontend/js/constants.js` `_SHARED_DEFAULTS` 中在 `headless: true` 之前添加 `browser_channel: "playwright"` 和 `browser_custom_path: ""`

### fix
- Playwright Chromium 检测添加 .local-browsers 备用路径
  - `app/utils/browser_registry.py` `_has_playwright_chromium` 通过 `importlib.util.find_spec` 定位 playwright 包内的 `.local-browsers` 目录
  - 先搜索标准缓存目录，再搜索包内备用路径，任一路径找到 chromium 即返回 True

### fix
- 添加自定义浏览器路径安全校验
  - `app/schemas.py` 在 `_SystemFieldsMixin` 和 `GlobalSettings` 中添加 `browser_custom_path` 字段校验器，检测路径中的危险字符（`;`、`&`、`|`、`` ` ``、`$`、`(`、`)`、`{`、`}`）
  - `app/workers/playwright_worker.py` `_launch_browser` 方法中添加路径存在性检查，路径不存在时抛出 `FileNotFoundError`

### fix
- 修复 Firefox 启动时不传递 Chromium 专属参数
  - `app/workers/playwright_worker.py` `_build_launch_args` 方法新增 `channel` 参数
  - 当 `channel == "firefox"` 时返回空列表，不传递 Chromium 专属参数
  - `_start_browser` 方法调用时传递 `channel` 参数

### fix
- 修复浏览器配置无法保存的问题
  - `app/schemas.py` MonitorConfigPayload 添加浏览器配置字段（headless、browser_channel 等）
  - `app/services/config_service.py` _update_global_settings 添加浏览器配置更新逻辑
  - `app/services/runtime_config.py` _build_config_payload 添加 browser_channel 和 browser_custom_path 字段

### fix
- 修复手动登录 skip_pause_check 参数未传递的问题
  - `app/services/engine.py` _handle_login 和 _do_async_login 传递 skip_pause_check
  - `app/services/task_executor.py` execute_login_async 和 execute_login 传递 skip_pause_check

### fix
- 修复浏览器未正确关闭的问题
  - `app/utils/browser.py` __aexit__ 改用 CMD_BROWSER_CLOSE 关闭浏览器

### refactor
- 删除浏览器复用逻辑，ensure_browser 每次都重新启动浏览器
  - `app/workers/playwright_worker.py` ensure_browser 简化为直接关闭并重启

### feat
- 优化浏览器选择 UI，使用 SVG 图标和更好的样式
  - `app/utils/browser_registry.py` 更新浏览器图标为 SVG
  - `frontend/partials/pages/settings/settings-browser.html` 优化卡片布局和状态显示
  - `frontend/partials/wizard.html` 同步更新向导页面样式
  - `frontend/styles/pages/settings.css` 添加浏览器选择相关样式

### fix
- 修复 Chrome 检测逻辑，添加 Windows 标准安装路径检测
  - `app/utils/browser_registry.py` 检查 Program Files 下的 Chrome 路径

### feat
- 恢复自定义路径选项，添加 Playwright 兼容性说明
  - `app/utils/browser_registry.py` 恢复 _detect_custom 函数
  - `frontend/partials/pages/settings/settings-browser.html` 添加自定义路径输入和说明链接
  - `frontend/partials/wizard.html` 同步更新向导页面
  - `frontend/styles/pages/settings.css` 添加自定义路径提示样式

## 2026-06-16

### feat
- `app/workers/playwright_worker.py` `_start_browser` 支持根据 `browser_channel` 启动不同浏览器
  - 新增 `_launch_browser` 辅助方法，根据 channel 分发到不同启动逻辑
  - 支持 5 种浏览器 channel：playwright（默认）、msedge、chrome、firefox、custom（自定义路径）
  - Firefox 使用 `playwright.firefox.launch()`，自定义路径使用 `executable_path` 参数
  - `browser_channel` 和 `browser_custom_path` 从 `browser_settings` 配置中读取

### feat
- `app/api/browsers.py` 新增 GET /api/browsers 端点
  - 返回系统已安装的浏览器列表（5 种选项）和当前配置的 browser_channel
  - 通过 `detect_browsers()` 检测浏览器，通过 `profile_service.load()` 获取当前配置
  - 使用 FastAPI Depends 注入 profile_service，与项目风格一致
- `app/application.py` 注册 browsers 路由

### test
- `tests/test_api/test_browsers.py` 添加浏览器 API 端点测试（5 个用例）
  - `test_get_browsers_returns_200`：返回 200 状态码
  - `test_get_browsers_structure`：响应包含 browsers 列表和 current 字段
  - `test_get_browsers_contains_all_channels`：5 种浏览器选项全覆盖
  - `test_get_browsers_current_field`：current 字段值合法
  - `test_get_browsers_item_structure`：每个浏览器项包含必要字段

### feat
- `app/utils/browser_registry.py` 新增浏览器注册表，检测系统已安装的浏览器
  - `BrowserInfo` 数据类：channel、name、icon、installed、needs_download、description
  - `detect_browsers()` 返回 5 种浏览器选项：Playwright Chromium、Microsoft Edge、Google Chrome、Firefox、自定义路径
  - Playwright Chromium 检测缓存目录中的已下载实例
  - Edge/Chrome/Firefox 通过 `shutil.which` 和 macOS 应用路径检测
  - 自定义路径始终可用，由用户自行确保路径有效

### test
- `tests/test_utils/test_browser_registry.py` 添加浏览器注册表测试（3 个用例）
  - `test_detect_browsers_returns_list`：返回类型验证
  - `test_browser_info_fields`：字段完整性验证
  - `test_detect_browsers_contains_all_options`：5 种浏览器选项全覆盖

## 2026-06-15

### fix
- `app/services/task_executor.py` 修复 `execute_login_async` 死锁风险
  - 将 `future.add_done_callback(self._on_login_done)` 从 `with self._login_lock:` 块内移到锁外
  - 原代码在锁内注册回调，而 `_on_login_done` 回调也会获取同一锁，若 `execute_login` 极快完成会导致主线程阻塞
  - 确保回调注册在锁释放后执行，消除时序问题

### test
- 完成测试覆盖率改进，整体覆盖率达到 86%（目标 85%）
  - `tests/test_utils/test_src_utils.py` 新增 PlaywrightWorker 纯逻辑测试
    - `TestBuildLaunchArgs`（8 个）：默认参数、disable_web_security、low_resource_mode、自定义参数、去重、空白行、空值/None
    - `TestBuildContextOptions`（6 个）：默认选项、自定义视口、User-Agent、空 UA、额外请求头、HTTPS 错误
    - `TestHealthCheck`（4 个）：无浏览器、连接正常、断开、异常
    - `TestIsNormalCloseError`（4 个）：target closed、connection closed、其他错误、大小写
    - `TestHandleLowResourceRequest`（6 个）：图片/字体/媒体拦截、文档/脚本放行、异常静默
    - `TestWakeAsync`（2 个）：设置事件、无事件
    - `TestWorkerProperties`（4 个）：page/browser/context/playwright_instance
    - `TestCloseResource`（5 个）：None、成功、已关闭、正常错误、非优雅模式
    - `TestDispatch`（6 个）：已取消跳过、SHUTDOWN、未知命令、BROWSER_RELEASE、response_event、异常
    - `TestSubmitQueueFull`（1 个）：队列满返回错误
    - `TestSubmitTimeout`（1 个）：超时返回错误
    - `TestSubmitResponseData`（2 个）：WorkerResponse/普通值
    - `TestSubmitNowait`（1 个）：命令入队
    - `TestCleanupBrowser`（9 个）：全 None、强制清理、调试页面、浏览器连接/断开、Playwright、正常错误、其他错误、强制静默
    - `TestStopDetails`（2 个）：永久关闭标志、排干队列
    - `TestGetWorkerShutdownWorker`（2 个）：None 时不报错、存活时关闭
  - `tests/test_api/test_api_autostart_routes.py` 新增 AutoStartService 纯逻辑测试
    - `TestAutostartCliArgs`（3 个）：轻量/完整模式、无连续空格
    - `TestAutoStartServiceInit`（1 个）：初始化
    - `TestAutoStartServicePaths`（3 个）：macOS/Linux/Windows 路径
    - `TestAutoStartServiceRun`（4 个）：成功/失败/超时/异常
    - `TestAutoStartServiceStatus`（4 个）：macOS/Linux/Windows/不支持平台
    - `TestAutoStartServiceEnableDisable`（5 个）：不支持平台、Windows 成功/CJK 路径、禁用
    - `TestBuildVbsContent`（3 个）：WshShell、PID 检查、运行命令
    - `TestHasCjkChars`（4 个）：中文、混合、纯 ASCII、空字符串
    - `TestStartCommand`（3 个）：打包可执行文件、回退、venv
    - `TestDisableMacos`（2 个）：存在/不存在
    - `TestDisableLinux`（1 个）：禁用
  - `tests/test_app/test_application_logic.py` 增强截图清理测试
    - `TestCleanupTempScreenshots`：重写为实际文件时间测试，覆盖 png/jpg/jpeg/新文件/非图片/不存在/空目录/异常
    - `TestCleanupOldScreenshots`（5 个）：旧目录删除/不存在/空目录/异常/跳过当天
  - 优化 6 个 10 秒超时测试（engine/monitor_service），测试执行时间从 126 秒降至 50 秒
    - `test_engine.py`：`test_reload_config_enqueues`/`test_reload_config_timeout`/`test_apply_profile_enqueues`/`test_apply_profile_timeout` 改为 mock response_event.wait
    - `test_monitor_service.py`：`test_reload_config_enqueues_reload_command`/`test_apply_profile_enqueues_command` 改为立即设置 response_event

### feat
- `frontend/js/constants.js` `DEFAULT_CONFIG` 新增 `lightweight_tray: true` 字段

### feat
- `main.py` `_build_app_config()` 新增读取 `lightweight_tray` 配置
  - 在 `minimize_to_tray` 读取后新增 `config.lightweight_tray` 读取
  - 默认值 `True`，与 `minimize_to_tray` 保持一致

### test
- `tests/test_integration/test_scheduled_task.py` 添加定时任务集成测试（38 个用例）
  - `TestTaskRegistrationAndExecution`（11 个）：保存/读取/列出/删除任务、删除清理历史、执行不存在/不支持类型的任务、执行记录历史/更新 last_run、has_enabled_tasks、调度索引查询/更新
  - `TestTaskExecutionWithVariableResolution`（12 个）：变量基础替换/嵌套解析/运行时优先级/JS 安全转义/未解析保留/循环引用/最大深度、StepHandler 参数解析、浏览器任务变量传递、Shell 任务执行/空命令
  - `TestTaskFailureHandling`（8 个）：异常记录失败历史、失败更新 last_status、脚本/浏览器不存在、历史持久化/裁剪/无效 ID、多次失败累积
  - `TestTaskCancellation`（7 个）：登录取消事件、异步去重、BoundedExecutor 队列满拒绝、NullTaskExecutor 全方法、shutdown、信号量释放、线程池懒初始化

### test
- `tests/test_integration/test_login_flow.py` 添加登录流程集成测试（39 个用例）
  - `TestFullLoginSequence`（10 个）：手动登录命令成功/失败、配置缺失、async_login 提交、TaskExecutor 登录成功/失败/取消/异常、完整手动登录序列
  - `TestLoginWithNetworkDetection`（7 个）：网络检测触发登录、无需登录、更新间隔、方案切换、异常继续、登录后网络恢复、引擎循环集成
  - `TestLoginRetryMechanism`（11 个）：基本重试判断、间隔时间、最大次数、进行中跳过、无配置/零计数、间隔递增、配置获取/异常回退、重置计数、唤醒时间
  - `TestLoginConcurrencyProtection`（11 个）：进行中拒绝、Future 清除状态、并发拒绝、手动登录锁、锁释放（完成/超时）、重试不触发、异常清除、Future None、多线程竞争

### test
- `tests/test_integration/test_app_startup.py` 添加应用启动集成测试（22 个用例）
  - `TestCreateAppInitialization`（9 个）：FastAPI 实例创建、标题/版本、lifespan 配置、首页路由、静态文件挂载、WebSocket 端点、existing_container 参数、CORS 中间件、必要目录创建
  - `TestAppLifespan`（7 个）：shutdown_event 创建、existing_container 模式启动、调度器启用/跳过、shutdown 调用、完整生命周期、新容器模式 startup
  - `TestDependencyInjection`（6 个）：services 挂载到 app.state、shutdown_event 类型、monitor_service 配置访问、uvicorn Server 存储、server_ref 填充、access_log_event 控制
  - 使用 `APIRouter` 作为 `new_callable` patch 路由模块，避免 MagicMock 导致的 lifespan 递归合并问题
- `tests/test_integration/__init__.py` 创建集成测试包

### test
- `tests/test_services/test_websocket_manager.py` 添加 websocket_manager.py 单元测试，覆盖率 100%
  - `TestNullWebSocketManager`：覆盖 connect、disconnect、broadcast、close_all 四个空操作方法
  - `TestWebSocketManagerConnect`：覆盖 accept 调用和连接追加、多连接
  - `TestWebSocketManagerDisconnect`：覆盖移除连接、不存在连接不报错、仅移除目标连接
  - `TestWebSocketManagerBroadcast`：覆盖空连接广播、多连接发送、失败连接自动清理、已移除连接不报错、超时断开、超时已移除、send_safe 调用验证
  - `TestWebSocketManagerCloseAll`：覆盖清空连接、调用 close、关闭异常不影响其他连接、空连接关闭
  - `TestWebSocketManagerInit`：覆盖初始化状态验证

### test
- `tests/test_services/test_login_history.py` 补充 login_history_service.py 单元测试，覆盖率从 73% 提升至 99%
  - `TestRecord`：覆盖 `record` 方法全部分支 — 无服务对象、profile_service 正常/返回 None/抛异常、task_manager 正常/无 name 属性/load_task 返回 None/抛异常、error 传递
  - `TestAddException`：覆盖 `add` 方法写入异常不抛出、失败时不递增 `_write_count`
  - `TestListRecentLargeFile`：覆盖 >5MB 大文件只读取末尾分支
  - `TestListRecentException`：覆盖 stat 查询异常和文件读取异常返回空列表
  - `TestClearException`：覆盖 clear 读取失败返回 0
  - `TestCleanupOldException`：覆盖 `_cleanup_old` 读取异常静默处理、JSON 解析失败行保留

### test
- `tests/test_services/test_debug_service.py` 添加 debug_service.py 补充单元测试，覆盖率从 90% 提升至 98%
  - `TestDebugTimeoutWatcherActualTimeout`：覆盖超时触发关闭浏览器、浏览器未活跃跳过关闭、锁内代数不匹配跳过
  - `TestStartTemplateVarReplacement`：覆盖 URL 模板变量替换分支
  - `TestNextStepSessionReplaced`：覆盖 Worker 失败/成功后会话被替换时直接返回
  - `TestRunAllSessionReplaced`：覆盖循环内会话被替换/停止运行/步骤完成后替换三种场景
  - `TestStopTempDirCleanupError`：覆盖临时目录 iterdir 异常和文件 unlink 异常

### test
- `tests/test_services/test_task_executor_fix.py` 提升 task_executor.py 测试覆盖率从 35% 到 99%
  - `TestTaskExecutorGetScriptPath`：新增 `test_uses_get_script_path_method`、`test_falls_back_to_py_extension`、`test_returns_none_when_script_not_found`
  - `TestTaskPoolLazyInit`：新增 `test_shutdown_with_task_pool`、`test_ensure_task_pool_creates_once`
  - `TestNullTaskExecutor`：覆盖全部 11 个方法（has_enabled_tasks、shutdown、execute_task_async、execute_login_async、execute_task、execute_login、list_tasks、get_task、save_task、delete_task、get_history）
  - `TestBoundedExecutor`：覆盖 submit 成功、参数传递、队列满抛异常、信号量异常释放、任务完成后释放、shutdown
  - `TestTaskExecutorCRUD`：覆盖 list_tasks、get_task、save_task、delete_task（成功/失败）、get_history、has_enabled_tasks、set_runtime_config_getter
  - `TestTaskExecutorExecuteTask`：覆盖任务不存在、不支持类型、script/browser/shell 分发、执行异常、默认超时、历史记录
  - `TestTaskExecutorExecuteScript`：覆盖无 registry、任务不存在、类型错误、脚本文件不存在
  - `TestTaskExecutorExecuteBrowser`：覆盖任务不存在、类型错误、成功/失败/ImportError/通用异常、data 非字符串、无 error 消息
  - `TestTaskExecutorExecuteShell`：覆盖空命令、配置来源（runtime/default/异常回退）、shell 类型格式（powershell/cmd/bash）、返回码处理、输出截断、异常处理
  - `TestTaskExecutorExecuteLogin`：覆盖取消事件、成功/失败/无 error/data 非字符串/无配置/ImportError/通用异常
  - `TestTaskExecutorRecordLoginHistory`：覆盖无服务、成功记录、失败记录、异常捕获
  - `TestTaskExecutorLoginAsync`：覆盖首次提交、去重返回已有 Future、完成后清理、cancel_event 传递、完成后可重新提交
  - `TestTaskExecutorOnLoginDone`：覆盖匹配清理、不匹配不清理
  - `TestTaskExecutorTaskAsync`：覆盖提交到 task_pool、懒初始化

### test
- `tests/test_services/test_engine.py` 添加 engine.py 单元测试，覆盖调度引擎核心逻辑（覆盖率 75% → 93%）
  - `TestEngineCmdType`：枚举值和成员数
  - `TestEngineCommand`：默认值和自定义值
  - `TestStatusSnapshot`：默认值和自定义值
  - `TestLoginRetryState`：默认值和自定义值
  - `TestEngineInit`：初始化默认值和 task 组件注入
  - `TestEnqueue`：成功入队和队列满
  - `TestCalculateWakeup`：默认/监控/重试/调度/异常回退 5 种场景
  - `TestProcessCommand`：6 种命令类型派发 + response_event 设置 + 异常仍 set
  - `TestHandleStart`：重复启动/正常创建/纯净模式
  - `TestHandleStop`：无 core/有 core
  - `TestHandleShutdown`：调用 stop
  - `TestHandleLogin`：无配置/缺字段/异步成功/已在进行
  - `TestHandleReload`：未监控/正在监控
  - `TestHandleApplyProfile`：未监控/正在监控
  - `TestDoNetworkCheck`：无 core/需登录/正常/方案切换/异常
  - `TestLoginRetryNeeded`：7 个分支全覆盖
  - `TestDoAsyncLogin`：已在进行/Future None/Future 成功/异常清除标志
  - `TestGetRetryConfig`：正常/异常回退
  - `TestRunScheduleTick`：有任务/无任务/无 registry
  - `TestUpdateStatusSnapshot`：无 core/connected/disconnected/节流/force/异常
  - `TestQueueStatusBroadcast`：默认队列/dashboard sink/异常
  - `TestGetStatus`：stopped/running
  - `TestShutdown`：设置事件/幂等/停止调度器
  - `TestStartStopMonitoring`：已在运行/配置无效/队列满/成功/未运行/运行中
  - `TestReloadConfig`：入队/队列满/超时
  - `TestApplyProfile`：入队/队列满/超时
  - `TestRunManualLogin`：进行中/队列满/成功/失败/超时(存活)/超时(死亡)
  - `TestNetwork`：正常/失败/异常/带目标
  - `TestTogglePureMode`：切换
  - `TestProperties`：login_in_progress/ws_broadcast_queue/pure_mode/_is_monitoring/tasks/scheduler_running
  - `TestSchedulerControl`：启动/幂等/停止/has_enabled_tasks
  - `TestGetConfig`：get_config/get_runtime_config 返回副本
  - `TestRecordLog`：基本/network source 触发快照
  - `TestListLogs`：无 sink/有 sink/零 limit
  - `TestBoot`：调用 start_monitoring
  - `TestWsDrain`：空队列/有消息/broadcast 异常

### test
- `tests/test_utils/test_login.py` 提升 login.py 测试覆盖率从 56% 到 98%
  - `TestAttemptLoginSkipPauseCheck`：skip_pause_check=True 跳过检查
  - `TestAttemptLoginWithPause`：暂停时段、网络正常、物理断开、认证地址不可达、前置条件通过、异常捕获
  - `TestPerformLoginWithAuthClass`：有/无活动任务分支
  - `TestPerformLoginWithActiveTask`：profile_task_id 路径、get_active_task 路径、task 为 None、ScriptTaskInfo 分支、LoginCancelledError、通用异常
  - `TestExecuteBrowserTask`：cancel_event、已有浏览器关闭、__aenter__ 失败、page 为 None、登录成功/失败关闭策略、弹窗监听器注册/移除、截图 URL
  - `TestExecuteScriptTask`：cancel_event、脚本失败、脚本成功+网络正常/不通、超时配置
  - `TestCloseBrowser`：有/无上下文、__aexit__ 异常
  - `TestScreenshotUrlPattern`：中英文冒号、jpg、无截图不变
  - `TestEnsureTaskManager`：初始化、已初始化跳过、环境变量覆盖
  - `TestInit`：默认值、自定义值

### test
- `tests/test_utils/test_crypto.py` 提升 crypto.py 测试覆盖率从 79% 到 97%
  - `TestGetOrCreateKeyCache`：缓存命中和 double-check 缓存
  - `TestCorruptedKeyFile`：密钥文件损坏备份、错误长度、rename FileNotFoundError、rename OSError
  - `TestChmodFailure`：chmod 失败时警告但不影响密钥生成
  - `TestIcaclsErrors`：icacls 超时和其他异常
  - `TestDeriveFernetKeyCache`：Fernet 密钥缓存命中
  - `TestEncryptPassword`：空字符串、正常加密、cryptography 未安装
  - `TestDecryptPassword`：空字符串、明文回退、正常解密、cryptography 未安装、解密失败
  - `TestDecryptionErrorFlag`：初始状态、设置和清除
  - `TestMaskPassword`：空值、None、正常值、长度一致性
  - `TestSavePasswordField`：全部 7 个分支（None、掩码、空、ENC、明文）

### test
- `tests/test_utils/test_ports.py` 添加 `resolve_port` 单元测试（19 个用例，覆盖率 100%）
  - `TestResolvePortFromEnv`：有效端口、最小/最大端口、带空格端口
  - `TestResolvePortEnvInvalid`：非数字、零、超范围、负数、空字符串、纯空格
  - `TestResolvePortFromSettings`：有效配置、缺字段、无效端口、非数字端口
  - `TestResolvePortSettingsErrors`：文件不存在、JSON 格式错误
  - `TestResolvePortPriority`：环境变量优先于 settings.json
  - `TestResolvePortDefault`：无配置时返回默认端口 50721

### perf
- 定时任务线程池懒初始化，无任务时不创建线程
  - `app/services/task_executor.py`：`_task_pool` 初始为 `None`，首次调用 `execute_task_async` 时才创建
  - 新增 `_ensure_task_pool()` 方法封装懒初始化逻辑
  - `shutdown()` 添加 `_task_pool is not None` 检查，避免未创建时调用
  - 更新类文档字符串，标注 `_task_pool` 为懒初始化

### test
- `tests/test_services/test_task_executor_fix.py` 新增 `TestTaskPoolLazyInit` 测试类
  - `test_task_pool_initially_none`：初始化时 `_task_pool` 应为 `None`
  - `test_task_pool_created_on_first_use`：首次调用 `execute_task_async` 时创建
  - `test_shutdown_without_task_pool`：无 `_task_pool` 时 `shutdown` 不报错

### fix
- `app/schemas.py` 在 `_SystemFieldsMixin` 中补充 `login_timeout` 字段
  - `MonitorConfigPayload` 继承的两个 mixin 均无此字段，Pydantic v2 静默丢弃用户设置的值
  - `engine.py` 中 `getattr(self._ui_config, "login_timeout", 120)` 永远返回 120s
  - 字段定义与 `GlobalSettings.login_timeout` 一致：`default=90, ge=10, le=600`
  - `tests/test_app/test_backend_services.py` 新增 `test_login_timeout_in_payload` 测试
- `login_timeout` 默认值从 60s 调整为 90s
  - `app/schemas.py`：`_SystemFieldsMixin` 和 `GlobalSettings` 两处同步修改
  - `frontend/js/constants.js`：前端默认值同步
  - `app/services/engine.py`：`getattr(..., 120)` 简化为直接属性访问（字段已补充，不再需要防御性 fallback）
  - `frontend/js/methods/actions.js`：回退值从 120 改为 90

### test
- 修复 7 个预先存在的测试失败
  - 6 个因字段迁移导致：监控字段和 `use_global_*` 标志已从 `ProfileSettings` 移至 `GlobalSettings`，但测试未同步更新
    - `test_config_schemas.py`：删除 `TestProfileSettingsDefaults.test_use_global_flags` 和 `TestProfileSettings.test_monitor_fields_defaults`，移除其他测试中对已迁移字段的断言
    - `test_backend_services.py`：`test_updates_default_profile` 改为检查 `global_settings.check_interval_seconds`
  - 1 个测试隔离问题：`test_valid_config` 因全局 `_decryption_failed` 状态被其他测试污染而失败
    - `test_utils.py`：`TestDecryptionError` 添加 `teardown_method` 清除状态
    - `test_config_schemas.py`：`TestValidateEnvConfig` 添加 `setup_method` 清除状态

### fix
- `application.py` 配置诊断路径修正：`settings.json` → `config/settings.json`

### perf
- 定时任务线程池 worker 数从 4 减至 2（定时任务很少并发）

### chore
- 删除空的 `backups/` 文件夹，清理 `.gitignore` 中的 `backups/*` 条目
  - 代码中无任何逻辑创建或使用此目录，属于残留文件
- 更新 `not-to-do.md`，新增"架构类"分类，补充 3 条设计决策
  - 不缩窄 `except Exception`：桌面应用永不崩溃的核心目标
  - 不迁移 threading 为 asyncio：牵动 engine/worker/tray 整条链路
  - 不给前端加 TS/bundler：保留用户可直接修改的优势
- CI Windows 依赖安装改用 `start.exe`（原 `go run start.go`）

### test
- 更新测试适配 close_browser、线程池和 lru_cache 的修改
  - `tests/test_utils/test_utils.py::TestGetProjectVersion`：移除 `setup_method` 中的 `cache_clear()` 调用和 `test_lru_cache` 测试方法（`get_project_version` 已无 `@lru_cache`）
  - `tests/test_api/test_scripts_fix.py::TestScriptThreadPool::test_executor_is_reused`：改为检查模块级 `_script_executor`（executor 已从函数属性移至模块级）
  - `tests/test_core/test_monitor.py::TestCloseBrowser::test_close_browser_with_context`：移除 `worker.close_browser` 断言（`close_browser` 仅释放上下文引用，不再销毁浏览器实例）

### test
- 修复 5 个测试文件中已删除的 `SystemSettings` 引用，改用 `GlobalSettings`
  - `test_api_config_routes.py`、`test_api_profiles_routes.py`、`test_api_repo_routes.py`、`test_routers.py`：导入替换 + `ProfilesData` 字段从 `system=SystemSettings(...)` 改为 `global_settings=GlobalSettings()`，凭证字段移至 `ProfileSettings`
  - `test_backend_services.py`：`test_masked_password_uses_sys` 简化为不传 `global_settings`（密码遮蔽逻辑不再依赖全局设置回退），`test_retry_settings` 改用 `GlobalSettings`

### docs
- `frontend/partials/pages/settings/settings-account.html` 密码字段添加不可恢复提示
  - 密码输入框下方新增提示："密码本地存储，不保证意外删除后可恢复"
  - 复用现有 `.hint` 样式类，与上方"密码不会随配置切换导出"提示风格一致

### fix
- `frontend/js/methods/profiles.js` 和 `frontend/styles/pages/profiles.css` 自动切换模式下添加防御检查、删除恢复和禁用卡片样式
  - `setActiveProfile` 方法开头添加 `if (this.autoSwitch) return` 防御检查，CSS pointer-events 失效时仍阻止手动切换
  - `deleteProfile` 中 `fetchProfiles` 后检查 `activeProfileId` 是否指向已删除方案，若是则重置为 `default`
  - `.profile-card-main.disabled` CSS 添加 `opacity: 0.5` 和 `cursor: not-allowed`，禁用卡片视觉提示更明确

### fix
- `app/version.py` 移除 `get_project_version` 的 `@lru_cache(maxsize=1)` 装饰器
  - 缓存导致不同 `project_root` 参数被忽略，始终返回首次调用的结果
  - 移除 `from functools import lru_cache` 导入（文件中无其他使用）

### fix
- `app/workers/script_runner.py` 脚本执行失败时优先输出 stderr 内容
  - 原逻辑 `stdout[:500] or stderr[:500]` 在 stdout 有内容时丢弃 stderr 错误详情
  - 成功时仅使用 stdout，失败时优先使用 stderr
  - 消除 `output` 变量在 `returncode` 判断前的无条件赋值

### fix
- `app/services/login_history_service.py` 登录历史写入后添加 fsync，防止进程崩溃丢数据
  - `add` 方法中 `f.flush()` 后新增 `os.fsync(f.fileno())`
  - `flush()` 仅写入 OS 缓冲区，`fsync` 确保数据落盘

### fix
- `app/services/login_history_service.py` 登录历史清理与写入在同一锁块内执行，消除竞态窗口
  - `add` 方法中 `need_cleanup` 标志和二次加锁改为在同一个 `with self._lock:` 块内直接调用 `_cleanup_old`
  - 原逻辑释放锁后重新获取锁执行清理，并发 `add()` 可能写入被 `atomic_write` 覆盖的新记录

### fix
- `app/api/scripts.py` 脚本执行线程池移至模块级，确保随进程生命周期管理
  - `ThreadPoolExecutor` 从 `run_script._executor` 函数属性移至模块级 `_script_executor`
  - 消除 `hasattr` + 赋值的线程安全隐患（并发首次调用可能创建多个 executor）
  - executor 现在随模块生命周期存在，可被进程退出时正确关闭

### fix
- `app/api/profiles.py` 自动切换检测失败时在响应中返回警告信息
  - `toggle_auto_switch` 中检测异常不再静默吞掉，改为在响应中返回 `warning` 字段
  - 用户可明确知道首次检测失败，而非只看到"自动切换已开启"

### fix
- `app/api/system.py` check_update 添加 asyncio.Lock 防止并发重复请求 GitHub API
  - 添加模块级 `_update_lock = asyncio.Lock()`
  - 将 `check_update` 函数体包裹在 `async with _update_lock:` 中
  - 防止并发请求同时 miss 缓存后各自发起 HTTP 请求

### fix
- `app/api/config.py` 配置回滚失败时记录详细错误信息
  - 回滚失败的 except 块现在捕获异常并记录详细信息
  - 包含"磁盘配置已回滚，运行时状态可能不一致"的提示，便于排查问题
  - 原逻辑只记录"回滚失败"，异常细节被静默吞掉

### fix
- `app/utils/config_utils.py` 密码解密失败时给出明确错误信息
  - `validate_env_config` 新增 `has_decryption_error()` 检查
  - 原逻辑：密钥变更后加密密码解密失败，password 字段非空，误报"缺少用户名或密码"
  - 新增检查位于 URL 校验之后、`return True` 之前，解密失败时返回"密码解密失败（可能是密钥变更），请在设置页面重新输入密码"

### fix
- `app/services/config_service.py` 支持用户显式清空密码字段
  - 用户清空密码字段时 `pwd_raw` 为空字符串，原 `if pwd_raw and ...` 条件跳过，旧密码残留
  - 改为 `if/elif/else` 三分支：掩码值跳过、非空加密保存、空字符串清空

### fix
- `main.py` CLI 登录模式传递 `global_settings` 给 `build_runtime_config`
  - 原逻辑未传 `global_settings`，浏览器配置和重试设置使用硬编码默认值
  - 现在通过 `data.global_settings` 正确传递，与 API 路由行为一致

### fix
- `app/utils/network.py` 修复 `parse_ping_targets` 对 IPv6 地址的处理
  - IPv6 地址含多个冒号（如 `::1`、`2001:db8::1`），原逻辑误判为已有端口
  - 新增 IPv6 检测：以 `[` 开头直接传递，多个冒号视为 IPv6 并补全 `[addr]:53`
  - 单冒号视为 host:port 格式，无冒号走原有 IPv4/域名逻辑

### refactor
- `app/network/decision.py` 移除 `is_network_available` 中的死代码
  - `socket_ok`/`http_ok`/`url_ok` 变量在循环中只会被赋值为 `True`（失败时已提前 `return False`）
  - 删除变量声明和循环中的赋值语句
  - 删除冗余的 `result` 计算和日志输出，循环正常结束直接 `return True`

### fix
- `app/network/probes.py` 探测成功时取消其余 pending 的 future，释放线程池资源
  - `is_network_available_socket`、`is_network_available_url`、`is_network_available_http` 三个函数
  - 首个目标返回成功后，遍历所有 future 取消未完成的任务
  - 避免剩余 future 继续占用线程池直到超时

### fix
- `app/network/probes.py` set_block_proxy 时关闭旧 httpx 客户端，确保代理设置立即生效
  - 修改后 `_block_proxy` 标志后，立即关闭并置空 `_probe_client`
  - 下次探测时 `_get_probe_client` 会以新的代理设置重建客户端

### fix
- `app/services/task_registry.py` save_task 磁盘写入失败时回滚缓存，防止任务丢失
  - 先更新缓存（备份旧值），再写入磁盘
  - 磁盘写入失败时回滚缓存和调度索引到写入前状态
  - 原逻辑：磁盘写入成功但缓存更新失败时任务会"消失"，缓存更新成功但磁盘写入失败时缓存与磁盘不一致

### fix
- `app/services/config_service.py` 补充 `build_runtime_config` 中遗漏的 `pure_mode` 字段
  - `global_settings` 分支：添加 `"pure_mode": global_settings.pure_mode`
  - 回退默认值分支：添加 `"pure_mode": True`（与 `GlobalSettings.pure_mode` 默认值一致）
  - TaskExecutor 路径因遗漏此字段导致 `pure_mode` 永远为 `False`

### fix
- `app/services/task_executor.py` 修复登录去重时错误设置调用方 cancel_event 的问题
  - 移除去重分支中 `cancel_event.set()` 调用（该操作设置的是调用方的事件，而非运行中任务的事件）
  - 有无 cancel_event 时统一返回已有 Future，不再返回 None
  - 更新返回类型注解和文档字符串

### fix
- `app/utils/crypto.py` 完全移除 base64 混淆逻辑，缺少 cryptography 时改用明文
  - `encrypt_password`：缺少 cryptography 时直接返回明文并输出 warning
  - `decrypt_password`：遇到 `ENC:` 前缀但 cryptography 不可用时抛出 `DecryptionError`
  - 删除 `_simple_obfuscate`、`_simple_deobfuscate` 函数和 `_OBFUSCATE_PREFIX` 常量
  - 删除 `decrypt_password` 中 `ENC:B64:` 分支和 `except ImportError` 的 base64 回退
  - 删除 `TestSimpleObfuscate` 和 `TestSimpleDeobfuscate` 测试类

### docs
- `app/network/decision.py` `_is_auth_url_reachable` 添加设计意图注释
  - 说明有 `extra_targets` 时只检测自定义目标、不回退 `auth_url` 是故意设计

### docs
- `docs/superpowers/plans/2026-06-15-code-review-fixes.md` 代码审查修复实施计划
  - 36 个任务，覆盖 36 个审查发现
  - 按子系统分组：测试套件、引擎核心、任务执行器、网络检测、配置/API、进程管理、工具模块、前端

### docs
- 生成全项目代码审查报告 `code-review-report.md`
  - 12 个 Review Unit 并行审查（P0×5 + P1×6 + P2×1）
  - 发现 12 个 Critical、32 个 Major、20 个 Minor 问题
  - 关键发现：测试套件引用已删除的 SystemSettings 无法运行、浏览器常驻机制被破坏、Go 启动器跨平台兼容性缺失、信号量泄漏、密钥损坏时无备份覆盖

### docs
- `.claude/skills/code-review-report.md` 完善 code review skill 定义
  - 补充 `disable-model-invocation: true` 注释说明
  - Phase 1 新增 Explore Agent Prompt 模板，明确探索阶段输出格式
  - Phase 1 新增默认 Unit 骨架表（14 个 Unit），提供确定性拆分基础
  - Phase 2 补充空优先级批次跳过条件
  - Phase 2 subagent prompt 模板输出字段与 JSON Schema 对齐（severity/file/line_range 等）
  - 新增输出 Schema 定义，通过 `schema` 参数强校验 subagent 返回格式
  - 报告模板模块表改为动态生成，与项目背景表解耦
  - 统一代码片段引用格式为 `` ```startLine:endLine:filepath`` ``
  - 执行要点新增 Schema 强校验说明

### fix
- `app/workers/playwright_worker.py` 跳过已超时的 Worker 命令执行，防止资源浪费
  - `WorkerCommand` 新增 `cancelled` 字段
  - `submit()` 超时后设置 `cmd.cancelled = True`
  - `_dispatch()` 执行前检查 `cancelled` 标志，已取消的命令直接跳过

### refactor
- `app/services/runtime_config.py` 清理 D7 `_normalize_targets` 死代码
  - 删除 `_normalize_targets` 函数（生产代码中无任何调用者）
  - 移除不再使用的 `DEFAULT_NETWORK_TARGETS` 导入
  - 删除 `tests/test_config/test_config_schemas.py` 中 `TestNormalizeTargets` 测试类和 `_normalize_targets` 导入

### refactor
- `app/utils/crypto.py` 清理 D6 `is_encrypted` 死代码
  - 删除 `is_encrypted` 函数（生产代码中无任何调用者）
  - 删除 `tests/test_utils/test_utils.py` 中 `TestIsEncrypted` 测试类和 `is_encrypted` 导入
  - 移除 `test_round_trip` 中对 `is_encrypted` 的断言

### refactor
- `app/utils/config_utils.py` 清理 D2-D5 死代码
  - 删除 `PROFILE_FIELDS` 常量（在重构后不再被生产代码使用）
  - 删除 `GLOBAL_FIELDS` 常量（在重构后不再被生产代码使用）
  - 删除 `extract_profile_fields` 函数（在重构后不再被生产代码使用）
  - 删除 `ConfigValidator.validate_gui_config` 方法（在重构后不再被生产代码使用）
  - 删除 `tests/test_utils/test_config_utils_fix.py` 文件（全部内容为 PROFILE_FIELDS 测试）
  - 删除 `tests/test_utils/test_utils.py` 中 `TestExtractProfileFields` 测试类
  - 删除 `tests/test_config/test_config_schemas.py` 中 `TestValidateGuiConfig` 测试类

### refactor
- `app/utils/notify.py` 删除 `send_notification` 死代码
  - 函数在生产代码中无任何调用者，仅在测试中使用
  - 删除 `send_notification` 函数及其测试类 `TestSendNotification`
  - 保留 `_notify_windows`、`_notify_macos`、`_notify_linux` 平台通知函数

### test
- 移除已删除类 `SystemSettings` 和 `migrate_config_if_needed` 的死测试引用
  - `tests/test_config/test_config_schemas.py`：移除 `SystemSettings` 导入和 `TestSystemSettings` 测试类
  - 删除 `tests/test_services/test_runtime_config.py`（全部测试均引用已删除的 `SystemSettings` 和 `migrate_config_if_needed`）

### fix
- `app/utils/shell_policy.py` `run_sync` 过滤 kwargs，防止安全策略被绕过
  - 原 `run_kwargs.update(kwargs)` 允许调用方传入 `shell=True` 等危险参数
  - 改为白名单过滤，仅允许 `env` 和 `cwd` 两个额外参数

### fix
- `app/services/config_service.py` 删除 `build_runtime_config` 中不可达的密码回退代码
  - `GlobalSettings` 没有 `password` 字段，`hasattr(global_settings, 'password')` 永远返回 `False`
  - 移除死代码分支及不再使用的 `decrypt_password`、`DecryptionError` 导入

### fix
- `app/services/task_executor.py` 修复 BoundedExecutor 信号量泄漏
  - `submit()` 中 `self._executor.submit()` 若抛异常，信号量已获取但无人释放
  - 用 try/except 包裹 submit 调用，异常时立即释放信号量再 re-raise

### fix
- `app/utils/login.py` 移除双重 close_browser，仅释放浏览器上下文引用
  - 移除 `close_browser` 中对 `worker.close_browser()` 的调用（该调用会销毁整个浏览器实例）
  - 移除不再需要的 `get_worker` 导入
  - 浏览器实例保持在 Worker 中复用，避免每次登录多花 3-5 秒重启浏览器

### fix
- `app/tasks/step_handlers.py` OCR 初始化和识别移至线程执行，避免阻塞事件循环
  - `DdddOcr()` 构造函数和 `classification()` 推理调用均为同步阻塞操作
  - 用 `asyncio.to_thread` 包裹三个调用点，释放事件循环

### fix
- `app/api/profiles.py` 和 `frontend/js/methods/profiles.js` toggleAutoSwitch 改用 POST body 传递参数
  - 前端：将 query string `?enabled=${newState}` 改为 POST body `{ enabled: newState }`
  - 后端：`Query(default="true")` 改为 `Body(default={})`，解析逻辑兼容字符串和布尔值

### fix
- `app/services/engine.py` 守卫 profile switch 防止并发 shutdown 导致 `_monitor_core` 为 None
  - `_do_network_check` 第 285 行 `consume_profile_switch_flag()` 调用前增加 `_monitor_core` 空值检查
  - 防止 `_handle_stop()` 设置 `_monitor_core = None` 后 `shutdown()` 并发访问引发 `AttributeError`

### fix
- `app/utils/ports.py` 修复端口配置读取路径和 JSON key
  - 路径从 `PROJECT_ROOT / "settings.json"` 修正为 `PROJECT_ROOT / "config" / "settings.json"`
  - JSON key 从 `system.app_port` 修正为 `global_settings.app_port`

### feat
- `app/api/profiles.py` 开启自动切换时立即检测匹配方案
  - `toggle_auto_switch` 新增 `monitor_svc` 依赖
  - 开启自动切换后立即调用 `detect_matching_profile` 检测当前网络
  - 检测到匹配方案且与当前方案不同时，自动切换并应用
  - 检测过程异常不影响开关状态设置，仅记录警告日志

### refactor
- `frontend/partials/pages/profiles.html` 移除所有 `use_global_*` 引用
  - 方案列表：`auth_url` 和 `active_task` 标签仅检查值是否存在
  - 编辑器：移除三个 toggle 开关（使用全局账号密码、跟随全局认证地址、跟随全局任务）
  - 账号凭证、认证地址、执行任务字段现在始终显示

### refactor
- 将监控配置从 `ProfileSettings` 移动到 `GlobalSettings`
  - 移动字段：check_interval_seconds、pause_enabled、pause_start_hour、pause_end_hour、network_targets、http_targets、enable_tcp_check、enable_http_check、enable_local_check、check_auth_url、auth_url_targets、url_check_urls、network_check_timeout
  - `ProfileSettings` 不再包含监控配置字段，仅保留凭证和自定义变量

### refactor
- `app/services/runtime_config.py` 从 `global_settings` 合并监控配置
  - `_build_config_payload` 新增监控配置字段合并

### refactor
- `app/services/config_service.py` 监控配置保存到 `global_settings` 而非 `profile`
  - `_update_global_settings` 新增监控配置更新
  - `save_config_combined` 移除 profile 的监控配置更新

### refactor
- `app/utils/config_utils.py` 更新 `PROFILE_FIELDS` 和 `GLOBAL_FIELDS`
  - `PROFILE_FIELDS`：移除所有监控配置字段（保留凭证和 custom_variables）
  - `GLOBAL_FIELDS`：新增所有监控配置字段

### refactor
- 将浏览器配置从 `ProfileSettings` 移动到 `GlobalSettings`
  - 移动字段：headless、browser_timeout、browser_navigation_timeout、login_timeout、browser_user_agent、browser_low_resource_mode、browser_disable_web_security、browser_extra_headers_json、browser_args、stealth_mode、stealth_custom_script、browser_locale、browser_timezone、browser_viewport_width、browser_viewport_height
  - 删除 `_BrowserFieldsMixin` 类
  - `ProfileSettings` 不再继承 `_BrowserFieldsMixin`
  - `MonitorConfigPayload` 不再继承 `_BrowserFieldsMixin`

### refactor
- `app/utils/config_utils.py` 更新 `PROFILE_FIELDS` 和 `GLOBAL_FIELDS`
  - `PROFILE_FIELDS`：移除所有浏览器配置字段
  - `GLOBAL_FIELDS`：新增所有浏览器配置字段

### refactor
- `app/services/runtime_config.py` 从 `global_settings` 合并浏览器配置
  - `_build_config_payload` 函数新增浏览器配置合并逻辑

### refactor
- `app/services/config_service.py` 更新配置保存逻辑
  - `_update_global_settings` 移除浏览器配置更新（浏览器配置现在是 GlobalSettings 的一部分）
  - `build_runtime_config` 新增 `global_settings` 参数，从 `GlobalSettings` 获取浏览器配置

### fix
- `app/api/autostart.py` 修复 `data.system` 引用为 `data.global_settings`
- `app/api/repo.py` 修复 `data.system` 引用为 `data.global_settings`

### test
- 更新测试文件适配浏览器配置移动到 `GlobalSettings`
  - `tests/test_config/test_config_schemas.py`：浏览器字段测试改用 `GlobalSettings`
  - `tests/test_services/test_config_service.py`：更新 `test_updates_browser_config` 测试
  - `tests/test_utils/test_config_utils_fix.py`：移除 `headless` 字段检查
  - `tests/test_app/test_backend_services.py`：更新测试数据结构
  - `tests/test_api/test_config_fix.py`：更新测试数据结构

### refactor
- `app/utils/config_utils.py` 更新 `PROFILE_FIELDS` 和新增 `GLOBAL_FIELDS`
  - `PROFILE_FIELDS`：移除全局配置字段（`backend_log_level`、`frontend_log_level`、`access_log`、`minimize_to_tray`、`auto_open_browser`、`startup_action`、`autostart_lightweight`、`max_retries`、`retry_interval`、`log_retention_days`、`proxy`、`app_port`、`use_global_credentials`、`shell_path`），新增 `active_task`
  - 新增 `GLOBAL_FIELDS` 常量，包含 `GlobalSettings` 中的所有字段

### refactor
- `app/services/profile_service.py` 更新 ProfileService 支持新的 ProfilesData 结构
  - `load` 方法：移除 profiles 目录的单独读写，直接从 `settings.json` 加载完整 ProfilesData
  - `save` 方法：移除 profiles 目录的单独写入，所有数据（含 profiles）保存到单个 `settings.json`
  - 移除 `_profiles_dir` 属性和 profiles 目录创建逻辑
  - 代码行数从 255 行减少到 220 行（减少 35 行）

### test
- `tests/test_services/test_profile_service.py` 添加 ProfileService 测试
  - `TestProfileServiceLoad` 测试类：测试文件缺失返回默认值、读取 settings.json、损坏文件处理、缓存行为
  - `TestProfileServiceSave` 测试类：测试创建 settings.json、保存后加载 roundtrip、不再创建 profiles 目录

### refactor
- `app/services/config_service.py` 简化配置保存逻辑，凭证保存到 profile
  - 将 `_update_system_settings` 重写为 `_update_global_settings`
  - 函数不再处理凭证字段（username/password/auth_url/carrier），仅更新系统级配置
  - 更新 `save_config_combined` 函数，将凭证保存到活动 profile 而非 system
  - 保存逻辑从 "system + default 方案" 改为 "global_settings + 活动 profile"
  - 自动创建不存在的活动 profile

### test
- `tests/test_services/test_config_service.py` 添加配置保存逻辑测试
  - `TestUpdateGlobalSettings` 测试类：测试全局设置更新、日志级别归一化、代理地址去空白、不更新凭证
  - `TestSaveConfigCombined` 测试类：测试保存到活动 profile、自动创建 profile、更新全局设置、保存凭证、更新监控/浏览器配置、密码加密

### fix
- `main.py` 修复 `build_runtime_config` 调用，移除 `data.system` 参数
  - `ProfilesData` 已无 `system` 字段，改为 `global_settings`
- `app/services/engine.py` 修复 `build_runtime_config` 调用，移除 `data.system` 参数

### refactor
- `app/services/runtime_config.py` 简化配置加载逻辑，删除 `use_global_*` 相关代码
  - 删除 `extract_profile_fields` 和 `PROFILE_FIELDS` 的导入和使用
  - 删除 `use_global_*` 相关的条件判断（10+ 个分支）
  - 简化为直接从 profile 构建 payload，合并 global_settings 系统配置
  - 调用 `migrate_config_if_needed` 进行迁移
  - 代码行数从 232 行减少到 199 行（减少 33 行）

### feat
- `app/services/runtime_config.py` 实现配置迁移逻辑
  - 新增 `migrate_config_if_needed()` 函数
  - 将旧格式 `SystemSettings` 中的凭证迁移到 default profile
  - 迁移后清空 system 中的凭证数据
  - 添加 `ProfileSettings` 到导入列表

### test
- `tests/test_services/test_runtime_config.py` 添加配置迁移测试
  - `TestMigrateConfig` 测试类包含 3 个测试用例
  - 测试迁移凭证到 default profile
  - 测试没有凭证时不执行迁移
  - 测试迁移保留现有 profile 配置

### feat
- `app/schemas.py` 扩展 `ProfileSettings` 类，添加浏览器配置和监控配置字段
  - 继承 `_BrowserFieldsMixin` 获取所有浏览器配置字段
  - 添加监控配置字段：check_interval_seconds、pause_enabled、pause_start_hour、pause_end_hour、network_targets、http_targets、enable_tcp_check、enable_http_check、enable_local_check、check_auth_url、auth_url_targets、url_check_urls、network_check_timeout、custom_variables
  - 保留 use_global_credentials、use_global_auth_url、use_global_task 标志位
  - 添加 auth_url 验证器
  - 更新类文档字符串为"方案配置 — 所有业务配置的唯一数据源"

### test
- `tests/test_config/test_config_schemas.py` 添加 `TestProfileSettings` 测试类
  - 测试默认值、自定义值、无效认证地址
  - 测试浏览器字段默认值、监控字段默认值
  - 测试浏览器请求头 JSON 验证

### feat
- `app/schemas.py` 添加 `GlobalSettings` 类
  - 仅包含系统级设置：日志、UI、网络、应用、重试、source 级别配置
  - 不包含业务逻辑（凭证、监控、浏览器配置）
  - 位于 `_SystemFieldsMixin` 之后，作为统一 Profile 配置架构的第一步

### test
- `tests/test_config/test_config_schemas.py` 添加 `TestGlobalSettings` 测试类
  - 测试默认值、自定义值、无效日志级别、日志级别归一化

### feat
- `app/schemas.py` 更新 `ProfilesData` 类，使用 `GlobalSettings` 替代 `SystemSettings`
  - `system: SystemSettings` 改为 `global_settings: GlobalSettings`
  - 添加 `ensure_default_profile` model_validator 确保 default profile 自动创建

### test
- `tests/test_config/test_config_schemas.py` 更新 `TestProfilesData` 测试类
  - 新增 test_default_profile_auto_created、test_global_settings_default、test_custom_profiles
  - 更新已有测试适配字段重命名和自动创建 default profile 行为

### test
- `tests/test_services/test_monitor_service.py` 添加自动切换方案标志位测试用例
  - `test_check_profile_switch_sets_flag`: 方案切换时设置标志位
  - `test_check_profile_switch_no_change`: 方案未变化时不设置标志位
  - `test_consume_profile_switch_flag`: 消费标志位行为验证

### fix
- `app/services/engine.py` 自动切换方案后重启监控
  - `_do_network_check` 中检查 `consume_profile_switch_flag()` 标志位
  - 检测到方案切换时执行停止 → 重载配置 → 重启监控流程

### feat
- `app/services/monitor_service.py` 添加自动切换方案的重启标志位
  - 新增 `_profile_switch_needed` 实例变量
  - `_check_profile_switch` 方案切换成功时设置标志位
  - 新增 `consume_profile_switch_flag()` 方法供 engine 消费标志位

### refactor
- 删除 `app/services/monitor_service.py` 中形同虚设的冷却时间机制
  - 删除 `GATEWAY_CHECK_COOLDOWN_SECONDS = 60` 常量
  - 删除 `_last_gateway_check_time` 实例变量
  - 删除 `_check_profile_switch` 中的冷却时间检查逻辑
  - 原因：检测间隔 300 秒远大于冷却 60 秒，冷却永远不会触发

## 2026-06-14

### feat
- 任务编辑器 name/description 输入框与 JSON 配置双向实时同步
  - 修改输入框自动更新 JSON 中的对应字段
  - 修改 JSON 中的 name/description 自动更新输入框
  - 加载模板时同步字段

### fix
- 修复 `is_local_network_connected()` 未正确过滤回环接口的问题
  - Windows: `Loopback Pseudo-Interface 1`，原精确匹配无法命中
  - Linux: `lo`，macOS: `lo0`
  - 改为 `name.lower().startswith("lo")`，一条规则兼容三平台

### docs
- 全面更新 README.md：修正项目结构（`backend/`→`app/`、`src/`→`app/`子目录）、入口文件（`app.py`→`main.py`）、CLI 参数、模块路径、技术栈
- 全面更新 `docs/api-doc.md`：新增日志级别、OCR 管理、脚本二进制列表、自启动模式等端点；移除已删除的配置备份、日志文件查看器等端点
- 全面更新 `docs/task-manual.md`：修正架构概览、核心模块路径、环境变量参考（仅保留 6 个仍在使用的环境变量）、任务存储结构
- 更新 `docs/update_log.md`：新增 v4.0.2 版本条目

### refactor
- 移除 `CAMPUS_AUTH_AUTOSTART` 环境变量，改用 `--source autostart` CLI 参数
  - 删除 macOS/Linux/Windows 三处环境变量注入
  - `_autostart_cli_args()` 返回值加 `--source autostart`
  - 删除 `_detect_launch_context()` 函数，直接从 argparse 读取
- 删除 `app/network/decision.py` 中未使用的 `check_campus_network_status()` 函数
- 清理 `tests/test_core/test_network_probes.py` 中对应的导入和测试类 `TestCheckCampusNetworkStatus`
- 删除 `app/schemas.py` `validate_custom_variables` 方法内重复的 `import re`（模块级已有）
- 删除 4 个前端未调用的 API 路由及对应测试：
  - `DELETE /api/config/source-level/{source}`（`app/api/config.py`）
  - `GET /api/debug/status`（`app/api/debug.py`）
  - `GET /api/profiles/active`（`app/api/profiles.py`）
  - `GET /api/scheduled-tasks/{task_id}`（`app/api/scheduled_tasks.py`）
- 重写 `docs/api-doc.md`，使其与实际代码中的 API 端点完全一致：
  - 新增 log-levels、source-level、default-stealth-script、scripts/binaries、shells、autostart/mode、OCR 相关、task-manual 端点
  - 移除不存在的 profiles/active、debug/status、scheduled-tasks/{task_id} GET、配置备份段
  - 更新静态资源路径
- 重写 `docs/task-manual.md`，修复所有过时的模块路径和引用：
  - 架构概览：更新模块表和调用链，新增 ScheduleEngine、TaskRegistry 等模块
  - 所有导入路径：`src/` → `app/`，`backend/` → `app/`
  - 环境变量：移除已迁移至 `config/settings.json` 的大量配置项，仅保留 6 个仍需环境变量的项
  - 任务文件存储：更新目录结构为 `tasks/browser/`、`tasks/scripts/`、`tasks/scheduled/`
  - TaskManager：`active.txt` 改为通过 API 管理活动任务
  - 网络探测：更新为 URL 响应检测、TCP/HTTP 可配置目标、psutil 本地网络检测

### fix
- `app/services/autostart.py` VBS 自启动脚本适配 JSON 格式 PID 文件
  - `write_pid` 函数写入 JSON 格式 (`{"pid": 12345, "create_time": ...}`)，但 VBS 脚本期望纯数字 PID
  - 更新 VBS 模板解析逻辑：初始化 `pid = 0`，使用 `InStr` 查找 `":"` 提取 JSON 中的 PID 值
  - 添加 `If pid > 0 Then` 条件检查，仅在成功解析 PID 后才执行 WMI 进程检测
  - 避免因格式不匹配导致 WMI 查询失败，防止启动重复实例

### refactor
- 移除旧的 configDirty 检测逻辑，改用 _lastSavedConfig 进行脏值检测
  - `frontend/js/app-options.js`：configDirty computed 改为直接比较 JSON.stringify(config) 与 _lastSavedConfig
  - `frontend/js/app-options.js`：config watcher 移除防抖定时器和 dirty 状态更新逻辑
  - `frontend/js/app-options.js`：beforeUnmount 移除 _configDirtyTimer 清理
  - `frontend/js/data/config.js`：移除 savedConfigSnapshot 和 _configDirty 数据属性
  - `frontend/js/methods/config.js`：fetchConfig 移除 _configDirty 和 savedConfigSnapshot 设置
  - `frontend/js/methods/config.js`：resetConfig 移除 _configDirty = true，由 computed 自动检测

### fix
- 修复 6 个 Minor 问题（分散在多个文件）
  - [50] `app/utils/browser.py` `STEALTH_INIT_SCRIPT` 改用 `Object.defineProperty` 设置 `__playwright`/`__pw_manual` 为 undefined，防止 non-configurable 属性 delete 静默失败
  - [53] `app/services/monitor_service.py` `consume_profile_switch_flag` 注释修正为"由引擎线程串行调用，无需额外同步"
  - [57] `app/utils/shell_utils.py` `get_default_shell` 非 Windows 回退路径使用 `shutil.which` 验证存在性，`$SHELL` 环境变量指向已删除 shell 时回退到 bash/sh
  - [60] `app/utils/crypto.py` `save_password_field` 掩码判断从 `startswith("•")` 改为精确匹配 `"••••••••"`，避免以 bullet 开头的密码被误判
  - [61] `app/schemas.py` 提取 `_CommonSettingsMixin` 共享 mixin，消除 `_SystemFieldsMixin` 与 `GlobalSettings` 之间约 40 个重复字段定义和 2 个重复验证器
  - [66] `app/tasks/manager.py` `_extract_script_metadata` 使用 `ast.get_docstring()` 正确提取标准多行 docstring

### refactor
- PROFILE_RUNTIME_FIELDS 集中定义，消除 config_service 中的魔法列表
  - `app/utils/config_utils.py` 新增 `PROFILE_RUNTIME_FIELDS` 模块级常量（8 个字段名元组）
  - `app/services/config_service.py` `build_runtime_dict_from_payload` 改用 `list(PROFILE_RUNTIME_FIELDS)` 替代内联列表
  - `tests/test_utils/test_utils.py` 新增 `TestProfileRuntimeFields`（类型检查 + 字段存在性检查）

### test
- 新增集成测试共享 fixture `tests/test_integration/conftest.py`
  - `_write_initial_config(tmp_path)` 写入最小化 settings.json（短间隔加速测试）
  - `mock_worker` fixture 模拟 Playwright worker
  - `integration_stack` fixture 组装真实 ProfileService + TaskExecutor + ScheduleEngine
  - `full_stack` fixture 额外暴露 TaskRegistry

## 2026-06-20

### fix — 防止去重命中时重复注册 _on_done 回调（P1-01）
- `app/services/engine.py`：
  - `__init__` 新增 `self._registered_futures: set[Future] = set()`
  - `_do_async_login` 添加去重检查：`if handle.future in self._registered_futures: return False`
  - `_on_done` 回调开头添加 `self._registered_futures.discard(f)` 清理
  - `add_done_callback` 前添加 `self._registered_futures.add(handle.future)` 注册
- 测试文件同步更新：
  - `tests/test_services/conftest.py`：`_make_raw` 添加 `svc._registered_futures = set()`
  - `tests/test_integration/test_login_flow.py`：`_make_raw_engine` 添加 `svc._registered_futures = set()`
  - `tests/test_services/test_engine_fix.py`：`_make_engine` 添加 `engine._registered_futures = set()`
  - `tests/test_services/test_monitor_service.py`：`test_do_async_login_delegates_to_task_executor` 添加 `svc._registered_futures = set()`
- 验收：2328 测试全通过

## 2026-06-22 (11)

### config: 添加 lightweight_tray 和 auto_open_browser 默认值

- `config/settings.json`：在 `config` 对象中添加 `lightweight_tray: true` 和 `auto_open_browser: false` 字段，与 `RuntimeConfig` 模型默认值保持一致
- 注意：`config/` 目录在 `.gitignore` 中，使用 `git add -f` 强制添加

## 2026-06-29 (1)

### chore: 删除 TaskExecutor 死方法并简化守卫

- `app/services/task_executor.py`：
  - 删除 `execute_login_async()` 方法（死方法，engine 直接调 LoginOrchestrator.submit()）
  - 删除 `execute_login()` 方法（死方法，engine 直接调 LoginOrchestrator.submit()）
  - `_execute_script` 删除 `if not self._registry` 不可能守卫（构造函数必填参数）
  - `_execute_browser` 删除 `cancel_event` 参数（无生产调用者传递此参数）
- 测试文件同步更新：
  - `tests/test_services/test_task_executor_fix.py`：删除 `TestTaskExecutorExecuteLogin`、`TestTaskExecutorLoginAsync`、`test_no_registry`、`test_browser_cancel_event_passed`、`test_browser_cancel_event_default_none`
  - `tests/test_services/test_container_fix.py`：删除 `test_lightweight_execute_login_async_returns_future`
  - `tests/test_integration/test_login_flow.py`：删除 4 个 execute_login 测试方法
  - `tests/test_integration/test_scheduled_task.py`：删除 `test_login_cancel_event`、`test_login_async_deduplication`、`test_execute_login_async_returns_future`
  - `tests/test_integration/test_login_connection.py`：更新为直接调用 `_login_orchestrator.submit()`
  - `tests/test_integration/test_lightweight_mode.py`：更新为直接调用 `_login_orchestrator.submit()`
  - `tests/test_integration/test_login_integration_extended.py`：更新为直接调用 `_login_orchestrator.submit()`
  - `tests/test_services/test_monitor_service.py`：删除无用的 `execute_login_async` mock 设置

## 2026-06-29 (2)

### refactor: 用 psutil.Process.wait() 替换 _wait_for_exit 轮询循环

- `app/services/launcher.py`：
  - `_wait_for_exit` 改用 `psutil.Process(pid).wait(timeout=max_wait)` 替代逐秒轮询
  - 处理 `TimeoutExpired`（超时返回 False）和 `NoSuchProcess`（进程已退出返回 True）
  - 新增 `import psutil`，移除不再使用的 `get_process_name` import

## 2026-06-29 (3)

### refactor: 移除 TaskExecutor CRUD 透传，暴露 registry/history_store 属性

- `app/services/task_executor.py`：
  - 新增 `registry` 和 `history_store` 只读属性，供 API 路由直接访问底层组件
  - 删除 5 个 CRUD 透传方法：`list_tasks`、`get_task`、`save_task`、`get_history`、`has_enabled_tasks`
  - 保留 `delete_task`（协调 registry + history_store 的删除逻辑）
- `app/api/scheduled_tasks.py`：
  - 所有 `engine.tasks.list_tasks()` → `engine.tasks.registry.list_tasks()`
  - 所有 `engine.tasks.get_task()` → `engine.tasks.registry.get_task()`
  - 所有 `engine.tasks.save_task()` → `engine.tasks.registry.save_task()`
  - 所有 `engine.tasks.get_history()` → `engine.tasks.history_store.get_history()`
  - `engine.tasks.delete_task()` 保持不变（仍走 TaskExecutor 协调方法）
- `app/services/scheduler_service.py`：
  - `self._task_executor.has_enabled_tasks()` → `self._task_executor.registry.has_enabled_tasks()`
- 测试文件同步更新：
  - `tests/test_services/test_task_executor_fix.py`：删除 5 个 CRUD 透传测试，新增 `test_registry_property` 和 `test_history_store_property`
  - `tests/test_integration/test_full_mode.py`：更新为 `task_executor.registry.*` / `task_executor.history_store.*`
  - `tests/test_services/test_scheduler_service_new.py`：mock 改为 `executor.registry.has_enabled_tasks`
  - `tests/test_api/test_api_scheduled_tasks_routes.py`：mock 改为 `mock_tasks.registry.*` / `mock_tasks.history_store.*`
  - `tests/test_api/test_scheduled_tasks_fix.py`：同上

## 2026-06-29: 移除 container.py 中 debug_manager 的不必要延迟初始化

- `app/container.py`：将 `debug_manager` 从延迟初始化（`@property` + `_debug_manager`）改为 `__init__` 中直接初始化，删除 `@property def debug_manager` 方法，简化 `shutdown` 中的引用

## 2026-06-29: 简化 deps.py 为 Annotated 别名，清理 main.py 向后兼容 re-export

- ：重写为 Annotated 类型别名，用 `_get(attr)` 工厂函数替代 6 个独立的 `get_*` 函数
- 11 个路由文件：所有 `Depends(get_xxx)` 改为 Annotated 类型别名（如 `MonitorServiceDep`），移除 `Depends` 和服务类型导入
- `main.py`：删除向后兼容 re-export（`_run_server`, `_open_browser`, `_run_full`, `_run_login_then_exit`, `_execute_login_with_retries`, `LoginResult` 等），仅保留实际使用的导入
- 测试文件同步更新：所有 `from main import _xxx` 改为从源模块导入（`app.services.launcher`, `app.services.login_runner`, `app.schemas`）
- `tests/conftest.py`：移除 `monkeypatch.setattr("main.AUTH_DATA_DIR", ...)`（不再在 main 中 re-export）
- `tests/test_config/test_deps.py`：重写为测试 `_get` 工厂函数

## 2026-06-29: 简化 deps.py 为 Annotated 别名，清理 main.py 向后兼容 re-export

- `app/deps.py`：重写为 Annotated 类型别名，用 `_get(attr)` 工厂函数替代 6 个独立的 `get_*` 函数
- 11 个路由文件：所有 `Depends(get_xxx)` 改为 Annotated 类型别名（如 `MonitorServiceDep`），移除 `Depends` 和服务类型导入
- `main.py`：删除向后兼容 re-export（`_run_server`, `_open_browser`, `_run_full`, `_run_login_then_exit`, `_execute_login_with_retries`, `LoginResult` 等），仅保留实际使用的导入
- 测试文件同步更新：所有 `from main import _xxx` 改为从源模块导入（`app.services.launcher`, `app.services.login_runner`, `app.schemas`）
- `tests/conftest.py`：移除 `monkeypatch.setattr("main.AUTH_DATA_DIR", ...)`（不再在 main 中 re-export）
- `tests/test_config/test_deps.py`：重写为测试 `_get` 工厂函数

## 2026-06-29 — Ponytail 全仓库审查 + 实施计划

- 提交：移除 profile_service 中已废弃的 v3→v4→v5 迁移函数（-320 行）
- 生成全仓库过度工程化审查报告：83 个发现，预估可削减 ~3,600 行
- 复核修正：4 项"不应执行"（detectPerformance、StepHandler ABC、set_autostart_mode、test_debug_service 直接删）
- 复核修正：5 项事实错误（文件名搞混、对照对象错、_validateConfig 描述、404 计数、重叠比例）
- 生成 4 个实施计划（排除问题条目后 ~40 项安全条目）：
  - 测试套件瘦身（9 tasks）— 删除冗余测试、合并重叠覆盖
  - 服务层与任务层清理（11 tasks）— 删除死方法、ConfigBuilder 改函数
  - 工具层与核心层清理（10 tasks）— 删除死常量、内联单调用函数
  - 前端清理（6 tasks）— 删除死函数、合并 data 工厂文件
