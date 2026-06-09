# 代码审查报告

**日期**：2026-06-09
**范围**：全项目（后端 + 前端）
**版本**：v4.0.2
**方法**：逐模块深度审查（方案 A）

---

## 审查范围

| 阶段 | 模块 | 文件 |
|------|------|------|
| 1 | 任务引擎 | `app/tasks/` — executor, step_handlers, variable_resolver, validator, models, manager |
| 2 | 网络检测 | `app/network/` + `app/core/monitor_core.py` — probes, decision, detect, diagnostics, monitor_core |
| 3 | Worker 线程 | `app/workers/` — playwright_worker, script_runner |
| 4 | 服务层 | `app/services/` — monitor, profile, config, task, scheduler, debug, debug_session, autostart, uninstall, login_history |
| 5 | API 路由 | `app/api/` — 13 个路由文件 + deps, schemas, application |
| 6 | 工具层 | `app/utils/` — 全部工具文件 |
| 7 | 前端 | `frontend/js/`, `frontend/styles/`, `frontend/partials/` |

---

## 问题统计

| 严重程度 | 数量 | 说明 |
|---------|------|------|
| 🔴 严重 | 6 | 可能导致崩溃、数据丢失、内存耗尽、安全漏洞 |
| 🟡 中等 | 22 | 可能导致非预期行为、性能下降、UI 异常 |
| 🟢 低优先级 | 20+ | 代码质量、可维护性、风格一致性 |

---

## 🔴 严重问题

### 1. upload_background 读取整个文件到内存后才检查大小

- **文件**：`app/api/tools.py:63-64`
- **类型**：内存安全
- **描述**：`upload_background` 使用 `await file.read()` 将整个上传文件读入内存，然后才检查 `len(content) > MAX_FILE_SIZE`。如果用户上传一个超大文件（如数 GB 的视频），会在检查大小前将整个文件内容读入内存，可能导致内存耗尽。
- **建议修复**：先通过 `Content-Length` 头或分块读取累计大小，超过限制立即拒绝，避免一次性 `read()`。可使用 `UploadFile.size` 属性（如果有）或逐步读取累积。

### 2. fetch_background_url 全量加载远程响应到内存

- **文件**：`app/api/tools.py:109-111`
- **类型**：内存安全
- **描述**：`fetch_background_url` 使用 `resp = await client.get(url)` 后 `resp.content` 已经将全部响应内容加载到内存，然后才检查大小。如果远程 URL 返回一个巨大文件，同样会导致内存耗尽。
- **建议修复**：使用 httpx 的流式下载（`stream=True`），分块读取并累计大小，超过 `MAX_FILE_SIZE` 立即断开连接并报错。

### 3. repo 代理 SSRF 风险

- **文件**：`app/api/repo.py:15-21, 25-31`
- **类型**：安全
- **描述**：`repo_fetch_index` 和 `repo_fetch_task` 直接将用户传入的 `url` 参数转发给 `repo_get` 进行 HTTP 请求，没有任何 URL 校验。攻击者可以传入内网地址（如 `http://127.0.0.1:50721/api/config`）或 `file:///etc/passwd` 进行 SSRF 攻击，获取本地配置/敏感数据。
- **建议修复**：对传入的 url 进行白名单校验或黑名单过滤，至少拒绝 `file://`、`ftp://` 等非 `http(s)` 协议，并可考虑拒绝内网地址段。

### 4. executor.py 中 `or` 操作符导致 timeout=0 被忽略

- **文件**：`app/tasks/executor.py:40`
- **类型**：正确性
- **描述**：`default_timeout or self.DEFAULT_STEP_TIMEOUT` 使用 `or` 判断，当用户显式传入 `default_timeout=0` 时会被替换为默认值 10000。`navigation_timeout`（第 41 行）同理。`0` 是一个合法的值（表示"无超时"），但被 `or` 当作 falsy 值忽略了。
- **建议修复**：改为 `default_timeout if default_timeout is not None else self.DEFAULT_STEP_TIMEOUT`。

### 5. manual_login 使用 asyncio.to_thread 执行 Playwright 操作

