# Campus-Auth 代码审计复核报告

> **复核时间**: 2026-06-01
> **复核方法**: 两轮验证 — 第一轮 5 个并行 Agent 广覆盖，第二轮 5 个并行 Agent 对争议项深挖追溯完整调用链
> **复核范围**: code-audit.md 中 CRITICAL 级别 20 项 + HIGH 级别 5 项抽样
> **原始报告**: `.omo/drafts/code-audit.md`

---

## 复核总览

| 级别 | 抽样数 | 属实 | 属实但降级 | 部分属实 | 不属实 |
|------|--------|------|-----------|----------|--------|
| CRITICAL (C-1 ~ C-20) | 20 | **17** | **1** (C-1→HIGH) | **1** (C-20) | **1** (C-14) |
| HIGH (H-6, H-23, H-30, H-31, H-34) | 5 | **3** | — | — | **2** (H-6, H-30) |
| **合计** | **25** | **20** | **1** | **1** | **3** |

**总体评价**: 原始审计报告质量较高，25 项抽样中 20 项完全属实（80%），1 项属实但严重度需调整（4%），1 项部分属实（4%），3 项不属实（12%）。不属实的 3 项均为审计对代码行为的误读，非凭空捏造。

---

## 逐项复核结果

### CRITICAL 级别

| # | 问题摘要 | 结论 | 严格说明 |
|---|----------|------|----------|
| C-1 | settings.json 损坏时静默覆盖 | **属实→降级 HIGH** | 缺陷确认存在，但有缓解：`backup.py` 提供手动备份/恢复 API（`/api/backup/create`、`/api/backup/restore/{filename}`）。最坏情况是用户从未手动备份过。详见下方分析 |
| C-2 | `_login_in_progress` 多处重置不持有锁 | **属实** | `run_manual_login` 设置 True 时持锁（line 592-595），但 `_handle_login` finally（line 249）、`run_manual_login` except（line 611）、timeout（line 619）三处重置均无锁。跨线程竞态确认 |
| C-3 | crypto.py 密钥文件非原子写 + 损坏时静默重生成 | **属实且更严重** | 不仅非原子写，且无旧密钥备份机制。损坏后自动生成新 key，所有 `ENC:` 密码永久不可解密。比审计描述的后果更严重 |
| C-4 | atomic_write PermissionError 回退先截断原文件 | **属实** | `open(path, "w")` 立即截断为零长度，写入过程中崩溃则数据丢失 |
| C-5 | Windows USERNAME 与校园账号相同时模板跳过 | **属实** | denylist 检查 `os.environ.get(k) == v`，当两者相同时 `{{USERNAME}}` 不被替换 |
| C-6 | `_reload_config_internal` 跨线程无锁 | **属实** | API 线程和消费者线程同时调用，`_ui_config` 和 `_runtime_config` 两次赋值非原子 |
| C-7 | apply_profile 双重入队 + 无 login 检查 | **属实** | `reload_config()` 入队 reload 后又入队 profile_switch，前者被浪费；不检查 `_login_in_progress` |
| C-8 | `os._exit(0)` 绕过所有清理 | **属实** | daemon 线程调 `os._exit(0)` 跳过 atexit、finally、lifespan 关闭流程 |
| C-9 | login_history 非原子 read-modify-write | **属实** | 读文件 → `open("w")` 截断 → 重写，中间崩溃则文件清空 |
| C-10 | backup 读两次文件 + 无锁写 settings.json | **属实** | `backup_path.read_text()` 调用两次；`atomic_write` 无进程间锁 |
| C-11 | crypto `_decryption_failed` 跨 profile 错乱 | **属实** | 模块级 `threading.Event`，profile A 解密失败后 profile B 加密成功会清除 flag |
| C-12 | logging emit 热路径函数内 import | **属实** | `from backend.schemas import LogEntry` 在每条日志的 `emit()` 中执行 |
| C-13 | add_file_handler 静默忽略新 log_dir | **属实** | 检测到已有 `_DateRotatingFileHandler` 就 return，不比较 log_dir 是否变化 |
| C-14 | log_store deque 无 maxlen | **不属实** | 穷举搜索所有 `deque()` 创建，全部有 `maxlen`。`monitor_service.py:84` 创建 `deque(maxlen=1200)`。审计将类型注解处（line 382）误认为创建处 |
| C-15 | `_FORCE_INPUT_JS` 不支持 textarea | **属实** | 只从 `HTMLInputElement.prototype` 获取 setter，`<textarea>` 的 value 在 `HTMLTextAreaElement.prototype` |
| C-16 | worker stop() 队列满时永久阻塞 | **属实** | `cmd_queue.put()` 无 timeout，队列满且 worker 忙时永久阻塞 |
| C-17 | login.py except 路径违反 close_on_failure | **属实** | 正常失败路径检查 `close_on_failure`，异常路径无条件调 `close_browser()` |
| C-18 | frontend `_initErrorCount` 永不重置 | **属实** | 4 个文件仅递增，无任何重置逻辑；对比 `fetchStatusFailCount` 有正确重置 |
| C-19 | CLAUDE.md `{{VAR}}` 优先级描述与代码相反 | **属实** | 文档: env > task > runtime；代码: runtime > env > task。测试 `test_resolve_priority_runtime_over_env` 验证 runtime 优先 |
| C-20 | `_copy_runtime_config` 不真正深拷贝 | **属实但当前无害** | `pause_login`/`monitor`/`custom_variables` 等嵌套 dict 未拷贝，但穷举所有消费者（monitor_core、network_decision、login、browser、task_executor、env），全部通过 `.get()` 只读访问，无任何 mutation。当前无实际 bug，属防御性编程缺陷 |

