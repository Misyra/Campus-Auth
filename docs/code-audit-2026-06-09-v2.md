# 代码审查报告 v2（深化重审）

**日期**：2026-06-09
**范围**：全项目（后端 + 前端）
**版本**：v4.0.2
**方法**：方案 A — 深化原有 7 模块划分，按五道关检查（入口边界、异常路径、调用链完整性、状态机一致性、已有修复复查）

---

## 审查范围

| 阶段 | 模块 | 文件 | 深度 |
|------|------|------|------|
| 1 | 任务引擎 | `app/tasks/` — executor, step_handlers, variable_resolver, validator, models, manager | 逐函数追踪 |
| 2 | 网络检测 | `app/network/` + `app/core/monitor_core.py` — probes, decision, detect, diagnostics, monitor_core | 逐函数追踪 |
| 3 | Worker 线程 | `app/workers/` — playwright_worker, script_runner | 逐函数追踪 |
| 4 | 服务层 | `app/services/` — monitor, scheduler, debug, config, profile, login_history, autostart | 核心路径追踪 |
| 5 | API 路由 + 核心 | `app/api/`、`app/application.py`、`app/deps.py` | 入口点扫描 |
| 6 | 工具层 | `app/utils/` — crypto, file_helpers, login, browser, env, config | 核心文件追踪 |
| 7 | 前端 | `frontend/js/`, `frontend/styles/`, `frontend/partials/` | 关键组件扫描 |

---

## 问题统计

| 严重程度 | 数量 | 说明 |
|---------|------|------|
| 🔴 严重 | 4 | 可能导致崩溃、状态不一致、资源泄漏 |
| 🟡 中等 | 10 | 可能导致非预期行为、错误传播不完整 |
| 🟢 低优先级 | 11 | 代码质量、防御性编程、一致性 |

---

## 🔴 严重问题

### 1. executor.py — `or` 操作符导致 timeout=0 被忽略（同类问题残留）

- **文件**：`app/tasks/executor.py:55, 229`
- **类型**：正确性
- **描述**：v1 审计修复了 `__init__` 中的 `or` 判断（line 40-41），但同文件中还有两处相同的模式：
  - Line 55: `self.config.timeout or self.DEFAULT_TASK_TIMEOUT` — `timeout=0` 被替换为默认值
  - Line 229: `step.timeout or 10000` — `step.timeout=0` 被替换为 10000
- **建议修复**：统一改为 `is not None` 判断：
  ```python
  # line 55
  task_timeout_ms = self.config.timeout if self.config.timeout is not None else self.DEFAULT_TASK_TIMEOUT
  # line 229
  effective_timeout = step.timeout if step.timeout is not None else 10000
  ```

### 2. monitor_core.py — `_stop_event.wait()` 返回值被忽略，stop 信号在 2s 等待内不生效

- **文件**：`app/core/monitor_core.py:380`
- **类型**：正确性
- **描述**：`_login_recovery_inner` 中调用 `self._stop_event.wait(timeout=2)` 等待 2 秒，但忽略了返回值。如果 stop 信号在这 2 秒内到来，代码不会中断当前登录后的等待，继续检查 `login_ok` 等后续流程。虽然外层 `while self.monitoring` 最终会退出，但这 2 秒阻塞会延迟对 stop 信号的响应。
- **建议修复**：
  ```python
  if self._stop_event.wait(timeout=2):
      return RecoveryResult.BREAK
  ```

### 3. playwright_worker.py — `_handle_debug_stop` 重建页面丢失反检测脚本

- **文件**：`app/workers/playwright_worker.py:541-546`
- **类型**：状态一致性
- **描述**：`_handle_debug_stop` 关闭调试页面（与主页面相同实例时）后创建新页面，但新页面未重新应用反检测脚本（`stealth_mode`）和路由拦截（`low_resource_mode`）。如果用户启用了这些功能，后续调试启动时页面将缺少这些保护。
- **建议修复**：在创建新页面后调用 `_apply_stealth_and_routes` 重新应用设置。

### 4. monitor_core.py — `block_proxy` 配置值为 null 时代理设置被反转

