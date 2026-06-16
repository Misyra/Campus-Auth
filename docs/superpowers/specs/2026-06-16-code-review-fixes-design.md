# 代码审查问题修复设计

> 日期：2026-06-16
> 来源：`code-review-report.md`（68 个问题）
> 范围：排除 22 个 + 3 个未确认后，修复全部 43 个确认问题

## 验证结论

| 类别 | 数量 |
|------|------|
| 已排除（per `.claude/not-to-do.md`） | 22 |
| 未确认（不成立或有意设计） | 3 |
| **需修复** | **43** |
| 其中 Critical | 8 |
| 其中 Major | 23 |
| 其中 Minor | 12 |

### 未确认项（不修复）

- [1] `__aexit__` + `ensure_browser` 冲突 — 有意设计（"删除浏览器复用逻辑"）
- [20] `start_monitoring` TOCTOU — 已有 `_start_stop_lock` 保护
- [46] `selectedBrowser` 状态不一致 — 两个字段始终同步到同一值

## 修复分组

### 第 1 组：浏览器自动化核心（`playwright_worker.py`）

**[11] `submit_nowait` 缺少队列满处理和 `_wake_async`**
- 添加 `try/except queue.Full`，队列满时返回错误
- 调用 `run_coroutine_threadsafe(self._wake_async(), loop)` 唤醒事件循环

**[12] `cleanup_orphan_browsers` 只清理 Chromium**
- 扩展过滤条件，增加 `"firefox"` 关键字匹配

**[13] `get_worker()` 锁内耗时操作**
- 将 `_worker` 赋值移到 `start()` 成功之后，避免其他线程拿到未初始化的 Worker

**[14] `_handle_debug_stop` 反检测脚本行为不一致**
- 使用与 `_start_browser` 完全相同的判断逻辑（检查 `pure_mode` + `stealth_mode`）

### 第 2 组：浏览器注册与安装（`browser_registry.py`、`playwright_bootstrap.py`、`install_playwright.py`）

**[4] Chromium 检测逻辑完全重复**
- 将检测逻辑抽取到 `browser_registry.py` 的公共函数 `has_playwright_chromium()`
- `playwright_bootstrap.py` 复用该函数，移除 `_has_chromium()`

**[5] `install_playwright` 布尔变量并发保护**
- 使用 `asyncio.Lock()` 替代 `_installing` 布尔变量

**[16] `ensure_playwright_ready` 修改 `os.environ` 无回滚**
- 函数入口保存原始值，函数结束（无论成功失败）恢复原值

**[17] Firefox 检测缺少 `LOCALAPPDATA` 路径**
- 补充 `%LOCALAPPDATA%\Mozilla Firefox\firefox.exe` 检测

**[18] `detect_browsers()` 无缓存**
- 添加模块级 TTL 缓存（30 秒），避免短时间内重复扫描

### 第 3 组：调度引擎（`engine.py`）

**[19] 手动登录路径污染自动重试计数**
- `_do_async_login` 添加 `is_manual` 参数，手动登录路径不递增 `count`

**[21] `shutdown` 绕过 Actor 模型**
- `_do_network_check` 开头获取 `_monitor_core` 本地引用后使用该局部变量

### 第 4 组：任务执行中心（`task_executor.py`）

**[2] `_ensure_task_pool` 懒初始化无锁保护**
- 使用 `threading.Lock` 实现双检锁模式

**[22] `execute_login_async` 去重返回旧 Future**
- 去重时将新 `cancel_event` 合并到已有任务（设置已有 event 或返回包装对象）

**[24] `_get_script_path` 路径推断脆弱**
- 在 `TaskRegistry` 上显式提供 `get_script_path(task_id)` 方法

### 第 5 组：配置服务（`config_service.py`、`runtime_config.py`）

**[26] `_update_global_settings` 遗漏 `lightweight_tray`**
- 补充 `global_settings.lightweight_tray = payload.lightweight_tray`

