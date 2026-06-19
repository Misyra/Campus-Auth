# 登录链路全面审查报告

> **审查日期**: 2026-06-19
> **审查范围**: 登录链路全路径（轻量模式、全量模式、配置逻辑、网络检测、重试机制）
> **审查方法**: 5 个并行 Agent 分维度深入审查

---

## 一、审查维度与覆盖范围

| Agent | 审查维度 | 核心文件 | 发现问题数 |
|-------|---------|---------|-----------|
| 1 | 轻量模式登录链路 | `main.py`, `container.py`, `application.py` | 1 严重 + 3 中等 + 4 轻微 |
| 2 | 全量模式登录链路 | `engine.py`, `task_executor.py`, `playwright_worker.py`, `login.py`, `browser.py`, `browser_runner.py` | 5 中等 + 6 轻微 |
| 3 | 不同配置下的逻辑 | `schemas.py`, `config_service.py`, `runtime_config.py`, `profile_service.py`, `crypto.py`, `env.py` | 3 中等 + 5 轻微 |
| 4 | 网络检测相关逻辑 | `decision.py`, `probes.py`, `detect.py`, `network.py` | 4 中等 + 7 轻微 |
| 5 | 重试与错误处理 | `login_retry.py`, `engine.py`(重试部分), `concurrent.py`, `exceptions.py` | 2 中等 + 4 轻微 |

**总计**: 1 严重 + 22 中等 + 26 轻微

---

## 二、架构概览

### 登录流程调用链

**自动登录（监控触发）：**
```
ScheduleEngine._engine_loop()
  → _do_network_check() → NetworkMonitorCore.check_once()
    → NetworkDecision.check_network_status() → probes (TCP/HTTP/URL)
  → 检测到 need_login=True
  → _do_async_login()
    → TaskExecutor.execute_login_async()  [login_pool 线程]
      → TaskExecutor.execute_login()
        → PlaywrightWorker.submit(CMD_LOGIN)
          → PlaywrightWorker._handle_login()
            → LoginAttemptHandler.attempt_login()
              → _perform_login_with_active_task()
                → _execute_browser_task()
                  → BrowserContextManager.__aenter__()  [启动浏览器]
                  → tasks.browser_runner.TaskExecutor.execute(page)  [执行步骤]
                  → BrowserContextManager.__aexit__()  [关闭浏览器]
```

**手动登录（Web 控制台触发）：**
```
POST /api/actions/login
  → ScheduleEngine.run_manual_login()
    → _handle_login()  [引擎线程]
      → _do_async_login(is_manual=True)
        → (同上 TaskExecutor → Worker → LoginAttemptHandler)
```

**轻量模式启动：**
```
main.py
  → StartupAction.LOGIN_ONCE → _run_login_then_exit()
    → 网络检测 → 指数退避重试登录 → 成功退出 / 失败继续监控
  → RuntimeMode.LIGHTWEIGHT → _run_lightweight()
    → ServiceContainer(mode="lightweight") → NullWebSocketManager
    → ScheduleEngine 启动 → 按需启动 Web 服务
```

---

## 三、需要修复的问题（按优先级排序）

### 问题 1：`record_attempt` 时机早于实际登录执行，浪费重试次数

- **严重程度**: 中等
- **文件**: `app/services/engine.py:326-332`
- **审查 Agent**: Agent 5（重试与错误处理）

**问题描述**:
`record_attempt` 在 `execute_login_async` 之前调用。如果 `execute_login_async` 抛出异常（如 executor 未初始化），count 已经递增但登录实际并未执行，白白消耗一次重试机会。

```python
# 当前代码
if not is_manual:
    self._login_retry.record_attempt(time.time())  # count 从 N → N+1
try:
    future = self._task_executor.execute_login_async(...)  # 可能抛异常
except Exception:
    self._update_status_snapshot()
    raise  # 异常向上传播，但 count 已经 +1
```

**影响范围**: 自动重试场景，executor 提交失败时会浪费重试机会。

**修复建议**:
```python
try:
    future = self._task_executor.execute_login_async(...)
except Exception:
    self._update_status_snapshot()
    raise
if not is_manual:
    self._login_retry.record_attempt(time.time())
```

---

