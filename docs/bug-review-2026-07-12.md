# Campus-Auth 功能性 Bug 审查报告

> **审查日期**: 2026-07-12
> **复核日期**: 2026-07-12（第二轮：23 个子代理逐条对照源码复核）
> **审查范围**: 全项目 Python 后端 + JS 前端（约 110 个 .py 与全部前端 JS）
> **审查方法**: 5 个子代理分模块并行审查 + 主代理对高优先级项逐行复核源码
> **复核方法**: 23 个子代理各领 1 条 bug，读取报告引用的源码行，逐条验证 claim 是否成立；B1/B4 因 429 由主代理手动复核
> **排除项（依据 `.claude/not-to-do.md`）**: 安全加固（仅监听 127.0.0.1）、单用户并发加锁、threading→asyncio 架构迁移、前端构建/TS 化、过度优化、故意保留的弃用 API 用法、已声明的设计决策（严格模式探测、凌晨暂停默认、无 monitor_config 判 True、密码掩码语义等）

---

## 一、总览

本次审查聚焦**真实功能性缺陷**（崩溃、错误行为、状态机卡死、资源泄漏、错误返回值、数据静默丢失），不计入代码味道与风格问题。

| 严重程度 | 数量 | 说明 |
|:---:|:---:|------|
| 🔴 高 | 1 | 核心功能在无感知下静默失效 |
| 🟡 中 | 7 | 特定场景下错误行为 / 设置静默丢失 |
| 🟢 低 | 15 | 边界 / 一致性 / 资源清理类，多数触发面较窄 |

> 标注 **[已复核]** 的项为主代理读取源码逐行确认；其余为子代理审查并抽样复核。

---

## 二、🔴 高严重度

### B1 — 自动切换到无效方案后，后台监控被静默杀死【已复核】
- **位置**: `app/services/engine.py:577-582`、`_handle_start:623-637`、`_handle_stop:683-692`
- **问题**: 在网络检测循环中，若 `consume_profile_switch_flag()` 为真且重载成功，代码先调用 `_handle_stop()`（把 `self._monitor_core = None`），再调用 `_handle_start()`。而 `_handle_start` 会用 `validate_env_config(self._runtime_config)` 校验**新激活方案**；若新方案凭据不完整/无效，`_handle_start` 直接 `return` 且**不再重建 `self._monitor_core`**。
- **影响**: 自动切换到一个无效方案后，`is_monitoring` 永远为 `False`，引擎循环每轮取到 `core is None` 直接 `return` —— 监控在用户完全无感知的情况下彻底停摆，断网后不会自动重连。这是核心功能的静默失效。
- **修复**: 不要「先 stop 再赌 start 成功」。应先构造新 core（含 `validate_env_config` 校验），仅当新 core 初始化成功后再替换 `self._monitor_core`；校验失败则保留旧 core 继续运行，并回退 `active_profile`。

---

## 三、🟡 中严重度

### B2 — `login_once` 模式下配置错误被误判为「临时失败」，不再报错退出【已复核】【二轮复核：确认】
- **位置**: `app/services/login_runner.py:14-56`、`app/services/launcher.py:181-189`
- **问题**: `execute_login_with_retries` 只返回 `SUCCESS` 或 `TEMPORARY_FAILURE`，**从不返回 `CONFIG_ERROR`**。`LoginOrchestrator.submit()` 虽调用 `validate_login_config()`，但校验失败时 `handle.result()` 返回 `(False, reason)`，被 `execute_login_with_retries` 统一归为 `TEMPORARY_FAILURE`。`handle_startup_action` 对 `TEMPORARY_FAILURE` 的处理是「继续启动监控」（`launcher.py:188-189` 返回 `(CONTINUE, True)`）。
- **影响**: 用户以 `--startup-action login_once` 运行且账号密码配错时，不会收到任何配置错误提示，而是静默转入常驻监控并带着错误凭据无限重试。
- **修复**: 在 `execute_login_with_retries` 开头调用 `validate_login_config(runtime_config)`，凭据不完整时直接返回 `LoginResult.CONFIG_ERROR`；或在 `LoginOrchestrator` 提交结果里区分「配置类失败」与「网络类失败」并上抛。
- **二轮复核修正**: 原报告称「函数 docstring 声称凭据缺失应返回 CONFIG_ERROR」不准确——`execute_login_with_retries` 的 docstring 仅列出 SUCCESS/TEMPORARY_FAILURE；列出 CONFIG_ERROR 的是 `run_login_then_exit` 的 docstring。实际 bug 行为（配置错误被吞为临时失败）仍然成立。