- **文件**：`app/api/monitor.py:55`
- **类型**：正确性
- **描述**：`manual_login` 使用 `asyncio.to_thread(svc.run_manual_login)` 将同步阻塞方法放到线程池执行。但 `run_manual_login` 内部会调用 Playwright 浏览器操作，这些操作依赖 Worker 线程的事件循环。如果 `to_thread` 的线程与 Worker 线程不是同一个，可能导致事件循环冲突或浏览器状态不一致。
- **建议修复**：确认 `run_manual_login` 内部是否通过 Worker 的 `submit` 队列来执行浏览器操作。如果是，则 `to_thread` 是安全的；如果不是，需要改为异步调用或确保在正确的事件循环中执行。

### 6. atomic_write 类型注解与实际调用不一致

- **文件**：`app/utils/file_helpers.py:12-18`
- **类型**：正确性
- **描述**：`atomic_write` 的 `path` 参数类型注解为 `str`，但调用方（如 `backup.py:103`）传入的是 `Path` 对象。`os.path.dirname(Path对象)` 虽然能工作，但 `tempfile.mkstemp(dir=parent)` 在 `parent` 为 `Path` 对象时行为依赖 Python 版本。更关键的是，`atomic_write` 接受 `str` 但内部没有统一转换为 `str`，如果传入 `Path` 对象在某些边缘情况下可能出现类型不一致。
- **建议修复**：将 `path` 参数类型改为 `str | Path`，内部统一转换为 `str`：`path = str(path)`。

---

## 🟡 中等问题

### 正确性（14 个）

#### 7. step_handlers.py — description 为 None 时 .lower() 崩溃

- **文件**：`app/tasks/step_handlers.py:234`
- **描述**：`step.description.lower()` — 如果 `step.description` 为 `None`，此处会抛出 `AttributeError`。查看 `StepConfig` 的定义，`description` 默认值为 `""`（空字符串），所以正常创建的 StepConfig 不会为 None。但 `from_dict` 中如果 JSON 数据包含 `"description": null`，dataclass 会将其设为 None，因为 `from_dict` 只做了 `if k in cls.__dataclass_fields__` 的过滤，没有对 None 值做特殊处理。
- **建议修复**：改为 `(step.description or "").lower()`，或在 `StepConfig.from_dict` 中对 description 做空值兜底。

#### 8. validator.py — 空步骤列表被误判为缺失

- **文件**：`app/tasks/validator.py:33-35`
- **描述**：`config.get("steps")` 返回 falsy 值时（如空列表 `[]`），会被 `not config.get("steps")` 判定为 True，触发"必须包含 steps 字段"的错误。但空步骤列表是合法的（任务可以没有步骤）。这会导致空任务无法保存。
- **建议修复**：改为 `if "steps" not in config:`，区分"字段不存在"和"字段为空列表"。

#### 9. validator.py — 步骤非 dict 类型时未处理

- **文件**：`app/tasks/validator.py:52`
- **描述**：`set(step.keys())` — 如果 `step` 不是 dict（如用户传入了 list 或 string），此处会抛出 `AttributeError`。验证器应该处理输入类型不合法的情况。
- **建议修复**：在 `_validate_step` 开头添加 `if not isinstance(step, dict): return [f"{prefix} 必须是对象"]`。

#### 10. models.py — from_dict 中步骤元素非 dict 时未处理

- **文件**：`app/tasks/models.py:189`
- **描述**：`TaskConfig.from_dict` 中 `steps=[StepConfig.from_dict(s) for s in data.get("steps", [])]`，如果 `steps` 中某个元素不是 dict（如 `None` 或字符串），`StepConfig.from_dict` 会抛出异常。验证器应该在 `from_dict` 之前捕获这种情况，但如果绕过验证器直接调用 `from_dict`，就会出错。
- **建议修复**：在 `StepConfig.from_dict` 开头添加类型检查，或在列表推导中添加异常处理。

#### 11. variable_resolver.py — None 值变成 "null" 字符串

- **文件**：`app/tasks/variable_resolver.py:62-63`
- **描述**：当 `runtime_vars` 中的值为 `None` 时，使用 `json.dumps(None)` 编码返回 `"null"`。如果嵌入到模板 `"value: {{RESULT}}"` 中会变成 `"value: null"`，这可能不是用户期望的空值行为。
- **建议修复**：对 `None` 特殊处理，返回空字符串 `""`。

