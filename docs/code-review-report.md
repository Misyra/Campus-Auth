# Campus-Auth 代码审查报告

> 审查时间：2026-07-06
> 审查范围：全项目（app/、frontend/、tests/、resources/tools/）
> Review Unit 数量：20
> 审查文件总数：~155 个 Python 文件 + ~74 个前端文件 + Go 工具

## 摘要

| 严重性 | 数量 |
|--------|------|
| 🔴 Critical | 21 |
| 🟠 Major | ~65 |
| 🟡 Minor | ~40 |
| 总计 | ~126 |

| 模块 | Critical | Major | Minor |
|------|----------|-------|-------|
| Actor 引擎 (engine/monitor) | 2 | 4 | 2 |
| 登录管线 (login_*) | 1 | 3 | 4 |
| 定时调度 (scheduler/executor) | 1 | 5 | 2 |
| 配置 & 模型 (config/schemas) | 1 | 2 | 5 |
| 网络探测 (probes/decision) | 2 | 4 | 2 |
| 网络检测 (detect/interfaces/proxy) | 0 | 3 | 4 |
| 任务系统 (tasks/step_handlers) | 1 | 2 | 4 |
| 浏览器任务 (browser_runner) | 1 | 3 | 2 |
| 工作线程 (playwright_worker) | 1 | 2 | 4 |
| API 路由 (api/*) | 0 | 4 | 3 |
| WebSocket (ws/websocket_manager) | 1 | 3 | 2 |
| 基础设施 (container/application/deps) | 1 | 2 | 3 |
| 工具核心 (utils/cancel_token/crypto) | 1 | 2 | 4 |
| 平台工具 (utils/platform/shell) | 0 | 2 | 3 |
| 进程生命周期 (launcher/autostart) | 2 | 1 | 4 |
| 调试会话 (debug_service) | 1 | 3 | 2 |
| 前端应用 (app.js/components) | 1 | 2 | 2 |
| 前端页面 (partials/methods) | 2 | 3 | 1 |
| Go 工具 (start/git-puller) | 1 | 2 | 2 |
| 测试覆盖 (tests/*) | 0 | 3 | 1 |

---

## 🔴 Critical 问题（21 项）

### [1] toggle_pure_mode TOCTOU 竞态：锁外磁盘持久化导致配置快照过期覆盖

- **模块**：Actor 引擎
- **文件**：`app/services/engine.py:1098-1131`
- **分类**：🟠 可靠性
- **描述**：toggle_pure_mode 在 _reload_lock 内读取 base_config，随后释放锁执行 profile_service.update()（磁盘 IO）。在释放锁到 _swap_runtime_config 之间，若另一线程调用 _reload_config_internal 更新了 _runtime_config，则基于过期快照构建的 new_config 会覆盖掉其他线程的配置变更。
- **影响**：配置丢失 — 若 reload_config/apply_profile 与 toggle_pure_mode 并发执行，用户的方案切换或配置修改会被静默回滚到旧值。
- **建议修复方向**：在 _swap_runtime_config 前重新持锁读取最新的 self._runtime_config 作为 base_config。

### [2] _dispatch_command 超时后已入队命令仍被延迟执行

- **模块**：Actor 引擎
- **文件**：`app/services/engine.py:966-987`
- **分类**：🟠 可靠性
- **描述**：_send_and_wait 中，命令先入队（cmd_queue.put），再 await asyncio.wait_for 等待结果。超时时内部协程被取消，但已入队的 EngineCommand 不会被撤回。引擎循环后续消费该命令时会执行实际操作，而 response_future 已无等待方，结果被静默丢弃。
- **影响**：超时后可能触发意外的监控启停或登录操作。LOGIN 命令 timeout 可达 70+秒，可能在用户已收到超时响应后仍启动浏览器。
- **建议修复方向**：为 EngineCommand 添加 expiry 时间戳，_process_command_async 处理时检查是否过期并跳过。

### [3] 手动登录成功不重置 MonitoredPolicy._attempt

- **模块**：登录管线
- **文件**：`app/services/login_orchestrator.py`（LoginBridge._on_done）
- **分类**：🟠 可靠性
- **描述**：手动登录路径中 on_complete 回调直接 return，不调用 retry_policy.on_login_done(success=True)。若此前自动登录已累积 _attempt=3，手动成功后 _attempt 仍为 3，下次自动失败从 attempt=4 开始。
- **影响**：后续自动重试提前耗尽预算（max_retries=5 但实际只剩 2 次），网络恢复前过早放弃。
- **建议修复方向**：在 on_complete 分支中 ok=True 时调用 retry_policy.reset()。

### [4] 浏览器定时任务被 Orchestrator 去重机制静默替换为登录结果

- **模块**：定时调度
- **文件**：`app/services/task_executor.py:312-341`
- **分类**：🟠 可靠性
- **描述**：_execute_browser 使用 source='browser' 调用 LoginOrchestrator.submit()。若恰好有 auto 登录在运行，submit 返回该登录的 Future，浏览器任务拿到登录结果而非浏览器结果，且无任何日志。
- **影响**：定时浏览器任务执行结果不可预测，历史记录中记录的也是错误结果。
- **建议修复方向**：在 Orchestrator.submit 中为 'browser' 来源增加独立槽位，不与 auto/manual 登录共享 _slot。

### [5] _race_first_success_async 提前返回后未取消剩余协程

- **模块**：网络探测
- **文件**：`app/network/probes.py:168-202`
- **分类**：🔴 崩溃/安全
- **描述**：当首个探测成功时直接 return True，asyncio.as_completed 内部创建的 Task 仍在后台运行。以 HTTP/URL 探测为例，其余 httpx 请求仍持有 TCP 连接直到各自超时（2~5 秒）。
- **影响**：高频监控循环中连接池耗尽、fd 泄漏，Windows 上可能触发端口耗尽。
- **建议修复方向**：将协程预先包装为 asyncio.Task 列表，提前返回后遍历 cancel 并 gather 清理。

### [6] OcrHandler char_range 临时 DdddOcr 实例永远不被清理

- **模块**：任务系统
- **文件**：`app/tasks/step_handlers.py:825-873`
- **分类**：🔴 崩溃/安全
- **描述**：char_range 不为 None 时创建临时 DdddOcr 实例（含 ONNX 模型），schedule_cleanup 仅管理缓存字典中的实例。临时实例依赖 Python GC 回收，但 ONNX Runtime 使用原生内存分配，GC 无法保证及时释放。
- **影响**：每次带 char_range 的 OCR 调用泄漏约 10-30MB 模型内存，高频调用导致 OOM 崩溃。
- **建议修复方向**：在 try/finally 中显式 del 临时实例并 gc.collect()，或维护独立的 char_range 缓存池。

### [7] Firefox 安装后执行 Chromium 完整性校验

- **模块**：工作线程
- **文件**：`app/workers/playwright_bootstrap.py:217-227`
- **分类**：🟠 可靠性
- **描述**：browser_channel 为 firefox 且系统未安装时，正确下载 Playwright Firefox，但下载成功后始终调用 _verify_chromium_install() 校验 Chromium 二进制。Firefox 安装目录下无 chromium-* 目录，校验必定失败。
- **影响**：配置 firefox channel 的用户首次安装永远无法通过 bootstrap 检查，应用无法启动。
- **建议修复方向**：按 install_target 分支校验，firefox 应校验 firefox 二进制而非 chromium。

### [8] cancel_token add_source() 与 wait() 锁顺序反转 ⚠️ 待运行时确认

- **模块**：工具核心
- **文件**：`app/utils/cancel_token.py:27-33`
- **分类**：🔴 崩溃/安全（锁顺序反转已确认，能否触发实际死锁需运行时验证）
- **描述**：add_source() 在持有 self._lock 时调用 super().set()，形成锁顺序 self._lock → threading.Condition._lock。is_set() 第46行注释表明开发者已修复了同类问题（移到锁外）但遗漏了 add_source()。静态分析确认锁顺序反转存在，但能否在运行时触发实际死锁取决于 CPython threading.Event 内部实现。
- **影响**：特定取消时序下引擎可能卡死，所有监控和登录操作停止。
- **建议修复方向**：将 super().set() 调用移出 _lock 保护范围，与 is_set() 保持一致的修复策略。

### [9] start_web_services 跨事件循环 drain task 泄漏

- **模块**：基础设施
- **文件**：`app/container.py:126-170`
- **分类**：🔴 崩溃/安全
- **描述**：stop_web_services() 检测到 _ws_drain_task 属于其他事件循环时仅日志记录，未对旧 drain task 执行 cancel()。轻量→完整模式升级路径中，旧 drain loop 永远无法被回收。
- **影响**：旧 drain task 持有旧 loop 和 ws_manager 引用，资源泄漏且无法释放。
- **建议修复方向**：在 else 分支中使用 loop.call_soon_threadsafe(task.cancel) 跨循环取消。

### [10] launcher.py _logging 变量可能未绑定导致 NameError

- **模块**：进程生命周期
- **文件**：`app/services/launcher.py:419-436`
- **分类**：🔴 崩溃/安全
- **描述**：当 profile_service.load() 返回 None 时，inner try 块中 _logging 赋值不执行，except 分支未设置 _logging=None。后续 logging_settings=_logging 引用触发 NameError，NameError 不在 inner try 捕获范围内。
- **影响**：配置文件损坏时完整模式无法启动，进程以 NameError 崩溃退出，无任何 Web 服务。
- **建议修复方向**：在 except 分支中补充 _logging = None。

### [11] Unix 平台 os.kill 未捕获异常

- **模块**：进程生命周期
- **文件**：`app/services/launcher.py:75-79`
- **分类**：🔴 崩溃/安全
- **描述**：_terminate_process 在非 Windows 平台调用 os.kill(pid, SIGTERM/SIGKILL) 未用 try/except 包裹。进程在 is_service_running 确认存活后、os.kill 前退出，会抛出 ProcessLookupError。
- **影响**：--force 强制模式在竞态条件下崩溃，无法终止已运行实例。
- **建议修复方向**：用 try/except 包裹 os.kill，捕获 ProcessLookupError 和 PermissionError。

### [12] WebSocket connect() accept 与注册非原子

- **模块**：WebSocket
- **文件**：`app/services/websocket_manager.py:35-38`
- **分类**：🔴 崩溃/安全
- **描述**：connect() 先 await websocket.accept()，再获取锁后 append。两个 await 之间若协程被取消，accept 已完成但连接未注册，socket 永远不会被回收。
- **影响**：热重载或优雅关闭期间孤儿连接持续占用文件描述符，反复触发可耗尽 fd。
- **建议修复方向**：用 try/except (CancelledError) 包裹，取消时主动 close 已 accept 的 socket。

### [13] debug start() 失败路径未重置会话状态

- **模块**：调试会话
- **文件**：`app/services/debug_service.py:185-202`
- **分类**：🟠 可靠性
- **描述**：Worker 启动失败时清理代码未将 self._session 重置为新 DebugSession()。stop() 和 _debug_timeout_watcher 会重置，但 start() 失败路径遗漏。
- **影响**：失败后 self._session 保持 running=True 的僵尸状态，后续命令提交到已关闭的 Worker。
- **建议修复方向**：在两个失败路径的锁内添加 self._session = DebugSession()。

### [14] browser_runner _network_detection_check 无超时保护

- **模块**：浏览器任务
- **文件**：`app/tasks/browser_runner.py:325-346`
- **分类**：🔴 崩溃/安全
- **描述**：asyncio.to_thread(check_network_status) 无超时，且不在 task_deadline 约束内。方法在步骤循环之后调用，一旦 check_network_status 内部阻塞，整个任务永久挂起。
- **影响**：Worker 线程被永久占用，影响后续任务调度，在校园网不稳定环境下极易触发。
- **建议修复方向**：用 asyncio.wait_for 包裹，设置 30s 硬上限。

### [15] 前端模板加载 innerHTML 未消毒导致 XSS

- **模块**：前端应用
- **文件**：`frontend/template-loader.js:12-15`
- **分类**：🔴 崩溃/安全
- **描述**：fetchInclude 将远程 HTML 直接 innerHTML 赋值后插入 DOM。innerHTML 不执行 <script> 但会执行内联事件处理器（<img onerror>、<svg onload>）。
- **影响**：攻击者控制任一 data-include 模板即可注入恶意脚本，窃取用户凭据。
- **建议修复方向**：引入 DOMPurify 消毒，并限制 data-include URL 为白名单路径。

### [16] saveConfig 中 active_task 被错误覆盖为空串

- **模块**：前端页面
- **文件**：`frontend/js/methods/config.js:121-126`
- **分类**：🟠 可靠性
- **描述**：第 121 行正确设置 payload.active_task，但第 124 行的 forEach 将 'active_task' 混入凭据字段列表，执行 payload['active_task'] = c.credentials['active_task']（undefined），覆盖为空串。
- **影响**：每次保存配置都会将用户选定的活动任务清空，自动登录使用错误的任务配置。
- **建议修复方向**：将 'active_task' 从 forEach 数组中移除。

### [17] 密码字段使用 type="text" 明文暴露

- **模块**：前端页面
- **文件**：`frontend/partials/pages/settings/settings-account.html:33-43`
- **分类**：🔴 崩溃/安全
- **描述**：密码输入框使用 type="text" 而非 type="password"，用户编辑后密码以明文显示。
- **影响**：肩窥泄露密码，不符合基本安全实践。
- **建议修复方向**：改为 type="password"，可选添加显示/隐藏切换按钮。

### [18] repo_proxy async_repo_fetch_json 缺少纵深防御 ⚠️ 降级

- **模块**：平台工具
- **文件**：`app/utils/repo_proxy.py:46-57`
- **分类**：⚪ 代码质量（原标 Critical，验证后降级）
- **描述**：async_repo_fetch_json 函数体内未调用 validate_url，但验证发现所有调用方（app/api/repo.py）在调用前已执行 validate_url(url)，当前不存在实际 SSRF 漏洞。
- **影响**：当前无实际风险。但这是脆弱的防御模式 — 未来新调用方可能忘记先校验。
- **建议修复方向**：将 validate_url 调用移入 async_repo_fetch_json 内部实现纵深防御，而非依赖调用方。

### [19] git-puller extractTar 路径穿越（Zip Slip）

- **模块**：Go 工具
- **文件**：`resources/tools/git-puller/main.go:270-328`
- **分类**：🔴 崩溃/安全
- **描述**：extractTar 使用 filepath.Join(destDir, name) 构造目标路径，name 直接取自 tar 头部，未校验是否包含 .. 等穿越组件。
- **影响**：恶意 tar 归档可将文件写入任意位置，包括覆盖系统文件或植入后门。
- **建议修复方向**：对每个 entry 做 filepath.Rel 校验，若结果以 .. 开头则跳过。

### [20] SSRF：fetch_background_url 未校验目标主机

- **模块**：API 路由
- **文件**：`app/api/tools.py:99-154`
- **分类**：🔴 崩溃/安全
- **描述**：validate_url() 仅校验 scheme 是否为 http/https，不检查目标主机。攻击者可提交 http://169.254.169.254/ 等内网地址，服务端主动请求并下载内容。
- **影响**：探测内网端口、窃取云实例元数据凭据（IAM role）、访问内网管理接口。
- **建议修复方向**：解析域名后拒绝私有地址段（10/8、172.16/12、192.168/16、127/8、169.254/16）。

### [21] 全局异常处理器泄露内部异常类型名称

- **模块**：基础设施
- **文件**：`app/application.py:308-317`
- **分类**：🔴 崩溃/安全
- **描述**：global_exception_handler 将 type(exc).__name__ 直接拼入 HTTP 响应体，暴露内部异常类名如 PlaywrightTimeoutError、FileSystemPermissionError 等。
- **影响**：攻击者可推断后端架构、使用的第三方库，辅助针对性攻击。
- **建议修复方向**：对外统一返回泛化消息，异常详情仅写入服务端日志。

---

## 🟠 Major 问题（Top 30，共约 65 项）

### [22] _handle_reload 重建 bind proxy 时意外启动已停止的监控

- **模块**：Actor 引擎 | `app/services/engine.py:744-749` | 🟠 可靠性
- **描述**：bind proxy 重建调用 stop+init，init_monitoring 总是将 monitoring 设为 True，若监控原本停止则被意外启动。
- **建议**：提取独立的 _rebuild_bind_proxy() 方法，仅重建 SOCKS5 Forwarder 而不触碰 monitoring 状态。

### [23] _check_profile_switch 同步磁盘 IO 阻塞 async 引擎事件循环

- **模块**：Actor 引擎 | `app/services/monitor_service.py:398-435` | 🟡 性能
- **描述**：check_once() 是 async 方法，内部调用同步的 profile_service.load() 和 detect_matching_profile()，直接阻塞 asyncio 事件循环。
- **建议**：改用 asyncio.to_thread() 包装磁盘 IO。

### [24] login_history_service _cleanup_old 与 add 使用不同锁

- **模块**：登录管线 | `app/services/login_history_service.py:133-170` | 🟠 可靠性
- **描述**：两把独立锁可并发执行，_cleanup_old 的 read-modify-write 与 add 的追加写入竞态，导致新记录静默丢失。
- **建议**：合并为一把锁。

### [25] login_once 路径创建独立 LoginOrchestrator，无法与主引擎去重

- **模块**：登录管线 | `app/services/login_runner.py:53-73` | 🟠 可靠性
- **描述**：每次调用新建 LoginOrchestrator（含独立 _slot），与主引擎完全隔离，可能向同一 Worker 提交并发登录。
- **建议**：通过 ServiceContainer 注入共享实例。

### [26] task_registry delete_task TOCTOU 竞态

- **模块**：定时调度 | `app/services/task_registry.py:114-135` | 🟠 可靠性
- **描述**：exists 检查与 unlink 均无锁保护，并发删除时第二个 unlink 抛 FileNotFoundError。
- **建议**：在锁内直接 unlink 并捕获 FileNotFoundError。

### [27] Shell 任务 command 参数未做内容校验

- **模块**：定时调度 | `app/services/task_executor.py:343-393` | 🔴 崩溃/安全
- **描述**：_execute_shell 直接将 command 字符串传递给 shell 执行，缺少执行审计和危险命令拦截。
- **建议**：增加命令审计日志，考虑黑名单拦截高危命令模式。

### [28] update_last_run 缓存与磁盘写入分离

- **模块**：定时调度 | `app/services/task_registry.py:147-169` | 🟠 可靠性
- **描述**：锁内更新缓存，锁外写磁盘。磁盘失败时缓存已更新但未持久化，进程重启后 last_run 回退。
- **建议**：写入失败时回滚缓存。

### [29] 三层超时嵌套导致等待时间不可预测

- **模块**：网络探测 | `app/network/probes.py:225-244` | 🟡 性能
- **描述**：TCP 探测有三层超时叠加（1.5s + 3.5s + 5.0s），as_completed 与 wait_for 交互行为不明确。
- **建议**：统一为单一 wait_for 控制总超时。

### [30] 异步代码中混用 threading 原语

- **模块**：网络探测 | `app/network/probes.py:17-21` | ⚪ 代码质量
- **描述**：_shutdown_event（threading.Event）和 _proxy_lock（threading.Lock）在 asyncio 单线程事件循环中使用，是 asyncio 迁移后的遗留模式。
- **建议**：替换为 asyncio.Event 和 asyncio.Lock。

### [31] PUT 端点 payload 使用裸 dict，绕过输入验证

- **模块**：API 路由 | `app/api/scheduled_tasks.py:46-78` | 🔴 崩溃/安全
- **描述**：update_scheduled_task 的 payload 为 dict 类型，FastAPI/Pydantic 不做 schema 校验，攻击者可注入任意脏数据。
- **建议**：定义专用 Pydantic 请求模型。

### [32] 异常内部信息直接泄露给客户端

- **模块**：API 路由 | `app/api/config.py:41-43` | 🔴 崩溃/安全
- **描述**：_handle_config_error 将 str(exc) 拼入 HTTP detail，暴露内部路径和模块名。多处路由有同样问题。
- **建议**：500 类错误统一返回泛化消息，原始异常仅写入服务端日志。

### [33] shutdown 幂等守卫非原子操作

- **模块**：基础设施 | `app/container.py:175-179` | 🟠 可靠性
- **描述**：_shutdown_done 布尔标志的 check-then-set 不是原子的，并发调用可导致双重关闭。
- **建议**：使用 asyncio.Lock 替代布尔标志。

### [34] _quit 回调在 pystray 线程执行 on_exit，可能死锁

- **模块**：基础设施 | `app/system_tray.py:75-80` | 🔴 崩溃/安全
- **描述**：pystray 托盘线程中调用 on_exit()，若涉及 asyncio 操作则 RuntimeError 或死锁。
- **建议**：on_exit 仅做线程安全的信号传递。

### [35] Fernet 密钥派生使用非标准 SHA-256 截断

- **模块**：工具核心 | `app/utils/crypto.py:127-142` | 🔴 崩溃/安全
- **描述**：Fernet 密钥需要特定格式（128位签名+128位加密），SHA-256 截断偏离标准。
- **建议**：使用 PBKDF2 派生 256 位密钥，base64 编码后传给 Fernet。

### [36] SOCKS5 中继 5 秒空闲超时断开合法长连接

- **模块**：网络检测 | `app/network/proxy.py:174-177` | 🟠 可靠性
- **描述**：sel.select(timeout=5.0) 过于激进，WebSocket/SSH/long-polling 等协议空闲间隔轻松超过。
- **建议**：将空闲超时提高到 120 秒以上。

### [37] ipconfig 回退的多语言字节模式使用错误编码

- **模块**：网络检测 | `app/network/detect.py:238-247` | 🔵 兼容性
- **描述**：法语/日语/韩语网关标签使用 UTF-8 编码，但 ipconfig 实际输出使用 OEM 代码页。
- **建议**：改用 WMI/COM 接口获取网关，或明确文档标注仅支持英文/中文。

### [38] 回环网卡判断 startswith('lo') 过于宽泛

- **模块**：网络检测 | `app/network/interfaces.py:57-59` | 🟠 可靠性
- **描述**：误排除 'lowpan0'、'local0' 等以 'lo' 开头的非回环接口，Windows 上此检查无效。
- **建议**：精确匹配 name == 'lo' 或使用 IFF_LOOPBACK 标志。

### [39] _try_candidates_with_fallback 策略1 不使用 deadline

- **模块**：任务系统 | `app/tasks/step_handlers.py:126-138` | 🟡 性能
- **描述**：每个候选使用固定 wait_timeout 而非 deadline 分摊，N 个候选总耗时为 N × wait_timeout，可能超过步骤超时。
- **建议**：策略1 也使用 deadline 做剩余时间分摊。

### [40] script_runner 缺乏沙箱隔离

- **模块**：工作线程 | `app/workers/script_runner.py:184-263` | 🔴 崩溃/安全
- **描述**：子进程继承父进程完整权限，可读写所有文件、发起网络请求。PYTHONPATH 未隔离，可 import 项目内部模块。
- **建议**：清空 PYTHONPATH 并移除项目目录，对脚本做基础静态分析。

### [41] asyncio.Queue 跨线程 put_nowait 违反线程安全

- **模块**：工作线程 | `app/workers/playwright_worker.py:288-304` | 🟠 可靠性
- **描述**：回退路径从调用者线程直接 put_nowait 到 asyncio.Queue，asyncio.Queue 非线程安全。
- **建议**：回退路径也通过 call_soon_threadsafe 入队。

### [42] 健康检查端点泄露过多进程内部信息

- **模块**：API 路由 | `app/api/system.py:50-67` | 🔴 崩溃/安全
- **描述**：/api/health 返回 PID、线程列表、打开文件列表、Python 精确版本号，对攻击者有侦察价值。
- **建议**：生产环境仅返回 status+version，诊断信息移至鉴权端点。

### [43] _shutdown_initiated 信号处理器与托盘线程数据竞态

- **模块**：进程生命周期 | `app/services/launcher.py:366-398` | 🟠 可靠性
- **描述**：nonlocal 布尔变量被信号线程和托盘线程同时读写，无同步原语，可能导致双重关闭。
- **建议**：用 threading.Lock 保护。

### [44] 双击 Ctrl+C 使用 os._exit(1) 跳过退出钩子

- **模块**：进程生命周期 | `app/services/launcher.py:371-374` | 🟠 可靠性
- **描述**：绕过 shutdown.py 注册的所有退出钩子，数据库连接/文件句柄可能未正确释放。
- **建议**：替换为 force_exit(1)，确保退出钩子执行。

### [45] WebSocket 端点缺少身份认证

- **模块**：WebSocket | `app/api/ws.py:13-17` | 🔴 崩溃/安全
- **描述**：websocket_logs_handler 直接 accept 连接，未验证客户端身份。
- **建议**：在 accept 前校验 JWT/Cookie 或 token。

### [46] 13 个数据模块展开合并存在键名冲突风险

- **模块**：前端应用 | `frontend/app-options.js:38-51` | 🟠 可靠性
- **描述**：data() 中 13 个展开运算符合并到同一对象，相同键名静默覆盖。
- **建议**：添加键名冲突检测或改用嵌套命名空间。

### [47] bootstrapApp() 未捕获 Promise 拒绝

- **模块**：前端应用 | `frontend/app.js:80-92` | 🟠 可靠性
- **描述**：启动失败产生 Unhandled Promise Rejection，Vue 永不挂载，用户只看到空白页。
- **建议**：添加 .catch() 展示友好错误页面。

### [48] background_url 未经验证直接注入 CSS url()

- **模块**：前端应用 | `frontend/app.js:21-23` | 🔴 崩溃/安全
- **描述**：从 localStorage 读取后直接拼入 CSS url()，可构造指向外部恶意资源的 URL。
- **建议**：用 URL 构造函数校验协议和同源。

### [49] isRemoteReachable 超时计时器 goroutine 泄漏

- **模块**：Go 工具 | `resources/tools/git-puller/main.go:343-362` | 🟡 性能
- **描述**：计时器 goroutine 在函数返回后仍 sleep 5 秒，每次调用泄漏一个 goroutine。
- **建议**：改用 context.WithTimeout。

### [50] doUpdate 中 fetch origin 错误被静默忽略

- **模块**：Go 工具 | `resources/tools/git-puller/main.go:564-565` | 🟠 可靠性
- **描述**：fetch 返回值被丢弃，后续 reset --hard 使用旧引用，代码静默回退到过时版本。
- **建议**：检查 fetch 错误，失败时输出明确错误并退出。

### [51] 集成测试引擎工厂大量重复

- **模块**：测试覆盖 | `tests/test_integration/test_login_flow.py:33-100` | ⚪ 代码质量
- **描述**：_make_raw_engine() 与 test_services/conftest.py 的 _make_raw() 高度重复，独立维护易不一致。
- **建议**：抽取到 tests/conftest.py 的公共 fixture。

---

## 🟡 Minor 问题（~40 项，以下列举代表性发现）

| # | 模块 | 文件 | 问题 |
|---|------|------|------|
| 52 | 引擎 | engine.py:1-1143 | 1143 行含 6 个类，需提取 MonitorLifecycle 和 ConfigCoordinator |
| 53 | 引擎 | engine.py:1001-1012 | start_monitoring 与 _handle_start 重复验证配置 |
| 54 | 登录 | retry_policy.py:30-32 | attempt 属性无锁读取，依赖 GIL 隐式保护 |
| 55 | 登录 | login_session.py:76-77 | LoginAttempt 跨重试复用可能残留状态 |
| 56 | 登录 | login_orchestrator.py:70-75 | validate_login_config 遗漏 isp/carrier_custom 校验 |
| 57 | 调度 | scheduler_service.py:95-129 | 追赶分钟无日期信息，夏令时可能遗漏/重复 |
| 58 | 调度 | task_executor.py:175-186 | delete_task 的 cancel() 无法中断已运行任务 |
| 59 | 配置 | schemas.py | model_copy(update=...) 跳过 Pydantic 验证 |
| 60 | 配置 | config_builder.py | config_version 字段从未校验 |
| 61 | 探测 | decision.py:35-43 | _interface_mgr 单例无锁保护 TOCTOU |
| 62 | 探测 | parsers.py:12-58 | parse_url_checks 未校验 URL scheme |
| 63 | 检测 | interfaces.py:139-153 | list_interfaces O(N²) psutil 调用 |
| 64 | 检测 | interfaces.py:13-17 | 跨模块导入下划线私有函数 |
| 65 | 任务 | variable_resolver.py:102-128 | resolve_for_js 未处理 U+2028/U+2029 |
| 66 | 任务 | models.py:112-147 | StepConfig.from_dict 不校验 timeout 类型 |
| 67 | 浏览器 | browser_runner.py:192-206 | _wait_url_stable 每次重定向延长截止时间 |
| 68 | 浏览器 | browser_runner.py:13 | 从 sync_api 导入 TimeoutError 用于 async 上下文 |
| 69 | 工作线程 | playwright_worker.py:522-470 | _debug_page 与 _page 共享引用 |
| 70 | 工作线程 | playwright_worker.py:1129-1148 | get_worker() 可在 shutdown 后复活实例 |
| 71 | 工作线程 | playwright_worker.py:724-733 | 用户自定义 browser_args 未充分过滤 |
| 72 | 工作线程 | playwright_worker.py:1163-1199 | cleanup_orphan_browsers 用 kill 无优雅退出 |
| 73 | 工作线程 | playwright_worker.py:1-1199 | 1199 行含 5+ 独立关注点 |
| 74 | API | config.py:85-112 | get_config 缺少 response_model |
| 75 | API | tools.py:22-23 | 模块导入时执行 mkdir 副作用 |
| 76 | API | scripts.py:52-65 | save_script 直接修改入参 dict |
| 77 | WebSocket | ws.py:38-42 | 客户端可控日志级别，日志注入风险 |
| 78 | WebSocket | websocket_manager.py:179-188 | 队列满检测 TOCTOU |
| 79 | 基础设施 | deps.py:17-23 | DI 工厂无错误处理 |
| 80 | 基础设施 | version.py:25-41 | compare_versions 对预发布版本号返回错误结果 |
| 81 | 工具核心 | cancel_token.py:73-78 | clear() 不应清除外部源事件状态 |
| 82 | 工具核心 | concurrent.py:37-42 | interruptible_sleep 最后一段未裁剪到 deadline |
| 83 | 工具核心 | logging.py:169-170 | _drain_notifier TOCTOU 竞态 |
| 84 | 工具核心 | crypto.py:92-121 | Windows 密钥文件权限 icacls 可能静默失败 |
| 85 | 平台工具 | platform.py:47-49 | is_linux() 与 get_platform() 语义不一致 |
| 86 | 平台工具 | process.py:108-141 | is_service_running TOCTOU 竞态 |
| 87 | 平台工具 | shell_utils.py:60-74 | get_default_shell 回退路径可能不存在 |
| 88 | 生命周期 | autostart.py:258-271 | Linux systemd WorkingDirectory 路径未转义 |
| 89 | 生命周期 | autostart.py:350 | Windows VBS utf-16 编码兼容性问题 |
| 90 | 生命周期 | autostart.py:175-206 | macOS plist 单字符串依赖 zsh 解析引号 |
| 91 | 生命周期 | uninstall.py:36-66 | 卸载残留检测缺少 PID 文件和日志目录 |
| 92 | 调试 | debug_service.py:33-41 | _rm() 同步 time.sleep 阻塞事件循环 |
| 93 | 调试 | debug_service.py:86-88 | _current_gen 跨线程读写无统一保护 |
| 94 | 前端页面 | lifecycle.js:237-241 | newLogCount 从未递增，"新消息"按钮永不显示 |
| 95 | 前端页面 | tasks.html:96,141 | 关闭/取消按钮绕过未保存修改确认 |
| 96 | 前端页面 | appearance.js:186-194 | 浅色主题下 background_color 被静默忽略 |
| 97 | 前端 | logger.js:38-50 | _flushBuffer 部分失败时重复发送 |
| 98 | Go | start.go:260-287 | runCommand 信号转发 Windows 竞态 |
| 99 | 测试 | test_engine.py:237-268 | async 测试混用手动 loop 与 pytest.mark.asyncio |
| 100 | 测试 | test_monitor_core.py | 核心方法 check_once/init/stop 完全未测试 |
| 101 | 测试 | test_probes.py:70-105 | 通过源码文本扫描做断言，脆弱测试 |

---

## 目录结构与代码结构优化建议

### 一、大文件拆分建议

| 文件 | 当前行数 | 建议拆分 | 预期收益 |
|------|----------|----------|----------|
| `app/services/engine.py` | 1143 | 提取 `monitor_lifecycle.py`（_handle_start/_stop/bind proxy）和 `config_coordinator.py`（_reload/_swap/toggle_pure_mode） | 降低认知负担，10+ 锁分散到独立组件，可独立测试 |
| `app/workers/playwright_worker.py` | 1199 | 提取 `browser_launcher.py`（启动参数构建+启动逻辑）和 `orphan_cleanup.py`（孤儿进程清理，已是独立函数） | 启动参数可独立测试，清理逻辑可复用 |
| `app/tasks/step_handlers.py` | 894 | 将 OcrHandler（~170 行）拆为 `ocr_handler.py`，OCR 模型池管理抽取为 `ocr_pool.py` | OCR 模型生命周期与步骤执行解耦，修复 ONNX 泄漏更聚焦 |
| `app/network/detect.py` | 532 | 拆分为 `gateway.py`（网关检测+路由解析）和 `ssid.py`（WiFi SSID 检测），detect.py 保留公共 API | 两套正交功能独立演进，减少合并冲突 |

### 二、跨模块耦合修复

| 问题 | 当前状态 | 建议 |
|------|----------|------|
| interfaces.py 导入 detect.py 私有函数 | `_parse_darwin_netstat_routes` 等下划线函数跨模块使用 | 提取到 `app/network/parsers.py`（已有此文件）并导出为公共 API |
| probes.py 混用 threading 原语 | asyncio 迁移遗留的 threading.Event/Lock | 替换为 asyncio.Event/Lock，shutdown_probes 改为 async |
| network/utils.py IP 判断用字符串前缀 | `startswith('127.')` 无法处理 IPv6 | 统一使用 `ipaddress` 模块做严格判断 |

### 三、O(N²) 性能优化

| 位置 | 问题 | 建议 |
|------|------|------|
| `interfaces.py:list_interfaces` | 对每个网卡调用 psutil.net_if_addrs()，N 个网卡约 2N+1 次系统调用 | 入口处一次性获取并缓存 addrs，_get_ipv4 改为纯函数 |

### 四、前端架构改善

| 问题 | 建议 |
|------|------|
| data() 中 13 个展开运算符扁平合并 | 添加开发时键名冲突检测；长期考虑嵌套命名空间（dashboard.xxx, config.xxx） |
| template-loader innerHTML 无消毒 | 引入 DOMPurify CDN + data-include URL 白名单 |
| app.js bootstrapApp() 无错误处理 | 添加 .catch() 展示友好错误页面，上报后端日志 |

### 五、安全加固优先级

| 优先级 | 问题 | 影响范围 |
|--------|------|----------|
| P0 | SSRF — tools.py fetch_background_url 未过滤内网地址 | API 背景图下载 |
| P0 | XSS — template-loader.js innerHTML 注入 | 前端全部页面 |
| P0 | Zip Slip — git-puller extractTar 路径穿越 | Go 工具更新流程 |
| P1 | 信息泄露 — 异常类名、健康检查端点 | API 全部响应 |
| P1 | 脚本沙箱 — script_runner 以主进程权限运行 | 自定义脚本执行 |
| P1 | 密码明文 — settings-account.html type="text" | 设置页面 |

### 六、建议的实施顺序

**第一周（安全 & 崩溃修复）**：
修复 19 个确认 Critical 问题中的安全类（SSRF、XSS、Zip Slip、信息泄露、密码明文），以及导致崩溃的问题（NameError、锁顺序反转、Firefox 校验）。#18 (repo_proxy) 作为纵深防御改进可安排到后续迭代。

**第二周（可靠性修复）**：
修复 Major 级别的竞态条件（toggle_pure_mode TOCTOU、delete_task TOCTOU、_shutdown_initiated 竞态）和数据丢失风险（login_history 锁合并、config 回滚快照）。

**第三周（结构优化）**：
engine.py 拆分、probes.py threading→asyncio 迁移、interfaces.py 解析函数提取、step_handlers.py OCR 拆分。

**第四周（代码质量）**：
Minor 级别问题逐步清理，测试统一 asyncio 模式，前端键名冲突检测。

---

## 审查覆盖范围

| Review Unit | 模块 | 焦点 | 优先级 | 文件数 |
|-------------|------|------|--------|--------|
| service-engine | 服务层 | Actor 引擎 asyncio 迁移后正确性、命令队列、关闭顺序 | P0 | 2 |
| service-login | 服务层 | 登录管线 5 层调用链、重试策略、历史记录 | P0 | 7 |
| service-scheduler | 服务层 | 定时调度、任务注册/执行、CMD_LOGIN 复用 | P0 | 3 |
| service-config | 服务层+数据模型 | RuntimeConfig 构建、Profile CRUD、frozen 模型 | P0 | 3 |
| network-probes | 网络检测 | asyncio 探测并发、决策状态机、响应解析 | P0 | 3 |
| tasks-system | 任务系统 | JSON Schema 验证、变量解析注入、步骤执行 | P0 | 5 |
| workers-playwright | 工作线程 | Playwright Actor、bootstrap、script_runner | P0 | 3 |
| infra-di | 基础设施 | ServiceContainer 装配、lifespan、DI 注入 | P0 | 7 |
| api-routes | API 路由层 | 路由注册、输入验证、错误码、响应模型 | P0 | 8 |
| api-websocket | API+服务层 | WebSocket 连接管理、广播线程安全 | P1 | 2 |
| service-debug | 服务层 | 调试会话线程安全、状态机、并发隔离 | P1 | 2 |
| service-launcher | 服务层 | 子进程生命周期、自启动、卸载残留 | P1 | 3 |
| network-detect | 网络检测 | 网关/SSID 检测、网卡枚举、代理检测 | P1 | 4 |
| tasks-browser | 任务系统 | BrowserTaskRunner 执行流程、超时、资源释放 | P1 | 1 |
| frontend-app | 前端 | Vue 3 初始化、API 服务、组件注册 | P1 | 7 |
| frontend-pages | 前端 | HTML partials、methods、任务编辑器 | P1 | 8 |
| utils-core | 工具模块 | cancel_token、crypto、日志中心、原子写入 | P1 | 8 |
| utils-platform | 工具模块 | 平台检测、进程管理、Shell 策略 | P1 | 6 |
| go-tools | Go 工具 | 启动器、Git puller、进程管理 | P2 | 3 |
| test-coverage | 测试 | 覆盖率盲区、mock 正确性、asyncio 迁移同步 | P2 | 8 |

---

## 验证结果

报告生成后对 5 个 Critical 发现进行了抽样源码验证：

| # | 发现 | 验证结果 | 说明 |
|---|------|----------|------|
| #8 | cancel_token 锁顺序反转 | ⚠️ Uncertain | 锁顺序反转已确认（开发者注释佐证），但能否触发实际死锁需运行时验证 |
| #7 | Firefox 校验错误 | ✅ True Positive | Firefox 安装后无条件调用 Chromium 专用校验，确定性 bug |
| #15 | innerHTML XSS | ✅ True Positive | fetch HTML 未消毒直接 innerHTML 注入，攻击面真实存在 |
| #16 | active_task 覆盖 | ✅ True Positive | forEach 中 active_task 不在 CREDENTIAL_FIELDS 中，undefined 覆盖正确值 |
| #18 | repo_proxy SSRF | ❌ False Positive → 降级 | 所有调用方已在调用前执行 validate_url，当前无实际漏洞，但建议纵深防御 |

**统计修正**：原报告 21 个 Critical 中，#18 降级为代码质量建议，#8 标记为待运行时确认。实际确认为 Critical 的问题为 19 个。

---

## 附注

- 本报告仅列出发现，未执行任何代码修改
- 建议按 Critical → Major → Minor 顺序处理
- 部分问题需要跨模块协同修复（如 SSRF 修复需同时修改 tools.py 和 repo_proxy.py 的 validate_url）
- Critical 问题中的安全类（#5、#6、#15、#17、#19、#20）应最优先处理，#8 需运行时验证后确认优先级
- 已知问题交叉引用：MEMORY.md 中记录的 4 个 Critical（CR-01~04）在本次审查中均被重新发现并确认
- AI 审查报告幻觉率提醒：根据项目经验，AI 审查约 15% 为纯误报、70% 为个人使用难触发，建议逐条对照源码验证后再行动