### B3 — 全部网络检测关闭时，登录后成功校验误判为「失败」【已复核】
- **位置**: `app/tasks/browser_runner.py:336-343` + `app/network/decision.py:105-107`
- **问题**: 监控设置里 TCP/HTTP/URL 三种检测全部关闭时，`check_network_status` 返回 `(False, "all_disabled", "none")`。`browser_runner._network_detection_check` 直接 `return ok`，于是已成功的登录被判定为失败，触发错误截图与「网络仍不可达」提示。
- **说明**: 此路径与 `login_runner.py:90-93` 对 `all_disabled` 的「假定已连接 → 跳过」处理**相互矛盾**。不是 not-to-do 中的「无 monitor_config 判 True」那条（那是另一条路径）。
- **影响**: 关闭全部网络检测方式后，每次自动登录即便实际成功也被记为失败，造成重复登录与告警噪声。
- **修复**: `_network_detection_check` 中遇 `status == "all_disabled"` 直接 `return True`（视为无法验证、信任登录步骤本身），与 `login_runner` 保持一致。

### B4 — `wait_url` 步骤忽略 `step.frame`，iframe 内 URL 轮询失效【已复核】
- **位置**: `app/tasks/step_handlers.py:601`（对比同文件 `InputHandler`/`ClickHandler`/`SelectHandler` 均先 `ctx = await self._resolve_frame(page, step)`）
- **问题**: `WaitUrlHandler.execute` 始终用 `page.url`（主框架 URL），唯独没有先 `_resolve_frame`。当 `wait_url` 步骤 target 的 URL 变化发生在 iframe 内时，它轮询的是错误的 URL。
- **影响**: iframe 门户场景下 `wait_url` 步骤要么永远不匹配直到超时，要么误匹配主页面 URL，导致登录流程卡死或误判成功。
- **修复**: 与其它 handler 一致，`ctx = await self._resolve_frame(page, step)` 后使用 `current_url = ctx.url`。

### B5 — 前端手动登录超时短于服务端（含重试），导致误报失败 / 重复点击【已复核】【二轮复核：确认】
- **位置**: `frontend/js/methods/actions.js:64-65` + `frontend/js/api-service.js:33`；后端 `app/api/monitor.py:60`、`app/services/engine.py:1064-1066`
- **问题**: 前端 `manualLogin` 超时取 `this.config.browser.login_timeout * 1000`（默认 90s）。后端 `/api/actions/login` 是**阻塞式**执行：`asyncio.to_thread(svc.run_manual_login)` 在线程中同步运行。编排器按 `max_retries=3`、`retry_interval=5s`、单次 `login_timeout=90s` 执行，理论最坏 280s；但后端 dispatch 超时为 `max(login_timeout, 60) + 10` = 100s（默认值），会提前截断。**前端 90s abort，后端 100s 超时**，用户先看到「失败」而服务端仍在跑。此外 `run_manual_login` 仅在自身超时时调用 `cancel_login()`，前端断开连接不会中止已提交的登录会话。
- **影响**: 用户先看到「失败」提示，服务端仍可能在剩余 10s 内登录成功并通过 WS 广播；易诱发用户重复点击造成重复登录。当 `login_timeout` 调大（上限 600s）时，前后端差距成比例放大。
- **修复**: 前端 timeout 覆盖后端 dispatch 窗口，或后端改为「立即返回、结果走 WS 推送」。
- **二轮复核修正**: 原报告称「最坏约 4–5 分钟」不准确——默认配置下后端 dispatch 超时将其截断至 ~100s，非 280s。核心 bug（前端先于后端 abort）仍然成立。

### B6 — 自启动模式切换始终返回 `success=True`，配置写入失败被静默吞掉【已复核】
- **位置**: `app/api/autostart.py:30-48, 90-103`
- **问题**: `set_autostart_mode` 无条件 `return ApiResponse(success=True, ...)`；真正落盘的 `_save_runtime_mode` 把异常 `except` 后仅 `warning` 吞掉、不返回任何状态。
- **影响**: 当配置写入失败（磁盘/权限/序列化）时，用户被告知「模式已切换」，但设置未持久化；下次开机仍用旧模式 —— 设置静默丢失。
- **修复**: `_save_runtime_mode` 返回 `bool`；`set_autostart_mode` 据其返回 `success`（与 `enable/disable` 端点保持一致）。