#### 12. monitor.py — wait_for_login_recovery 在 Event 未 set 时阻塞 300s

- **文件**：`app/services/monitor.py:461-478`
- **描述**：`wait_for_login_recovery` 调用 `core._login_recovery_in_progress.wait(timeout=timeout)`。如果调用时登录恢复没有在进行中（Event 未 set），`wait()` 会阻塞 300 秒等待 Event 被 set。虽然调用方 `scheduler.py:277-279` 先检查了 `login_recovery_in_progress`，但存在 TOCTOU 竞态窗口：检查时恢复在进行，调用 `wait` 时恢复已结束（Event 已 clear），此时 `wait` 会阻塞 300s。
- **建议修复**：在 `wait_for_login_recovery` 中先检查 `if not core._login_recovery_in_progress.is_set(): return`，或改用 `Condition` / 轮询方式。

#### 13. scheduler.py — 同一分钟内可能重复触发同一定时任务

- **文件**：`app/services/scheduler.py:467-487`
- **描述**：`_scheduler_loop` 每 30 秒调用一次 `_check_and_execute`。如果任务在同一分钟内被检查到并开始执行（`asyncio.create_task`），30 秒后的下一次检查中，`now.minute` 仍然相同，会再次匹配并创建新的执行任务。虽然 `execute_task` 本身是幂等的（只是执行一次登录），但会导致同一分钟内执行两次。
- **建议修复**：在触发后记录 `last_triggered_minute`，跳过已触发的分钟：`if current_minute == last_triggered_minute: continue`。

#### 14. debug.py — stop() 清理公共 temp 目录可能影响其他服务

- **文件**：`app/services/debug.py:287-293`
- **描述**：`stop()` 方法在停止调试会话后清理 `self._temp_dir` 中的所有文件。但 `_temp_dir` 指向 `project_root / "temp"`，这是项目的公共临时目录，不仅存放调试截图，还可能存放其他临时文件（如 OCR 步骤的临时文件等）。如果其他服务正在使用 temp 目录中的文件，`item.unlink(missing_ok=True)` 可能导致其他服务出现文件找不到的错误。
- **建议修复**：只删除调试相关的截图文件（如通过文件名前缀匹配），或使用独立的调试临时子目录。

#### 15. playwright_worker.py — submit() 超时后命令仍在队列中执行

- **文件**：`app/workers/playwright_worker.py:252-258`
- **描述**：`submit()` 在 `response_event.wait(timeout)` 超时后返回 `WorkerResponse(success=False, error="命令执行超时或无响应")`，但此时 `WorkerCommand` 仍在 `_cmd_queue` 中。当 Worker 后续取出该命令执行时，会设置 `cmd.response_data` 并 `cmd.response_event.set()`，但已经没有消费者等待了。如果命令执行过程中有副作用（如 `_handle_login` 会清除 `_login_in_progress` 标志），超时返回的调用方可能会认为登录失败并继续提交新命令，而旧命令仍在执行中，造成重复操作。
- **建议修复**：在命令中添加 `cancelled` 标志，`_dispatch()` 在执行前检查此标志。对于单用户本地运行场景，实际影响较小。

#### 16. scheduled_tasks.py — schedule.hour/minute 缺少范围校验

- **文件**：`app/api/scheduled_tasks.py:63-65, 114-117`
- **描述**：创建和更新定时任务时，`schedule.hour` 和 `schedule.minute` 的验证仅检查类型是否为 `int`，但没有校验值的范围（hour 0-23, minute 0-59）。用户可以传入 `hour=99, minute=-1` 等无效值。
- **建议修复**：添加范围校验：`0 <= hour <= 23, 0 <= minute <= 59`。

#### 17. scheduled_tasks.py — timeout 字段 int() 转换未捕获异常