### 问题 2：网络检测每次都 reset 重试状态，导致重试机制可能完全失效

- **严重程度**: 中等
- **文件**: `app/services/engine.py:269-273`
- **审查 Agent**: Agent 5（重试与错误处理）

**问题描述**:
当 `check_once` 判定 `need_login=True` 时，代码无条件调用 `self._login_retry.reset()`。如果网络检测间隔很短（如 60 秒），每次检测都会重置重试计数为 0，重试机制永远无法生效。

场景复现：
1. 网络检测 → `need_login=True` → `reset()` → `configure()` → 登录失败（count=1）
2. 60 秒后再次网络检测 → `need_login=True` → `reset()`（count 归零）→ 重新开始
3. 重复以上过程，重试机制永远无法达到 `max_retries`

**影响范围**: 自动登录重试的实际效果大打折扣。

**修复建议**:
仅在登录成功时 reset，或在 `need_login` 时检查当前重试状态，如果已在重试中则不 reset。

---

### 问题 3：轻量模式 Web 服务已启动后 shutdown 路径缺失

- **严重程度**: 中等（原报告标记为严重，经分析降级）
- **文件**: `main.py:497-512` (`_run_lightweight` finally 块)
- **审查 Agent**: Agent 1（轻量模式）

**问题描述**:
当 `_web_server_state["started"]` 为 True 时，finally 块直接跳过容器的 shutdown，假设由 Uvicorn 事件循环处理。但如果 Uvicorn 崩溃或尚未就绪，容器不会被清理。

对比 `_run_full` 始终调用 `asyncio.run(container.shutdown())` 作为防御。

**影响范围**: Web 服务已启动后主进程退出时，可能泄漏线程池资源和 Playwright 进程。

**修复建议**:
```python
finally:
    if tray_icon:
        tray_icon.stop()
    if not _web_server_state["started"]:
        # ... 现有异步 shutdown 逻辑 ...
    else:
        # 至少确保 TaskExecutor 被关闭
        container.task_executor.shutdown(wait=False)
```

---

### 问题 4：手动登录取消超时后可能被"吞掉"

- **严重程度**: 中等
- **文件**: `app/services/engine.py:319-326`
- **审查 Agent**: Agent 2（全量模式）+ Agent 5（重试与错误处理）

**问题描述**:
手动登录时，如果当前有自动登录在运行，取消等待 5 秒后超时，代码继续提交新登录。但 `is_login_running()` 仍为 True，`execute_login_async` 的去重机制会返回旧的 future，手动登录实际被"吞掉"。

**影响范围**: 手动登录与自动登录并发时，用户可能看到非预期的登录结果。

**修复建议**:
超时后强制清理旧的 `_login_future` 引用（设为 None），或绕过去重机制直接提交到线程池。

---

### 问题 5：`auth_url/carrier/carrier_custom/active_task` 字段双写

- **严重程度**: 中等
- **文件**: `app/services/config_service.py` + `app/schemas.py`
- **审查 Agent**: Agent 3（配置逻辑）

**问题描述**:
这四个字段同时存在于 `_MonitorFieldsMixin` 和 `_SystemFieldsMixin` 中，且同时属于 `GLOBAL_SETTINGS_FIELDS`。在 `save_config_combined` 中被同时写入 `global_settings` 和 `profile` 两个位置。

运行时合并逻辑正确（profile 优先），但数据冗余且可能不一致（当用户手动编辑 settings.json 或切换 profile 时）。

**影响范围**: 配置维护困惑，可能导致调试困难。

**修复建议**:
考虑将这四个字段从 `GLOBAL_SETTINGS_FIELDS` 的 `SystemSettings` 侧移除，或添加注释说明设计意图。

---

### 问题 6：`_MonitorFieldsMixin` 和 `_SystemFieldsMixin` 字段重叠导致 API schema description 丢失

- **严重程度**: 中等
- **文件**: `app/schemas.py:118-121` + `app/schemas.py:275-279`
- **审查 Agent**: Agent 3（配置逻辑）

**问题描述**:
`auth_url/carrier/carrier_custom` 在两个 mixin 中都有定义。由于 `MonitorConfigPayload` 的 MRO 是 `_MonitorFieldsMixin` 优先，`_SystemFieldsMixin` 中的 description 被覆盖为 `None`。

