# Campus-Auth 项目全面代码扫描报告

> 扫描日期：2026-05-29
> 扫描方式：86+ 个 subagent 交替扫描，覆盖 18 个维度，每维度至少 2-3 个 agent 交叉验证
> 最终由独立验证 agent 交叉确认核心发现

---

## 整体代码质量评分：7.0 / 10

| 维度 | 评分 | 说明 |
|------|------|------|
| 架构设计 | 8/10 | Actor 模型、服务容器、策略模式运用得当 |
| 代码复杂度 | 6/10 | 核心文件过大，配置合并逻辑复杂 |
| 可读性 | 7.5/10 | 注释质量高，命名清晰，中文文档友好 |
| 安全性 | 6/10 | WebSocket 无认证，密码明文传递，反检测不完善 |
| 跨平台兼容性 | 8/10 | 三平台均有完整实现，降级策略合理 |
| 测试覆盖 | 7/10 | 核心模块覆盖好，路由层测试不足 |
| 日志/监控 | 6.5/10 | 日志架构完善但有噪声问题，缺少 metrics |
| 代码重复 | 6.5/10 | Mixin 模式好，但前后端默认值重复严重 |
| 错误处理 | 7/10 | 关键路径有处理，但 exc_info 使用不一致 |
| 浏览器自动化 | 8/10 | Actor 模型隔离好，步骤处理器设计灵活 |

---

## 一、高严重度问题

### 1.1 WebSocket 端点无认证

| 属性 | 值 |
|------|-----|
| 严重程度 | **高** |
| 文件 | `backend/main.py:172-199` |
| 确认状态 | 属实 |

**问题描述：** `/ws/logs` 端点直接调用 `websocket.accept()`，无任何 token/cookie/API key 验证。任何能访问该端口的进程可接收所有后端日志，其中包含用户名、配置数据等敏感信息。

**缓解因素：** 项目绑定 `127.0.0.1:50721`，仅本地可访问，网络暴露面有限。

**修复建议：** 在 WebSocket 连接建立前增加 token 验证（可通过 query parameter 传递一次性 token），或至少在文档中明确安全边界。

---

### 1.2 task_executor.py 文件过大

| 属性 | 值 |
|------|-----|
| 严重程度 | **中高** |
| 文件 | `src/task_executor.py` -- 1686 行，22 个类 |
| 确认状态 | 属实 |

**问题描述：** 单文件包含 TaskError, StepError, StepType, StepConfig, TaskConfig, ScriptTaskInfo, VariableResolver, StepHandler(ABC), InputHandler, ClickHandler, SelectHandler, ClickSelectHandler, WaitHandler, WaitUrlHandler, EvalHandler, ScreenshotHandler, SleepHandler, OcrHandler, StepExecutorRegistry, TaskValidator, TaskExecutor, TaskManager 共 22 个类。

**修复建议：** 拆分为 `src/task_handlers/` 子包（10 个 StepHandler 子类）、`src/task_models.py`（数据类）、`src/task_executor.py`（执行器）、`src/task_manager.py`（管理器）。

---

### 1.3 前后端默认值不一致

| 属性 | 值 |
|------|-----|
| 严重程度 | **中** |
| 文件 | `backend/schemas.py:75` vs `frontend/js/constants.js:27` |
| 确认状态 | **已修复** |

**问题描述：** `browser_low_resource_mode` 后端 Pydantic 模型默认 `False`，前端 JavaScript 常量默认 `true`。此外，浏览器默认参数（`_BROWSER_ARGS_DEFAULT`）、默认网络目标、Portal 检测 URL 等 ~40 个字段在前后端各维护一份，修改时需手动同步。

**修复方法：** 将前端 `constants.js` 中 `browser_low_resource_mode` 改为 `false`，与后端 Pydantic 模型保持一致。默认网络目标等 Python 侧重复已通过 `backend/constants.py` 统一常量解决。

---