- **文件**：`app/api/scheduled_tasks.py:81, 134`
- **描述**：`timeout` 字段使用 `int(payload.get("timeout", 60))`，如果 `payload["timeout"]` 是字符串如 `"abc"`，`int()` 会抛出 `ValueError` 导致 500 错误，而不是返回友好的错误消息。
- **建议修复**：使用 `try-except` 包裹 `int()` 转换，失败时返回 400 错误。

#### 18. backup.py — 备份文件名精度到秒，同秒创建会覆盖

- **文件**：`app/api/backup.py:26`
- **描述**：`list_backups` 函数中，`sorted(BACKUP_DIR.glob("settings_*.json"), reverse=True)` 按文件名排序。如果两个备份在同一秒内创建（文件名相同），后者会覆盖前者。虽然概率低，但 `datetime` 精度只到秒。
- **建议修复**：使用微秒精度的文件名（已在 `restore_backup` 的自动备份中使用 `%f`），或者在文件名中加入递增序号。

#### 19. process.py — 跨模块导入私有函数

- **文件**：`app/utils/process.py:126`
- **描述**：`is_service_running` 内部导入 `app.application._resolve_port`，这是一个下划线开头的私有函数。跨模块导入私有函数违反封装原则，如果 `_resolve_port` 的实现变更，`process.py` 会静默失败。
- **建议修复**：将 `_resolve_port` 提取到公共模块（如 `config_helpers.py` 或 `constants.py`）中。

#### 20. monitor.py — _handle_stop 中 join + wait 双重等待逻辑冗余

- **文件**：`app/services/monitor.py:234-248`
- **描述**：`thread.join(timeout=8)` 已经等待线程结束，如果 `join` 超时后线程仍存活，再调用 `_thread_done.wait(timeout=10)` 等待 10s。但实际上 `join` 已经等了 8s，`_thread_done.wait` 又等 10s，总共可能等 18s。如果 `join` 在 8s 内返回（线程已死但 Event 未设置），`_thread_done.wait` 会再等 10s 然后超时。
- **建议修复**：简化为先 `stop_monitoring()`，然后只用 `_thread_done.wait(timeout)` 等待，移除多余的 `join`。或者只保留 `join`。

### 性能（3 个）

#### 21. logfiles.py — 大日志文件逐行全读入内存再截取

- **文件**：`app/api/logfiles.py:136`
- **描述**：读取日志文件时使用 `deque(f, maxlen=max(limit * 2, 5000))`，对于大型日志文件（数百 MB），会将最多 5000-20000 行全部读入内存然后截取。虽然 `deque` 会自动丢弃旧数据，但文件仍然被逐行完整读取。
- **建议修复**：对于大文件，先获取文件大小，如果超过阈值（如 50MB），使用 `mmap` 或只读取文件末尾部分（`seek` 到文件末尾附近）。

#### 22. repo_proxy.py — repo_get 每次创建新 httpx.Client

- **文件**：`app/utils/repo_proxy.py:35`
- **描述**：`repo_get` 每次调用都创建一个新的 `httpx.Client` 实例。如果频繁调用（如批量下载任务），会重复创建/销毁连接池，浪费资源。
- **建议修复**：使用模块级的 `httpx.Client` 实例（带连接池），或使用 `httpx.AsyncClient`（如果是异步上下文）。注意需要在应用关闭时正确清理。

#### 23. login_history.py — list_recent 读取整个文件

- **文件**：`app/services/login_history.py:119-143`
- **描述**：`list_recent()` 读取整个 JSONL 文件的所有行到内存，然后取最后 N 条。如果登录历史文件很大（虽然有 30 天清理，但高频登录场景下可能积累大量记录），会导致不必要的内存和 I/O 开销。
- **建议修复**：使用文件末尾反向读取（如从文件末尾向前扫描 N 条记录），或维护一个内存中的最近记录缓存。对于本项目的使用频率，当前实现可接受。

### 前端（5 个）

#### 24. app.js — applyAppearanceEarly 中 zoom 在 Vue 挂载前静默失效

