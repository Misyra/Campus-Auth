# Campus-Auth 全面代码审查报告

**审查日期**：2026-07-04
**审查范围**：功能逻辑链路、可能无法实现的功能
**审查方法**：6 个并行代理分别审查主入口/容器、网络检测、任务执行、登录编排、Playwright Worker、配置系统

---

## 一、审查概览

本次审查覆盖了 Campus-Auth 的 6 个核心模块，重点关注功能逻辑链路的完整性和可能无法实现的功能。

| 模块 | 审查文件 | 发现问题数 |
|------|---------|-----------|
| 主入口和容器 | `main.py`, `container.py`, `deps.py` | 5 |
| 网络检测 | `probes.py`, `decision.py`, `detect.py` | 15 |
| 任务执行系统 | `models.py`, `task_executor.py`, `scheduler_service.py` | 7 |
| 登录编排流程 | `login_orchestrator.py`, `login_attempt.py`, `retry_policy.py` | 8 |
| Playwright Worker | `playwright_worker.py`, `playwright_bootstrap.py`, `script_runner.py` | 13 |
| 配置和方案系统 | `config_builder.py`, `profile_service.py`, `schemas.py` | 9 |

**总计**：发现 57 个问题，其中严重 2 个、中等 6 个、低等 49 个。

---

## 二、严重问题（功能完全失效）

### 2.1 浏览器定时任务退化为通用登录

**位置**：`app/services/task_executor.py:308-333`

**问题描述**：
`_execute_browser` 方法从 registry 加载了浏览器任务配置，但完全不使用它：

```python
def _execute_browser(self, task_id: str, timeout: int) -> tuple[bool, str]:
    task = self._registry.get_task(task_id)
    if not task or task.get("type") != "browser":
        return False, f"浏览器任务不存在: {task_id}"
    # task 拿到了，但下面直接提交通用登录，没有传入 task 的 URL/步骤等配置
    config = self._get_runtime_config() if self._get_runtime_config else RuntimeConfig()
    handle = self._login_orchestrator.submit(
        source="browser",
        config=config,  # 用的是全局运行时配置，不是任务定义
        timeout=timeout,
    )
```

**后果**：
- registry 中定义的浏览器类型定时任务（自定义 URL、步骤等）被完全忽略
- 所有浏览器定时任务都退化为"执行一次登录"
- 用户在 TaskRegistry 中配置的 browser 类型定时任务实际上无法按自定义步骤执行

**修复建议**：
修改 `_execute_browser` 方法，将任务配置传递给 `LoginOrchestrator.submit()`，或创建专门的浏览器任务执行路径。

---

### 2.2 定时任务错过不可恢复

**位置**：`app/services/scheduler_service.py:60-75`

**问题描述**：
调度索引是 `(hour, minute)` 精确匹配。`tick()` 方法的调度逻辑：

```python
def tick(self, now: float) -> None:
    dt_now = datetime.now()
    due_tasks = registry.get_due_tasks(dt_now.hour, dt_now.minute)
    for task_id in due_tasks:
        executor.execute_task_async(task_id)
    # 无论是否抛异常，都推进下一次 tick 时间
    self._next_schedule_tick = (int(time.time() // 60) * 60) + 60
```

**后果**：
- 如果引擎因系统休眠、崩溃重启等原因错过某个分钟的 tick，该分钟内的所有定时任务将被永久跳过
- 直到下一天同一时刻才会再次执行
- 没有任何"追赶"（catch-up）机制

**修复建议**：
1. 记录上次 tick 时间戳
2. 在下次 tick 时检查是否有错过的时间窗口
3. 对错过的任务执行追赶逻辑（可配置是否追赶）

---

## 三、中等问题（功能降级或边界场景失效）

### 3.1 轻量模式不清理孤儿浏览器

**位置**：`app/launcher.py:launch_lightweight()`

**问题描述**：
轻量模式不经过 lifespan，跳过了 `cleanup_orphan_browsers()` 调用。

**后果**：
- 如果上一次运行在登录过程中崩溃，残留的 Chromium 进程不会被清理
- 崩溃重启后可能累积僵尸浏览器进程

**修复建议**：
在 `launch_lightweight()` 中添加：
```python
from app.workers.playwright_worker import cleanup_orphan_browsers
cleanup_orphan_browsers()
```

---

### 3.2 重试耗尽后需等待 10 分钟才能恢复

**位置**：`app/services/engine.py:571-582`

**问题描述**：
```python
if result.need_login:
    self._retry_policy.on_network_check(True)
    if self._retry_policy.retries_exhausted:
        self._retry_policy.reset()      # 只重置，不触发登录
    else:
        self._do_async_login()
```