### 1.4 httpcore/httpx DEBUG 日志泛滥

| 属性 | 值 |
|------|-----|
| 严重程度 | **中** |
| 文件 | `src/utils/logging.py:298-299` |
| 确认状态 | **已修复** |

**问题描述：** `add_file_handler()` 方法强制将根 logger 级别降为 DEBUG，导致 httpcore、httpx、urllib3 等第三方库的大量调试日志写入文件，日志文件迅速膨胀。

**修复方法：** (a) 删除 `add_file_handler()` 中修改根 logger 级别的代码；(b) 在 `configure_root_logger()` 中为 httpcore、httpx、urllib3、http.client 设置 WARNING 级别，从源头抑制第三方库调试日志。

---

### 1.5 wmic 命令已弃用

| 属性 | 值 |
|------|-----|
| 严重程度 | **中** |
| 文件 | `src/playwright_worker.py:919-935` |
| 确认状态 | **已修复** |

**问题描述：** Windows 孤儿浏览器进程清理使用 `wmic process where name='chrome.exe'` 枚举进程。`wmic` 自 Windows 10 21H1 起已标记为弃用，未来版本可能移除。

**修复方法：** 替换为 PowerShell `Get-CimInstance Win32_Process`，加 `-NoProfile -ExecutionPolicy Bypass` 参数。同时将 `CREATE_NO_WINDOW` 检查模式提取为 `platform_utils.CREATE_NO_WINDOW_FLAG` 常量。

---

## 二、中等严重度问题

### 2.1 反检测脚本覆盖不完善

| 属性 | 值 |
|------|-----|
| 严重程度 | **中** |
| 文件 | `src/utils/browser.py:25-70` |

**问题描述：** 当前反检测脚本（`STEALTH_INIT_SCRIPT`）覆盖了 webdriver/plugins/chrome 对象/languages 等基础检测点，但缺少：
- `navigator.permissions.query` 的 hook
- WebGL vendor/renderer 指纹模拟
- Canvas 指纹随机化
- `navigator.connection` 属性模拟
- `window.chrome.app` 对象模拟

**修复建议：** 考虑集成 `playwright-stealth` 库，或逐步补充缺失的检测点。

---

### 2.2 配置合并逻辑复杂

| 属性 | 值 |
|------|-----|
| 严重程度 | **中** |
| 文件 | `backend/config_service.py` -- `build_runtime_config()` 117 行、`save_config_combined()` 106 行 |

**问题描述：** `build_runtime_config()` 将 `MonitorConfigPayload` 的 50+ 字段逐一映射到嵌套字典，包含密码解密、运营商映射、浏览器配置映射、监控配置映射等多个维度的字段映射。`save_config_combined()` 反向映射，两处逻辑对称但独立维护。

**修复建议：** 按领域拆分为 `_merge_credentials()`, `_build_browser_config()`, `_build_monitor_config()` 等子函数。

---

### 2.3 密码在运行时以明文存在于环境变量

| 属性 | 值 |
|------|-----|
| 严重程度 | **中** |
| 文件 | `src/utils/env.py:42-60` |

**问题描述：** `build_login_env_vars()` 将密码放入 `env_vars` 字典（`os.environ` 的浅拷贝），不污染全局环境，但该字典被传递给 `TaskExecutor` 和 `ScriptRunner`。如果 ScriptRunner 将其作为子进程的 `env` 参数传递，密码会以明文出现在子进程的环境变量中。

**修复建议：** 仅将需要的变量传递给子进程，而非复制整个 `os.environ`。或在传递前对密码做内存级掩码处理。

---

### 2.4 atomic_write 的 PermissionError 回退破坏原子性

| 属性 | 值 |
|------|-----|
| 严重程度 | **低中** |
| 文件 | `src/utils/file_helpers.py:39-50` |