- **文件**：`frontend/app.js:28`
- **类型**：正确性
- **描述**：`applyAppearanceEarly()` 中对 `.content-wrapper` 的 `querySelector` 在 Vue 挂载前执行，此时 `#app` 的 `display` 为 `none`，`.content-wrapper` 可能尚未被模板加载。虽然有 `?.` 可选链不会崩溃，但 zoom 设置在页面初始化时会静默失效。
- **建议修复**：将 zoom 设置延迟到 `mounted()` 中 `applyAppearance()` 执行时处理，或在 `applyAppearanceEarly` 中移除该段（`applyAppearance` 中已有相同逻辑）。

#### 25. methods/ui.js — removeCustomVar 使用 delete 删除响应式属性

- **文件**：`frontend/js/methods/ui.js:122-125`
- **类型**：正确性
- **描述**：`removeCustomVar` 使用 `delete` 操作符删除 Vue 响应式对象的属性。Vue 3 的 Proxy 可以检测到 `delete`，但如果 `custom_variables` 是通过 `Object.assign` 或展开运算符从后端数据 shallow copy 而来的，`delete` 后 Vue 可能不会触发视图更新。此处的 `updateCustomVarKey` 使用了整体替换策略（`newVars`），而 `removeCustomVar` 直接 `delete`，两者策略不一致。
- **建议修复**：`removeCustomVar` 也使用整体替换策略，保持一致性。

#### 26. methods/status.js — 一次获取 250 条日志全量渲染

- **文件**：`frontend/js/methods/status.js:18-22`
- **类型**：性能
- **描述**：`fetchLogs` 一次获取 250 条日志并全部存入 `this.logs`。如果日志消息较长，250 条日志的 DOM 渲染可能造成页面卡顿。`filteredLogs` computed 在每次日志筛选时都会遍历整个数组。
- **建议修复**：考虑对日志列表使用虚拟滚动（virtual scroll），或限制初始渲染数量（如只渲染最近 50 条，滚动时加载更多）。

#### 27. app-options.js — filteredLogs 三次 filter 遍历

- **文件**：`frontend/js/app-options.js:98-110`
- **类型**：性能
- **描述**：`filteredLogs` computed 每次访问都会执行三次 filter 操作（level、source、search 各一次），且每次都创建新数组。在日志量大时（接近 `LOG_MAX_ENTRIES=100`），频繁访问此 computed（如模板中 `v-for` 渲染）会重复计算。
- **建议修复**：合并三个 filter 条件到一次遍历中。

#### 28. styles/components.css — 通知下拉菜单 position:fixed 脱离按钮

- **文件**：`frontend/styles/components.css:816-831` + `responsive.css:84-86`
- **类型**：UI
- **描述**：`.notification-dropdown` 使用 `position:fixed` 且 `top:68px, right:32px`。在移动端（768px 以下）`top` 改为 `60px, right` 改为 `16px`，但没有考虑页面滚动位置的变化。如果用户滚动页面后点击通知按钮，下拉菜单会出现在固定位置而非按钮附近。
- **建议修复**：将 `notification-dropdown` 改为 `position:absolute` 相对于 `.notification-wrapper` 定位，或使用 JS 动态计算位置。

---

## 🟢 低优先级问题

### 任务引擎

| 文件 | 问题 |
|------|------|
| `executor.py:414` | `_handle_success` 方法中的 `page` 参数未使用，建议改为 `_page` |
| `step_handlers.py:627-683` | `OcrHandler` 的 `_cleanup_timers.pop` 不在锁保护内，CPython 下安全但不够严谨 |
| `step_handlers.py:507-523` | `WaitUrlHandler` 手写轮询循环，可用 `page.wait_for_url()` 替代 |
| `variable_resolver.py:95-113` | `resolve_for_js` 对未解析变量替换为空字符串，用户可能不知道变量未被解析 |
| `validator.py:21-43` | 缺少 `variables`、`on_success`、`on_failure` 等字段的类型验证 |
| `models.py:84-104` | `StepConfig._DEFAULTS` 中 `"extra": {}` 是共享的空字典，修改会影响所有实例 |
| `models.py:222-230` | `ScriptTaskInfo` 的 `script_path` 默认值是空 `Path()`，语义不明确 |
| `manager.py:92-94` | 所有搜索目录未找到文件时返回默认路径，可能让调用方困惑 |
| `manager.py:114` | 元数据读取失败时静默返回空字典，缺少日志 |
| `manager.py:203-221` | `list_tasks` 每次调用都读取所有 JSON 文件，无缓存 |
| `manager.py:194-201` | `_sort_by_order` 每次调用都读取 `.order.json`，重复 I/O |

