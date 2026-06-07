# 日志系统优化计划

> 生成时间：2026-06-07
> 修订时间：2026-06-07（综合两个审核 agent 意见）
> 状态：**审核通过，可执行**

---

## 审核修订摘要

| 原计划项 | 审核结论 | 修订操作 |
|---------|---------|---------|
| 1.2 set_level 行号 | 行号偏差 | 修正为 L365-369、L398 |
| 3.1 中英文统一 | 遗漏 30+ 条英文日志 | 补充 api/ 路由文件 |
| 3.2 格式化风格 | 遗漏 %s 和 f-string 约束 | 补充 + 说明 log_message 架构约束 |
| 3.3 分隔符统一 | 遗漏 login.py、executor.py | 补充 |
| 3.4 移除 emoji | 遗漏 ✓/✗ | 补充 + 前端影响分析 |
| 4.2 提取常量 | 过度设计 | 降级为可选 |
| 新增 | 关闭流程 debug 级别不当 | 补充 2.2 |
| 新增 | 调试临时目录清理 debug 级别 | 补充 2.3 |

---

## 阶段一：Bug 修复（高优先级）

### 1.1 修复 `log_message` 无效条件分支

**文件：** `app/core/monitor_core.py:96-113`

**问题：** `else` 分支中 `if exc_info` 和 `else` 执行完全相同的 `log_func(message)`，条件判断无意义。且手动 `traceback.format_exc()` 拼接到消息字符串，丢失了 loguru 的结构化异常追踪能力。

**改动：**
```python
# 改前
def log_message(self, message: str, level: str = "INFO", exc_info: bool = False) -> None:
    if exc_info:
        import traceback
        tb = traceback.format_exc()
        if tb and tb != "NoneType: None\n":
            message = f"{message}\n{tb}"
    if self.log_callback:
        self.log_callback(message, level, "monitor.core")
    else:
        log_func = getattr(self.logger, level.lower(), self.logger.info)
        if exc_info:
            log_func(message)
        else:
            log_func(message)

# 改后
def log_message(self, message: str, level: str = "INFO", exc_info: bool = False) -> None:
    if self.log_callback:
        self.log_callback(message, level, "monitor.core")
    else:
        log_func = getattr(self.logger, level.lower(), self.logger.info)
        if exc_info:
            log_func(message, exc_info=True)
        else:
            log_func(message)
```

**注意：** `_push_log` 路径（`log_callback` 存在时）仍然会丢失结构化异常信息，因为 `_push_log` 只接受字符串。这是现有架构的限制，不在本次修改范围内。

**验证：** `uv run pytest tests/test_monitor_core.py`

---

### 1.2 修正 `set_level` 文档

**文件：** `app/utils/logging.py:365-369`

**问题：** `set_level()` 只调用 `logger.level(normalized)` 设置 loguru 全局级别，但文件 sink 注册时固定 `level="DEBUG"`（第 398 行），运行时修改级别不会影响它。

**分析：** 文件 sink 使用 `level="DEBUG"` 是**正确设计** — 文件应记录全部级别，由 filter 控制。问题在于 `set_level()` 的语义不清晰。

**改动：** 不改代码，改文档。
```python
def set_level(self, level: str) -> None:
    """动态修改全局日志级别（热更新）。

    影响控制台输出和标准 logging 桥接的最低级别。
    文件 sink 始终记录 DEBUG 及以上（由 filter 控制 side）。
    """
    normalized = normalize_level(level)
    logger.level(normalized)
    self._config["level"] = normalized
```

**验证：** `uv run ruff check app/utils/logging.py`

---

## 阶段二：日志级别修正

### 2.1 修正 5 处日志级别不当

| 文件 | 行号 | 当前 | 改为 | 原因 |
|------|------|------|------|------|
| `app/application.py` | 87 | `warning` | `error` | 配置迁移失败影响启动功能 |
| `app/application.py` | 51 | `debug` | `warning` | 磁盘操作失败应可见 |
| `app/application.py` | 312 | `debug` | `warning` | 旧日志清理失败应可见 |
| `app/container.py` | 124 | `debug` | `warning` | 临时目录清理失败可能是权限问题 |
| `app/core/monitor_core.py` | 645 | `DEBUG` | `WARNING` | 登录历史记录失败，且需补充异常信息 |

**具体改动：**

`app/application.py:87`:
```python
# 改前
startup_logger.warning("配置迁移失败: {}", exc)
# 改后
startup_logger.error("配置迁移失败: {}", exc)
```

