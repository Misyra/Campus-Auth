# Campus-Auth 代码审查报告

> 审查时间：2026-06-16
> 审查范围：全项目（跳过日志系统 app/utils/logging.py）
> Review Unit 数量：13
> 已排除 `.claude/not-to-do.md` 中的设计决策和误判项（见附注）

## 摘要

| 严重性 | 数量 |
|--------|------|
| 🔴 Critical | 10 |
| 🟠 Major | 35 |
| 🟡 Minor | 23 |
| 总计 | 68 |

| 模块 | Critical | Major | Minor |
|------|----------|-------|-------|
| 浏览器自动化核心 (playwright_worker / browser) | 1 | 4 | 3 |
| 浏览器注册与安装 (browser_registry / bootstrap / icons) | 2 | 3 | 2 |
| 调度引擎 (engine / monitor_service) | 0 | 4 | 4 |
| 任务执行中心 (task_executor / shell_policy) | 1 | 4 | 3 |
| 配置服务 (config_service / runtime_config / schemas) | 0 | 3 | 3 |
| 应用入口与容器 (main / application / container) | 1 | 3 | 1 |
| 任务系统 (tasks/*) | 2 | 3 | 2 |
| 网络检测 (network/*) | 0 | 4 | 4 |
| 加密与安全工具 (crypto / repo_proxy / files / process) | 0 | 2 | 3 |
| 脚本任务执行 (script_runner / task_service / scripts) | 1 | 4 | 2 |
| 调试会话管理 (debug_service / debug_session) | 2 | 3 | 2 |
| 前端浏览器选择 UI (frontend/*) | 0 | 4 | 4 |

---

## 🔴 Critical 问题

### [1] 浏览器 `__aexit__` 发送关闭命令与 `ensure_browser` 每次重建冲突

- **模块**：浏览器自动化核心
- **文件**：`app/utils/browser.py:116-148` + `app/workers/playwright_worker.py:635-643`
- **分类**：🟡 性能
- **描述**：`BrowserContextManager.__aexit__` 通过 `submit_nowait(CMD_BROWSER_CLOSE)` 异步发送关闭命令（fire-and-forget），但 `ensure_browser` 每次调用都执行 `_close_browser()` + `_start_browser(config)` 无条件重建。一次登录流程中浏览器被启动 2 次、关闭 2 次——`ensure_browser` 关闭一次，`__aexit__` 又关闭刚新建的浏览器。Playwright 使用 `launch` 创建独立进程，不会影响用户已打开的浏览器。
- **影响**：每次登录多一次浏览器启停的性能开销（约 2-3 秒）。非崩溃、非安全问题。
- **建议修复方向**：当前为有意设计（"删除浏览器复用逻辑，ensure_browser 每次都重新启动浏览器"）。若需优化，可让 `ensure_browser` 检查浏览器健康状态后复用，或移除 `__aexit__` 中的关闭逻辑。

### [2] `ensure_task_pool` 懒初始化无锁保护

- **模块**：任务执行中心
- **文件**：`app/services/task_executor.py:147-151`
- **分类**：🔴 崩溃/安全
- **描述**：`_ensure_task_pool` 在判断 `self._task_pool is None` 后赋值，无任何锁机制。多线程并发调用 `execute_task_async` 可能各自创建 `BoundedExecutor` 实例，后创建的覆盖前一个，导致线程池泄漏。
- **影响**：资源泄漏（泄漏一个线程池及其内部线程）、提交到被覆盖线程池的任务 Future 丢失、shutdown 时无法关闭被覆盖的线程池。
- **建议修复方向**：使用 `threading.Lock` 保护懒初始化的双检锁模式。

### [3] 轻量模式下创建了真正的 TaskExecutor 而非 NullTaskExecutor

- **模块**：应用入口与容器
- **文件**：`app/container.py:54-60`
- **分类**：🔴 崩溃/安全
- **描述**：容器构造函数始终创建真正的 `TaskExecutor` 实例，没有根据 `_is_lightweight` 标志切换为 `NullTaskExecutor`。真正的 `TaskExecutor` 在构造时会初始化登录专用线程池（1 个工作线程），在轻量模式下是不必要的资源浪费。
- **影响**：轻量模式下依然创建线程池消耗资源；如果 TaskExecutor 尝试使用 Playwright Worker，可能在轻量模式下产生未预期的副作用。
- **建议修复方向**：在第 54 行附近加入轻量模式判断，创建 `NullTaskExecutor` 而非 `TaskExecutor`。

### [4] Chromium 检测逻辑完全重复，维护隐患

- **模块**：浏览器注册与安装
- **文件**：`app/workers/playwright_bootstrap.py:92-141` + `app/utils/browser_registry.py:149-186`
- **分类**：🔴 可靠性
- **描述**：`_has_chromium()` 和 `_has_playwright_chromium()` 实现几乎完全相同的逻辑——扫描 `ms-playwright` 缓存目录下的 `chromium-*` 子目录。`playwright_bootstrap.py` 的版本还多了一个回退到 `sync_playwright` 的慢速路径。两份代码各自独立维护，极易出现不一致。
- **影响**：bootstrap 判断已安装而 API 报告未安装（或反之），前端显示与实际行为矛盾。
- **建议修复方向**：将 Chromium 检测逻辑抽取到 `browser_registry.py` 的公共函数中，`playwright_bootstrap.py` 直接复用。

### [5] `install_playwright` 端点并发保护使用布尔变量，存在竞态

- **模块**：浏览器注册与安装
- **文件**：`app/api/install_playwright.py:16-69`
- **分类**：🔴 崩溃/安全
- **描述**：`_installing` 是普通的模块级 `bool`，用 `if _installing` + `_installing = True` 做并发保护。在多 worker 进程或前端快速连点场景下，两个协程可能同时进入安装流程。
- **影响**：重复执行 Playwright Chromium 安装，浪费带宽和磁盘 I/O；极端情况下可能导致下载冲突。
- **建议修复方向**：使用 `asyncio.Lock()` 代替布尔变量。

### [6] `resolve_for_js` 双重编码和类型不一致

- **模块**：任务系统
- **文件**：`app/tasks/variable_resolver.py:99-117`
- **分类**：🔴 崩溃/安全
- **描述**：`resolve_for_js` 调用 `resolve()` 后直接 `json.dumps(resolved)`。当变量值是 `None`/布尔值/数字时，输出不再是引号包裹的字符串。更关键的是 `resolve` 对非字符串值已做 `json.dumps`，`resolve_for_js` 再做一次形成双重编码。
- **影响**：变量替换结果与用户预期不一致，可能导致 JS 执行逻辑错误或任务步骤静默失败。极端场景下恶意构造的变量值可突破 JS 字符串边界。
- **建议修复方向**：统一将解析结果 `str()` 转为字符串后再 `json.dumps`，确保输出始终是带引号的 JS 字符串字面量。

### [7] 变量解析缓存未绑定上下文，外部修改变量后返回过期结果

- **模块**：任务系统
- **文件**：`app/tasks/variable_resolver.py:42-44, 88-91`
- **分类**：🔴 可靠性
- **描述**：`_cache` 以原始字符串 `value` 为 key 缓存解析结果。`template_vars` 和 `config.variables` 在运行期间被外部修改（Python dict 是引用类型）时，缓存不会被清除，返回的是旧值。
- **影响**：在长时间运行或外部动态修改变量配置的场景下，变量解析返回过期值，导致任务步骤使用错误数据。
- **建议修复方向**：增加版本号机制，`set_runtime_var` 递增版本号，`resolve` 检查版本号是否匹配。

### [8] 脚本执行白名单自动追加 + binary_path 未校验

- **模块**：脚本任务执行
- **文件**：`app/workers/script_runner.py:192-201` + `app/api/scripts.py:47-57`
- **分类**：🔴 崩溃/安全
- **描述**：两层问题叠加：(1) 如果 `self.binary_path` 不在 `detect_available_binaries()` 返回的列表中，代码只打印 warning 日志后就将其自动追加到 `available` 列表中，实质上绕过了 `ShellCommandPolicy` 的白名单机制；(2) `save_script` 端点 `payload: dict` 未使用 Pydantic 模型校验输入，`binary_path` 直接存储并在后续执行时使用。
- **影响**：用户可通过 API 提交任意脚本内容并指定任意解释器路径，白名单形同虚设。
- **建议修复方向**：移除自动追加逻辑，对不在已知列表中的 `binary_path` 直接拒绝执行并返回错误。将 `binary_path` 限制为已知解释器的枚举值。
- **⛔ 已排除**（per `.claude/not-to-do.md`）：白名单是已知解释器发现机制而非安全防线；自动追加是合理的降级策略，warning 已提示用户。单用户桌面应用场景下用户已拥有完整系统权限，限制解释器路径无实际安全收益。若优化应改到前端保存时提示"该路径不在已知列表中，是否继续？"，后端只做路径存在性检查。

### [9] `run_all` 在锁外访问共享 `_session` 存在竞态

- **模块**：调试会话管理
- **文件**：`app/services/debug_service.py:252-253`
- **分类**：🔴 崩溃/安全
- **描述**：第 252 行 `if self._session is not session or not session.running:` 在信号量和锁块之外执行。此时 `stop()` 或 `start()` 可能已替换 `self._session` 并关闭了旧会话的浏览器，但这里仍在用过期引用做判断。
- **影响**：并发调用 `stop()` + `run_all()` 时，`run_all` 可能在会话已被销毁后继续向 Worker 提交步骤命令。
- **建议修复方向**：将会话有效性检查移入 `async with self._lock` 块内。

### [10] 超时监控器无锁读取 `_session._last_activity`

- **模块**：调试会话管理
- **文件**：`app/services/debug_service.py:70-94`
- **分类**：🔴 崩溃/安全
- **描述**：`_debug_timeout_watcher` 第 80 行在锁外读取 `self._session._last_activity`。`self._session` 可能已被替换为全新的 `empty_debug_session()`（`_last_activity` 为 0.0），导致立即触发超时判定。
- **影响**：误判为超时并尝试关闭浏览器，可能引发对已关闭会话的重复关闭操作或竞态异常。
- **建议修复方向**：将 `_last_activity` 的读取也放入锁保护范围内。

---

## 🟠 Major 问题

### [11] `submit_nowait` 缺少队列满的异常处理和事件循环唤醒

- **模块**：浏览器自动化核心
- **文件**：`app/workers/playwright_worker.py:295-297`
- **分类**：🟠 可靠性
- **描述**：`submit_nowait` 直接调用 `self._cmd_queue.put_nowait()`，无 try/except 处理 `queue.Full`，也不调用 `_wake_async()` 唤醒事件循环。命令放入队列后需等待 0.5 秒超时兜底才能被处理。
- **影响**：命令延迟最高 0.5 秒；如果 Worker 正在 await 长时间操作，命令会等到操作完成后才被消费。
- **建议修复方向**：在 `submit_nowait` 中也调用 `run_coroutine_threadsafe(self._wake_async(), loop)` 立即唤醒事件循环。

### [12] `cleanup_orphan_browsers` 只清理 Chromium，遗漏 Firefox 和 custom

- **模块**：浏览器自动化核心
- **文件**：`app/workers/playwright_worker.py:1008-1037`
- **分类**：🟠 可靠性
- **描述**：项目已扩展支持 Firefox 和自定义浏览器路径，但 `cleanup_orphan_browsers` 只扫描包含 `"chrom"` 关键字的进程。
- **影响**：Firefox 或自定义浏览器的孤儿进程会残留，持续占用系统内存。
- **建议修复方向**：扩展清理逻辑，增加对 `"firefox"` 关键字的匹配。

### [13] `get_worker()` 存在 TOCTOU 竞态

- **模块**：浏览器自动化核心
- **文件**：`app/workers/playwright_worker.py:975-993`
- **分类**：🟠 可靠性
- **描述**：`get_worker()` 在锁内调用 `_worker.stop()` + `cleanup_orphan_browsers()` + `_worker.start()` 是同步阻塞操作。第二个线程在锁外检查 `is_alive()` 可能看到旧 Worker 已死但新 Worker 尚未 `start()`。
- **影响**：调用方可能拿到一个尚未完成初始化的 Worker，`submit()` 命令会超时。
- **建议修复方向**：将 `_worker` 的赋值放在 `start()` 成功之后。

### [14] `_handle_debug_stop` 重建页面时反检测脚本行为与初始启动不一致

- **模块**：浏览器自动化核心
- **文件**：`app/workers/playwright_worker.py:444-528, 586-593`
- **分类**：🟠 可靠性
- **描述**：纯净模式下 `_start_browser` 有条件地调用 `_apply_stealth_and_routes`，但 `_handle_debug_stop` 重建页面时无条件调用，传入的 `browser_settings` 可能不包含 `stealth_mode` 标志。
- **影响**：调试会话停止后重建的页面可能意外启用或禁用反检测脚本，与初始启动时行为不一致。
- **建议修复方向**：`_handle_debug_stop` 中重建页面时使用与 `_start_browser` 完全相同的判断逻辑。

### [15] SVG 图标路径遍历防护使用字符串前缀匹配

- **模块**：浏览器注册与安装
- **文件**：`app/api/icons.py:24-26`
- **分类**：🟠 安全
- **描述**：使用 `str(icon_path).startswith(str(ICONS_DIR.resolve()))` 防止路径遍历。`E:\Campus-Auth\res\icons-evil\foo.svg` 也会通过 `startswith` 检查。
- **影响**：如果未来添加更多文件类型或子目录支持，该绕过可导致任意文件读取。
- **建议修复方向**：使用 `Path.is_relative_to()` (Python 3.9+) 代替字符串 `startswith` 比较。
- **⛔ 已排除**（per `.claude/not-to-do.md`）：localhost 访问，`.svg` 扩展名已限制。

### [16] `ensure_playwright_ready` 修改全局 `os.environ` 无回滚

- **模块**：浏览器注册与安装
- **文件**：`app/workers/playwright_bootstrap.py:216-228`
- **分类**：🟠 可靠性
- **描述**：镜像源回退循环中每次迭代直接修改 `os.environ["PLAYWRIGHT_DOWNLOAD_HOST"]`，所有下载源都失败后环境变量被污染。
- **影响**：用户预设的 `PLAYWRIGHT_DOWNLOAD_HOST` 被永久覆盖；后续子进程读取该变量会拿到错误的值。
- **建议修复方向**：函数入口保存原始值，函数结束恢复原值。

### [17] Firefox 检测在 Windows 上缺少 `LOCALAPPDATA` 路径

- **模块**：浏览器注册与安装
- **文件**：`app/utils/browser_registry.py:111-134`
- **分类**：🟠 可靠性
- **描述**：`_detect_firefox()` 在 Windows 上只检查 `PROGRAMFILES` 和 `PROGRAMFILES(X86)`，遗漏了 `%LOCALAPPDATA%\Mozilla Firefox`（用户安装版默认路径）。
- **影响**：Windows 上通过用户级安装的 Firefox 会被错误标记为"未安装"。
- **建议修复方向**：补充 `LOCALAPPDATA` 路径，与 `_detect_chrome()` 保持一致。

### [18] `detect_browsers()` 每次调用都执行 I/O，无缓存

- **模块**：浏览器注册与安装
- **文件**：`app/utils/browser_registry.py:38-50`
- **分类**：🟠 性能
- **描述**：`detect_browsers()` 被 `/api/browsers` 调用，每次请求都执行 `shutil.which()`、`Path.exists()`、`Path.glob()` 等文件系统操作。
- **影响**：在文件系统较慢的环境中 API 响应可能较慢。
- **建议修复方向**：添加 TTL 缓存（30-60 秒），避免短时间内重复扫描。

### [19] `_do_async_login` 手动登录路径污染自动重试计数

- **模块**：调度引擎
- **文件**：`app/services/engine.py:311-338`
- **分类**：🟠 可靠性
- **描述**：`_do_async_login` 被自动重试和手动登录两条路径调用，都会执行 `self._login_retry.count += 1`。手动登录消耗重试计数，导致实际自动重试次数少于配置值。
- **影响**：自动重试次数被手动登录消耗，可能提前终止重试。
- **建议修复方向**：手动登录路径不应修改 `_login_retry.count`。

### [20] `start_monitoring` 存在 TOCTOU 竞态

- **模块**：调度引擎
- **文件**：`app/services/engine.py:653-666`
- **分类**：🟠 可靠性
- **描述**：`start_monitoring` 中检查 `self._is_monitoring` → 验证配置 → 入队 START 之间，另一个线程可能已经调用了 `stop_monitoring`。配置验证用的 `_runtime_config` 可能与实际执行时不同。
- **影响**：配置验证与实际执行使用不同配置。
- **建议修复方向**：将配置验证移到引擎线程内的 `_handle_start` 中执行。

### [21] `shutdown` 直接操作 `_monitor_core` 绕过 Actor 模型

- **模块**：调度引擎
- **文件**：`app/services/engine.py:678-701`
- **分类**：🟠 可靠性
- **描述**：`shutdown` 在第 686-689 行直接调用 `self._monitor_core.stop_monitoring()` 并设为 None。引擎线程可能正在执行 `_do_network_check`，检查 `self._monitor_core is not None` 后进入 try 块，但 `shutdown` 可能在检查之后将其设为 None。
- **影响**：关闭时可能产生 `AttributeError` 日志噪音。
- **建议修复方向**：在 `_do_network_check` 开头获取本地引用后使用该本地变量。

### [22] `execute_login_async` 去重返回旧 Future，调用方 cancel_event 丢失

- **模块**：任务执行中心
- **文件**：`app/services/task_executor.py:210-227`
- **分类**：🟠 可靠性
- **描述**：去重场景下直接返回已有的 `self._login_future`，新调用方的 `cancel_event` 被静默丢弃。调用方可能误以为可以通过 cancel_event 控制该登录。
- **影响**：UI 层点击"取消登录"时无法真正取消执行中的登录。
- **建议修复方向**：返回包装对象告知调用方这是去重的 Future，或将新 cancel_event 合并到已有任务中。

### [23] 异步 `ShellCommandPolicy.run` 未对 kwargs 做白名单过滤

- **模块**：任务执行中心
- **文件**：`app/utils/shell_policy.py:97-136`
- **分类**：🟠 安全
- **描述**：`run_sync` 正确实现了 `_ALLOWED_KWARGS = {"env", "cwd"}` 白名单过滤，但异步 `run` 方法直接将 `**kwargs` 展开传给 `create_subprocess_exec`，缺少同样的过滤。
- **影响**：安全策略被绕过的风险——调用方可通过 kwargs 传入 `stdin`、`preexec_fn` 等未预期参数。
- **建议修复方向**：对异步 `run` 方法也实现相同的白名单过滤。
- **⛔ 已排除**（per `.claude/not-to-do.md`）：用户自己写的脚本，单用户场景。

### [24] `_get_script_path` 路径推断脆弱

- **模块**：任务执行中心
- **文件**：`app/services/task_executor.py:495-520`
- **分类**：🟠 可靠性
- **描述**：通过 `tasks_dir.parent.parent` 硬编码推断项目根目录，依赖于目录深度恰好是 `project_root/tasks/scheduled/` 的结构。
- **影响**：目录结构变化时脚本任务无法找到对应的脚本文件。
- **建议修复方向**：在 `TaskRegistry` 或 `TaskManager` 上显式提供 `get_script_path` 方法。

### [25] `ShellCommandPolicy` 白名单不做路径规范化

- **模块**：任务执行中心
- **文件**：`app/utils/shell_policy.py:46-60`
- **分类**：🟠 安全
- **描述**：路径比较仅在 Windows 上做 `lower()` 处理，不调用 `Path.resolve()` 进行完整路径规范化。`/usr/bin/../bin/bash` 这样的路径变体可能绕过白名单。
- **影响**：边界场景下路径变体可能绕过白名单检查。
- **建议修复方向**：统一使用 `Path(path).resolve()` 进行路径规范化后再比较。
- **⛔ 已排除**（per `.claude/not-to-do.md`）：`shutil.which` 返回的已是规范路径，单用户场景。

### [26] `_update_global_settings` 遗漏 `lightweight_tray` 字段同步

- **模块**：配置服务
- **文件**：`app/services/config_service.py:20-79`
- **分类**：🟠 可靠性
- **描述**：`GlobalSettings` 包含 `lightweight_tray`，但 `_update_global_settings` 函数没有将该字段从 `MonitorConfigPayload` 复制到 `global_settings`。`_SystemFieldsMixin` 也没有该字段。
- **影响**：`lightweight_tray` 设置无法通过主配置 API 保存。
- **建议修复方向**：在 `_SystemFieldsMixin` 和 `MonitorConfigPayload` 中添加 `lightweight_tray` 字段。

### [27] `_build_config_payload` 遗漏 `lightweight_tray` 字段

- **模块**：配置服务
- **文件**：`app/services/runtime_config.py:90-141`
- **分类**：🟠 可靠性
- **描述**：`_build_config_payload` 构建的 `MonitorConfigPayload` 缺少 `lightweight_tray`。前端通过 `/api/config` 获取配置时看不到该字段的实际值。
- **影响**：前端设置页面加载时 `lightweight_tray` 可能总是显示默认值。
- **建议修复方向**：在 `_build_config_payload` 的 `update` 字典中包含 `lightweight_tray`。

### [28] `save_config_combined` 中密码处理绕过 `save_password_field`

- **模块**：配置服务
- **文件**：`app/services/config_service.py:105-111`
- **分类**：🟠 可靠性
- **描述**：`config_service.py` 自行做了掩码判断后直接绕过了 `save_password_field`，导致其 `raw is None` 守护逻辑变成死代码。非标准掩码输入（如 `"•abc"`）会导致密码被静默跳过。
- **影响**：非标准掩码输入可能导致密码意外不更新。
- **建议修复方向**：将密码处理完全委托给 `save_password_field`。

### [29] 轻量模式关闭时 event loop 管理竞态

- **模块**：应用入口与容器
- **文件**：`main.py:416-428`
- **分类**：🟠 可靠性
- **描述**：`_run_lightweight()` 的 `finally` 块中创建全新的 `asyncio.new_event_loop()` 来运行 `container.shutdown()`，与 Scheduler 可能使用的 event loop 完全不同。
- **影响**：轻量模式下 Scheduler 内部的异步资源可能无法正确释放。
- **建议修复方向**：将轻量模式下的 `container.shutdown()` 改为同步分离方式。

### [30] 轻量模式 Web 服务按需启动存在竞态条件

- **模块**：应用入口与容器
- **文件**：`main.py:359-378`
- **分类**：🟠 可靠性
- **描述**：`_start_web_server()` 通过 `_web_server_state["started"]` 标志防止重复启动，但该检查没有加锁。两个线程可能同时启动 Web 服务实例。
- **影响**：可能导致端口冲突或两个 Uvicorn 实例同时绑定同一端口。
- **建议修复方向**：使用 `threading.Lock` 保护标志检查和设置。

### [31] 日志中明文打印认证配置敏感信息

- **模块**：应用入口与容器
- **文件**：`app/application.py:157-165`
- **分类**：🟠 安全
- **描述**：启动时将 `username`、`auth_url` 等信息以 INFO 级别写入日志。`auth_url` 通常包含内网域名或 IP。
- **影响**：日志文件可能被非授权人员查看，暴露用户认证账号和内网认证地址。
- **建议修复方向**：将日志级别降为 DEBUG，或对 `username` 做脱敏处理。
- **⛔ 已排除**（per `.claude/not-to-do.md`）：本地单用户桌面应用，日志文件在本地，用户自己配置的值。

### [32] `delete_task` 绕过 `_safe_subdir_path` 路径验证

- **模块**：任务系统
- **文件**：`app/tasks/manager.py:383-400`
- **分类**：🟠 安全
- **描述**：`delete_task` 直接拼接路径，未使用其他 CRUD 方法都使用的 `_safe_subdir_path` 路径穿越防护。
- **影响**：当前因 `TASK_ID_PATTERN` 限制无法穿越，但未来 ID 规则放宽时将成为安全缺口。
- **建议修复方向**：统一使用 `_safe_subdir_path` 获取文件路径。
- **⛔ 已排除**（per `.claude/not-to-do.md`）：TASK_ID_PATTERN 已排除路径穿越字符，单用户桌面应用场景。

### [33] OCR Timer 生命周期竞态

- **模块**：任务系统
- **文件**：`app/tasks/step_handlers.py:640-689`
- **分类**：🟠 可靠性
- **描述**：`_get_ocr` 使用 `threading.Lock` 保护 `_ocr_instances`，但 `schedule_cleanup` 和 `_cancel_cleanup` 操作 `_cleanup_timers` 时没有加锁。
- **影响**：并发执行 OCR 步骤时模型可能被意外卸载，或 Timer 对象泄漏。
- **建议修复方向**：将 `_cleanup_timers` 的读写也纳入 `_ocr_lock` 保护范围。

### [34] `SleepHandler` 缺少负值和非法值校验

- **模块**：任务系统
- **文件**：`app/tasks/step_handlers.py:609-634`
- **分类**：🟠 可靠性
- **描述**：`int(params.get("duration", 1000))` 无 try/except 保护，负数 duration 行为不可预测。
- **影响**：变量替换产生非法值时步骤执行崩溃而非优雅降级。
- **建议修复方向**：增加 try/except 包裹和范围校验。

### [35] `_get_probe_client` 快速路径存在 TOCTOU 竞态

- **模块**：网络检测
- **文件**：`app/network/probes.py:33-39`
- **分类**：🟠 可靠性
- **描述**：无锁快速路径读取 `_probe_client` 状态，多步条件判断中间可能被其他线程打断。
- **影响**：并发调用 `set_block_proxy()` 和探测函数时可能 `AttributeError` 崩溃。
- **建议修复方向**：将快速路径读取也放在锁内，或使用 try/except 处理 `AttributeError`。

### [36] 多策略探测遇到第一个失败即短路返回

- **模块**：网络检测
- **文件**：`app/network/decision.py:193-204`
- **分类**：🟠 可靠性
- **描述**：`as_completed` 返回的第一个结果如果 `ok=False`，立即取消其余任务返回 False。即使 HTTP 或 URL 策略本可成功，只要 TCP 先完成且失败就被判定为网络不可用。
- **影响**：在 TCP 目标短暂不可达但 HTTP 正常的场景下会误报网络不可用。
- **建议修复方向**：改为"任一成功即返回 True，全部失败才返回 False"的语义。
- **⛔ 已排除**（per `.claude/not-to-do.md`）：故意设计的严格模式，宁可误报不可漏报。

### [37] `is_in_pause_period` 默认 `enabled=True`，空配置导致全天暂停

- **模块**：网络检测
- **文件**：`app/utils/time_utils.py:7-18`（被 `decision.py:51` 调用）
- **分类**：🟠 可靠性
- **描述**：`pause_config.get("enabled", True)` — 当配置为空字典时 `enabled` 默认为 `True`。用户从未配置 `pause_login` 项也会触发凌晨 0-6 点暂停。
- **影响**：用户未配置暂停功能时凌晨网络检测静默停止，可能导致漏登录。
- **建议修复方向**：将默认值改为 `False`。
- **⛔ 已排除**（per `.claude/not-to-do.md`）：故意设计，校园网凌晨 0-6 点一般不需要认证，文档字符串已说明。

### [38] `_is_auth_url_reachable` 与其他探测任务共享 3 线程池

- **模块**：网络检测
- **文件**：`app/network/decision.py:249-266`
- **分类**：🟠 性能
- **描述**：`_is_auth_url_reachable` 使用从 `probes.py` 导入的 `executor`（仅 `max_workers=3`），与网络探测共享同一个线程池。
- **影响**：登录前置检查延迟增大，极端情况下超时失败。
- **建议修复方向**：为 `_is_auth_url_reachable` 使用独立线程池，或增大共享池 `max_workers`。
- **⛔ 已排除**（per `.claude/not-to-do.md`）：同时跑满 3 worker 概率极低，都有超时保护。

### [39] 错误信息中暴露远程 URL 和异常详情

- **模块**：加密与安全工具
- **文件**：`app/utils/repo_proxy.py:74-80`
- **分类**：🟠 安全
- **描述**：HTTPException detail 字段泄露完整的请求 URL 和底层异常堆栈信息。
- **影响**：攻击者可通过精心构造的 URL 获取服务端网络拓扑、代理地址等敏感信息。
- **建议修复方向**：对用户返回通用错误消息，详细信息仅记录到 logger。
- **⛔ 已排除**（per `.claude/not-to-do.md`）：本地单用户，详细错误信息帮助排查。

### [40] PID 复用 + 宽限期逻辑可导致误判"服务运行中"

- **模块**：加密与安全工具
- **文件**：`app/utils/process.py:130-143`
- **分类**：🟠 可靠性
- **描述**：30 秒宽限期内跳过端口检查。PID 被不相关进程复用且 `create_time` 差值在 1 秒内通过校验时，不相关进程会被误判为本应用。
- **影响**：启动时检测到"服务已运行"而拒绝启动。
- **建议修复方向**：宽限期逻辑应额外校验进程名。
- **⛔ 已排除**（per `.claude/not-to-do.md`）：PID 复用 × 创建时间巧合 × 宽限期同时满足的概率几乎为零。

### [41] `run_script` 端点并发无限制

- **模块**：脚本任务执行
- **文件**：`app/api/scripts.py:71-105, 18`
- **分类**：🟠 可靠性
- **描述**：`ThreadPoolExecutor(max_workers=4)` 限制并行执行但不限制并发提交。大量并发请求导致任务在队列中堆积，每个请求持有连接直到脚本执行完成（最长 3600 秒）。
- **影响**：批量调用可耗尽服务器连接/内存。
- **建议修复方向**：在 API 层增加并发限制（信号量或速率限制中间件）。
- **⛔ 已排除**（per `.claude/not-to-do.md`）：单用户桌面应用，前端无批量执行功能。

### [42] `_build_minimal_env` 透传敏感环境变量

- **模块**：脚本任务执行
- **文件**：`app/workers/script_runner.py:246-269`
- **分类**：🟠 安全
- **描述**：最小环境变量包含 `APPDATA`、`LOCALAPPDATA`、`USERPROFILE` 等用户目录变量，暴露当前用户的完整目录结构。
- **影响**：恶意脚本可利用这些路径读取用户浏览器配置、SSH 密钥等敏感文件。
- **建议修复方向**：评估脚本是否真的需要这些变量，非必要则移除。
- **⛔ 已排除**（per `.claude/not-to-do.md`）：用户自己写的脚本已有完整系统权限，这些变量是解释器正常工作必需的。

### [43] 临时文件删除失败后无告警

- **模块**：脚本任务执行
- **文件**：`app/workers/script_runner.py:223-226`
- **分类**：🟠 安全
- **描述**：临时文件清理使用 `contextlib.suppress(OSError)` 静默忽略删除失败。脚本内容（可能含敏感信息）残留在磁盘上。
- **影响**：脚本明文内容残留在临时目录中，可被其他用户或进程读取。
- **建议修复方向**：删除失败时记录 warning 日志。
- **⛔ 已排除**（per `.claude/not-to-do.md`）：用户自己的脚本，桌面应用场景。

### [44] `run_all` 与 `next_step` 并发保护不一致

- **模块**：调试会话管理
- **文件**：`app/services/debug_service.py:223-284`
- **分类**：🟠 可靠性
- **描述**：`run_all` 内部每次循环都会释放再重新获取信号量，中间有窗口期可以让 `next_step` 插入执行，导致步骤乱序。
- **影响**：`run_all` 和 `next_step` 并发调用时可能跳过步骤或重复执行。
- **建议修复方向**：`run_all` 应在循环开始前一次性获取 `_exec_sem` 并持有到整个批量执行完成。

### [45] `start` 方法在锁内执行耗时的同步 Worker 调用

- **模块**：调试会话管理
- **文件**：`app/services/debug_service.py:96-178`
- **分类**：🟠 性能
- **描述**：`await asyncio.to_thread(lambda: get_worker().submit(...))` 在 `async with self._lock` 块内执行。锁一直持有直到 Worker 启动完成。
- **影响**：如果 Worker 启动耗时较长，其他调试操作全部排队等待。
- **建议修复方向**：将 Worker 启动调用移到锁外，失败时再加锁回滚状态。

### [46] 向导步骤 4 使用 `selectedBrowser` 与 `config.browser_channel` 状态不一致

- **模块**：前端浏览器选择 UI
- **文件**：`frontend/js/methods/ui.js:110-113`
- **分类**：🟠 可靠性
- **描述**：`fetchBrowsers` 中 `selectedBrowser` 为初始值 `'playwright'` 时会被后端 `data.current` 覆盖，绕过了"新用户选择"的预期流程。`selectedBrowser` 和 `config.browser_channel` 是两个独立变量，只在向导步骤 4 才同步。
- **影响**：向导中看到的浏览器选择与实际保存到配置的不一致。
- **建议修复方向**：`selectedBrowser` 初始值改为 `''`（空字符串），`fetchBrowsers` 中仅在设置页面时同步。

### [47] `handleBrowserClick` 对自定义浏览器未安装时交互逻辑错误

- **模块**：前端浏览器选择 UI
- **文件**：`frontend/js/methods/ui.js:144-171`
- **分类**：🟠 可靠性
- **描述**：`custom` 通道的浏览器被归入通用 `else` 分支，`installed` 为 false 时弹出 confirm 提示跳转到 Playwright 文档，而非提示输入路径。
- **影响**：用户想输入自定义浏览器路径时被告知跳转下载页面。
- **建议修复方向**：为 `custom` 通道增加独立分支，聚焦到路径输入框。

### [48] `installPlaywrightChromium` 无超时保护

- **模块**：前端浏览器选择 UI
- **文件**：`frontend/js/methods/ui.js:173-194`
- **分类**：🟠 可靠性
- **描述**：安装请求使用默认 10 秒超时，但下载约 150MB 在慢速网络下需要数十分钟。
- **影响**：慢速网络下安装必然失败（10 秒超时过短）。
- **建议修复方向**：为安装请求单独设置更长的超时（如 600000ms）。

---

## 🟡 Minor 问题

### [49] `_build_launch_args` 用户自定义参数未做安全过滤

- **模块**：浏览器自动化核心
- **文件**：`app/workers/playwright_worker.py:647-671`
- **分类**：🟡 安全
- **描述**：`browser_args` 配置项通过 `splitlines()` 拆分后直接追加到启动参数列表，无白名单或黑名单过滤。
- **影响**：管理员配置错误或配置文件被篡改时可能导致浏览器启动行为异常。
- **建议修复方向**：至少对 `--remote-debugging-port`、`--user-data-dir` 等高风险参数进行警告或拒绝。
- **⛔ 已排除**（per `.claude/not-to-do.md`）：用户自己配置的启动参数。

### [50] `STEALTH_INIT_SCRIPT` 的 `delete window.__playwright` 在新版 Playwright 中可能无效

- **模块**：浏览器自动化核心
- **文件**：`app/utils/browser.py:15-59`
- **分类**：🟡 可靠性
- **描述**：新版 Playwright 使用 `Object.defineProperty` 设置这些属性（可能为 non-configurable），`delete` 操作会静默失败。
- **影响**：反检测效果可能随 Playwright 版本升级而逐渐失效。
- **建议修复方向**：考虑使用 `playwright-stealth` 等社区维护的方案。

### [51] `browsers.py` 异常处理泄露内部错误信息

- **模块**：浏览器注册与安装
- **文件**：`app/api/browsers.py:44-46`
- **分类**：🟡 安全
- **描述**：`raise HTTPException(500, f"获取浏览器列表失败: {e}")` 将原始异常信息直接拼接到 HTTP 响应中。
- **影响**：生产环境中泄露服务器内部信息。
- **建议修复方向**：返回通用错误消息，详细信息仅记录到日志。
- **⛔ 已排除**（per `.claude/not-to-do.md`）：本地单用户，详细错误帮助排查。

### [52] `_has_chromium()` 回退路径在事件循环已运行时会崩溃

- **模块**：浏览器注册与安装
- **文件**：`app/workers/playwright_bootstrap.py:133-141`
- **分类**：🟡 可靠性
- **描述**：慢速回退路径使用 `playwright.sync_api.sync_playwright()`，在 FastAPI 应用运行期间被调用会导致 `RuntimeError: This event loop is already running`。
- **影响**：如果直接调用 `_has_chromium()` 会导致 API 500 错误。
- **建议修复方向**：移除 sync_playwright 回退路径，统一使用文件扫描检测。

### [53] `consume_profile_switch_flag` 注释声称"原子操作"但实际不是

- **模块**：调度引擎
- **文件**：`app/services/monitor_service.py:344-349`
- **分类**：🟡 可维护性
- **描述**：读取和写入之间没有锁保护，但注释声称是"原子操作"。当前单生产者单消费者在同一引擎线程中，实际安全。
- **影响**：误导性注释可能导致未来维护者误用。
- **建议修复方向**：修正注释为"由引擎线程串行调用，无需额外同步"。

### [54] `_do_network_check` 中 profile switch 后重建的 START 缺少 response_event

- **模块**：调度引擎
- **文件**：`app/services/engine.py:267-295`
- **分类**：🟡 可靠性
- **描述**：`_reload_config_internal` 失败时会继续执行 `_handle_start`，用过期的配置启动监控。
- **影响**：配置重载失败时可能用旧配置重新启动监控。
- **建议修复方向**：`_reload_config_internal` 调用失败时跳过 `_handle_start`。

### [55] `ws_drain_loop` 使用 asyncio 与引擎"零 asyncio 依赖"设计不一致

- **模块**：调度引擎
- **文件**：`app/services/engine.py:529-556`
- **分类**：🟡 可维护性
- **描述**：`drain_ws_queue` 中如果 `_ws_manager` 为 None，`await self._ws_manager.broadcast(...)` 会抛出 `AttributeError`。
- **影响**：WS 排空循环会持续抛异常（被 logger.exception 捕获不会崩溃）。
- **建议修复方向**：在入口检查 `self._ws_manager is not None`，为空时直接返回。

### [56] `__init__` 中配置加载和 pure_mode 读取重复 IO

- **模块**：调度引擎
- **文件**：`app/services/engine.py:141-144`
- **分类**：🟡 性能
- **描述**：`_reload_config_internal()` 和第 144 行 `self._profile_service.load()` 各调用一次 `load()`，存在不必要的重复 IO。
- **影响**：初始化时多一次文件读取，性能影响极小。
- **建议修复方向**：在 `_reload_config_internal` 中同时更新 `self._pure_mode`。

### [57] `get_default_shell` 非 Windows 回退路径未验证存在性

- **模块**：任务执行中心
- **文件**：`app/utils/shell_utils.py:60-71`
- **分类**：🟡 可靠性
- **描述**：`$SHELL` 可能包含已删除的 shell 路径，`/bin/bash` 在某些最小化 Linux 发行版中可能不存在。
- **影响**：错误信息"执行路径不在白名单中"而非"默认 shell 不存在"。
- **建议修复方向**：使用 `shutil.which` 验证回退路径是否真实存在。

### [58] `_execute_shell` 中 `command` 直接拼接到 shell 参数

- **模块**：任务执行中心
- **文件**：`app/services/task_executor.py:450-458`
- **分类**：🟡 安全
- **描述**：用户提供的 `command` 字符串直接传入 `[shell_path, "-c", command]`，无内容消毒。
- **影响**：桌面应用场景下可接受，但建议记录完整 command 内容便于审计。
- **建议修复方向**：在日志中记录完整的 command 内容。
- **⛔ 已排除**（per `.claude/not-to-do.md`）：用户自己写的 shell 命令，桌面应用场景。

### [59] `BoundedExecutor.shutdown` 信号量残留

- **模块**：任务执行中心
- **文件**：`app/services/task_executor.py:96-98`
- **分类**：🟡 可靠性
- **描述**：`wait=False` 时已提交但未执行的任务信号量不会被释放。
- **影响**：应用退出时影响有限。
- **建议修复方向**：当前仅影响优雅退出场景，可接受。

### [60] `build_runtime_config` 中密码掩码判断不一致

- **模块**：配置服务
- **文件**：`app/services/config_service.py:142-148`
- **分类**：🟡 可靠性
- **描述**：密码以 `"•"` 开头的用户（极罕见）密码验证会失败。
- **影响**：极低概率边界情况。
- **建议修复方向**：使用完整匹配 `"••••••••"` 而非 `startswith`。

### [61] ⭐ `_SystemFieldsMixin` 和 `GlobalSettings` 大量字段重复定义

- **模块**：配置服务
- **文件**：`app/schemas.py:162-362`
- **分类**：🟡 可维护性
- **优先级**：⭐ 高 — 已导致 `lightweight_tray` 字段不同步 bug，每次新增字段都有遗漏风险
- **描述**：两个模型定义了几乎完全相同的字段集，新增字段时需要两处同步添加。
- **影响**：容易出现字段不同步的 bug（`lightweight_tray` 已出现此问题）。
- **建议修复方向**：考虑让 `GlobalSettings` 继承共享 mixin，或使用 `model_validator` 构建 `MonitorConfigPayload`。

### [62] `ProfileService._load_unsafe` 缓存后外部修改不感知

- **模块**：配置服务
- **文件**：`app/services/profile_service.py:32-59`
- **分类**：🟡 可维护性
- **描述**：缓存存在时即使文件在磁盘上被外部修改也不会重新加载。
- **影响**：外部修改 `settings.json` 需要重启应用才能生效。
- **建议修复方向**：添加注释说明缓存策略，或添加文件修改时间检查。
- **⛔ 已排除**（per `.claude/not-to-do.md`）：正常通过 UI/API 修改配置，不会运行时手动改文件。

### [63] `delete_profile` 后 `active_profile` 切换不确定性

- **模块**：配置服务
- **文件**：`app/services/profile_service.py:149-169`
- **分类**：🟡 可维护性
- **描述**：`next(iter(data.profiles))` 总是返回字典中第一个方案。
- **影响**：用户体验不够理想，但不会导致功能错误。
- **建议修复方向**：添加注释说明设计意图。
- **⛔ 已排除**（per `.claude/not-to-do.md`）：方案数量少，用户可手动切换。

### [64] 终止进程后未验证退出，force 模式下可能遗留幽灵进程

- **模块**：应用入口与容器
- **文件**：`main.py:103-133`
- **分类**：🟡 可靠性
- **描述**：`_terminate_process` 与 `cleanup_pid` 之间没有验证进程已实际退出。
- **影响**：强制模式下可能出现两个实例同时运行。
- **建议修复方向**：在 `cleanup_pid` 之前验证进程已退出。

### [65] 静态文件目录暴露调试日志和临时文件

- **模块**：应用入口与容器
- **文件**：`app/application.py:336-338`
- **分类**：🟡 安全
- **描述**：`/debug` 和 `/temp` 目录挂载为静态文件服务，任何能访问 localhost 的进程都可以读取。
- **影响**：本机上任何程序可读取调试日志和临时文件。
- **建议修复方向**：考虑对 `/debug` 路由添加简单认证检查。
- **⛔ 已排除**（per `.claude/not-to-do.md`）：localhost 访问，单用户桌面应用。

### [66] `_extract_script_metadata` 解析 docstring 不支持标准多行格式

- **模块**：任务系统
- **文件**：`app/tasks/manager.py:136-165`
- **分类**：🟡 可维护性
- **描述**：docstring 解析只取首行 `"""` 后的内容，遇到多行 docstring 时行为不确定。
- **影响**：使用标准多行 docstring 的脚本无法正确提取任务名称。
- **建议修复方向**：使用 `ast.get_docstring()` 正确提取。

### [67] `WaitHandler` 捕获 `TimeoutError` 依赖 Playwright 版本

- **模块**：任务系统
- **文件**：`app/tasks/step_handlers.py:490-495`
- **分类**：🟡 可靠性
- **描述**：Playwright 的超时异常在某些版本中不继承自 Python 内置 `TimeoutError`。
- **影响**：超时错误消息可能不够精确，但不影响功能。
- **建议修复方向**：确认项目使用的 Playwright 版本异常继承关系。

### [68] Windows SSID 检测中纯十六进制字符 SSID 误判

- **模块**：网络检测
- **文件**：`app/network/detect.py:183-189`
- **分类**：🟡 可靠性
- **描述**：`re.fullmatch(r"[0-9A-Fa-f]+", ssid_hex)` 会将 `"cafe"` 等纯十六进制 SSID 误判为编码值。
- **影响**：某些 WiFi 名称下 SSID 显示错误。
- **建议修复方向**：增加长度启发式条件或可打印字符比例检查。

### [69] `is_network_available_http` 的 `follow_redirects` 语义不直观

- **模块**：网络检测
- **文件**：`app/network/decision.py:178-179`
- **分类**：🟡 可维护性
- **描述**：`follow_redirects=not enable_tcp` 缺乏注释解释设计意图。
- **影响**：后续修改者容易误解语义。
- **建议修复方向**：添加注释说明此设计决策。

### [70] SSL 错误字符串匹配不够健壮

- **模块**：网络检测
- **文件**：`app/network/probes.py:244`
- **分类**：🟡 可靠性
- **描述**：`"CERTIFICATE_VERIFY_FAILED" in str(exc)` 可能遗漏 httpx 包装后的异常。
- **影响**：校园网 HTTPS 劫持场景下 SSL 错误被当作一般异常。
- **建议修复方向**：改为递归检查异常链。

### [71] `cancel_futures` 参数要求 Python 3.9+

- **模块**：网络检测
- **文件**：`app/network/probes.py:19`
- **分类**：🟡 兼容性
- **描述**：`ThreadPoolExecutor.shutdown(cancel_futures=True)` 是 Python 3.9 新增参数。
- **影响**：Python 3.8 环境下进程退出时崩溃。
- **建议修复方向**：确认项目最低 Python 版本要求。
- **⛔ 已排除**（per `.claude/not-to-do.md`）：项目最低要求 Python 3.10，默认 3.12。

### [72] `save_password_field` 掩码判断仅检查前缀 "•"

- **模块**：加密与安全工具
- **文件**：`app/utils/crypto.py:218`
- **分类**：🟡 可靠性
- **描述**：密码恰好以 "•" 开头会被错误地当作掩码处理。
- **影响**：极低概率边界情况。
- **建议修复方向**：改为检查是否完全由 "•" 组成。

### [73] `is_local_port_in_use` 不处理 IPv6-only 环境

- **模块**：加密与安全工具
- **文件**：`app/utils/process.py:148-152`
- **分类**：🟡 兼容性
- **描述**：仅检测 IPv4 回环 `127.0.0.1`，忽略 IPv6 环境。
- **影响**：纯 IPv6 环境下误判端口未被占用。
- **建议修复方向**：增加 IPv6 回环检测。
- **⛔ 已排除**（per `.claude/not-to-do.md`）：纯 IPv6 环境几乎不存在，校园网必有 IPv4。

### [74] `_load_script_content` 缓存语义导致空内容无法刷新

- **模块**：脚本任务执行
- **文件**：`app/workers/script_runner.py:75-94`
- **分类**：🟡 可靠性
- **描述**：`_script_content is not None` 做缓存判断，空字符串 `""` 也非 None，后续调用仍返回空而非重新读取。
- **影响**：若复用 ScriptRunner 实例会执行过期内容。
- **建议修复方向**：使用 `_sentinel = object()` 区分"未加载"和"加载为空"。

### [75] `close` 方法未取消超时定时器

- **模块**：调试会话管理
- **文件**：`app/services/debug_service.py:308-314`
- **分类**：🟡 可靠性
- **描述**：`close()` 方法没有先调用 `_cancel_debug_timer()`，Timer 任务可能泄漏。
- **影响**：应用关闭时可能有未完成的 asyncio Task 警告。
- **建议修复方向**：在 `close()` 方法开头添加 `await self._cancel_debug_timer()`。

### [76] 浏览器卡片内联样式重复

- **模块**：前端浏览器选择 UI
- **文件**：`frontend/partials/wizard.html`, `frontend/partials/pages/settings/settings-browser.html`
- **分类**：🟡 可维护性
- **描述**：Firefox 兼容性警告和自定义浏览器提示使用内联 `style` 属性，样式重复定义在两个文件中。
- **影响**：维护成本高。
- **建议修复方向**：将内联样式迁移到 CSS 类中。

### [77] `fetchBrowsers` 失败时无用户反馈

- **模块**：前端浏览器选择 UI
- **文件**：`frontend/js/methods/ui.js:100-118`
- **分类**：🟡 可靠性
- **描述**：catch 块只执行 `console.error`，用户看到永久的"正在检测浏览器..."加载状态。
- **影响**：后端 API 不可达时用户只会看到空白区域。
- **建议修复方向**：在 catch 块中添加 toast 提示。

### [78] `browser_extra_headers_json` 未做 JSON 格式校验

- **模块**：前端浏览器选择 UI
- **文件**：`frontend/partials/pages/settings/settings-browser.html:290-296`
- **分类**：🟡 可靠性
- **描述**：保存前未校验该字段是否为合法 JSON。
- **影响**：非法 JSON 字符串会导致浏览器启动失败。
- **建议修复方向**：在 `saveConfig` 中增加 `JSON.parse` 校验。

---

## 审查覆盖范围

| Review Unit | 模块 | 焦点 | 优先级 | 文件数 |
|-------------|------|------|--------|--------|
| PlaywrightWorker 浏览器自动化核心 | app/workers | Actor 模型浏览器生命周期、多浏览器 channel 启动 | P0 | 2 |
| 浏览器注册与安装 | app/utils, app/api, app/workers | 浏览器检测注册表、SVG 图标、Playwright 下载引导 | P0 | 5 |
| ScheduleEngine 调度引擎 | app/services | Actor 模型命令派发、网络状态机、WS 广播 | P0 | 2 |
| TaskExecutor 任务执行中心 | app/services, app/utils | 双线程池架构、登录去重、Shell 安全策略 | P1 | 3 |
| 配置服务与运行时配置 | app/services, app/schemas | 配置读写、Profile 管理、字段合并 | P1 | 4 |
| Playwright 启动引导 | app/workers | 按需下载、多镜像源回退 | P1 | 1 |
| 应用入口与容器 | main, app/application, app/container | 进程生命周期、服务容器、轻量模式 | P1 | 5 |
| 前端浏览器选择 UI | frontend | 浏览器选择交互、fetchBrowsers、Firefox 提示 | P1 | 6 |
| 任务系统 | app/tasks | 任务模型、步骤处理器、变量解析 | P2 | 6 |
| 网络检测 | app/network | TCP/HTTP/URL 探测、网关检测、暂停判断 | P2 | 3 |
| 加密与安全工具 | app/utils | Fernet 加密、SSRF 防护、原子写入、PID 管理 | P2 | 4 |
| 脚本任务执行 | app/workers, app/services, app/api | 脚本子进程执行、解释器检测 | P2 | 3 |
| 调试会话管理 | app/services, app/api | 调试会话状态管理、代数计数器、信号量控制 | P2 | 3 |

## 附注

- 本报告仅列出发现，未执行任何修复
- 建议按 Critical → Major → Minor 顺序处理
- 部分问题可能需要跨模块协同修复
- 日志系统（app/utils/logging.py 及相关）正在优化中，已跳过审查

### 已排除项（per `.claude/not-to-do.md`）

以下发现属于设计决策或误判，已从报告中排除：

| 原编号 | 原标题 | 排除原因 |
|--------|--------|----------|
| — | 明文密码无加密警告 | "cryptography 缺失时回退为明文存储，已有 warning" |
| — | WebSocket 缺少 Origin 校验 | "仅监听 127.0.0.1，不要加 API 鉴权/CORS 限制" |
| — | repo_proxy SSRF 防护不完整 | "不要给 repo_proxy 加 SSRF 防护" |
| — | 密钥文件权限 TOCTOU 竞态 | "不要把密钥移到 keyring"，单用户场景无实际风险 |
| — | save_script 加 Pydantic 校验 | "不要给 save_task 加 Pydantic 校验"，任务 JSON 结构灵活 |
| — | os._exit 跳过 finally 清理 | "信号处理器/回退路径中无法优雅关闭，调用前已做清理" |
| [8] | 脚本执行白名单自动追加 + binary_path 未校验 | 白名单是已知解释器发现机制而非安全防线；单用户已有完整系统权限；优化方向为前端保存时提示 |