### 网络检测

| 文件 | 问题 |
|------|------|
| `probes.py:25-26` | 全局 `ThreadPoolExecutor` 的 `atexit` 注册在程序退出时可能有资源泄漏警告（风险低） |
| `decision.py:167-169` | `follow_redirects=not enable_tcp` 的隐含假设不够直观，只启用 HTTP 检测时可能导致门户认证场景漏检 |
| `decision.py:54-55` | portal 检测启用逻辑基于数据存在性而非配置开关，与 TCP/HTTP 不一致 |
| `decision.py:232-260` | `_is_auth_url_reachable` 的 `extra_targets` 全部失败后不 fallback 到 `auth_url` |
| `monitor_core.py:401-405` | 通知发送硬编码为第 2 次失败，与动态的 `max_retries` 不匹配 |
| `decision.py:250-251` | `as_completed` 的 `timeout=4` 是总超时，与单个 future 的 3s 超时不匹配 |
| `probes.py:348-353` | SSL 异常检测双重判断，缺少注释说明原因 |
| `detect.py:158-162` | 重复的 `CREATE_NO_WINDOW_FLAG` 获取，应复用已导入的常量 |
| `decision.py:150-151` | 函数内重复导入 `as_completed` |
| `monitor_core.py:305-321` | `_login_recovery_loop` 仅做标志位管理，与 `_login_recovery_inner` 容易混淆 |
| `monitor_core.py:473-491` | `RecoveryResult.PAUSED` 缺少显式处理分支 |

### Worker 线程和服务层

| 文件 | 问题 |
|------|------|
| `playwright_worker.py:104-112` | `_wake_event` 跨线程可见性问题，最坏后果仅是 0.5s 延迟 |
| `playwright_worker.py:857-871` | `_handle_low_resource_request` 异常处理粒度过粗，可能隐藏编程错误 |
| `script_runner.py:150-162` | `_content_temp_file` 临时文件在异常路径可能泄漏（概率极低） |
| `monitor.py:154-174` | `_queue_consumer` 中非 LOGIN/STOP 命令的 `response_event` 未统一 set（当前恰好安全，但缺乏防御性编程） |
| `monitor.py:125-126` | `StatusSnapshot` 读写无内存屏障，CPython 下安全，free-threaded Python 下需加锁 |
| `profile.py:98-101` | `load()` 每次深拷贝，只读场景下不必要（数据量小，可接受） |
| `scheduler.py:174-175` | 重复导入 `atomic_write` |
| `debug.py:218-277` | `run_all` 中锁嵌套顺序与其他方法不一致（asyncio 单线程下不会死锁） |
| `container.py:84-85` | `has_enabled_tasks` 在 startup 中只检查一次，运行时新增任务不会自动启动调度器 |
| `autostart.py:310-313` | `_has_cjk_chars` 正则范围不完整，未覆盖 CJK 扩展区 B-G |
| `uninstall.py:118-125` | `_remove_user_data` 直接删除 `AUTH_DATA_DIR`，包含加密密钥文件（设计如此） |

### API 路由和工具层

| 文件 | 问题 |
|------|------|
| `tools.py:77-88` | `fetch_background_url` 的 URL 无协议白名单校验（当前 httpx 仅支持 http/https） |
| `crypto.py:68` | `atomic_write` 传入 `str(_KEY_FILE)` 与类型注解一致，但类型不统一 |
| `logging.py:150` | `DashboardSink.write` 中 `broadcast_queue.append()` 未加锁，CPython 下安全 |
| `system.py:41` | `check_update` 使用 `global` 缓存，多 worker 部署下无法共享 |
| `system.py:162` | `uninstall_perform` 接受裸 `dict` 未使用 Pydantic 模型 |
| `debug.py:19-21` | `debug_start` 直接传入 `Request` 而非 `Depends` 注入，风格不一致 |
| `notify.py:73-74` | 冗余的 `hasattr(subprocess, "CREATE_NO_WINDOW")` 判断 |
| `process.py:69-71` | 同上，应复用 `platform_utils.CREATE_NO_WINDOW_FLAG` |
| `config.py:45` | `str(payload.check_interval_seconds)` 不必要的类型转换 |
| `shell_policy.py:65` | 审计日志混用 `%s` 和 `{}` 占位符风格 |
| `config_helpers.py:14-65` | `PROFILE_FIELDS` 列表与 `schemas.py` 存在隐式耦合 |
| `scheduled_tasks.py:18-20` | `_get_scheduler` 是多余的包装函数 |
| `logfiles.py:23-24` | `_LOG_LINE_PATTERN` 与 `DateRotatingSink._file_format` 格式定义分离 |