`app/application.py:51`:
```python
# 改前
startup_logger.debug("清理 temp 截图失败: {}", exc)
# 改后
startup_logger.warning("清理 temp 截图失败: {}", exc)
```

`app/application.py:312`:
```python
# 改前
startup_logger.debug("旧日志清理失败", exc_info=True)
# 改后
startup_logger.warning("旧日志清理失败", exc_info=True)
```

`app/container.py:124`:
```python
# 改前
container_logger.debug("临时目录清理失败", exc_info=True)
# 改后
container_logger.warning("临时目录清理失败", exc_info=True)
```

`app/core/monitor_core.py:644-645`:
```python
# 改前
except Exception:
    self.log_message("记录登录历史失败", "DEBUG")
# 改后
except Exception:
    self.log_message("记录登录历史失败", "WARNING", exc_info=True)
```

**验证：** `uv run pytest`

---

### 2.2 修正关闭流程中 debug 级别（审核补充）

**文件：** `app/api/system.py` — `_do_shutdown()` 函数

关闭流程中的异常使用 `debug` 级别，默认配置下不可见，导致关闭失败无法排查。

| 行号 | 当前 | 改为 | 内容 |
|------|------|------|------|
| L150 | `debug` | `warning` | 关闭监控服务失败 |
| L155 | `debug` | `warning` | 关闭 PlaywrightWorker 失败 |
| L160 | `debug` | `warning` | 清理孤儿浏览器失败 |
| L164 | `debug` | `warning` | PID 文件清理失败 |
| L173 | `debug` | `warning` | services.shutdown() 执行失败 |

**验证：** `uv run ruff check app/api/system.py`

---

### 2.3 修正调试临时目录清理 debug 级别（审核补充）

**文件：** `app/services/debug.py:299`

```python
# 改前
api_logger.debug("调试临时目录清理失败", exc_info=True)
# 改后
api_logger.warning("调试临时目录清理失败", exc_info=True)
```

与 `container.py:124` 的"临时目录清理失败"属同类场景。

**验证：** `uv run ruff check app/services/debug.py`

---

## 阶段三：日志格式统一

### 3.0 设计原则

- **语言**：日志消息统一使用中文。技术术语（SSL、TCP、HTTP、Portal、OCR、PID、WebSocket）保留英文。
- **分隔符**：统一使用 `->`（ASCII 箭头），不使用 `→`（Unicode）和 `—`（全角破折号，改为 `--`）。
- **格式化**：统一使用 `{}` 占位符（loguru 风格）。`log_message` 和 `_push_log` 因接口限制使用 f-string，属可接受例外。
- **emoji**：日志消息中不使用 emoji。

---

### 3.1 统一中英文 — 全部改为中文

#### API 路由文件（审核补充，原计划遗漏）

**`app/api/monitor.py`：**
- L39: `"Monitor start requested -> success={}, message={}"` → `"启动监控 -> success={}, message={}"`
- L48: `"Monitor stop requested -> success={}, message={}"` → `"停止监控 -> success={}, message={}"`
- L57: `"Manual login requested -> success={}, message={}"` → `"手动登录 -> success={}, message={}"`
- L66: `"Network test requested -> success={}, message={}"` → `"网络测试 -> success={}, message={}"`

**`app/api/tasks.py`：**
- L49: `"Save task {} -> success={}, message={}"` → `"保存任务 {} -> success={}, message={}"`
- L59: `"Delete task {} -> success={}, message={}"` → `"删除任务 {} -> success={}, message={}"`
- L69-71: `"Set active task {} -> success={}, message={}"` → `"设置活动任务 {} -> success={}, message={}"`
- L81: `"Save task order -> success={}, message={}"` → `"保存任务排序 -> success={}, message={}"`

**`app/api/scripts.py`：**
- L55: `"Save script {} -> success={}, message={}"` → `"保存脚本 {} -> success={}, message={}"`
- L66: `"Delete script {} -> success={}, message={}"` → `"删除脚本 {} -> success={}, message={}"`
- L99: `"Run script {} -> success={}, message={}"` → `"运行脚本 {} -> success={}, message={}"`

**`app/api/scheduled_tasks.py`：**
- L84: `"Create scheduled task {} -> success={}, message={}"` → `"创建定时任务 {} -> success={}, message={}"`
- L134: `"Update scheduled task {} -> success={}, message={}"` → `"更新定时任务 {} -> success={}, message={}"`
- L146: `"Delete scheduled task {} -> success={}, message={}"` → `"删除定时任务 {} -> success={}, message={}"`
- L158: `"Run scheduled task {} -> success={}, message={}"` → `"执行定时任务 {} -> success={}, message={}"`
- L173: `"Toggle scheduled task {} -> {}"` → `"切换定时任务 {} -> {}"`

