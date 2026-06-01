# Campus-Auth 代码审计修复计划（审核通过版）

> **生成时间**: 2026-06-01
> **审核轮次**: 3 轮（初稿 → 3 并行 Agent 审核 → 修正）
> **基于**: `deve/code-review-report.md` 复核结果
> **修复范围**: 18 项确认可修复的问题

---

## 修复分组

| 组别 | 文件 | 修复项 | 审核状态 |
|------|------|--------|----------|
| A | `src/utils/crypto.py` | C-3 | 通过（已修正） |
| B | `src/utils/file_helpers.py` | C-4 | 通过 |
| C | `backend/monitor_service.py` | C-2, C-6 | 通过（已修正） |
| D | `backend/profile_service.py` | C-1 | 通过 |
| E | `backend/login_history_service.py` | C-9 | 通过（已修正） |
| F | `backend/routers/backup.py` | C-10 | 通过 |
| H | `src/utils/env.py` | C-5 | 通过 |
| I | `src/utils/login.py` | C-17 | 通过 |
| J | `src/utils/logging.py` | C-12, C-13 | 通过（已修正） |
| K | `src/task_executor.py` | C-15 | 通过 |
| L | `src/playwright_worker.py` | C-16 | 通过 |
| M | `src/utils/notify.py` | H-23 | 通过 |
| N | `frontend/js/methods/ui.js` | H-31 | 通过（已修正） |
| O | `frontend/js/methods/utils.js` | H-34 | 通过（已修正） |
| P | `frontend/js/` (4 文件) | C-18 | 通过 |
| Q | `CLAUDE.md` | C-19 | 通过 |

**延后处理**:
- C-7 (`apply_profile` 去除冗余 reload) — 审核不通过，需重新设计
- C-8 (shutdown 改用 lifespan) — Windows 信号不可靠，保留 `os._exit(0)` + 补充 `logging.shutdown()`
- C-11 (per-profile 解密追踪) — 调用方适配链过长，降为 P2 单独处理

---

## A 组: `src/utils/crypto.py` — C-3

### C-3: 密钥文件原子写 + 旧密钥备份

**审核修正**: 补充 `import time`（原方案遗漏）。

**文件顶部添加**:
```python
import time
from src.utils.file_helpers import atomic_write
```

**`_get_or_create_key` 中替换 line 55-63**:
```python
except Exception as exc:
    logger.error("读取加密密钥失败: %s", exc)
    # 备份损坏的密钥文件
    if _KEY_FILE.exists():
        backup_path = _KEY_FILE.with_suffix(f".bak.{int(time.time())}")
        try:
            _KEY_FILE.rename(backup_path)
            logger.info("已备份损坏的密钥文件到: %s", backup_path)
        except OSError as backup_err:
            logger.warning("备份密钥文件失败: %s", backup_err)
    logger.warning("将生成新密钥，此前加密的密码将无法解密")
```

**替换 line 61-63 的写入**:
```python
key = os.urandom(32)
encoded_key = base64.urlsafe_b64encode(key).decode("ascii")
atomic_write(str(_KEY_FILE), encoded_key, encoding="utf-8")
```

---

## B 组: `src/utils/file_helpers.py` — C-4

### C-4: `atomic_write` 删除 PermissionError 回退

**审核附注**: 需同步删除测试 `test_permission_error_fallback`（test_utils.py line 282-291）。

**替换 line 39-50**:
```python
os.replace(tmp_path, path)
```

删除整个 `except PermissionError` 块。

**测试修改**: 删除或重写 `test_permission_error_fallback`，改为验证 `PermissionError` 向上抛出。

---

## C 组: `backend/monitor_service.py` — C-2 + C-6

### C-2: `_login_in_progress` 改为 `threading.Event`

**审核修正**: 补充 property 修改和测试适配。

**`__init__` 中替换 line 110-111**:
```python
self._login_in_progress = threading.Event()
# 保留 self._login_lock 不删除（run_manual_login 的 check-then-set 仍需锁保证原子性）
```

