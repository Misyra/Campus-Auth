# 🔍 Ponytail 全仓库过度工程化审查报告

**日期**: 2026-06-29  
**范围**: 全仓库扫描（Python 后端 + JS 前端 + 测试套件）  
**维度**: 死代码、标准库替代、框架原生替代、单调用抽象、可压缩逻辑  
**预估削减**: ~3,600 行, ~5 个依赖可移除

---

## 目录

1. [Top 5 最大削减](#top-5-最大削减)
2. [测试套件瘦身](#1-测试套件瘦身)
3. [服务层过度抽象](#2-服务层过度抽象)
4. [工具层死代码与冗余](#3-工具层死代码与冗余)
5. [任务系统与 API 层](#4-任务系统与-api-层)
6. [核心基础设施](#5-核心基础设施)
7. [前端死代码与冗余](#6-前端死代码与冗余)
8. [汇总统计](#汇总统计)

---

## Top 5 最大削减

| # | 标签 | 发现 | 预估削减 |
|---|------|------|----------|
| 1 | `delete` | 删除 test_monitor_service.py — 916 行，85% 与 test_engine.py 重叠 | **-900 行** |
| 2 | `delete` | 删除 test_engine_fix.py — 183 行，90% 与 test_engine.py 重叠 | **-170 行** |
| 3 | `yagni` | 合并 SchedulerService + StatusManager + LoginBridge 到 ScheduleEngine | **-280 行** |
| 4 | `delete` | 删除 test_src_utils.py 中重复的 crypto/logging/files 测试类 | **-400 行** |
| 5 | `yagni` | 合并 14 个 frontend/js/data/*.js 文件为 1 个 | **-200 行** |

---

## 1. 测试套件瘦身

### 1.1 `delete` test_monitor_service.py — 85% 与 test_engine.py 重叠

**文件**: `tests/test_services/test_monitor_service.py` (916 行)  
**问题**: 该文件测试的 `ScheduleEngine` 方法与 `test_engine.py` (1834 行) 高度重叠。21 个测试类中有 19 个与 test_engine.py 中的同名类测试完全相同的功能。

**重叠对照表**:

| test_monitor_service.py | test_engine.py 对应 |
|---|---|
| `TestEngineCommand` | `TestEngineCommand` |
| `TestStatusSnapshot` | `TestStatusSnapshot` |
| `TestScheduleEngineInit` | `TestEngineInit` |
| `TestRecordLog` | `TestRecordLog` |
| `TestListLogs` | `TestListLogs` |
| `TestGetStatus` | `TestGetStatus` |
| `TestUpdateStatusSnapshot` | `TestUpdateStatusSnapshot` |
| `TestStartStopMonitoring` | `TestStartStopMonitoring` |
| `TestHandleStartStop` | `TestHandleStart` + `TestHandleStop` |
| `TestHandleLogin` | `TestHandleLogin` |
| `TestRunManualLogin` | `TestRunManualLogin` |
| `TestNetwork` | `TestNetwork` |
| `TestTogglePureMode` | `TestTogglePureMode` |
| `TestGetConfig` | `TestGetConfig` |
| `TestShutdownSynchronous` | `TestShutdown` |
| `TestReloadConfigQueueDispatch` | `TestReloadConfig` |
| `TestApplyProfileQueueDispatch` | `TestApplyProfile` |

**仅有的非重叠测试** (需迁移):
- `TestProfileSwitchFlag` (3 tests) — 测试 `NetworkMonitorCore._check_profile_switch`
- `TestSaveProfileApplyId` (1 test) — 测试 `app.api.profiles.save_profile`

**操作**: 迁移 4 个独有测试 → 删除整个文件。**削减 ~900 行**。

---

### 1.2 `delete` test_engine_fix.py — 90% 与 test_engine.py 重叠

**文件**: `tests/test_services/test_engine_fix.py` (183 行)  
**问题**: 包含 2 个独立测试 + 1 个类 `TestManualLoginCancelRaceFix` (4 tests)。

```python
# test_engine_fix.py — 独立测试 1: 与 test_engine.py TestHandleLogin.test_handle_login_success 重复
def test_handle_login_uses_validated_config(engine_factory):
    ...

# 独立测试 2: 测试 MonitorSettings schema 默认值，应归入 schema 测试
def test_engine_test_network_default_false():
    ...

# TestManualLoginCancelRaceFix: 测试 _do_async_login 行为
# 已被 test_engine.py 的 TestDoAsyncLogin (7 tests) + TestNetworkCheckBackoff (8 tests) 覆盖
class TestManualLoginCancelRaceFix:
    ...
```

**操作**: 删除整个文件。**削减 ~183 行**。

---

### 1.3 `delete` test_container_fix.py — 与 test_container_cleanup_fix.py 重叠

**文件**: `tests/test_services/test_container_fix.py` (14 行, 1 个测试)

```python
# test_container_fix.py — 唯一的测试
def test_lightweight_container_has_real_task_executor(tmp_path):
    """验证 lightweight 模式使用真实的 TaskExecutor 而非 dummy。"""
    container = ServiceContainer(tmp_path, mode="lightweight")
    assert isinstance(container.task_executor, TaskExecutor)
```

**操作**: 合并到 `test_container_cleanup_fix.py` → 删除文件。**削减 14 行**。

---

### 1.4 `shrink` test_debug_service.py — 与 test_debug_session_manager.py 重叠

**文件**: `tests/test_services/test_debug_service.py` (406 行)  
**问题**: 两个文件定义了相同的辅助函数 (`_make_manager`, `_ok_response`, `_fail_response`, `_set_session_running`)。test_debug_session_manager.py (764 行) 已全面覆盖 DebugSessionManager。

**test_debug_service.py 中仅有的独有测试** (需迁移):
- `TestDebugTimeoutWatcherActualTimeout` (3 tests)
- `TestStartTemplateVarReplacement` (1 test)
- `TestNextStepSessionReplaced` (2 tests)
- `TestRunAllSessionReplaced` (3 tests)
- `TestStopTempDirCleanupError` (2 tests)

**操作**: 迁移 5 个独有测试类到 test_debug_session_manager.py → 删除文件。**削减 ~300 行**。

---

### 1.5 `shrink` test_src_utils.py — 重复 crypto/logging/files 覆盖

**文件**: `tests/test_utils/test_src_utils.py` (1118 行)  
**问题**: "厨房水槽"式测试文件，重复了更深入的专项测试文件的覆盖：

| test_src_utils.py 中的类 | 被覆盖于 |
|---|---|
| `TestEncryptDecrypt` (7 tests) | `test_crypto.py` — 有密钥缓存、损坏文件等更深覆盖 |
| `TestSavePasswordField` (7 tests) | `test_crypto.py` |
| `TestDecryptionError` (2 tests) | `test_crypto.py` |
| `TestLogConfigCenter` (6 tests) | `test_logging_fix.py` + test_utils.py |
| `TestNormalizeLevel` | `test_logging_fix.py` |
| `TestAtomicWrite` (8 tests) | `test_files_fix.py` + test_utils.py |

**操作**: 删除重叠类，保留独有的 (platform, str_to_bool, network, version, time_utils, exceptions, env, constants 等)。**削减 ~400 行**。

---

### 1.6 `shrink` test_logging_fix.py — 严格子集

**文件**: `tests/test_utils/test_logging_fix.py` (56 行)  
**问题**: 3 个测试覆盖 `LogConfigCenter._LEVEL_ORDER` 和 `should_emit`，是 test_src_utils.py `TestLogConfigCenter` 的严格子集。

**操作**: 删除文件。**削减 56 行**。

---

### 1.7 `shrink` test_files_fix.py — 窄切片

**文件**: `tests/test_utils/test_files_fix.py` (57 行)  
**问题**: 2 个测试 `atomic_write` 跨文件系统行为。test_utils.py 的 `TestAtomicWrite` 已从 8 个角度覆盖。

**操作**: 合并到 test_utils.py → 删除文件。**削减 57 行**。

---

### 1.8 `shrink` test_scripts_fix.py — 与 test_api_scripts_routes.py 重叠

**文件**: `tests/test_api/test_scripts_fix.py` (69 行)  
**问题**: 测试 `run_script` 使用专用 `ThreadPoolExecutor`，是实现细节测试。

**操作**: 合并到 test_api_scripts_routes.py → 删除文件。**削减 69 行**。

---

### 1.9 `delete` tests/conftest.py 未使用 fixture

**文件**: `tests/conftest.py`  
**问题**: 定义了 `tmp_pid_dir` 和 `patched_webbrowser` 两个 fixture，但全仓库无任何测试引用。

```python
@pytest.fixture
def tmp_pid_dir(tmp_path):
    """提供临时 PID 目录。"""
    ...

@pytest.fixture
def patched_webbrowser(monkeypatch):
    """模拟 webbrowser.open。"""
    ...
```

**操作**: 删除两个 fixture。**削减 ~20 行**。

---

## 2. 服务层过度抽象

### 2.1 `yagni` SchedulerService — 仅 ScheduleEngine 消费

**文件**: `app/services/scheduler_service.py` (87 行)  
**问题**: 整个类仅被 `ScheduleEngine` 一个消费者使用。它持有两个浮点数和一个布尔值 (`_scheduler_running`, `_next_schedule_tick`)，所有逻辑可以直接内联到 engine.py。

```python
class SchedulerService:
    """定时任务调度器。"""

    def __init__(self, task_registry, task_executor) -> None:
        self._task_registry = task_registry
        self._task_executor = task_executor
        self._scheduler_running = False
        self._next_schedule_tick = 0.0

    @property
    def running(self) -> bool:
        return self._scheduler_running

    @property
    def next_tick_time(self) -> float:
        return self._next_schedule_tick

    def start(self) -> None:
        if self._scheduler_running:
            return
        self._scheduler_running = True
        self._next_schedule_tick = (int(time.time() // 60) * 60) + 60

    def stop(self) -> None:
        self._scheduler_running = False

    def should_tick(self, now: float) -> bool:
        return self._scheduler_running and now >= self._next_schedule_tick

    def tick(self, now: float) -> None:
        # ... 查询到期任务并执行
        self._next_schedule_tick = (int(time.time() // 60) * 60) + 60

    def sync_state(self) -> None:
        # ... 自动启停

    def has_enabled_tasks(self) -> bool:
        return self._task_executor.registry.has_enabled_tasks() if self._task_executor else False
```

**操作**: 内联到 ScheduleEngine。**削减 ~87 行**。

---

### 2.2 `yagni` ConfigBuilder — 类包装单个 @staticmethod

**文件**: `app/services/config_builder.py` (52 行)  
**问题**: 整个类只有一个 `@staticmethod build()`，无状态、无继承。应该是普通函数。

```python
class ConfigBuilder:
    """GlobalConfig + Profile → RuntimeConfig，全项目唯一的凭据注入点。"""

    @staticmethod
    def build(global_config: GlobalConfig, profile: Profile) -> RuntimeConfig:
        """构建运行时配置。ISP 转换、密码过滤只在此处发生。"""
        username = profile.username.strip()
        raw_password = profile.password.strip()
        password = raw_password if (raw_password and not raw_password.startswith("•")) else ""
        # ... 30 行构建逻辑
        return RuntimeConfig(...)
```

**操作**: 改为 `def build_runtime_config(global_config, profile) -> RuntimeConfig`。**削减 ~5 行类开销**。

---

### 2.3 `yagni` LoginBridge — 仅 engine 消费

**文件**: `app/services/engine.py` 中的 `LoginBridge` 类 (~130 行)  
**问题**: 仅被 `ScheduleEngine._do_async_login` 和 `ScheduleEngine.cancel_login` 调用。每次只实例化一个。

**操作**: 内联到 ScheduleEngine。**削减 ~130 行间接层**。

---

### 2.4 `yagni` StatusManager + StatusSnapshot — 仅 engine 内部

**文件**: `app/services/engine.py`  
**问题**: `StatusManager` (~60 行) 和 `StatusSnapshot` (9 字段 dataclass) 仅在 engine.py 内部使用，无外部消费者。

**操作**: 折叠到 ScheduleEngine。**削减 ~60 行**。

---

### 2.5 `yagni` _debug_response() — 一行包装

**文件**: `app/services/debug_service.py:43-44`  
**问题**: 包装 `debug_to_response(self._session)`，被 ~10 处调用。

```python
def _debug_response(self) -> dict:
    return debug_to_response(self._session)
```

**操作**: 所有调用处直接替换为 `debug_to_response(self._session)`。**削减 ~12 行** (方法定义 + 调用处间接)。

---

### 2.6 `delete` MonitoredPolicy.attempts() — 生产代码未调用

**文件**: `app/services/retry_policy.py:40-41`  
**问题**: 仅测试代码调用。

```python
def attempts(self) -> Iterator[int]:
    yield from range(1, self.max_retries + 1)
```

**操作**: 删除方法。**削减 3 行**。

---

### 2.7 `delete` TaskExecutor 两个死方法

**文件**: `app/services/task_executor.py`

```python
# 行 189-195 — 生产代码从未调用，API 路径是 engine → bridge → orchestrator
def is_login_running(self) -> bool:
    """检查是否有登录在执行。"""
    return self._login_orchestrator.is_running()

def cancel_login(self) -> None:
    """取消当前登录。"""
    self._login_orchestrator.cancel_running()
```

**操作**: 删除两个方法。**削减 8 行**。

---

### 2.8 `delete` NetworkMonitorCore 死参数和死常量

**文件**: `app/services/monitor_service.py`

```python
# 行 51 — 类常量从未被引用，间隔始终从 config 读取
DEFAULT_INTERVAL_SECONDS = 300

# 行 61-66 — __init__ 接受但类体从未使用
def __init__(self, config, log_callback=None, login_history=None,
             worker_getter: Callable | None = None):  # ← 死参数
    ...
    self._worker_getter = worker_getter  # ← 从未读取
```

**操作**: 删除常量和参数。**削减 ~5 行**。

---

### 2.9 `delete` WS_DRAIN_INTERVAL_SECONDS — 生产代码不读取

**文件**: `app/services/websocket_manager.py:23`, `app/services/engine.py` (re-export with `# noqa: F401`)

```python
# websocket_manager.py:23
WS_DRAIN_INTERVAL_SECONDS = 0.05

# engine.py — noqa 注释暴露了这是死导入
from app.services.websocket_manager import WS_DRAIN_INTERVAL_SECONDS  # noqa: F401
```

**操作**: 删除常量和 re-export。**削减 ~3 行**。

---

### 2.10 `shrink` _build_test_sites() — 内联

**文件**: `app/services/monitor_service.py:303-309`  
**问题**: 仅被 `_get_test_sites()` 调用，3 行函数体。

```python
def _build_test_sites(self) -> list[tuple[str, int]]:
    """构建测试站点列表"""
    targets = self.config.monitor.ping_targets
    result = parse_ping_targets(targets)
    if not result:
        result = parse_ping_targets(self.DEFAULT_PING_TARGETS)
    return result
```

**操作**: 内联到 `_get_test_sites`。**削减 ~8 行**。

---

### 2.11 `shrink` USER_DATA_DIR 别名

**文件**: `app/services/uninstall.py:16`

```python
from app.constants import AUTH_DATA_DIR, PROJECT_ROOT
USER_DATA_DIR = AUTH_DATA_DIR  # ← 冗余别名
```

**操作**: 直接使用 `AUTH_DATA_DIR`。**削减 1 行**。

---

### 2.12 `yagni` _get_script_path 的 hasattr 防御

**文件**: `app/services/task_executor.py:349-356`

```python
def _get_script_path(self, script_id: str):
    if hasattr(self._registry, "get_script_path"):  # ← TaskRegistry 总有此方法
        return self._registry.get_script_path(script_id)
    return None
```

**操作**: 直接调用 `self._registry.get_script_path(script_id)`。**削减 2 行**。

---

## 3. 工具层死代码与冗余

### 3.1 `delete` DecryptionError — 仅 crypto.py 内部使用

**文件**: `app/utils/exceptions.py:13-15`  
**问题**: `DecryptionError` 仅在 `crypto.py` 内部被捕获，从未被外部导入。应移为 crypto.py 的私有异常。

```python
class DecryptionError(Exception):
    """密码解密失败异常（密钥变更或数据损坏）"""
    pass
```

**操作**: 移到 `crypto.py` 作为 `_DecryptionError`。从 exceptions.py 删除。**削减 4 行**。

---

### 3.2 `delete` _ENV_DENYLIST_UPPER — 冗余预计算

**文件**: `app/utils/env.py:35-36`  
**问题**: `_ENV_DENYLIST` 中所有 key 本身已大写，`k.upper() in _ENV_DENYLIST` 与 `k in _ENV_DENYLIST_UPPER` 结果相同。

```python
_ENV_DENYLIST = {"PATH", "PYTHONPATH", "HOME", ...}  # 全部大写
_ENV_DENYLIST_UPPER = {k.upper() for k in _ENV_DENYLIST}  # ← 冗余
```

**操作**: 删除 `_ENV_DENYLIST_UPPER`，改用 `k.upper() in _ENV_DENYLIST`。**削减 2 行**。

---

### 3.3 `delete` ICONS_DIR — 死变量

**文件**: `app/utils/browser_registry.py:19-20`  
**问题**: 仅 `_get_icon_url()` 被调用（生成 URL 字符串），`ICONS_DIR` 文件路径从未被读取。

```python
ICONS_DIR = Path(__file__).parent.parent.parent / "resources" / "icons"  # ← 从未读取
```

**操作**: 删除。**削减 1 行**。

---

### 3.4 `stdlib` _check_command_exists → shutil.which

**文件**: `app/utils/browser_registry.py:207-209`  
**问题**: 包装 `shutil.which(command) is not None`，被 4 处调用。

```python
def _check_command_exists(command: str) -> bool:
    """检查命令是否存在。"""
    return shutil.which(command) is not None
```

**操作**: 4 处调用直接替换为 `shutil.which(command) is not None`。**削减 ~5 行**。

---

### 3.5 `native` BrowserInfo 重复定义

**文件**: `app/utils/browser_registry.py` (dataclass) vs `app/schemas.py` (Pydantic BaseModel)  
**问题**: 两个文件定义了同名类 `BrowserInfo`，`browsers.py` API 手动逐字段映射。

```python
# browser_registry.py
@dataclass
class BrowserInfo:
    channel: str
    name: str
    icon: str
    installed: bool
    needs_download: bool
    description: str

# schemas.py
class BrowserInfo(BaseModel):
    channel: str
    name: str
    icon: str
    installed: bool
    needs_download: bool
    description: str
```

**操作**: 删除 dataclass 版本，`detect_browsers()` 直接返回 Pydantic 模型。**削减 ~15 行 + 消除映射代码**。

---

### 3.6 `delete` normalize_repo_url — 单调用者

**文件**: `app/utils/repo_proxy.py:33-43`  
**问题**: 仅被同文件 `async_repo_fetch_json` 调用。

```python
def normalize_repo_url(url: str) -> str:
    """将 GitHub/Gitee 页面链接转换为 raw 链接"""
    m = re.match(r"https?://github\.com/([^/]+)/([^/]+)/blob/([^/]+)/(.+)", url)
    if m:
        return f"https://raw.githubusercontent.com/{m.group(1)}/{m.group(2)}/{m.group(3)}/{m.group(4)}"
    m = re.match(r"https?://gitee\.com/([^/]+)/([^/]+)/blob/([^/]+)/(.+)", url)
    if m:
        return f"https://gitee.com/{m.group(1)}/{m.group(2)}/raw/{m.group(3)}/{m.group(4)}"
    return url
```

**操作**: 内联到 `async_repo_fetch_json`。**削减 ~12 行**。

---

### 3.7 `yagni` safe_decrypt — 单调用者

**文件**: `app/utils/crypto.py:208-216`  
**问题**: 仅被 `decrypt_password_field` 调用。

```python
def safe_decrypt(ciphertext: str) -> tuple[str, bool]:
    """解密密码。返回 (解密结果, 是否有错误)"""
    if not ciphertext:
        return ("", False)
    try:
        return (decrypt_password(ciphertext), False)
    except DecryptionError:
        logger.error("密码解密失败，使用空密码")
        return ("", True)
```

**操作**: 内联到 `decrypt_password_field`。**削减 ~10 行**。

---

### 3.8 `yagni` decrypt_password/encrypt_password 重导出

**文件**: `app/utils/__init__.py:3,24-25`  
**问题**: 外部调用者全部使用 `save_password_field` 和 `decrypt_password_field`，这两个低级函数从未被外部直接导入。

```python
from .crypto import decrypt_password, encrypt_password  # ← 外部无人使用

__all__ = [
    ...
    "decrypt_password",   # ← 死导出
    "encrypt_password",   # ← 死导出
    ...
]
```

**操作**: 从 `__init__.py` 移除重导出。**削减 3 行**。

---

### 3.9 `shrink` _to_std_logging bridge — 生产环境也运行

**文件**: `app/utils/logging.py:57-84`  
**问题**: 为了让 pytest caplog 能捕获 loguru 日志而添加的桥接 sink，在生产环境也运行（每条日志都付出转发成本）。

```python
def _to_std_logging(message):
    """将 loguru 消息转发到标准 logging。"""
    record = message.record
    name = record["extra"].get("name", record["name"])
    level = record["level"].name
    level_map = {"DEBUG": logging.DEBUG, "INFO": logging.INFO, ...}
    std_level = level_map.get(level, logging.INFO)
    std_logger = logging.getLogger(name)
    std_logger.log(std_level, str(message).strip())

# 模块导入时就添加，生产环境也运行
logger.add(_to_std_logging, level="DEBUG", format="{message}")
```

**操作**: 改为条件加载（检测 pytest 或环境变量）。**生产环境减少每条日志的额外开销**。

---

### 3.10 `yagni` LogConfigCenter 单例模式过度设计

**文件**: `app/utils/logging.py:183-222`  
**问题**: 使用 `__new__` + `_init_lock` + `_initialized` 三重保护的单例模式。实际上只在应用启动时创建一次。

```python
class LogConfigCenter:
    _instance = None
    _init_lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._init_lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        ...
        self._initialized = True
```

**操作**: 简化为 module-level `_instance = None` + `get_instance()`。**削减 ~10 行**。

---

### 3.11 `delete` get_source_level — 单调用者

**文件**: `app/utils/logging.py:314-320`  
**问题**: 仅被同文件 `should_emit()` 调用。

```python
def get_source_level(self, source: str) -> str:
    """获取指定 source 的日志级别"""
    with self._source_levels_lock:
        return self._source_levels.get(source, self._config.get("level", "INFO"))
```

**操作**: 内联到 `should_emit`。**削减 ~7 行**。

---

## 4. 任务系统与 API 层

### 4.1 `delete` app/tasks/__init__.py 过度重导出

**文件**: `app/tasks/__init__.py` (62 行)  
**问题**: 重导出 20+ 名称，但外部仅导入 4 个: `TaskManager`, `TaskConfig`, `BrowserTaskRunner`, `is_valid_task_id`。

```python
__all__ = [
    "DEFAULT_STEP_TIMEOUT_MS",     # ← 外部无导入
    "DEFAULT_TASK_TIMEOUT_MS",     # ← 外部无导入
    "TASK_ID_PATTERN",             # ← 外部无导入
    "ClickHandler",                # ← 外部无导入
    "ClickSelectHandler",          # ← 外部无导入
    "EvalHandler",                 # ← 外部无导入
    # ... 11 个 handler 类全部未被外部导入
    "TaskValidator",               # ← 外部无导入
    "VariableResolver",            # ← 外部无导入
    "normalize_task_id",           # ← 外部无导入
    # 仅以下 4 个被外部导入:
    "BrowserTaskRunner",
    "TaskManager",
    "TaskConfig",
    "is_valid_task_id",
]
```

**操作**: 仅保留 4 个实际使用的重导出。**削减 ~50 行**。

---

### 4.2 `delete` TaskManager._safe_script_path — 从未调用

**文件**: `app/tasks/manager.py:149-151`

```python
def _safe_script_path(self, task_id: str) -> Path | None:
    """返回 scripts/ 下的 .py 路径。"""
    return self._safe_subdir_path(self.scripts_dir, task_id, ".py")
```

**操作**: 删除。**削减 3 行**。

---

### 4.3 `yagni` StepHandler ABC — 无运行时多态

**文件**: `app/tasks/step_handlers.py:57-74`  
**问题**: 10 个 handler 静态注册到字典，ABC 基类的 `ABCMeta` 开销无实际收益。

```python
class StepHandler(ABC):
    @property
    @abstractmethod
    def step_type(self) -> str:
        pass

    @abstractmethod
    async def execute(self, page, step, resolver) -> tuple[bool, str]:
        pass
```

**操作**: 改为普通基类，`step_type` 用类属性。**削减 ABC 导入 + 装饰器开销**。

---

### 4.4 `yagni` TaskManager._validate_id — 与其他 5 处重复

**文件**: `app/tasks/manager.py:90-95`  
**问题**: 包装 `normalize_task_id` + `is_valid_task_id`，但其他 5 处已直接调用这两个函数。

```python
def _validate_id(self, task_id: str) -> str | None:
    normalized = normalize_task_id(task_id)
    if not is_valid_task_id(normalized):
        return None
    return normalized
```

**操作**: 调用处直接使用模块级函数。**削减 ~7 行**。

---

### 4.5 `delete` set_autostart_mode — 与 enable_autostart 重复

**文件**: `app/api/autostart.py:78-91`  
**问题**: 与 `enable_autostart` 功能几乎相同，唯一区别是一个额外的 `if not status.get("enabled")` guard。

```python
@router.post("/api/autostart/mode", response_model=ApiResponse)
def set_autostart_mode(request, body, autostart_svc):
    _save_autostart_lightweight(request, body.lightweight)
    status = autostart_svc.status()
    if not status.get("enabled"):
        return ApiResponse(success=True, message="自启动未启用，模式已保存")
    ok, message = autostart_svc.enable(lightweight=body.lightweight)
    return ApiResponse(success=ok, message=message)
```

**操作**: 合并到 `enable_autostart`。**削减 ~15 行**。

---

### 4.6 `native` 7 个 404 guard 重复

**文件**: `app/api/tasks.py`, `app/api/scheduled_tasks.py`  
**问题**: 每个端点手动 `if not task: raise HTTPException(404)`，重复 7 次。

**操作**: 改为 FastAPI 依赖或服务层统一抛出。**削减 ~15 行**。

---

## 5. 核心基础设施

### 5.1 `delete` 两个死常量

**文件**: `app/constants.py:38-39`

```python
MONITOR_STOP_TIMEOUT = 10    # ← 从未导入或读取
PORTAL_WAIT_AFTER_LOGIN = 5  # ← 从未导入或读取
```

**操作**: 删除。**削减 2 行**。

---

### 5.2 `delete` self._is_lightweight — 设置但从未读取

**文件**: `app/container.py:29`

```python
def __init__(self, project_root: Path, mode: str = "full"):
    self.project_root = project_root
    self._temp_dir = project_root / "temp"
    self._is_lightweight = mode == "lightweight"  # ← 从未读取
```

**操作**: 删除。**削减 1 行**。

---

### 5.3 `shrink` _temp_dir 重复 constants.TEMP_DIR

**文件**: `app/container.py:28`  
**问题**: `project_root / "temp"` 与 `constants.TEMP_DIR` 计算相同路径。

```python
# container.py
self._temp_dir = project_root / "temp"  # ← 重复计算

# constants.py
TEMP_DIR = PROJECT_ROOT / "temp"
```

**操作**: 导入 `TEMP_DIR`。**削减 1 行**。

---

### 5.4 `yagni` _validate_auth_url — 单调用者

**文件**: `app/schemas.py:100-103`  
**问题**: 仅被 `Profile.validate_auth_url` field_validator 调用。

```python
def _validate_auth_url(v: str) -> str:
    v = v.strip()
    if v and not _URL_PATTERN.match(v):
        raise ValueError("认证地址必须以 http:// 或 https:// 开头")
    return v
```

**操作**: 内联到 field_validator。**削减 ~5 行**。

---

### 5.5 `shrink` _parse_targets / _parse_url_check — 近似函数

**文件**: `app/schemas.py:298-303`  
**问题**: 两个函数仅分隔符不同（逗号 vs 逗号+换行）。

```python
def _parse_targets(raw: str) -> list[str]:
    return [t.strip() for t in raw.split(",") if t.strip()]

def _parse_url_check(raw: str) -> list[str]:
    return [s.strip() for s in re.split(r'[,\n]', raw) if s.strip()]
```

**操作**: 统一为一个函数，使用 `re.split(r'[,\n]', raw)`。**削减 ~3 行**。

---

### 5.6 `stdlib` compare_versions — 手写 semver

**文件**: `app/version.py:25-41`  
**问题**: 仅被 `app/api/system.py` 一处调用。

```python
def compare_versions(a: str, b: str) -> int:
    try:
        va = [int(x) for x in a.split(".")]
        vb = [int(x) for x in b.split(".")]
        max_len = max(len(va), len(vb))
        va.extend([0] * (max_len - len(va)))
        vb.extend([0] * (max_len - len(vb)))
        for x, y in zip(va, vb, strict=False):
            if x > y: return 1
            if x < y: return -1
        return 0
    except (ValueError, AttributeError):
        return 0
```

**操作**: 用 `tuple(map(int, a.split(".")))` 比较，或导入 `packaging.version.Version`。**削减 ~15 行**。

---

## 6. 前端死代码与冗余

### 6.1 `delete` 5 个死函数 — ui.js

**文件**: `frontend/js/methods/ui.js`

```javascript
// 行 145-161 — 4 个函数从未被模板或方法调用
getBrowser(channel) {
    return this.availableBrowsers.find(b => b.channel === channel) || { channel, installed: false };
},
getBrowserIcon(channel) {
    const browser = this.availableBrowsers.find(b => b.channel === channel);
    return browser ? browser.icon : '';
},
isBrowserInstalled(channel) {
    const browser = this.availableBrowsers.find(b => b.channel === channel);
    return browser ? browser.installed : false;
},
getOtherBrowsers() {
    return this.availableBrowsers.filter(b => b.channel !== 'playwright');
},
```

**文件**: `frontend/js/methods/formatters.js:40-44`

```javascript
// 从未被模板或方法引用
formatFileSize(bytes) {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
},
```

**操作**: 删除 5 个函数。**削减 ~25 行**。

---

### 6.2 `delete` api-service.js 死方法

**文件**: `frontend/js/api-service.js:28-29`

```javascript
togglePureMode: () => api.post('/api/pure-mode').then(r => r.data),  // ← editor.js 直接调 axios
fetchPureMode: () => api.get('/api/pure-mode').then(r => r.data),    // ← editor.js 直接调 axios
```

**操作**: 删除两个方法。**削减 2 行**。

---

### 6.3 `yagni` api-service.js — 全部 .then(r => r.data)

**文件**: `frontend/js/api-service.js` (94 行)  
**问题**: 30+ 方法全是 `api.get(...).then(r => r.data)` 模式。

```javascript
// 每一行都是同一个模式
fetch: () => api.get('/api/config').then(r => r.data),
save: (payload, opts) => api.put('/api/config', payload, opts).then(r => r.data),
// ... 30+ 行
```

**操作**: 添加 axios 响应拦截器 `api.interceptors.response.use(r => r.data)`，然后删除整个文件。**削减 ~94 行**。

---

### 6.4 `delete` _validateConfig — 无效验证

**文件**: `frontend/js/methods/config.js:67-78`  
**问题**: 每次保存运行但仅 `return warnings`，调用方不检查返回值，不阻止保存。实质是 no-op。

```javascript
_validateConfig() {
    const warnings = [];
    const url = this.config.credentials.auth_url;
    if (url && !/^https?:\/\//.test(url)) {
        warnings.push('认证地址必须以 http:// 或 https:// 开头');
    }
    const port = this.config.app_settings.app_port;
    if (port && (port < 1 || port > 65535)) {
        warnings.push('端口范围必须在 1-65535 之间');
    }
    return warnings;  // ← 调用方不检查，不阻止保存
},
```

**操作**: 删除或改为实际阻止保存的验证。**削减 ~12 行**。

---

### 6.5 `delete` detectPerformance — 投机性优化

**文件**: `frontend/app.js:52-78`  
**问题**: 本地 localhost 应用的 FPS 检测。5 秒延迟后运行 2 秒 rAF 循环，若 < 30fps 则禁用毛玻璃。

```javascript
function detectPerformance() {
    let frameCount = 0;
    let lastTime = performance.now();
    const CHECK_DURATION = 2000;

    function measure() {
        frameCount++;
        const now = performance.now();
        const elapsed = now - lastTime;
        if (elapsed >= CHECK_DURATION) {
            const fps = Math.round((frameCount * 1000) / elapsed);
            if (fps < 30) {
                document.documentElement.classList.add('no-backdrop-filter');
            }
            return;
        }
        requestAnimationFrame(measure);
    }
    requestAnimationFrame(measure);
}
setTimeout(detectPerformance, 5000);
```

**操作**: 删除。用户可在设置中手动关闭毛玻璃。**削减 ~27 行**。

---

### 6.6 `yagni` 一行包装函数

**文件**: 分布在多个文件中

```javascript
// ui.js:59-61 — _showToast 的纯别名
toastOnly(success, message) { this._showToast(success, message); },

// appearance.js:7-10 — 实际持久化由 watcher 负责
saveAppearance() { this.toastOnly(true, '外观设置已保存'); },

// appearance.js:150-152 — 返回常量无转换
getBgColors() { return BG_COLORS; },

// appearance.js:252-254 — 返回常量无转换
getAccentColors() { return ACCENT_COLORS; },

// appearance.js:242-249 — 设置 bool 值
openBgLightbox() { this.bgLightbox.visible = true; },
closeBgLightbox() { this.bgLightbox.visible = false; },

// config.js:325-326 — 包装 _toggleAutostart(bool)
enableAutostart() { return this._toggleAutostart(true); },
disableAutostart() { return this._toggleAutostart(false); },

// config.js:276-277 — 包装 _toggleOcr(str)
installOcr() { return this._toggleOcr('install'); },
uninstallOcr() { return this._toggleOcr('uninstall'); },
```

**操作**: 模板直接调用底层方法。**削减 ~20 行**。

---

### 6.7 `yagni` 14 个 data/*.js 工厂文件

**文件**: `frontend/js/data/` 目录下 14 个文件  
**问题**: 每个文件 7-36 行，导出单个工厂函数返回纯对象字面量。

```javascript
// scripts.js — 典型示例，整个文件 7 行
export function scriptData() {
    return { scripts: [], availableBinaries: [] };
}

// timers.js — 整个文件 10 行
export function timerData() {
    return {
        timers: [], _dangerTimer: null, _repoDisclaimerTimer: null,
        _toastTimer: null, _toastLeavingTimer: null,
    };
}
```

**操作**: 合并为单个 `data.js`。**削减 ~100 行导入/导出开销**。

---

## 汇总统计

| 标签 | 发现数 | 预估可削减行数 |
|------|--------|----------------|
| `delete` | 32 | ~2,200 |
| `stdlib` | 7 | ~120 |
| `native` | 5 | ~200 |
| `yagni` | 25 | ~800 |
| `shrink` | 14 | ~300 |
| **合计** | **83** | **~3,600 行, ~5 个依赖可移除** |

---

## 建议执行优先级

| 优先级 | 范围 | 风险 | 预估削减 |
|--------|------|------|----------|
| **P0** | 测试瘦身 (1.1-1.9) | 最低 — 删除冗余测试不影响功能 | ~1,600 行 |
| **P1** | 删除死代码 (2.6-2.9, 3.1-3.3, 4.1-4.2, 5.1-5.2, 6.1-6.2) | 低 — 删除未调用的代码 | ~300 行 |
| **P2** | 服务层内联 (2.1-2.5) | 中 — 需要重构 engine.py | ~280 行 |
| **P3** | 前端清理 (6.3-6.7) | 中 — 需要更新模板引用 | ~300 行 |
| **P4** | 工具层瘦身 (3.4-3.11) | 低 — 内联/简化 | ~120 行 |
