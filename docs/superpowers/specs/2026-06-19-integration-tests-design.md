# 集成测试设计：组件连接测试 + 自启动模拟

## 目标

补充组件间连接测试，验证数据在真实组件间正确流转。只 mock 外部边界（Playwright、网络 socket），不 mock 内部组件。

## 范围

- 4 条链路的连接测试（登录、配置、网络检测、Profile 切换）
- 3 种自启动模式的全生命周期模拟（轻量、完整、LOGIN_ONCE）
- 约 24 个新增测试

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
    - 调度器启用
    """
```

### 同步策略

引擎线程和测试线程之间用 `threading.Event` 同步，避免 `time.sleep`：
- 登录完成事件：mock worker 的 side_effect 在执行后 set 一个 event
- 检测完成事件：engine 的 `_update_status_snapshot` 后检查条件
- 短间隔：`check_interval_seconds=1` 加速检测周期

---

## 测试文件 1：`test_login_connection.py`

验证 **engine → task_executor → mock worker → login.py** 完整链路。

### 场景

| # | 场景 | 验证点 |
|---|---|---|
| 1 | 自动登录成功 | engine 发信号 → task_executor 提交 → worker 执行 → 登录历史 +1 |
| 2 | 自动登录失败 | worker 返回失败 → 重试计数递增 → 重试间隔正确 |
| 3 | 登录重试耗尽 | 连续失败达 max_retries → 停止重试 |
| 4 | 手动登录抢占自动登录 | 手动登录取消卡住的自动登录 → 重新提交成功 |
| 5 | 登录完成回调 | Future done_callback → 状态快照更新 + 历史记录写入 |
| 6 | 并发登录去重 | 两个线程同时提交 → 只有一个实际执行 |
| 7 | 配置快照传递 | config_snapshot 正确传递到 worker，无 TOCTOU |

### Mock 设计

```python
# mock worker 模拟登录成功
mock_worker = MagicMock()
mock_worker.submit.return_value = WorkerResponse(success=True, data="登录成功")

# mock worker 模拟登录失败（用 side_effect 控制序列）
mock_worker.submit.side_effect = [
    WorkerResponse(success=False, error="网络超时"),
    WorkerResponse(success=False, error="网络超时"),
    WorkerResponse(success=True, data="登录成功"),
]
```

---

## 测试文件 2：`test_config_connection.py`

验证 **API → config_service → runtime_config → engine 配置生效**。

### 场景

| # | 场景 | 验证点 |
|---|---|---|
| 1 | 保存配置 → 运行时生效 | save_and_apply → reload → get_config 返回新值 |
| 2 | 保存失败回滚 | reload 失败 → 磁盘回滚到备份 → 运行时不变 |
| 3 | 配置变更 → 监控参数更新 | 修改 check_interval → 重载后 monitor 使用新间隔 |
| 4 | 密码加密保存 | 明文 → 保存后磁盘 ENC: → 读取后解密还原 |
| 5 | 日志级别变更 | 修改 backend_log_level → 重载后生效 |

### 验证方式

```python
# 保存后验证
result = save_and_apply(payload, profile_service, engine.reload_config)
assert result.success is True

# 读取磁盘验证
data = profile_service.load()
assert data.global_settings.check_interval_seconds == 60

# 运行时验证
config = engine.get_config()
assert config.check_interval_seconds == 60
```

---

## 测试文件 3：`test_network_connection.py`

验证 **monitor_service → decision → mock probes → engine 登录触发**。

### 场景

| # | 场景 | 验证点 |
|---|---|---|
| 1 | 网络不通 → 触发登录 | check_once 返回 need_login → engine 提交登录 |
| 2 | 网络通 → 不触发登录 | check_once 返回正常 → login_retry 重置 |
| 3 | 暂停时段 → 跳过检测 | 当前时间在暂停范围 → check_once 跳过 |
| 4 | 检测异常 → 不崩溃 | 探测抛异常 → 引擎继续运行 |
| 5 | 方案切换信号 | check_once 触发 profile switch → engine reload + restart |

### Mock 设计

```python
# mock 网络不通
with patch("app.network.decision.is_network_available", return_value=False):
    core.check_once()

# mock 暂停时段
with patch("app.network.decision.check_pause", return_value=(True, None)):
    result = core.check_once()
```

---

## 测试文件 4：`test_profile_connection.py`

验证 **profile_service → engine 配置重载 → 监控重启**。

### 场景

| # | 场景 | 验证点 |
|---|---|---|
| 1 | 切换方案 → 配置生效 | apply_profile → engine 使用新 profile 凭证 |
| 2 | 自动切换 | 网关 IP 变化 → detect_matching_profile → 自动切换 |
| 3 | 方案删除 | 删除当前方案 → 回退到 default |
| 4 | 方案切换失败 | reload 失败 → 继续使用旧方案 |

---

## 测试文件 5：`test_autostart_simulation.py`

模拟三种自启动模式的完整生命周期。

### 场景 A：轻量模式

```
t0  轻量模式启动 → engine 监控启动
t1  断网 → 自动登录 → 成功
t2  再次断网 → 自动登录 → 失败 → 重试 → 成功
t3  手动登录 → 验证可抢占
t4  停止监控 → 验证清理
```

### 场景 B：完整模式

```
t0  完整模式启动 → engine + web 服务 + 调度器
t1  注册定时任务（shell 类型，echo 命令）
t2  断网 → 自动登录 → 成功
t3  定时任务触发 → 验证执行 + 历史记录
t4  手动登录 → 验证与定时任务不冲突
t5  保存配置 → 验证重载后监控参数更新
t6  关闭 → 验证线程池清理
```

### 场景 C：LOGIN_ONCE 模式

LOGIN_ONCE 逻辑在 `main.py::_run_login_then_exit` 中，测试直接调用该函数。

```
t0  配置 startup_action=LOGIN_ONCE，写入 settings.json
t1  断网 → _run_login_then_exit → 自动登录成功 → 验证返回 LoginResult.EXIT
t2  登录失败 → 验证返回 LoginResult.TEMPORARY_FAILURE
t3  配置错误（无密码）→ 验证返回 LoginResult.CONFIG_ERROR
```

### 定时任务测试细节

```python
# 注册一个 shell 定时任务
task_config = {
    "name": "测试任务",
    "type": "shell",
    "command": "echo hello",
    "enabled": True,
    "hour": now_hour,  # 当前小时，确保立即触发
    "minute": now_minute,
}
task_executor.save_task("test-task", task_config)

# 触发调度 tick
engine._run_schedule_tick()

# 验证执行历史
history = task_executor.get_history("test-task")
assert len(history) == 1
assert history[0]["status"] == "success"
```

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