**[27] `_build_config_payload` 遗漏 `lightweight_tray`**
- 在 `payload_dict` 中补充 `lightweight_tray` 字段

**[28] 密码处理绕过 `save_password_field`**
- 将密码处理完全委托给 `save_password_field`，移除自行掩码判断

### 第 6 组：任务系统（`variable_resolver.py`、`step_handlers.py`）

**[6] `resolve_for_js` 双重编码**
- 统一将解析结果 `str()` 转为字符串后再 `json.dumps`

**[7] 变量解析缓存未绑定上下文**
- 添加版本号机制：`set_runtime_var` 递增版本号，`resolve` 检查版本号

**[33] OCR Timer 生命周期竞态**
- 将 `_cleanup_timers` 的读写纳入 `_ocr_lock` 保护范围

**[34] `SleepHandler` 缺少校验**
- 添加 `try/except` 包裹 `int()` 转换，添加负值检查

### 第 7 组：应用入口（`main.py`、`container.py`）

**[3] 轻量模式创建真正的 TaskExecutor**
- 根据 `_is_lightweight` 标志创建 `NullTaskExecutor`

**[29] 轻量模式关闭时 event loop 管理竞态**
- `container.shutdown()` 改为同步分离方式，不创建新 event loop

**[30] 轻量模式 Web 服务按需启动竞态**
- 使用 `threading.Lock` 保护 `_web_server_state["started"]` 检查和设置

### 第 8 组：调试会话管理（`debug_service.py`）

**[9] `run_all` 锁外访问 `_session`**
- 会话有效性检查移入 `async with self._lock` 块内

**[10] 超时监控器无锁读取 `_last_activity`**
- 将 `_last_activity` 读取移入锁保护范围内

**[44] `run_all` 与 `next_step` 并发保护不一致**
- `run_all` 在循环开始前一次性获取 `_exec_sem` 并持有到批量完成

**[45] `start` 方法锁内执行耗时操作**
- 将 Worker 启动调用移到锁外，失败时再加锁回滚状态

### 第 9 组：网络检测（`probes.py`）

**[35] `_get_probe_client` 快速路径 TOCTOU**
- 将快速路径读取移入锁内，或使用 `try/except` 处理 `AttributeError`

### 第 10 组：前端（`ui.js`）

**[47] 自定义浏览器交互逻辑错误**
- 为 `custom` 通道增加独立分支，聚焦到路径输入框

**[48] `installPlaywrightChromium` 无超时保护**
- 使用 `AbortController` 设置 600 秒超时

### 第 11 组：Minor 问题（12 个）

- [50] `STEALTH_INIT_SCRIPT` — 改用 `Object.defineProperty` 重写而非 `delete`
- [52] `_has_chromium()` 回退路径 — 移除 `sync_playwright` 回退，统一文件扫描
- [53] `consume_profile_switch_flag` 注释 — 修正注释为"由引擎线程串行调用"
- [54] `_do_network_check` profile switch — `_reload_config_internal` 失败时跳过 `_handle_start`
- [55] `ws_drain_loop` — 入口检查 `_ws_manager is not None`
- [56] `__init__` 重复 IO — 在 `_reload_config_internal` 中同时更新 `_pure_mode`
- [57] `get_default_shell` — 使用 `shutil.which` 验证回退路径
- [59] `BoundedExecutor.shutdown` — 当前可接受，添加注释说明
- [60] 密码掩码判断 — 改为完整匹配 `"••••••••"`
- [61] 字段重复定义 — 考虑让 `GlobalSettings` 继承共享 mixin
- [64] 终止进程后未验证 — `cleanup_pid` 前验证进程已退出
- [66] docstring 解析 — 使用 `ast.get_docstring()` 替代

## 设计原则

1. **最小改动** — 每个修复只触碰问题涉及的代码行，不做额外重构
2. **保持风格** — 与现有代码风格一致，不引入新依赖
3. **测试验证** — 每个修复应有对应测试验证（新增或更新现有测试）
4. **分组独立** — 每组修复可独立提交，减少冲突风险