**后果**：
- 重试耗尽后需要再等一个完整的网络检测周期（默认 300 秒）才能再次尝试
- 网络长时间不稳定时，每次重试耗尽后有 5-10 分钟的空白期

**修复建议**：
在 `reset()` 后立即调用 `_do_async_login()`，减少不必要的等待。

---

### 3.3 方案切换后监控重启失败静默丢失

**位置**：`app/services/engine.py:734-737`

**问题描述**：
```python
if was_monitoring:
    self._handle_stop()
    self._handle_start(EngineCommand(type=EngineCmdType.START))  # 返回值被忽略
```

**后果**：
- 如果新方案配置无效导致监控启动失败，API 仍返回"方案切换成功"
- 用户误以为监控正常运行，实际已停止

**修复建议**：
检查 `_handle_start` 返回值，如果失败则向用户返回错误信息。

---

### 3.4 掩码密码可能被加密存储

**位置**：`app/services/profile_service.py` + `app/utils/crypto.py`

**问题描述**：
`save_password_field` 没有掩码检测：
```python
def save_password_field(value: str, existing: str) -> str:
    if not value:
        return existing  # 空串保留原密码
    if value.startswith("ENC:"):
        return value  # 已加密，原样返回
    return encrypt_password(value)  # 其他当作明文加密
```

**后果**：
- 如果前端对已有密码显示掩码 `"••••••••"` 并回传，会被当作明文加密存储
- 导致密码损坏，下次登录失败

**修复建议**：
在 `save_password_field` 中添加掩码检测：
```python
if value.startswith("•"):
    return existing  # 掩码保留原密码
```

---

### 3.5 Windows 虚拟网卡误判为有效网络

**位置**：`app/network/probes.py:150-158`

**问题描述**：
`_VIRTUAL_NIC_PREFIXES` 不包含 Windows 常见虚拟网卡前缀：
- Hyper-V: `vEthernet (Default Switch)`
- WSL2: `vEthernet (WSL)`
- VMware: `VMware Network Adapter VMnet1`
- VirtualBox: `VirtualBox Host-Only Ethernet Adapter`

**后果**：
- 在有 Hyper-V 或 WSL2 的机器上，即使物理网卡断开，虚拟网卡可能仍 `isup=True`
- 断网检测失效，不触发自动登录

**修复建议**：
扩展 `_VIRTUAL_NIC_PREFIXES`：
```python
_VIRTUAL_NIC_PREFIXES = (
    "lo", "docker", "br-", "veth", "virbr", "vmnet", "vboxnet",
    "vethernet",  # Windows Hyper-V/WSL2
    "vmware",     # VMware
    "virtualbox", # VirtualBox
)
```

---

### 3.6 `_decision_executor` 关闭顺序不可控

**位置**：`app/network/decision.py:28`

**问题描述**：
使用 `atexit` 而非显式 shutdown。已有 `shutdown_decision_executor()` 函数但未在 `ServiceContainer.shutdown()` 中调用。

**后果**：
- 关闭时资源清理顺序不一致
- in-flight 请求可能在服务关闭后继续运行

**修复建议**：
在 `ServiceContainer.shutdown()` 中添加：
```python
from app.network.decision import shutdown_decision_executor
shutdown_decision_executor()
```

---

## 四、低等问题（代码质量或边界场景）