**`app/api/system.py`：**
- L121: `"Autostart enable requested -> success={}, message={}"` → `"启用自启动 -> success={}, message={}"`
- L130: `"Autostart disable requested -> success={}, message={}"` → `"禁用自启动 -> success={}, message={}"`
- L142: `"Shutdown requested"` → `"收到关机请求"`
- L212: `"Uninstall requested, keys={}"` → `"收到卸载请求, keys={}"`

**`app/api/profiles.py`：**
- L88-89: `"Save profile {} -> success={}, message={}"` → `"保存方案 {} -> success={}, message={}"`
- L97: `"Apply profile failed"` → `"保存方案后应用方案失败"`
- L111-112: `"Delete profile {} -> success={}, message={}"` → `"删除方案 {} -> success={}, message={}"`
- L122: 已是中文 `"删除方案后 apply_profile 失败"`，无需改
- L133-134: `"Set active profile {} -> success={}, message={}"` → `"设置活动方案 {} -> success={}, message={}"`
- L143: `"Apply profile failed"` → `"删除方案后应用方案失败"`
- L184: `"Auto-switch {}"` → `"自动切换 {}"`

#### 服务层文件

**`app/services/task.py`：**
- L74: `"Loading task {}"` → `"加载任务 {}"`
- L135: `"Task {}: {}"` → `"任务 {}: {}"`
- L169: `"Task deleted: {}"` → `"任务已删除: {}"`
- L171: `"Task delete failed: {}"` → `"任务删除失败: {}"`
- L187: `"Active task set: {}"` → `"活动任务已设置: {}"`
- L189: `"Set active task failed: {}"` → `"设置活动任务失败: {}"`

**`app/services/monitor.py`：**
- L448: `"WS drain loop error"` → `"WS 排空循环异常"`
- L555: `"Config reloaded from settings.json"` → `"配置已从 settings.json 重载"`
- L663: `"MonitorService 已关闭"` → `"监控服务已关闭"`
- L691: `"Manual login requested"` → `"收到手动登录请求"`
- L727: `"Manual login succeeded"` → `"手动登录成功"`
- L731: `"Manual login failed: {}"` → `"手动登录失败: {}"`
- L771: `"Network test failed"` → `"网络测试失败"`

**`app/services/debug.py`：**
- L177: `"Debug session started for task {}"` → `"调试会话已启动，任务: {}"`
- L300: `"Debug session stopped"` → `"调试会话已停止"`

**`app/api/config.py`：**
- L52: `"Config update rejected: {}"` → `"配置更新被拒绝: {}"`
- L55: `"Config save failed: {}"` → `"配置保存失败: {}"`

#### 混合中英文（技术术语保留）

以下日志中的英文技术术语（Captive portal、SSL、systemd、OCR）保留，不翻译：
- `app/network/probes.py:300` — `"Captive portal 检测成功"` ✅ 保留
- `app/network/probes.py:302` — `"Captive portal 检测失败"` ✅ 保留
- `app/network/probes.py:343` — `"SSL 证书验证失败"` ✅ 保留
- `app/services/autostart.py:262` — `"Linux systemd enable 成功"` → `"Linux systemd 启用成功"`
- `app/services/autostart.py:264` — `"Linux systemd enable 失败: {}"` → `"Linux systemd 启用失败: {}"`
- `app/tasks/step_handlers.py:727` — `"[ocr] 普通 fill 成功"` ✅ 保留（fill 是 OCR 术语）

**验证：** `grep -rn 'logger\.\(info\|warning\|error\|debug\|exception\)(\"[A-Z]' app/ --include="*.py"` 确认无残留英文开头的日志消息

---

### 3.2 统一格式化风格 — 全部使用 `{}` 占位符

**需修改的文件和行：**

**`app/utils/login.py:115`：**
```python
# 改前
self.logger.error(f"❌ {error_msg}")
# 改后
self.logger.error("{}", error_msg)
```

**`app/utils/login.py:177`（审核补充）：**
```python
# 改前
self.logger.info(
    "登录开始 → 任务=%s URL=%s 用户=%s 运营商=%s %d个步骤",
    active_task_id, login_url, username, isp or "无", len(task.steps),
)
# 改后
self.logger.info(
    "登录开始 -> 任务={} URL={} 用户={} 运营商={} {}个步骤",
    active_task_id, login_url, username, isp or "无", len(task.steps),
)
```

