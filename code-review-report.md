# Campus-Auth 代码审查报告

> 审查时间：2026-06-23
> 审查范围：后端核心服务、API 路由、网络检测、任务系统、Playwright Worker、加密模块、前端 Vue、Go/Shell 启动器、工具模块、测试套件
> Review Unit 数量：12

## 摘要

| 严重性 | 数量 |
|--------|------|
| 🔴 Critical | 1 |
| 🟠 Major | 7 |
| 🟡 Minor | 36 |
| 总计 | 44 |

| 模块 | Critical | Major | Minor |
|------|----------|-------|-------|
| 服务层 | 1 | 2 | 6 |
| 任务系统 | — | 1 | 3 |
| API 路由层 | — | 1 | 4 |
| 前端 | — | 1 | 4 |
| Go 启动器 | — | 2 | 2 |
| 测试 | — | 2 | 6 |
| 工作线程 | — | — | 2 |
| 工具模块（加密） | — | — | 5 |
| 网络检测 | — | — | 9 |
| 工具模块（通用） | — | — | 3 |

---

## 🔴 Critical 问题

### [1] _handle_login 阻塞引擎线程，登录期间所有命令停摆且关闭应用可能挂起

- **模块**：服务层 / 工作线程
- **文件**：`app/services/engine.py:410-432, 731-753`
- **分类**：🟠 可靠性 / 崩溃
- **描述**：`_handle_login` 在引擎线程中调用 `handle.result(timeout=worker_timeout+60)` 同步等待登录完成，最长阻塞 150 秒（login_timeout=600 时）。在此期间引擎主循环 `_engine_loop` 无法处理队列中的 STOP/RELOAD/SHUTDOWN 命令，`_do_network_check` 和 `_run_schedule_tick` 也不会执行。对比同文件中 `_do_async_login`（自动登录路径）已使用回调模式（submit + add_done_callback），不阻塞引擎线程，手动登录路径却仍使用同步等待模式。更严重的是，`engine.shutdown()` 的 `_engine_thread.join(timeout=5.0)` 超时后返回，引擎线程作为 daemon 继续运行，用户关闭窗口后进程可能挂起长达 150 秒。
- **影响**：用户在登录过程中点击「停止监控」或「重载配置」无响应；网络断线检测延迟，可能错过校园网掉线重连窗口；定时任务调度被推迟。关闭应用后 Windows 任务管理器显示进程未退出，系统托盘图标已消失但进程仍在，可能导致下次启动端口冲突。
- **建议修复方向**：将 `_handle_login` 改为异步模式（提交登录后注册 done 回调，在回调中设置 `cmd.response_data` 和 `cmd.response_event`），与 `_do_async_login` 保持一致的架构模式。同时在 `engine.shutdown()` 中发送 SHUTDOWN 命令前先调用 `self._orchestrator.cancel_running()` 中断正在执行的登录。
- **代码片段**：
```python
# _handle_login (line 429): 阻塞引擎线程
ok, msg = handle.result(timeout=worker_timeout + 60)

# shutdown (line 738-744): 未取消登录就等待线程
self._shutdown_event.set()
with contextlib.suppress(queue.Full):
    self._cmd_queue.put_nowait(EngineCommand(type=EngineCmdType.SHUTDOWN))
if self._engine_thread and self._engine_thread.is_alive():
    self._engine_thread.join(timeout=5.0)  # 5秒后放弃，但线程还在
```

---

## 🟠 Major 问题

### [1] save_global_and_profile 用 payload 的陈旧 logging 覆盖磁盘上的 source_levels

- **模块**：服务层
- **文件**：`app/services/config_service.py:49-67`
- **分类**：🟠 可靠性
- **描述**：`save_global_and_profile` 用 `payload.logging`（含 source_levels）整体替换 `data.global_config.logging`。如果用户先通过 `PUT /api/config/source-level` 修改了日志级别（`_persist_source_levels` 直接写入磁盘），再保存主配置（前端 `GET /api/config` 拿到的 logging.source_levels 可能已过时），则 save 会用陈旧的 source_levels 覆盖磁盘上的新值。
- **影响**：用户调整日志级别后立即保存主配置，会导致刚设置的日志级别被还原。用户以为设置丢失。
- **建议修复方向**：在 `_apply` 中构建 GlobalConfig 时，保留磁盘上已有的 source_levels，而非使用 payload 中的值。例如：`logging=payload.logging.model_copy(update={'source_levels': data.global_config.logging.source_levels})`。

### [2] WebSocket 广播总体超时时跳过死亡连接清理

- **模块**：服务层
- **文件**：`app/services/websocket_manager.py:52-69`
- **分类**：🟠 可靠性
- **描述**：`broadcast()` 中 `asyncio.wait_for` 的 5 秒总体超时触发时，`TimeoutError` 被捕获后直接 return，跳过了后续的死亡连接清理代码（lines 75-78）。超时的 `_send_safe` 任务被取消，其中可能正在等待锁以移除死亡连接的代码也被取消。
- **影响**：死亡连接在 `_connections` 列表中累积，后续每次广播都尝试向已断开的连接发送数据，导致重复超时和更多无效 I/O。在 WebSocket 频繁断连重连（如浏览器标签刷新）时可能加剧。
- **建议修复方向**：将死亡连接清理逻辑移入 `try/finally` 块，确保无论是否超时都执行清理。或在 `TimeoutError` 分支中也执行一轮清理。

### [3] cancel_login 使用 async def 却直接调用同步阻塞方法，阻塞事件循环

- **模块**：API 路由层
- **文件**：`app/api/monitor.py:60-66`
- **分类**：🟠 可靠性
- **描述**：`cancel_login` 声明为 `async def`，在事件循环线程上直接调用 `svc.cancel_login()`。该方法内部获取 `_slot_lock`（RLock）并调用 `future.cancel()`。若此时引擎线程正持有 `_slot_lock` 执行 submit（含 model_dump 转换和线程池提交），事件循环会被阻塞。同文件中 `manual_login` 正确使用 `asyncio.to_thread` 包装同步调用，两者风格不一致。
- **影响**：取消登录时若恰好与引擎的 submit 操作竞争 `_slot_lock`，事件循环短暂阻塞，影响同一事件循环上的其他异步端点和 WebSocket 连接的响应性。
- **建议修复方向**：移除 `async` 关键字改为同步 `def`（FastAPI 自动使用线程池），或将 `svc.cancel_login()` 包装在 `asyncio.to_thread` 中。
- **代码片段**：
```python
@router.post("/api/actions/cancel-login", response_model=ActionResponse)
async def cancel_login(
    svc: ScheduleEngine = Depends(get_monitor_service),
) -> ActionResponse:
    ok, message = svc.cancel_login()  # 同步调用，未用 to_thread
```