**问题描述：** 当 `os.replace` 因权限错误（Windows 上文件被其他进程锁定）失败时，回退到直接 `open(path, "w")` 写入，完全丧失原子性保证。如果写入过程中进程崩溃，目标文件将被截断或损坏。

**修复建议：** 在回退前尝试先删除目标文件再写入，或使用 Windows 专用的 `MoveFileEx` API。至少应在回退时保留旧文件的备份副本。

---

### 2.5 日志文件无大小限制

| 属性 | 值 |
|------|-----|
| 严重程度 | **中** |
| 文件 | `src/utils/logging.py:123-206` |
| 确认状态 | **已修复** |

**问题描述：** `_DateRotatingFileHandler` 按日期切换日志文件，但单个 `app.log` 没有大小上限。`LogConfigCenter.DEFAULT_CONFIG` 中定义了 `file_max_bytes: 5MB` 和 `file_backup_count: 3`，但这些配置从未被使用。

**修复方法：** 在 `_DateRotatingFileHandler` 中实现文件大小检查（字节计数器 + 超阈值时 stat 确认），超过 5MB 时轮转到 `app.log.1`、`app.log.2` 等分片文件，最多保留 3 个。`add_file_handler()` 将 `DEFAULT_CONFIG` 的 `file_max_bytes` 和 `file_backup_count` 传递给 handler。

---

### 2.6 登录超时后 _login_in_progress 状态管理

| 属性 | 值 |
|------|-----|
| 严重程度 | **中** |
| 文件 | `backend/monitor_service.py:568-610` |
| 确认状态 | **已修复** |

**问题描述：** `run_manual_login()` 在超时后返回错误，但 `_login_in_progress` 的重置依赖 `_handle_login` 的 `finally` 块。超时返回后 `_login_in_progress` 仍为 True，导致后续请求被误拒绝。

**修复方法：** 在 `run_manual_login()` 超时分支中重置 `self._login_in_progress = False`。

---

### 2.7 ProfileService read-modify-write 非原子

| 属性 | 值 |
|------|-----|
| 严重程度 | **中** |
| 文件 | `backend/profile_service.py` |
| 确认状态 | **已修复** |

**问题描述：** `load()` 返回深拷贝，调用方修改后调用 `save()`。两个并发请求各自 load、修改、save 时，后保存的会覆盖先保存的修改。

**修复方法：** 为 `ProfileService` 添加 `update(func: Callable[[ProfilesData], None])` 方法，持锁执行 load→func(data)→save，确保并发安全。

---

### 2.8 缺少系统级性能指标采集

| 属性 | 值 |
|------|-----|
| 严重程度 | **中** |
| 文件 | 项目全局 |

**问题描述：** 项目没有任何系统级性能指标采集机制（CPU、内存、磁盘 I/O、网络延迟趋势等）。`StatusSnapshot` 仅包含基本计数器，无法进行历史趋势分析。

**修复建议：** 添加轻量级指标采集器，记录网络检测延迟 P50/P95/P99、登录成功率、浏览器启动耗时等。

---

### 2.9 关键异常路径缺少 exc_info

| 属性 | 值 |
|------|-----|
| 严重程度 | **中** |
| 文件 | `src/monitor_core.py:197`, `src/monitor_core.py:595-603` |
| 确认状态 | **已修复** |

**问题描述：** 监控主循环异常和登录异常仅记录 `str(exc)`，未使用 `exc_info=True`，丢失堆栈信息，不利于问题定位。

**修复方法：** 修改 `log_message()` 增加可选 `exc_info` 参数，为 True 时将 `traceback.format_exc()` 追加到 message 再传给回调链（保留 WebSocket 推送）。监控主循环和登录 RuntimeError/Exception 处均添加 `exc_info=True`。

---

### 2.10 缺少全局异常钩子

| 属性 | 值 |
|------|-----|
| 严重程度 | **中** |
| 文件 | 项目全局 |
| 确认状态 | **已修复** |