### 前端

| 文件 | 问题 |
|------|------|
| `methods/scripts.js:42-43` | `base === 'py'` 是死代码，永远不会匹配 |
| `tasks/editor.js:134-135` | 副本命名逻辑不一致：第一个叫"副本"而非"副本1" |
| `methods/lifecycle.js:246-268` | `_wsPingTimer` 的清理逻辑依赖 `timers` 数组，脆弱但不会导致功能异常 |
| `methods/ui.js:162-173` | `_appendLogs` 使用 spread + slice 创建新数组，可用 `splice` 替代 |
| `styles/responsive.css:48-78` | 移动端 `nav-more-arrow` 被隐藏，用户可能不清楚点击后会展开子菜单 |
| `styles/components.css:564-612` | `.field-help` tooltip 可能超出视口，依赖手动添加 `--flip` 类 |
| `partials/pages/settings.html:15-23` | 非激活标签页的子页面仍通过 `data-include` 加载到 DOM |
| `methods/drag.js:4-6` | `_dragState` 等全局模块变量共享状态，隐式依赖不够清晰 |
| `methods/ui.js:136-139` | `updateCustomVarKey` 直接操作 DOM，与 Vue 响应式理念不符 |
| `methods/formatters.js:46-48` | `getLogClass` 使用中文关键词匹配成功消息，脆弱 |
| `app-options.js:36-247` | `appOptions` 是"上帝对象"入口，所有 Vue 实例的方法和数据都通过展开合并 |
| `styles/settings.css:712-739` | `.btn-sm` 和 `.btn-secondary` 在 settings.css 中被重新定义，覆盖了 components.css |

---

## 修复优先级建议

### 第一批（数据安全 / 内存安全）
1. `app/api/tools.py` — 大文件上传内存问题（#1, #2）
2. `app/api/repo.py` — SSRF 风险（#3）

### 第二批（功能正确性）
3. `app/tasks/executor.py` — `or` 判断问题（#4）
4. `app/tasks/step_handlers.py` — description 为 None 崩溃（#7）
5. `app/tasks/validator.py` — 空步骤列表误判（#8）
6. `app/tasks/validator.py` — 非 dict 输入未处理（#9）
7. `app/tasks/models.py` — 非 dict 步骤元素未处理（#10）
8. `app/tasks/variable_resolver.py` — None 值变成 "null"（#11）
9. `app/api/scheduled_tasks.py` — schedule 范围校验（#16, #17）

### 第三批（可靠性）
10. `app/services/monitor.py` — wait_for_login_recovery 竞态（#12）
11. `app/services/scheduler.py` — 重复触发定时任务（#13）
12. `app/services/debug.py` — temp 目录清理范围过大（#14）
13. `app/workers/playwright_worker.py` — submit 超时后命令仍在队列（#15）

### 第四批（前端体验）
14. `frontend/app.js` — applyAppearanceEarly zoom 失效（#24）
15. `frontend/js/methods/ui.js` — removeCustomVar 策略不一致（#25）
16. `frontend/js/app-options.js` — filteredLogs 三次 filter（#27）
17. `frontend/styles/components.css` — 通知下拉菜单定位（#28）

### 第五批（性能优化）
18. `app/api/logfiles.py` — 大日志文件读取（#21）
19. `app/utils/repo_proxy.py` — httpx.Client 重复创建（#22）
20. `app/services/login_history.py` — list_recent 全量读取（#23）
