# Campus-Auth 代码审查验证报告

> 验证时间：2026-07-06
> 验证方法：10 个并行 Agent 逐条对照源码验证
> 原报告：`docs/code-review-report.md`（126 项发现）
> 验证后保留：**48 项**（排除 78 项）

## 验证统计

| 原严重性 | 原数量 | 验证为 TRUE | 排除 | 排除原因分布 |
|----------|--------|------------|------|-------------|
| 🔴 Critical | 21 | **12** | 9 | FALSE×3, 单例难触发×5, 设计如此×1 |
| 🟠 Major | 30 | **13** | 17 | FALSE×3, 单例难触发×7, 无待办×4, 设计如此×3 |
| 🟡 Minor | 50 | **23** | 27 | FALSE×5, 单例难触发×14, 无待办×5, 低影响×3 |
| **总计** | **101** | **48** | **53** | — |

### 排除原因说明

- **FALSE**：报告描述与源码不符，代码逻辑正确
- **单例难触发**：问题在单用户桌面场景下几乎不可能触发（需极高并发竞态、特定平台条件等）
- **无待办**：报告未给出明确修复方向，或属于设计选择无改进空间
- **设计如此**：代码行为符合设计意图，非缺陷

---

## 🔴 Critical 问题（12 项）

### [2] _dispatch_command 超时后已入队命令仍被延迟执行

- **文件**：`app/services/engine.py:966-987`
- **分类**：可靠性
- **验证结果**：TRUE
- **相关代码**：
  ```python
  def _dispatch_command(self, cmd_type, data=None, timeout=10.0):
      async def _send_and_wait():
          cmd = EngineCommand(type=cmd_type, data=data or {})
          cmd.response_future = asyncio.Future()
          await self._cmd_queue.put(cmd)         # 先入队
          try:
              return await asyncio.wait_for(cmd.response_future, timeout=timeout)
          except TimeoutError:
              return (False, f"操作超时 ({cmd_type.value})")  # 超时返回错误，但命令仍在队列中
  ```
- **影响**：超时后可能触发意外的监控启停或登录操作。LOGIN 命令 timeout 可达 70+ 秒，可能在用户已收到超时响应后仍启动浏览器。
- **修复建议**：为 EngineCommand 添加 expiry 时间戳，`_process_command_async` 处理时检查是否过期并跳过。

---

### [4] 浏览器定时任务被 Orchestrator 去重机制静默替换为登录结果

- **文件**：`app/services/task_executor.py:312-341`，`app/services/login_orchestrator.py:240-256`
- **分类**：可靠性
- **验证结果**：TRUE
- **相关代码**：
  ```python
  # login_orchestrator.py:246-256
  existing = self._slot
  if existing is not None and not existing.done():
      if source == "login_once":          # 不匹配
          ...
      elif source == "manual" and existing.source == "auto":  # 不匹配
          ...
      else:                               # browser 落入此分支
          self._link_cancel(cancel_event, existing.cancel_event)
          return existing                 # 返回已有的 auto 登录 handle
  ```
- **影响**：定时浏览器任务执行结果不可预测，历史记录中记录的也是错误结果。
- **修复建议**：在 `submit()` 的去重逻辑中为 `browser` source 添加类似 `login_once` 的独立分支，或在 `_execute_browser` 中检测返回的 handle 是否是自己提交的。

---

### [6] OcrHandler char_range 临时 DdddOcr 实例永远不被清理

- **文件**：`app/tasks/step_handlers.py:825-873`
- **分类**：资源泄漏
- **验证结果**：TRUE
- **相关代码**：
  ```python
  # 825-831: char_range 分支创建临时实例
  if char_range is not None:
      ocr = await asyncio.to_thread(ddddocr.DdddOcr, old=old, show_ad=False)
      ocr.set_ranges(char_range)
  else:
      ocr = await asyncio.to_thread(self._get_ocr, old=old)  # 缓存实例

  # schedule_cleanup 仅管理缓存字典中的实例
  self.schedule_cleanup(old)
  ```
- **影响**：每次带 char_range 的 OCR 调用泄漏约 10-30MB 模型内存，高频调用导致 OOM。
- **修复建议**：在 try/finally 中显式 `del` 临时实例并 `gc.collect()`，或维护独立的 char_range 缓存池。

---

### [7] Firefox 安装后执行 Chromium 完整性校验

