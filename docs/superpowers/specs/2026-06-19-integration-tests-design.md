# 集成测试设计：组件连接测试 + 自启动模拟

## 目标

补充组件间连接测试，验证数据在真实组件间正确流转。只 mock 外部边界（Playwright、网络 socket），不 mock 内部组件。

## 范围

- 4 条链路的连接测试（登录、配置、网络检测、Profile 切换）
- 3 种自启动模式的生命周期模拟（轻量、完整、LOGIN_ONCE）
- 约 20 个新增测试

## 设计原则

1. **验证行为，不验证实现细节** — 断言 `login_history.count`、`engine.status`，不断言 `engine._retry_count`、`future._callbacks`
2. **Event 同步，不用 sleep** — 用 `threading.Event` 协调测试线程和引擎线程
3. **短间隔加速** — `check_interval_seconds=1`，避免 CI 慢
4. **不重复单元测试** — 连接测试关注组件间数据流转，不覆盖已有单元测试的分支

## 测试基础设施

### `tests/test_integration/conftest.py` 新增 fixture

```python
@pytest.fixture
def integration_stack(tmp_path):
    """创建真实组件栈。

    真实组件：ProfileService、TaskExecutor、ScheduleEngine
    Mock 边界：Playwright worker、网络探测

    Returns:
        (engine, profile_service, task_executor, mock_worker)
    """
```

实现要点：
- `ProfileService(tmp_path)` — 真实文件 I/O，tmp_path 隔离
- `TaskExecutor` — 真实线程池，mock 的 `worker_getter`
- `ScheduleEngine` — 真实命令队列，真实配置加载
- mock worker 通过 `side_effect` 控制每次登录结果
- 创建 `tmp_path / "config" / "settings.json"` 写入初始配置

```python
@pytest.fixture
def full_stack(tmp_path):
    """完整模式组件栈。

    在 integration_stack 基础上增加：
    - 真实 TaskRegistry + TaskHistoryStore
    """
```

### 同步策略

```python
# 登录完成事件：mock worker side_effect 在执行后 set
login_done = threading.Event()

def mock_submit(*args, **kwargs):
    login_done.set()
    return WorkerResponse(success=True, data="登录成功")

mock_worker.submit.side_effect = mock_submit

# 测试线程等待
engine._do_network_check()
login_done.wait(timeout=5)
```

---

## 测试文件 1：`test_login_connection.py`

验证 **engine → task_executor → mock worker** 完整链路。

### 场景

| # | 场景 | 验证点 |
|---|---|---|
| 1 | auto_login_success | 自动登录成功 → 登录历史 +1，status 更新 |
| 2 | auto_login_retry | 登录失败 → 重试 → 最终成功 |
| 3 | retry_exhausted | 连续失败达 max_retries → 停止重试，历史记录失败 |
| 4 | manual_preempt_auto | 手动登录取消卡住的自动登录 → 手动登录成功 |
| 5 | callback_updates_history | 登录完成 → 历史记录写入 + 状态快照更新 |
| 6 | concurrent_dedup | 用 Event 阻塞 worker → 两个线程提交 → submit 只调一次 |
| 7 | reload_during_login | 登录进行中 → 保存配置 → reload → 旧登录正常结束，新配置已生效 |

### 并发去重的稳定写法

```python
start_event = threading.Event()
release_event = threading.Event()

def blocking_submit(*args, **kwargs):
    start_event.set()
    release_event.wait(timeout=5)
    return WorkerResponse(success=True, data="ok")

mock_worker.submit.side_effect = blocking_submit

# 线程 A 提交登录
engine._do_async_login()
start_event.wait(timeout=5)  # 等 worker 开始执行

# 线程 B 尝试提交，应被去重
future_b = task_executor.execute_login_async()
assert future_b is not None  # 返回已有 future

# 验证 submit 只调了一次
assert mock_worker.submit.call_count == 1

release_event.set()  # 释放 worker
```

### reload_during_login 场景

```python
login_done = threading.Event()
release_login = threading.Event()

def slow_login(*args, **kwargs):
    login_done.set()
    release_login.wait(timeout=5)
    return WorkerResponse(success=True, data="ok")

mock_worker.submit.side_effect = slow_login

# 启动登录
engine._do_async_login()
login_done.wait(timeout=5)

# 登录进行中，保存新配置
new_payload = MonitorConfigPayload(check_interval_seconds=60, ...)
save_and_apply(new_payload, profile_service, engine.reload_config)

# 释放登录
release_login.wait(timeout=5)

# 验证：旧登录正常完成，新配置已生效
assert engine.get_config().check_interval_seconds == 60
```

---

## 测试文件 2：`test_config_connection.py`

验证 **config_service → runtime_config → engine 配置生效**。

### 场景

| # | 场景 | 验证点 |
|---|---|---|
| 1 | save_apply_success | 保存 → 磁盘 + 运行时都更新 |
| 2 | save_apply_rollback | reload 失败 → 磁盘回滚，运行时不变 |
| 3 | interval_reload | 修改 check_interval → 重载后生效 |
| 4 | password_encrypt | 明文 → 磁盘 ENC: → 读取后解密还原 |
| 5 | log_level_reload | 修改 backend_log_level → 重载后生效 |

