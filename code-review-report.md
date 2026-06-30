# Campus-Auth 代码审查报告

> 审查时间：2026-06-30
> 审查范围：app/api、app/services、app/network、app/tasks、app/workers、app/utils、frontend、start.go/start.sh/main.py、tests
> Review Unit 数量：15（P0×4、P1×8、P2×3）

## 适用场景声明

本报告基于 **单桌面单用户本地使用** 场景筛选。以下两类问题已标记为 ⏭️ 跳过，不计入待修复清单：

1. **安全漏洞**：本地使用场景下用户不可能自己攻击自己（SSRF、XSS、信息泄露、命令注入、PATH 劫持、密钥内存常驻等）
2. **单桌面单用户场景基本不可能出现的并发竞态**：如 lost-update、跨线程竞态窗口、多实例误杀等触发条件苛刻或概率极低的问题

## 摘要

| 严重性 | 总数 | ⏭️ 已跳过 | ✅ 待修复 |
|--------|------|-----------|-----------|
| 🔴 Critical | 10 | 5 | 5 |
| 🟠 Major | 55 | 11 | 44 |
| 🟡 Minor | 55 | 16 | 39 |
| 总计 | 120 | 32 | 88 |

| 模块 | Critical（待修复/跳过） | Major（待修复/跳过） | Minor（待修复/跳过） |
|------|-------------------------|----------------------|----------------------|
| service-engine-async（调度引擎+登录编排） | 0/0 | 3/0 | 2/3 |
| tasks-system（任务系统） | 0/1 | 1/2 | 3/1 |
| workers-playwright（Playwright Actor+浏览器） | 0/0 | 4/2 | 1/1 |
| utils-crypto（加密模块） | 0/1 | 2/2 | 1/2 |
| api-routes（REST 路由层） | 0/1 | 3/1 | 1/2 |
| api-websocket（WebSocket 通道） | 0/0 | 3/0 | 3/2 |
| service-core（应用工厂+DI+任务基础设施） | 0/1 | 3/0 | 4/0 |
| service-support（支撑服务） | 1/0 | 2/2 | 3/0 |
| network-detection（网络探测与决策） | 0/0 | 4/1 | 2/1 |
| frontend-vue（Vue 3 SPA 核心） | 0/0 | 3/0 | 4/1 |
| frontend-ws（前端实时通信） | 0/0 | 4/0 | 4/0 |
| utils-shell-process（Shell 执行与进程） | 0/1 | 1/1 | 2/3 |
| starter（启动器与桌面集成） | 2/0 | 4/0 | 2/0 |
| utils-general（通用工具） | 0/0 | 4/0 | 4/0 |
| test-coverage（测试套件） | 2/0 | 3/0 | 3/0 |

## 🔴 Critical 问题

### [1] ⏭️ 脚本任务绕过危险步骤审计且 binary_path 未校验，构成 RCE 风险

> **跳过原因**：安全漏洞。本地单用户使用场景下，脚本任务由用户自建，binary_path 由用户自配，不存在外部攻击者。