### B7 — `select` / `click_select` 在 `value` 为空或含未解析变量时即便 `required` 也静默跳过【已复核】
- **位置**: `app/tasks/step_handlers.py:364-367`（`SelectHandler`）、`466-469`（`ClickSelectHandler`）
- **问题**: `if not value or "{{" in value: return True, ""` 在 `_find_element` 之前，且未判断 `step.required`。当 `value` 因变量未解析（仍是 `{{VAR}}`）或为空时，步骤直接成功返回。
- **影响**: 关键下拉/选择步骤在变量缺失时悄悄通过，导致登录表单漏填却被判为成功，可能让「成功」的登录实际是半成品。
- **修复**: 若 `step.required`，此处应 `return False, "value 为空/未解析"`；仅非 required 才跳过。

### B8 — SOCKS5 中继半关闭（half-close）处理错误，丢失对端剩余数据【已复核】
- **位置**: `app/network/proxy.py:165-187`（`_relay`）
- **问题**: 任意一端 `recv` 返回 `b""`（EOF）时 `_relay` 立即 `return`，**直接丢弃另一端可能仍在发送的数据**，且未对另一端 `shutdown(SHUT_WR)`。典型场景：客户端先发完 EOF、服务端回包尚未读完即被截断。
- **影响**: 仅影响「网卡绑定（nic-binding）」模式下的 SOCKS5 转发，表现为上传型请求后响应数据被截断。
- **修复**: 某侧 EOF 时对该侧 `shutdown(SHUT_WR)` 并继续从对侧读取，直到对侧也 EOF 才退出；不要在首次 EOF 时 `return`。

---

## 四、🟢 低严重度（含一致性与资源清理）

### B9 — `start_monitoring` 已运行时返回 `False`，与 `_handle_start` 语义相反【已复核】
- **位置**: `app/services/engine.py:1004-1010` vs `623-629`
- **问题**: 二者对「已在运行中」的返回分别是 `(False, "监控已在运行中")` 与 `(True, "监控已在运行中")`。API 若经由 `start_monitoring()` 重复启动时拿到 `ok=False`，被误判为「启动失败」。
- **修复**: 将 `start_monitoring` 的返回值改为 `(True, "监控已在运行中")`，使重复启动成为无害幂等成功。

### B10 — 切换/重载时若网卡绑定变化，重建代理会清零累计计数器【已复核】
- **位置**: `app/services/engine.py:_handle_reload:757-760`、`_handle_apply_profile:798-801`
- **问题**: 监控运行中且 `bind_interface_name` 变化时，代码 `core.stop_monitoring(); core.init_monitoring()`。而 `init_monitoring` 会重置 `network_check_count/login_attempt_count/start_time`。
- **影响**: 仪表盘的「检测次数 / 登录尝试 / 运行时长」在改绑网卡后被静默清零（触发面窄：仅当用户修改 `bind_interface_name`）。
- **修复**: 重建前保存、重建后恢复这些累计字段；或仅重启 SOCKS5 forwarder 不调 `init_monitoring`。

### B11 — Worker 提交超时只放弃等待，并不真正中断正在执行的命令【已复核】
- **位置**: `app/workers/playwright_worker.py:311-314`
- **问题**: 超时后仅置 `cmd.cancelled = True` 返回失败，但 `cancelled` 只在 `_dispatch` **开头**被检查。命令已通过检查、正在执行（如一次数分钟的登录）时，超时不中止底层执行，且后续提交会在唯一命令队列上串行阻塞。
- **影响**: 「命令超时」形同虚设，真正的登录仍占用队列，后续命令排队；期间 UI 已显示超时。
- **修复**: 将取消信号传入执行体（如 `LoginSession.cancel_event`），`submit` 超时应 `cancel_event.set()`，执行循环周期性检查以真正中断。

### B12 — 脚本任务的取消事件未透传给 `ScriptRunner`，运行中无法中断【已复核】
- **位置**: `app/services/task_executor.py:_execute_script`（约 301-325）
- **问题**: `cancel_event` 已传入 `execute_task`，但构造 `ScriptRunner` 时未透传（对比浏览器任务会把 cancel 经 orchestrator 进 Worker）。用户删除/停止脚本任务时 `future.cancel()` 对已执行线程无效，且 `ScriptRunner` 不观测该事件。
- **影响**: 停止/删除脚本任务后，脚本仍在后台跑到结束，资源不释放，可能并发重复执行。
- **修复**: 将 `cancel_event` 透传给 `ScriptRunner`（`run()` 入参），在脚本执行循环中周期检查 `is_set()` 提前退出。