| # | 问题 | 位置 | 严重程度 | 建议 |
|---|------|------|---------|------|
| 1 | captive portal URL 子串匹配过于宽泛 | `probes.py:293-294` | 低-中 | 改用精确域名匹配或正则 |
| 2 | `update_last_run` 锁外写磁盘，失败后数据不一致 | `task_registry.py:147-169` | 中 | 采用与 `save_task` 相同的磁盘优先策略 |
| 3 | 被拒绝的 LoginHandle 残留在 `_slot` 中 | `login_orchestrator.py:362-373` | 低 | 注册 `_on_done` 回调清理 |
| 4 | 超时检测依赖字符串匹配 `"超时"` | `login_orchestrator.py:353` | 低 | 改为捕获具体超时异常类型 |
| 5 | `set_block_proxy` 锁间窗口期 | `probes.py:134-141` | 低 | 合并为一把锁 |
| 6 | BoundedExecutor shutdown(wait=False) Semaphore 泄漏 | `task_executor.py:76-78` | 低 | 已知问题，有注释说明 |
| 7 | debug_page 与 _page 共享引用 | `playwright_worker.py:510-512` | 低 | 文档说明限制 |
| 8 | config_version 字段未被用于迁移逻辑 | `schemas.py:557` | 低 | 添加版本迁移机制 |
| 9 | `boot()` 与 `start_thread()` 调用重叠 | `application.py:123-125` | 低 | 简化调用逻辑 |
| 10 | deps.py 未暴露所有服务 | `deps.py` | 低 | 补充缺失的服务类型别名 |
| 11 | `_cmd_stop()` 未设置退出码 | `main.py:61` | 低 | 添加退出码 |
| 12 | AND 语义可能导致误报断网 | `decision.py:252-257` | 中 | 文档说明行为 |
| 13 | `follow_redirects` 逻辑缺少注释 | `decision.py:229` | 低 | 添加注释说明设计意图 |
| 14 | is_local_network_connected 不检查 speed | `probes.py:175` | 低 | 增加 `speed > 0` 条件 |
| 15 | Windows SSID 编码回退可能误判 | `detect.py:295-332` | 低 | 已有限制注释，可接受 |
| 16 | BrowserTaskRunner logger 名称与 TaskExecutor 冲突 | `browser_runner.py:22` | 低 | 使用不同的 logger 名称 |
| 17 | ScriptRunner 每次执行都新建 ShellCommandPolicy | `script_runner.py:216-222` | 低 | 缓存 ShellCommandPolicy |
| 18 | 300 秒默认超时对调试步骤过长 | `playwright_worker.py` | 设计 | 按命令类型区分超时 |
| 19 | 每次登录重建浏览器有启动开销 | `browser.py:116-134` | 设计 | 考虑浏览器复用 |
| 20 | 全量覆盖配置风险 | `profile_service.py:297-307` | 中 | 前后端模型严格同步 |

---

## 五、设计上做得好的地方

### 5.1 架构分层清晰

- **API 层**：纯路由定义，无业务逻辑
- **Services 层**：核心业务逻辑，由 ServiceContainer 统一管理
- **Workers 层**：Playwright Actor 模型工作线程

### 5.2 循环依赖处理合理

- **LoginOrchestrator <-> TaskExecutor**：先创建无 executor 的编排器，再创建执行器，最后 `set_executor()` 替换
- **Engine <-> LoginOrchestrator/TaskExecutor**：延迟绑定 `bind_runtime_config()`

### 5.3 并发控制机制完善

- **LoginOrchestrator 的去重与抢占**：`_slot` + `Condition` 设计很好地解决了 auto/manual/login_once 三种来源的并发控制
- **CompositeCancelEvent**：实现了"任一源取消则整体取消"的语义
- **BoundedExecutor**：Semaphore + done_callback 限制队列长度

### 5.4 生命周期管理健壮

- `shutdown()` 的幂等保护（`_shutdown_done`）防止重复关闭
- `wait_for_callbacks()` 在 engine shutdown 和 task_executor shutdown 之间，避免回调触及已关闭组件
- 孤儿浏览器清理 `cleanup_orphan_browsers` 通过 psutil 检测父进程存活状态

### 5.5 安全措施到位

- `ShellCommandPolicy` 白名单验证执行路径
- `_build_minimal_env` 最小化环境变量，避免泄漏敏感信息
- 密码加密使用 Fernet 对称加密
- 临时文件在 `finally` 中清理

---

## 六、修复优先级建议

### P0（立即修复）

1. **浏览器定时任务退化**（#2.1）— 导致自定义浏览器任务功能形同虚设
2. **定时任务错过不可恢复**（#2.2）— 系统休眠后任务丢失

### P1（尽快修复）

3. **轻量模式孤儿浏览器**（#3.1）— 崩溃后累积僵尸进程
4. **重试耗尽后恢复延迟**（#3.2）— 影响用户体验
5. **方案切换监控失败静默**（#3.3）— 用户误以为监控正常
6. **掩码密码存储**（#3.4）— 可能导致密码损坏
7. **Windows 虚拟网卡误判**（#3.5）— 断网检测失效
8. **decision_executor 关闭顺序**（#3.6）— 资源清理不一致

### P2（计划修复）

9. 所有低等问题（#4 中的 20 项）

---

## 七、总结

Campus-Auth 的整体架构质量较高，分层清晰，循环依赖处理合理，并发控制机制完善。主要问题集中在：

1. **任务执行系统**：浏览器定时任务功能不完整，定时任务错过不可恢复
2. **边界场景处理**：轻量模式、重试耗尽、方案切换等场景的异常处理
3. **平台兼容性**：Windows 虚拟网卡前缀不完整

建议优先修复 P0 和 P1 问题，这些问题直接影响核心功能的可用性。低等问题可以纳入后续迭代计划。

---

**审查人**：Claude Code
**审查工具**：6 个并行代理（主入口/容器、网络检测、任务执行、登录编排、Playwright Worker、配置系统）