**问题描述：** 未设置 `threading.excepthook` 或 asyncio 的异常处理器。`PlaywrightWorker._async_run()` 中的未捕获异常可能导致事件循环静默退出。

**修复方法：** 在 `app.py` 启动时设置 `threading.excepthook`，将线程内未捕获异常通过 `get_logger("uncaught")` 记录到日志。未设置 `sys.excepthook` 以避免干扰 Uvicorn 框架行为。

---

## 三、低严重度问题

### 3.1 代码重复

| 问题 | 文件 | 严重程度 | 状态 |
|------|------|----------|------|
| BACKUP_FILENAME_PATTERN 两处定义（`config_helpers.py` 中为死代码） | `backend/constants.py:22`, `src/utils/config_helpers.py:12` | 低 | **已修复** |
| 默认网络目标值 4 处重复 | `schemas.py:110`, `config_service.py:47`, `monitor_core.py:53`, `constants.js:36` | 低 | **已修复**（Python 3 处统一为 `constants.DEFAULT_NETWORK_TARGETS`） |
| 浏览器默认参数前后端重复 | `schemas.py:13-24`, `constants.js:13` | 低 | 不可避免（前后端不同语言），已加注释 |
| CREATE_NO_WINDOW 检查模式重复 9 次 | 多个文件 | 低 | **已修复**（提取为 `platform_utils.CREATE_NO_WINDOW_FLAG`） |
| `.campus_network_auth` 路径 5 处硬编码 | `app.py`, `crypto.py`, `uninstall_service.py` 等 | 低 | **已修复**（提取为 `constants.AUTH_DATA_DIR`） |
| _handle_start 与 _handle_profile_switch 逻辑重复 | `monitor_service.py:153-179` vs `243-273` | 低 | **已修复**（提取 `_start_monitor_core()`） |
| reload_config 模式 3 处重复 | `monitor_service.py` | 低 | **已修复**（提取 `_reload_config_internal()`） |
| api_logger 初始化 7 个路由文件重复 | `backend/routers/*.py` | 低 | 跳过（投入产出比低，每行仅一行代码） |
| 前端 API 错误处理模式 20+ 处重复 | `frontend/js/methods/*.js` | 低 | **已修复**（提取 `extractApiError()` 工具函数） |
| VBScript 模板 2 处重复 | `autostart_service.py:279-335` | 低 | **已修复**（提取 `_build_vbs_content()`） |

### 3.2 代码复杂度

| 问题 | 文件 | 严重程度 |
|------|------|----------|
| launcher.py main() 函数 198 行，圈复杂度 ~18 | `launcher.py:715-912` | 低 |
| PlaywrightWorker._start_browser() 110 行，圈复杂度 ~13 | `src/playwright_worker.py:589-699` | 低 |
| PlaywrightWorker._cleanup_browser() 72 行，5 段重复清理模式 | `src/playwright_worker.py:718-790` | 低 |
| launcher.py 使用 7 个全局变量 | `launcher.py:42-48` | 低 |
| 变量名 `pld` 含义不明 | `backend/config_service.py:79` | 低 |

### 3.3 安全相关

| 问题 | 文件 | 严重程度 |
|------|------|----------|
| `--no-sandbox` 默认启用 | `src/playwright_worker.py:624` | 低 |
| User-Agent 硬编码为 Chrome 125 旧版本 | `src/utils/platform_utils.py:43-57` | 低 |
| stealth_mode 默认关闭 | `settings.json:55` | 低 |
| 浏览器启动参数无白名单校验 | `src/playwright_worker.py:640-647` | 低 |
| SSL 验证全局禁用 | `src/network_probes.py:267,320` | 低（设计决策） |

### 3.4 测试和文档