- **文件**：`app/core/monitor_core.py:153, 184`
- **类型**：正确性
- **描述**：`set_block_proxy(self.config.get("block_proxy", True))` — 如果 JSON 中 `block_proxy` 设为 `null`，`config.get("block_proxy", True)` 返回 `None`。在 `probes.py` 中 `not is_block_proxy()` → `not None` = `True`，导致代理行为反转（本应屏蔽代理变为信任代理）。
- **建议修复**：
  ```python
  block_proxy = self.config.get("block_proxy", True)
  set_block_proxy(block_proxy if block_proxy is not None else True)
  ```

---

## 🟡 中等问题

### 5. executor.py — `_execute_step` 异常日志丢失堆栈跟踪

- **文件**：`app/tasks/executor.py:251-254`
- **类型**：错误传播
- **描述**：`_execute_step` 捕获 `handler.execute` 的所有异常时使用 `logger.error` 而非 `logger.exception`，丢失了堆栈跟踪。对于非预期的 Programming Error（如 TypeError），丢失堆栈会增加调试难度。
- **建议修复**：将 `logger.error` 改为 `logger.exception`：
  ```python
  except Exception as e:
      logger.exception("步骤 [{}/{}] 执行失败", step.id, step.type)
      return False, str(e)
  ```

### 6. executor.py — `execute_remaining` 未校验 `from_index` 非负

- **文件**：`app/tasks/executor.py:282-285`
- **类型**：边界条件
- **描述**：`execute_remaining(page, from_index)` 循环 `range(from_index, len(...))`，负值 `from_index` 会导致 `execute_step_at` 收到越界索引，返回"步骤索引超出范围"但中间步骤被静默跳过。调试模式下传入负值可能产生令人困惑的行为。
- **建议修复**：`from_index = max(0, from_index)`

### 7. executor.py — `_network_detection_check` 中 JSON null 值导致 TypeError

- **文件**：`app/tasks/executor.py:315`
- **类型**：边界条件
- **描述**：`cfg.get("post_login_delay", 5)` — 如果 JSON 中 `post_login_delay` 设为 `null`，`.get()` 返回 `None` 而非默认值 5，后续 `asyncio.sleep(None)` 会抛出 TypeError。同样的问题存在于 `cfg.get("enable_tcp_check", True)` 等调用中（虽然不是 crash 但语义不符）。
- **建议修复**：统一对所有 `cfg.get(key, default)` 做 null 值检查，或使用 `cfg.get(key) or default` 模式（注意 0 和 False 的语义）。

### 8. variable_resolver.py — `json.dumps` 对不可序列化对象抛出 TypeError

- **文件**：`app/tasks/variable_resolver.py:65`
- **类型**：异常处理
- **描述**：`json.dumps(raw, ensure_ascii=False)` 在 `runtime_vars` 值为不可 JSON 序列化的对象（如 Playwright JSHandle、自定义类实例）时抛出 TypeError，未捕获。虽然正常情况下 `runtime_vars` 只存基本类型，但 `eval` 步骤的返回值可能包含复杂对象。
- **建议修复**：
  ```python
  try:
      resolved = json.dumps(raw, ensure_ascii=False)
  except TypeError:
      resolved = str(raw)
  ```

### 9. crypto.py — 模块级全局变量的跨线程可见性

- **文件**：`app/utils/crypto.py:27-30`
- **类型**：线程安全
- **描述**：`_cached_raw_key`、`_cached_fernet_key`、`_decryption_failed` 是模块级全局变量。`_get_or_create_key` 使用 double-checked locking，但 `_cached_raw_key` 的第一个检查（line 36）在锁外，Python GIL 下安全，free-threaded Python 下需要内存屏障。`_decryption_failed` 是 `threading.Event`，线程安全。
- **建议修复**：在 free-threaded Python 场景下考虑使用 `threading.local()` 或添加显式内存屏障。当前 CPython 不受影响。

### 10. executor.py — `_handle_success` 和 `_handle_failure` 的 `page` 参数未使用

- **文件**：`app/tasks/executor.py:366-413`
- **类型**：代码质量
- **描述**：两个方法签名包含 `page` 参数但从未使用。虽然不影响功能，但增加了调用方的困惑——调用者需要传 page 但实际不消费。v1 审计已记录（低优先级 #1），仍未修复。
- **建议修复**：将 `page` 改为 `_page` 或移除参数（需同步修改调用方）。

### 11. script_runner.py — `FileNotFoundError` 未被显式捕获

