# Campus-Auth 全面优化计划（v2 — 审核修订版）

> 生成时间：2026-06-07
> 修订时间：2026-06-07（综合三个审核代理意见）
> 状态：**审核通过，可执行**

---

## 审核修订摘要

| 原计划项 | 审核结论 | 修订操作 |
|---------|---------|---------|
| 1.1 time_utils.py 移除 Dict/Any | 描述错误，实际有使用 | 改为删除重复导入 |
| 1.3 CREATE_NO_WINDOW_FLAG | 遗漏 shell_policy.py | 补充 |
| 1.5 移除 python-multipart | 不应移除（有直接使用） | 保留 |
| 1.5 移除 onnxruntime | 移除有风险 | 保留 |
| 2.1 httpx.Client 模块级单例 | 非线程安全 | 改用 threading.local |
| 2.3 增加 max_workers | 无证据是瓶颈 | 删除 |
| 2.4 filteredLogs 移到模板 | 可能更慢 | 改为增量缓存方案 |
| 3.2 截图逻辑去重 | 接口不兼容 | 扩展 save_screenshot 接口 |
| 3.3 _setup_dialog_handler | 仅 4 行，价值不大 | 保留内联 |
| 4.1 RuntimeConfigService | 设计不充分 | 简化为方法级重构 |
| 新增 | 登录成功固定等待 2 秒 | 补充 2.6 |
| 新增 | WS 广播队列轮询优化 | 补充 2.7 |
| 新增 | logging.py 向后兼容别名 | 补充 1.6 |
| 新增 | temp 目录启动时清理 | 补充 1.7 |
| 新增 | container.py 访问私有方法 | 补充 4.4 |
| 新增 | 测试覆盖缺失模块 | 补充 5.5 |
| 顺序调整 | 测试应前移 | 先补测试再重构 |

---

## 阶段一：快速修复（低风险，高收益）

### 1.1 修复重复导入

**文件变更：**
- `app/utils/logging.py:23` — 删除重复的 `from pathlib import Path`（第 22 行已有）

**验证方式：** `uv run ruff check app/utils/logging.py`

### 1.2 统一日志占位符风格

**文件变更：**
- `app/tasks/step_handlers.py` — 所有 `%s`、`%d` → `{}`
- `app/utils/shell_policy.py:62` — `%s` → `{}`
- `app/utils/login.py:155,249` — `%s` → `{}`
- `app/utils/crypto.py:229` — `%s` → `{}`（审核补充）

**验证方式：**
- `grep -rn "%[sdrf]" app/ --include="*.py" | grep logger` 确认无残留
- `uv run pytest tests/test_step_handlers.py tests/test_shell_policy.py`

### 1.3 统一 CREATE_NO_WINDOW_FLAG 使用

**文件变更：**
- `app/network/probes.py:97,120` — `getattr(subprocess, "CREATE_NO_WINDOW", 0)` → `from app.utils.platform_utils import CREATE_NO_WINDOW_FLAG`
- `app/network/detect.py:81-82` — 同上
- `app/utils/shell_policy.py:123,183` — `0x08000000` → `CREATE_NO_WINDOW_FLAG`（审核补充）

**验证方式：** `grep -rn "0x08000000\|CREATE_NO_WINDOW" app/` 确认只在 `platform_utils.py` 定义

### 1.4 删除 CSS 重复定义

**文件变更：**
- `frontend/styles/components.css:996` — 删除重复的 `@keyframes spin`

**验证方式：** 浏览器中加载动画仍正常

### 1.5 清理 pyproject.toml 依赖

**文件变更：**
- 移除 `python-multipart` — **审核确认：不移除**（FastAPI 文件上传直接依赖）
- 移除 `onnxruntime` — **审核确认：不移除**（ddddocr 版本兼容风险）
- 移除 `websockets>=16.0` — **审核确认：不移除**（之前有版本约束说明）
- 确认 `cairosvg` 用途 — 若无直接 import 则移除
- 删除 `[project.optional-dependencies].dev`，保留 `[dependency-groups].dev`（统一 uv 标准）

**验证方式：** `uv sync && uv run pytest`

### 1.6 清理 logging.py 向后兼容别名（审核补充）

**文件变更：**
- `app/utils/logging.py:95` — 删除 `_VALID_LOG_LEVELS = VALID_LOG_LEVELS`（检查无外部引用后）
- `app/utils/logging.py:104` — 删除 `_normalize_level = normalize_level`
- `app/utils/logging.py:171` — 删除 `WebSocketLogHandler = WebSocketSink`
- `app/utils/logging.py:304` — 删除 `_DateRotatingFileHandler = DateRotatingSink`

**验证方式：** `grep -rn "_VALID_LOG_LEVELS\|_normalize_level\|WebSocketLogHandler\|_DateRotatingFileHandler" app/` 确认无外部引用

### 1.7 启动时清理 temp 目录旧截图（审核补充）

**文件变更：**
- `app/application.py` — 在 lifespan startup 中添加 `cleanup_temp_screenshots()`（删除 temp/ 中超过 7 天的截图文件）