### B13 — `debug_service.run_all` 跨锁窗口可能重复执行步骤【已复核】
- **位置**: `app/services/debug_service.py:run_all`（约 277-289）
- **问题**: `from_idx = session.current_step` 在持 `_lock` 时捕获，但释放 `_lock` 到获取 `_exec_sem` 之间存在空窗；若此时 `next_step` 抢到 `_exec_sem` 推进了 `current_step`，`run_all` 仍从旧 `from_idx` 开始，会重跑已执行步骤（如重复提交登录）。
- **影响**: 仅当用户同时点「单步执行」与「全部运行」时触发，概率低。
- **修复**: `async with self._lock, self._exec_sem:` 同时持两锁，或获取 `_exec_sem` 后重新读 `from_idx = session.current_step`。

### B14 — 解密失败标记为全局单一标志，可能误伤其它有效方案【已复核】
- **位置**: `app/utils/crypto.py:35,240-260` + `app/utils/config_utils.py:42-45`
- **问题**: `_decryption_failed` 是模块级单例 `Event`，任一密码解密失败即 `set`，仅当某次解密**成功**才 `clear`。`validate_env_config` 用 `has_decryption_error()` 作为「整份配置无效」的硬判据。多方案下，某方案密码损坏会置位全局标志，在活跃方案解密成功清空标志之前的窗口内，可能让一份本有效的配置被判为无效而无法启动。
- **影响**: 实际触发依赖加载/校验时序，属窄场景，但语义上「全局标志」不应决定「当前方案」的合法性。
- **修复**: 让 `decrypt_password_field` 在调用点返回该字段是否失败，按方案粒度本地判定，避免用全局标志阻断整体校验。

### B15 — `compare_versions` 解析失败返回 `0`（相等），吞掉更新提示【已复核】
- **位置**: `app/version.py:50-52`；调用方 `app/api/system.py:100`（`has_update = compare_versions(tag, current) > 0`）
- **问题**: 远端 tag 解析失败（如 `lstrip("v")` 后为空/非法）时返回 `0`，被当作「等于当前版本」，更新通知被静默抑制。
- **修复**: 解析失败不应等同「相等」；返回哨兵/`None` 由调用方显式决定，或仍 `warning` 后回退到「有更新需提示」的安全侧。

### B16 — PID 文件未记录端口，自定义 `APP_PORT` 下可能误删有效 PID【已复核】
- **位置**: `app/utils/process.py:113-146`（仅存 `mode`，未存 `port`）
- **问题**: `is_service_running` 的端口校验用 `resolve_port()` 从「当前进程环境变量」重新推导端口，而非读取运行实例实际端口。若运行实例用了与检查者不同的自定义 `APP_PORT`，端口校验命中错误端口 → 误报「未运行」并删除有效 PID 文件，进而可能拉起第二个实例。
- **影响**: 仅当用户跨进程使用不同自定义 `APP_PORT` 时触发（窄场景），但后果是双实例/状态混乱。
- **修复**: `write_pid` 把 `port` 写入 PID 文件，`is_service_running` 用 `data.get("port")` 校验。

### B17 — `dir_size_mb` 把目录也算进 `max_entries` 配额，导致容量低估【已复核】
- **位置**: `app/utils/files.py:111-143`
- **问题**: `for f in p.rglob("*"): if f.is_file(): total += ...; count += 1` —— `count` 对文件**和目录**都自增，且每个文件还做了一次多余 `is_file()`+`stat()` 双 stat。当目录含大量子目录时，预算被目录耗尽而字节数为 0，返回偏小的 `size_mb` 与 `complete=False`。
- **修复**: `if f.is_file(): total += f.stat().st_size; count += 1`，仅文件计入配额。

### B18 — 普通 HTTP 探测目标返回 3xx 被误判为「网络断开」【已复核】
- **位置**: `app/network/probes.py:387-408`（结合 `decision.py:236` `follow_redirects=not enable_tcp`）
- **问题**: 当 `enable_tcp=True` 时 HTTP 探测 `follow_redirects=False`；若默认探测目标返回 301/302（如 http→https 重定向），`ok = 200 <= status < 300` 为 `False`，该探测判失败。严格模式（AND）下整体判「网络断开」，触发多余登录。
- **修复**: 连通性判定应包含 3xx（`200 <= status < 400`），或对非 captive 目标始终 `follow_redirects=True`。