### HIGH 级别（抽样）

| # | 问题摘要 | 结论 | 严格说明 |
|---|----------|------|----------|
| H-6 | `is_initialized` 检查掩码密码永远 truthy | **不属实** | `mask_password("")` 返回 `""`（falsy）。完整数据流验证：`settings.json` 空密码 → `SystemSettings.password=""` → `mask_password("")=""` → `bool(username and "")=False`。解密失败场景通过 `password_decryption_failed` 字段单独处理 |
| H-23 | Windows `msg` 命令失败仍返回 True | **属实** | `subprocess.run` 结果未检查 `returncode`，对比 PowerShell/macOS/Linux 路径正确检查了返回码 |
| H-30 | WebSocket 重连 5 次后无 UI 提示 | **不属实** | 完整 UI 链路存在：①topbar 重连进度条 `重连中 (x/5)` + spinner（`topbar.html:9-12`）②耗尽后 toast 弹窗"与服务器的连接已断开"（`lifecycle.js:224`）③通知历史记录 + 铃铛未读徽章（`ui.js:54-57`） |
| H-31 | quitApp 触发 WS 重连 5 次 | **属实** | `quitApp` 未设置 `_wsDestroyed = true`，shutdown 后 onclose 触发完整 5 次指数退避重连 |
| H-34 | extractApiError 不处理 422 数组 | **属实** | `error.response.data.detail` 在 422 时是数组，直接返回导致显示 `[object Object]` |

---

## 不属实项深入分析

### C-14: log_store deque 无 maxlen

**原始审计声称**: `src/utils/logging.py:382` 的 `log_store: deque` 没有 `maxlen`，内存会无界增长。

**穷举验证**: 对整个 `src/` 和 `backend/` 目录搜索所有 `deque()` 创建：

| 文件 | 行号 | 代码 | maxlen |
|------|------|------|--------|
| `backend/monitor_service.py` | 84 | `deque(maxlen=1200)` | 有 |
| `backend/monitor_service.py` | 106 | `deque(maxlen=200)` | 有 |
| `backend/debug_session.py` | 63 | `deque(maxlen=1000)` | 有 |
| `backend/routers/logfiles.py` | 97 | `deque(f, maxlen=limit)` | 有 |

零个 `deque()` 创建缺少 `maxlen`。`WebSocketLogHandler` 的唯一实例化在 `container.py:61-64`，传入的两个 deque 均有 maxlen。

**结论**: 审计将类型注解处（参数定义 `log_store: deque`）误认为对象创建处。从 CRITICAL 中移除。

### H-6: is_initialized 检查掩码密码永远 truthy