**验证方式：** 创建旧截图文件，重启服务后确认被清理

---

## 阶段二：性能优化

### 2.1 复用 httpx.Client（审核修订：threading.local）

**文件变更：**
- `app/network/probes.py` — 使用 `threading.local()` 为每个线程创建独立的 `httpx.Client`

```python
_thread_local = threading.local()

def _get_http_client() -> httpx.Client:
    if not hasattr(_thread_local, "client"):
        _thread_local.client = httpx.Client(verify=False, timeout=5.0)
    return _thread_local.client
```

**验证方式：** `uv run pytest tests/test_network_probes.py`

### 2.2 合并登录前置检查

**文件变更：**
- `app/network/decision.py` — 提取共享的网络检测结果，避免 `check_network_status` 和 `check_login_prerequisites` 重复调用
- `app/utils/login.py` — 将 `decision.py` 的导入移到模块顶部（消除延迟导入）

**验证方式：** `uv run pytest tests/test_decision.py`（新建）

### 2.3 filteredLogs 增量缓存（审核修订）

**文件变更：**
- `frontend/js/app-options.js:96-107` — 使用 Map 缓存已处理的日志条目，只对新增条目计算 `_screenshot`

```js
// 在 data 中添加
_logScreenshotCache: new Map(),

// 在 filteredLogs computed 中
filteredLogs() {
  let result = this.logs;
  // ...filter...
  return result.map(item => {
    if (!this._logScreenshotCache.has(item)) {
      this._logScreenshotCache.set(item, {
        ...item,
        _screenshot: this.extractScreenshotUrl(item.message)
      });
    }
    return this._logScreenshotCache.get(item);
  });
}
```

**验证方式：** 日志显示正常，截图检测功能正常

### 2.4 提取 applyAppearance 共享逻辑

**文件变更：**
- `frontend/app.js` — 提取 `_applyCSSVars(settings)` 共享函数
- `frontend/js/methods/appearance.js` — `applyAppearance` 调用共享函数

**验证方式：** 外观设置切换正常，Vue 挂载前后主题一致

### 2.5 登录成功后轮询确认（审核补充）

**文件变更：**
- `app/utils/login.py:220` — 将 `await asyncio.sleep(2)` 改为轮询网络状态

```python
# 原来：await asyncio.sleep(LOGIN_SUCCESS_SETTLE_SECONDS)
# 改为：轮询确认连接，最多等待 3 秒
for _ in range(6):
    await asyncio.sleep(0.5)
    if await _check_connected():
        break
```

**验证方式：** 登录流程正常，登录后不再固定等待 2 秒

### 2.6 WS 广播队列按需唤醒（审核补充）

**文件变更：**
- `app/services/monitor.py` — 添加 `_ws_event = asyncio.Event()`，`_push_log` 和 `_queue_status_broadcast` 中调用 `_ws_event.set()`，`_ws_drain_loop` 中 `await _ws_event.wait()` + `clear()`

**验证方式：** 空闲时 CPU 唤醒频率降低

---

## 阶段三：代码质量改进

### 3.1 Shell 检测逻辑去重

**文件变更：**
- 新建 `app/utils/shell_utils.py` — 提取 `detect_available_shells()` 和 `get_default_shell()`
- `app/services/scheduler.py` — 从 `shell_utils` 导入
- `app/workers/script_runner.py` — 从 `shell_utils` 导入（保留 `detect_available_binaries` 作为包装函数，添加 Python 解释器检测）

**验证方式：** `uv run pytest tests/test_scheduler*.py tests/test_script_runner.py`

### 3.2 截图逻辑去重（审核修订：扩展接口）

**文件变更：**
- `app/utils/file_helpers.py` — 扩展 `save_screenshot()` 接口，支持 `full_page`、`custom_dir` 参数
- `app/workers/playwright_worker.py:458-478` — `_handle_debug_start` 复用扩展后的 `save_screenshot()`

**验证方式：** 调试会话截图功能正常

### 3.3 拆分 `_perform_login_with_active_task`（审核修订：保留内联）

**文件变更：**
- `app/utils/login.py:118-236` — 拆分为：
  - `_ensure_task_manager()` — TaskManager 懒初始化
  - `_execute_browser_task(ctx)` — 浏览器任务执行路径
- `_setup_dialog_handler` 保留内联（审核认为仅 4 行，独立函数价值不大）

**验证方式：** `uv run pytest tests/test_login*.py`

### 3.4 拆分 `load_runtime_config`

**文件变更：**
- `app/services/config.py:134-212` — 拆分为：
  - `_merge_credentials(config, ui, flags)` — 凭证合并
  - `_merge_advanced_settings(config, ui, flags)` — 高级设置合并

**验证方式：** `uv run pytest tests/test_config*.py`

### 3.5 候选选择器降级模式提取

**文件变更：**
- `app/tasks/step_handlers.py` — 在 `StepHandler` 基类中提取 `_try_candidates_with_fallback(ctx, selector, action_fn, timeout)`
- `InputHandler` 和 `ClickHandler` 使用该方法