### B19 — `resolve_for_js` 按字典顺序替换，变量值互相包含占位符时破坏 JS 语法【已复核】
- **位置**: `app/tasks/variable_resolver.py:142-147`
- **问题**: 按 `known_vars` 字典任意顺序做字符串 `.replace`。若变量 `A` 的值是 `"prefix{{B}}suffix"`，先替换 `{{A}}` 会得到含 `{{B}}` 的 JSON 字符串，再替换 `{{B}}` 时在引号内插入值及多余引号，破坏注入 JS 的语法。
- **影响**: 多变量且值互相包含占位符时，注入脚本出现 JS 语法错误，步骤失败。
- **修复**: 先递归解析所有已知变量值，再统一替换；或按占位符长度降序替换。

### B20 — `is_network_available` 在全部检测关闭时返回 `True`，与 `check_network_status` 不一致【已复核】
- **位置**: `app/network/decision.py:180-213`（`is_network_available` 分支 vs `check_network_status:105-107`）
- **问题**: 两函数对同一「全部关闭」条件分别返回 `True` 与 `(False, "all_disabled", ...)`。当前 `is_network_available` 该分支因调用方守卫不触发，但直接被外部调用时会误报「网络已连通」，可能跳过本应触发的登录。
- **修复**: 与 #B3 一并统一——全部关闭时返回能表达「未知/跳过」的语义，而不是 `True`。

### B21 — `scheduled_tasks.update_scheduled_task` 仅深度合并 `schedule`，其它嵌套字典被整体覆盖【已复核】
- **位置**: `app/api/scheduled_tasks.py:58-60`
- **问题**: `merged = {**existing, **payload}` 后再只对 `schedule` 做深合并。若任务有其它嵌套 dict 字段且客户端局部更新其一，未传的子键会丢失。
- **修复**: 对 payload 中每个嵌套 dict 键都做 `{**existing.get(k, {}), **payload[k]}` 深合并。

### B22 — `ocr_uninstall` 缺少 `subprocess.TimeoutExpired` 处理，与 `ocr_install` 不一致【已复核】
- **位置**: `app/api/ocr.py:107-135`（对照 `ocr_install` 已处理）
- **问题**: `uv remove` 超 60s 时抛 `TimeoutExpired`，`ocr_uninstall` 仅捕获 `FileNotFoundError`/`Exception`，落到 `raise HTTPException(500)`，给出不友好的 500。
- **修复**: 复用 `ocr_install` 的 `except subprocess.TimeoutExpired` 分支。

### B23 — 密码 `""` 与 `None` 语义在文档与实现不一致（清除路径已失效）【已复核】
- **位置**: `app/schemas.py:403,425` 注释写 `""` 表示清空；`app/utils/crypto.py:271` 实现把 `None` 与 `""` 都当「不修改」
- **影响**: 当前 UI 只发 `null`，无现网损坏；但文档承诺的「传空字符串清空密码」是死路径，未来任何直接传 `""` 的调用方会被静默忽略。
- **修复**: 要么让 `save_password_field` 把 `""` 视为清空（加密空串→清空），要么修正 docstring 说明 `""` = 不修改。

---

## 五、本次未计入的项（已排除，依据 not-to-do.md）
- 安全加固类（API 鉴权/CORS/SSRF/输入消毒/路径遍历/沙箱）—— 应用仅监听 127.0.0.1，且用户拥有整机权限。
- 单用户并发加锁、`asyncio.get_event_loop` 等已被安全使用的弃用 API。
- threading→asyncio 迁移、模块拆分、前端 TS/构建化、前端过度优化。
- 已声明的设计决策：严格模式网络探测（任一失败即 False）、凌晨暂停默认启用、无 monitor_config 时登录判 True、DOM detached 由 GC 回收、CLOSE-then-RELEASE 顺序等。

---

## 六、修复优先级建议

| 优先级 | 项 | 工作量估计 |
|:---:|------|:---:|
| P0（尽快） | **B1** 自动切换无效方案致监控静默死亡 | ~2h |
| P1（短期） | B2、B3、B4、B5、B6、B7、B8 | 各 0.5–1.5h |
| P2（日常迭代） | B9–B23 其余一致性 / 清理类 | 各 0.25–1h |

