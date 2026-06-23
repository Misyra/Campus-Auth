# 代码审查修复方案

> 生成时间：2026-06-23
> 范围：code-review-report.md 中 [4] 起的 Major 及 Minor 问题
> 已修复问题（不在本文档内）：[1] cancel_login async、[2] list_recent 竞态、[3] login_once 取消、[5] Go/Shell fallback 链、[7] resetConfig 持久化

---

## 目录

- Major: [4](#4) [5](#5) [6](#6) [7](#7) [8](#8) [9](#9) [10](#10)
- Minor: [11](#11) [12](#12) [13](#13) [14](#14) [15](#15) [16](#16) [17](#17) [18](#18) [19](#19) [20](#20) [21](#21) [22](#22) [23](#23) [24](#24) [25](#25) [26](#26) [27](#27) [28](#28) [29](#29) [30](#30) [31](#31) [32](#32) [33](#33) [34](#34) [35](#35) [36](#36) [37](#37) [38](#38) [39](#39) [40](#40) [41](#41) [42](#42) [43](#43) [44](#44) [45](#45)

---

## Major

### [4] execute_task_async 队列满时缺少结构化降级路径 {#4}

- **文件**：`app/services/task_executor.py:164-168`
- **现状**：`RuntimeError` 被捕获后直接 re-raise，调用方（engine 调度器）需自行处理
- **方案**：在 `execute_task_async` 内部捕获 `RuntimeError`，返回一个已完成且带异常信息的 Future

```python
# 修改前
try:
    future = self._ensure_task_pool().submit(self.execute_task, task_id)
except RuntimeError:
    raise

# 修改后
try:
    future = self._ensure_task_pool().submit(self.execute_task, task_id)
except RuntimeError:
    logger.warning("任务队列已满，任务 {} 被拒绝", task_id)
    f: Future = Future()
    f.set_exception(RuntimeError(f"任务队列已满，无法提交任务 {task_id}"))
    return f
```

- **影响**：调用方无需额外 try/except，通过 `future.result()` 或 done callback 自然获取异常
- **风险**：低。不改变语义，仅将抛出时机从 submit 延迟到 result

---

### [5] 手动登录异常被误报为"超时" {#5}

- **文件**：`app/services/engine.py:831-837`
- **现状**：`cmd.response_data is None` 时只区分"引擎线程已死"和"超时"，不区分内部异常和取消
- **方案**：在 `_handle_login` 的异常处理中，将错误信息写入 `cmd.response_data`

```python
# engine.py _handle_login 的 except 块
except Exception as e:
    logger.error("手动登录异常: {}", e, exc_info=True)
    if cmd.response_event:
        cmd.response_data = (False, f"登录内部错误: {e}")
        cmd.response_event.set()
```

`run_manual_login` 中 `response_data is None` 分支保持不变（仅在真正超时时触发）。

- **影响**：异常和取消有独立的错误消息，超时仅在真正超时时出现
- **风险**：低。异常路径本来就是错误场景，只是改善错误信息

---

### [6] _handle_debug_stop 中 new_page() 缺少异常处理 {#6}

- **文件**：`app/workers/playwright_worker.py:613`
- **现状**：`self._context.new_page()` 无 try/except，失败后 `self._page` 指向已关闭的旧页面
- **方案**：为 `new_page()` 添加 try/except，失败时走完整重建路径

```python
# 修改前
self._page = await self._context.new_page()

# 修改后
try:
    self._page = await self._context.new_page()
except Exception:
    logger.exception("新建页面失败，尝试重建浏览器")
    self._page = None
    try:
        config = {"browser_settings": self._last_browser_settings or {}}
        await self._close_browser()
        await self._start_browser(config)
    except Exception:
        logger.exception("重建浏览器也失败")
```

- **影响**：调试停止后浏览器自动恢复可用状态
- **风险**：低。与 else 分支的重建逻辑一致，仅增加了一个恢复路径

---

### [7] TaskValidator 不验证 variables 字段类型 {#7}

- **文件**：`app/tasks/validator.py:54`（validate 方法末尾）
- **现状**：`validate()` 不检查 `variables` 类型，非 dict 值通过验证但运行时 TypeError
- **方案**：在 steps 验证之后、return 之前增加 variables 类型检查

```python
variables = config.get("variables")
if variables is not None and not isinstance(variables, dict):
    errors.append("'variables' 必须是对象（dict），当前值类型: " + type(variables).__name__)
```

- **影响**：非法 variables 在验证阶段即被拦截，错误信息直观
- **风险**：无。纯新增校验

---

### [8] TaskValidator 仅验证步骤级 timeout 而不验证任务级 timeout {#8}

- **文件**：`app/tasks/validator.py:54`（validate 方法末尾）
- **现状**：步骤级 timeout 有类型和正值检查，任务级 timeout 无任何校验
- **方案**：在 variables 校验之后添加任务级 timeout 校验

```python
timeout = config.get("timeout")
if timeout is not None and (
    not isinstance(timeout, int | float) or timeout <= 0
):
    errors.append(f"任务级 timeout 必须为正数，当前值: {timeout}")
```

- **影响**：非法 timeout 在验证阶段即被拦截
- **风险**：无。与步骤级 timeout 校验逻辑一致

---

### [9] _find_task_type 与 load_task 的目录搜索顺序不一致 {#9}

- **文件**：`app/tasks/manager.py:406-417`
- **现状**：`load_task` 先搜 browser 再搜 scripts，`_find_task_type` 先搜 scripts 再搜 browser
- **方案**：统一 `_find_task_type` 的搜索顺序为 browser 优先

```python
# 修改后
def _find_task_type(self, task_id: str) -> str | None:
    normalized = normalize_task_id(task_id)
    if not is_valid_task_id(normalized):
        return None
    for ext in (".json",):
        if (self.browser_dir / f"{normalized}{ext}").exists():
            return "browser"
    for ext in (".json", ".py"):
        if (self.scripts_dir / f"{normalized}{ext}").exists():
            return "scripts"
    return None
```

- **影响**：同一 task_id 在两个目录都存在时，行为一致
- **风险**：低。仅影响同名任务冲突的边缘场景

---

### [10] save_profile / delete_profile 在 apply_profile 失败时静默吞掉错误 {#10}

- **文件**：`app/api/profiles.py:76-80, 93-98`
- **现状**：`apply_profile` 失败仅记 warning 日志，API 仍返回 `success=True`
- **方案**：在 message 中附加警告信息

```python
# save_profile
except Exception:
    api_logger.warning("保存方案后应用方案失败", exc_info=True)
    message = f"{message}（注意：方案已保存但应用到引擎失败，请手动重载）"

# delete_profile
except Exception:
    api_logger.warning("删除方案后应用方案失败", exc_info=True)
    message = f"{message}（注意：方案已删除但引擎重载失败，请手动重载）"
```

- **影响**：前端 toast 显示警告，用户知道需要手动操作
- **风险**：低。不影响保存/删除本身的成功状态

---

## Minor

### [11] 配置变更日志遗漏 ISP 和运营商自定义字段 {#11}

- **文件**：`app/api/config.py:181-191`
- **现状**：遍历 `flat_old` 的键，ISP 和 carrier_custom 可能不在其中
- **方案**：补充遍历 `flat_new` 中 `flat_old` 没有的键 + 在 `FIELD_NAMES` 中补充 `"isp": "运营商"`, `"carrier_custom": "自定义运营商"`

```python
# 在 for field_name in flat_old: 循环之后添加
for field_name in flat_new:
    if field_name in flat_old or field_name in IGNORE_FIELDS:
        continue
    new_val = flat_new.get(field_name)
    if new_val:
        name = FIELD_NAMES.get(field_name, field_name)
        changes.append(f"{name}已设置")
```

---

### [12] set_source_level 端点绕过 Depends() 依赖注入 {#12}

- **文件**：`app/api/config.py:31-35`
- **评估**：`LogConfigCenter.get_instance()` 是全局单例，不走 DI 是合理设计
- **方案**：添加注释说明设计意图，不改代码

---

### [13] set_level 对无效日志级别静默降级为 INFO {#13}

- **文件**：`app/api/config.py:42-54`
- **方案**：调用后检查实际生效的级别，不一致时在响应中附加警告

```python
if source == "global":
    config.set_level(level)
    actual = config.get_config().get("level", "INFO")
    if actual != level.upper():
        return {"success": True, "message": f"无效级别 '{level}'，已降级为 {actual}"}
```

---

### [14] race_first_success 超时返回时未取消残留 future {#14}

- **文件**：`app/utils/concurrent.py:66-68`
- **方案**：在超时路径中取消残留 future

```python
except TimeoutError:
    logger.warning("{} 检测超时 ({:.1f}s)", label, timeout)
    for f in futures:
        if not f.done():
            f.cancel()
    return False
```

---

### [15] race_first_success 未对 future.result() 做防御性异常捕获 {#15}

- **文件**：`app/utils/concurrent.py:45`
- **方案**：添加 try/except Exception，循环结束后显式 `return False`

```python
for future in as_completed(futures, timeout=timeout):
    try:
        result = future.result(timeout=1)
    except Exception:
        logger.debug("{} 探测异常", label, exc_info=True)
        continue
    # ... 后续逻辑不变
```

---

### [16] _get_probe_client return 语句在锁保护范围之外 {#16}

- **文件**：`app/network/probes.py:54`
- **方案**：将 `return _probe_client` 移入 `with _probe_lock` 块内（缩进一层）

---

### [17] ipconfig 回退路径缺少 _is_valid_ipv4 验证 {#17}

- **文件**：`app/network/detect.py:150-153, 156-159`
- **方案**：两个 return 点增加 `_is_valid_ipv4(ip)` 校验

```python
if ip != "0.0.0.0" and _is_valid_ipv4(ip):
    return ip
```

---

### [18] nmcli terse 模式未反转义 SSID 中的冒号 {#18}

- **文件**：`app/network/detect.py:266-267`
- **方案**：返回前 `.replace("\\:", ":")`

```python
return line.split(":", 1)[1].strip().replace("\\:", ":")
```

---

### [19] all_disabled 时 method 返回 "none" 与文档不一致 {#19}

- **文件**：`app/network/decision.py:79`
- **方案**：改为 `"all_disabled"`

```python
return (False, "all_disabled", "all_disabled")
```

- **注意**：需检查调用方是否依赖 "none" 值。当前无消费方读取此字段做条件判断。

---

### [20] 函数内延迟导入 parse_url_checks 和 parse_ping_targets {#20}

- **文件**：`app/network/decision.py:65, 81`
- **方案**：移至模块顶层。确认无循环依赖。

---

### [21] macOS 网关检测的 "gateway" 关键词匹配可能命中非网关行 {#21}

- **文件**：`app/network/detect.py:288`
- **方案**：改为精确匹配行首

```python
if line.strip().lower().startswith("gateway:"):
```

---

### [22] ipconfig 回退第一个正则的 [\s.:]* 分隔符过于宽泛 {#22}

- **文件**：`app/network/detect.py:149`
- **方案**：改为 `[^\S\n.:]*`（排除换行符）

```python
pattern = re.compile(combined + rb"[^\S\n.:]*(\d+\.\d+\.\d+\.\d+)", re.DOTALL)
```

---

### [23] saveConfig abort 竞态可能导致 busy.save 状态闪烁 {#23}

- **文件**：`frontend/js/methods/config.js:94-101`
- **方案**：在 finally 中检查 abort controller 是否为当前请求

```javascript
const controller = this._saveAbortController;
// ... fetch ...
} finally {
  if (this._saveAbortController === controller) {
    this.busy.save = false;
  }
}
```

---

### [24] cloneConfig 浅拷贝共享数组引用 {#24}

- **文件**：`frontend/js/data/config.js:4-24`
- **方案**：对数组属性（`url_check_urls`）单独展开

```javascript
monitor: { ...src.monitor, url_check_urls: [...(src.monitor.url_check_urls || [])] },
```

---

### [25] closeEditor() 缺少脏值检测 {#25}

- **文件**：`frontend/js/methods/config.js`（closeEditor 方法）
- **方案**：仅在 `configDirty` 为 true 时弹确认框

```javascript
if (this.configDirty && !confirm('有未保存的更改，确定要关闭吗？')) return;
```

---

### [26] fetchBrowsers() 使用原始 fetch() 无超时 {#26}

- **文件**：`frontend/js/methods/` 相关文件
- **方案**：添加 AbortController 超时（10s）

---

### [27] atomic_write 在 os.fdopen 失败时泄漏文件描述符 {#27}

- **文件**：`app/utils/files.py:39-43`
- **方案**：在 `os.fdopen` 之前用 try/except 包裹，失败时 `os.close(tmp_fd)`

```python
try:
    try:
        f = os.fdopen(tmp_fd, "w", encoding=encoding, errors=errors)
    except Exception:
        os.close(tmp_fd)
        raise
    with f:
        f.write(content)
        f.flush()
        os.fsync(f.fileno())
```

---

### [28] decrypt_password 中 InvalidSignature 是死代码导入 {#28}

- **文件**：`app/utils/crypto.py:163`
- **方案**：移除 `from cryptography.exceptions import InvalidSignature`

---

### [29] 密钥加载时仅校验长度，不验证可用性 {#29}

- **文件**：`app/utils/crypto.py:46-55`
- **方案**：长度不是 32 字节时添加 warning 日志

```python
if len(key) == 32:
    _cached_raw_key = key
    return key
else:
    logger.warning("密钥文件长度异常: 期望 32 字节，实际 {} 字节", len(key))
```

---

### [30] async 函数 save_screenshot 内部使用同步阻塞 I/O {#30}

- **文件**：`app/utils/files.py:83-93`
- **评估**：截图频率低，实际影响可忽略
- **方案**：如需优化，截图用 buffer 模式 + `asyncio.to_thread` 写文件

---

### [31] save_password_field 对 ENC: 前缀值不做格式校验 {#31}

- **文件**：`app/utils/crypto.py:231-233`
- **方案**：添加轻量 base64 格式校验

```python
if raw.startswith("ENC:"):
    try:
        base64.urlsafe_b64decode(raw[4:])
        return raw
    except Exception:
        logger.warning("ENC: 值格式无效，将重新加密")
        # fall through to encrypt
```

---

### [32] run_sync 超时后未杀子进程树，可能导致孤儿进程 {#32}

- **文件**：`app/utils/shell_policy.py:236-238`
- **方案**：杀进程后调用 `proc.wait()` 回收僵尸进程

```python
except subprocess.TimeoutExpired:
    self._kill_process_tree_sync(proc.pid)
    proc.wait()
    return -1, "", f"命令执行超时 ({effective_timeout}s)"
```

---

### [33] LogConfigCenter.set_level 写 _config 未持锁 {#33}

- **文件**：`app/utils/logging.py:246-248`
- **方案**：复用 `_source_levels_lock`

```python
def set_level(self, level: str) -> None:
    normalized = normalize_level(level)
    logger.level(normalized)
    with self._source_levels_lock:
        self._config["level"] = normalized
```

---

### [34] verify_process_identity 在 create_time 缺失时静默降级 {#34}

- **文件**：`app/utils/process.py:101-107`
- **评估**：改为返回 False 会导致旧版 PID 文件无法识别
- **方案**：在 `read_pid_file` 中确保 `create_time` 必须存在，缺失则返回 None

---

### [35] start.go 信号转发 goroutine 缺少清理 {#35}

- **文件**：`start.go:234-245`
- **方案**：`cmd.Wait()` 之后调用 `signal.Stop(sigChan)` + `close(sigChan)`

```go
err := cmd.Wait()
signal.Stop(sigChan)
close(sigChan)
return err
```

---

### [36] start.sh 透传所有参数给 main.py {#36}

- **文件**：`start.sh:158-166`
- **评估**：start.sh 在检测到 `--install-only` 后直接 `exit 0`，不会执行到透传逻辑
- **方案**：添加注释说明，不改代码

---

### [37] start.sh curl 的 stderr 被静默丢弃 {#37}

- **文件**：`start.sh:73`
- **方案**：`2>/dev/null` 改为 `2>&1`

---

### [38] test_do_network_check_profile_switch 缺少 _handle_start 断言 {#38}

- **文件**：`tests/test_services/test_engine.py:589-601`
- **方案**：添加 `svc._handle_start.assert_called_once()`

---

### [39] test_extra_targets_empty_skip 依赖真实网络连通性 {#39}

- **文件**：`tests/test_core/test_network_probes.py:481-486`
- **方案**：添加 `@patch('app.network.decision.socket.create_connection', side_effect=TimeoutError)`

---

### [40] 集成测试未覆盖 v3→v4 配置迁移路径 {#40}

- **文件**：`tests/test_integration/test_login_flow.py`
- **方案**：添加一个使用 v3 格式 settings.json 的集成测试

---

### [41] _make_raw_engine 与 conftest.py 的 _make_raw 实现不一致 {#41}

- **文件**：`tests/test_integration/test_login_flow.py:34-73`
- **方案**：提取到共享模块或复用 conftest 的 `_make_raw`

---

### [42] 异步回调验证使用 time.sleep(0.1) 硬编码延迟 {#42}

- **文件**：`tests/test_services/test_engine.py:655-702`
- **方案**：用 `threading.Event` 替代 `time.sleep(0.1)`

---

### [43] _make_executor 辅助方法在 5 个测试类中重复定义 {#43}

- **文件**：`tests/test_services/test_task_executor_fix.py:335-419`
- **方案**：提取为模块级函数

---

### [44] 多线程测试的 mock side_effect 计数器非线程安全 {#44}

- **文件**：`tests/test_integration/test_login_flow.py:595-600`
- **方案**：用 `threading.Lock` 保护计数器

---

### [45] _capture_login_completion 的 task_executor 参数从未使用 {#45}

- **文件**：`tests/test_integration/test_login_integration_extended.py:36-73`
- **方案**：移除参数，更新所有调用点

---

## 修复优先级建议

### 第一梯队（可靠性，建议立即修复）

| # | 问题 | 工作量 |
|---|------|--------|
| 4 | execute_task_async 队列满降级 | 5 行 |
| 5 | 手动登录异常误报 | 10 行 |
| 6 | debug_stop new_page 异常 | 10 行 |
| 7+8 | TaskValidator 补全校验 | 10 行 |
| 9 | 搜索顺序统一 | 3 行 |
| 10 | apply_profile 失败提示 | 6 行 |

### 第二梯队（代码质量，可批量处理）

| # | 问题 | 工作量 |
|---|------|--------|
| 14+15 | race_first_success 防御 | 8 行 |
| 16 | 锁内 return | 1 行 |
| 17+18+21+22 | detect.py 小修复 | 4 行 |
| 27 | atomic_write fd 泄漏 | 5 行 |
| 28+29+31 | crypto.py 小修复 | 10 行 |
| 32 | run_sync 僵尸进程 | 1 行 |
| 33 | set_level 加锁 | 2 行 |
| 35 | start.go goroutine 清理 | 2 行 |

### 第三梯队（前端 + 测试，可后续处理）

| # | 问题 | 工作量 |
|---|------|--------|
| 23+24+25+26 | 前端 config.js | 15 行 |
| 11+13 | config.py 日志 | 10 行 |
| 37 | start.sh stderr | 1 行 |
| 38-45 | 测试修复 | 各 2-5 行 |

### 跳过（影响极低或需更多讨论）

| # | 原因 |
|---|------|
| 12 | LogConfigCenter 是全局单例，不走 DI 是合理设计 |
| 19 | method 返回值无消费方，改不改都行 |
| 20 | 延迟导入无实际危害 |
| 30 | 截图频率低，阻塞影响可忽略 |
| 34 | 需讨论 PID 文件格式兼容性 |
| 36 | 实际不会执行到透传逻辑 |