**原始审计声称**: `config.password` 是掩码后的 `"••••••••"`，永远 truthy。

**完整数据流验证**:
1. `system.py:72`: `config = svc.get_config()` → 返回 `MonitorConfigPayload`
2. `config_service.py:85`: `pld["password"] = mask_password(sys_cfg.password)`
3. `crypto.py:183-187`: `mask_password` 对空值返回 `""`，非空返回 `"••••••••"`
4. `schemas.py:177`: `SystemSettings.password` 默认值为 `""`

四种场景验证：
- 空密码 → `mask_password("")` = `""` → `is_initialized = False` ✓
- 有效加密密码 → `mask_password("ENC:xxx")` = `"••••••••"` → `is_initialized = True` ✓
- 解密失败 → `mask_password("ENC:xxx")` = `"••••••••"` → `is_initialized = True`（语义正确：系统已初始化，只是密钥问题）+ `password_decryption_failed` 字段补充 ✓
- 文件不存在 → 默认空值 → `is_initialized = False` ✓

**结论**: 审计忽略了 `mask_password` 的空值处理分支。从 HIGH 中移除。

### H-30: WebSocket 重连 5 次后无 UI 提示

**原始审计声称**: 重试 5 次后放弃，前端无任何提示。

**完整 UI 链路验证**:

| 阶段 | UI 元素 | 文件:行号 |
|------|---------|-----------|
| 重连中 | topbar spinner + 进度条 `重连中 (x/5)` | `topbar.html:9-12`, `lifecycle.js:227` |
| 重连耗尽 | toast 弹窗"与服务器的连接已断开，请刷新页面" | `lifecycle.js:224`, `ui.js:53-59`, `toast.html:1` |
| 重连耗尽 | 通知历史记录 + 铃铛未读徽章 | `ui.js:54-57`, `topbar.html:19` |
| 重连耗尽 | 前端日志 `连接断开，重试次数已耗尽` | `lifecycle.js:223` |

**结论**: UI 提示完整实现。审计可能遗漏了 `lifecycle.js` 中的 `notify` 调用和 `topbar.html` 中的模板。从 HIGH 中移除。

---

## 争议项深入分析

### C-1: settings.json 损坏时静默覆盖 — 降级为 HIGH

**缺陷确认存在**：`_load_unsafe` 捕获异常后将 `self._data` 设为空 `ProfilesData()`，6 个调用方法中有 5 个后续会触发 save，导致空数据覆盖原文件。

**但有缓解措施**（审计报告未提及）：
- `backend/routers/backup.py` 提供完整的备份创建、恢复、列表、下载、删除功能
- 备份目录 `backups/` 在启动时自动创建（`container.py:31,36`）
- 用户可通过 UI (`POST /api/backup/create`) 手动备份
- 恢复前自动备份当前文件（`backup.py:87-95`）

**降级理由**：这不是数据完全不可恢复的场景。只要用户事先做过备份，就能恢复。最坏情况是用户从未手动备份过。建议增加自动备份（每次 save 前）而非仅手动备份。

### C-3: crypto.py 密钥文件 — 比审计描述更严重

审计报告聚焦于"非原子写"，但实际问题更严重：

1. **非原子写**（审计已指出）：`write_text()` 直接写入，进程崩溃可能截断
2. **无旧密钥备份**（审计未强调）：生成新密钥前不备份旧密钥，旧密钥永久丢失
3. **静默重生成**（审计已指出）：损坏后自动生成新 key，所有 `ENC:` 密码永久不可解密
4. **无恢复机制**：没有密钥版本管理、没有密钥恢复流程

对比：`profile_service.py` 使用 `atomic_write` 写入 settings.json，但 `crypto.py` 完全没有使用 `atomic_write`。

### C-20: `_copy_runtime_config` 不真正深拷贝 — 当前无害

**理论缺陷确认**：`pause_login`、`monitor`（含 4 个 list）、`logging`、`frontend_logging`、`retry_settings`、`custom_variables` 均未拷贝，与 `self._runtime_config` 共享引用。