> 与既有 `docs/code-audit-report.md` / `docs/code-review-verified-report.md` 的关系：本报告为**独立重新审查**，聚焦功能性缺陷。B15（compare_versions）等少数项与历史报告重叠；其余（B1/B2/B3/B4/B5/B6/B7/B8/B11/B12/B16/B17/B18/B19 等）为本次新发现或此前未强调的实际行为缺陷。

---

## 七、二轮复核结果（2026-07-12）

23 个子代理各领 1 条 bug，读取报告引用的源码行逐条验证。B1/B4 因 429 限流由主代理手动复核。

| Bug | 结论 | 备注 |
|:---:|:---:|------|
| B1 | ✅ 确认 | `_handle_stop` 置 `core=None`(692行)，`_handle_start` 校验失败直接 return(633-637行) 不重建 core |
| B2 | ✅ 确认 | 行为确认；**修正**：docstring 描述不准确（CONFIG_ERROR 列在 `run_login_then_exit` 而非 `execute_login_with_retries`） |
| B3 | ✅ 确认 | `check_network_status` 返回 `(False, "all_disabled")`，`browser_runner` 未处理直接返回 `ok=False`，与 `login_runner`/`monitor_service` 矛盾 |
| B4 | ✅ 确认 | `WaitUrlHandler` 601行用 `page.url`，其它 6 个 handler 均调用 `_resolve_frame` |
| B5 | ✅ 确认 | 核心 bug 确认；**修正**：原称「最坏 4–5 分钟」不准确，后端 dispatch 超时 `max(login_timeout,60)+10`=100s 会截断，前端 90s 先 abort，差距 ~10s |
| B6 | ✅ 确认 | `set_autostart_mode` 无条件 `success=True`，`_save_runtime_mode` 异常被 except 吞掉 |
| B7 | ✅ 确认 | `SelectHandler:365`/`ClickSelectHandler:467` 的 `if not value or "{{" in value: return True` 不检查 `step.required` |
| B8 | ✅ 确认 | `_relay` 179行 `if not data: return` 立即退出，无 `shutdown(SHUT_WR)`，不继续读对端 |
| B9 | ✅ 确认 | `start_monitoring` 返回 `(False, ...)` 而 `_handle_start` 返回 `(True, ...)` |
| B10 | ✅ 确认 | `stop_monitoring` + `init_monitoring` 重建时 `init_monitoring` 重置 `network_check_count/login_attempt_count/start_time` |
| B11 | ✅ 确认 | 超时仅置 `cmd.cancelled=True`，已执行命令无法中断 |
| B12 | ✅ 确认 | `cancel_event` 未传给 `ScriptRunner`，脚本任务无法中途取消 |
| B13 | ✅ 确认 | `_lock`→`_exec_sem` 之间有空窗，`next_step` 可推进 `current_step` 导致 `run_all` 重跑 |
| B14 | ✅ 确认 | 模块级 `_decryption_failed` Event 单例，任一解密失败全局置位，影响所有方案校验 |
| B15 | ✅ 确认 | `compare_versions` 解析失败返回 `0`，`> 0` 为 False，更新通知被抑制 |
| B16 | ✅ 确认 | PID 文件仅存 `mode` 不存 `port`，`is_service_running` 从当前进程 env 推导端口 |
| B17 | ✅ 确认 | `count += 1` 在 `if f.is_file()` 块外，目录也计入配额；`f.is_file()` + `f.stat()` 双 stat |
| B18 | ✅ 确认 | `follow_redirects=not enable_tcp` 时 3xx 返回 `ok=False`，误判网络断开 |
| B19 | ✅ 确认 | `resolve_for_js` 按 dict 插入顺序做 `str.replace`，`template_vars`/`runtime_vars` 值未预解析，嵌套占位符破坏 JS 语法 |
| B20 | ✅ 确认 | `check_network_status` 返回 `(False, "all_disabled")` 而 `is_network_available` 返回 `True`，语义矛盾 |
| B21 | ✅ 确认 | 仅 `schedule` 字段深合并，其它嵌套 dict 被浅覆盖（当前无实际受害者字段） |
| B22 | ✅ 确认 | `ocr_uninstall` 缺少 `TimeoutExpired` 处理，`ocr_install` 有 |
| B23 | ✅ 确认 | schemas 注释 `""` 表示清空，`save_password_field` 把 `""` 当「不修改」 |

**结论：23/23 全部确认存在。** B2、B5 有描述细节修正（见对应条目的「二轮复核修正」），实际 bug 行为不变。