### [4] resolve_for_js 对非字符串类型的运行时变量双重 JSON 编码

- **模块**：任务系统
- **文件**：`app/tasks/variable_resolver.py:62-70, 102-120`
- **分类**：🟠 可靠性
- **描述**：当 eval 步骤通过 `store_as` 将非字符串结果（数字、布尔值、null、数组）存入 `runtime_vars` 后，后续 eval 步骤的脚本中用 `{{var}}` 引用该变量时，值会被双重编码。路径为：`resolve()` 的 replacer 先对非字符串值执行 `json.dumps`（如 int 5 → Python 字符串 "5"），然后 `resolve_for_js` 的 replacer 对该字符串再次 `json.dumps`（"5" → JS 字面量 "5" 带引号）。最终 JS 代码拿到的是字符串 "5" 而非数字 5。对于 null：None → "" → JS 中为 ""（空串）而非 null。对于 true：True → "true" → JS 中为 "true"（字符串）而非 true。
- **影响**：eval 步骤链式调用时，前一步的数字/布尔/对象结果在后续步骤的 JS 中变为字符串字面量。导致 JS 中 `+` 运算变成字符串拼接（"5" + 1 = "51" 而非 6）、`===` 严格比较失败（"true" === true 为 false）、对象方法调用报错等。字符串类型的结果（最常见场景）不受影响。
- **建议修复方向**：`resolve_for_js` 的 replacer 应区分字符串与非字符串值：对字符串值做 `json.dumps` 以确保安全嵌入，对非字符串值直接使用 `resolve` 返回的 `json.dumps` 结果（已是合法 JS 字面量），不再二次包装引号。
- **代码片段**：
```python
# resolve 中对非字符串 runtime_var 的处理（line 66-68）:
elif not isinstance(raw, str):
    resolved = json.dumps(raw, ensure_ascii=False)
# resolve_for_js 的 replacer（line 112-118）:
def replacer(match):
    resolved = self.resolve(match.group(0))
    if resolved == match.group(0):
        return json.dumps(match.group(0))
    return json.dumps(str(resolved))  # ← 对已经是 JSON 数字的 "5" 再次加引号
```

### [5] 解压失败和 uv.exe 缺失检查会中断 Go 启动器的镜像 fallback 链

- **模块**：Go 启动器
- **文件**：`start.go:179-191`
- **分类**：🔵 兼容性
- **描述**：在 mirror for 循环中，curl 下载失败（`continue`）和 SHA256 校验失败（`continue`）都正确地 fallback 到下一个镜像。但 tar 解压失败（`return`）和解压后 uv.exe 不存在（`return`）直接退出函数，不再尝试后续镜像。如果某个镜像返回了格式异常的压缩包（如 gzip 压缩的 tar 伪装成 zip），Windows tar 可能解压失败，此时用户将失去剩余镜像的 fallback 机会。
- **影响**：若某个镜像返回格式异常但 curl 下载成功的文件，整个 uv 下载流程直接失败，用户必须手动安装 uv，多镜像 fallback 机制形同虚设。
- **建议修复方向**：将 line 179-186 的 `return` 改为 `continue`（先清理 archive 和已解压文件），与 SHA256 失败保持一致的 fallback 策略。

### [6] start.sh SHA256 校验失败直接 exit 退出，不尝试下一个镜像

- **模块**：Go 启动器
- **文件**：`start.sh:90-109`
- **分类**：🔵 兼容性
- **描述**：与 start.go 不同，start.sh 将 SHA256 校验放在了 mirror for 循环的外部（line 90-110）。mirror 循环仅验证 tar 包的完整性（`tar -tzf`），SHA256 校验在循环结束后才执行。如果某个镜像返回了一个 tar 格式合法但内容与预期版本不符的文件（SHA256 不匹配），脚本直接 `exit 1`，不再尝试后续镜像。相比之下，start.go 的 SHA256 校验在循环内部，失败后会 `continue` 到下一个镜像。
- **影响**：macOS/Linux 用户遇到首个镜像返回过期/错误版本时（tar 格式合法但 SHA256 不匹配），启动脚本直接失败，无法利用剩余镜像。对于使用国内镜像的用户，首个镜像出问题的概率相对较高。
- **建议修复方向**：将 SHA256 校验移入 mirror for 循环内部（在 `tar -tzf` 检查之后），失败时 `rm` 掉 archive 并 `continue` 到下一个镜像，与 start.go 保持一致。

### [7] resetConfig() 不持久化且 UI 误报"已保存"

- **模块**：前端
- **文件**：`frontend/js/methods/config.js:153-158`
- **分类**：🟠 可靠性
- **描述**：`resetConfig()` 将 `_lastSavedConfig` 设为 `null` 后，`configDirty` 的计算逻辑 `_lastSavedConfig !== null && ...` 直接短路返回 `false`，加上 `_lastSavedConfig` 本身不是响应式属性（定义在 methods 对象而非 data() 中），导致保存按钮错误显示"已保存"，自动保存也不会触发。用户重启后旧配置复现。
- **影响**：用户执行重置操作后以为配置已恢复默认值并持久化，但实际上重启后旧配置仍然生效。
- **建议修复方向**：`resetConfig()` 应在重置内存状态后立即调用 `saveConfig()` 持久化，或调整 `configDirty` 的计算逻辑使其在 `_lastSavedConfig === null` 时也返回 true。

---

## 🟡 Minor 问题

### [1] CompositeCancelEvent 覆写 is_set() 但未同步覆写 wait()，违反 threading.Event 契约