**`app/utils/login.py:261`（审核补充）：**
```python
# 改前
self.logger.info("脚本任务开始 → 任务=%s 脚本=%s", task.task_id, task.script_path)
# 改后
self.logger.info("脚本任务开始 -> 任务={} 脚本={}", task.task_id, task.script_path)
```

**`app/tasks/step_handlers.py:275`（审核补充）：**
```python
# 改前
logger.debug("[click] timeout=%dms", timeout)
# 改后
logger.debug("[click] timeout={}ms", timeout)
```

**`main.py:226-228`：**
```python
# 改前
logger.warning(
    "login_then_exit 登录失败（已重试 %d 次），回退到正常模式启动服务器",
    max_retries,
)
# 改后
logger.warning(
    "login_then_exit 登录失败（已重试 {} 次），回退到正常模式启动服务器",
    max_retries,
)
```

#### 关于 `log_message` / `_push_log` 的 f-string（架构约束）

`app/core/monitor_core.py` 中有 13 处 `self.log_message(f"...")` 调用，`app/services/monitor.py` 中有多处 `self._push_log(f"...")` 调用。这两个方法的签名只接受纯字符串，不支持 loguru 的延迟格式化 `{}` 占位符。

**决策：** 接受这两个路径使用 f-string 的现实，不做强制统一。原因：
1. 改签名需要改动所有调用方，风险大
2. `log_message` 内部会经过 `_push_log` → loguru，f-string 的性能开销在日志场景下可忽略
3. 这两个方法的调用方相对集中，维护时容易一并处理

**验证：** `grep -rn 'logger\.\(info\|warning\|error\|debug\|exception\)(f"' app/ main.py` 确认仅 `log_message` / `_push_log` 路径使用 f-string

---

### 3.3 统一分隔符 — 使用 `->` 替换 Unicode 箭头

#### Unicode 箭头 `→` 改为 `->`

| 文件 | 行号 | 当前 | 改为 |
|------|------|------|------|
| `app/core/monitor_core.py` | 428 | `"网络检测 → ..."` | `"网络检测 -> ..."` |
| `app/core/monitor_core.py` | 575 | `"开始登录认证 → ..."` | `"开始登录认证 -> ..."` |
| `app/services/monitor.py` | 352 | `"自动切换方案 → ..."` | `"自动切换方案 -> ..."` |
| `app/services/monitor.py` | 563 | `"切换方案 → ..."` | `"切换方案 -> ..."` |
| `app/services/monitor.py` | 752 | `"手动网络测试 → ..."` | `"手动网络测试 -> ..."` |
| `app/tasks/executor.py` | 94 | `"步骤[...] → ..."` | `"步骤[...] -> ..."` |
| `app/tasks/executor.py` | 164 | `"URL 重定向: {} → {}"` | `"URL 重定向: {} -> {}"` |
| `app/tasks/step_handlers.py` | 124 | `"{} 普通操作成功 → {}"` | `"{} 普通操作成功 -> {}"` |
| `app/tasks/step_handlers.py` | 137 | `"{} 降级操作成功 → {}"` | `"{} 降级操作成功 -> {}"` |
| `app/tasks/step_handlers.py` | 727 | `"[ocr] 普通 fill 成功 → {}"` | `"[ocr] 普通 fill 成功 -> {}"` |
| `app/tasks/step_handlers.py` | 729 | `"[ocr] 普通 fill 失败，降级到强制输入 → {}"` | `"[ocr] 普通 fill 失败，降级到强制输入 -> {}"` |
| `app/tasks/step_handlers.py` | 735 | `"[ocr] 强制输入成功 → {}"` | `"[ocr] 强制输入成功 -> {}"` |
| `app/network/decision.py` | 188 | `"网络检测完成: ... → {}"` | `"网络检测完成: ... -> {}"` |
| `app/network/probes.py` | 300 | `"Captive portal 检测成功: {} → {}"` | `"Captive portal 检测成功: {} -> {}"` |
| `app/network/probes.py` | 352 | `"HTTP 请求成功: {} → {}"` | `"HTTP 请求成功: {} -> {}"` |
| `app/utils/login.py` | 177 | `"登录开始 → ..."` | `"登录开始 -> ..."`（已在 3.2 中处理） |
| `app/utils/login.py` | 261 | `"脚本任务开始 → ..."` | `"脚本任务开始 -> ..."`（已在 3.2 中处理） |

#### 全角破折号 `—` 改为 `--`