**影响范围**: API 文档（OpenAPI schema）中这三个字段缺少描述信息。

**修复建议**:
将 description 移到 `_MonitorFieldsMixin` 中，或使用 `Annotated` 方式统一定义。

---

### 问题 7：`engine.py` 的 `test_network` 未解析 `url_check_urls`

- **严重程度**: 中等
- **文件**: `app/services/engine.py:796-835`
- **审查 Agent**: Agent 4（网络检测）

**问题描述**:
手动"测试网络"功能直接读取 `url_check_urls`，未调用 `parse_url_checks()` 解析字符串格式。如果用户以字符串格式配置了 `url_check_urls`，传入 `is_network_available` 的将是原始字符串而非 `list[tuple[str, str]]`，导致 URL 检测被跳过或行为异常。

**影响范围**: 手动"测试网络"功能中 URL 检测不生效。

**修复建议**:
```python
from app.utils.network import parse_url_checks
url_checks_raw = monitor_cfg.get("url_check_urls", None)
if isinstance(url_checks_raw, str) and url_checks_raw.strip():
    url_checks = parse_url_checks(url_checks_raw)
else:
    url_checks = url_checks_raw
```

---

### 问题 8：`_link_cancel_event` 创建的 watcher 线程可能泄漏

- **严重程度**: 中等
- **文件**: `app/services/task_executor.py:210-222`
- **审查 Agent**: Agent 2（全量模式）+ Agent 5（重试与错误处理）

**问题描述**:
每次登录去重命中时都创建新 daemon 线程，最多存活 300 秒。高频场景下可能积累大量睡眠线程。

**影响范围**: 高频手动登录点击场景。

**修复建议**:
使用单个共享 cancel 事件，或在 `_on_login_done` 中通知 watcher 提前退出。

---

### 问题 9：指数退避算法缺少最大间隔上限

- **严重程度**: 中等
- **文件**: `app/utils/retry.py:14-15`
- **审查 Agent**: Agent 5（重试与错误处理）

**问题描述**:
当 `exponential=True` 时，退避间隔按 `retry_interval * (2**i)` 无限增长。若 `retry_interval=300`、`max_retries=10`，第 10 次重试间隔为 `300 * 2^9 = 153600 秒`（约 42 小时）。虽然当前代码硬编码 `exponential=False`，但作为通用工具函数缺乏防御。

**影响范围**: 所有使用 `get_retry_intervals(exponential=True)` 的场景。

**修复建议**:
```python
return [min(retry_interval * (2**i), max_interval) for i in range(max_retries)]
```

---

## 四、可改进的问题（非阻塞）