- **模块**：服务层
- **文件**：`app/utils/cancel_token.py:31-44`
- **分类**：⚪ 代码质量
- **描述**：`CompositeCancelEvent` 继承 `threading.Event` 并覆写了 `is_set()` 实现惰性扫描源事件。但 CPython 的 `Event.wait()` 内部直接读取 `self._flag` 属性并使用 `self._cond` 条件变量，不调用 `is_set()`。当某个源事件被 set 而复合事件自身的 `_flag` 仍为 False 时，`wait(timeout)` 会阻塞到超时才返回，尽管此时 `is_set()` 已返回 True。同理，`clear()` 仅清除自身 `_flag` 但保留源列表，导致 `clear()` 后立即调用 `is_set()` 可能仍返回 True。`clear_sources()` 方法已在 BUG-062 中新增但从未被调用，属于死代码。
- **影响**：当前代码中所有消费者均使用 `is_set()` 轮询而非 `wait()` 阻塞，因此此问题不会在现有代码中触发。但任何未来维护者合理地调用 `wait()` 都会遭遇隐蔽的超时延迟 bug。
- **建议修复方向**：覆写 `wait()` 使其感知源事件，或在 `clear()` 中同时调用 `clear_sources()` 保持 Event 契约一致性。

### [2] list_recent() 读取 JSONL 文件未持有 self._lock，与 add()/_cleanup_old() 存在文件访问竞态

- **模块**：服务层
- **文件**：`app/services/login_history_service.py:118-148`
- **分类**：🟠 可靠性
- **描述**：`list_recent()` 直接 `open()` 读取 `login_history.jsonl`，不获取 `self._lock`。而 `add()` 在持有锁的情况下写入并 `fsync()`，`_cleanup_old()` 也在锁内通过 `atomic_write` 整体重写文件。在 Windows 上读取可能与写入并发执行，导致读到不完整的 JSON 行或短暂空文件。
- **影响**：触发概率很低（list_recent 由 API 按需调用，add 仅在登录完成时触发）。触发时 `list_recent` 会跳过损坏行（有 try/except），但可能丢失最近一条记录或返回不完整的结果列表。
- **建议修复方向**：在 `list_recent()` 的文件读取操作外层加 `with self._lock`。

### [3] login_once 源未取消已有登录任务，新旧登录在单 worker 池中串行执行

- **模块**：服务层
- **文件**：`app/services/login_orchestrator.py:220-237`
- **分类**：🟠 可靠性
- **描述**：`submit()` 的去重逻辑中，当 `source='login_once'` 且已有未完成的 handle 时，代码执行 `pass` 直接进入新建分支，不调用 `existing.cancel()`。旧的 login_once 任务继续运行，新任务被提交到 `max_workers=1` 的线程池排队等待。
- **影响**：极端情况下（用户连续触发两次 login_once），两个登录任务串行执行，第二个需等待第一个完成或超时（最长 600s），导致登录延迟和资源浪费。
- **建议修复方向**：如果 login_once 语义是"只保留最新一次"，应调用 `existing.cancel()` 取消旧任务。

### [4] execute_task_async 向调用方抛出 RuntimeError（队列满）时缺少结构化降级路径

- **模块**：服务层
- **文件**：`app/services/task_executor.py:156-177`
- **分类**：🟠 可靠性
- **描述**：当 `BoundedExecutor` 的信号量耗尽（queue_size=10），`submit()` 抛出 `RuntimeError`，`execute_task_async` 直接 re-raise。调用方（engine 调度器）需自行捕获并处理。如果调用方未做 try/except，该异常会向上传播，可能中断整个调度周期。
- **影响**：正常使用中定时任务数量少、执行频率低，队列几乎不可能满。但如果某任务长时间阻塞，后续任务提交会被拒绝。
- **建议修复方向**：在 `execute_task_async` 内部捕获 `RuntimeError` 并返回一个已完成且带异常信息的 Future。

### [5] 手动登录异常被误报为"超时"，cancel_login 结果也被误报

- **模块**：服务层
- **文件**：`app/services/engine.py:795-803`
- **分类**：🟠 可靠性
- **描述**：`_handle_login` 若在 `orchestrator.submit()` 等处抛出非预期异常，`_process_command` 捕获异常并设置 `response_event`，但 `cmd.response_data` 仍为 None。`run_manual_login` 仅检查 `response_data is None` 就返回"手动登录超时"。此外，`cancel_login()` 导致 `_handle_login` 中的 `handle.result()` 抛出 `CancelledError`，同样使 `response_data` 为 None，用户看到的也是"超时"而非"已取消"。
- **影响**：用户在 UI 上看到误导性的"超时"错误信息，无法区分真正的超时、内部异常和主动取消三种不同情况。
- **建议修复方向**：在 `_handle_login` 中增加对 Exception 的 try/except，将异常信息写入 `cmd.response_data`。

### [6] _handle_debug_stop 中 new_page() 缺少异常处理，失败后浏览器进入不可用状态

- **模块**：工作线程
- **文件**：`app/workers/playwright_worker.py:606-613`
- **分类**：🟠 可靠性
- **描述**：在 `_handle_debug_stop` 中，先通过 `_cleanup_debug_session` 关闭了调试页面，然后调用 `self._context.new_page()` 创建新主页面。此调用没有 try/except 保护。如果 `new_page()` 失败，`self._page` 仍指向已关闭的旧页面对象，后续所有需要 `self._page` 的操作都会失败。
- **影响**：调试停止后 Worker 的 `self._page` 指向已关闭页面，后续操作可能失败。虽然下次登录时 `ensure_browser` 会重建浏览器（自愈），但两次操作之间浏览器处于不可用状态。
- **建议修复方向**：为 `self._context.new_page()` 添加 try/except，失败时走完整重建路径。

### [7] TaskValidator 不验证 variables 字段类型，非 dict 值会导致运行时 TypeError

- **模块**：任务系统
- **文件**：`app/tasks/validator.py:21-54`
- **分类**：🟠 可靠性
- **描述**：`validate()` 方法检查了 name、steps 及各步骤字段，但未验证 `variables` 的类型。若任务 JSON 中 `variables` 为 null、数组或数字等非 dict 值，验证通过但 `TaskConfig.variables` 被赋为该非法值。当 `VariableResolver` 执行 `var_name in self.config.variables` 时，对 null/数字类型会抛出 TypeError。
- **影响**：用户手动编辑任务 JSON 时若误将 `variables` 写为 null 或非对象类型，任务验证通过但执行时崩溃，错误信息不直观。
- **建议修复方向**：在 `validate()` 中增加对 `variables` 字段的类型检查：若存在则必须为 dict。