**修改 `login_in_progress` property (line 437-438)**:
```python
@property
def login_in_progress(self) -> bool:
    return self._login_in_progress.is_set()
```

**修改所有读写点**:

| 位置 | 当前代码 | 修改为 |
|------|----------|--------|
| `run_manual_login` line 592-595 | `with self._login_lock: if self._login_in_progress: ... self._login_in_progress = True` | `with self._login_lock: if self._login_in_progress.is_set(): raise ... self._login_in_progress.set()` |
| `_handle_login` line 249 | `self._login_in_progress = False` | `self._login_in_progress.clear()` |
| `run_manual_login` line 611 | `self._login_in_progress = False` | `self._login_in_progress.clear()` |
| `run_manual_login` line 619 | `self._login_in_progress = False` | `self._login_in_progress.clear()` |
| `_handle_profile_switch` | 无检查 | 添加 `self._login_in_progress.clear()` |

**测试适配** (`test_monitor_service.py`):
- line 182: `assert svc._login_in_progress is False` → `assert not svc._login_in_progress.is_set()`
- line 606: `svc._login_in_progress = True` → `svc._login_in_progress.set()`
- line 721-722: `svc._login_in_progress = True` → `svc._login_in_progress.set()`，`svc.login_in_progress is True` → `svc._login_in_progress.is_set()`

### C-6: `_reload_config_internal` 加锁

**`__init__` 中添加**:
```python
self._reload_lock = threading.Lock()
```

**`_reload_config_internal` 中包裹**:
```python
def _reload_config_internal(self) -> None:
    with self._reload_lock:
        self._ui_config = load_ui_config(self._profile_service)
        self._runtime_config = _copy_runtime_config(
            build_runtime_config(load_runtime_config(self._profile_service), self._profile_service)
        )
```

**`get_config()` 加锁**:
```python
def get_config(self) -> MonitorConfigPayload:
    with self._reload_lock:
        return self._ui_config.model_copy(deep=True)
```

---

## D 组: `backend/profile_service.py` — C-1

### C-1: settings.json 损坏时自动备份 + 从 backups 恢复

**审核附注**: 建议在备份恢复循环中添加 debug 日志。

**替换 `_load_unsafe` 中 line 42-45**:
```python
except Exception as exc:
    profile_logger.exception("加载 settings.json 失败")
    # 备份损坏文件
    if self._settings_path.exists():
        corrupt_name = f"settings.corrupt.{int(time.time())}.json"
        corrupt_path = self._settings_path.parent / corrupt_name
        try:
            self._settings_path.rename(corrupt_path)
            profile_logger.info("已备份损坏文件到: %s", corrupt_path)
        except OSError as rename_err:
            profile_logger.warning("备份损坏文件失败: %s", rename_err)
    # 尝试从 backups/ 恢复最新备份
    restored = self._try_restore_from_backup()
    if restored:
        self._data = restored
        profile_logger.info("已从备份恢复配置")
        return self._data.model_copy(deep=True)
    # 无备份可用，使用空默认值
    profile_logger.warning("无可用备份，将使用空配置")
    self._data = ProfilesData()
```

**新增方法**:
```python
def _try_restore_from_backup(self) -> ProfilesData | None:
    """尝试从 backups/ 目录恢复最新有效备份"""
    from backend.constants import BACKUP_DIR
    if not BACKUP_DIR.exists():
        return None
    backups = sorted(BACKUP_DIR.glob("settings_*.json"), reverse=True)
    for backup_path in backups:
        try:
            raw = backup_path.read_text(encoding="utf-8")
            data = ProfilesData.model_validate_json(raw)
            profile_logger.info("从备份恢复: %s", backup_path.name)
            return data
        except Exception:
            profile_logger.debug("备份 %s 校验失败，跳过", backup_path.name)
            continue
    return None
```

---

## E 组: `backend/login_history_service.py` — C-9

### C-9: `_cleanup_old` 改用 atomic_write