| # | 严重程度 | 文件 | 问题 | 审查 Agent |
|---|---------|------|------|-----------|
| 10 | 轻微 | `main.py:219` | `time.sleep` 阻塞主线程，Windows 上无法响应 Ctrl+C | Agent 1 |
| 11 | 轻微 | `engine.py:208-210` | 引擎循环异常处理过于宽泛（已正确排除 BaseException） | Agent 2 |
| 12 | 轻微 | `playwright_worker.py:362-369` | `task_done()` 调用多余（无 `join()` 场景） | Agent 2 |
| 13 | 轻微 | `playwright_worker.py:1051-1083` | `cleanup_orphan_browsers` 可能误杀其他实例的浏览器 | Agent 2 |
| 14 | 轻微 | `login.py:256-263` | `close_browser` 传入 `(None, None, None)` 语义不精确 | Agent 5 |
| 15 | 轻微 | `task_executor.py:195` | `cancel_event is not None` 检查永远为 True（冗余） | Agent 5 |
| 16 | 轻微 | `login_retry.py` | 非线程安全（当前单线程使用，无实际风险） | Agent 2/5 |
| 17 | 轻微 | `probes.py:90-101` | `is_local_network_connected` 只检查物理连接不检查 IP | Agent 4 |
| 18 | 轻微 | `decision.py:75-76` | 延迟导入 `parse_url_checks`（可能是有意设计） | Agent 4 |
| 19 | 轻微 | `env.py:82-83` | 未定义模板变量不会被替换，也无警告 | Agent 3 |
| 20 | 轻微 | `crypto.py:228-229` | 空字符串 vs None 清除密码行为依赖前端序列化 | Agent 3 |
| 21 | 轻微 | `concurrent.py:45` | `race_first_success` 所有 future 异常时丢失错误信息 | Agent 5 |
| 22 | 轻微 | `decision.py:108-116` | `check_network_status` 返回的 `method` 字段不准确 | Agent 4 |
| 23 | 轻微 | `decision.py:207-219` | AND 语义下单一检测方式持续失败会导致持续误报 | Agent 4 |
| 24 | 轻微 | `probes.py:43-54` | `follow_redirects` 传递链较隐晦 | Agent 4 |
| 25 | 轻微 | `detect.py:124-151` | ipconfig 回退中 GBK 编码匹配有平台限制 | Agent 4 |
| 26 | 轻微 | `detect.py:186-194` | 十六进制 SSID 解码存在已知限制 | Agent 4 |
| 27 | 轻微 | `time_utils.py:21` | `datetime.datetime.now()` 未显式指定时区 | Agent 4 |
| 28 | 轻微 | `decision.py:237-275` | `extra_targets=[]` 时行为与直觉不符 | Agent 4 |
| 29 | 轻微 | `config_service.py:131-138` | `_rollback_config` 回滚逻辑正确但可读性可改善 | Agent 3 |
| 30 | 轻微 | `config_service.py:159-160` | 密码恰好以 `•` 开头时会被误判为掩码 | Agent 3 |
| 31 | 轻微 | 测试覆盖 | 缺少 `carrier/carrier_custom` 覆盖测试、profile 切换测试 | Agent 3 |

---

## 五、审查总结

### 整体评价

**代码质量：良好。** 登录链路的架构设计合理，具体表现在：

1. **Actor 模型**确保线程安全 — ScheduleEngine 和 PlaywrightWorker 各自单线程消费命令队列
2. **登录去重机制**（`_login_future` + `_login_lock`）可靠地防止重复提交
3. **超时控制**覆盖各环节 — 命令入队超时、Worker 命令执行超时、手动登录等待超时、浏览器操作超时
4. **取消机制**全链路贯通 — 从 API 层到 Worker 层通过 `threading.Event` 传递
5. **资源清理**完整 — `_cleanup_browser` 按序关闭浏览器资源，`_force_cleanup` 确保 Worker 退出时强制清理
6. **配置合并逻辑**正确 — SystemSettings + AuthProfile → MonitorConfigPayload，profile 非空值覆盖全局值
7. **密码加密**健壮 — Fernet 对称加密，密钥损坏时有备份和恢复机制

### 需要重点关注的 3 个问题

| 优先级 | 问题 | 影响 |
|--------|------|------|
| ⚠️ 高 | `record_attempt` 时机问题 (#1) | 会浪费重试次数，降低自动重试可靠性 |
| ⚠️ 高 | 网络检测重置重试状态 (#2) | 可能导致重试机制完全失效 |
| ⚠️ 中 | 轻量模式 shutdown 路径 (#3) | Web 服务已启动后退出可能泄漏资源 |

### 建议修复顺序

1. **第一批**（影响自动重试可靠性）: 问题 #1、#2
2. **第二批**（影响手动登录体验和资源管理）: 问题 #3、#4
3. **第三批**（代码质量改进）: 问题 #5、#6、#7
4. **第四批**（防御性编程）: 问题 #8、#9

---

## 六、无需修复的确认项

以下经审查确认为正确设计，无需修改：

- ✅ 浏览器生命周期管理：每次登录创建/销毁浏览器是有意设计，确保 session 隔离
- ✅ `StatusSnapshot` 的引用替换是线程安全的（Python GIL + 对象引用赋值原子性）
- ✅ `_engine_loop` 的宽泛异常捕获是合理的防御性设计（不捕获 BaseException）
- ✅ 网络检测 AND 语义（任一失败即断网）是有意的保守设计
- ✅ `is_network_available_url` 内部 OR 语义（任一 captive portal 响应正常即通过）是正确的
- ✅ `_rollback_config` 的 `copy.deepcopy` 确保了备份独立性
- ✅ 密钥损坏时的备份和恢复机制工作正常