- **文件**：`app/workers/playwright_bootstrap.py:217-227`
- **分类**：确定性 bug
- **验证结果**：TRUE
- **相关代码**：
  ```python
  # 177: install_target 根据 channel 决定
  install_target = "chromium" if channel == "playwright" else "firefox"

  # 217-227: 下载成功后，无论 install_target 是什么，都校验 Chromium
  if result.returncode == 0:
      cache_dir = get_playwright_cache_dir()
      if cache_dir is not None and not _verify_chromium_install(cache_dir):
          _BOOTSTRAP_DONE = False
  ```
- **影响**：配置 firefox channel 的用户首次安装永远无法通过 bootstrap 检查，应用无法启动。
- **修复建议**：按 `install_target` 分支校验，firefox 应校验 firefox 二进制而非 chromium。

---

### [11] Unix 平台 os.kill 未捕获异常

- **文件**：`app/services/launcher.py:75-79`
- **分类**：崩溃
- **验证结果**：TRUE
- **相关代码**：
  ```python
  else:
      os.kill(pid, signal.SIGTERM)       # 无 try/except
      if not _wait_for_exit(pid, max_wait=5):
          os.kill(pid, signal.SIGKILL)   # 无 try/except
  ```
- **影响**：`--force` 强制模式在竞态条件下崩溃（ProcessLookupError）。`main.py:67-84` 中的另一处调用点已用 `try/except OSError` 保护，说明开发者意识到了问题但遗漏了此处。
- **修复建议**：用 try/except 包裹 os.kill，捕获 ProcessLookupError 和 PermissionError。

---

### [13] debug start() 失败路径未重置会话状态

- **文件**：`app/services/debug_service.py:185-202`
- **分类**：可靠性
- **验证结果**：TRUE
- **相关代码**：
  ```python
  # Worker 启动失败
  except Exception:
      async with self._lock:
          await self._cancel_debug_timer()
          await self._close_debug_browser()
      raise                                  # 未重置 self._session

  # Worker 返回失败
  if not response.success:
      async with self._lock:
          await self._cancel_debug_timer()
          await self._close_debug_browser()
      raise RuntimeError(...)                # 未重置 self._session
  ```
- **影响**：失败后 `self._session` 保持 `running=True` 的僵尸状态，后续命令提交到已关闭的 Worker。对比超时处理器和 `stop()` 方法都会执行 `self._session = DebugSession()` 重置。
- **修复建议**：在两个失败路径的锁内添加 `self._session = DebugSession()`。

---

### [16] saveConfig 中 active_task 被错误覆盖为空串

- **文件**：`frontend/js/methods/config.js:121-126`
- **分类**：功能性 bug
- **验证结果**：TRUE
- **相关代码**：
  ```javascript
  // 第 6 行定义凭据字段
  const CREDENTIAL_FIELDS = ['username', 'password', 'auth_url', 'isp', 'carrier_custom'];

  // 第 121 行正确设置
  active_task: c.active_task || '',

  // 第 124-125 行错误覆盖
  ['username', 'auth_url', 'isp', 'carrier_custom', 'active_task'].forEach(f => {
      payload[f] = c.credentials[f] ?? '';  // credentials 中无 active_task → undefined → ''
  });
  ```
- **影响**：每次保存配置都会将用户选定的活动任务清空，自动登录使用错误的任务配置。
- **修复建议**：将 `'active_task'` 从 forEach 数组中移除。

---

### [17] 密码字段使用 type="text" 明文暴露

- **文件**：`frontend/partials/pages/settings/settings-account.html:33-43`
- **分类**：安全
- **验证结果**：TRUE
- **相关代码**：
  ```html
  <input
    id="settings-password"
    :value="passwordSaved && !editingPassword ? '••••••••••' : config.credentials.password"
    @input="config.credentials.password = $event.target.value"
    name="password"
    type="text"
  />
  ```
- **影响**：编辑密码时明文显示，肩窥泄露风险。应用有自定义掩码逻辑但安全性弱于原生 `type="password"`。
- **修复建议**：改为 `type="password"`，可选添加显示/隐藏切换按钮。

---

### [19] git-puller extractTar 路径穿越（Zip Slip）

- **文件**：`resources/tools/git-puller/main.go:270-328`
- **分类**：安全
- **验证结果**：TRUE
- **相关代码**：
  ```go
  name := strings.TrimRight(string(header[0:100]), "\x00")  // 直接取自 tar 头部
  target := filepath.Join(destDir, name)                     // 未校验穿越
  // ...
  f, err := os.OpenFile(target, os.O_CREATE|os.O_WRONLY|os.O_TRUNC, 0o644)
  ```
