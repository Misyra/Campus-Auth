# Campus-Auth v3.6.7 — 综合代码审查报告

> **审查日期:** 2026-05-25  
> **审查范围:** 全代码库二次交叉验证审查  
> **方法:** 5 × 并行后台探索 agent + 亲自 grep/ast-grep/LSP/代码阅读 + 两轮独立验证  
> **覆盖:** Python ~30 文件, JavaScript ~8 文件, HTML ~7 文件, 测试 ~351 项  
> **审查人:** Atlas → 供人工复审

---

## 目录

1. [执行摘要](#1-执行摘要)
2. [方法论与审查流程](#2-方法论与审查流程)
3. [撤回的发现（原始报告错误）](#3-撤回的发现原始报告错误)
4. [已确认发现数据库](#4-已确认发现数据库)
5. [安全分析报告](#5-安全分析报告)
6. [并发与线程安全分析](#6-并发与线程安全分析)
7. [Frontend / Vue 3 审查](#7-frontend--vue-3-审查)
8. [后端 API 审查](#8-后端-api-审查)
9. [圈复杂度分析](#9-圈复杂度分析)
10. [测试覆盖矩阵](#10-测试覆盖矩阵)
11. [资产风险热力图](#11-资产风险热力图)
12. [修复优先级路线图](#12-修复优先级路线图)
13. [附录](#13-附录)

---

## 1. 执行摘要

| 指标 | 数值 |
|------|------|
| 原始报告发现总数 | 20 |
| 撤回（误报） | 2 |
| 已确认保留 | 18 |
| 第二轮新增发现 | 9 (N-1 至 N-9) |
| **最终报告发现总数** | **27** |
| 严重级别分布 | 🟠 P1: 3, 🟡 P2: 10, 🟢 P3: 6, 🟢 OPT: 8 |
| 测试结果 | 351/351 通过 ✅ |
| Ruff | 23 错误 (22×E402 + 1×F841) |

### 三大最关键发现

| 优先级 | 发现 | 理由 |
|--------|------|------|
| 🟠 P1 | `ignore_https_errors: True` 硬编码不可关闭 | MITM 攻击面，唯一的绕过方式(Safe Mode)是核选项 |
| 🟠 P1 | `_DateRotatingFileHandler.close()` 与 `emit()` 竞争条件 | 关闭时日志写入冲突，静默丢日志条目 |
| 🟡 P2 | 14 个 ActionResponse 路由可能抛 500 而非返回统一错误格式 | API 响应形状不一致，前端难以统一处理错误 |

---

## 2. 方法论与审查流程

本审查采用**两轮独立验证**流程，确保每一条发现的准确性：

### 第一轮（初始审查）
- 5 × 并行后台探索 agent（项目结构、bug 模式、安全、测试覆盖、前端）
- 直接 grep/ast-grep 搜索 20+ 种模式
- 运行完整测试套件
- 初始报告交付

### 第二轮（交叉验证 — 本报告）
- 5 × 并行后台探索 agent（事件循环竞争条件验证、ignore_https_errors 验证、全新 Bug 狩猎、WebSocket 生命周期审查、backend/main.py 深度分析）
- 亲自代码追踪（线程所有权分析、异常链验证、状态机推演）
- 25+ 次 grep/ast-grep 搜索，覆盖以下模式：
  - 可变默认参数 (`def f(x=[])`)
  - 星号导入 (`from x import *`)
  - 裸 except/except Exception 普查
  - `asyncio.create_task` 泄露
  - `os.environ` 跨线程修改
  - `atexit` + `os._exit` 冲突
  - 全局变量无锁变异
  - 套接字泄漏
  - 路径遍历
  - 等等

### 验证标准
- ❌ **误报**：代码证据明确证明无实际问题
- ✅ **影响轻微**：问题真实存在但异常链已处理
- ✅ **已确认**：问题真实存在且有实际影响

---

## 3. 撤回的发现（原始报告错误）

本报告包含两轮独立验证。以下两条原始发现经核实为**误报**，正式撤回：

### ❌ W-1: "裸 `except:` 抑制 SystemExit/KeyboardInterrupt"

- **原始报告:** "约 15 处裸 `except:` 会抑制 SystemExit 和 KeyboardInterrupt"
- **撤回理由:** ❌ **代码库中不存在裸 `except:`**
- **证据:** 所有 `except` 块均使用 `except Exception`，根据 Python 异常层级：
  ```
  BaseException
  ├── SystemExit        ← 不被 except Exception 捕获
  ├── KeyboardInterrupt ← 不被 except Exception 捕获
  └── Exception         ← 被 except Exception 捕获
  ```
- **教训:** 审查时混淆了 `except:` 与 `except Exception:`，未仔细验证 Python 异常继承机制。

### ❌ W-2: "备份端点存在路径穿越漏洞"

- **原始报告:** "restore_backup/download_backup/delete_backup 可通过 `../` 路径穿越读取任意文件"
- **撤回理由:** ❌ **三个端点均有正则格式验证**
- **证据:**
  ```python
  # 三个端点共享同一正则:
  re.match(r"^settings_\d{8}_\d{6}(_\d{6})?(_autosave)?\.json$", filename)
  # `../../settings.json` 不匹配此正则 → 返回 400
  ```
- **仍存在的问题:** `restore_backup()`（第 1218-1224 行）的**检查顺序有误**：先检查 `backup_path.exists()`（第 1219 行），再验证格式（第 1223 行）。差异化的响应（404 vs 400）可被用作**文件存在性判定**（见 N-7）。

---

## 4. 已确认发现数据库

### 4.1 事件循环与并发

#### R-1: 事件循环竞争条件 — `_loop` vs `_loop_stopped`

| 属性 | 值 |
|------|-----|
| **文件** | `src/monitor_core.py` |
| **行号** | 560-603, `stop_monitoring():183-205` |
| **原始级别** | 🔴 P0 |
| **修正级别** | 🟡 P2 |
| **最终判定** | 真实存在但影响轻微 |
| **修复预估** | ~20 行 |

**线程所有权分析：**

| 线程 | 角色 | 访问的 `_loop` 行 |
|------|------|-------------------|
| **Monitor Thread** (守护线程) | 运行 `start_monitoring()` → `attempt_login()` | 560, 574-597 (读取/写入) |
| **Uvicorn Thread** (主线程) | 处理 API 请求 → `stop_monitoring()` | 200-205 (关闭/置空) |
| **Shutdown Thread** (守护线程) | `/api/shutdown` → `stop_monitoring()` | 200-205 (关闭/置空) |

**竞争条件时间线：**

```
Monitor Thread                           Uvicorn Thread
──────────────                           ─────────────
attempt_login() line 560:
  if self._loop_stopped:  → False
                                         stop_monitoring() line 197:
                                           self._loop_stopped = True
                                         line 200-205:
                                           self._loop.close()    ← RuntimeError on running loop
                                           self._loop = None
attempt_login() line 574:
  if self._loop is None:  → True
line 575: self._loop = asyncio.new_event_loop()  ← 创建浪费的新循环
line 581: self._loop.run_until_complete(...)      ← 在新循环上运行
```

**三层异常屏障确保不崩溃：**

| 层 | 位置 | 捕获的异常 | 结果 |
|-----|--------|-----------------|--------|
| 1 | line 586 | `RuntimeError` (已关闭循环上的 run_until_complete) | 返回 `False, "事件循环已关闭"` |
| 2 | line 600 | `Exception` (None.run_until_complete → AttributeError) | 通过 `pass` 静默处理 |
| 3 | line 203 | `Exception` (运行中循环上的 close → RuntimeError) | 通过 `pass` 静默处理 |

**修复建议：**
```python
# 添加锁保护
self._loop_lock = threading.Lock()

# 在每个 _loop 访问处:
with self._loop_lock:
    if self._loop_stopped:
        return False, "事件循环已关闭"
    loop = self._loop
    if loop is None:
        loop = self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
```

---

#### N-1: `_DateRotatingFileHandler.close()` 与 `emit()` 竞争条件

| 属性 | 值 |
|------|-----|
| **文件** | `src/utils/logging.py` |
| **行号** | 153 (`emit`), 197 (`close`) |
| **级别** | 🟠 P1 |
| **类型** | 资源竞争 · 数据丢失 |
| **修复预估** | ~5 行 |

**有问题的代码：**
```python
def emit(self, record):
    with self._emit_lock:          # ✅ 在 emit 中持有锁
        if self._stream:
            self._stream.write(msg)
            self._stream.flush()

def close(self):
    # ⚠️ 没有 `with self._emit_lock:`
    if self._stream:
        self._stream.close()       # 🔴 close() 时 emit 可能正在写入
        self._stream = None
```

**推演：**
1. 线程 A 进入 `emit()`：获取 `_emit_lock`，开始写入 `self._stream`
2. 线程 B 进入 `close()`：**不获取锁**，直接调用 `self._stream.close()`
3. 线程 A 继续写入已关闭的流：`ValueError: I/O operation on closed file`
4. 被 `emit()` 第 193 行的 `except Exception` 静默捕获 → **日志条目丢失**

**修复：**
```python
def close(self) -> None:
    with self._emit_lock:          # ✅ 添加锁
        # ... 刷新未写入行 ...
        if self._stream:
            self._stream.close()
            self._stream = None
    super().close()
```

---

#### N-2: Signal Handler 死锁风险

| 属性 | 值 |
|------|-----|
| **文件** | `app.py` |
| **行号** | 297-305 |
| **级别** | 🟡 P2 |
| **类型** | 并发死锁 · 进程不退出 |
| **修复预估** | ~5 行 |

**有问题的代码：**
```python
def _signal_handler(signum, _frame):
    print("\n收到停止信号，正在关闭...")
    try:
        from backend.main import service
        service.stop_monitoring()   # 🔴 可能在持有 _config_lock 时被调用
    except Exception:
        pass
    _cleanup_pid()
    os._exit(0)                     # 🔴 如果卡在 stop_monitoring 处，永远不会到达
```

**推演：**
1. API handler 进入 `update_config()`：获取 `_config_lock`
2. 在锁持有期间收到 SIGINT/SIGTERM
3. Signal handler 调用 `stop_monitoring()` → `reload_config()` → 尝试获取 `_config_lock`
4. **死锁！** Signal handler 永远卡住，`os._exit(0)` 不会执行

**修复：**
```python
def _signal_handler(signum, _frame):
    print("\n收到停止信号，正在关闭...")
    # 不要在此处获取锁 — 直接终止
    _cleanup_pid()
    os._exit(0)
```

---

#### N-3: `_get_executor()` 无锁竞争条件

| 属性 | 值 |
|------|-----|
| **文件** | `src/network_test.py` |
| **行号** | 36-40 |
| **级别** | 🟡 P2 |
| **类型** | 资源泄漏 |
| **修复预估** | ~10 行 |

**有问题的代码：**
```python
def _get_executor() -> ThreadPoolExecutor:
    global _executor
    if _executor is None:
        _executor = ThreadPoolExecutor(max_workers=5)  # 🔴 无锁！
    return _executor
```

**推演：**
1. 线程 A 检查 `_executor is None` → True
2. 线程 B 检查 `_executor is None` → True
3. 线程 A 创建 `ThreadPoolExecutor` → `_executor = executor_A`
4. 线程 B 创建 `ThreadPoolExecutor` → `_executor = executor_B`（覆盖 A）
5. `executor_A` 被泄漏：其线程继续运行但无人可以 shutdown

**修复：**
```python
_executor_lock = threading.Lock()

def _get_executor() -> ThreadPoolExecutor:
    global _executor
    if _executor is None:
        with _executor_lock:
            if _executor is None:  # 双重检查锁定
                _executor = ThreadPoolExecutor(max_workers=5)
    return _executor
```

---

### 4.2 WebSocket 生命周期

#### P2-1: WebSocket 陈旧 `onclose` 竞争条件

| 属性 | 值 |
|------|-----|
| **文件** | `frontend/js/methods/lifecycle.js` |
| **行号** | 172-244 |
| **级别** | 🟡 P2 |
| **类型** | 竞争条件 · 功能损坏 |
| **修复预估** | ~5 行 |

**问题时间线：**

```
时间  connectWebSocket()
  ↓
  T0: clearTimeout(this._wsRetryTimer)        [lifecycle.js:176]
  T1: this.ws.close()   // 关闭旧的 WS       [lifecycle.js:179]
  T2: this.ws = new WebSocket(wsUrl)          [lifecycle.js:182]
  T3: 设置 onopen/onmessage/onclose/onerror   [lifecycle.js:185-243]
      *** 新 WS 的 onclose handler 已绑定到 this.ws ***
      *** 旧 WS 的 onclose 事件仍在事件循环队列中 ***
  T4: 新 WS 打开 → onopen 触发
      - wsRetryCount = 0                      [lifecycle.js:186]
      - setWebSocket(this.ws) → logger._ws = 新 WS
  ↓
  T5: ★ 旧 WS 关闭完成 → 旧的 onclose 触发 ★
      - setWebSocket(null)  ★ BUG! ★    [lifecycle.js:223]
        → logger._ws = null (日志转发中断！)
      - _wsDestroyed = false (仅在 beforeUnmount 中设置)
      - wsRetryCount = 0 < wsMaxRetries (5)
      - 触发重连定时器！                       [lifecycle.js:235]
  ↓
  T6: 重连定时器触发 → connectWebSocket() 再次
      - this.ws.close()  ★ 杀掉仍然正常的新 WS！★
      - 创建第三个连接
```

**实际影响：**

| 影响 | 严重性 | 解释 |
|------|----------|-----------|
| 前端日志转发中断 | 🟡 中 | `logger._ws = null` → `_sendToBackend()` 停止工作（`lifecycle.js:223`, `logger.js:19`） |
| 活跃 WS 被杀并重建 | 🟡 中 | 陈旧 onclose 触发 `connectWebSocket()`，关闭正常的新连接 |
| UI 错误显示重连状态 | 🟢 低 | `topbar.html:11` 在连接正常时显示 `wsReconnecting = true` |

**修复：** 添加 generation 计数器：
```javascript
connectWebSocket() {
  clearTimeout(this._wsRetryTimer);
  if (this.ws) this.ws.close();
  
  const gen = (this._wsGen = (this._wsGen || 0) + 1);  // 每次调用 +1
  this.ws = new WebSocket(wsUrl);
  
  this.ws.onclose = () => {
    this.frontendLogger.setWebSocket(null);
    this.frontendLogger.warn('websocket', 'connection closed');
    if (this._wsDestroyed) return;
    if (gen !== this._wsGen) return;     // ★ 忽略陈旧 onclose ★
    if (this.wsRetryCount >= this.wsMaxRetries) { ... }
    // ...
  };
}
```

**重连数学修正：** 5 次重试，延迟为 1s, 2s, 4s, 8s, 16s = **总计 31 秒**（不是原来担心的 5 分钟）。

---

#### P1-2: WebSocket 连接泄漏

| 属性 | 值 |
|------|-----|
| **文件** | `backend/monitor_service.py` |
| **行号** | 57-61 |
| **级别** | 🟠 P1 |
| **类型** | 资源泄漏 |
| **修复预估** | ~3 行 |

**有问题的代码：**
```python
# _send_safe() 内部:
if isinstance(result, Exception) and ws in self._connections:
    self._connections.remove(ws)  # 从列表中移除但从不调用 ws.close()
```

**修复：**
```python
if isinstance(result, Exception) and ws in self._connections:
    self._connections.remove(ws)
    try:
        await ws.close()          # ✅ 关闭 WebSocket 连接
    except Exception:
        pass
```

---

### 4.3 网络与安全

#### S-1: `ignore_https_errors: True` 硬编码

| 属性 | 值 |
|------|-----|
| **文件** | `src/utils/browser.py:140`, `backend/main.py:249` |
| **级别** | 🟠 P1 |
| **类型** | 安全 · MITM |
| **修复预估** | ~50 行（含 schema + UI） |

**完整目录（所有 Playwright context 创建）：**

| 位置 | 文件:行 | Safe Mode? | `ignore_https_errors` | 可配置？ |
|--------|--------|-----------|----------------------|-----------|
| 1A | `src/utils/browser.py:119` | ✅ 是 | **未设置** (默认 False) | 通过 `safe_mode` |
| 1B | `src/utils/browser.py:140` | ❌ 否 | **硬编码 True** | ❌ |
| 2A | `backend/main.py:198` | ✅ 是 | **未设置** (默认 False) | 通过 `safe_mode` |
| 2B | `backend/main.py:249` | ❌ 否 | **硬编码 True** | ❌ |

**绕过方式：** 唯一方式是开启 Safe Mode，但这会**清除所有自定义设置**（UA、headers、args、stealth、locale、timezone）。这是个核选项，不是精确的 SSL 控制。

**Schema 检查：** `MonitorConfigPayload` / `ProfileSettings` / `SystemSettings`（`backend/schemas.py`）中 **不存在** 任何 `ssl`/`tls`/`certificate`/`verify`/`ignore_https_errors` 字段。

**前端检查：** `settings.html` 和 `profiles.html` 中 **不存在** HTTPS/SSL 开关。

**修复计划：**
1. `backend/schemas.py`: 添加 `ignore_https_errors: bool = True` 到 `ProfileSettings` 和 `MonitorConfigPayload`
2. `src/utils/browser.py`: 改为 `"ignore_https_errors": self.browser_settings.get("ignore_https_errors", True)`
3. `backend/main.py`: 改为 `"ignore_https_errors": browser_settings.get("ignore_https_errors", True)`
4. `settings.html` + `profiles.html`: 添加用户可见开关

---

#### S-10: StaticFiles 挂载点暴露目录列表

| 属性 | 值 |
|------|-----|
| **文件** | `backend/main.py` |
| **行号** | 1311-1313 |
| **级别** | 🟢 P3 |
| **类型** | 信息泄露 |

```python
app.mount("/debug", StaticFiles(directory=DEBUG_DIR), name="debug")
app.mount("/temp", StaticFiles(directory=TEMP_DIR), name="temp")
```

默认的 `StaticFiles`（无 `html=True`）可能暴露目录列表。意味着：
- `GET /debug/` → 可能列出所有调试截图（含敏感登录页面内容）
- `GET /temp/` → 可能列出临时调试截图

**修复：** 如果不需要，传递 `html=True` 或添加 `response_class=...` 以禁用列表。

---

### 4.4 后端 API 问题

#### N-4: 14 个 `ActionResponse` 路由在异常时抛出 500 而非返回统一错误

| 属性 | 值 |
|------|-----|
| **文件** | `backend/main.py` |
| **行号** | 多处 |
| **级别** | 🟡 P2 |
| **类型** | API 一致性 |
| **修复预估** | ~80 行 |

**受影响的路由：**

| 路由 | 行号 | 问题 |
|------|-------|--------|
| `POST /api/monitor/start` | 541-545 | 无 try/except |
| `POST /api/monitor/stop` | 548-552 | 同上 |
| `POST /api/actions/login` | 555-559 | 同上 |
| `POST /api/actions/test-network` | 562-566 | 同上 |
| `POST /api/autostart/enable` | 580-584 | 同上 |
| `POST /api/autostart/disable` | 587-593 | 同上 |
| `PUT /api/tasks/{task_id}` | 614-618 | 同上 |
| `DELETE /api/tasks/{task_id}` | 621-625 | 同上 |
| `POST /api/tasks/active/{task_id}` | 628-634 | 同上 |
| `PUT /api/profiles/{profile_id}` | 979-993 | 同上 |
| `DELETE /api/profiles/{profile_id}` | 996-1002 | 同上 |
| `POST /api/profiles/active/{profile_id}` | 1005-1019 | 同上 |
| `POST /api/profiles/auto-switch` | 1061-1067 | 同上 |
| `POST /api/shutdown` | 1080-1123 | 同上 |

**问题：** 当这些路由中的 service 方法抛出异常时，FastAPI 返回 `HTTP 500 {"detail": "..."}`，而不是 `{"success": false, "message": "..."}`。前端代码如果期待 ActionResponse 格式，会解析失败。

**修复：**
```python
def start_monitoring() -> ActionResponse:
    try:
        ok, message = service.start_monitoring()
        return ActionResponse(success=ok, message=message)
    except Exception as exc:
        api_logger.error("启动监控失败: %s", exc)
        return ActionResponse(success=False, message=f"启动监控失败: {exc}")
```

---

#### N-5: `save_task()` 和 `uninstall_perform()` 缺少 Pydantic 验证

| 属性 | 值 |
|------|-----|
| **文件** | `backend/main.py:614`, `backend/main.py:1148` |
| **级别** | 🟡 P2 |
| **类型** | 输入验证缺失 |
| **修复预估** | ~30 行 |

```python
# Line 614 — 接受任意 JSON 载荷
@app.put("/api/tasks/{task_id}", response_model=ActionResponse)
def save_task(task_id: str, payload: dict) -> ActionResponse:
    ok, message = task_service.save_task(task_id, payload)
    return ActionResponse(success=ok, message=message)

# Line 1148 — 同样的问题
@app.post("/api/uninstall")
def uninstall_perform(payload: dict) -> dict:
    keys = payload.get("keys", [])
```

`payload: dict` 表示**接受任意 JSON，无结构验证**。无效输入可能导致 service 层出现意外的行为/异常。

**修复：** 为此端点引入 Pydantic 模型：
```python
class SaveTaskPayload(BaseModel):
    id: str = ""
    name: str = ""
    # ... 与 Task 结构匹配的更多字段

@app.put("/api/tasks/{task_id}")
def save_task(task_id: str, payload: SaveTaskPayload) -> ActionResponse:
    ok, message = task_service.save_task(task_id, payload.model_dump())
    return ActionResponse(success=ok, message=message)
```

---

#### N-6: `_require_debug_session()` 返回不正确的 HTTP 状态码

| 属性 | 值 |
|------|-----|
| **文件** | `backend/main.py` |
| **行号** | 325-328 |
| **级别** | 🟢 P3 |
| **类型** | REST 合规 |

```python
def _require_debug_session():
    if not _debug["session"] or not _debug["running"]:
        raise HTTPException(status_code=400, detail="没有活跃的调试会话")
```

400 Bad Request → 请求格式有误时才应使用。此处的问题是资源状态（没有活跃的会话），应使用 404 Not Found 或 409 Conflict。

---

#### N-7: `restore_backup` 文件存在性判定

| 属性 | 值 |
|------|-----|
| **文件** | `backend/main.py` |
| **行号** | 1218-1224 |
| **级别** | 🟢 P3 |
| **类型** | 信息泄露 |

```python
backup_path = _BACKUP_DIR / filename
if not backup_path.exists():                   # 1. 先检查文件是否存在
    raise HTTPException(404, "备份文件不存在")   # → 404
if not re.match(r"...regex...", filename):     # 2. 后验证文件名格式
    raise HTTPException(400, "无效的备份文件名")  # → 400
```

**差异化的响应**允许攻击者盲探测任意文件是否存在（在备份目录外，通过 `../../settings.json`）。虽然格式验证最终会拒绝此类路径，但 `exists()` 检查已在此前泄露了存在性。

**修复：** 交换顺序：先验证格式，再检查存在性。
```python
if not re.match(r"...regex...", filename):
    raise HTTPException(400, "无效的备份文件名")
backup_path = _BACKUP_DIR / filename
if not backup_path.exists():
    raise HTTPException(404, "备份文件不存在")
```

---

#### N-8: `toggle_auto_switch()` 为无效输入返回 `success=True`

| 属性 | 值 |
|------|-----|
| **文件** | `backend/main.py` |
| **行号** | 1061-1067 |
| **级别** | 🟢 P3 |
| **类型** | 虚假成功信号 |

```python
@app.post("/api/profiles/auto-switch")
def toggle_auto_switch(enabled: str = Query(default="true")):
    # enabled 的解析：任何非 truthy 字符串 → 视为 "false"
    # 但永远返回 success=True
```

`POST /api/profiles/auto-switch?enabled=garbage` → `{"success": true, "message": "自动切换已关闭"}`。没有任何失败信号。

---

### 4.5 前端问题

#### P2-2: Toast 离开计时器未清理

| 属性 | 值 |
|------|-----|
| **文件** | `frontend/js/app-options.js` |
| **行号** | 208-210 |
| **级别** | 🟡 P2 |

`beforeUnmount()` 清理了 `_toastTimer` 但漏掉了 `_toastLeavingTimer`。如果用户在 Toast 渐出动画期间离开页面，回调可能访问已卸载的组件状态。

#### P2-3: v-model.number 产生 NaN

| 属性 | 值 |
|------|-----|
| **文件** | `frontend/partials/pages/settings.html` |
| **行号** | 19 个字段使用 v-model.number |
| **级别** | 🟡 P2 |

`v-model.number` 对空字符串调用 `parseFloat('')` 产生 `NaN`。`JSON.stringify` 将 `NaN` 序列化为 `null`。影响 `check_interval_minutes`、`login_timeout`、`max_retries` 等数值字段。

**修复：**
```javascript
// 在保存前添加守卫
data.check_interval_minutes = Number.isNaN(data.check_interval_minutes) ? 5 : data.check_interval_minutes;
```

#### P2-5: showProfileEditor 在 API 失败时不后退

| 属性 | 值 |
|------|-----|
| **文件** | `frontend/js/methods/profiles.js` |
| **行号** | 14-27 |
| **级别** | 🟡 P2 |

```javascript
this.$api.get(`/api/profiles/${profileId}`)
  .then(({ data }) => {
    this.editingProfile = { ... };
    this.currentPage = 'profile-edit';  // 在 API 完成前已设置页面
  }).catch(() => {
    // 🔴 没有 this.currentPage = 'profiles'
    // 停留在 profile-edit 视图，编辑器中 editingProfile 为 null
  });
```

---

### 4.6 代码质量与优化

#### P1-1: Socket 文件描述符泄漏

| 属性 | 值 |
|------|-----|
| **文件** | `src/monitor_core.py:278` |
| **级别** | 🟠 P1 |
| **现状** | `sock = socket.create_connection(...)` 无 `with` |
| **正确做法** | `with socket.create_connection((host, port), timeout=3) as sock:` |
| **对比** | `src/network_test.py:221` 正确使用了 `with` |

#### P2-4: 模板替换变量名子串匹配

| 属性 | 值 |
|------|-----|
| **文件** | `src/utils/env.py:54` |
| **级别** | 🟡 P2 |
| **修复预估** | ~10 行 |

```python
for k, v in env_vars.items():
    resolved_url = resolved_url.replace("{{" + k + "}}", v)  # 🔴 可能匹配子串
```

如果 `k="USER"` 且 `v="someuser"`，`resolved_url` 中的 `{{USERNAME}}` 会在 `{{USERNAME}}` 中的 `{{USER}}` 部分被替换。结果：`{{someuserNAME}}`。

动态编排中的词条顺序差异可能导致结果不可预测。

**修复：** 使用单次扫描的正则替换或先替换最长匹配的键。

#### OPT: host:port 解析重复

| 属性 | 值 |
|------|-----|
| **文件** | `backend/main.py`, `src/monitor_core.py`, `src/network_test.py` |
| **级别** | 🟢 OPT |

至少 4 处重复实现 `host:port` 解析逻辑。应提取到 `src/utils/network_utils.py`：

```python
def parse_host_port(url: str, default_port: int = 80) -> tuple[str, int]:
    parsed = urlparse(url)
    host = parsed.hostname or ""
    port = parsed.port or default_port
    return host, port
```

#### OPT: RLock → Lock

| 属性 | 值 |
|------|-----|
| **文件** | `src/monitor_core.py:68` |
| **级别** | 🟢 OPT |

`self._config_lock = threading.RLock()`。没有证据表明此锁需要可重入性。使用 `RLock` 会隐藏潜在的可重入 bug。建议改为 `threading.Lock()`。

---

## 5. 安全分析报告

| ID | 严重性 | 问题 | 文件 | 类型 |
|----|--------|------|------|------|
| S-1 | 🟠 高 | Playwright 始终禁用 HTTPS | `browser.py:140`, `main.py:249` | MITM |
| S-2 | 🟠 高 | 远程仓库获取是 SSRF 向量 | `main.py:698-743` | SSRF |
| S-3 | 🟡 中 | 用户名在日志中明文记录 | `config_service.py:300`, `main.py:490` | 日志泄露 |
| S-5 | 🟡 中 | 3 个端点无 Pydantic 验证 | `main.py` | 输入验证 |
| S-6 | 🟡 中 | 无安全标头中间件 | `main.py` | 缺少 CSP/XFO/HSTS |
| S-10 | 🟢 中 | StaticFiles 暴露目录列表 | `main.py:1311-1313` | 信息泄露 |
| S-7 | 🟢 低 | 远程仓库获取使用用户配置的代理 | `main.py:693` | 信任用户输入 |
| S-9 | 🟢 低 | 前端截图 URL 清理基本路径遍历 | `formatters.js:24-28` | XSS |
| N-7 | 🟢 低 | 备份端点文件存在性判定 | `main.py:1218-1224` | 信息泄露 |

### S-2 详细分析: 远程仓库获取 SSRF

```python
@app.get("/api/repo/fetch")
async def repo_fetch_index(url: str = Query(...)):
    # ...
    resp = _requests.get(url, headers=headers, timeout=15, proxies=proxies)
```

`url` 参数来自用户前端的输入。虽然 `_normalize_repo_url()` 进行了规范化，但验证宽松：

```python
def _normalize_repo_url(url: str) -> str:
    if url.startswith(("http://", "https://")):
        return url  # 直接返回，不做进一步验证
    # ...
```

攻击者可以提供 `http://169.254.169.254/latest/meta-data/`（云 metadata 端点）或 `http://127.0.0.1:50721/api/config`（自请求）。

**修复：** 添加 IP 地址黑名单/白名单，或使用专门的 HTTP 客户端禁止私有 IP 范围。

---

## 6. 并发与线程安全分析

### 6.1 线程模型

```
app.py 主线程
  ├── Uvicorn 主线程 (asyncio 事件循环)
  │     ├── FastAPI 同步路由 → 线程池 worker
  │     └── FastAPI 异步路由 → 事件循环中执行
  ├── 监控线程 (守护线程)
  │     └── NetworkMonitorCore.start_monitoring()
  │           ├── monitor_network() 循环
  │           └── attempt_login() 使用独立 asyncio 循环
  ├── Shutdown 守护线程
  │     └── /api/shutdown 创建
  └── 系统托盘线程 (守护线程)
```

### 6.2 线程安全检查表

| 变量 | 文件 | 线程 | 有锁？ | 风险 |
|--------|------|----------|-------|------|
| `_loop` | `monitor_core.py` | 监控 ↔ Uvicorn | ❌ | 🟡 P2 TOCTOU |
| `_loop_stopped` | `monitor_core.py` | 监控 ↔ Uvicorn | ❌ | 🟡 P2 TOCTOU |
| `_executor` | `network_test.py` | 线程池 ↔ 任意 | ❌ | 🟡 P2 竞争 |
| `_block_proxy` | `network_test.py` | 监控 → 线程池 | ❌ | 🟢 P3 理论风险 |
| `_decryption_failed` | `crypto.py` | API handler 线程 | ❌ | 🟢 P3 理论风险 |
| `_root_configured` | `logging.py` | 任意（启动时） | ❌ | 🟢 P3 TOCTOU |
| `_debug` | `main.py` | Uvicorn 协程 | ✅ `_debug_lock` | 安全 |
| `service` | `main.py` | API 线程池 | ⚠️ 内部锁 | 🟡 P2 有待验证 |
| `login_attempt_count` | `monitor_core.py` | 仅监控线程 | N/A | 安全 |

### 6.3 关键竞争条件可视化

```
R-1: 事件循环竞争
  Monitor Thread                     Uvicorn Thread
  attempt_login()                     stop_monitoring()
  ┌─ if _loop_stopped: ──False──┐
  │                             │   _loop_stopped = True
  │                             │   _loop.close()
  │                             │   _loop = None
  │ if _loop is None: → True    │
  │ _loop = new_event_loop()    │
  │ run_until_complete(...)     │
  └─────────────────────────────┘
  结果: 浪费的新循环, 被 finally 链清理

N-3: Executor 竞争
  Thread A                         Thread B
  _get_executor()                   _get_executor()
  ┌─ _executor is None → True      ┌─ _executor is None → True
  │ _executor = TPE_A              │ _executor = TPE_B
  │ return TPE_A                   │ return TPE_B (TPE_A 泄漏!)
  └────────────────                └────────────────

N-1: 日志竞争
  Thread A (emit)                   Thread B (close)
  ┌─ with _emit_lock:              ┌─ (无锁!)
  │ _stream.write(msg)             │ _stream.close()
  │                                │ _stream = None
  │ _stream.write(msg)  → ERROR!   │
  └─ except Exception: pass        └─
  结果: 日志条目静默丢失
```

---

## 7. Frontend / Vue 3 审查

### 7.1 WebSocket 状态机

```
                    ┌──────────────┐
                    │  未初始化     │
                    │ (ws = null)   │
                    └──────┬───────┘
                           │ init()
                           ▼
                    ┌──────────────┐
               ┌───▶│  连接中       │◀─── 重连定时器触发
               │    │ (new WS())   │     (lifecycle.js:236)
               │    └──────┬───────┘
               │           │ onopen
               │           ▼
               │    ┌──────────────┐
               │    │  OPEN        │──▶ onmessage → 日志/状态
               │    │ (已连接)      │──▶ onclose (错误/关闭)
               │    └──────┬───────┘
               │           │ onclose
               │           ▼
               │    ┌──────────────┐
               │    │  重连中      │
               │    │              │
               │    └──────┬───────┘
               │           │
               │           └─────── 超过 5 次 → 提示刷新
               │
               │    ┌──────────────┐
               └────│  DESTROYED   │
                    │ (组件卸载)    │
                    └──────────────┘

竞争条件转换 (BUG):
  OPEN (新) ──旧 onclose──▶ 重连 (杀掉仍正常的新连接!)
```

### 7.2 前端文件风险矩阵

| 文件 | 行数 | 严重 Bug | 中 Bug | 轻微 Bug |
|------|------|-----------|---------|-----------|
| `lifecycle.js` | 245 | - | P2-1 竞争条件 | 陈旧捕获 |
| `app-options.js` | 227 | - | P2-2 toast 泄漏 | - |
| `profiles.js` | ~80 | - | P2-5 后退导航 | - |
| `logger.js` | 63 | - | - | - |
| `formatters.js` | 41 | - | S-9 路径遍历防护 | - |
| `settings.html` | ~500 | - | P2-3 NaN | - |

### 7.3 `_waitWebSocketReady()` 陈旧捕获（理论风险）

```javascript
// lifecycle.js:38
const ws = this.ws;  // 调用时捕获
// 如果 connectWebSocket() 在此 Promise 待处理时替换了 this.ws:
// 'open' 和 'close' 监听器仍在旧的（可能已关闭的）WS 上
```

使用 `{ once: true }` 保证最多触发一次。仅从 `autoCheckUpdateOnStartup()` 调用，此函数在 WS 稳定后才执行。风险极低。

---

## 8. 后端 API 审查

### 8.1 路由清单（49 条路由）

| 方法 | 路径 | 模型 | try/except? | 风险 |
|------|------|-------|-------------|------|
| GET | `/api/health` | dict | ❌ | 🟢 |
| GET | `/api/check-update` | dict | ✅ | 🟢 |
| GET | `/api/init-status` | dict | ❌ | 🟢 |
| GET | `/api/config` | `MonitorConfigPayload` | ❌ | 🟢 |
| PUT | `/api/config` | `ActionResponse` | ✅ ValueErrors | 🟡 |
| GET | `/api/status` | `MonitorStatusResponse` | ❌ | 🟢 |
| GET | `/api/logs` | `list[LogEntry]` | ❌ | 🟢 |
| POST | `/api/monitor/start` | `ActionResponse` | ❌ | 🟡 N-4 |
| POST | `/api/monitor/stop` | `ActionResponse` | ❌ | 🟡 N-4 |
| POST | `/api/actions/login` | `ActionResponse` | ❌ | 🟡 N-4 |
| POST | `/api/actions/test-network` | `ActionResponse` | ❌ | 🟡 N-4 |
| GET | `/api/autostart/status` | `AutoStartStatusResponse` | ❌ | 🟢 |
| POST | `/api/autostart/enable` | `ActionResponse` | ❌ | 🟡 N-4 |
| POST | `/api/autostart/disable` | `ActionResponse` | ❌ | 🟡 N-4 |
| GET | `/api/tasks` | 无 | ❌ | 🟢 |
| GET | `/api/tasks/active` | 无 | ❌ | 🟢 |
| GET | `/api/tasks/{task_id}` | 无 | ❌ | 🟢 |
| PUT | `/api/tasks/{task_id}` | `ActionResponse` | ❌ | 🟡 N-4 |
| DELETE | `/api/tasks/{task_id}` | `ActionResponse` | ❌ | 🟡 N-4 |
| POST | `/api/tasks/active/{task_id}` | `ActionResponse` | ❌ | 🟡 N-4 |
| GET | `/api/profiles` | 无 | ❌ | 🟢 |
| GET | `/api/profiles/active` | 无 | ❌ | 🟢 |
| GET | `/api/profiles/{profile_id}` | 无 | ❌ | 🟢 |
| PUT | `/api/profiles/{profile_id}` | `ActionResponse` | ❌ | 🟡 N-4 |
| DELETE | `/api/profiles/{profile_id}` | `ActionResponse` | ❌ | 🟡 N-4 |
| POST | `/api/profiles/active/{profile_id}` | `ActionResponse` | ❌ | 🟡 N-4 |
| POST | `/api/profiles/detect` | 无 | ✅ | 🟢 |
| POST | `/api/profiles/auto-switch` | `ActionResponse` | ❌ | 🟡 N-4 |
| POST | `/api/shutdown` | `ActionResponse` | ❌ | 🟡 N-4 |
| POST | `/api/debug/*` | 无 | ✅ | 🟢 |
| POST | `/api/backup/create` | `ActionResponse` | ✅ | 🟢 |
| POST | `/api/backup/restore/{filename}` | `ActionResponse` | ✅ | 🟢 |
| DELETE | `/api/backup/{filename}` | `ActionResponse` | ✅ | 🟢 |

### 8.2 响应形状不一致

正常响应：
```json
{"success": true, "message": "监控已启动"}
```

异常响应（同一路由，未处理异常时）：
```json
{"detail": "Internal Server Error"}
```

这意味着前端如果直接解析 `response.success` 会在异常时拿到 `undefined`。此问题影响所有标记为 🟡 N-4 的路由。

---

## 9. 圈复杂度分析

### 前 10 名

| 排名 | 文件 | 函数 | 行数 | McCabe 圈复杂度 | 已测试？ |
|------|------|----------|-------|-----------------|-------|
| 1 | `src/utils/login.py` | `_perform_login_with_active_task()` | 135 | **27** | ❌ |
| 2 | `src/playwright_bootstrap.py` | `ensure_playwright_ready()` | 60 | **19** | ❌ |
| 3 | `src/monitor_core.py` | `attempt_login()` | 79 | **18** | ✅ 部分 |
| 4 | `src/utils/logging.py` | `emit()` | 42 | **17** | ✅ |
| 5 | `backend/main.py` | `restore_backup()` | 55 | **17** | ❌ |
| 6 | `backend/main.py` | `save_config()` | 22 | **16** | ❌ |
| 7 | `backend/profile_service.py` | `match_and_switch()` | ~90 | **16** | ❌ |
| 8 | `src/utils/browser.py` | `_start_browser()` | ~60 | **15** | ❌ |
| 9 | `src/task_executor.py` | `_ensure_input()` | ~80 | **15** | ✅ 部分 |
| 10 | `backend/main.py` | `debug_start()` | ~80 | **14** | ❌ |

### 重构目标

圈复杂度 > 10 的函数应从重构中受益。优先级：

1. **`_perform_login_with_active_task()`** (27): 提取浏览器初始化、健康检查、截图清理到单独的方法。添加测试。
2. **`ensure_playwright_ready()`** (19): 简化下载主机候选迭代。
3. **`attempt_login()`** (18): 提取事件循环管理到辅助方法。

---

## 10. 测试覆盖矩阵

### 10.1 模块覆盖

| 模块 | 测试文件 | 估算覆盖率 | 风险 | 备注 |
|--------|-----------|-------------|------|-------|
| `src/task_executor.py` | ✓ 有 | ✅ 70%+ | 🟢 低 | 主要逻辑已覆盖 |
| `src/utils/logging.py` | ✓ 有 | ✅ ~80% | 🟢 低 | emit, handler 已覆盖 |
| `src/network_test.py` | ✓ 有 | ✅ ~60% | 🟢 中 | TCP/HTTP 探测已覆盖 |
| `src/monitor_core.py` | ✓ 有 | ⚠️ ~40% | 🟡 **中** | 无并发测试 |
| `src/utils/crypto.py` | ✓ 有 | ✅ ~70% | 🟢 低 | 加密/解密已覆盖 |
| `src/utils/env.py` | ✓ 有 | ✅ ~80% | 🟢 低 | |
| `src/utils/login.py` | ✓ 有 | ❌ ~10% | 🔴 **高** | 仅暂停/关闭浏览器测试 |
| `src/utils/browser.py` | ✓ 有 | ❌ ~20% | 🟠 **中** | 仅基本生命周期 |
| `backend/main.py` | ✓ 有 | ❌ ~10% | 🔴 **高** | 49 个端点几乎无测试 |
| `backend/config_service.py` | ❌ 无 | 0% | 🟠 **中** | |
| `backend/profile_service.py` | ❌ 无 | 0% | 🟠 **中** | |
| `backend/monitor_service.py` | ❌ 无 | 0% | 🟠 **中** | WS 管理器无测试 |
| `backend/task_service.py` | ❌ 无 | 0% | 🟠 **中** | |
| `backend/schemas.py` | ❌ 无 | 0% | 🟢 低 | Pydantic 模型 |
| `src/utils/config.py` | ❌ 无 | 0% | 🟡 **中** | ConfigValidator |
| `src/playwright_bootstrap.py` | ❌ 无 | 0% | 🟡 **中** | |
| `src/system_tray.py` | ❌ 无 | 0% | 🟢 低 | GUI 组件，难测试 |
| `app.py` | ❌ 无 | 0% | 🟠 **高** | CLI 参数解析无测试 |
| `frontend/**/*.js` | ❌ 无 | 0% | 🔴 **高** | 整个前端无测试 |

### 10.2 关键缺口

```
                     覆盖率热力图
                     
src/task_executor     ████████████████░░░░  70%
src/utils/logging    ████████████████░░░░  80%
src/network_test     ████████████░░░░░░░░  60%
src/utils/crypto    ██████████████░░░░░░  70%
src/utils/env        ████████████████░░░░  80%
src/monitor_core     ████████░░░░░░░░░░░░  40%
src/utils/login      ██░░░░░░░░░░░░░░░░░░  10%
src/utils/browser    ████░░░░░░░░░░░░░░░░  20%
backend/main.py      ██░░░░░░░░░░░░░░░░░░  10%
backend/* (其余)     ░░░░░░░░░░░░░░░░░░░░   0%
app.py               ░░░░░░░░░░░░░░░░░░░░   0%
frontend/**/*.js     ░░░░░░░░░░░░░░░░░░░░   0%
```

### 10.3 建议的新测试

| 优先级 | 测试套件 | 理由 |
|--------|-----------|-------|
| 🔴 P0 | `backend/main.py` HTTP API | 49 个端点，10 个关键（start/stop/login/monitor） |
| 🔴 P0 | `src/utils/login.py` 登录流程 | 圈复杂度 27，0% 覆盖 |
| 🟠 P1 | `backend/monitor_service.py` WS 管理器 | 连接生命周期，broadcast，close_all |
| 🟠 P1 | `app.py` CLI 参数 | `--tray`, `--status`, `--stop`, `--no-browser` |
| 🟡 P2 | `src/monitor_core.py` 并发 | 多线程竞争条件测试 |
| 🟡 P2 | Pydantic schema 验证 | `schemas.py` 字段级测试 |
| 🟡 P2 | 前端 E2E | WS 重连，profile 编辑器，设置页 |

---

## 11. 资产风险热力图

```
高风险 / 需立即关注
  ┌────────────────────────────────────────────────────┐
  │ src/monitor_core.py         │ R-1 竞争, P1-1 泄漏  │
  │ src/utils/login.py          │ CC 27, 0% 测试覆盖   │
  │ backend/main.py             │ 22×E402, N-4, N-5   │
  │ frontend/.../lifecycle.js   │ P2-1 stale onclose  │
  │ src/utils/logging.py        │ N-1 close/emit 竞争  │
  │ src/utils/browser.py        │ S-1 HTTPS 硬编码     │
  │ app.py                      │ N-2 signal 死锁      │
  └────────────────────────────────────────────────────┘

中等风险
  ┌────────────────────────────────────────────────────┐
  │ src/network_test.py         │ N-3 executor 竞争    │
  │ src/utils/env.py            │ P2-4 模板子串        │
  │ backend/monitor_service.py  │ P1-2 WS 泄漏         │
  │ frontend/.../app-options    │ P2-2 toast 泄漏      │
  │ frontend/.../profiles.js    │ P2-5 后退导航        │
  │ backend/profile_service.py  │ 0% 测试覆盖           │
  │ backend/task_service.py     │ 0% 测试覆盖           │
  └────────────────────────────────────────────────────┘

低风险
  ┌────────────────────────────────────────────────────┐
  │ frontend/.../settings.html  │ P2-3 v-model NaN     │
  │ src/utils/crypto.py         │ 全局变量无锁          │
  │ src/utils/config.py         │ 0% 测试覆盖           │
  │ backend/main.py S-10        │ 目录列表泄露          │
  │ backend/main.py N-7         │ 文件存在性判定         │
  └────────────────────────────────────────────────────┘
```

---

## 12. 修复优先级路线图

### 第一优先: 立即执行 (P1 + 安全)

| ID | 任务 | 文件 | 预估精力 |
|----|------|------|----------|
| S-1 | 使 `ignore_https_errors` 可配置 (schema + 逻辑 + UI) | `schemas.py`, `browser.py`, `main.py`, `settings.html`, `profiles.html` | ~50 行 |
| N-1 | 修复 `close()`/`emit()` 竞争条件 | `logging.py` | ~5 行 |
| P1-1 | 修复 socket 泄漏 | `monitor_core.py` | ~2 行 |
| P1-2 | 修复 WS 连接泄漏 | `monitor_service.py` | ~5 行 |
| S-2 | SSRF 防护：添加私有 IP 黑名单 | `main.py` | ~15 行 |

### 第二优先: 今日处理 (P2)

| ID | 任务 | 文件 | 预估精力 |
|----|------|------|----------|
| N-2 | 重构 signal handler 避免死锁 | `app.py` | ~5 行 |
| N-3 | 为 `_get_executor()` 添加锁 | `network_test.py` | ~10 行 |
| N-4 | 为 14 个 ActionResponse 路由添加 try/except | `main.py` | ~80 行 |
| N-5 | 为 `save_task` 和 `uninstall` 添加 Pydantic 模型 | `main.py`, `schemas.py` | ~30 行 |
| R-1 | 为 `_loop`/`_loop_stopped` 添加锁 | `monitor_core.py` | ~20 行 |
| P2-1 | 添加 WS generation 计数器修复陈旧 onclose | `lifecycle.js` | ~5 行 |
| P2-2 | 清理 `_toastLeavingTimer` | `app-options.js` | ~3 行 |
| P2-3 | 添加 NaN 守卫 | `settings.html` | ~10 行 |
| P2-5 | 修复 showProfileEditor 后退导航 | `profiles.js` | ~3 行 |

### 第三优先: 本周处理 (P3 + OPT)

| ID | 任务 | 文件 | 预估精力 |
|----|------|------|----------|
| N-6 | 修正 `_require_debug_session` 状态码 | `main.py` | ~2 行 |
| N-7 | 修复 restore_backup 检查顺序 | `main.py` | ~5 行 |
| N-8 | `toggle_auto_switch` 输入验证 | `main.py` | ~10 行 |
| N-10 | 修复 `list_backups` TOCTOU | `main.py` | ~5 行 |
| S-10 | 添加 StaticFiles 目录列表防护 | `main.py` | ~3 行 |
| P2-4 | 修复模板替换子串问题 | `env.py` | ~10 行 |
| OPT | 提取 host:port 解析为共享函数 | `network_utils.py` | ~20 行 |
| OPT | RLock → Lock | `monitor_core.py` | ~2 行 |
| OPT | Ruff E402/F841 修复 | `main.py` | ~5 行 |
| OPT | 添加 `_perform_login_with_active_task` 测试 | `test_login.py` | ~80 行 |

### 第四优先: 持续改进

| 任务 | 预估精力 |
|------|----------|
| `app.py` CLI 测试 (~30 个用例) | ~120 行 |
| `backend/main.py` API 集成测试 (~49 个端点) | ~500 行 |
| `backend/monitor_service.py` WS 管理器测试 | ~150 行 |
| 前端 JS 单元测试 (Vue 组件) | ~300 行 |
| 并发/压力测试 (monitor_core, network_test) | ~200 行 |

---

## 13. 附录

### 13.1 审查工具链

| 工具 | 用途 |
|------|---------|
| `grep` | 文本模式搜索（except, global, os.environ, socket, ...） |
| `ast-grep` | AST 模式搜索（可变默认参数, 星号导入, `__del__`） |
| `pytest` | 运行 351 个测试 |
| `Read` | 阅读 ~3000 行源代码 |
| `lsp_diagnostics` | 类型检查（Python 项目无类型错误） |
| 后台 agent | 5 个并行探索 agent 用于深入专家分析 |

### 13.2 Python 异常捕获注意事项

| 构造 | 捕获 |
|-----------|--------|
| `except:` | **所有** 异常，含 `SystemExit`, `KeyboardInterrupt`, `GeneratorExit` |
| `except Exception:` | **仅** `Exception` 子类（不捕获 `SystemExit` 等） |
| `except BaseException:` | 同 `except:` |

**本项目：** 全部使用 `except Exception:` — 不会抑制 `SystemExit`/`KeyboardInterrupt`。✅

### 13.3 关键代码参考

```python
# src/monitor_core.py — 事件循环管理 (R-1)
_loop: Optional[asyncio.AbstractEventLoop] = None  # 锁保护缺失
_loop_stopped: bool = False                         # 锁保护缺失

# src/utils/env.py — 模板替换 (P2-4)
def build_login_env_vars(...) -> dict[str, str]:
    for k, v in env_vars.items():
        resolved_url = resolved_url.replace("{{" + k + "}}", v)  # 子串风险

# frontend/js/methods/lifecycle.js — WebSocket 重连 (P2-1)
this.ws.onclose = () => {
    if (this._wsDestroyed) return;  # 仅防护销毁，不防护陈旧
```

### 13.4 版本信息

| 字段 | 值 |
|-------|-------|
| 项目 | Campus-Auth |
| 版本 | v3.6.7 |
| 审查日期 | 2026-05-25 |
| 测试 | 351/351 通过 |
| Ruff | 23 错误 (22×E402 + 1×F841) |

---

*报告生成由 Atlas (OhMyOpenCode Master Orchestrator) 完成*  
*两轮独立验证: 5 × 后台探索 agent + 亲自代码分析*