| 文件 | 行号 | 当前 | 改为 |
|------|------|------|------|
| `app/tasks/executor.py` | 101 | `f" — {message}"` | `f" -- {message}"` |
| `app/network/probes.py` | 244 | `"TCP 连接失败: {} — {}"` | `"TCP 连接失败: {} -- {}"` |
| `app/network/probes.py` | 302 | `"Captive portal 检测失败: {} — {}"` | `"Captive portal 检测失败: {} -- {}"` |
| `app/network/probes.py` | 343 | `"SSL 证书验证失败 (预期行为): {} — {}"` | `"SSL 证书验证失败 (预期行为): {} -- {}"` |
| `app/network/probes.py` | 345 | `"HTTP 请求异常: {} — {}"` | `"HTTP 请求异常: {} -- {}"` |
| `app/network/probes.py` | 354 | `"HTTP 请求失败: {} — {}"` | `"HTTP 请求失败: {} -- {}"` |
| `app/network/decision.py` | 215 | `"认证可达性检测失败: {} — {}"` | `"认证可达性检测失败: {} -- {}"` |
| `app/api/backup.py` | 100 | `"备份文件校验失败: {} — {}"` | `"备份文件校验失败: {} -- {}"` |

**验证：** `grep -rn '→\|—' app/ --include="*.py" | grep -i logger` 确认日志消息中无残留

---

### 3.4 移除 emoji

**需修改的位置：**

| 文件 | 行号 | 当前 | 改后 |
|------|------|------|------|
| `app/utils/login.py` | 115 | `f"❌ {error_msg}"` | `"{}"` (已在 3.2 中处理) |
| `app/core/monitor_core.py` | 611 | `f"登录成功 ✓ {message}"` | `f"登录成功 {message}"` |
| `app/core/monitor_core.py` | 613 | `f"登录失败 ✗ {message}"` | `f"登录失败 {message}"` |

**前端影响分析：**

`frontend/js/methods/formatters.js:41` 中 `getLogClass()` 依赖 `text.includes('✓')` 判断成功样式。移除 `✓` 后：
- 成功样式：`text.includes('成功')` 仍然匹配（兜底），不受影响
- 失败样式：依赖 `level === 'ERROR'` 判断（不依赖 `✗`），不受影响

**结论：** 可安全移除，前端无需改动。

---

## 阶段四：冗余文案清理

### 4.1 合并重复的 `Apply profile failed`

已在阶段 3.1 中区分上下文处理，无需额外改动。

---

### 4.2 ~~提取变量解析器重复警告为常量~~（降级为可选）

**审核结论：** `app/tasks/variable_resolver.py` L70 和 L105 的重复消息在同一文件的不同方法中，提取常量属过度抽象。保持原样即可。

---

## 阶段五：潜在风险缓解

### 5.1 `_cleanup_old_dirs` 记录清理失败

**文件：** `app/utils/logging.py:278-279`

```python
# 改前
except OSError:
    pass

# 改后
except OSError as exc:
    # 不能用 logger — 本方法由 write() 调用，同属 sink 内部
    print(f"[LOG ERROR] 清理过期日志目录失败: {d.name}: {exc}", file=sys.stderr)
```

**验证：** `uv run ruff check app/utils/logging.py`

---

### 5.2 `drain_ws_queue` 添加异常保护

**文件：** `app/services/monitor.py:456-462`

```python
# 改前
async def drain_ws_queue(self) -> None:
    while True:
        try:
            data = self._ws_broadcast_queue.popleft()
        except IndexError:
            break
        if self._ws_manager:
            await self._ws_manager.broadcast(json.dumps(data))

# 改后
async def drain_ws_queue(self) -> None:
    while True:
        try:
            data = self._ws_broadcast_queue.popleft()
        except IndexError:
            break
        try:
            if self._ws_manager:
                await self._ws_manager.broadcast(json.dumps(data))
        except Exception:
            service_logger.exception("WS 广播发送失败")
```

**验证：** `uv run pytest tests/test_monitor_service.py`

---

## 执行顺序

```
阶段一（Bug 修复）
  ↓ uv run pytest
阶段二（日志级别修正）
  ↓ uv run pytest
阶段三（格式统一）
  ↓ uv run pytest
阶段五（风险缓解）
  ↓ uv run pytest
```

---

## 风险评估

| 阶段 | 风险 | 回滚难度 | 说明 |
|------|------|---------|------|
| 一 | 低 | 容易 | 仅改行为，不改接口 |
| 二 | 低 | 容易 | 仅改日志级别 |
| 三 | 低 | 容易 | 仅改文案字符串，不影响逻辑 |
| 五 | 低 | 容易 | 仅添加异常保护 |