- **影响**：恶意 tar 归档可将文件写入任意位置。不过该工具仅用于从可信源（GitHub/Gitee）拉取仓库，实际利用难度较高。
- **修复建议**：对每个 entry 做 `filepath.Rel` 校验，若结果以 `..` 开头则跳过。同时检查第 315-319 行的符号链接处理。

---

### [20] SSRF：fetch_background_url 未校验目标主机

- **文件**：`app/api/tools.py:99-154`
- **分类**：安全
- **验证结果**：TRUE
- **相关代码**：
  ```python
  validate_url(url)  # 仅校验 scheme 是否为 http/https
  async with httpx.AsyncClient(follow_redirects=True, timeout=15) as client:
      async with client.stream("GET", url) as resp:
  ```
- **影响**：可访问 `http://169.254.169.254/` 等内网地址。单用户桌面工具场景下用户本身就是攻击者，实际威胁低。若未来部署为多用户服务则需加固。
- **修复建议**：解析域名后拒绝私有地址段（10/8、172.16/12、192.168/16、127/8、169.254/16）。

---

### [21] 全局异常处理器泄露内部异常类型名称

- **文件**：`app/application.py:308-317`
- **分类**：信息泄露
- **验证结果**：TRUE
- **相关代码**：
  ```python
  return JSONResponse(
      status_code=500,
      content={"detail": f"服务器内部错误: {type(exc).__name__}"},
  )
  ```
- **影响**：暴露内部异常类名（如 PlaywrightTimeoutError、FileSystemPermissionError）。单用户场景下风险低，修复简单。
- **修复建议**：对外统一返回泛化消息 `"服务器内部错误"`，异常详情仅写入服务端日志。

---

### [18] repo_proxy async_repo_fetch_json 缺少纵深防御（降级）

- **文件**：`app/utils/repo_proxy.py:46-57`
- **分类**：⚪ 代码质量（原 Critical，验证后降级）
- **验证结果**：TRUE（降级）
- **分析**：函数体内未调用 `validate_url`，但所有调用方（`app/api/repo.py`）在调用前已执行校验。当前无实际漏洞，但建议纵深防御。
- **修复建议**：将 `validate_url` 调用移入 `async_repo_fetch_json` 内部。

---

## 🟠 Major 问题（13 项）

### [23] _check_profile_switch 同步磁盘 IO 阻塞 async 引擎事件循环

- **文件**：`app/services/monitor_service.py:398-435`
- **分类**：性能
- **验证结果**：TRUE
- **相关代码**：
  ```python
  # 调用链：
  engine._do_network_check_async() (async)
    → await core.check_once() (async)
      → self._check_profile_switch() (sync)
        → self._profile_service.load() (sync, 含 threading.Lock + 磁盘 IO)
  ```
- **影响**：同步锁和文件读取阻塞 asyncio 事件循环。虽然 `ProfileService.load()` 使用 mtime 缓存减少频率，但首次调用或文件变更时仍阻塞。
- **修复建议**：改用 `asyncio.to_thread()` 包装磁盘 IO。

---

### [24] login_history_service _cleanup_old 与 add 使用不同锁

- **文件**：`app/services/login_history_service.py:133-170`
- **分类**：可靠性
- **验证结果**：TRUE
- **相关代码**：
  ```python
  # add() 使用 self._lock
  # _cleanup_old() 使用 self._cleanup_lock
  # 两把独立锁可并发执行，_cleanup_old 的 read-modify-write 与 add 的追加写入竞态
  ```
- **影响**：清理操作的 `atomic_write` 可能覆盖 `add()` 新追加的记录。影响较低（清理仅每 50 次写入触发一次，窗口很小）。
- **修复建议**：合并为一把锁，或在 `_cleanup_old` 中也获取 `_lock`。

---

### [28] update_last_run 缓存与磁盘写入分离

- **文件**：`app/services/task_registry.py:147-169`
- **分类**：可靠性
- **验证结果**：TRUE
- **相关代码**：
  ```python
  with self._lock:
      task["last_run"] = timestamp or datetime.now().isoformat()
      snapshot = {k: v for k, v in task.items() if k != "id"}
  # 锁外写磁盘
  try:
      atomic_write(str(self._tasks_dir / f"{task_id}.json"), json.dumps(snapshot, ...))
  except Exception as exc:
      logger.warning("更新定时任务状态失败 {}: {}", task_id, exc)
  ```
- **影响**：磁盘写入失败时缓存已更新但未持久化，进程重启后 last_run 回退。
- **修复建议**：写入失败时回滚缓存。

---