### [8] TaskValidator 仅验证步骤级 timeout 而不验证任务级 timeout

- **模块**：任务系统
- **文件**：`app/tasks/validator.py:108-113`
- **分类**：🟠 可靠性
- **描述**：验证器对每个 step 的 timeout 做了类型和正值检查，但对任务顶层的 timeout 字段完全没有验证。`TaskConfig.from_dict` 中 `timeout=data.get("timeout", DEFAULT_TASK_TIMEOUT_MS)` 直接取值，若 timeout 为字符串、负数或 null，会导致下游使用时出现 TypeError 或逻辑异常。
- **影响**：任务 JSON 中 timeout 字段类型错误时，验证通过但执行时可能出现不可预期的超时行为或异常。
- **建议修复方向**：在 `validate()` 中为顶层 timeout 增加与步骤级 timeout 相同的类型和正值校验。

### [9] _find_task_type 与 load_task 的目录搜索顺序不一致

- **模块**：任务系统
- **文件**：`app/tasks/manager.py:406-417 vs 79-97`
- **分类**：🟠 可靠性
- **描述**：`_find_task_type` 先搜索 `scripts/` 再搜索 `browser/`，而 `load_task` 在无 task_type 参数时先搜索 `browser/` 再搜索 `scripts/`。当同一 task_id 同时存在于两个目录时，不同 API 返回不同任务版本。
- **影响**：同一 task_id 在两个子目录都存在时，不同 API 返回不同任务版本，行为不一致。
- **建议修复方向**：统一 `_find_task_type` 和 `load_task` 的搜索优先级顺序。

### [10] save_profile 和 delete_profile 在 apply_profile 失败时静默吞掉错误

- **模块**：API 路由层
- **文件**：`app/api/profiles.py:64-98`
- **分类**：🟠 可靠性
- **描述**：两个端点在方案保存/删除成功后调用 `monitor_svc.apply_profile()` 来通知引擎重载配置并重启监控。若 `apply_profile` 失败（队列满、超时、重载失败），异常被 `except Exception` 捕获后仅记录 warning 日志，API 仍返回 `success=True`。
- **影响**：前端显示操作成功，但引擎可能仍在运行旧方案的配置。用户需手动检查监控状态才能发现问题。
- **建议修复方向**：在 `apply_profile` 失败时，在返回的 `ActionResponse.message` 中附加警告信息。

### [11] 配置变更日志遗漏 ISP 和运营商自定义字段的变更检测

- **模块**：API 路由层
- **文件**：`app/api/config.py:166-181`
- **分类**：⚪ 代码质量
- **描述**：`_log_config_changes` 通过遍历 `flat_old`（来自 `RuntimeConfig.model_dump()`）的键来检测变更。`RuntimeConfig` 的 credentials 子模型不含独立的 isp 和 carrier_custom 字段（这些值通过 ConfigBuilder 从 profile.carrier 转换而来），因此修改 ISP 下拉框或运营商自定义字段时变更不会被记录到配置变更日志。
- **影响**：用户修改运营商设置后，配置变更日志中缺少对应记录，排查问题时可能遗漏关键操作信息。
- **建议修复方向**：在 `_log_config_changes` 的循环中补充对 `flat_new` 独有键的检测。

### [12] set_source_level 端点绕过 Depends() 依赖注入直接访问 request.app.state

- **模块**：API 路由层
- **文件**：`app/api/config.py:31-54`
- **分类**：⚪ 代码质量
- **描述**：`set_source_level` 和辅助函数 `_persist_source_levels` 通过 `request.app.state.services.profile_service` 直接获取 ProfileService 实例，而非使用 `Depends(get_profile_service)`。同文件中 `get_config` 和 `save_config` 均使用 `Depends()` 注入。
- **影响**：代码风格不一致，削弱了 FastAPI 依赖注入系统在可测试性和可维护性方面的优势。
- **建议修复方向**：将 `set_source_level` 改为使用 `profile_svc: ProfileService = Depends(get_profile_service)`。

### [13] set_level 对无效日志级别静默降级为 INFO，API 仍返回成功

- **模块**：API 路由层
- **文件**：`app/api/config.py:42-54`
- **分类**：🟠 可靠性
- **描述**：`config.set_level(level)` 内部对不在 `VALID_LOG_LEVELS` 中的级别值静默返回默认值 `'INFO'`。`set_source_level` 端点未检查实际设置的级别是否与请求一致，直接返回成功。
- **影响**：若通过 API 直接调用传入了无效级别，响应显示成功但实际设置为 INFO，误导调用方。前端下拉框通常只发送有效值，影响有限。
- **建议修复方向**：在 `set_level` 调用后读取实际生效的级别，若与请求不一致则在响应中附带警告信息。

### [14] race_first_success 超时返回时未取消残留 future

- **模块**：网络检测
- **文件**：`app/utils/concurrent.py:66-68`
- **分类**：⚪ 代码质量
- **描述**：当 `as_completed` 超时触发 `TimeoutError` 时，函数直接返回 False，但未调用 `cancel_pending()` 取消仍在运行的 future。对比 `decision.py` 的 `is_network_available`，后者在超时路径中正确调用了 `cancel_pending(futures)`。
- **影响**：超时后残留的 future 继续在共享 `ThreadPoolExecutor` 中运行，占用线程直到各自的超时生效。探测间隔 300 秒，实际影响有限，但属于资源管理疏漏。
- **建议修复方向**：在 `except TimeoutError` 分支的 `return False` 之前调用 `cancel_pending(futures)`。

### [15] race_first_success 未对 future.result() 做防御性异常捕获

- **模块**：网络检测
- **文件**：`app/utils/concurrent.py:44-45`
- **分类**：⚪ 代码质量
- **描述**：`future.result()` 在 worker 函数抛出异常时会重新抛出该异常。当前仅用 `except TimeoutError` 捕获超时。对比 `decision.py` 的 `is_network_available`，后者为 `future.result()` 额外包裹了 `try/except Exception` 做防御性处理。
- **影响**：当前 `probes.py` 的 worker 函数都有 `except Exception` 保护，暂时不会触发。但作为共享工具函数，缺乏对调用方 worker 质量的防御。
- **建议修复方向**：为 `future.result()` 添加 `try/except Exception` 防御，与 `decision.py` 保持一致。