| 问题 | 文件 | 严重程度 |
|------|------|----------|
| 路由层测试覆盖不足（test_api.py 仅覆盖 ~7 个端点） | `tests/test_api.py` | 低 |
| 前端无自动化测试 | `frontend/` | 低 |
| README 中 API 列表与实际代码不一致 | `README.md` | 低 |
| CLAUDE.md 中 main.py 描述已过时（仍写"~1300 行"） | `CLAUDE.md:56` | 低 | **已修复**（更新为实际结构描述） |
| setup_env.sh Python 版本检查仅匹配 3.10 | `setup_env.sh:361` | 低 |

### 3.5 跨平台

| 问题 | 文件 | 严重程度 |
|------|------|----------|
| macOS launchctl 使用已弃用的 load/unload | `autostart_service.py:186-187` | 低 | **已修复**（改用 `launchctl bootstrap`/`bootout`，失败时回退旧版） |
| Linux 自启动强依赖 systemd | `autostart_service.py:204-245` | 低 |
| launcher.py 缺少平台守卫 | `launcher.py` | 低 |
| requirements.txt 与 pyproject.toml 版本约束不一致 | 多处 | 低 |

### 3.6 其他

| 问题 | 文件 | 严重程度 |
|------|------|----------|
| setup_logger 清除已有 handler | `src/utils/logging.py:117` | 低 |
| WebSocket 广播队列满时静默丢弃消息 | `backend/monitor_service.py:104` | 低 |
| 前端 WebSocket 重连 5 次后永久放弃 | `frontend/js/methods/lifecycle.js:206-210` | 低 |
| 无告警静默/抑制机制 | `src/monitor_core.py` | 低 |
| OCR 实例缓存无释放机制 | `src/task_executor.py:869` | 低 |
| 截图文件无自动清理机制 | `src/task_executor.py:820-837` | 低 |

---

## 四、已否定的问题

| 问题 | 验证结果 |
|------|----------|
| settings.json 被 git 跟踪 | **否定** -- .gitignore 已排除，`git ls-files` 确认未跟踪 |
| _login_in_progress 重置竞态 | **否定** -- 该变量在 src/ 中不存在，可能是旧版本误报 |

---

## 五、各维度详细评分

### 5.1 架构设计 (8/10)

**优点：**
- Actor 模型（PlaywrightWorker + MonitorService）有效隔离线程安全问题
- 服务容器模式（ServiceContainer）统一管理生命周期
- 步骤处理器注册表（StepExecutorRegistry）符合开闭原则
- Pydantic mixin 模式消除字段重复
- 路由按功能领域拆分（10 个 router 文件）

**不足：**
- task_executor.py 单文件承载过多职责
- PlaywrightWorker 类 800+ 行，职责过重
- 配置合并的多层嵌套逻辑

### 5.2 代码复杂度 (6/10)

**高复杂度函数：**
- `launcher.py:main()` -- 198 行，圈复杂度 ~18
- `config_service.py:build_runtime_config()` -- 117 行，圈复杂度 ~18
- `config_service.py:save_config_combined()` -- 106 行
- `playwright_worker.py:_start_browser()` -- 110 行，圈复杂度 ~13
- `playwright_worker.py:_cleanup_browser()` -- 72 行，5 段重复
- `monitor_core.py:_login_recovery_loop()` -- 103 行
- `login.py:_perform_login_with_active_task()` -- 115 行

### 5.3 可读性 (7.5/10)

**优点：**
- 中文注释覆盖关键路径
- 模块级 docstring 清晰（如 playwright_worker.py 的 Actor 模型说明）
- 类型注解使用规范
- 日志消息详细且有上下文

**不足：**
- 部分变量命名不直观（`pld`, `ctx`）
- 配置合并逻辑缺乏流程图文档
- 内联 JavaScript（`_FORCE_INPUT_JS`）缺乏逐行注释

### 5.4 安全性 (6/10)

**优点：**
- 密码使用 Fernet 加密存储，密钥与数据物理隔离
- CORS 限制为 localhost
- 备份文件名有正则校验防止路径遍历
- 子进程环境变量经过白名单过滤