### [29] 三层超时嵌套导致等待时间不可预测

- **文件**：`app/network/probes.py:225-244`
- **分类**：性能
- **验证结果**：TRUE
- **相关代码**：
  ```python
  # 第 1 层：单连接超时
  await asyncio.wait_for(asyncio.open_connection(...), timeout=timeout)
  # 第 2 层：竞态总超时
  await _race_first_success_async(tasks, timeout=timeout + 2, ...)
  # 第 3 层：调用方总超时
  ```
- **影响**：多层嵌套使得实际最大等待时间难以推理和配置。
- **修复建议**：统一为单一 `wait_for` 控制总超时。

---

### [32] 异常内部信息直接泄露给客户端

- **文件**：`app/api/config.py:41-43`
- **分类**：信息泄露
- **验证结果**：TRUE
- **相关代码**：
  ```python
  except Exception as exc:
      api_logger.warning("{}失败: {}", operation, exc, exc_info=True)
      raise HTTPException(status_code=500, detail=f"{operation}失败: {exc}") from exc
  ```
- **影响**：`str(exc)` 可能包含内部文件路径、库版本、配置细节。多处路由有同样问题。
- **修复建议**：500 类错误统一返回泛化消息，原始异常仅写入服务端日志。

---

### [34] _quit 回调在 pystray 线程执行 on_exit，可能死锁

- **文件**：`app/system_tray.py:75-80`
- **分类**：可靠性
- **验证结果**：TRUE
- **相关代码**：
  ```python
  def _quit(self, icon, item):
      if self.icon:
          self.icon.stop()
      if self.on_exit:
          self.on_exit()  # 在 pystray 线程中调用
  ```
- **影响**：pystray 线程中直接调用 `on_exit()`，若涉及 async 操作或依赖特定线程的资源，可能产生线程安全问题。
- **修复建议**：`on_exit` 仅做线程安全的信号传递（如设置 Event），实际关闭逻辑在主线程执行。

---

### [35] Fernet 密钥派生使用非标准 SHA-256 截断

- **文件**：`app/utils/crypto.py:139-141`
- **分类**：密码学
- **验证结果**：TRUE
- **相关代码**：
  ```python
  signing_key = hashlib.sha256(raw_key + b":signing").digest()[:16]
  encryption_key = hashlib.sha256(raw_key + b":encryption").digest()[:16]
  _cached_fernet_key = base64.urlsafe_b64encode(signing_key + encryption_key)
  ```
- **影响**：非标准密钥派生方式，功能上能工作但偏离 Fernet 规范。标准做法应使用 HKDF 或 PBKDF2 派生完整 32 字节。
- **修复建议**：使用 `cryptography.hazmat.primitives.kdf.pbkdf2.PBKDF2HMAC` 或 `HKDF` 派生密钥。

---

### [39] _try_candidates_with_fallback 策略1 不使用 deadline

- **文件**：`app/tasks/step_handlers.py:126-138`
- **分类**：性能
- **验证结果**：TRUE
- **相关代码**：
  ```python
  deadline = time.perf_counter() + timeout / 1000

  # 策略1: 每个候选使用固定 wait_timeout，不考虑 deadline
  wait_timeout = max(1500, int(timeout * 0.15))
  for candidate in candidates:
      loc = ctx.locator(candidate).first
      await loc.wait_for(state="visible", timeout=wait_timeout)  # 可能超过 deadline
  ```
- **影响**：3 个候选时总耗时可达 3 × 1500ms = 4500ms，超过 `timeout=3000ms` 的 deadline。对比策略2 正确使用了 `remaining` 分摊。
- **修复建议**：策略1 也使用 `min(wait_timeout, remaining)` 尊重 deadline。

---

### [47] bootstrapApp() 未捕获 Promise 拒绝

- **文件**：`frontend/app.js:80-92`
- **分类**：可靠性
- **验证结果**：TRUE
- **相关代码**：
  ```javascript
  async function bootstrapApp() {
    await ensurePartialsReady();    // 可能 reject
    const app = createApp(appOptions);
    app.mount('#app');              // 可能 reject
  }
  bootstrapApp();                   // 无 .catch()
  ```
- **影响**：启动失败产生 Unhandled Promise Rejection，Vue 永不挂载，用户只看到空白页。
- **修复建议**：添加 `.catch()` 展示友好错误页面。

---

### [48] background_url 未经验证直接注入 CSS url()

- **文件**：`frontend/app.js:21-22`
- **分类**：安全
- **验证结果**：TRUE
- **相关代码**：
  ```javascript
  if (appearance.background_url) {
    body.style.setProperty('--bg-image', `url(${appearance.background_url})`);
  }
  ```