---

## 测试文件 3：`test_network_connection.py`

验证 **monitor_service → decision → engine 登录触发**。

### 场景

| # | 场景 | 验证点 |
|---|---|---|
| 1 | need_login | 网络不通 → 触发登录 → 历史 +1 |
| 2 | network_ok | 网络通 → 不触发登录，重试计数重置 |
| 3 | pause_window | 暂停时段 → check_once 跳过 |
| 4 | probe_exception | 探测抛异常 → 引擎继续运行 |
| 5 | profile_switch_signal | 方案切换 → engine reload + restart |

---

## 测试文件 4：`test_profile_connection.py`

验证 **profile_service → engine 配置重载 → 监控重启**。

### 场景

| # | 场景 | 验证点 |
|---|---|---|
| 1 | apply_profile | 切换方案 → engine 使用新凭证 |
| 2 | switch_while_monitoring | 监控运行中切换 → 旧配置停、新配置起，无线程泄漏 |
| 3 | delete_current_profile | 删除当前方案 → 回退到 default |

### switch_while_monitoring 场景

```python
# 启动监控
engine.start_monitoring()
assert engine._is_monitoring

# 切换方案（监控运行中）
engine.apply_profile("profile-b")

# 验证：监控重启，使用新配置
assert engine._is_monitoring
assert engine.get_config().username == "user-b"
```

---

## 测试文件 5：`test_lightweight_mode.py`

轻量模式全生命周期。

### 场景

```
t0  轻量模式启动 → engine 监控启动
t1  断网 → 自动登录 → 成功
t2  再次断网 → 自动登录 → 失败 → 重试 → 成功
t3  手动登录 → 验证可抢占
t4  停止监控 → 验证清理
```

验证行为：
- `engine._is_monitoring == True`（启动后）
- `login_history.count` 递增（登录成功后）
- `engine.get_status().network_state` 更新
- 关闭后所有线程 join 完成

---

## 测试文件 6：`test_full_mode.py`

完整模式全生命周期（含定时任务）。

### 场景

```
t0  完整模式启动 → engine + 调度器
t1  注册定时任务（shell 类型）
t2  断网 → 自动登录 → 成功
t3  触发 tick → 定时任务执行 → 历史记录
t4  手动登录 → 验证与定时任务不冲突
t5  保存配置 → 验证重载后生效
t6  关闭 → 验证线程池清理
```

### 定时任务测试

直接调用 `engine._run_schedule_tick()`，不等待真实时间：

```python
task_executor.save_task("test-task", {
    "name": "测试任务",
    "type": "shell",
    "command": "echo hello",
    "enabled": True,
    "hour": datetime.now().hour,
    "minute": datetime.now().minute,
})

engine._run_schedule_tick()

history = task_executor.get_history("test-task")
assert len(history) == 1
assert history[0]["status"] == "success"
```

---

## 测试文件 7：`test_login_once_mode.py`

LOGIN_ONCE 逻辑在 `main.py::_run_login_then_exit` 中。

### 场景

| # | 场景 | 验证点 |
|---|---|---|
| 1 | success | 登录成功 → 返回 LoginResult.EXIT |
| 2 | temporary_failure | 登录失败 → 返回 LoginResult.TEMPORARY_FAILURE |
| 3 | config_error | 无密码配置 → 返回 LoginResult.CONFIG_ERROR |

---

## Mock 边界汇总

| 外部依赖 | Mock 方式 |
|---|---|
| Playwright worker | `MagicMock` 模拟 `submit()` 返回 `WorkerResponse` |
| 网络探测 | `patch("app.network.decision.is_network_available")` |
| 文件系统 | `tmp_path` fixture（真实 I/O，隔离目录） |
| 时间 | 真实时间，短间隔加速 |

---

## 不做的事

- 不测试真实 Playwright 浏览器（CI 无头环境不稳定）
- 不测试前端 API 调用（已有 test_api/ 覆盖）
- 不重复现有单元测试已覆盖的分支
- 不验证内部实现细节（`_retry_count`、`_callbacks` 等）
- 不用 `time.sleep` 同步（用 `threading.Event`）
- 不真实等待定时任务调度（直接调用 `_run_schedule_tick()`）

## 文件结构

```
tests/test_integration/
├── conftest.py                    (新增 fixture)
├── test_login_connection.py       (7 tests)
├── test_config_connection.py      (5 tests)
├── test_network_connection.py     (5 tests)
├── test_profile_connection.py     (3 tests)
├── test_lightweight_mode.py       (1 test)
├── test_full_mode.py              (1 test)
├── test_login_once_mode.py        (3 tests)
├── test_app_startup.py            (已有)
├── test_login_flow.py             (已有)
├── test_scheduled_task.py         (已有)
└── test_multi_browser.py          (已有)
```