### [16] _get_probe_client 最终 return 语句在 _probe_lock 保护范围之外

- **模块**：网络检测
- **文件**：`app/network/probes.py:53-54`
- **分类**：🟠 可靠性
- **描述**：`with _probe_lock` 块覆盖第 34-53 行，但第 54 行的 `return _probe_client` 在锁释放以后执行。早期返回（第 40 行）正确位于锁内。锁释放与变量读取之间存在理论竞态窗口：另一线程调用 `set_block_proxy` 可能在此期间关闭客户端并将 `_probe_client` 置为 None。
- **影响**：正常单用户桌面场景下极难触发。如果触发，调用方会收到 `AttributeError`，被 worker 的 `except Exception` 捕获后报告为单次探测失败，下次探测自动恢复。
- **建议修复方向**：将第 54 行的 `return _probe_client` 移入 `with _probe_lock` 块内。

### [17] ipconfig 回退路径缺少 _is_valid_ipv4 验证

- **模块**：网络检测
- **文件**：`app/network/detect.py:149-160`
- **分类**：🟠 可靠性
- **描述**：PowerShell 路径使用 `_is_valid_ipv4()` 验证网关 IP，但 ipconfig 回退路径仅检查 `ip != '0.0.0.0'`。正则 `(\d+\.\d+\.\d+\.\d+)` 可匹配任意点分四段数字，未校验每段是否在 0-255 范围内。
- **影响**：Windows ipconfig 实际输出几乎不会产生非法 IP，但与 PowerShell 和 macOS 路径的防御策略不一致。
- **建议修复方向**：在 ipconfig 回退的两个返回点增加 `_is_valid_ipv4(ip)` 校验。

### [18] nmcli terse 模式未反转义 SSID 中的冒号

- **模块**：网络检测
- **文件**：`app/network/detect.py:259-267`
- **分类**：🟠 可靠性
- **描述**：nmcli `-t`（terse）模式使用 `\:` 转义字段值中的冒号。代码用 `line.split(":", 1)[1]` 取 SSID，但未将 `\:` 还原为 `:`。若 SSID 包含冒号（如 "Net:Work"），返回的值为 "Net\:Work"。
- **影响**：含冒号的 WiFi SSID 会导致方案匹配失败。校园网 SSID 含冒号的概率极低。
- **建议修复方向**：在返回前增加 `.replace("\\:", ":")` 反转义处理。

### [19] all_disabled 时 method 返回 "none" 与 NetworkCheckResult 文档不一致

- **模块**：网络检测
- **文件**：`app/network/decision.py:77-79`
- **分类**：⚪ 代码质量
- **描述**：`NetworkCheckResult.method` 的文档字符串列出的合法值为 "tcp"/"http"/"url"/"paused"/"local_only"/"all_disabled"，但 `check_network_status` 在所有检测关闭时返回 `method="none"`。
- **影响**：当前无消费方读取 method 字段做条件判断，但若未来有代码检查 `result.method == "all_disabled"` 将永远不匹配。
- **建议修复方向**：将返回值改为 `"all_disabled"`，或在文档中补充 "none" 为合法值。

### [20] 函数内延迟导入 parse_url_checks 和 parse_ping_targets

- **模块**：网络检测
- **文件**：`app/network/decision.py:65-87`
- **分类**：⚪ 代码质量
- **描述**：`parse_url_checks` 和 `parse_ping_targets` 在 `check_network_status` 函数体内导入，而非模块顶层。这两个函数来自 `app.utils.network`，与 `decision.py` 之间不存在循环依赖风险。
- **影响**：若 `app.utils.network` 模块存在导入错误，错误会在首次调用时才暴露，而非应用启动时立即报错。
- **建议修复方向**：将这两个导入移至 `decision.py` 模块顶层。

### [21] macOS 网关检测的 "gateway" 关键词匹配可能命中非网关行

- **模块**：网络检测
- **文件**：`app/network/detect.py:286-293`
- **分类**：⚪ 代码质量
- **描述**：代码用 `"gateway" in line.lower()` 逐行扫描 `route -n get default` 的输出。该输出包含 `flags: <UP,GATEWAY,DONE,STATIC,...>` 等含 "gateway" 字样的非网关行。虽然 `_is_valid_ipv4` 校验会过滤掉无效 IP，但函数仍会对这些行做无意义的 split 和校验。
- **影响**：不会导致错误结果，但增加了不必要的解析开销。
- **建议修复方向**：将匹配条件改为 `line.strip().lower().startswith("gateway:")`。

### [22] ipconfig 回退第一个正则的 [\s.:]* 分隔符过于宽泛

- **模块**：网络检测
- **文件**：`app/network/detect.py:148-153`
- **分类**：🟠 可靠性
- **描述**：第一个正则模式中 `[\s.:]*` 是贪婪匹配且 `\s` 包含换行符，可跨行匹配。这使得该模式可能在 ipconfig 输出格式异常时跨越多个字段匹配到不相关的 IP 地址。
- **影响**：在标准 ipconfig 输出下不会出问题，但若输出格式异常理论上可能匹配到错误的 IP。
- **建议修复方向**：将 `[\s.:]*` 改为 `[^\S\n.:]*`（排除换行符），使其仅在同一行内匹配。

### [23] saveConfig() abort 竞态可能导致 busy.save 状态闪烁

- **模块**：前端
- **文件**：`frontend/js/methods/config.js`
- **分类**：🟠 可靠性
- **描述**：被取消的旧请求的 `finally` 块会异步地将 `busy.save` 重置为 `false`，可能覆盖新请求设置的 `busy.save = true` 状态。
- **影响**：快速连续保存时，保存按钮可能短暂闪烁或状态不一致。
- **建议修复方向**：在 `finally` 中检查 abort controller 是否为当前请求，仅当前请求的 `finally` 才重置 busy 状态。

### [24] cloneConfig() 浅拷贝共享数组引用