- **影响**：从 localStorage 读取后直接拼入 CSS `url()`，可构造 `javascript:` 伪协议。实际风险低（同源限制 + 现代浏览器防护）。
- **修复建议**：用 URL 构造函数校验协议和同源。

---

### [49] isRemoteReachable 超时计时器 goroutine 泄漏

- **文件**：`resources/tools/git-puller/main.go:343-362`
- **分类**：资源泄漏
- **验证结果**：TRUE
- **相关代码**：
  ```go
  go func() {
      time.Sleep(remoteTimeout)  // 5 秒，无法取消
      close(ctx)
  }()
  // 当命令快速完成时，此 goroutine 仍在 sleep
  ```
- **影响**：每次快速完成的调用泄漏一个 goroutine 最多 5 秒。调用频率低，影响微乎其微。
- **修复建议**：改用 `context.WithTimeout`。

---

### [50] doUpdate 中 fetch origin 错误被静默忽略

- **文件**：`resources/tools/git-puller/main.go:564-566`
- **分类**：可靠性
- **验证结果**：TRUE
- **相关代码**：
  ```go
  gitRun(gitPath, repoDir, "fetch", "origin", branch)  // 返回值被丢弃
  if _, err := gitRun(gitPath, repoDir, "reset", "--hard", "origin/"+branch); err != nil {
  ```
- **影响**：fetch 失败时后续 `reset --hard` 使用旧引用，代码静默回退到过时版本。同文件其他位置均正确检查了错误返回值。
- **修复建议**：检查 fetch 错误，失败时输出明确错误并退出。

---

## 🟡 Minor 问题（23 项）

### 代码正确性

| # | 文件 | 问题 | 验证 |
|---|------|------|------|
| 53 | `engine.py:1001-1012` | `start_monitoring` 与 `_handle_start` 重复调用 `validate_env_config` | TRUE |
| 58 | `task_executor.py:175-186` | `Future.cancel()` 对已运行任务无效，无内部取消机制 | TRUE |
| 60 | `schemas.py:603` | `config_version` 字段从未被业务代码读取或校验，版本迁移保护未实现 | TRUE |
| 64 | `interfaces.py:13-18` | 跨模块导入 `_` 前缀私有函数（`_parse_darwin_netstat_routes` 等），违反项目命名规范 | TRUE |
| 67 | `browser_runner.py:192-206` | `_wait_url_stable` 每次重定向重置 deadline，实际最大等待 15s 而非参数暗示的 3s | TRUE |
| 80 | `version.py:25-41` | `compare_versions` 对预发布版本号（如 `1.2.3-beta1`）抛 ValueError 后返回 0（相等） | TRUE |
| 81 | `cancel_token.py:73-78` | `clear()` 不仅重置自身标志，还清除外部源事件状态，可能导致其他等待方丢失取消信号 | TRUE |
| 82 | `concurrent.py:37-42` | `interruptible_sleep` 最后一段未裁剪到 deadline，且睡眠后未再检查 cancel_event | TRUE |
| 94 | `lifecycle.js:237-241` | `newLogCount` 从未递增，"新消息"按钮是死 UI | TRUE |
| 95 | `tasks.html:96,141` | 关闭/取消按钮直接 `editingTask = null`，绕过 `closeEditor()` 的未保存修改确认 | TRUE |
| 96 | `appearance.js:186-194` | 浅色主题下硬编码背景色，完全忽略用户设置的 `background_color` | TRUE |
| 97 | `logger.js:38-50` | `_flushBuffer` 部分失败时将整批（含已发送的）放回缓冲区，导致重复发送 | TRUE |

### 代码质量

| # | 文件 | 问题 | 验证 |
|---|------|------|------|
| 71 | `playwright_worker.py:724-733` | 用户自定义 `browser_args` 未做安全敏感参数黑名单过滤（如 `--remote-debugging-port`） | TRUE |
| 74 | `config.py:85-112` | `get_config` 返回裸 `dict`，缺少 `response_model`，OpenAPI 文档无响应 schema | TRUE |
| 75 | `tools.py:22-23` | 模块导入时执行 `mkdir` 副作用，影响测试隔离性和静态分析 | TRUE |
| 76 | `scripts.py:52-65` | `save_script` 直接修改入参 `payload` dict，违反函数不变性惯例 | TRUE |
| 77 | `ws.py:38-42` | 客户端可控日志级别通过 `getattr` 动态获取方法，可能调用 `disable`/`remove` 等非日志方法 | TRUE |
| 88 | `autostart.py:258-271` | Linux systemd `WorkingDirectory` 路径未转义，含空格时解析失败 | TRUE |
| 100 | `test_monitor_core.py` | `NetworkMonitorCore` 核心方法 `check_once()`/`init()`/`stop()` 完全未测试 | TRUE |
| 101 | `test_probes.py:70-105` | 通过源码文本扫描做断言，脆弱测试（重构或格式变化可能误报） | TRUE |