- **文件**：`app/workers/script_runner.py:201-209`
- **类型**：异常处理
- **描述**：`policy.run_sync(cmd, ...)` 内部调用 `subprocess.run()`，若二进制不存在会抛出 `FileNotFoundError`。当前只捕获 `PermissionError`，`FileNotFoundError` 会传播到调用方。虽然上层通常有兜底 catch，但错误信息对用户不友好。
- **建议修复**：在 `except PermissionError` 后添加 `except FileNotFoundError` 分支。

### 12. monitor.py — `ws_broadcast_queue` getter 的 fallback 创建独立 deque

- **文件**：`app/services/monitor.py:481-485`
- **类型**：状态一致性
- **描述**：`ws_broadcast_queue` 属性在 `_dashboard_sink` 为 None 时返回独立的 `deque(maxlen=200)`。调用方（如 `_queue_status_broadcast`）往这个临时 deque 追加数据，但该数据永远不会被消费（因为没有绑定到 DashboardSink），导致静默丢消息。
- **建议修复**：在 `_queue_status_broadcast` 中增加 `if self._dashboard_sink is None: return` 的守卫。

### 13. scheduler.py — `_on_task_done` 中使用 `task.exception()`

- **文件**：`app/services/scheduler.py:430`
- **类型**：正确性
- **描述**：`task.exception()` 在不检查 `task.done()` 的情况下调用是安全的（未完成的 task 返回 None）。但 `task.cancelled()` 和 `task.exception()` 之间存在微小窗口——cancel 后但在 exception 前，task 可能完成了且有异常。当前代码先检查 cancelled 再读 exception，顺序正确。

### 14. login_history.py — 概率性清理在大写入量下可能丢失记录

- **文件**：`app/services/login_history.py:109-117`
- **类型**：数据安全
- **描述**：每 50 次写入触发一次清理（30 天过期）。清理操作在 `_cleanup_lock` 锁下进行，但写入只在 `_lock` 下。清理期间新写入会正常追加，但 `atomic_write` 在清理时的替换可能与并发写入产生竞态——清理读到的文件内容可能不包含刚刚追回的行。不过由于清理使用 `atomic_write`，最坏情况是刚写入的记录被清理丢弃。概率极低（写入恰好发生在清理读取和替换之间）。
- **建议修复**：清理前先用 `_lock` 锁定写入，或改用基于时间戳的追加删除（如按天分文件）而非全量重写。

---

## 🟢 低优先级问题

### 15. step_handlers.py — char_range OCR 实例未加入清理队列

- **文件**：`app/tasks/step_handlers.py:746`
- **描述**：带 `char_range` 的 OCR 识别每次创建新的 `ddddocr.DdddOcr` 实例，使用后仅靠 GC 回收。高频验证码场景下可能短时间内累积多个模型实例（每个数百 MB）。
- **建议**：可考虑在 finally 块中显式 `del ocr` 并调用 `gc.collect()`，或引入小型 LRU 缓存。

### 16. validator.py — `validate()` 未校验 config 参数类型

- **文件**：`app/tasks/validator.py:21`
- **描述**：传入非 dict 值（list、None）时 `config.get("name")` 抛出 AttributeError。调用方应保证传入 dict，但验证器自身缺少防御性检查。

### 17. validator.py — `TASK_ID_PATTERN.fullmatch(step_id)` 对非字符串抛出 TypeError

- **文件**：`app/tasks/validator.py:63`
- **描述**：`step_id` 可能不是字符串（如数字 123 或 None），`re.fullmatch(None)` 抛出 TypeError。

### 18. models.py — `float(data.get("step_delay", 0.5))` 对非数字抛出异常

- **文件**：`app/tasks/models.py:194`
- **描述**：`step_delay` 为非数字字符串或 None 时，`float()` 抛出 ValueError/TypeError。

### 19. step_handlers.py — `_find_element` 空字符串 selector 被静默处理

- **文件**：`app/tasks/step_handlers.py:196`
- **描述**：`_find_element(ctx, "", timeout)` → `_parse_selectors("")` 返回 `[""]` → `ctx.locator("")` 抛出异常，被外层 catch 静默跳过。应早返回空值错误。

### 20. step_handlers.py — `WaitHandler` 的 `locator` 创建在 try 块外