**审核修正**: `kept` 中存储的是 JSON 字符串，不能用 `json.dumps(r)`（会双重编码）。直接拼接原始字符串。

**文件顶部添加**:
```python
from src.utils.file_helpers import atomic_write
```

**替换 line 112-114**:
```python
content = "\n".join(kept)
if kept:
    content += "\n"
atomic_write(str(self._history_path), content, encoding="utf-8")
```

注意：`self._history_path` 是 `Path` 对象，需 `str()` 转换。变量名修正为 `self._history_path`（非 `self._history_file`）。

---

## F 组: `backend/routers/backup.py` — C-10

### C-10: 读一次备份文件

**替换 line 97-111**:
```python
backup_content = backup_path.read_text(encoding="utf-8")
try:
    ProfilesData.model_validate_json(backup_content)
except Exception as exc:
    raise HTTPException(status_code=400, detail=f"备份文件格式错误: {exc}")
# ...
atomic_write(settings_path, backup_content, encoding="utf-8")
```

---

## G 组: `backend/routers/system.py` — C-8（降级处理）

### C-8: shutdown 补充日志 flush

**审核结论**: 主方案（信号触发 lifespan）在 Windows 上不可靠，不通过。采用降级方案。

**在 `os._exit(0)` 之前添加**:
```python
import logging
logging.shutdown()  # flush 所有日志 handler
os._exit(0)
```

---

## H 组: `src/utils/env.py` — C-5

### C-5: denylist 变量显式设置到 os.environ

**在模板替换循环之前添加**:
```python
for k, v in env_vars.items():
    if k.upper() in _ENV_DENYLIST_UPPER:
        os.environ[k] = v
```

**简化模板替换循环**（删除 denylist 检查）:
```python
for k, v in env_vars.items():
    placeholder = "{{" + k + "}}"
    if placeholder in task_url:
        task_url = task_url.replace(placeholder, v)
```

---

## I 组: `src/utils/login.py` — C-17

### C-17: except 路径尊重 `close_on_failure`

**替换 line 232-234**:
```python
except Exception:
    if self.close_on_failure:
        await self.close_browser()
    raise
```

---

## J 组: `src/utils/logging.py` — C-12 + C-13

### C-12: `emit` 中的 import 改用类属性延迟初始化

**审核修正**: 用类属性替代 `global` 语句。

**`WebSocketLogHandler` 类上添加类属性**:
```python
class WebSocketLogHandler(logging.Handler):
    _LogEntry: type | None = None  # 延迟初始化
```

**`emit` 方法中替换 import**:
```python
if self._log_store is not None:
    if WebSocketLogHandler._LogEntry is None:
        from backend.schemas import LogEntry
        WebSocketLogHandler._LogEntry = LogEntry
    self._log_store.append(WebSocketLogHandler._LogEntry(**log_data))
```

### C-13: `add_file_handler` 比较 log_dir

**审核修正**: 属性名是 `_log_dir`（非 `base_dir`），用 `list()` 复制避免迭代时修改。

**替换 line 339-341**:
```python
for handler in list(root.handlers):
    if isinstance(handler, _DateRotatingFileHandler):
        if str(handler._log_dir) == str(log_dir):
            return  # 相同目录，无需替换
        # 不同目录，移除旧 handler
        root.removeHandler(handler)
        handler.close()
        break
```

---

## K 组: `src/task_executor.py` — C-15

### C-15: `_FORCE_INPUT_JS` 支持 textarea

**替换 line 38-39**:
```js
const proto = el.tagName === 'TEXTAREA'
    ? HTMLTextAreaElement.prototype
    : HTMLInputElement.prototype;
const nativeSet = Object.getOwnPropertyDescriptor(proto, 'value').set;
```

---

## L 组: `src/playwright_worker.py` — C-16

### C-16: `stop()` 使用 `put_nowait`

**替换 line 143**:
```python
try:
    self._cmd_queue.put_nowait(WorkerCommand(type=CMD_SHUTDOWN))
except queue.Full:
    logger.warning("命令队列已满，强制停止 Worker")
    if self._loop is not None and self._loop.is_running():
        self._loop.call_soon_threadsafe(self._loop.stop)
    return
```