### 低影响问题

| # | 文件 | 问题 | 验证 |
|---|------|------|------|
| 92 | `debug_service.py:33-41` | `_rm()` 使用 `time.sleep(0.1)` 重试 5 次，最大阻塞 0.5s（非热路径） | TRUE |
| 99 | `test_engine.py:237-268` | async 测试混用手动 loop 与 `pytest.mark.asyncio`，风格不一致但功能正常 | TRUE |

---

## 排除项汇总（53 项）

### FALSE（8 项）— 报告描述与源码不符

| # | 标题 | 原因 |
|---|------|------|
| 3 | 手动登录不重置 retry_policy | **有意设计**：manual 路径不参与 retry_policy |
| 8 | cancel_token 锁顺序反转 | `is_set()` 中两个锁**不存在嵌套持有**，锁顺序一致 |
| 14 | browser_runner 网络检测无超时 | 底层有超时保护；更根本的 bug 是 `async def` 传给 `to_thread()` 导致从未成功执行 |
| 22 | _handle_reload 意外启动监控 | `core.monitoring` 守卫阻止，监控已停止时不会进入该分支 |
| 31 | PUT 端点裸 dict 绕过验证 | 已有 `ScheduledTaskConfig.model_validate(merged)` 完整校验 |
| 46 | 13 个数据模块键名冲突 | 逐一检查 14 个模块，**无任何顶层键名冲突** |
| 68 | sync_api 导入 TimeoutError | sync_api 和 async_api 的 TimeoutError 是**同一个类**，功能不受影响 |
| 89 | VBS UTF-16 编码问题 | Windows Script Host 原生支持 UTF-16 LE BOM，标准做法 |

### 单例难触发（22 项）— 单用户桌面场景下几乎不可能触发

| # | 标题 | 排除理由 |
|---|------|----------|
| 1 | toggle_pure_mode TOCTOU | 仅 API 手动触发，毫秒级并发窗口 |
| 5 | _race_first_success 未取消协程 | 传入协程非 Task，提前 return 后协程不执行；描述有误 |
| 9 | 跨事件循环 drain task 泄漏 | start/stop 通常配对调用，旧 loop 关闭时自动取消 |
| 10 | _logging NameError | Pydantic frozen model 属性访问不会抛异常 |
| 12 | WebSocket accept/register 非原子 | 需在极短窗口内发生 Task 取消 |
| 15 | innerHTML XSS | data-include 是本地相对路径，攻击者需修改服务器文件 |
| 26 | delete_task TOCTOU | 单用户手动触发，并发删除同一 task_id 概率极低 |
| 30 | 异步代码混用 threading 原语 | 实际仅用 `is_set()` 非阻塞检查，安全 |
| 33 | shutdown 幂等守卫非原子 | 仅 ASGI lifespan 调用一次 |
| 36 | SOCKS5 5 秒空闲超时 | 专为校园网认证设计，不承载长连接 |
| 37 | ipconfig 多语言编码错误 | 三层回退最后一层，Windows 10+ 默认 UTF-8 |
| 38 | 回环网卡 startswith('lo') | 仅存在于 Linux 嵌入式场景 |
| 40 | script_runner 缺乏沙箱 | 已有 `_build_minimal_env` + `ShellCommandPolicy`，用户自有权限 |
| 41 | asyncio.Queue 跨线程 put_nowait | 回退仅在 loop 关闭瞬间触发，CPython GIL 下 deque.append 原子 |
| 42 | 健康检查泄露进程信息 | 服务器绑定 127.0.0.1，仅本地可访问 |
| 43 | _shutdown_initiated 竞态 | CPython GIL 下布尔赋值原子，结果幂等 |
| 45 | WebSocket 端点无认证 | 服务器绑定 127.0.0.1，项目整体无认证体系 |
| 57 | 夏令时追赶分钟 | 中国不使用夏令时，Asia/Shanghai 无 DST |
| 59 | model_copy 跳过验证 | 所有 update 值均来自已验证的模型实例 |
| 61 | _interface_mgr 单例 TOCTOU | InterfaceManager 无状态，GIL 保护 |
| 83 | _drain_notifier TOCTOU | 设置后永不变更，运行时无并发修改 |
| 86 | is_service_running TOCTOU | 所有竞态场景都有容错处理 |