- **模块**：前端
- **文件**：`frontend/js/methods/config.js`
- **分类**：⚪ 代码质量
- **描述**：`cloneConfig()` 使用展开运算符进行浅拷贝，数组属性（如 targets、profiles）仍共享同一引用。
- **影响**：当前无 in-place mutation，但构成维护陷阱。未来若新增对数组的原地修改操作，会意外影响原始配置。
- **建议修复方向**：对数组属性使用 `structuredClone()` 或手动深拷贝。

### [25] closeEditor() 缺少脏值检测

- **模块**：前端
- **文件**：`frontend/js/methods/config.js`
- **分类**：⚪ 代码质量
- **描述**：关闭编辑器时每次都弹确认框，不检查是否有未保存的更改。
- **影响**：用户体验问题——即使没有修改也需要确认。
- **建议修复方向**：在关闭前检查 `configDirty` 状态，仅在存在未保存更改时弹确认框。

### [26] fetchBrowsers() 使用原始 fetch() 无超时

- **模块**：前端
- **文件**：`frontend/js/methods/` 相关文件
- **分类**：🟠 可靠性
- **描述**：`fetchBrowsers()` 直接使用原生 `fetch()` 而无 `AbortController` 超时保护，与项目其他 API 调用的健壮性标准不一致。
- **影响**：若后端响应极慢或无响应，请求将无限挂起。
- **建议修复方向**：统一使用项目内的 API 调用封装或添加 `AbortController` 超时。

### [27] atomic_write 在 os.fdopen 失败时泄漏文件描述符

- **模块**：工具模块（加密）
- **文件**：`app/utils/files.py:39-43`
- **分类**：⚪ 代码质量
- **描述**：`tempfile.mkstemp` 返回 `(fd, path)`。如果 `os.fdopen(tmp_fd, ...)` 抛出异常，`with` 块从未进入，`tmp_fd` 不会被关闭。外层 `except Exception` 只清理了 `tmp_path` 文件，但底层 POSIX 文件描述符仍然泄漏。
- **影响**：每次触发会泄漏一个文件描述符。当前所有调用者使用 utf-8 编码，实际触发概率极低。
- **建议修复方向**：在 `os.fdopen` 之前用 try/except 包裹，或在 except 块中增加 `os.close(tmp_fd)` 的防御性调用。

### [28] decrypt_password 中 InvalidSignature 是死代码导入

- **模块**：工具模块（加密）
- **文件**：`app/utils/crypto.py:162-164`
- **分类**：⚪ 代码质量
- **描述**：代码导入了 `cryptography.exceptions.InvalidSignature` 并在 except 子句中捕获，但 `Fernet.decrypt()` 只抛出 `InvalidToken`（`InvalidToken` 并不继承 `InvalidSignature`）。`InvalidSignature` 仅在使用 HMAC/公钥签名 API 时出现，Fernet 的解密路径不会产生此异常。
- **影响**：无功能影响，但会误导读者以为 Fernet 解密可能产生签名验证异常。
- **建议修复方向**：移除 `InvalidSignature` 的导入和捕获，仅保留 `InvalidToken`。

### [29] 密钥加载时仅校验长度，不验证可用性

- **模块**：工具模块（加密）
- **文件**：`app/utils/crypto.py:46-53`
- **分类**：⚪ 代码质量
- **描述**：`_get_or_create_key` 从文件读取密钥后只检查 `len(key) == 32`，未进行任何加解密验证。如果密钥文件被篡改为一个合法的 32 字节值（非原始密钥），会被静默接受。
- **影响**：密钥文件损坏/篡改不会被立即发现，延迟到第一次 `decrypt_password` 调用时才报错。对单用户桌面应用影响有限。
- **建议修复方向**：可在密钥加载后做一次 test encrypt/decrypt round-trip 验证。

### [30] async 函数 save_screenshot 内部使用同步阻塞 I/O

- **模块**：工具模块（加密）
- **文件**：`app/utils/files.py:83-93`
- **分类**：⚪ 代码质量
- **描述**：`save_screenshot` 声明为 async，但 `Path.mkdir(parents=True)` 是同步文件系统操作，在截图目录层级较深或磁盘响应慢时会阻塞事件循环。
- **影响**：在 FastAPI 事件循环中可能导致短暂阻塞（通常毫秒级）。校园网认证场景下截图频率低，实际影响可忽略。
- **建议修复方向**：如需优化可将 `mkdir` 部分用 `asyncio.to_thread` 包装。

### [31] save_password_field 对 ENC: 前缀值不做格式校验直接透传

- **模块**：工具模块（加密）
- **文件**：`app/utils/crypto.py:231-233`
- **分类**：⚪ 代码质量
- **描述**：当 raw 以 'ENC:' 开头时，函数直接原样返回而不验证其是否为合法的 Fernet 密文。如果传入 'ENC:invalid_data'，会被当作有效加密值存入配置文件。
- **影响**：无效的 ENC: 值被静默存储，延迟到登录时才发现解密失败。考虑到前端是唯一的写入来源，触发概率极低。
- **建议修复方向**：如需增强可做轻量校验（如检查 ENC: 后的内容是否为合法 base64）。

### [32] run_sync 超时后未杀子进程树，可能导致孤儿进程

- **模块**：工具模块（通用）
- **文件**：`app/utils/shell_policy.py:233-242`
- **分类**：🟠 可靠性
- **描述**：`run_sync()` 中 `proc.communicate(timeout=...)` 超时后，CPython 内部只杀死直接子进程，不会递归杀孙进程。随后调用的 `_kill_process_tree_sync(proc.pid)` 虽然会遍历并杀死子孙进程，但此时父进程已死、`psutil.Process(pid)` 会抛 `NoSuchProcess` 被静默捕获，导致孙进程可能存活。
- **影响**：脚本任务超时后，由脚本启动的孙进程可能成为孤儿进程继续运行，占用系统资源。在 Windows 上孙进程可能持有文件锁或端口。
- **建议修复方向**：在 `communicate()` 调用前先通过 psutil 获取子进程列表，`TimeoutExpired` 发生后立即杀死整棵进程树。

### [33] LogConfigCenter.set_level 写 _config 未持锁，与读取端锁保护不对称

