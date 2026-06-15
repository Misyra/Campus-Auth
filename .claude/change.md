# 修改日志

## 2026-06-15

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