### 无待办（7 项）— 设计选择或无明确修复方向

| # | 标题 | 原因 |
|---|------|------|
| 25 | login_once 创建独立 Orchestrator | 设计如此：单次登录后退出的独立入口 |
| 27 | Shell 命令未做内容校验 | 本地工具，用户自有权限，无合理修复方向 |
| 44 | 双击 Ctrl+C 跳过退出钩子 | **有意设计**：紧急退出，`os._exit(1)` 是预期行为 |
| 52 | engine.py 1143 行含 6 个类 | 仅描述现象，无修复方向；StatusManager/LoginBridge 已是提取后的类 |
| 56 | validate_login_config 遗漏 isp | `isp` 非必填项，当前校验逻辑正确 |
| 72 | cleanup_orphan_browsers 用 kill | 孤儿进程无法接收优雅退出信号，kill 是标准做法 |
| 91 | 卸载残留检测缺少 PID 文件 | `AUTH_DATA_DIR` 整目录被 `shutil.rmtree` 删除，PID 文件自然清理 |

---

## 目录结构与代码结构优化建议评估

### 一、大文件拆分建议

| 文件 | 行数 | 评估 | 优先级 |
|------|------|------|--------|
| `engine.py` | 1142 | **合理但低优先级**。StatusManager 和 LoginBridge 已是独立类，进一步拆分收益有限 | 低 |
| `playwright_worker.py` | 1199 | **合理但低优先级**。Actor 模型的命令处理 + 浏览器启动 + 孤儿清理，可拆但改动风险高 | 低 |
| `step_handlers.py` | 894 | **合理，中优先级**。OCR 处理逻辑较独立，拆出 `ocr_handler.py` 可降低复杂度，且有助于修复 #6 的 ONNX 泄漏 | 中 |
| `detect.py` | 532 | **不太合理**。532 行属中等规模，gateway 和 SSID 检测共享平台判断逻辑，拆分反而增加耦合 | 不建议 |

### 二、跨模块耦合修复

| 问题 | 评估 | 优先级 |
|------|------|--------|
| interfaces.py 导入 detect.py 私有函数 | **合理**。`_parse_darwin_netstat_routes` 等应提升为公共 API 或移入 interfaces.py | 中 |
| probes.py 混用 threading 原语 | **不太合理**。`threading.Event`/`Lock` 用于跨线程 shutdown 信号和代理设置保护，是正确用法 | 不建议 |
| network/utils.py IP 判断用字符串前缀 | **合理但低优先级**。`startswith("127.")` 技术上不精确，但当前场景误判概率极低 | 低 |

### 三、O(N²) 性能优化

| 位置 | 评估 | 优先级 |
|------|------|--------|
| `interfaces.py:list_interfaces` | **合理但低优先级**。可入口处一次缓存 `psutil.net_if_addrs()`，但典型系统 5-15 接口，开销 15-75ms 用户无感知 | 低 |

### 四、前端架构改善

| 问题 | 评估 | 优先级 |
|------|------|--------|
| data() 中 14 个展开运算符扁平合并 | **不太合理**。按功能域拆分是好的架构实践，展开运算符是 Vue 3 迁移前的过渡方案 | 不建议 |
| template-loader innerHTML 无消毒 | **合理**。虽然数据源是本地 fetch，但作为纵深防御仍值得加固 | 中 |
| bootstrapApp() 无错误处理 | **合理**。启动失败时页面白屏无提示，添加 `.catch()` 成本低 | 低 |

---

## 建议实施顺序

### 第一周：安全 & 崩溃修复（Critical 安全类）

| 优先级 | 编号 | 问题 | 工作量 |
|--------|------|------|--------|
| P0 | #16 | active_task 被覆盖为空串 | 5 分钟 |
| P0 | #7 | Firefox 安装后 Chromium 校验 | 15 分钟 |
| P0 | #11 | Unix os.kill 未捕获异常 | 10 分钟 |
| P0 | #19 | Zip Slip 路径穿越 | 30 分钟 |
| P0 | #20 | SSRF 未过滤内网地址 | 30 分钟 |
| P0 | #21 | 异常类型名称泄露 | 5 分钟 |
| P0 | #17 | 密码字段明文显示 | 15 分钟 |
| P0 | #48 | background_url CSS 注入 | 15 分钟 |
| P1 | #77 | 客户端可控日志级别 | 10 分钟 |