- **文件**：`app/tasks/step_handlers.py:481`
- **描述**：`ctx.locator(selector).first` 在 `try` 块外，无效 CSS 选择器语法错误（非元素未匹配）不会被 `except TimeoutError` 捕获，传播到上层 `except Exception` 兜底。

### 21. playwright_worker.py — `_close_resource` 中 check 函数异常未捕获

- **文件**：`app/workers/playwright_worker.py:748-752`
- **描述**：`has_check` 检查函数（如 `is_closed()`）的异常未被 `_close_resource` 捕获，传播到 `_cleanup_browser` 后某资源关闭失败不影响其他资源，但资源引用未置 None。

### 22. monitor_core.py — `async asyncio.to_thread` 使用不当

- **文件**：`app/services/monitor.py:66`
- **描述**：原 v1 审计 #5 指出 `manual_login` 使用 `asyncio.to_thread` 执行 Playwright 操作。审查确认通过 Worker 的 `submit` 队列执行，线程安全。此问题已澄清，但代码中 `to_thread(lambda: get_worker().submit(...))` 的两层间接调用可读性较差。

### 23. script_runner.py — `_content_temp_file` 使用 `ntpath` 而非 `os.path`

- **文件**：`app/workers/script_runner.py:101, 152`
- **描述**：使用 `ntpath`（Windows 路径模块）处理跨平台路径。在 Linux/macOS 上，`ntpath.basename("/usr/bin/python3")` 意外地返回正确结果（没有反斜杠），但这是巧合而非正确逻辑。应使用 `os.path`。

### 24. detect.py — 重复的 `hasattr(subprocess, "CREATE_NO_WINDOW")` 判断

- **文件**：`app/network/detect.py:158-162`
- **描述**：`_detect_ssid_windows` 使用内联 `hasattr` 检测而非已导入的 `CREATE_NO_WINDOW_FLAG` 常量。v1 审计在 `notify.py` 和 `process.py` 中发现了相同问题（低优先级 #27, #28），此处是第三处。应统一使用 `platform_utils.CREATE_NO_WINDOW_FLAG`。

### 25. probes.py — 全局 ThreadPoolExecutor 在模块级别创建

- **文件**：`app/network/probes.py:25-26`
- **描述**：`executor = ThreadPoolExecutor(max_workers=5)` 在模块导入时创建。多次导入（虽然 unlikely）或 fork 场景下可能创建多个实例。`atexit` 只注册一次 cleanup。v1 审计已记录（低优先级 #19）。

---

## 修复优先级建议

### 第一批（正确性热修复）
1. `executor.py:55,229` — `or` 操作符 timeout=0 问题（#1）
2. `monitor_core.py:380` — stop 信号在 2s wait 内被忽略（#2）
3. `monitor_core.py:153` — block_proxy null 值反转（#4）

### 第二批（可靠性增强）
4. `playwright_worker.py:541` — 调试页面重建丢失反检测脚本（#3）
5. `executor.py:251` — 异常日志丢失堆栈（#5）
6. `executor.py:315` — JSON null 值导致 TypeError（#7）
7. `variable_resolver.py:65` — JSON 序列化异常未捕获（#8）

### 第三批（防御性编程）
8. `executor.py:282` — execute_remaining 负索引（#6）
9. `validator.py:21,63` — 类型检查强化（#16, #17）
10. `models.py:194` — step_delay float 转换异常（#18）
11. `script_runner.py:201` — FileNotFoundError 未捕获（#11）

### 第四批（代码质量）
12. 其余所有 🟢 低优先级问题

---

## 与 v1 审计对比

| 维度 | v1 | v2 |
|------|-----|-----|
| 发现问题数 | 48+ | 25 |
| 🔴 严重 | 6 | 4 |
| 🟡 中等 | 22 | 10 |
| 🟢 低优先级 | 20+ | 11 |
| 新增独有发现 | — | 9 个（#1-#7, #14, #16-#18） |
| v1 遗漏复查 | — | 发现 3 处 v1 同类问题残留（#1, #4, #7） |

**v1 已修复的 v2 复查确认**：`executor.py:40-41` ✓, `step_handlers.py:236` ✓, `variable_resolver.py:62,111` ✓, `validator.py:33,51` ✓, `models.py:189` ✓

**v1 已修复但 v2 发现遗漏**：`executor.py:55,229` 的 `or` 模式只修了 `__init__` 没修其他地方。

---

*报告结束*