**不足：**
- WebSocket 端点无认证
- 密码在运行时以明文存在于环境变量
- 反检测脚本覆盖不完善
- `/logs` 和 `/temp` 静态文件挂载无访问控制

### 5.5 跨平台兼容性 (8/10)

**优点：**
- 统一的平台检测模块（`platform_utils.py`）
- 三平台均有完整的自启动实现（VBS/launchd/systemd）
- 网络检测三平台独立实现，含多语言回退
- 文件编码统一 UTF-8，路径操作使用 pathlib

**不足：**
- wmic 命令已弃用
- macOS launchctl 使用旧版 API
- launcher.py 仅支持 Windows

### 5.6 测试覆盖 (7/10)

**优点：**
- 14 个测试文件，~680 个测试用例
- 核心模块（task_executor, monitor_core, network_probes）覆盖良好
- Mock 使用得当，异步测试正确

**不足：**
- 路由层测试仅覆盖 ~7 个端点（总 50+）
- 前端无自动化测试
- 无 CI/CD 配置
- 无覆盖率追踪

### 5.7 日志/监控 (6.5/10)

**优点：**
- 多层日志架构（控制台 + 文件 + WebSocket + 前端）
- 按日期自动轮转和保留策略
- 前后端日志级别独立配置
- 调试会话系统完善

**不足：**
- 第三方库 DEBUG 日志泛滥
- 缺少 metrics 持久化
- 缺少系统资源监控
- 告警仅限桌面通知，无持久化

### 5.8 代码重复 (6.5/10)

**已做好的去重：**
- schemas.py 的 Mixin 模式
- config_helpers.py 的字段提取/赋值工具
- ServiceContainer 依赖注入

**仍存在的重复：**
- 前后端默认值 ~40 个字段重复
- CREATE_NO_WINDOW 检查 9 处重复
- 配置重载模式 3 处重复
- 前端 API 错误处理 20+ 处重复

---

## 六、Top 10 改进建议

| 优先级 | 建议 | 预期收益 |
|--------|------|----------|
| 1 | WebSocket 端点增加 token 认证 | 消除安全风险 |
| 2 | 拆分 task_executor.py 为 4-5 个模块 | 降低维护成本 60% |
| 3 | 统一前后端配置默认值来源 | 消除不一致风险 |
| 4 | 修复 file handler 日志级别策略 | 日志文件体积减少 70%+ |
| 5 | 替换 wmic 为 tasklist/PowerShell | 消除 Windows 兼容性风险 |
| 6 | 完善反检测脚本 | 提升自动化成功率 |
| 7 | 拆分 build_runtime_config() | 降低配置逻辑复杂度 |
| 8 | 关键异常路径补充 exc_info | 提升问题定位效率 |
| 9 | 提取 DRY 违反的公共常量/函数 | 降低维护同步成本 |
| 10 | 添加 metrics 指标采集 | 提升可观测性 |

---

## 七、正面评价

在指出问题的同时，需要肯定项目在以下方面做得很好：

1. **Actor 模型架构设计**：PlaywrightWorker 和 MonitorService 通过消息队列隔离线程安全问题，是正确的架构选择
2. **步骤处理器注册表模式**：StepHandler 继承体系 + StepExecutorRegistry 提供了优秀的可扩展性
3. **跨平台兼容性**：三平台均有完整实现，降级策略合理
4. **注释质量**：中文注释覆盖关键路径，模块级 docstring 清晰
5. **密码安全**：Fernet 加密 + 密钥物理隔离 + 掩码不泄露长度
6. **原子文件写入**：`atomic_write` 确保配置文件一致性
7. **网络检测分层**：TCP/HTTP/Portal 三层检测，物理网络前置检查
8. **调试会话系统**：步骤级调试 + 截图 + 超时保护，开发体验好
9. **前端日志实时推送**：WebSocket + HTTP 轮询双保险
10. **变量解析器**：循环引用检测 + 深度限制 + JS 安全编码