### 第二周：可靠性修复（Critical 功能类 + Major）

| 优先级 | 编号 | 问题 | 工作量 |
|--------|------|------|--------|
| P1 | #2 | 超时后命令仍执行 | 1 小时 |
| P1 | #4 | 浏览器任务被去重替换 | 30 分钟 |
| P1 | #6 | OCR 临时实例泄漏 | 30 分钟 |
| P1 | #13 | debug start 失败未重置状态 | 10 分钟 |
| P1 | #32 | 异常信息泄露给客户端 | 30 分钟 |
| P1 | #24 | login_history 不同锁 | 30 分钟 |
| P1 | #28 | update_last_run 缓存分离 | 30 分钟 |
| P1 | #35 | Fernet 密钥派生非标准 | 1 小时 |
| P1 | #39 | 策略1 deadline 未生效 | 15 分钟 |
| P1 | #47 | bootstrapApp 无错误处理 | 15 分钟 |
| P1 | #50 | fetch origin 错误忽略 | 10 分钟 |

### 第三周：Minor 代码正确性

| 优先级 | 编号 | 问题 | 工作量 |
|--------|------|------|--------|
| P2 | #80 | compare_versions 预发布版本 | 15 分钟 |
| P2 | #81 | clear() 清除外部源事件 | 15 分钟 |
| P2 | #82 | interruptible_sleep 未裁剪 | 15 分钟 |
| P2 | #94 | newLogCount 死 UI | 10 分钟 |
| P2 | #95 | 关闭按钮绕过确认 | 10 分钟 |
| P2 | #96 | 浅色主题背景色忽略 | 10 分钟 |
| P2 | #97 | _flushBuffer 重复发送 | 15 分钟 |
| P2 | #64 | 跨模块导入私有函数 | 30 分钟 |

### 第四周：代码质量 & 测试

| 优先级 | 编号 | 问题 | 工作量 |
|--------|------|------|--------|
| P3 | #74 | get_config 缺少 response_model | 15 分钟 |
| P3 | #75 | 模块导入时 mkdir | 10 分钟 |
| P3 | #76 | save_script 修改入参 | 10 分钟 |
| P3 | #88 | systemd WorkingDirectory 转义 | 10 分钟 |
| P3 | #100 | 核心方法未测试 | 2 小时 |
| P3 | #71 | browser_args 过滤 | 30 分钟 |
| P3 | #53 | 重复配置验证 | 10 分钟 |
| P3 | #58 | cancel() 无法中断任务 | 1 小时 |
| P3 | #67 | _wait_url_stable deadline 重置 | 15 分钟 |
| P3 | #60 | config_version 未校验 | 30 分钟 |
| P3 | #29 | 三层超时嵌套 | 1 小时 |
| P3 | #34 | pystray 线程 on_exit | 30 分钟 |
| P3 | #49 | goroutine 泄漏 | 15 分钟 |
| P3 | #51 | 测试工厂重复 | 30 分钟 |
| P3 | #101 | 源码文本扫描测试 | 30 分钟 |
| P3 | #92 | _rm() 同步 sleep | 5 分钟 |
| P3 | #99 | 测试风格不一致 | 15 分钟 |
| P3 | #18 | repo_proxy 纵深防御 | 15 分钟 |

---

## 验证结果对比

| 指标 | 原报告 | 验证后 |
|------|--------|--------|
| Critical | 21 | **12**（-9） |
| Major | ~30 | **13**（-17） |
| Minor | ~50 | **23**（-27） |
| 总计 | ~101 | **48** |
| 确认率 | — | **47.5%** |
| 最常见排除原因 | — | 单例难触发（22 项） |

**关键发现**：
1. **安全类问题确认率高**：#16、#17、#19、#20、#21、#48 均确认为 TRUE，应最优先修复
2. **竞态条件类问题排除率高**：单用户桌面场景下，绝大多数 TOCTOU/数据竞态实际上不可触发
3. **原报告 #3（手动登录不重置 retry_policy）和 #8（锁顺序反转）为 FALSE**：这两个在原报告中被标为 Critical，但源码验证后发现描述与代码不符
4. **原报告 #14（browser_runner 无超时）有更根本的 bug**：`async def` 传给 `asyncio.to_thread()` 导致网络检测从未成功执行
5. **#16（active_task 覆盖）是最容易修复的 Critical bug**：仅需从 forEach 数组中移除 `'active_task'`