**验证方式：** `uv run pytest tests/test_step_handlers.py`

### 3.6 CSS 变量统一

**文件变更：**
- 多个 CSS 文件 — `border-radius: 10px` → `var(--radius-lg)`
- 多个 CSS 文件 — `backdrop-filter: blur(Npx)` → `var(--blur-sm/md/lg)`
- `components.css`, `logfiles.css` — `transition: all` → 显式属性列表

**验证方式：** 浏览器视觉检查无变化

### 3.7 前端组件化改进

**文件变更：**
- `frontend/partials/pages/tasks.html` — 列表项提取公共模板
- `frontend/partials/pages/scripts.html` — 同上

**验证方式：** 任务/脚本页面功能正常

---

## 阶段四：架构改进

### 4.1 MonitorService 方法级重构（审核修订：不新建 Service）

> 审核结论：新建 RuntimeConfigService 收益低、风险高（状态归属和线程安全设计不充分）。
> 改为方法级重构，不新建文件/Service。

**文件变更：**
- `app/services/monitor.py` — 将 `_reload_config_internal` 拆分为更清晰的子方法：
  - `_reload_runtime_config()` — 重载运行时配置
  - `_reload_ui_config()` — 重载 UI 配置
- 将 `_push_log` + `_ws_drain_loop` + `drain_ws_queue` 抽取为独立的内部类 `_LogBroadcaster`

**验证方式：** `uv run pytest tests/test_monitor_service.py`

### 4.2 统一依赖注入

**文件变更：**
- `app/deps.py` — 添加 `get_scheduler_service()`
- `app/api/scheduled_tasks.py` — 使用 `Depends(get_scheduler_service)`
- `app/api/system.py` — 同上

**验证方式：** `uv run pytest tests/test_api*.py`

### 4.3 修复穿透访问

**文件变更：**
- `app/services/task.py` — 添加 `get_script_path(task_id)` 公开方法
- `app/services/scheduler.py` — 使用 `task_service.get_script_path()`
- `app/api/scripts.py` — 同上

**验证方式：** `uv run pytest tests/test_task*.py tests/test_scheduler*.py`

### 4.4 container.py 访问私有方法修复（审核补充）

**文件变更：**
- `app/services/monitor.py` — 将 `_ws_drain_loop` 改为公开方法 `start_ws_drain_loop()`
- `app/container.py:86` — `self.monitor_service._ws_drain_loop()` → `self.monitor_service.start_ws_drain_loop()`

**验证方式：** `uv run pytest tests/test_container.py`

---

## 阶段五：测试补充

### 5.1 补充核心模块测试

**新建测试文件：**
- `tests/test_login_handler.py` — 覆盖 `app/utils/login.py` 的核心登录流程
- `tests/test_decision.py` — 覆盖 `app/network/decision.py` 的检查函数
- `tests/test_variable_resolver.py` — 覆盖 `app/tasks/variable_resolver.py`（审核补充）

**扩展测试文件：**
- `tests/test_playwright_worker.py` — 覆盖命令分发、submit 超时、队列满、Worker 自动恢复、异常传播
- `tests/test_debug_service.py` — 覆盖 start/step/stop/status/超时/并发访问/竞态条件

### 5.2 补充 API 路由测试

**扩展测试文件：**
- 覆盖 backup、tools、scripts、scheduled_tasks、system、logfiles 路由
- 包含错误路径测试（无效参数、资源不存在）

### 5.3 测试质量改善

**文件变更：**
- 合并重复的 `TestExecuteShellUsesPolicy`
- 提取 `test_monitor_service.py` 中重复的 mock patch 为 `conftest.py` 共享 fixture
- 清理断言不足的测试

### 5.4 回归测试确认

每个阶段完成后确认以下场景无回归：
- 密码加密/解密完整流程
- 配置方案切换（全局 ↔ 独立）
- 监控服务完整生命周期
- 前端外观设置切换
- 定时任务 CRUD + 执行

**验证方式：** `uv run pytest --cov=app --cov-report=term-missing` 覆盖率提升

---

## 执行顺序（审核修订）

```
阶段一（快速修复）
  ↓ uv run pytest
阶段五.1（补充核心模块测试 — 为后续重构建立安全网）
  ↓ uv run pytest
阶段二（性能优化）
  ↓ uv run pytest
阶段三（代码质量改进）
  ↓ uv run pytest
阶段四（架构改进）
  ↓ uv run pytest
阶段五.2-5.4（补充 API 测试 + 测试质量改善）
  ↓ uv run pytest --cov
```

---

## 风险评估

| 阶段 | 风险等级 | 回滚难度 | 审核备注 |
|------|---------|---------|---------|
| 阶段一 | 低 | 容易 | 全部审核通过 |
| 阶段二 | 中 | 中等 | 2.1 改用 threading.local 解决并发安全 |
| 阶段三 | 中 | 中等 | 3.2 扩展接口后去重，3.3 保留内联 |
| 阶段四 | 中 | 中等 | 4.1 简化为方法级重构，不新建 Service |
| 阶段五 | 低 | 容易 | 前移建立安全网 |