**但穷举消费者验证无实际 bug**：
- `NetworkMonitorCore`：全部 `.get()` 只读，`_build_test_sites` 创建新 list
- `network_decision.py`：全部 `.get()` 只读
- `login.py`：全部 `.get()` 只读
- `BrowserContextManager`：存储引用但不修改
- `PlaywrightWorker`：全部 `.get()` 只读
- `TaskExecutor`：全部 `.get()` 只读
- `build_login_env_vars`：全部 `.get()` + `.items()` 只读

**结论**：当前代码中无任何消费者修改嵌套配置对象。这是防御性编程缺陷，非实际 bug。未来代码变更若修改嵌套对象会静默污染主配置。

---

## 修正后的优先级建议

### P0（本周必须修）— 3 项

1. **C-3** crypto 密钥文件改 atomic_write + 损坏时备份旧密钥 + 拒绝静默重生成 — 后果最严重（所有密码永久丢失）
2. **C-2** `_login_in_progress` 所有读写加锁 — 改用 `threading.Event` 或全部 `with self._login_lock:`
3. **C-4** `atomic_write` 删除 PermissionError 回退或改安全语义

### P1（本月）— 8 项

4. **C-1** settings.json 损坏恢复 — 加自动备份（每次 save 前）+ 损坏时从 `backups/` 恢复最新
5. **C-5** env.py USERNAME denylist 行为修复
6. **C-7** apply_profile 去除冗余 reload 入队
7. **C-8** shutdown 改用 lifespan 退出机制
8. **C-15** `_FORCE_INPUT_JS` 支持 textarea
9. **C-17** login.py except 路径尊重 `close_on_failure`
10. **C-18** frontend `_initErrorCount` 在 init 末尾重置
11. **C-19** 更新 CLAUDE.md 文档中的变量优先级描述

### P2（本季度）— 测试 + 防御性改进

- 补 `playwright_worker._start_browser` 测试
- 补 `browser.py` `__aenter__`/`__aexit__` 测试
- 补 `profile_service` 损坏恢复测试
- 补 router 测试（当前仅 8 端点覆盖）
- **C-20** `_copy_runtime_config` 改用 `copy.deepcopy`（防御性改进）

### P3（技术债）— 代码质量

- 拆 `app-options.js` 单文件
- 拆 `_perform_login_with_active_task` 130 行
- 拆 `_start_browser` 112 行
- 函数内 import 移到模块顶部（C-12、H-22）

---

## 复核方法论说明

本报告采用两轮验证：

**第一轮**（广覆盖）：5 个并行 Agent 分别验证 C-1~C-5、C-6~C-10、C-11~C-15、C-16~C-20、H 级别抽样。每项读取相关代码文件，确认行号和行为。

**第二轮**（深挖争议）：5 个并行 Agent 对第一轮判定为"不属实"和"部分属实"的项进行严格追溯：
- C-14：穷举搜索所有 `deque()` 创建，确认全部有 maxlen
- H-6：追踪 `settings.json` → `SystemSettings` → `mask_password` → `MonitorConfigPayload` 完整数据流
- H-30：追踪 `onclose` → `notify` → `_showToast` → `toast.html` 完整 UI 链路
- C-20：穷举所有消费者，确认无 mutation
- C-1/C-3：追溯完整调用链，确认缓解措施和实际严重度

---

## 复核结论

原始审计报告整体质量**良好**，80% 的抽样项完全属实。主要问题：

1. **1 项误判**（C-14）：将类型注解处误认为对象创建处，未追溯到实际 `deque()` 创建代码
2. **2 项遗漏**（H-6、H-30）：未完整阅读 `mask_password` 空值分支和 `lifecycle.js` + `topbar.html` 的 UI 提示实现
3. **1 项严重度偏差**（C-1）：未提及已有的备份/恢复 API 缓解措施
4. **1 项严重度不足**（C-3）：审计聚焦"非原子写"，但实际更严重的是"无旧密钥备份 + 静默重生成"

**建议**：审计时对"缺失"类结论应穷举搜索而非单点采样；对"永远/总是"类断言应追踪完整数据流；对严重度评估应考虑已有的缓解措施。

---

**复核完成**。两轮共 10 个并行 Agent，覆盖 25 项审计发现，交叉验证后生成本报告。