- **模块**：工具模块（通用）
- **文件**：`app/utils/logging.py:240-332`
- **分类**：⚪ 代码质量
- **描述**：`set_source_level()`、`get_source_level()`、`should_emit()` 等方法均通过 `_source_levels_lock` 保护，但 `set_level()` 直接修改 `self._config['level'] = normalized` 时未获取任何锁。
- **影响**：CPython GIL 保证 dict 赋值原子性，实际不会导致数据损坏或崩溃。但锁使用不对称是代码异味。
- **建议修复方向**：在 `set_level()` 中获取 `_source_levels_lock` 后再写入 `_config['level']`。

### [34] verify_process_identity 在 create_time 缺失时静默降级为仅 PID 比对

- **模块**：工具模块（通用）
- **文件**：`app/utils/process.py:87-109`
- **分类**：🟠 可靠性
- **描述**：`verify_process_identity()` 接受 `stored_create_time=None` 参数，此时跳过创建时间校验，仅检查 PID 是否存活。`read_pid_file()` 不要求 `create_time` 字段必须存在。
- **影响**：若 PID 被操作系统复用给不同进程，`is_service_running` 会误判为"已在运行"。非 lightweight 模式有端口检查兜底，风险有限。
- **建议修复方向**：在 `verify_process_identity` 中对 `stored_create_time is None` 的情况返回 False。

### [35] start.go 信号转发 goroutine 缺少清理，runCommand 多次调用会累积泄漏

- **模块**：Go 启动器
- **文件**：`start.go:232-243`
- **分类**：⚪ 代码质量
- **描述**：`runCommand` 每次调用都会通过 `signal.Notify` 注册新的信号处理器并启动一个 goroutine，但函数返回时既不调用 `signal.Stop(sigChan)` 也不关闭 `sigChan`，导致 goroutine 永久阻塞。`main` 函数中 `runCommand` 被调用两次（uv sync 和 uv run），第一次调用的 goroutine 和信号注册在第二次调用期间仍然存活。
- **影响**：两次 `runCommand` 调用产生两个永不退出的 goroutine 和两组信号注册。在当前短生命周期场景下无实际危害。
- **建议修复方向**：在 `runCommand` 的 `cmd.Wait()` 之后添加 `defer signal.Stop(sigChan)` 和 `close(sigChan)`。

### [36] start.sh 透传所有参数给 main.py，包括已消费的 --install-only

- **模块**：Go 启动器
- **文件**：`start.sh:158-166`
- **分类**：⚪ 代码质量
- **描述**：`start.go` 在参数解析阶段将 `--install-only` 和 `--no-pause` 从 extraArgs 中过滤，仅将剩余参数透传给 `main.py`。而 `start.sh` 在检测到 `--install-only` 后直接 exit 0，但任何其他 start.sh 专有参数都会被原样透传给 `main.py`。
- **影响**：当前无功能影响。两个脚本的参数处理策略不一致。
- **建议修复方向**：如需保持一致性，可在 `start.sh` 中过滤掉已消费的参数后再 `exec`。

### [37] start.sh curl 的 stderr 被静默丢弃，镜像失败时无诊断信息

- **模块**：Go 启动器
- **文件**：`start.sh:73-74`
- **分类**：⚪ 代码质量
- **描述**：`start.sh` 中 curl 命令使用 `2>/dev/null` 将所有错误输出丢弃。当镜像因网络问题失败时，用户看不到任何 curl 级别的诊断信息。相比之下，`start.go` 保留了 stderr 输出。
- **影响**：当所有镜像都失败时，用户无法判断具体原因，增加排障难度。
- **建议修复方向**：将 curl 的 stderr 重定向到 `>&2` 而非 `/dev/null`。

### [38] test_do_network_check_profile_switch 缺少关键断言 _handle_start.assert_called_once()

- **模块**：测试
- **文件**：`tests/test_services/test_engine.py:589-601`
- **分类**：🟠 可靠性
- **描述**：测试验证方案切换后 `_handle_stop` 和 `_reload_config_internal` 被调用，但遗漏了对 `_handle_start` 的断言。源码 `engine.py:274-276` 在重载成功后会调用 stop + start 重启监控。同项目的 `test_login_flow.py:361` 中相同场景的测试正确包含了三个断言。
- **影响**：如果 `_handle_start` 在方案切换路径中被意外移除，测试仍然通过但监控不会重启。
- **建议修复方向**：在现有断言后添加 `svc._handle_start.assert_called_once()`。

### [39] test_extra_targets_empty_skip 依赖真实网络连通性而非 mock

- **模块**：测试
- **文件**：`tests/test_core/test_network_probes.py:481-486`
- **分类**：🟠 可靠性
- **描述**：测试调用 `_is_auth_url_reachable('http://10.0.0.1/login', extra_targets=[])` 但未 mock `socket.create_connection`。函数在 `extra_targets` 为空列表时走 auth_url 直连路径，实际尝试 TCP 连接 `10.0.0.1:80`。测试能否通过完全取决于运行环境网络。同文件中其他测试都正确 mock 了网络调用。
- **影响**：在 `10.0.0.1` 可达的网络环境中测试会返回 True 而非预期的 False，导致测试失败。
- **建议修复方向**：添加 `@patch('app.network.decision.socket.create_connection', side_effect=TimeoutError)` mock 网络调用。

### [40] 集成测试未覆盖 v3→v4 配置迁移路径

- **模块**：测试
- **文件**：`tests/test_integration/test_login_flow.py:1-74`
- **分类**：🟠 可靠性
- **描述**：`test_login_flow.py` 和 `test_login_integration_extended.py` 的所有测试都从 v4 格式配置开始。`test_profile_service.py` 有 `migrate_v3_to_v4` 的单元测试，但集成测试缺少"从 v3 配置启动 → 自动迁移 → 登录流程正常执行"的端到端验证。
- **影响**：如果迁移过程与登录流程存在交互问题，无法被当前集成测试捕获。
- **建议修复方向**：在 `test_login_flow.py` 中添加至少一个使用 v3 格式 settings.json 的集成测试。

### [41] _make_raw_engine 与 conftest.py 的 _make_raw 实现不一致