---

## M 组: `src/utils/notify.py` — H-23

### H-23: `msg` 命令检查 returncode

**替换 line 84-93**:
```python
result = subprocess.run(
    ["msg", os.environ.get("USERNAME", "*"), f"{title}: {message}"],
    capture_output=True,
    timeout=5,
    creationflags=subprocess.CREATE_NO_WINDOW
    if hasattr(subprocess, "CREATE_NO_WINDOW")
    else 0,
)
return result.returncode == 0
```

---

## N 组: `frontend/js/methods/ui.js` — H-31

### H-31: `quitApp` 设置 `_wsDestroyed` 阻止重连

**审核修正**: 补充注释说明设置时机。

**在 `quitApp` 方法中，POST 之前添加**:
```javascript
// 后端 shutdown 是异步的，WS 可能在 POST 响应返回前就断开
// 必须在 POST 之前设置，否则 onclose 会触发无意义的重连
this._wsDestroyed = true;
if (this.ws) {
    this.ws.onclose = null;
    this.ws.onerror = null;
    this.ws.close();
}
```

---

## O 组: `frontend/js/methods/utils.js` — H-34

### H-34: `extractApiError` 处理 422 数组

**审核修正**: 空数组时回退到 `fallback`。

```javascript
export function extractApiError(error, fallback = '操作失败') {
  const detail = error?.response?.data?.detail;
  if (Array.isArray(detail)) {
    return detail.map(d => d.msg || d.detail || String(d)).join('; ') || fallback;
  }
  return detail || error?.message || fallback;
}
```

---

## P 组: `frontend/js/` — C-18

### C-18: `_initErrorCount` 在 init 末尾重置

**在 `frontend/js/methods/lifecycle.js` 的 `Promise.all([...])` 完成后添加**:
```javascript
// 初始化完成后重置错误计数器，允许后续运行时错误正常显示通知
this._initErrorCount = 0;
```

---

## Q 组: `CLAUDE.md` — C-19

### C-19: 更新变量优先级描述

**替换 line 127 的描述**:
> `{{VAR_NAME}}` resolves through runtime vars -> env vars -> task variables (runtime overrides env overrides task)

---

## 修复顺序

1. **B 组** (`file_helpers.py`) — 基础设施
2. **A 组** (`crypto.py`) — 数据安全
3. **C 组** (`monitor_service.py`) — 并发安全
4. **D 组** (`profile_service.py`) — 依赖 B 组
5. **E 组** (`login_history_service.py`) — 依赖 B 组
6. **F ~ Q 组** — 独立修复

---

## 测试策略

| 组 | 测试方法 | 备注 |
|----|----------|------|
| A | `uv run pytest tests/test_utils.py -v -k crypto` | |
| B | `uv run pytest tests/test_utils.py -v -k atomic` | 需删 `test_permission_error_fallback` |
| C | `uv run pytest tests/test_monitor_service.py -v` | 3 处断言已适配 Event |
| D | `uv run pytest tests/test_backend_services.py -v` | |
| E | 手动测试：写入旧格式 jsonl，验证清理不丢数据 | |
| F | `uv run pytest tests/test_api.py -v -k backup` | |
| H | `uv run pytest tests/test_utils.py -v -k env` | |
| I | 手动测试：模拟异常场景验证浏览器不被关闭 | |
| J | `uv run pytest tests/test_utils.py -v -k logging` | |
| K | `uv run pytest tests/test_task_executor.py -v -k input` | |
| L | `uv run pytest tests/test_src_utils.py -v -k worker` | |
| M | 手动测试：Windows Home 上 msg 命令失败 | |
| N | 手动测试：quitApp 后检查 WS 重连行为 | |
| O | 手动测试：触发 422 错误验证显示 | |
| P | 手动测试：启动时断网，恢复后检查通知 | |
| Q | 文档检查 | |