- **模块**：tasks-system
- **文件**：`app/tasks/manager.py:553-595`
- **分类**：崩溃/安全
- **描述**：save_task_with_validation 在 task_type == "script" 时直接调用 _save_script_task_validated 并 return，完全不经过 _check_dangerous_steps 审计（该审计仅对 browser 任务生效）。_save_script_task_validated 将用户提供的 content（最大 100KB 任意代码）和 binary_path（执行二进制路径）原样写入 scripts/*.json，二者均无任何校验或白名单约束。ScriptTaskInfo.binary_path 注释为「执行二进制路径，为空则使用 Python 解释器」，意味着用户可指定任意可执行文件配合任意脚本内容在服务器上执行。
- **影响**：任何具备任务创建权限的用户可上传任意 Python/Shell 脚本并通过 binary_path 指定任意解释器，导致服务器端任意命令执行（RCE），可窃取凭据、横向移动、完全控制宿主机。
- **建议修复方向**：对脚本任务启用独立的安全审计，对 binary_path 实施白名单校验（仅允许 python/python3），并在受控沙箱中执行用户脚本。

### [2] ⏭️ cryptography 缺失时静默降级为明文存储密码

> **跳过原因**：安全漏洞（密码学降级）。本地使用场景下，cryptography 依赖缺失属于环境异常，攻击者要读取明文密码文件已能直接获取原密码；非外部攻击向量。

- **模块**：utils-crypto
- **文件**：`app/utils/crypto.py:142-153`
- **分类**：崩溃/安全
- **描述**：encrypt_password 在 `from cryptography.fernet import Fernet` 抛 ImportError 时，仅打印一次 warning 日志后直接 `return plaintext`，把明文密码原样写入 settings.json。该降级既不抛异常也不阻断流程，且 `_crypto_missing_warned` 一旦置位后续不再告警。
- **影响**：密码明文持久化到用户目录，绕过整个加密保护体系；在多用户主机或备份同步场景下造成凭据泄露。攻击者通过破坏依赖环境即可让密码以明文落盘而不被察觉。
- **建议修复方向**：缺失依赖时应抛出运行时异常拒绝加密写入，而非静默回退明文。

### [3] ⏭️ fetch_background_url 存在 SSRF 漏洞，可窃取内网/云元数据响应

> **跳过原因**：安全漏洞（SSRF）。本地单用户使用，背景图 URL 由用户自配，不存在外部攻击者；用户不会自己攻击自己内网。

- **模块**：api-routes
- **文件**：`app/api/tools.py:97-148`
- **分类**：崩溃/安全
- **描述**：validate_url（app/utils/repo_proxy.py:22-30）仅校验 URL scheme 为 http/https，未拦截 127.0.0.1、10/172.16/192.168 私网段、169.254.169.254 云元数据地址、localhost 等。httpx 客户端设置 follow_redirects=True，外网 302 跳转到内网地址也会被跟随。内容类型校验存在绕过：只要 URL 以 .png/.jpg 等结尾即放行。下载内容随后被 _save_background 保存并经 GET /api/background/{filename} 公开返回，形成完整的数据外泄链路。
- **影响**：本机或同网段攻击者可探测内网端口、读取 AWS/云实例元数据（含临时凭证）、访问本机其他服务并将响应内容通过背景图接口回传外泄。
- **建议修复方向**：在 validate_url 中增加私网/回环/链路本地 IP 黑名单解析，并禁用 follow_redirects 或对每次跳转重新校验目标。

### [4] ⏭️ update_last_run 与 save_task 之间存在 lost-update 竞态，可覆盖用户编辑

> **跳过原因**：单桌面单用户场景基本不可能出现。引擎线程更新 last_run 与用户在前端编辑保存任务配置需在同一时间窗口内交错才会触发，概率极低。

- **模块**：service-core
- **文件**：`app/services/task_registry.py:147-169`
- **分类**：可靠性
- **描述**：update_last_run 在锁内修改缓存并创建 snapshot 后，在锁外调用 atomic_write 写盘。save_task 也在锁外写盘。两者并发时：Thread A（update_last_run）读取旧缓存生成 snapshot → Thread B（save_task）写新配置到磁盘 → Thread B 更新缓存 → Thread A 将旧 snapshot 写盘，覆盖 Thread B 的磁盘写入。最终磁盘保留旧配置 + last_run，缓存为新配置，两者不一致；重启后用户编辑丢失。
- **影响**：用户编辑定时任务配置后，若该任务恰好在执行并更新 last_run，则用户的编辑会从磁盘丢失，重启后回滚到旧配置。
- **建议修复方向**：将 update_last_run 的磁盘写入移入锁内，或统一磁盘与缓存的写入临界区。

### [5] 删除 Playwright 缓存目录无路径校验，存在误删用户文件风险

- **模块**：service-support
- **文件**：`app/services/uninstall.py:144-152`
- **分类**：崩溃/安全
- **描述**：_remove_playwright_cache() 直接对 get_playwright_cache_dir() 返回的路径执行 shutil.rmtree()，未像 _remove_user_data() 那样校验目录名（如 'ms-playwright'）。若路径计算被环境变量 PLAYWRIGHT_BROWSERS_PATH 影响、或日后 get_playwright_cache_dir 逻辑变更、或目录被软链接到其他位置，shutil.rmtree 将递归删除整个目录树且不可恢复。
- **影响**：不可恢复地删除用户文件，可能波及整个缓存根目录或共享目录，造成数据丢失。
- **建议修复方向**：增加 expected_name 校验（如确认 cache_dir.name == 'ms-playwright'），并校验路径未通过软链接指向敏感目录。

### [6] ⏭️ validate_url 仅校验 scheme 未校验 host/IP，存在 SSRF 漏洞

> **跳过原因**：安全漏洞（SSRF）。本地单用户使用，repo fetch URL 由用户自配或来自项目内置仓库地址，不存在外部攻击者。

- **模块**：utils-shell-process
- **文件**：`app/utils/repo_proxy.py:22-30`
- **分类**：崩溃/安全
- **描述**：validate_url 只检查 URL scheme 是否属于 {http, https}，对 host/端口/IP 没有任何限制。调用方（repo.py:/api/repo/fetch、/api/repo/task）直接将用户 Query 参数传给此函数后即交给 async_repo_fetch_json 发起请求。攻击者可构造 http://127.0.0.1:6379/、http://169.254.169.254/latest/meta-data/、http://10.0.0.1/ 等地址。
- **影响**：内网端口扫描、云实例元数据凭证泄露、内部未鉴权服务暴露，构成完整 SSRF 攻击链。
- **建议修复方向**：在 validate_url 中增加 host 解析与 IP 分类校验，拒绝回环/私有/链路本地及元数据地址，并对解析得到的 IP 做二次校验以防 DNS rebinding。

### [7] 轻量模式托盘退出发送 SIGTERM 但未注册处理器，导致 finally 清理被跳过

- **模块**：starter
- **文件**：`app/system_tray.py:74-79`（根因在 `app/services/launcher.py` launch_lightweight）
- **分类**：可靠性
- **描述**：_quit 调用 on_exit，而 on_exit 在 launch_lightweight 中绑定为 os.kill(getpid(), SIGTERM)。但 launch_lightweight 只捕获 KeyboardInterrupt，没有 signal.signal(SIGTERM, ...) 注册。Python 默认 SIGTERM 行为是直接终止进程，不抛异常、不执行 finally、不执行 atexit。因此 container.shutdown()、cleanup_pid()、force_exit(0) 全部被跳过。launch_full 不存在此问题（已注册 SIGTERM 处理器）。
- **影响**：轻量模式下用户通过托盘退出时，PID 文件残留、容器资源不释放，下次启动 is_service_running 误判，端口与单例锁冲突。
- **建议修复方向**：在 launch_lightweight 中同样注册 SIGTERM 处理器，设置 _web_server_shutdown_event 以触发正常的 finally 清理路径。

### [8] Windows 下信号转发实现有缺陷：SIGTERM 死代码、SIGINT 双重触发

- **模块**：starter
- **文件**：`start.go:234-248`
- **分类**：兼容性
- **描述**：signal.Notify(sigChan, os.Interrupt, syscall.SIGTERM) 在 Windows 上对 SIGTERM 永不触发（死代码）；cmd.Process.Signal(sig) 返回的 error 被忽略。更严重的是，用户按 Ctrl+C 时整个控制台进程组已直接收到 SIGINT，start.go 又通过 GenerateConsoleCtrlEvent 再次转发，导致子进程的 _signal_handler 被调用两次：第一次置 _shutdown_initiated=True，第二次因已为 True 直接走 os._exit(1) 紧急退出路径，绕过所有 finally 清理。
- **影响**：Windows 下 Ctrl+C 退出时大概率跳过 container.shutdown() 与 cleanup_pid()，造成 PID 文件残留、资源泄漏。
- **建议修复方向**：区分平台：Windows 下不显式转发 SIGINT（子进程已直接收到），并检查 Process.Signal 返回的错误。

### [9] 模块级 sys.modules["pystray"] 全局污染，无 finalizer 且无法恢复

- **模块**：test-coverage
- **文件**：`tests/conftest.py:16-20`
- **分类**：代码质量
- **描述**：在 conftest.py 模块加载（pytest 收集阶段）即执行 sys.modules["pystray"] = MagicMock()，且仅按 sys.platform != 'win32' 判断。这不是 fixture，没有 yield/teardown，一旦设置在整个测试会话期间永久生效，且 _pystray_mock 变量赋值后从未被使用或清理。
- **影响**：全局 mock 泄漏到所有测试，破坏隔离性；若未来新增需要真实 pystray 的测试将在 CI 上静默失败或走错路径。
- **建议修复方向**：改为 autouse session 级 fixture，用 monkeypatch 或 try/finally + sys.modules.pop 在会话结束后恢复。

### [10] test_engine_loop_integration_with_network_login 全程无任何断言

- **模块**：test-coverage
- **文件**：`tests/test_integration/test_login_flow.py:333-363`
- **分类**：代码质量
- **描述**：该测试方法体不含一个 assert 语句，仅构造 mock、手动调用一次 _do_network_check、然后 future.set_result(None) + time.sleep(0.1) 收尾。而 _on_login_done 回调期望 f.result() 解包为 (ok, msg) 元组，传入 None 会触发 TypeError 走 except 分支。测试既未验证登录被触发，也未验证结果。
- **影响**：测试永远绿色但零价值，无法捕获回归；误导维护者以为引擎循环+网络检测+登录链路已被覆盖。
- **建议修复方向**：补充对 _do_async_login/assert_called、response_data、response_event 的断言，并将 set_result 改为 (True, '登录成功') 元组以符合回调契约。

---

## 🟠 Major 问题

### [11] retry_policy on_login_done 与 retries_exhausted 边界条件不一致

- **模块**：service-engine-async
- **文件**：`app/services/retry_policy.py:55-63`
- **分类**：可靠性
- **描述**：on_login_done 使用 `_attempt > max_retries` 判断停止，而 retries_exhausted 使用 `_attempt >= max_retries`。当 max_retries=5 时，第 5 次失败后 retries_exhausted 已为 True，但 on_login_done 仍返回 delay_before(5)=100s 并调度第 6 次重试。结合 engine._do_network_check 在网络检测时会先清除 _next_retry_time 再判断 retries_exhausted，导致实际重试次数取决于网络检测间隔与重试延迟的时序竞争。
- **影响**：实际重试次数与配置不符（可能少 1 次），网络检测间隔较短时登录恢复能力下降；日志数字不一致造成排障困难。
- **建议修复方向**：统一边界条件，将 on_login_done 的 `>` 改为 `>=`。

### [12] tick 方法缺少异常处理，异常时引发引擎循环每秒重试与 CPU 飙升

- **模块**：service-engine-async
- **文件**：`app/services/scheduler_service.py:60-73`
- **分类**：可靠性
- **描述**：tick 方法中 registry.get_due_tasks 或 executor.execute_task_async 抛异常时，方法末尾的 `_next_schedule_tick = ...` 不会执行。引擎循环捕获异常后 sleep 1s 继续运行，但 should_tick 因 _next_schedule_tick 未更新仍返回 True，形成每秒一次的异常→捕获→重试紧循环。
- **影响**：CPU 飙升、日志刷屏、到期任务可能被重复执行（execute_task_async 非幂等时）。
- **建议修复方向**：用 try/finally 包裹 tick 主体，确保 _next_schedule_tick 在 finally 中无论如何都更新。

### [13] 手动登录 API 超时后不取消后台登录任务，导致浏览器资源泄漏

- **模块**：service-engine-async
- **文件**：`app/services/engine.py:924-932`
- **分类**：可靠性
- **描述**：run_manual_login 在 response_event.wait(timeout=api_wait_timeout) 超时后直接返回错误，但不调用 cancel_login 取消正在执行的登录 future。Worker 进程（含 Playwright 浏览器实例）会继续运行直到 worker_timeout（最多 600s）才释放。同时 finally 块已将 _manual_login_in_progress 重置为 False，但 orchestrator._slot 仍持有未完成的旧 handle，用户再次发起手动登录时会被去重逻辑拒绝。
- **影响**：浏览器进程资源泄漏（最长 600s），用户在旧任务结束前无法发起新登录。
- **建议修复方向**：超时返回前调用 self._login_bridge.cancel_login() 取消正在执行的登录任务。

### [14] threading.Lock 在异步 FastAPI 上下文中阻塞事件循环

- **模块**：tasks-system
- **文件**：`app/tasks/manager.py:86,373,429`
- **分类**：性能
- **描述**：TaskManager 使用 threading.Lock 保护 save_task 和 delete_task。这些方法是同步方法，内部执行 atomic_write、file.unlink、json.dumps 等阻塞 I/O。在 FastAPI 异步后端中，若路由处理器直接调用这些同步方法，会阻塞整个事件循环；即使通过线程池调用，threading.Lock 也会在 I/O 期间持有锁，导致所有并发任务写操作串行化。
- **影响**：高并发下文件 I/O 期间所有协程被阻塞，API 响应延迟剧增；多个保存/删除请求串行排队。
- **建议修复方向**：改用 asyncio.Lock 并将方法改为 async，或对阻塞 I/O 使用 asyncio.to_thread 包装。

### [15] ⏭️ wait_url 步骤 pattern 字段为用户可控正则，存在 ReDoS 风险

> **跳过原因**：安全漏洞（ReDoS）。本地单用户使用，任务 pattern 由用户自配，不存在外部攻击者构造恶意正则。

- **模块**：tasks-system
- **文件**：`app/tasks/step_handlers.py:577-592`
- **分类**：崩溃/安全
- **描述**：WaitUrlHandler.execute 从任务配置读取 pattern，直接 re.compile(pattern) 后在 while True 循环中反复 compiled.search(current_url)。pattern 来自用户自定义任务 JSON，validator.py 未对其做任何复杂度或语法约束。攻击者可构造灾难性正则（如 (a+)+$ 配合长 URL），导致单次 search 调用指数级回溯。
- **影响**：单个恶意任务可导致执行该任务的 worker 线程长时间 CPU 占满，其他任务被饿死；若任务执行在事件循环线程则直接卡死整个服务（DoS）。
- **建议修复方向**：对 pattern 添加复杂度上限，或使用 re.search 的超时机制，或改用 Playwright 原生 page.wait_for_url(glob)。

### [16] ⏭️ TaskValidator 未校验 url 字段协议与格式，存在 SSRF 风险

> **跳过原因**：安全漏洞（SSRF）。本地单用户使用，任务 url 由用户自配，不存在外部攻击者。

- **模块**：tasks-system
- **文件**：`app/tasks/validator.py:33-63`
- **分类**：崩溃/安全
- **描述**：validate 方法校验了 name、steps、variables、timeout，但完全未校验 config["url"]。攻击者可设置 url 为 file:///etc/passwd、http://169.254.169.254/（云元数据）、http://内网IP:port 或 javascript:alert(1) 等危险协议，validator 全部放行。
- **影响**：任务执行时浏览器导航至 file:// 可读取服务器本地文件并截图回传；导航至内网地址或云元数据端点可探测内网拓扑、窃取实例凭据（SSRF）。
- **建议修复方向**：在 validate 中增加 url 协议白名单校验（仅允许 http/https）、禁止内网 IP 段。

### [17] _handle_debug_start 复用已关闭的页面导致调试会话失效

- **模块**：workers-playwright
- **文件**：`app/workers/playwright_worker.py:484-509`
- **分类**：可靠性
- **描述**：当用户未先停止上一个调试会话就再次调用 debug_start 时，_cleanup_debug_session() 会关闭 self._debug_page（与 self._page 指向同一对象），但 self._page 仍保留对该已关闭页面的引用。_health_check() 仅检查 browser.is_connected()（返回 True），不会触发浏览器重建，于是后续 goto() 抛出 'Target page, context or browser has been closed'。
- **影响**：用户再次启动调试时收到错误，且后续 debug_step 也会失败，用户必须显式 stop 才能恢复。
- **建议修复方向**：在 _health_check 中增加 self._page is None or self._page.is_closed() 的检查。

### [18] ⏭️ binary_path 不在白名单时自动添加，绕过 ShellCommandPolicy 安全策略

> **跳过原因**：安全漏洞。本地单用户使用，binary_path 由用户自配，用户不会自己指定恶意解释器攻击自己。

- **模块**：workers-playwright
- **文件**：`app/workers/script_runner.py:195-203`
- **分类**：崩溃/安全
- **描述**：run() 中检测到 self.binary_path 不在 detect_available_binaries 返回的已知列表时，仅记录 warning 后将该路径直接 append 到 available 列表，再用该列表构造 ShellCommandPolicy。这意味着任何 binary_path 都会被白名单接纳，allowlist 形同虚设。
- **影响**：若 binary_path 来源于不可信输入，攻击者可指定任意可执行文件路径（如 /bin/sh、cmd.exe）执行用户脚本，导致任意代码执行。
- **建议修复方向**：当 binary_path 不在已知列表时直接拒绝执行并返回错误，而非自动添加。

### [19] ⏭️ _get_extra_http_headers 仅校验 header key 的 CRLF，未校验 value 导致 HTTP 头注入

> **跳过原因**：安全漏洞（HTTP 头注入）。本地单用户使用，extra_headers 由用户自配，不存在外部攻击者。

- **模块**：workers-playwright
- **文件**：`app/workers/playwright_worker.py:960-972`
- **分类**：崩溃/安全
- **描述**：解析 extra_headers_json 时，对 key 做了 \r/\n 换行符检查并跳过，但对 value (v_str) 未做同样检查就直接放入 result 字典。攻击者可构造 value 含 '\r\nSet-Cookie: evil=1' 之类的注入载荷。
- **影响**：可能导致 HTTP 响应拆分/头注入，注入恶意 Cookie 或绕过 CORS 等安全策略。
- **建议修复方向**：对 v_str 同样做 \r/\n 检查并跳过。

### [20] _check_success 在无 monitor_config 时直接返回 True，登录成功判定不可靠

- **模块**：workers-playwright
- **文件**：`app/tasks/browser_runner.py:303-306`
- **分类**：可靠性
- **描述**：_check_success 仅当 self.monitor_config 为真值时才调用 _network_detection_check 做网络验证；否则无条件返回 True。这意味着只要任务步骤全部执行成功（哪怕只是 fill 了错误密码），就被判定为登录成功。
- **影响**：当调用方未传入 monitor_config 时，登录失败会被误报为成功，导致认证状态判断错误。
- **建议修复方向**：无 monitor_config 时应返回 False 并给出明确原因。

### [21] post_login_delay 使用 'or' 运算导致 0 被当作 5 处理

- **模块**：workers-playwright
- **文件**：`app/tasks/browser_runner.py:323`
- **分类**：可靠性
- **描述**：await asyncio.sleep(cfg.get('post_login_delay') or 5) 中，若用户显式配置 post_login_delay=0（表示无需等待），Python 的 or 短路求值会将 0 视为 falsy，实际 sleep 5 秒。
- **影响**：用户显式设置 0 延迟以加速认证检测的场景下，每个登录任务被多等 5 秒，批量任务时累积显著拖慢。
- **建议修复方向**：改为 delay = cfg.get('post_login_delay'); await asyncio.sleep(delay if delay is not None else 5)。

### [22] 截图 URL 在 Windows 下使用 Path.relative_to 产生反斜杠路径

- **模块**：workers-playwright
- **文件**：`app/workers/playwright_worker.py:547-551`（browser_runner.py:372-376 同样问题）
- **分类**：兼容性
- **描述**：计算 screenshot_url 时用 f'/temp/{rel}/{filename}'，rel 是 Path.relative_to(TEMP_DIR) 的结果。Windows 下 str(rel) 对多级子目录返回反斜杠（如 'subdir\\nested'），拼出的 URL 形如 '/temp/subdir\\nested/file.png'。
- **影响**：Windows 环境下嵌套截图目录生成的 URL 含反斜杠，前端无法正确解析，截图链接 404。
- **建议修复方向**：统一用 rel.as_posix() 将路径转为正斜杠形式再拼入 URL。

### [23] ⏭️ 密钥派生使用非标准 SHA-256 拼接后缀而非标准 KDF

> **跳过原因**：安全漏洞（密码学标准）。本地单用户使用，攻击者要破解需先获取密钥文件，已能直接解密；非外部攻击向量。

- **模块**：utils-crypto
- **文件**：`app/utils/crypto.py:129-131`
- **分类**：崩溃/安全
- **描述**：_derive_fernet_key 通过 `sha256(raw_key + b":signing").digest()[:16]` 与 `b":encryption"` 拼接后单轮哈希来派生子密钥。这是「自制 KDF」：固定后缀充当 salt、无迭代次数、无 HKDF 的 extract/expand 结构。
- **影响**：审计风险高；若未来 raw_key 来源改为口令（低熵输入），现有派生方式将无法抵抗暴力枚举；HMAC 签名密钥仅 16 字节（128 位），低于推荐长度。
- **建议修复方向**：改用 cryptography.hazmat.primitives.kdf.hkdf.HKDF，或直接用 Fernet.generate_key()。

### [24] ⏭️ 全局缓存密钥永不清理，明文密钥长驻进程内存

> **跳过原因**：安全漏洞（内存泄露）。本地单用户使用，进程内存属于用户自己；攻击者要 dump 内存已需获得本机执行权限。

- **模块**：utils-crypto
- **文件**：`app/utils/crypto.py:31-32,113,132`
- **分类**：崩溃/安全
- **描述**：_cached_raw_key 与 _cached_fernet_key 作为模块级全局变量，一旦填充后即永久驻留，无任何清理接口。Python 字符串/bytes 不可变，无法显式置零。
- **影响**：进程崩溃 dump、内存取证、共享主机上的 ptrace 等场景下密钥直接暴露，进而解密所有历史密码密文。
- **建议修复方向**：提供 bytearray 包装的密钥持有对象并在退出/锁定时显式清零；或缩短密钥缓存生命周期。

### [25] encrypt_password 调用 clear_decryption_error() 误清全局失败标记

- **模块**：utils-crypto
- **文件**：`app/utils/crypto.py:159`
- **分类**：可靠性
- **描述**：encrypt_password 在加密成功后无条件调用 clear_decryption_error()，而 _decryption_failed 是进程级全局 threading.Event，不区分字段/方案。若用户有多个密码字段，其中字段 A 解密失败（标记已 set），用户更新字段 B 的新密码时，B 的加密会清掉全局标记，导致 has_decryption_error() 返回 False。
- **影响**：解密失败的字段 A 被错误地标记为「正常」，UI 不再提示用户重新输入，登录时静默使用空密码或旧值导致认证失败。
- **建议修复方向**：失败标记应改为按字段/方案粒度记录。

### [26] decrypt_password_field 吞掉 _DecryptionError 详情，仅返回布尔标志

- **模块**：utils-crypto
- **文件**：`app/utils/crypto.py:238-263`
- **分类**：可靠性
- **描述**：decrypt_password_field 三个 except 分支统一返回 ("", True)，原始 _DecryptionError（区分 cryptography 缺失 vs 密钥变更 vs 数据损坏）被完全丢弃。decrypt_password 中精心构造的异常消息无法传递到调用方。
- **影响**：线上排查困难：无法区分是依赖缺失（运维问题）还是密钥变更（用户行为）。
- **建议修复方向**：返回值中携带错误类型枚举或保留异常对象。

### [27] patch_config 增量更新会清空未传入的 username/auth_url/active_task 等凭据字段

- **模块**：api-routes
- **文件**：`app/api/config.py:241-266`
- **分类**：可靠性
- **描述**：current = old_cfg.model_dump() 产生的字典中凭据嵌套在 credentials 下，而 ConfigPatchRequest 的凭据字段是平铺的。merged = {**current, **patch_data} 仅在顶层合并，未把 current['credentials'] 扁平化到顶层；随后 ConfigSaveRequest.model_validate(merged) 对缺失的 username/auth_url/active_task 取默认空串。save_global_and_profile 用 payload.username or '' 直写覆盖 existing，导致这些字段被清空。
- **影响**：前端若用 PATCH 仅修改 browser/monitor 等非凭据字段，已保存的认证用户名、auth_url、活动任务会被清空，导致认证任务无法执行。
- **建议修复方向**：在 patch_config 中将 current['credentials'] 扁平化到顶层后再与 patch_data 合并。

### [28] ⏭️ 允许上传/下载 SVG 文件导致存储型 XSS

> **跳过原因**：安全漏洞（XSS）。本地单用户使用，背景图由用户自上传，用户不会上传恶意 SVG 攻击自己。

- **模块**：api-routes
- **文件**：`app/api/tools.py:155-164`
- **分类**：崩溃/安全
- **描述**：ALLOWED_EXTENSIONS 包含 .svg。get_background 用 FileResponse(filepath) 返回文件且未指定 media_type，Starlette 会推断为 image/svg+xml，也未设置 Content-Disposition: attachment。SVG 内可嵌入 <script>，当用户直接在浏览器访问 /api/background/{filename}.svg 时，脚本在应用同源上下文中执行。
- **影响**：攻击者上传恶意 SVG 后诱导用户直接打开该 URL，可窃取本地会话凭证、调用其他同源 API 执行高危操作。
- **建议修复方向**：从 ALLOWED_EXTENSIONS 移除 .svg，或对 SVG 强制返回 Content-Disposition: attachment。

### [29] save_task 接收 raw dict 作为请求体，未做 Pydantic 校验

- **模块**：api-routes
- **文件**：`app/api/tasks.py:40-48`
- **分类**：代码质量
- **描述**：save_task(task_id, payload: dict, ...) 直接接受任意 dict 并透传给 task_mgr.save_task_with_validation。与同文件 save_task_order 使用 TaskOrderRequest、其他模块使用具体 schema 的做法不一致。FastAPI 对 dict 类型不会进行请求体校验。
- **影响**：前端或第三方传入结构错误的任务数据可绕过入口校验，引发下游序列化/反序列化异常或写入脏数据。
- **建议修复方向**：定义 TaskSaveRequest Pydantic 模型替换 dict 入参。

### [30] update_scheduled_task 接收 raw dict 并浅合并，与 create 端点校验不一致

- **模块**：api-routes
- **文件**：`app/api/scheduled_tasks.py:43-72`
- **分类**：代码质量
- **描述**：create_scheduled_task 入参为 ScheduledTaskConfig，但 update_scheduled_task 入参为 payload: dict。merged = {**existing, **payload} 是浅合并，payload 可注入任意顶层键（如 last_run、last_status、id 等运行时元数据），line 64-66 又把 last_run/last_status 直接写回 config 字典，绕过模型约束。
- **影响**：前端可篡改 last_run/last_status 等本应由系统维护的运行时字段，污染执行历史展示。
- **建议修复方向**：update 端点也改用 ScheduledTaskConfig 作为入参，运行时元数据由服务层从 existing 取值。

### [31] set_dashboard_sink 迁移期间存在消息丢失与延迟排空竞态

- **模块**：api-websocket
- **文件**：`app/services/websocket_manager.py:118-130`
- **分类**：可靠性
- **描述**：set_dashboard_sink 在 while 循环迁移 _empty_broadcast_queue 到 sink.broadcast_queue 期间，_dashboard_sink 仍为 None。若此时 enqueue_status 被调用，消息会入队到 _empty_broadcast_queue，但这些消息既不会被迁移，也不会被后续 _drain_queue 排空。此外迁移完成后未调用 _notify_drain，已迁移的消息需等待下一次操作才被排空。
- **影响**：初始化切换 DashboardSink 期间的状态更新或日志消息可能永久丢失或长时间延迟。
- **建议修复方向**：在 set_dashboard_sink 末尾调用 self._notify_drain()，并在迁移期间持锁或使用原子切换。

### [32] disconnect 与超时清理仅从列表移除，未调用 websocket.close()

- **模块**：api-websocket
- **文件**：`app/services/websocket_manager.py:41-44,62-73,96-103`
- **分类**：可靠性
- **描述**：disconnect 方法只从 _connections 列表移除连接，不调用 websocket.close()。broadcast 的总体超时分支和 _send_safe 的单连接超时分支同样只移除连接而不关闭底层 WebSocket。
- **影响**：客户端不知道连接已失效，会持续保持 TCP 连接并等待消息，造成连接泄漏和资源占用。
- **建议修复方向**：在移除连接后增加 await websocket.close() 调用（包裹在 try/except 中）。

### [33] _drain_queue 串行广播且单条 broadcast 最长阻塞 5 秒

- **模块**：api-websocket
- **文件**：`app/services/websocket_manager.py:166-177`
- **分类**：性能
- **描述**：_drain_queue 的 while 循环对每条消息串行调用 await self.broadcast(json.dumps(data))。broadcast 内部对慢连接有 5 秒总体超时。若存在一个慢连接，每条消息的排空都要等待最长 5 秒，期间新消息持续入队，队列 maxlen 满后旧消息被静默丢弃。
- **影响**：高频日志场景下单个慢客户端会拖慢整个广播链路，导致队列积压、消息丢弃、前端 dashboard 实时性严重下降。
- **建议修复方向**：将 broadcast 改为非阻塞入队 + 后台并发发送，或为慢连接设置更短的单连接超时并快速剔除。

### [34] 关闭顺序不当：WS drain loop 先于 task_executor 关闭，运行中任务的 WS 消息丢失

- **模块**：service-core
- **文件**：`app/container.py:169-201`
- **分类**：可靠性
- **描述**：shutdown() 顺序为：stop_web_services()（取消 _ws_drain_task）→ engine.shutdown() → task_executor.shutdown(wait=False) → debug_manager.close() → ws_manager.close_all()。由于 task_executor.shutdown(wait=False) 不等待运行中任务，而 WS drain loop 已被取消，运行中的任务若调用 ws_manager.broadcast 推送进度/结果，消息会滞留队列随后被丢弃。
- **影响**：关闭期间运行中的定时任务无法向前端推送最终状态，用户可能看到任务卡在中间状态。
- **建议修复方向**：调整为：engine.shutdown() → task_executor.shutdown(wait=True, timeout=N) → stop_web_services() → ws_manager.close_all()。

### [35] Windows 上 os.kill(pid, SIGTERM) 回退路径实为 TerminateProcess 硬终止

- **模块**：service-core
- **文件**：`app/application.py:165-180`
- **分类**：兼容性
- **描述**：_wait_shutdown 在无法获取 _uvicorn_server 引用时回退到 os.kill(os.getpid(), signal.SIGTERM)。在 Windows 上，Python 的 os.kill 对 SIGTERM 的实现是调用 TerminateProcess，直接终止进程，不会执行 lifespan yield 之后的 services.shutdown() 清理逻辑。
- **影响**：当 create_app 被直接使用且在 Windows 上运行时，通过 shutdown_event 触发的关闭会硬终止进程，跳过 services.shutdown()，可能导致临时文件残留、浏览器进程未释放。
- **建议修复方向**：Windows 回退路径改用 _server.should_exit = True 的等价机制，或直接调用 force_exit 并在调用前同步执行一次 services.shutdown()。

### [36] existing_container 升级路径跳过 cleanup_orphan_browsers

- **模块**：service-core
- **文件**：`app/application.py:115-122`
- **分类**：可靠性
- **描述**：lifespan 中 existing_container 分支调用 start_web_services() + engine.start_thread() + sync_scheduler_state()，但未调用 startup() 中的 cleanup_orphan_browsers()。轻量模式→完整模式升级时，若上一次完整模式崩溃残留了 Playwright 浏览器进程，升级后不会清理。
- **影响**：升级场景下残留的浏览器进程可能占用端口和内存，导致新启动的浏览器任务因端口冲突或资源不足而失败。
- **建议修复方向**：在 existing_container 分支的 start_web_services() 之前补充 cleanup_orphan_browsers() 调用。

### [37] 调试会话启动失败时未取消超时定时器，导致 asyncio 任务泄漏

- **模块**：service-support
- **文件**：`app/services/debug_service.py:143-178`
- **分类**：可靠性
- **描述**：start() 在 async with self._lock 块内创建了 self._session._timer_task = asyncio.create_task(self._debug_timeout_watcher(gen))。随后 Worker 启动在锁外执行，若抛异常进入 except 块，仅调用 _close_debug_browser()，未调用 _cancel_debug_timer()。此时新创建的 timer 任务未被取消，会在 1800s 后触发。
- **影响**：每次启动失败都会泄漏一个 asyncio 任务，1800s 后才触发异常路径；长期运行可能累积大量僵尸任务。
- **建议修复方向**：在 except 块中补充 await self._cancel_debug_timer()。

### [38] _cleanup_lock 为死代码，且 _cleanup_old 在主写入锁内执行阻塞所有并发写入

- **模块**：service-support
- **文件**：`app/services/login_history_service.py:38-74`
- **分类**：性能
- **描述**：__init__ 中定义了 self._cleanup_lock = threading.Lock()，但该锁在整个类中从未被 acquire。同时 add() 在 with self._lock 内调用 self._cleanup_old(max_age_days=30)，而 _cleanup_old 会读取整个 JSONL 文件、过滤、再 atomic_write 重写。每 50 次写入触发一次全文件重写，期间持有 _lock 阻塞所有其他调用。
- **影响**：清理期间所有登录历史写入被阻塞，可能导致监控线程的登录记录写入超时或丢失。
- **建议修复方向**：将 _cleanup_old 移出 _lock（使用独立的 _cleanup_lock 或后台线程异步执行）。

### [39] ⏭️ save_global_and_profile 在无锁状态下读取 backup，回滚时可能覆盖并发修改

> **跳过原因**：单桌面单用户场景基本不可能出现。需「自动方案切换」与「用户编辑配置失败回滚」在同一时间窗口交错才触发，概率极低。

- **模块**：service-support
- **文件**：`app/services/profile_service.py:294-365`
- **分类**：可靠性
- **描述**：save_global_and_profile() 先无锁执行 backup_data = copy.deepcopy(profile_service.load())，随后在 profile_service.update(_apply) 内持锁重新 load 并修改。若两次调用之间其他线程（如自动方案切换）修改了 settings.json，backup_data 仍是旧快照。一旦 reload_fn() 失败触发回滚，_rollback_config 会用 backup_data 的字段覆盖当前 data，丢失其他线程的并发修改。
- **影响**：回滚时静默丢失其他线程已提交的配置变更（如方案切换、密码更新），导致数据不一致且无告警。
- **建议修复方向**：在 update(_apply) 的锁内同时获取 backup，确保 backup 与 apply 基于同一快照。

### [40] ⏭️ _terminate_process 存在 TOCTOU 竞态，PID 复用时可能误杀无关进程

> **跳过原因**：安全漏洞 + 单桌面单用户场景基本不可能出现。需目标进程退出且 OS 将 PID 立即复用给无关进程，且在 _terminate_process 调用窗口内完成，概率极低。

- **模块**：service-support
- **文件**：`app/services/launcher.py:66-86`
- **分类**：崩溃/安全
- **描述**：_terminate_process(pid) 直接对传入 PID 发送 SIGTERM（POSIX）或 taskkill（Windows），未在终止前重新验证进程身份。虽然 is_service_running() 通过 verify_process_identity(pid, create_time) 验证过身份，但从验证到 _terminate_process 执行之间存在时间窗口。若目标进程在此期间退出且操作系统将该 PID 复用给无关进程，SIGTERM/taskkill 会误杀新进程。
- **影响**：极端情况下误杀无关进程，可能导致系统服务异常或用户数据丢失；Linux 上 PID 空间有限复用更快。
- **建议修复方向**：在 _terminate_process 内再次调用 verify_process_identity(pid, stored_create_time) 验证身份后再发送信号。

### [41] 线程池嵌套提交导致 worker 耗尽与潜在死锁

- **模块**：network-detection
- **文件**：`app/network/probes.py:19-20`
- **分类**：性能
- **描述**：probes.py 创建全局 executor(max_workers=8)，decision.is_network_available 向其提交 TCP/HTTP/URL 三个外层 future（占用 3 个 worker），而 is_network_available_socket/http/url 又各自向同一 executor 提交子 future。当默认配置同时启用三种检测时，外层任务占用 worker 等待子任务完成，子任务因无空闲 worker 而排队，形成经典的嵌套提交死锁。
- **影响**：网络正常时 URL 检测可能因 worker 不足超时，AND 语义判定为 network_down，触发无效登录。
- **建议修复方向**：为外层调度与内层探测使用独立线程池，或将内层探测改为同步串行执行由外层并发驱动。

### [42] parse_ping_targets 对 [IPv6] 无端口格式触发 ValueError 而非自动补全

- **模块**：network-detection
- **文件**：`app/network/parsers.py:124-141`
- **分类**：可靠性
- **描述**：对以 '[' 开头的输入直接 append 不做端口补全，注释声称'已是 [IPv6]:port 格式'。但用户输入 '[::1]'（无端口）也会进入此分支，随后 parse_host_port 执行 rsplit(':',1) 得到 host='[:'、port_str='1]'，'1]'.isdigit() 为 False，抛出 ValueError。与函数 docstring '缺少端口的项自动补全' 的承诺直接矛盾。
- **影响**：用户配置 IPv6 ping 目标且省略端口时，TCP 检测目标解析失败，导致 TCP 检测回退到默认目标，与用户配置意图不符。
- **建议修复方向**：对 '[' 开头的输入检查 ']' 后是否跟随 ':port'，若无则补全为 '[IPv6]:53'。

### [43] is_local_network_connected 未过滤虚拟网卡导致物理断网时误报已连接

- **模块**：network-detection
- **文件**：`app/network/probes.py:90-101`
- **分类**：可靠性
- **描述**：仅过滤名字以 'lo' 开头的接口，未排除 docker0、veth*、br-*、vmnet*、VirtualBox Host-Only Adapter 等虚拟网卡。这些网卡 stats.isup 通常为 True（只要对应服务运行），但并不代表有真实上行网络。当用户拔掉网线/断开 WiFi 但 Docker 或虚拟机服务仍在运行时，函数仍返回 True。
- **影响**：物理网络断开仍判定为'已连接'，放行后续登录流程，导致浏览器被无意义启动并反复登录失败。
- **建议修复方向**：增加虚拟网卡名黑名单过滤，或改用默认路由是否存在来判断真实上行连通性。

### [44] _is_auth_url_reachable 在 auth_url 解析失败时错误返回 True

- **模块**：network-detection
- **文件**：`app/network/decision.py:263-273`
- **分类**：可靠性
- **描述**：urlparse(auth_url).hostname 为 None（如 auth_url='http://' 或 'not-a-url'）时直接 return True。这相当于'无法解析认证地址就认为它可达'，与函数语义'检查认证地址可达性'相反。后续 _check_host_port 不会执行，直接放行登录前置检查。
- **影响**：auth_url 配置错误或被篡改为非法格式时，不会被识别为不可达，反而触发浏览器登录流程，掩盖配置问题。
- **建议修复方向**：解析失败时应 return False（视为不可达）。

### [45] ⏭️ set_block_proxy 与 _get_probe_client 之间存在竞态窗口

> **跳过原因**：单桌面单用户场景基本不可能出现。需用户切换代理设置的瞬间并发触发网络探测，窗口极短，概率极低。

- **模块**：network-detection
- **文件**：`app/network/probes.py:68-82`
- **分类**：可靠性
- **描述**：set_block_proxy 先用 _proxy_lock 修改 _block_proxy，释放后再用 _probe_lock 关闭并置空 _probe_client。两把锁之间有一个窗口：线程 A 刚改完 _block_proxy 还未关闭 client 时，线程 B 调用 _get_probe_client 可能命中旧 client 并返回，随后该 client 被 A 关闭，B 的请求将使用已关闭的 Client 抛异常。
- **影响**：代理设置切换瞬间并发的探测请求可能拿到即将关闭的 Client，触发 httpx.ClientClosedError，导致单次检测误判失败。
- **建议修复方向**：用单一锁同时保护 _block_proxy 与 _probe_client 的读写。

### [46] fetchBrowsers 中 browser_channel 拼写为 browser_channels 导致后端当前浏览器无法同步

- **模块**：frontend-vue
- **文件**：`frontend/js/methods/ui.js:116-135`
- **分类**：可靠性
- **描述**：第 128 行写的是 this.config.browser.browser_channels = data.current（带 s），但 DEFAULT_CONFIG、config.js、settings-browser.html 全部使用 browser_channel（单数）。该赋值实际在 config.browser 上新增了一个无效属性 browser_channels，真正的 browser_channel 字段保持旧值不变。
- **影响**：后端检测到的 current 浏览器无法同步到 config.browser.browser_channel；保存配置时旧 browser_channel 会被回传后端。
- **建议修复方向**：将第 128 行的 browser_channels 改为 browser_channel。

### [47] extractApiError 未提取 error.response.data.message，后端业务错误用户只能看到通用回退文案

- **模块**：frontend-vue
- **文件**：`frontend/js/methods/utils.js:7-18`
- **分类**：可靠性
- **描述**：api-service.js 文档约定写操作返回 { success, message, data? }，但 extractApiError 只读取 error.response.data.detail（FastAPI 422 校验格式）和 error.message（axios 默认 'Request failed with status code XXX'），完全没有回退到 error.response.data.message。当后端以 HTTP 400/500 返回 {"success":false,"message":"端口冲突"} 这类业务错误时，detail 为 undefined，最终返回 'Request failed with status code 400' 或 fallback。
- **影响**：所有调用 extractApiError 的位置（20+ 处）在网络层错误时无法展示后端真实错误原因，用户排查体验显著下降。
- **建议修复方向**：在 return 链中加入 error?.response?.data?.message。

### [48] beforeUnmount 未释放 _focusTrapHandler，弹窗打开时卸载组件会泄漏 document keydown 监听器

- **模块**：frontend-vue
- **文件**：`frontend/js/app-options.js:265-282`
- **分类**：可靠性
- **描述**：ui.js:30 通过 document.addEventListener('keydown', this._focusTrapHandler) 注册了全局焦点陷阱监听器，该监听器仅在 closeModal()→_releaseFocusTrap() 中被移除。但 app-options.js 的 beforeUnmount 清理了 _wsRetryTimer/_dangerTimer/_toastTimer 等多个定时器和监听器，唯独没有调用 _releaseFocusTrap()。
- **影响**：若组件在弹窗打开状态下卸载，document 上的 keydown 监听器会持续存在并引用已卸载的 Vue 实例，造成内存泄漏与潜在的错误焦点跳转。
- **建议修复方向**：在 beforeUnmount 中增加 this._releaseFocusTrap && this._releaseFocusTrap()。

### [49] WS onmessage 缺少消息结构校验与未知类型告警，协议变更会静默失败

- **模块**：frontend-ws
- **文件**：`frontend/js/methods/lifecycle.js:223-234`
- **分类**：可靠性
- **描述**：onmessage 只处理 'status' 与 'log' 两种 type，其他类型直接丢弃且无任何日志；未校验 data.data 是否为对象。若后端重构广播协议，前端既不报错也不降级，问题完全不可见。当 data.data 为字符串时 {...this.status, ...data.data} 会把字符按下标铺进 status，污染状态对象。
- **影响**：后端 WS 协议任何不兼容变更都会导致前端状态/日志静默停滞，且控制台无任何线索。
- **建议修复方向**：对 data.type 走 switch 并保留 default 分支记录 warn；校验 data.data 为纯对象后再合并。

### [50] WS 状态合并与 fetchStatus 全量替换策略不一致，字段删除后本地残留旧值

- **模块**：frontend-ws
- **文件**：`frontend/js/methods/lifecycle.js:226-227`
- **分类**：可靠性
- **描述**：WS 推送走浅合并 this.status = { ...this.status, ...data.data }，而 HTTP 轮询 fetchStatus 走全量替换 this.status = data。若后端 StatusSnapshot 移除或重命名某字段，WS 合并不会清除本地对应旧字段，dashboard 持续展示陈旧值。
- **影响**：后端字段变更期间 dashboard 显示与后端真实状态不一致；类型不匹配时还会引发模板渲染异常。
- **建议修复方向**：WS status 消息改为全量替换（与 fetchStatus 对齐）。

### [51] visibilitychange 无防抖且重置 wsRetryCount，绕过 wsMaxRetries 上限

- **模块**：frontend-ws
- **文件**：`frontend/js/methods/lifecycle.js:272-285`
- **分类**：可靠性
- **描述**：页面恢复可见时直接 wsRetryCount = 0 并调用 connectWebSocket，无任何防抖。快速 Alt+Tab 会让每次切回都重置重连计数，使 wsMaxRetries=5 的上限形同虚设——后端长期宕机时只要用户偶尔回到页面就会无限重连。
- **影响**：重连次数上限被绕过，后端故障可能被掩盖为'偶发恢复'；频繁切换产生额外握手与 GC 压力。
- **建议修复方向**：对 visibilitychange 加防抖，并在重连成功（onopen）时才重置 wsRetryCount。

### [52] 重连耗尽后永久放弃，后台页面无法在后端恢复时自愈

- **模块**：frontend-ws
- **文件**：`frontend/js/methods/lifecycle.js:236-252`
- **分类**：可靠性
- **描述**：onclose 在 wsRetryCount >= wsMaxRetries 后直接 return 并提示用户刷新，不再安排任何后续重试。若用户将页面挂在后台，后端即使重启也无法自动恢复连接，唯一出口是用户手动刷新或触发 visibilitychange。
- **影响**：后端短暂重启后前端长期处于断连态，监控数据停止更新且无自动恢复。
- **建议修复方向**：耗尽后进入低频'探活'模式（如每 60s 尝试一次）。

### [53] run_sync 超时后 proc.wait() 无超时，kill 失败时永久阻塞

- **模块**：utils-shell-process
- **文件**：`app/utils/shell_policy.py:147-150`
- **分类**：可靠性
- **描述**：except subprocess.TimeoutExpired 分支中先调用 _kill_process_tree_sync(proc.pid) 再调用 proc.wait()，但 wait() 未传 timeout。若子进程因权限不足、僵尸状态或 psutil 杀进程失败而未真正退出，proc.wait() 会无限期阻塞，使 run_sync 永久挂起。
- **影响**：超时保护失效：本应在 effective_timeout 秒返回的命令变成永久挂起，占用工作线程，最终可能拖垮调度器。
- **建议修复方向**：改为 proc.wait(timeout=5)，并对二次异常做兜底。

### [54] ⏭️ 白名单仅校验 argv[0]，shell -c 的命令主体不受约束，allowlist 可被绕过

> **跳过原因**：安全漏洞（命令注入）。本地单用户使用，shell 命令由用户自配，不存在外部攻击者。

- **模块**：utils-shell-process
- **文件**：`app/utils/shell_policy.py:65-85`
- **分类**：崩溃/安全
- **描述**：validate_and_prepare 只校验 executable=argv[0] 是否在白名单，argv[1:] 完全不检查。实际调用方构造 [shell_path, '-c', command]，其中 command 为用户输入字符串。一旦白名单包含 bash/cmd.exe/python，argv[0] 必然通过校验，shell -c 后的命令体可执行任意内容，白名单等于失效。
- **影响**：命令注入防护名存实亡：任何在白名单内的解释器/shell 都可被 -c 参数携带任意命令。
- **建议修复方向**：对 shell -c 场景额外校验/转义 command 内容，或将 shell 类解释器从默认白名单移除并要求显式授权。

### [55] _cmd_stop 在进程未真正退出时仍误报"服务已停止"并清理 PID 文件

- **模块**：starter
- **文件**：`main.py:61-79`
- **分类**：可靠性
- **描述**：循环最多等待 5 秒（10×0.5s）轮询 is_service_running，无论是否 break，循环后均执行 print("服务已停止")；随后 finally 中无条件 cleanup_pid()。若目标进程 5 秒内未退出，PID 文件被清理但进程仍在运行占用端口。
- **影响**：状态不一致：进程仍在运行但报告已停止，PID 文件丢失导致 is_service_running 后续误判为未运行，重启时端口冲突却无法通过 --stop 正确停止。
- **建议修复方向**：循环结束后再次检查 is_service_running，区分"已停止"与"停止超时"，超时时不清理 PID 文件。

### [56] $UV_CMD sync 未加引号，含空格的 UV_DIR 路径会导致命令解析失败

- **模块**：starter
- **文件**：`start.sh:157`
- **分类**：兼容性
- **描述**：UV_CMD 可能是 "$UV_DIR/uv"，UV_DIR 源自 PROJECT_ROOT。在 macOS 上用户主目录或安装路径常含空格（如 /Users/My Name/Campus-Auth）。第 168 行 exec "$UV_CMD" 已正确加引号，但第 157 行 $UV_CMD sync 未加引号，bash 会按 IFS 拆分。
- **影响**：路径含空格时 uv sync 被拆成多个命令参数，依赖安装阶段直接失败。
- **建议修复方向**：统一改为 "$UV_CMD" sync。

### [57] findUv 优先复用本地 .uv/uv.exe 但不校验版本与完整性

- **模块**：starter
- **文件**：`start.go:108-125`
- **分类**：可靠性
- **描述**：findUv 顺序为 PATH → 本地 .uv/uv.exe → 下载。一旦 .uv/uv.exe 存在即直接返回，不校验是否匹配当前 uvVersion 常量（0.11.21），也不校验 SHA256。当 uvVersion 升级后，旧版 uv 仍被复用；若文件被损坏，也只在使用时才暴露错误。
- **影响**：版本漂移导致 uv sync 行为与 uv.lock 不一致；损坏的二进制导致运行时崩溃而非自动重下。
- **建议修复方向**：在 .uv 目录旁记录版本号，版本不匹配时重新下载并校验 SHA256。

### [58] launch_server 路径的 force_exit 本质仍是 os._exit，端到端测试会杀死 pytest 进程

- **模块**：starter
- **文件**：`main.py:252`
- **分类**：代码质量
- **描述**：main.py 调用 launch_server，其内部 launch_lightweight/launch_full 的 finally 块均调用 force_exit(0)。force_exit 实现为 atexit._run_exitfuncs() + os._exit(code)。虽然提取 login_runner 缓解了单元测试场景，但通过 main.py 入口的端到端测试一旦走到 finally，os._exit 会立即终止整个测试宿主进程。
- **影响**：端到端测试无法通过 main.py 入口覆盖完整启动/退出流程，测试用例连同 pytest 一起被杀死。
- **建议修复方向**：在 force_exit 中增加测试环境探测（如 'pytest' in sys.modules），测试环境下改用 sys.exit。

### [59] __aexit__ 调用 Worker 私有 _close_browser()，与模块 docstring「浏览器常驻不实际关闭」直接矛盾

- **模块**：utils-general
- **文件**：`app/utils/browser.py:1-6,116-134`
- **分类**：代码质量
- **描述**：模块 docstring 声明 BrowserContextManager 作为轻量代理，__aexit__ 仅「通知 Worker 释放引用（浏览器常驻 Worker 不实际关闭）」。但 __aexit__ 实际调用 worker._close_browser()——这是一个下划线前缀的私有方法，且会真正执行 _cleanup_browser(graceful=True) 关闭浏览器。同时 ensure_browser 自身也是「先 _close_browser 再 _start_browser」。因此每个登录周期为：close→start→使用→close，浏览器根本不常驻，与 docstring 完全相反。
- **影响**：docstring 严重误导后续开发者对浏览器生命周期的理解；每次登录都执行完整的浏览器关闭+重启（1-3 秒开销）。
- **建议修复方向**：统一 docstring 与实现：若设计为每次关闭则修正 docstring 并改用 Worker 公开 API；若设计为常驻则 __aexit__ 不应调用 _close_browser。

### [60] force_exit 使用 CPython 私有 API atexit._run_exitfuncs()，且 suppress(Exception) 无法捕获 BaseException 与阻塞型挂起

- **模块**：utils-general
- **文件**：`app/utils/shutdown.py:24-26`
- **分类**：可靠性
- **描述**：三个问题叠加：(1) atexit._run_exitfuncs() 是 CPython 内部下划线 API，非公开接口。(2) contextlib.suppress(Exception) 只抑制 Exception 子类，若 atexit 钩子抛出 SystemExit/KeyboardInterrupt（BaseException 子类），异常会直接逃逸，os._exit(code) 永远不会执行，进程反而挂起。(3) atexit._run_exitfuncs() 同步执行所有已注册钩子，若某个钩子阻塞不返回，os._exit 不会被调用，进程死锁。
- **影响**：在 atexit 钩子抛出 BaseException 或阻塞时，force_exit 无法保证进程退出，违背「强制退出」语义。
- **建议修复方向**：对 _run_exitfuncs 调用增加超时看门狗（如 threading.Timer 强制 os._exit）；suppress 改为 suppress(BaseException)。

### [61] STEALTH_INIT_SCRIPT 将 __playwright / __pw_manual 设为 configurable:false，可能破坏 Playwright 自身属性赋值

- **模块**：utils-general
- **文件**：`app/utils/browser.py:56-58`
- **分类**：可靠性
- **描述**：使用 Object.defineProperty(window, '__playwright', {value: undefined, writable: false, configurable: false})。configurable:false 意味着该属性永远无法被 delete 或重新 defineProperty。如果 Playwright 在此 init script 之后尝试设置或重定义 window.__playwright，在严格模式下会抛出 TypeError。
- **影响**：可能导致 Playwright page-side 通信通道异常，浏览器自动化流程随机失败；在严格模式下页面 JS 报 TypeError 中断登录流程。
- **建议修复方向**：改为 configurable:true（允许后续重定义）或使用 Proxy/Getter 返回 undefined。

### [62] APP_PORT 为合法整数但超出 1-65535 范围时静默回退默认端口，无任何告警日志

- **模块**：utils-general
- **文件**：`app/utils/ports.py:26-33`
- **分类**：可靠性
- **描述**：resolve_port 在 APP_PORT 能被 int() 解析但超出 1<=port<=65535 范围时（如 APP_PORT=0、APP_PORT=99999、APP_PORT=-1），if 条件为 False，不 return，直接落到函数末尾 return _DEFAULT_PORT，中间没有任何日志输出。而 ValueError 分支（非数字）却有 warning 日志。
- **影响**：用户设置 APP_PORT=99999 时应用静默监听 50721，用户完全无感知，排障困难。
- **建议修复方向**：在 if 1<=port<=65535 后添加 else 分支记录 warning 日志。

### [63] _make_raw_engine 含 ws_broadcaster→ws_manager 重构前的废弃字段，与 conftest engine_factory 字段假设分歧

- **模块**：test-coverage
- **文件**：`tests/test_integration/test_login_flow.py:35-98`
- **分类**：代码质量
- **描述**：_make_raw_engine 仍设置了 ScheduleEngine 不再拥有的字段：_status_snapshot（属 StatusManager）、_snapshot_min_interval、_last_snapshot_time、_dashboard_sink、_empty_broadcast_queue（ws_broadcaster 重构后已废弃）、_scheduler_running/_next_schedule_tick（应为 _scheduler）。同时缺失 _status_manager 字段，靠把 _update_status_snapshot 直接 mock 掉来掩盖。
- **影响**：重构后字段假设分歧未同步，若被测代码路径访问 self._status_manager 将 AttributeError；废弃字段误导维护者。
- **建议修复方向**：删除该辅助函数，改用 test_services/conftest.py 的 engine_factory(raw=True)。

### [64] 多处用 time.sleep(0.1) 等待异步回调完成，时间敏感且无确定性

- **模块**：test-coverage
- **文件**：`tests/test_integration/test_login_flow.py:362-363,403-404,441-442,555-556`
- **分类**：代码质量
- **描述**：多个测试用 time.sleep(0.1) 等待 future 回调线程执行完毕后做清理，而非用 Event.wait(timeout=) 或 join。对比同仓库 test_engine.py 的 TestNetworkCheckBackoff 采用 callback_done Event + _wrapping_adc 模式确定性等待回调，本文件未采纳。
- **影响**：在 CI 高负载或 Windows 调度器行为不同时，0.1s 可能不足以让回调线程完成，导致后续测试读到脏状态；属于典型的 flaky 测试反模式。
- **建议修复方向**：改用 callback_done = threading.Event() 包装 add_done_callback，参照 test_engine.py 的 _wrapping_adc 模式。

### [65] 位于 test_integration 目录却用全 mock 的 _make_raw_engine，未复用同目录 conftest 的 integration_stack fixture

- **模块**：test-coverage
- **文件**：`tests/test_integration/test_login_flow.py:1-98`
- **分类**：代码质量
- **描述**：同目录其他文件全部通过 integration_stack fixture 注入真实组件栈（ProfileService+TaskExecutor+ScheduleEngine+真实 LoginBridge），仅 mock Playwright worker。唯独 test_login_flow.py 自建 _make_raw_engine 用 __new__ 跳过 __init__ 并把 orchestrator/task_executor 全部 MagicMock，本质是单元测试。文件 docstring 自称'端到端登录认证流程'但实际未走任何真实组件交互。
- **影响**：分类错位导致集成覆盖率虚高——这些路径看似被集成测试覆盖，实则只验证 mock 交互；维护者难以判断哪些场景真正走过端到端链路。
- **建议修复方向**：将需要真实组件交互的场景迁移到 integration_stack，纯单元场景移到 test_services 或显式标注。

---

## 🟡 Minor 问题

### [66] ⏭️ StatusManager.update_snapshot 并发调用时节流检查无锁保护

> **跳过原因**：单桌面单用户场景基本不可能出现。需引擎线程与 API 线程同时调用 update_snapshot 通过节流检查，概率极低；影响仅为偶发重复 WS 广播。

- **模块**：service-engine-async
- **文件**：`app/services/engine.py:105-145`
- **分类**：可靠性
- **描述**：update_snapshot 可从引擎线程和 API 线程并发调用，对 _last_snapshot_time 的读-改-写无任何锁保护。两个线程可同时通过节流检查，重复构建 StatusSnapshot 并触发重复 WS 广播。
- **影响**：偶发重复 WS 状态广播，浪费带宽与序列化 CPU；不会导致数据损坏。
- **建议修复方向**：在 _last_snapshot_time 检查与更新周围加 threading.Lock。

### [67] _handle_login 多处直接调用 cmd.response_event.set() 未做 None 检查

- **模块**：service-engine-async
- **文件**：`app/services/engine.py:635-673`
- **分类**：可靠性
- **描述**：_handle_login 第 643、648、654、658 行在拒绝路径中直接调用 cmd.response_event.set()，未检查是否为 None。而同文件的 _handle_start 和 _handle_stop 均使用 if cmd.response_event: 守卫。
- **影响**：当前无实际影响；防御性编程缺失，未来扩展时易引入 AttributeError 崩溃，且与同文件其他 handler 风格不一致。
- **建议修复方向**：统一使用 if cmd.response_event: 守卫。

### [68] LoginBridge._on_done 直接访问 retry_policy._attempt 私有属性破坏封装

- **模块**：service-engine-async
- **文件**：`app/services/engine.py:267-283`
- **分类**：代码质量
- **描述**：LoginBridge._on_done 回调中第 269、281 行的日志直接读取 self._retry_policy._attempt（下划线前缀私有属性）。retry_policy 模块未暴露公共的当前 attempt 访问器。
- **影响**：可维护性风险：内部实现变更时日志显示错误数字，违反封装约定。
- **建议修复方向**：在 MonitoredPolicy 上暴露公共只读属性 attempt（property）。

### [69] ⏭️ SchedulerService 跨线程读写状态字段无锁保护

> **跳过原因**：单桌面单用户场景基本不可能出现。需 API 线程调用 sync_state/start/stop 与引擎线程调用 should_tick/tick 同时交错，概率极低。

- **模块**：service-engine-async
- **文件**：`app/services/scheduler_service.py:21-87`
- **分类**：可靠性
- **描述**：sync_state/start/stop 由 API 线程调用，而 should_tick/tick 在引擎线程调用。_scheduler_running 和 _next_schedule_tick 的读写无任何锁。tick 中 _next_schedule_tick 的读-改-写不是原子的。
- **影响**：极端并发下调度器可能在 stop 后多执行一次 tick，或 next_tick_time 计算偏移；发生概率低但难以复现。
- **建议修复方向**：引入 threading.Lock 保护 _scheduler_running 与 _next_schedule_tick 的读写。

### [70] ⏭️ _handle_apply_profile 日志输出用户名前3字符，存在信息泄露

> **跳过原因**：安全漏洞（信息泄露）。本地单用户使用，日志文件归用户自己所有；多用户/日志采集场景才会出现泄露风险。

- **模块**：service-engine-async
- **文件**：`app/services/engine.py:728`
- **分类**：崩溃/安全
- **描述**：logger.debug 输出 new_user[:3] + "***"。虽然为 debug 级别，但若生产环境日志级别被调低或日志被采集到外部系统，会暴露部分用户名。结合 auth_url 等其他日志字段，可能被用于社工猜测完整凭据。
- **影响**：用户名前3字符及长度信息泄露，可能辅助攻击者进行凭据猜测或社工。
- **建议修复方向**：仅记录用户名是否已设置（如 '已设置'/'未设置'），不输出任何明文片段。

### [71] WaitHandler 捕获内置 TimeoutError 而非 Playwright 的超时异常

- **模块**：tasks-system
- **文件**：`app/tasks/step_handlers.py:551-555`
- **分类**：可靠性
- **描述**：except TimeoutError 捕获的是 Python 内置 TimeoutError。但 Playwright Python 的超时异常是 playwright.async_api.TimeoutError（不继承内置 TimeoutError）。因此 Playwright 超时实际落入 except Exception 通用分支，精准超时提示信息「等待元素超时 ({timeout}ms)」永远不会被使用。
- **影响**：运维与排障时无法从错误消息区分「超时」与「其他异常」，日志中丢失超时时长等关键信息。
- **建议修复方向**：导入 from playwright.async_api import TimeoutError as PlaywrightTimeoutError 并优先捕获。

### [72] ⏭️ EvalHandler 日志与返回值泄露 eval 结果前 80-100 字符，可能含敏感数据

> **跳过原因**：安全漏洞（信息泄露）。本地单用户使用，eval 脚本与日志均归用户自己；用户不会自己泄露自己的数据。

- **模块**：tasks-system
- **文件**：`app/tasks/step_handlers.py:615-626`
- **分类**：崩溃/安全
- **描述**：EvalHandler.execute 在 logger.debug 输出 store_as 变量名及 result 的前 80 字符；return True, result_str[:100] 将结果前 100 字符作为步骤 message 返回。eval 步骤常用于读取页面数据（如 document.cookie、localStorage.getItem('token')），这些值会同时落入 debug 日志和 API 响应。
- **影响**：若 eval 脚本返回密码、Token、Cookie、个人信息等，敏感数据会持久化到日志文件并可能通过任务执行结果接口回传给前端。
- **建议修复方向**：对 eval 结果默认脱敏，仅在显式标记 step.extra.debug=true 时输出原文。

### [73] delete_task 对 "default" 的保护为大小写敏感，Windows 下可绕过

- **模块**：tasks-system
- **文件**：`app/tasks/manager.py:423-428`
- **分类**：兼容性
- **描述**：delete_task 第 425 行 if normalized == "default": return False 使用严格字符串比较。但 TASK_ID_PATTERN 允许任意大小写字母开头，因此 "Default"、"DEFAULT" 均通过 is_valid_task_id 校验。在 Windows（及 macOS 默认）文件系统大小写不敏感时，Default.json 会命中已存在的 default.json，导致保护被绕过、默认任务被删除。
- **影响**：Windows/macOS 部署下，用户可通过 delete_task_with_validation("Default") 删除受保护的默认任务。
- **建议修复方向**：对 normalized 做 .lower() == "default" 的归一化比较。

### [74] resolve_for_js 对字符串变量触发双重解析，嵌套引用时类型语义丢失

- **模块**：tasks-system
- **文件**：`app/tasks/variable_resolver.py:102-127`
- **分类**：可靠性
- **描述**：当 var_name 在 runtime_vars 且值为字符串时，会落入 resolved = self.resolve(match.group(0))，对 {{var_name}} 再做一次完整 TEMPLATE_PATTERN.sub。若该字符串本身含 {{other_var}}（嵌套引用），resolve 会递归解析 other_var；若 other_var 是非字符串（如 int 5），resolve 将其 json.dumps 为 "5"（字符串），resolve_for_js 再次 json.dumps 得到 "\"5\""（被引号包裹的字符串），而非预期的数字 5。
- **影响**：嵌套变量引用时，JS 脚本中得到的是被字符串化的值，可能导致 if ({{flag}}) 变成 if ("true") 恒真。
- **建议修复方向**：在 resolve_for_js 的 replacer 内直接处理 runtime_vars 字符串值（return json.dumps(raw)）。

### [75] ⏭️ cleanup_orphan_browsers 进程匹配规则过宽，可能误杀其他 Playwright 实例

> **跳过原因**：单桌面单用户场景基本不可能出现。需同机运行多个 Playwright 实例（如多 Campus-Auth 实例或开发工具）才会触发，单用户场景下不常见。

- **模块**：workers-playwright
- **文件**：`app/workers/playwright_worker.py:1036-1063`
- **分类**：可靠性
- **描述**：清理孤儿浏览器时仅判断进程 exe 或 cmdline 含 'ms-playwright' 且含 'chrom'/'firefox' 即 kill。该规则无法区分本应用实例与其他同机运行的 Playwright 应用（如另一个 Campus-Auth 实例、测试脚本、开发工具）启动的浏览器。
- **影响**：多实例部署或同机有其他 Playwright 用户的场景下，get_worker() 重启时会误杀他人浏览器。
- **建议修复方向**：记录本进程启动的浏览器 PID 列表，清理时仅针对该列表中已失去父进程的 PID。

### [76] _handle_browser_acquire 每次都关闭并重建浏览器，浪费资源

- **模块**：workers-playwright
- **文件**：`app/workers/playwright_worker.py:611-642`
- **分类**：性能
- **描述**：ensure_browser 无条件先 _close_browser 再 _start_browser，即使浏览器当前健康也强制重建。_handle_browser_acquire 直接调用 ensure_browser。若调用方频繁 acquire，每次都会触发完整浏览器重启。
- **影响**：不必要的浏览器进程创建/销毁增加 CPU/内存/启动延迟开销（Chromium 冷启动数百毫秒到秒级）；若调试会话进行中误触发 acquire，会中断当前 page 状态。
- **建议修复方向**：ensure_browser 内先做 _health_check，健康则直接复用 self._page，仅在不健康时才关闭重建。

### [77] ⏭️ Windows 用户名取自 USERNAME 环境变量可被伪造，icacls 授予 Full control 过宽

> **跳过原因**：安全漏洞（权限）。本地单用户使用，USERNAME 环境变量由系统设置，用户不会伪造自己的用户名；共享主机场景才会出现。

- **模块**：utils-crypto
- **文件**：`app/utils/crypto.py:93,100`
- **分类**：崩溃/安全
- **描述**：L93 优先使用 os.environ.get("USERNAME") 获取用户名，该环境变量可被父进程任意设置；L100 icacls 授予 {username}:F（Full Control），而密钥文件后续无需修改，只需读写权限即可。
- **影响**：在共享环境或被注入环境变量的场景下，可能把密钥文件权限授予非预期用户；Full Control 允许该用户修改权限位或删除文件。
- **建议修复方向**：优先使用 getpass.getuser()；icacls 改用 :M（Modify）或 :RW，最小权限原则。

### [78] ⏭️ 密钥文件目录权限未显式限制，仅限制文件本身

> **跳过原因**：安全漏洞（权限）。本地单用户使用，密钥目录归用户自己所有；多用户系统才会出现其他用户枚举风险。

- **模块**：utils-crypto
- **文件**：`app/utils/crypto.py:51,84`
- **分类**：崩溃/安全
- **描述**：L51 _KEY_DIR.mkdir(parents=True, exist_ok=True) 使用默认 mode（受 umask 影响，未显式设 0o700），仅在 L84 对密钥文件本身 chmod(0o600)。若用户 umask 为 0o000（如某些容器/CI 环境），目录权限为 0o777。
- **影响**：多用户系统上其他用户可枚举密钥文件存在性及元数据。
- **建议修复方向**：mkdir 时显式传入 mode=0o700。

### [79] _crypto_missing_warned 标志存在多线程竞态且依赖恢复后不重置

- **模块**：utils-crypto
- **文件**：`app/utils/crypto.py:37-38,147-152,182-185`
- **分类**：可靠性
- **描述**：_crypto_missing_warned 是模块级 bool，未受 _key_lock 保护。多线程同时触发 ImportError 时，两线程可能均读到 False 并各自打印一次告警（重复日志）。此外标志一旦置位永不重置，即便用户后续安装了 cryptography，标志仍为 True。
- **影响**：日志重复噪声；依赖状态变化后告警机制失效，运维误判。
- **建议修复方向**：对告警标志的检查与设置纳入 _key_lock，或在导入成功时显式重置标志。

### [80] ⏭️ 500 错误响应体包含原始异常字符串，存在信息泄露

> **跳过原因**：安全漏洞（信息泄露）。本地单用户使用，错误响应返回给用户自己；用户不会自己探测自己的内部实现。

- **模块**：api-routes
- **文件**：`app/api/config.py:33-35`（system.py:156、monitor.py:103 同样模式）
- **分类**：崩溃/安全
- **描述**：_handle_config_error 将 detail 设为 f"{operation}失败: {exc}"，把异常完整字符串返回给客户端。异常文本可能含文件路径、内部模块名、库错误细节。
- **影响**：攻击者可借异常信息探测内部实现、文件结构或依赖版本，辅助进一步攻击。
- **建议修复方向**：对外返回通用错误文案（如"操作失败，请查看日志"），将 exc 仅写入服务端日志。

### [81] set_log_level 对无效级别返回 success=True，API 契约误导

- **模块**：api-routes
- **文件**：`app/api/config.py:45-57`
- **分类**：代码质量
- **描述**：config.set_level 内部对非法级别做了降级处理，actual 与 payload.level.upper() 不等时，端点仍返回 ApiResponse(success=True, message="无效级别...已降级为...")。按 ApiResponse 语义 success=False 表示业务失败。
- **影响**：前端若仅依据 success 字段判断成败，会误认为级别设置成功。
- **建议修复方向**：对无效级别直接 raise HTTPException(400)，或在 success=False 中返回降级信息。

### [82] ⏭️ _cleanup_old_backgrounds 与并发上传存在竞态，可能误删新文件

> **跳过原因**：单桌面单用户场景基本不可能出现。单用户不会同时并发上传多个背景图。

- **模块**：api-routes
- **文件**：`app/api/tools.py:39-53`
- **分类**：可靠性
- **描述**：_save_background 先 write_bytes 写入新文件，再调用 _cleanup_old_backgrounds 遍历 BG_DIR 删除所有 name != exclude_filename 的文件。两个并发上传请求交错执行时，请求 A 写入文件后、清理前，请求 B 的清理逻辑可能把 A 刚写入的文件当作旧文件删除。
- **影响**：并发上传场景下背景图可能被误删，导致用户上传成功但随即 404。
- **建议修复方向**：为背景图操作加进程内锁，或改用"先写入临时名、原子重命名、再清理"的两阶段方案。

### [83] 广播队列满时静默丢弃消息且无日志记录

- **模块**：api-websocket
- **文件**：`app/services/websocket_manager.py:31,128,142`
- **分类**：可靠性
- **描述**：_empty_broadcast_queue（maxlen=10）和 DashboardSink.broadcast_queue（maxlen=STATUS_LOG_MAXLEN）都是 deque(maxlen=...)，满时 append 会自动丢弃最旧元素且不抛异常、不记录日志。
- **影响**：背压场景下消息被静默丢弃，运维和调试无法感知丢弃事件，难以诊断前端 dashboard 缺失消息的原因。
- **建议修复方向**：在入队时检测 len(queue) == maxlen，满时记录一次 warning 日志或计数指标。

### [84] ⏭️ frontend_log 的 level 名称经 getattr 反射可能命中非可调用属性

> **跳过原因**：安全漏洞。本地单用户使用，前端日志 level 由用户自己的浏览器发送，不存在恶意客户端。

- **模块**：api-websocket
- **文件**：`app/api/ws.py:34-41`
- **分类**：崩溃/安全
- **描述**：level_name = str(d.get("level", "INFO")).upper()，然后 getattr(fe_logger, level_name.lower(), fe_logger.info)。level 由客户端控制，若传入 "_logger"、"_min_level" 等内部属性名，getattr 可能返回非可调用对象，调用时抛 TypeError。
- **影响**：恶意或异常客户端可触发异常，虽被外层 except 捕获不会崩溃，但会产生无意义告警日志。
- **建议修复方向**：使用白名单字典映射 level 名称到日志方法，避免直接 getattr 反射。

### [85] websocket_logs_handler 的 engine 参数未使用

- **模块**：api-websocket
- **文件**：`app/api/ws.py:12`
- **分类**：代码质量
- **描述**：函数签名声明了 engine 参数，但函数体内从未引用该参数。
- **影响**：接口签名具有误导性，调用方需多传一个无用参数，增加维护成本和误用风险。
- **建议修复方向**：若确无用途，移除 engine 参数；若为预留扩展，添加占位注释说明。

### [86] _notify_drain 在 loop 关闭过程中 call_soon_threadsafe 可能抛 RuntimeError

- **模块**：api-websocket
- **文件**：`app/services/websocket_manager.py:111-116`
- **分类**：可靠性
- **描述**：_notify_drain 检查 self._loop.is_running() 后调用 call_soon_threadsafe。在 loop 正在关闭的过程中，is_running() 可能仍返回 True，但 call_soon_threadsafe 会抛 RuntimeError。DashboardSink.write 调用 _drain_notifier 时未用 try/except 包裹。
- **影响**：应用关闭期间若仍有日志写入，可能抛出未捕获的 RuntimeError，影响 loguru sink 正常工作甚至导致日志丢失。
- **建议修复方向**：在 _notify_drain 内对 call_soon_threadsafe 包裹 try/except RuntimeError。

### [87] ⏭️ set_dashboard_sink 与 _drain_queue 对 _empty_broadcast_queue 的跨线程访问无同步

> **跳过原因**：单桌面单用户场景基本不可能出现。set_dashboard_sink 通常在启动时调用一次，与 _drain_queue 并发概率极低。

- **模块**：api-websocket
- **文件**：`app/services/websocket_manager.py:118-130,166-168`
- **分类**：可靠性
- **描述**：set_dashboard_sink 迁移 _empty_broadcast_queue 时使用 while popleft，与 _drain_queue 的 popleft 可能跨线程并发（若 set_dashboard_sink 在非 asyncio 线程调用）。deque 单次操作线程安全，但多步操作非原子。
- **影响**：迁移期间若 _drain_queue 并发 popleft，可能导致消息被双方同时取走或 IndexError，造成少量消息丢失或重复。
- **建议修复方向**：迁移期间使用锁保护 _empty_broadcast_queue 访问，或确保 set_dashboard_sink 只在 asyncio 线程同步调用。

### [88] 注释声称保留 ActionResponse 别名但实际未定义，向后兼容承诺落空

- **模块**：service-core
- **文件**：`app/schemas.py:122-125`
- **分类**：代码质量
- **描述**：注释写道「ActionResponse 已合并到 ApiResponse，保留别名向后兼容 / 逐步迁移后删除此别名」，但后续并未定义 ActionResponse = ApiResponse。若有外部代码或插件依赖 from app.schemas import ActionResponse，会触发 ImportError。
- **影响**：向后兼容承诺未兑现，依赖该别名的代码会 ImportError；注释与实现不一致，误导维护者。
- **建议修复方向**：若迁移已完成，删除残留注释；若仍需兼容，补充 ActionResponse = ApiResponse 别名定义。

### [89] run() 重复实例化 ProfileService 读取日志配置，与 container 中的实例重复

- **模块**：service-core
- **文件**：`app/application.py:387-396`
- **分类**：性能
- **描述**：run() 在 logging_settings 为 None 时，临时创建 ProfileService(PROJECT_ROOT) 读取日志配置，随后 ServiceContainer.__init__ 又会创建一个 ProfileService(PROJECT_ROOT)。两次实例化重复读取 settings.json，浪费 I/O。
- **影响**：启动时多一次磁盘读取和对象创建，性能轻微浪费。
- **建议修复方向**：将日志配置读取推迟到 container 创建后复用 container.profile_service。

### [90] 请求日志中间件异常分支以 DEBUG 记录且不输出访问日志，500 错误难以追踪

- **模块**：service-core
- **文件**：`app/application.py:325-349`
- **分类**：可靠性
- **描述**：request_logging_middleware 的 except 分支使用 http_logger.debug 记录异常，且不检查 _access_log_event。成功响应以 http_logger.info 记录访问日志，但 500 异常走 except 分支，仅在 DEBUG 级别记录。当 access_log 开启时，500 请求不会出现在访问日志中。
- **影响**：开启访问日志后，500 错误请求不在访问日志中，排查问题时需要跨 logger 关联，增加运维成本；DEBUG 级别在生产默认配置下被过滤，异常可能完全无日志。
- **建议修复方向**：except 分支也应检查 _access_log_event 并以 WARNING/INFO 记录方法、路径和耗时。

### [91] delete_task 未取消运行中的任务，已删除任务继续执行并产生孤儿历史文件

- **模块**：service-core
- **文件**：`app/services/task_executor.py:143-148`
- **分类**：可靠性
- **描述**：TaskExecutor.delete_task 调用 registry.delete_task 和 history_store.delete_history，但不检查 _running_tasks 中是否有该 task_id 的运行中 Future，也不取消。若任务正在线程池中执行，删除后任务仍会运行完毕并调用 _history_store.add_record，重新创建刚被 delete_history 删除的历史文件。
- **影响**：删除正在运行的任务后，会产生无对应任务配置的孤儿历史文件；用户预期任务已删除但实际仍在执行。
- **建议修复方向**：delete_task 时检查 _running_tasks 并 cancel 运行中的 Future。

### [92] check_once 在 all_disabled 分支不更新 network_state，UI 状态显示不准确

- **模块**：service-support
- **文件**：`app/services/monitor_service.py:254-264`
- **分类**：可靠性
- **描述**：当 net_reason == 'all_disabled'（所有网络检测均未启用）时，代码仅记录日志，不调用 _update_state 更新 network_state 和 status_detail。此时 network_state 可能停留在 UNKNOWN 或上一次的 CONNECTED/DISCONNECTED，snapshot() 返回给前端的状态与实际不符。
- **影响**：前端 UI 显示的网络状态与实际配置不一致，用户误以为网络正常/异常，难以排查问题。
- **建议修复方向**：在 all_disabled 分支增加 _update_state 显式标记 network_state=UNKNOWN 和 status_detail='网络检测已禁用'。

### [93] start() 在 async 函数中同步调用 get_runtime_config() 阻塞事件循环

- **模块**：service-support
- **文件**：`app/services/debug_service.py:113-130`
- **分类**：性能
- **描述**：DebugSessionManager.start() 是 async 函数，但直接调用 monitor_service.get_runtime_config()，该方法内部执行 profile_service.load()（磁盘 I/O）+ build_runtime_config + decrypt_password_field（CPU 密集，可能调用 subprocess）。这些同步操作在事件循环线程中执行，会阻塞同一事件循环上的其他请求。
- **影响**：慢盘或加密耗时较长时阻塞事件循环，导致其他调试请求延迟响应。
- **建议修复方向**：将 get_runtime_config() 及 template_vars 构建包装在 await asyncio.to_thread(...) 中。

### [94] handle_existing_instance 在 force 模式下终止进程后未等待端口释放即继续启动

- **模块**：service-support
- **文件**：`app/services/launcher.py:196-211`
- **分类**：可靠性
- **描述**：force 模式下 _terminate_process(pid) 终止旧进程后，立即 cleanup_pid() 并 return，主流程继续向下执行 write_pid 和启动 uvicorn/容器。_terminate_process 仅等待进程退出（最多 5s），但未等待 TCP 端口完全释放。若旧进程持有 SO_REUSEADDR 未设置的监听 socket，新进程绑定同一端口时可能失败。
- **影响**：新启动的 Web 服务可能因端口占用而启动失败，用户需手动再次强制启动。
- **建议修复方向**：在 _terminate_process 后增加短暂等待或主动轮询 is_local_port_in_use(port) 直到端口释放。

### [95] ⏭️ URL 探测无内网地址过滤且 verify=False + follow_redirects=True 存在 SSRF 风险

> **跳过原因**：安全漏洞（SSRF）。本地单用户使用，探测 URL 由用户自配，不存在外部攻击者。

- **模块**：network-detection
- **文件**：`app/network/probes.py:43-52`
- **分类**：崩溃/安全
- **描述**：_get_probe_client 创建的 Client 设置 verify=False 与 follow_redirects=True，is_network_available_url/http 对配置 URL 不做内网地址校验。若配置文件被恶意篡改或用户误配 http://192.168.x.x/...，应用会代为发起请求；follow_redirects=True 还允许公网 URL 302 跳转到内网地址。
- **影响**：配置被篡改时可被利用作 SSRF 跳板探测内网服务；verify=False 进一步削弱 TLS 完整性保护。
- **建议修复方向**：对探测 URL 做 IP 解析后过滤私网/回环/链路本地地址段，重定向目标也需校验。

### [96] Windows 网关回退检测的 GBK 字节模式在 UTF-8 locale 下失效

- **模块**：network-detection
- **文件**：`app/network/detect.py:137-160`
- **分类**：兼容性
- **描述**：ipconfig 字节匹配模式中，中文'默认网关'使用 GBK 编码 \xc4\xac...。但 Windows 10/11 开启 Beta'使用 Unicode UTF-8 提供全球语言支持'后，ipconfig 输出为 UTF-8，'默认网关'编码变为 \xe9\xbb\x98...，GBK 模式无法匹配。
- **影响**：在启用 UTF-8 系统区域设置的中文 Windows 上，若 PowerShell 路径也异常，网关检测将完全失败返回 None。
- **建议修复方向**：同时匹配 UTF-8 编码的'默认网关'字节序列，或对 ipconfig 输出尝试 GBK 与 UTF-8 双解码后再用文本正则匹配。

### [97] Windows SSID 检测的 hex 解码分支会误判纯十六进制 SSID

- **模块**：network-detection
- **文件**：`app/network/detect.py:196-212`
- **分类**：兼容性
- **描述**：当 netsh 输出的 SSID 为纯 hex 字符且长度为偶数时，会尝试 bytes.fromhex 解码为 UTF-8。代码注释已承认此限制：若用户 SSID 恰好是纯 hex 字符（如 '414243'），会被误解码为 'ABC' 返回，与真实 SSID 不符。
- **影响**：纯十六进制字符命名的 SSID 会被错误上报，影响基于 SSID 的网络识别与配置匹配。
- **建议修复方向**：netsh 同时输出 'SSID' 和 'BSSID' 字段，可优先解析非 hex 的 SSID 行；或通过 'Profile' 字段交叉验证。

### [98] fetchBrowsers 与 installPlaywrightChromium 绕过 apiService 直接用原生 fetch，丢失重试拦截器

- **模块**：frontend-vue
- **文件**：`frontend/js/methods/ui.js:116-135`
- **分类**：代码质量
- **描述**：fetchBrowsers 使用 fetch('/api/browsers') 而非 this.$apiService，installPlaywrightChromium 同样使用 fetch。constants.js 中 axios api 实例配置了 GET/HEAD/OPTIONS 的 5xx 与网络错误自动重试（最多 2 次，指数退避），原生 fetch 无法享受；且 fetchBrowsers 的 catch 使用 console.error 而非 frontendLogger。
- **影响**：弱网或后端短暂重启时浏览器列表加载失败不会重试；日志未进入前端 logger 体系，排障困难。
- **建议修复方向**：将这两个调用迁移到 apiService，并将 console.error 替换为 this.frontendLogger.error。

### [99] manualLogin 的 loginCooldown setTimeout 未被跟踪，beforeUnmount 不清理

- **模块**：frontend-vue
- **文件**：`frontend/js/methods/actions.js:73-78`
- **分类**：可靠性
- **描述**：finally 块中通过 setTimeout(() => { this.busy.loginCooldown = false; }, 3000) 设置冷却定时器，但没有像 _toastTimer/_appearanceTimer 那样保存到实例属性，beforeUnmount 也没有 clearTimeout 该定时器。
- **影响**：若用户在登录后 3 秒内关闭页面或卸载组件，定时器回调仍会执行并访问已卸载实例的 busy.loginCooldown。
- **建议修复方向**：将定时器保存到 this._loginCooldownTimer 并在 beforeUnmount 中 clearTimeout。

### [100] configDirty computed 依赖非响应式的 _lastSavedConfig，保存后到 fetchConfig 完成前 dirty 指示器处于 stale 状态

- **模块**：frontend-vue
- **文件**：`frontend/js/app-options.js:123-125`
- **分类**：可靠性
- **描述**：_lastSavedConfig 定义在 configMethods 对象中，不是 data() 返回的响应式属性。configDirty 通过 JSON.stringify(this.config) !== this._lastSavedConfig 计算，Vue 只追踪 this.config 的依赖，不追踪 _lastSavedConfig。saveConfig 中先执行 this._lastSavedConfig = current，再 await this.fetchConfig(true) 重新赋值 this.config；在这两步之间，configDirty 仍返回旧的 true。
- **影响**：保存成功后到 fetchConfig 重载完成之间的短暂窗口内，UI 上的"未保存"指示器仍显示为 dirty，可能让用户误以为保存失败而重复点击保存。
- **建议修复方向**：将 _lastSavedConfig 移入 data() 使其响应式。

### [101] credentials 前端嵌套存储与后端平铺字段不一致，新增凭据字段需同时维护两处

- **模块**：frontend-vue
- **文件**：`frontend/js/methods/config.js:34-42`
- **分类**：代码质量
- **描述**：fetchConfig 将后端平铺的 data.username/password/auth_url/isp/carrier_custom 重新组装为嵌套的 config.credentials 对象；saveConfig 反向操作，仅当 _passwordChanged/_credentialsChanged 时将 config.credentials.* 拆为平铺 payload.username/password 等字段发送。DEFAULT_CONFIG.credentials 也使用嵌套结构。这种"前端嵌套 / API 平铺"的适配缺少集中映射表，完全靠手写散落的两处赋值。
- **影响**：新增一个凭据字段需要同时修改 fetchConfig、saveConfig、DEFAULT_CONFIG.credentials 三处，任一遗漏会导致该字段静默不同步。
- **建议修复方向**：抽取一个 credentials 字段映射常量，fetchConfig 与 saveConfig 共用该映射进行读写。

### [102] ⏭️ 通知图标使用 v-html 渲染，当前安全但 category 来源变化时存在 XSS 隐患

> **跳过原因**：安全漏洞（XSS 隐患）。当前无实际漏洞，category 来源为硬编码；本地单用户使用不存在外部攻击者。

- **模块**：frontend-vue
- **文件**：`frontend/partials/topbar.html:29`
- **分类**：崩溃/安全
- **描述**：topbar.html:29 <span class="notify-icon" v-if="n.icon" v-html="n.icon"></span> 将 n.icon 作为 HTML 渲染。n.icon 由 _notifyCategoryIcon(category) 返回，当前仅对六个硬编码 category 返回固定 SVG 字符串，未知 category 返回空字符串，因此当前不存在 XSS。但 notify(success, message, category, action) 是公共方法，若未来某个调用方将用户可控的字符串拼入 category 或直接传入 n.icon，v-html 会直接执行任意 HTML。
- **影响**：当前无实际漏洞；一旦 category 来源变为外部数据，可被注入 <img onerror=...> 等 payload，导致存储型 XSS。
- **建议修复方向**：将 _notifyCategoryIcon 的 SVG 改为通过 :is 动态组件或 v-if 分支渲染，移除 v-html。

### [103] beforeUnmount 对 this.timers 统一用 clearInterval，混入 setTimeout 将无法清理

- **模块**：frontend-ws
- **文件**：`frontend/js/app-options.js:277-281`
- **分类**：可靠性
- **描述**：卸载时 this.timers.forEach((t) => clearInterval(t))。当前数组里都是 setInterval（状态轮询、autostart 轮询、WS ping），所以暂无泄漏；但 timers 是个通用收纳数组，未来若有人 push 一个 setTimeout id，clearInterval 对其无效，会形成定时器泄漏。
- **影响**：未来代码演进中若向 timers 混入 setTimeout，卸载时无法清理，造成内存/回调泄漏。
- **建议修复方向**：统一记录 {id, type} 或同时调用 clearInterval/clearTimeout（二者对异类 id 互为安全 no-op）。

### [104] 重连退避上限与 ping 间隔使用硬编码魔法数，未走 TIMING 常量

- **模块**：frontend-ws
- **文件**：`frontend/js/methods/lifecycle.js:247-269`
- **分类**：代码质量
- **描述**：退避 Math.min(1000 * Math.pow(2, ...), 30000) 中的 1000 基础延迟、30000 上限，以及 ping 的 30000 间隔，均为硬编码，而项目已有 TIMING 常量模块（constants.js）。
- **影响**：调参需在多处改动，易遗漏；与既有 TIMING 风格不一致，可维护性下降。
- **建议修复方向**：将 WS_BACKOFF_BASE、WS_BACKOFF_MAX、WS_PING_INTERVAL 纳入 TIMING 常量。

### [105] WS 断连期间前端日志静默丢弃，无缓冲队列

- **模块**：frontend-ws
- **文件**：`frontend/js/logger.js:19-28`
- **分类**：可靠性
- **描述**：_sendToBackend 仅在 _ws && readyState === OPEN 时发送，否则直接丢弃，无任何缓冲。断连期间（含退避重试的数十秒）所有前端日志永久丢失，恰好是排查断连问题最需要的时段日志缺失。
- **影响**：断连时段的前端日志无法上送后端，事后排查连接问题缺少关键现场。
- **建议修复方向**：维护一个有界环形缓冲，重连成功后批量补发，超限丢弃最旧。

### [106] 定时器状态分类混乱：专用 timer 字段与通用 timers[] 双轨，且 _wsPingTimer 未声明

- **模块**：frontend-ws
- **文件**：`frontend/js/data/timers.js:1-9`
- **分类**：代码质量
- **描述**：timerData 声明了 _dangerTimer/_repoDisclaimerTimer/_toastTimer/_toastLeavingTimer 等专用字段，同时又有通用 timers[] 数组；而 _wsPingTimer（lifecycle.js 中使用并 push 进 timers[]）既未在 timerData 声明、也未被专用字段管理。此外 dashboardData 里的 fetchStatusFailCount 实属状态域却放在 dashboard。
- **影响**：新成员难以判断某个定时器该走专用字段还是 timers[]；卸载清理分散在两处，易遗漏。
- **建议修复方向**：统一策略——要么所有内部 timer 走 timers[] 并标注语义，要么全部专用字段化。

### [107] ⏭️ async_repo_fetch_json 未限制响应体大小，存在内存耗尽 DoS 风险

> **跳过原因**：安全漏洞（DoS）。本地单用户使用，repo URL 来自项目内置或用户自配，远程仓库被入侵场景不属于本地使用威胁模型。

- **模块**：utils-shell-process
- **文件**：`app/utils/repo_proxy.py:50-53`
- **分类**：崩溃/安全
- **描述**：使用 async with httpx.AsyncClient(...): resp = await client.get(url) 后直接 resp.json()，httpx 会将整个响应体读入内存且无大小上限。若远程仓库被入侵或 URL 指向恶意服务器返回超大 JSON（数百 MB~GB），主进程内存将被瞬间占满。
- **影响**：单次请求即可触发主进程 OOM 或卡死，影响所有用户；对比 tools.py 的 fetch_background_url 已用 client.stream + MAX_FILE_SIZE 限制，此处防护不一致。
- **建议修复方向**：改用 client.stream('GET', url) 配合 Content-Length 校验与分块读取上限（如 5MB）。

### [108] _kill_process_tree_sync 函数内 import psutil 且未捕获 ImportError

- **模块**：utils-shell-process
- **文件**：`app/utils/shell_policy.py:87-97`
- **分类**：可靠性
- **描述**：第 90 行在函数体内 import psutil，而第 96 行 except 子句引用 psutil.NoSuchProcess 等符号。若 psutil 因环境异常未安装或导入失败，import 抛出的 ImportError 既不在 except 列表中，又会因 psutil 未绑定导致 except 求值时再次抛 NameError，最终异常向上穿透。
- **影响**：极端环境下超时分支会抛出未预期异常，run_sync 不再返回 -1 超时码而是崩溃。
- **建议修复方向**：在模块顶层 import psutil（与 process.py 一致），或对 import 包一层 try/except 并提供 os.kill 的兜底实现。

### [109] ⏭️ get_default_shell 在 Windows 回退返回 'cmd.exe' 相对路径，存在 PATH 劫持风险

> **跳过原因**：安全漏洞（PATH 劫持）。本地单用户使用，用户自己的 PATH 环境变量不会被恶意篡改；受污染环境场景才会出现。

- **模块**：utils-shell-process
- **文件**：`app/utils/shell_utils.py:60-74`
- **分类**：崩溃/安全
- **描述**：当 pwsh.exe/powershell.exe 均未找到时直接 return 'cmd.exe' 字符串，而非 shutil.which('cmd.exe') 解析出的绝对路径。该返回值后续会进入 ShellCommandPolicy 白名单并作为 subprocess.Popen argv[0] 使用。若进程 PATH 被篡改，可能执行到伪造的 cmd.exe。Linux 分支同样在最后 fallback '/bin/bash' 但至少是绝对路径。
- **影响**：在受污染的 PATH 环境下，默认 shell 路径可能指向恶意可执行文件，绕过白名单语义。
- **建议修复方向**：Windows 回退也走 shutil.which('cmd.exe') 或硬编码 SystemRoot + \System32\cmd.exe。

### [110] is_local_port_in_use 仅探测 IPv4 127.0.0.1，IPv6 ::1 监听漏检

- **模块**：utils-shell-process
- **文件**：`app/utils/process.py:145-149`
- **分类**：兼容性
- **描述**：用 socket.AF_INET + connect_ex(('127.0.0.1', port)) 判断端口占用，仅能发现绑定到 IPv4 回环或 0.0.0.0 的监听。若本应用实例监听在 ::1（IPv6 回环）或仅绑定 IPv6 socket，探测会返回 False。
- **影响**：在双栈或纯 IPv6 配置环境下，服务存活检测失效，可能引发重复启动或 PID 文件被误清理。
- **建议修复方向**：同时探测 ('127.0.0.1', port) 与 ('::1', port)，任一连接成功即视为占用。

### [111] ⏭️ verify_process_identity 在 stored_create_time=None 时跳过身份验证，存在 PID 复用风险

> **跳过原因**：安全漏洞 + 单桌面单用户场景基本不可能出现。需调用方违规传 None 且 OS 立即复用 PID，概率极低；read_pid_file 已强制要求 create_time。

- **模块**：utils-shell-process
- **文件**：`app/utils/process.py:84-106`
- **分类**：崩溃/安全
- **描述**：当 stored_create_time is None 时，函数仅检查 get_process_name(pid) 是否非空即返回 True，不再比对创建时间。虽然 read_pid_file 已强制要求 create_time 存在，但 verify_process_identity 作为 __all__ 公开 API，其他调用方若直接传入 pid 而不带 create_time，将无法防御 PID 复用。
- **影响**：PID 复用场景下误判其他进程为本应用实例，可能导致后续对无关进程做端口检查或触发错误的清理逻辑。
- **建议修复方向**：将 stored_create_time 设为必填参数，或在 None 时直接返回 False / 发出告警。

### [112] 解压后用 find+head 选择 uv 二进制，可能匹配到非主程序文件

- **模块**：starter
- **文件**：`start.sh:119-125`
- **分类**：可靠性
- **描述**：若 .uv/uv 不存在，执行 found=$(find "$UV_DIR" -name "uv" -type f | head -1)。find -name "uv" 会匹配任意名为 uv 的普通文件，head -1 取第一个，结果不确定。此外 mv 后子目录内其余文件（README 等）仍残留于 .uv 目录。
- **影响**：极端情况下移动错误的文件作为 uv 可执行体，导致启动失败；残留文件污染 .uv 目录。
- **建议修复方向**：限定 find 路径深度（-maxdepth 2）并优先匹配可执行权限文件，或直接按 uv 官方 tarball 的固定目录结构取值。

### [113] update_status 跨线程读写 self._monitoring 与 icon.title 无同步

- **模块**：starter
- **文件**：`app/system_tray.py:111-118`
- **分类**：可靠性
- **描述**：托盘线程由 self._thread 运行 self.icon.run，而 update_status 由监控/调度线程调用，二者并发访问 self._monitoring 与 icon.title。_monitoring 与 icon.title 之间无 happens-before 关系，菜单刷新可能读到不一致组合。
- **影响**：菜单状态标签与 tooltip 偶发显示与实际监控状态不符，仅视觉问题，不影响功能。
- **建议修复方向**：用 threading.Lock 保护 _monitoring 与 icon.title 的读写。

### [114] clear() 仅清除自身标志，若任一源事件仍为 set 则 is_set() 立即返回 True，clear() 形同虚设

- **模块**：utils-general
- **文件**：`app/utils/cancel_token.py:69-71`
- **分类**：代码质量
- **描述**：clear() 调用 super().clear() 只清除 CompositeCancelEvent 自身的 _flag，不修改 _sources 中任何源事件的状态。而 is_set() 在 super().is_set() 为 False 后会遍历 _sources 重新扫描——只要任一源事件仍处于 set 状态，is_set() 立即再次返回 True。文档注释未说明此限制，容易误用。
- **影响**：调用方若期望 clear() 后组合事件进入未取消状态（例如复用 handle 做新一轮登录尝试），会因源事件仍 set 而立即判定为已取消。
- **建议修复方向**：在 clear() 文档中明确说明限制，或提供 clear_all() 同时清除自身与所有源事件。

### [115] detect_browsers 缓存检查与更新位于两个独立锁块，存在 TOCTOU 竞态导致重复检测

- **模块**：utils-general
- **文件**：`app/utils/browser_registry.py:52-65`
- **分类**：性能
- **描述**：第 52-54 行在 _DETECT_CACHE_LOCK 内检查缓存有效性，若过期则释放锁执行检测（包含多次 shutil.which 与 Path.exists 文件系统调用），第 62-64 行再次获取锁写入缓存。在检测期间，其他线程同样会发现缓存过期并并行执行检测，造成重复的文件系统 I/O。
- **影响**：在向导/设置页面并发刷新时，多个线程同时执行浏览器检测，造成不必要的文件系统 I/O 与 CPU 开销。
- **建议修复方向**：将检测逻辑移入同一锁块内（双重检查模式），或使用 threading.Condition 实现 single-flight 模式。

### [116] future.result() 抛出 BaseException 时剩余 future 不会被取消，且 f.cancel() 无法停止已运行 future

- **模块**：utils-general
- **文件**：`app/utils/concurrent.py:43-77`
- **分类**：可靠性
- **描述**：两个相关问题：(1) race_first_success 的 try 块中 except Exception 只捕获 Exception 子类，若 future.result() 抛出 BaseException（如 SystemExit、KeyboardInterrupt），异常会直接逃逸，取消清理代码不会执行，剩余 future 继续在后台运行无人清理。(2) 即便走到取消逻辑，concurrent.futures.Future.cancel() 只能取消尚未开始的 future，对正在运行的 future 返回 False 且不中断执行。
- **影响**：BaseException 逃逸时后台 future 泄漏线程池资源；正常取消路径下已运行 future 仍持续消耗 CPU/网络/内存。
- **建议修复方向**：将取消清理移入 finally 块确保所有路径都执行；对已运行 future 使用可中断的执行原语实现协作式取消。

### [117] Linux 下 Chrome 检测遗漏 google-chrome-stable / chromium / chromium-browser 命令名

- **模块**：utils-general
- **文件**：`app/utils/browser_registry.py:99-123`
- **分类**：兼容性
- **描述**：_detect_chrome 在 Linux 上仅检查 _check_command_exists("google-chrome") 或 _check_command_exists("chrome")。但部分发行版（Fedora RPM、Arch AUR）实际可执行文件名为 google-chrome-stable；Chromium 在 Ubuntu/Debian 上为 chromium-browser，在 Snap/Flatpak 上为 chromium。这些均未被覆盖。
- **影响**：Linux 用户已安装 Chrome/Chromium 但向导页显示「未检测到 Chrome 浏览器」，用户体验受损；跨平台行为不一致。
- **建议修复方向**：扩展命令名列表至 ["google-chrome", "google-chrome-stable", "chrome", "chromium", "chromium-browser"]。

### [118] test_ws_broadcast_queue_default 断言逻辑过弱，与注释意图不符

- **模块**：test-coverage
- **文件**：`tests/test_services/test_engine.py:1477-1482`
- **分类**：代码质量
- **描述**：注释说明'验证 engine 不再拥有 ws_broadcast_queue 属性'，但断言 not hasattr(svc, 'ws_broadcast_queue') or isinstance(getattr(type(svc), 'ws_broadcast_queue', None), property) is False 的第二分支允许'存在该属性且不是 property'也通过。即如果有人在 ScheduleEngine 上重新引入 ws_broadcast_queue 实例属性，该测试仍会绿色。
- **影响**：无法有效守护'ws_broadcast_queue 已迁移至 WebSocketManager'这一重构成果，回归可能静默通过。
- **建议修复方向**：简化为 assert not hasattr(svc, 'ws_broadcast_queue')。

### [119] TestSavePasswordField 部分测试隐式依赖 autouse _reset_crypto_cache 但未显式声明

- **模块**：test-coverage
- **文件**：`tests/test_utils/test_crypto.py:340-360`
- **分类**：代码质量
- **描述**：test_raw_none_returns_existing、test_raw_mask_gets_encrypted 等 5 个测试未将 _reset_crypto_cache 作为参数显式请求，其中 test_raw_mask_gets_encrypted 会触发真实 encrypt_password → _derive_fernet_key → _get_or_create_key 链路。当前因 _reset_crypto_cache 是 autouse=True 才安全（会把 _KEY_DIR 重定向到 tmp_path），但依赖是隐式的。
- **影响**：若未来有人移除 autouse 或重构该 fixture，这些测试会写入真实项目目录的密钥文件，污染开发环境。
- **建议修复方向**：对触发真实加密的测试显式传入 _reset_crypto_cache 参数。

### [120] _make 中 patch 在 return 时退出，返回的 svc 上 _reload_config_internal/ProfileService 已恢复真实

- **模块**：test-coverage
- **文件**：`tests/test_services/conftest.py:40-58`
- **分类**：代码质量
- **描述**：_make 在 with(patch.object(ScheduleEngine, '_reload_config_internal', _fake_reload), patch('app.services.engine.ProfileService')) 上下文内构造 svc 后直接 return svc。with 语句在 return 时退出，patch 立即恢复，意味着返回给测试的 svc 上 ScheduleEngine._reload_config_internal 已是真实方法、app.services.engine.ProfileService 已是真实类。
- **影响**：若后续测试在 svc 返回后调用 svc._reload_config_internal() 或依赖 ProfileService 保持 mock，会执行真实逻辑产生不可预期副作用；半 mock 语义违反最小惊讶原则。
- **建议修复方向**：将 with 改为 yield 并让工厂成为生成器，或在返回前把所需 mock 显式绑定到 svc 实例属性上。

---

## 审查覆盖范围

| Review Unit | 模块 | 焦点 | 优先级 | 文件数 |
|-------------|------|------|--------|--------|
| api-routes | API 路由层 | 路由注册、Pydantic 校验、错误处理、响应模型一致性 | P1 | 8 |
| api-websocket | API 路由层 + 服务层 | WebSocket 连接管理、广播队列 drain、DashboardSink 交互 | P1 | 3 |
| service-core | 应用工厂 + DI | FastAPI 工厂、ServiceContainer 生命周期、Pydantic schemas | P1 | 6 |
| service-engine-async | 服务层 | async/await、事件循环阻塞、并发竞态、登录状态机、重试退避 | P0 | 6 |
| service-support | 服务层 | launcher 进程管理、uninstall 数据安全、profile 持久化、debug 会话 | P1 | 8 |
| network-detection | 网络检测 | TCP/HTTP/URL 探测、网关/SSID 检测、网络状态机 | P1 | 4 |
| tasks-system | 任务系统 | JSON Schema 验证、变量模板解析安全性、步骤执行顺序 | P0 | 5 |
| workers-playwright | 工作线程 + 任务 | Playwright Actor、线程安全、资源泄漏、脚本沙箱 | P0 | 4 |
| frontend-vue | 前端 | Vue 3 状态管理、API 错误处理、XSS 防护、引用完整性 | P1 | 8 |
| frontend-ws | 前端 | WebSocket 重连、消息处理、状态同步、定时器泄漏 | P1 | 4 |
| starter | 根目录 + app | Go/shell 启动器、进程管理、uv 下载安全、force_exit | P2 | 4 |
| utils-crypto | 工具模块 | 加密/解密安全、密钥管理、_DecryptionError 异常处理 | P0 | 2 |
| utils-shell-process | 工具模块 | Shell 命令执行策略、命令注入防护、repo_proxy URL 安全 | P1 | 4 |
| utils-general | 工具模块 | 并发原语取消传播、force_exit 关闭顺序、端口冲突、浏览器注册表 | P2 | 8 |
| test-coverage | 测试 | 测试覆盖率、Mock 正确性、异步测试稳定性、fixture 解构 | P2 | 8 |

## 附注

- 本报告仅列出发现，未执行任何修复
- 建议按 Critical → Major → Minor 顺序处理，优先处理未标记 ⏭️ 的待修复项
- 已跳过 32 项（5 Critical / 11 Major / 16 Minor），跳过原因为「本地单用户使用场景下用户不可能自己攻击自己」或「单桌面单用户场景基本不可能出现的并发竞态」
- 部分问题可能需要跨模块协同修复（如 force_exit/信号处理涉及 main.py、launcher.py、application.py、shutdown.py、start.go）
- 主题相关问题（非重复）已全部保留：force_exit/os._exit（3 处不同文件）、credentials 前后端结构不一致（1 处）
- 近期重构（ws_broadcaster→ws_manager、engine 合并、ConfigBuilder→函数、crypto 内联）后的残留问题已在相应 Unit 中标注

## ⏭️ 已跳过问题汇总（32 项）

| 编号 | 严重性 | 跳过类型 | 简述 |
|------|--------|----------|------|
| [1] | Critical | 安全 | 脚本任务 RCE（用户自建） |
| [2] | Critical | 安全 | cryptography 缺失明文存储（环境异常） |
| [3] | Critical | 安全 | fetch_background_url SSRF |
| [4] | Critical | 并发概率低 | update_last_run lost-update 竞态 |
| [6] | Critical | 安全 | validate_url SSRF |
| [15] | Major | 安全 | wait_url ReDoS（用户自配） |
| [16] | Major | 安全 | TaskValidator URL SSRF |
| [18] | Major | 安全 | binary_path 白名单绕过（用户自配） |
| [19] | Major | 安全 | HTTP 头注入（用户自配） |
| [23] | Major | 安全 | 非标准 KDF（密码学标准） |
| [24] | Major | 安全 | 密钥内存常驻 |
| [28] | Major | 安全 | SVG XSS（用户自上传） |
| [39] | Major | 并发概率低 | save_global_and_profile 回滚竞态 |
| [40] | Major | 安全+概率低 | _terminate_process TOCTOU PID 复用 |
| [45] | Major | 并发概率低 | set_block_proxy 与 _get_probe_client 竞态 |
| [54] | Major | 安全 | 白名单 argv[0] 命令注入（用户自配） |
| [66] | Minor | 并发概率低 | update_snapshot 节流无锁 |
| [69] | Minor | 并发概率低 | SchedulerService 跨线程无锁 |
| [70] | Minor | 安全 | 日志泄露用户名前3字符 |
| [72] | Minor | 安全 | EvalHandler 日志泄露 eval 结果 |
| [75] | Minor | 并发概率低 | cleanup_orphan_browsers 多实例误杀 |
| [77] | Minor | 安全 | Windows USERNAME 伪造（共享主机） |
| [78] | Minor | 安全 | 密钥目录权限（多用户系统） |
| [80] | Minor | 安全 | 500 错误响应信息泄露 |
| [82] | Minor | 并发概率低 | _cleanup_old_backgrounds 并发上传竞态 |
| [84] | Minor | 安全 | frontend_log getattr 反射 |
| [87] | Minor | 并发概率低 | set_dashboard_sink 跨线程访问 |
| [95] | Minor | 安全 | URL 探测 SSRF |
| [102] | Minor | 安全 | v-html XSS 隐患（当前无漏洞） |
| [107] | Minor | 安全 | async_repo_fetch_json DoS |
| [109] | Minor | 安全 | cmd.exe PATH 劫持 |
| [111] | Minor | 安全+概率低 | verify_process_identity PID 复用 |