- **模块**：测试
- **文件**：`tests/test_integration/test_login_flow.py:34-73`
- **分类**：⚪ 代码质量
- **描述**：`_make_raw_engine()` 与 `test_services/conftest.py` 中的 `_make_raw()` 创建相同的 ScheduleEngine raw 实例，但前者缺少 6 个属性（3 个线程锁和 `set_active_profile` 返回值配置）。两处代码独立维护同一 mock 工厂逻辑。
- **影响**：若后续测试通过 `_make_raw_engine` 创建的引擎调用 `_handle_apply_profile`、`_handle_reload` 等方法，会因缺失属性触发 `AttributeError`。
- **建议修复方向**：将 `_make_raw` 提取到共享模块，让两个文件共用同一个工厂函数。

### [42] 异步回调验证使用 time.sleep(0.1) 硬编码延迟

- **模块**：测试
- **文件**：`tests/test_services/test_engine.py:655-702`
- **分类**：🟠 可靠性
- **描述**：`TestNetworkCheckBackoff` 中 4 个测试通过 `future.set_result()` 设置结果后用 `time.sleep(0.1)` 等待 `add_done_callback` 执行。这是基于时序的同步方式。
- **影响**：CI 环境下 GC 暂停或调度延迟可能导致回调在 100ms 内未完成，产生间歇性测试失败。
- **建议修复方向**：用 `threading.Event` 替代：在回调中 set event，测试中 `event.wait(timeout=2)` 替代 sleep。

### [43] _make_executor 辅助方法在 5 个测试类中重复定义

- **模块**：测试
- **文件**：`tests/test_services/test_task_executor_fix.py:335-419`
- **分类**：⚪ 代码质量
- **描述**：5 个测试类各自定义了完全相同的 `_make_executor` 方法（创建带 mock 依赖的 TaskExecutor），总计约 80 行重复代码。
- **影响**：修改 TaskExecutor 构造参数时需要同时更新 5 处，容易遗漏。
- **建议修复方向**：将 `_make_executor` 提取为模块级函数或移入 conftest.py 作为 fixture。

### [44] 多线程测试的 mock side_effect 计数器非线程安全

- **模块**：测试
- **文件**：`tests/test_integration/test_login_flow.py:595-600`
- **分类**：⚪ 代码质量
- **描述**：`test_multiple_threads_competing_for_login` 使用 `call_count = [0]` 配合 `side_effect` 函数模拟 orchestrator 的去重行为。`call_count[0] += 1` 不是原子操作（Python 字节码层面包含 LOAD、ADD、STORE 三步），且 `if call_count[0] == 1` 的读取与递增之间存在 TOCTOU 窗口。
- **影响**：极端调度情况下多个线程可能同时读到 `call_count[0]==0`，导致断言失败。CPython GIL 使实际触发概率极低。
- **建议修复方向**：使用 `threading.Lock` 保护 `call_count` 的读写，或使用 `itertools.count` 的 `next()` 原子操作替代。

### [45] _capture_login_completion 的 task_executor 参数从未使用

- **模块**：测试
- **文件**：`tests/test_integration/test_login_integration_extended.py:36-73`
- **分类**：⚪ 代码质量
- **描述**：`_capture_login_completion` 辅助函数接受 `task_executor` 参数但函数体内从未引用它。所有调用点都传入了该参数，使读者误以为该参数在内部有用途。
- **影响**：增加代码理解成本。
- **建议修复方向**：移除 `task_executor` 参数，更新所有调用点。

---

## 已知问题验证结果

以下 MEMORY 中记录的已知问题在本次审查中进行了验证：

| 已知问题 | 状态 | 说明 |
|----------|------|------|
| DI 容器通过直接赋值私有属性注入依赖 | ✅ 已修复 | 现在使用 `set_orchestrator()` 等公共方法 |
| debug_service.start() 对 frozen model 调用 .get() | ✅ 已修复 | 使用标准属性访问 |
| proxy/app_port RuntimeConfig 无字段 | ✅ 已修复 | `schemas.py` 已有 `proxy` 和 `app_port` 字段 |
| save_config 回滚是死代码 | ✅ 已修复 | 正确检查 `reload_fn()` 返回的 `(ok, msg)` 元组 |
| FIELD_NAMES 3 处键名过期 | ✅ 已修复 | 逐一比对了 FIELD_NAMES 与所有 Pydantic 模型字段 |
| playwright_worker stealth 注入在 page 创建之后 | ✅ 已修复 | 改为 context 级 `add_init_script()`，时序正确 |
| engine._handle_login 阻塞引擎线程 | ❌ 仍存在 | 见 Critical [1] |
| CompositeCancelEvent.wait() 未覆盖 | ❌ 仍存在 | 见 Minor [1] |

## 审查覆盖范围

| Review Unit | 模块 | 焦点 | 优先级 | 文件数 |
|-------------|------|------|--------|--------|
| service-async | 服务层 | async/await 正确性、取消机制、并发竞态 | P0 | 6 |
| tasks-system | 任务系统 | JSON 验证、模板注入、步骤执行、脚本运行 | P0 | 8 |
| workers-playwright | 工作线程 | Actor 模型线程安全、资源泄漏 | P0 | 4 |
| utils-crypto | 工具模块 | 加密安全、密钥管理、原子写入 | P0 | 3 |
| api-routes | API 路由层 | 路由注册、输入验证、错误处理 | P1 | 8 |
| service-core | 服务层 | 业务逻辑、DI 生命周期、配置构建链 | P1 | 8 |
| network-probes | 网络检测 | 探测超时、httpx 单例线程安全 | P1 | 3 |
| network-decision | 网络检测 | 状态机、跨平台网关/SSID 检测 | P1 | 2 |
| frontend-vue | 前端 | Vue 状态、API 错误处理、WS 重连 | P1 | 8+ |
| starter-go | Go 启动器 | 下载安全、镜像 fallback、跨平台 | P2 | 2 |
| utils-general | 工具模块 | 日志、Shell 安全、进程管理 | P2 | 8 |
| test-coverage | 测试 | Mock 正确性、集成覆盖、异步稳定性 | P2 | 8 |

## 附注

- 本报告仅列出发现，未执行任何修复
- 建议按 Critical → Major → Minor 顺序处理
- 部分问题可能需要跨模块协同修复（如 engine._handle_login 阻塞问题同时影响引擎层和 API 层）
- 5 个 MEMORY 中记录的已知问题已在近期修复，配置系统重构（v3→v4）的质量较高
- 所有审查已排除 not-to-do.md 中列出的设计决策和单桌面用户场景下极难触发的问题
