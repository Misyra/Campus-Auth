# Campus-Auth 问题审查报告（合并版）

**审查日期**: 2026-06-22
**来源**: `config-system-audit-2026-06-22.md`（配置系统全链路审查）+ `dev/architecture-review-2026-06-22.md`（架构审查）
**审查范围**: 后端核心（schemas / engine / config_service / profile_service / container / API）+ 前端（constants.js / config.js）

> 两份报告的问题已合并去重，同类问题只保留一条并标注来源。
>
> ✅ = 已通过 V2 配置架构重构修复（2026-06-23）

---

## 🔴 P0 — 用户数据丢失 / 配置静默失效

### ✅ BUG-01: `proxy` 和 `app_port` 前端有 UI，后端 Schema 不存在

**来源**: config #1 + architecture H2

**已修复**: V2 重构中 `GlobalConfig` 和 `RuntimeConfig` 均包含 `proxy: str` 和 `app_port: int` 字段，前端保存的值不再被 Pydantic 静默丢弃。

**相关代码**:

前端 `frontend/js/constants.js:153-154`：
```js
export const DEFAULT_CONFIG = {
  // ...
  proxy: "",
  app_port: 50721,
};
```

后端 `app/schemas.py:294-318` — `RuntimeConfig` 的字段定义中**没有** `proxy` 和 `app_port`：
```python
class RuntimeConfig(BaseModel, frozen=True):
    browser: BrowserSettings = Field(default_factory=BrowserSettings)
    credentials: LoginCredentials = Field(default_factory=LoginCredentials)
    monitor: MonitorSettings = Field(default_factory=MonitorSettings)
    # ... 无 proxy / app_port
```

`app/api/config.py:154-155` 的 FIELD_NAMES 为这两个字段定义了中文标签，但永远不会匹配到：
```python
FIELD_NAMES = {
    # ...
    "app_port": "网页端口",   # 死代码
    "proxy": "网络代理",       # 死代码
}
```

前端 `frontend/js/methods/config.js:79` 的 `saveConfig()` 把整个 `this.config` 发送到后端：
```js
const payload = { ...this.config };  // 包含 proxy 和 app_port
const { data } = await this.$api.put('/api/config', payload, { ... });
```

后端 Pydantic 反序列化时 `extra='ignore'`（默认），这两个字段被**静默丢弃**。

端口实际来自 `app/utils/ports.py:18-34` 的环境变量：
```python
def resolve_port() -> int:
    raw = os.getenv("APP_PORT", "").strip()
    # ... 仅从环境变量读取
    return _DEFAULT_PORT
```

**影响**: 用户在 UI 中填写的代理和端口**完全不生效**，每次保存后页面刷新恢复默认值，无任何错误提示。用户在 UI 上看到"端口可改"，改了不生效——典型的**配置幻觉**。

**修复建议**:
- **方案 A**（推荐）: 移除前端 `settings-system.html` 中代理和端口的输入控件，在 UI 上注明"端口通过 `APP_PORT` 环境变量配置"
- **方案 B**: 在 `RuntimeConfig` 添加 `proxy` 和 `app_port` 字段，接入 `resolve_port()` 和代理消费端

---

### ✅ BUG-02: `get_config()` API 返回的 ISP 与登录实际使用的不一致

**来源**: config #2 + architecture H3（部分）

**已修复**: V2 重构中 ISP 转换逻辑收敛到 `ConfigBuilder.build` 唯一入口，`GET /api/config` 直接从 `profile_svc.build_runtime_config(data)` 获取已转换的 ISP 值，不再有独立的注入逻辑。

**相关代码**:

`app/api/config.py:84` — GET `/api/config` 直接传递 `profile.carrier`：
```python
config = config.model_copy(update={
    "credentials": config.credentials.model_copy(update={
        # ...
        "isp": str(profile.carrier or "无"),  # ← 直接用原始 carrier 值
    }),
})
```

`app/services/config_service.py:66-73` — `build_runtime_config()` 对 carrier 做了语义转换：
```python
carrier = str(profile.carrier or "无").strip() or "无"
custom_isp = str(profile.carrier_custom or "").strip()
if carrier == "自定义":
    isp = custom_isp        # ← 实际使用自定义 ISP 名称
elif carrier == "无":
    isp = ""                # ← 实际使用空串
else:
    isp = carrier           # ← 直接传递
```

**影响**: 当运营商选择"自定义"时，GET API 返回 `isp="自定义"`（字面量），但 Worker 登录时用的 `RuntimeConfig.credentials.isp` 是用户填写的实际 ISP 名称。前端展示的 ISP 和 Worker 拿到的 ISP 不同，调试时会造成困惑。

**修复建议**: `api/config.py:get_config()` 中的 ISP 赋值逻辑改为与 `build_runtime_config()` 一致：
```python
carrier = str(profile.carrier or "无").strip() or "无"
custom_isp = str(profile.carrier_custom or "").strip()
if carrier == "自定义":
    isp = custom_isp
elif carrier == "无":
    isp = ""
else:
    isp = carrier
```

---

### ✅ BUG-03: 启动诊断永远显示空凭据

**来源**: config #9 + architecture review（启动日志）

**已修复**: V2 重构中 `_ui_config` 已删除，`engine.get_config()` 直接返回 `_runtime_config`（含凭据），启动诊断能正确显示用户名、密码状态、ISP。

**相关代码**:

`app/application.py:140-148`：
```python
cfg = services.monitor_service.get_config()
startup_logger.info(
    "当前配置: 用户={}, 密码={}, 认证={}, 运营商={}, 间隔={}min",
    f"'{cfg.credentials.username}'" if cfg.credentials.username else "(空)",
    "已设置" if cfg.credentials.password else "(空)",
    f"'{cfg.credentials.auth_url}'" if cfg.credentials.auth_url else "(空)",
    cfg.credentials.isp,
    cfg.monitor.check_interval_seconds // 60,
)
```

`app/services/engine.py:620-621` — `get_config()` 返回 `_ui_config`（空凭据）：
```python
def get_config(self) -> RuntimeConfig:
    return self._ui_config.model_copy(deep=True)
```

`app/services/config_service.py:97-103` — `_apply()` 保存时剥离凭据：
```python
def _apply(data: ProfilesData):
    data.config = config.model_copy(update={
        "credentials": LoginCredentials(),  # 空
        "active_task": "",                  # 空
    })
```

**影响**: 启动日志中 `用户=(空)`, `密码=(空)`, `认证=(空)`, `运营商=` 永远如此。无法帮助排查"凭据是否正确加载"的问题，**启动诊断完全无意义**。

**修复建议**: 启动诊断应读取 `_runtime_config`（含凭据注入的运行时配置），而非 `_ui_config`。或者直接从 `profile_service.get_active_profile()` 读取。

---

## 🟠 P1 — 功能缺陷 / 逻辑错误

### ~~BUG-04~~: 已排除（误报）+ 已修复

**来源**: architecture H3

**状态**: `Profile` 不含 `login_timeout` 字段，`_ui_config` 和 `_runtime_config` 的 `browser` 子配置来源相同，值无差异。此外 V2 重构已删除 `_ui_config`，`_handle_login` 改读 `_runtime_config`。

**相关代码**:

`app/services/engine.py:411`：
```python
def _handle_login(self, cmd: EngineCommand) -> None:
    # ... 提交登录用的是 self._runtime_config
    handle = self._orchestrator.submit(source="manual", config=self._runtime_config)
    # ...
    login_timeout = self._ui_config.browser.login_timeout  # ← 读的是全局默认配置
    worker_timeout = max(login_timeout, 60)
    try:
        ok, msg = handle.result(timeout=worker_timeout + 60)
```

`_ui_config` 来自 `data.config`（settings.json 的全局默认），`_runtime_config` 才包含 profile 的实际配置。如果用户在方案中自定义了 `login_timeout`，手动登录时**使用的是全局默认值而非方案值**。

**影响**: 当 profile 的 `login_timeout` 与全局默认不同时，手动登录的超时等待时间与预期不符。虽然当前 browser 子配置大多从全局继承，但这是一个**双真相源**的典型 bug。

**修复建议**: 改为 `self._runtime_config.browser.login_timeout`。

---

### ⚠️ BUG-05: `_handle_login` 阻塞引擎线程 120-660 秒（已缓解）

**来源**: config #6

**状态**: 已通过取消登录机制缓解。用户可在登录中点击"取消登录"按钮，`cancel_event` 使登录快速返回，引擎线程不再长时间阻塞。

**相关代码**:

`app/services/engine.py`（V2 重构后）：
```python
login_timeout = self._runtime_config.browser.login_timeout
worker_timeout = max(login_timeout, 60)
try:
    ok, msg = handle.result(timeout=worker_timeout + 60)  # 阻塞 120-660 秒
except TimeoutError:
    ok, msg = False, "登录超时"
```

在此期间引擎命令队列（`maxsize=50`）完全停滞，`_run_loop` 的 `while True` 循环被 `handle.result()` 阻塞。

**影响**:
- RELOAD 命令无法处理 → 配置重载延迟
- STOP 命令无法处理 → 用户点击"停止"无响应
- 网络检查无法执行 → 监控数据断档
- `reload_config()` 等待 10 秒超时 → 用户看到"配置重载失败"

**约束**: `not-to-do.md` 第 56 条禁止拆分 engine.py，修复必须在 engine.py 内部完成。

**修复建议**: 参考 `_do_async_login` 的非阻塞提交模式——提交登录后立即返回，通过回调或轮询获取结果，不阻塞引擎线程。

---

### ✅ BUG-06: `_handle_apply_profile` 忽略传入的 `profile_id`

**来源**: architecture H5

**已修复**: `_handle_apply_profile` 内部调用 `set_active_profile(profile_id)`，不再依赖调用方先 set。API 层删除冗余的 `set_active_profile` 调用。

**相关代码**:

`app/services/engine.py:436-445`：
```python
def _handle_apply_profile(self, cmd: EngineCommand) -> None:
    profile_id = cmd.data.get("profile_id", "")  # ← 只用于日志
    was_monitoring = self._is_monitoring

    if not self._reload_config_internal():  # ← 从 _profile_service.load() 重新读，不看 profile_id
        logger.error("配置重载失败，监控继续使用旧方案运行")
        cmd.response_data = (False, "方案切换失败")
        return
```

`_reload_config_internal()` 只读取当前 `active_profile`，完全无视 `profile_id` 参数。调用方必须**先调 `set_active_profile()` 再调 `apply_profile()`**，否则切错方案。

`app/api/profiles.py` 中确实都是先 set 后 apply，但这种"两个 API 必须成对调用"的设计是**脆弱的隐式契约**。

**影响**: 一旦有人单独调 `apply_profile()` 而不先 `set_active_profile()`，会静默切换到错误方案。

**修复建议**: `_handle_apply_profile` 内部应显式调用 `self._profile_service.set_active_profile(profile_id)`，让 `apply_profile` 自包含。

---

### ✅ BUG-07: `container.py` 违反封装的私有属性篡改

**来源**: architecture H1

**已修复**: 移除 `_login_pool`；`login_orchestrator` 改为必填参数；新增 `engine.set_orchestrator()` 和 `engine.set_task_executor()` 公共方法。

**相关代码**:

`app/container.py:77-87`：
```python
self.task_executor = TaskExecutor(
    registry=self.task_registry,
    history_store=self.task_history_store,
    worker_getter=_get_worker,
    # 注意: login_orchestrator 未在此传入
)

self.login_orchestrator = LoginOrchestrator(
    ..., pool=self.task_executor._login_pool,  # ← 读 TaskExecutor 私有字段
)
self.task_executor._login_orchestrator = self.login_orchestrator  # ❌ 写私有字段
self.engine._orchestrator = self.login_orchestrator               # ❌ 写私有字段
```

`TaskExecutor.__init__` 已有 `login_orchestrator` 可选参数（`app/services/task_executor.py:80`），但 container 没用它。

**影响**:
- **构造窗口期**: `task_executor` 和 `engine` 在构造完成到注入之间没有 orchestrator，若此时引擎启动调用 `execute_login_async` 会 NPE
- **测试难复现**: 单测中 `TaskExecutor(...)` 时 `_login_orchestrator` 是 `None`，行为与生产不同

**修复建议**: 将 `TaskExecutor.__init__` 的 `login_orchestrator` 参数改为必填，container 构造时直接传入。

---

### ✅ BUG-08: `FIELD_NAMES` 键名错误，变更日志显示原始字段名

**来源**: config #4

**已修复**: `browser.channel` → `browser.browser_channel`，`logging.backend_log_level` → `logging.level`，`logging.frontend_log_level` → `logging.frontend_level`。

**相关代码**:

`app/api/config.py:144`：
```python
FIELD_NAMES = {
    "browser.channel": "浏览器",           # ← 错误，应为 "browser.browser_channel"
    "logging.backend_log_level": "后端日志级别",  # ← 错误，应为 "logging.level"
    "logging.frontend_log_level": "前端日志级别",  # ← 错误，应为 "logging.frontend_level"
}
```

后端 `app/schemas.py` 中实际字段名：
```python
class BrowserSettings(BaseModel, frozen=True):
    browser_channel: str = "msedge"   # ← 不是 "channel"

class LoggingSettings(BaseModel, frozen=True):
    level: str = "INFO"              # ← 不是 "backend_log_level"
    frontend_level: str = "INFO"     # ← 不是 "frontend_log_level"
```

**影响**: 用户修改浏览器类型、后端日志级别、前端日志级别时，配置变更日志显示原始字段名（如 `browser.browser_channel`）而非中文友好名称。

**修复建议**: 修正为：
```python
"browser.browser_channel": "浏览器",
"logging.level": "后端日志级别",
"logging.frontend_level": "前端日志级别",
```

---

### ⚪️ BUG-09: `source_levels` 可能被主配置保存覆盖（可忽略）

**来源**: config #5

**可忽略**: 单用户场景下触发窗口极窄（<500ms），前端防抖+保存后刷新机制保证安全。

**相关代码**:

`source_levels` 通过独立的 `PUT /api/config/source-level` 端点写入，直接修改 `settings.json`。但主配置保存 `save_global_and_profile()` 的 `_apply` 会**整体替换** `data.global_config`：

`app/services/config_service.py`：
```python
def _apply(data: ProfilesData):
    data.global_config = global_config
    # source_levels 来自 payload，可能是旧快照
```

**竞态场景**:
1. 用户在日志面板设置某 source 的级别 → `_persist_source_levels` 写入磁盘 ✓
2. 用户在同一会话中修改其他设置 → 主配置保存
3. payload 的 `logging.source_levels` 来自 `fetchConfig()` 时的旧快照
4. 旧的 `source_levels` 覆盖刚才的修改

实际上窗口很窄（前端 `saveConfig()` 成功后会立即 `fetchConfig()` 刷新快照），但快速操作时仍可能触发。

**影响**: 用户自定义的日志 source 级别可能被意外恢复为旧值。

**修复建议**: `_apply` 中 merge 而非 replace `source_levels`——从当前磁盘数据保留 `source_levels`，而非用 payload 的值。

---

### ✅ BUG-10: `script_timeout` 缺失于前端 `DEFAULT_CONFIG`

**来源**: config #3

**已修复**: 在前端 `DEFAULT_CONFIG.monitor` 中添加 `script_timeout: 60`。

**相关代码**:

后端 `app/schemas.py:266`：
```python
class MonitorSettings(BaseModel, frozen=True):
    # ...
    script_timeout: int = Field(default=60, ge=1, le=600)
```

前端 `frontend/js/constants.js:103-121`：
```js
monitor: {
    check_interval_seconds: 300,
    network_check_timeout: 2,
    ping_targets: [...],
    enable_tcp_check: false,
    enable_http_check: false,
    enable_local_check: true,
    test_urls: [...],
    check_auth_url: false,
    auth_url_targets: [],
    url_check_urls: [...],
    // ← 缺少 script_timeout
},
```

前端 `fetchConfig()` 用 `{...DEFAULT_CONFIG.monitor, ...(data.monitor || {})}` 合并，API 返回值会补上。但 `resetConfig()` 调用 `structuredClone(DEFAULT_CONFIG)` 后，`script_timeout` 消失。

**影响**: 重置配置后，自定义的 `script_timeout` 被静默恢复为默认值 60。用户保存后发送的 payload 不含此字段，Pydantic 填默认值 60。

**修复建议**: 在前端 `DEFAULT_CONFIG.monitor` 中添加 `script_timeout: 60`。

---

### ✅ BUG-11: 配置验证仅在外部 API 路径执行

**来源**: config #8

**已修复**: 将验证逻辑移到 `_handle_start()` 内部，确保所有路径都经过验证。`start_monitoring()` 保留提前验证以立即返回错误信息。

**相关代码**:

`app/services/engine.py:687-688` — 仅 `start_monitoring()` 调用验证：
```python
def start_monitoring(self) -> tuple[bool, str]:
    valid, error = ConfigValidator.validate_env_config(self._runtime_config)
    if not valid:
        return False, f"配置无效: {error}"
```

以下路径**跳过验证**直接调用 `_handle_start()`：
- `_handle_reload()` (line 432) — 配置重载后重启监控
- `_do_network_check()` (line 267) — 自动切换方案后重启监控
- `_handle_apply_profile()` (line 457) — 手动切换方案后重启监控

**影响**: 如果重载后的配置无效（如所有网络检查被禁用、ping 目标格式错误），监控会以无效配置启动，可能导致误判网络状态。

**修复建议**: 提取验证为独立函数，在 `_handle_start()` 内部统一调用，或在各入口点增加验证。

---

## 🟡 P2 — 设计缺陷 / 一致性问题

### ✅ BUG-12: `DEFAULT_PROFILE_SETTINGS`（前端）包含大量后端已废弃的扁平字段

**已修复**: 前端 `constants.js` 中 `DEFAULT_PROFILE_SETTINGS` 已清理后端不持有的扁平字段（commit `ebcdafa`）。

---

### ✅ BUG-13: `BrowserChannel` 枚举是死代码

**来源**: config #14

**已修复**: `browser_channel` 字段类型从 `str` 改为 `BrowserChannel`，Pydantic 保存时自动校验。

**相关代码**:

`app/schemas.py:30-37`：
```python
class BrowserChannel(StrEnum):
    PLAYWRIGHT = "playwright"
    MSEdge = "msedge"
    CHROME = "chrome"
    FIREFOX = "firefox"
    CUSTOM = "custom"
```

`app/schemas.py:231`：
```python
class BrowserSettings(BaseModel, frozen=True):
    # ...
    browser_channel: str = "msedge"  # ← 类型是 str，不是 BrowserChannel
```

枚举定义了 5 个值，但 `browser_channel` 字段类型为 `str`，枚举未被任何字段引用。

**影响**: 零类型安全保障。无效的 `browser_channel` 值（如 `"invalid"`）在配置保存时不报错。

**修复建议**: 将 `browser_channel` 字段类型改为 `BrowserChannel`，或删除 `BrowserChannel` 枚举。

---

### BUG-14: `startup_action` 类型未约束为枚举

**来源**: config #12

**相关代码**:

`app/schemas.py:294-318` — `RuntimeConfig` 中：
```python
startup_action: str = "none"  # ← 类型是 str，不是 StartupAction
```

`app/schemas.py:15-20` — 枚举已定义：
```python
class StartupAction(StrEnum):
    NONE = "none"
    MONITOR = "monitor"
    LOGIN_ONCE = "login_once"
```

**影响**: 无效值如 `"bogus"` 只在 `AppConfig.from_runtime_config()` 转换时才失败，配置解析阶段不做校验。

**修复建议**: 将 `startup_action` 类型改为 `StartupAction`。

---

### BUG-15: `PauseSettings` 缺少跨字段验证

**来源**: config #13

**相关代码**:

`app/schemas.py:269-274`：
```python
class PauseSettings(BaseModel, frozen=True):
    enabled: bool = True
    start_hour: int = Field(default=0, ge=0, le=23)
    end_hour: int = Field(default=6, ge=0, le=23)
```

`start_hour` 和 `end_hour` 各自约束 `[0, 23]`，但没有交叉验证。

**影响**: `start_hour == end_hour` 的语义不明确（全天暂停？永不暂停？），`start_hour > end_hour` 需要明确的跨夜语义。用户可能配置出意外行为。

**修复建议**: 增加 `model_validator` 处理 `start_hour == end_hour` 和 `start_hour > end_hour` 的语义。

---

### ✅ BUG-16: `config_version` 不一致

**来源**: config #15 + architecture L3

**已修复**: V2 重构中 `ProfilesData.config_version` 默认值改为 4，v3→v4 迁移函数自动更新旧配置文件。`AppConfig.config_version` 仍为 2（独立于 ProfilesData），但两者不再语义混淆。

**相关代码**:

`app/schemas.py:65`：
```python
@dataclass
class AppConfig:
    config_version: int = 2  # ← 默认 2
```

`app/schemas.py:321`：
```python
class ProfilesData(BaseModel):
    config_version: int = Field(default=3)  # ← 默认 3
```

`AppConfig.config_version` 是死字段——全项目无读取点。

**影响**: 两个版本号语义混淆，新贡献者会困惑。

**修复建议**: 删除 `AppConfig.config_version`，或统一为同一个值。

---

### BUG-17: `Worker dict` 包含无关 UI 字段

**来源**: config #16

**相关代码**:

`app/services/login_orchestrator.py:57-59`：
```python
d["minimize_to_tray"] = config.minimize_to_tray
d["startup_action"] = config.startup_action
d["autostart_lightweight"] = config.autostart_lightweight
```

这些是应用层 UI 关注点，Playwright Worker 进程不需要它们。

**影响**: 不造成 bug，但增加了 IPC payload 噪音，且 Worker 依赖了不应关心的字段。

**修复建议**: 从 `_runtime_config_to_worker_dict` 中移除这三个字段。

---

### BUG-18: `Worker dict` 遗漏 `carrier_custom`

**来源**: config #7

**相关代码**:

`app/services/login_orchestrator.py:38-44`：
```python
d: dict = {
    "username": creds["username"],
    "password": creds["password"],
    "auth_url": creds["auth_url"],
    "isp": creds["isp"],
    # ← 缺少 carrier_custom
}
```

`LoginCredentials` 有 5 个字段，这里只提取了 4 个。

**影响**: 当前不造成 bug（`build_runtime_config` 已将 `carrier_custom` 赋给 `isp`），但破坏了字段完整性。如果 Worker 将来需要区分"原生 ISP"和"自定义 ISP"，这个字段就不可用了。

**修复建议**: 补充 `"carrier_custom": creds["carrier_custom"]`。

---

### ✅ BUG-19: `_reload_config_internal` 双重磁盘读取

**来源**: config #17

**已修复**: V2 重构中 `_reload_config_internal` 只调用一次 `profile_service.load()`，然后将 `data` 传递给 `profile_service.build_runtime_config(data)`，不再重复读盘。

**相关代码**:

`app/services/engine.py:629-631`：
```python
data = self._profile_service.load()          # ← 第一次读磁盘
self._ui_config = data.config
runtime_config, has_decrypt_error = load_active_config(self._profile_service)  # ← 第二次读磁盘
```

`load_active_config` 内部会再次调用 `profile_service.load()`。

**影响**: 性能微损（文件 <10KB），但逻辑上可以优化为单次读取后传递 data 对象。

**修复建议**: 让 `load_active_config` 接受已加载的 `data` 参数，避免重复读取。

---

### BUG-20: `monitor_service` 别名误导

**来源**: architecture M1

**相关代码**:

`app/container.py:96-98`：
```python
@property
def monitor_service(self) -> ScheduleEngine:
    return self.engine
```

`ScheduleEngine` 早已合并了 MonitorService + SchedulerService，但 `application.py:140`、`deps.py:20`、`api/scripts.py:90` 等处还在用 `services.monitor_service`。

**影响**: 命名滞后于架构演进，新贡献者会以为"monitor_service 只管监控"，导致关注点混淆。

**修复建议**: 全局替换为 `services.engine`，删除别名。

---

### ⚠️ BUG-21: `_handle_login` 阻塞期间 `reload_config` 超时导致命令积压（已缓解）

**来源**: config #6 的连锁影响

**状态**: 随 BUG-05 一并缓解。取消登录后引擎线程恢复处理队列命令。

**相关代码**:

`app/services/engine.py:654-657`：
```python
if not cmd.response_event.wait(timeout=10):
    return False, "配置重载超时，将在引擎空闲后生效"
```

当 `_handle_login` 阻塞引擎线程时，RELOAD 命令在队列中等待。API 调用方 10 秒超时后返回"配置重载超时"，但**命令仍在队列中**。当登录完成后，积压的 RELOAD 命令会被逐个执行，可能导致意外的多次重载。

**影响**: 用户看到"配置重载超时"以为失败，但稍后配置突然被重载，造成困惑。

**修复建议**: 与 BUG-05 一起修复——非阻塞登录后，引擎线程可以正常处理队列命令。

---

### ~~BUG-22~~: 已不存在

**来源**: config #10

**状态**: `DEFAULT_PROFILE_SETTINGS` 已清理，不再包含 monitor 字段。`DEFAULT_CONFIG.monitor` 中 `enable_tcp_check: false`、`enable_http_check: false` 与后端默认值一致。

**相关代码**:

前端 `frontend/js/constants.js:237-238` — `DEFAULT_PROFILE_SETTINGS`：
```js
enable_tcp_check: true,
enable_http_check: true,
```

后端 `app/schemas.py:253-254` — `MonitorSettings`：
```python
enable_tcp_check: bool = False
enable_http_check: bool = False
```

**影响**: 新建方案默认启用 TCP/HTTP 检测，但全局配置默认禁用。用户新建方案后如果不保存就直接运行，行为与预期不符。

**修复建议**: 统一前后端默认值。

---

### BUG-23: `LoggingSettings.level` 未做枚举校验

**来源**: config #18

**相关代码**:

`app/schemas.py` 中 `LoggingSettings.level` 类型为 `str`：
```python
class LoggingSettings(BaseModel, frozen=True):
    level: str = "INFO"
    frontend_level: str = "INFO"
```

**影响**: 无效的日志级别（如 `"VERBOSE"`）在配置保存时不报错，运行时被静默忽略或回退。

**修复建议**: 增加 `pattern` 约束或使用 `StrEnum` 限定有效值。

---

### BUG-24: `LoginOrchestrator` 与 `TaskExecutor` 共享线程池的生命周期耦合

**来源**: architecture M6

**相关代码**:

`app/container.py:77-82`：
```python
self.login_orchestrator = LoginOrchestrator(
    ..., pool=self.task_executor._login_pool,  # 借用 TaskExecutor 的线程池
)
```

`task_executor.shutdown()` 会 `self._login_pool.shutdown(wait=wait)`，同时 `login_orchestrator.shutdown(wait=wait)` 又会 `self._pool.shutdown(wait=wait)`——**同一个线程池被 shutdown 两次**。

**影响**: 第二次 shutdown 是 no-op 但仍走一遍路径。且 container 关闭顺序中 orchestrator 的 shutdown 没有被显式调用。

**修复建议**: 明确 orchestrator 的 `pool` 是"借用"还是"自有"，container.shutdown 里显式调 orchestrator.shutdown 或文档化生命周期归属。

---

### ✅ BUG-25: 前端 `user_agent` 写死 Chrome 125，后端默认为空

**来源**: architecture L6

**已修复**: 后端 `BrowserSettings.user_agent` 默认值改为空 Chrome 125 UA，与前端一致。

**相关代码**:

前端 `frontend/js/constants.js:87`：
```js
user_agent: "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
```

后端 `app/schemas.py` 中 `BrowserSettings.user_agent` 默认为空字符串（使用浏览器原生 UA）。

**影响**: 前端显示一个固定的 UA，但后端默认不覆盖浏览器 UA。如果用户从未修改过此设置，前端显示值与实际行为不一致。

**修复建议**: 前端默认值改为空字符串，与后端一致。

---

### ⚠️ BUG-26: 命令队列 `maxsize=50` 关键命令静默丢弃（已缓解）

**状态**: 随 BUG-05 一并缓解。取消登录后引擎线程恢复消费队列，不再积压。

**来源**: architecture L2

**相关代码**:

`app/services/engine.py:144`：
```python
self._cmd_queue: queue.Queue[EngineCommand] = queue.Queue(maxsize=50)
```

`_enqueue` 满了只 warning 跳过：
```python
def _enqueue(self, cmd: EngineCommand) -> bool:
    try:
        self._cmd_queue.put_nowait(cmd)
        return True
    except queue.Full:
        logger.warning("命令队列已满，丢弃命令: {}", cmd.type)
        return False
```

**影响**: 在高频广播场景可能静默丢弃关键命令（START/STOP/LOGIN/RELOAD/APPLY_PROFILE）。

**修复建议**: 对关键命令类型应 raise 而非静默丢弃，或增大队列容量并增加告警。

---

## 总览表

> ✅ = 已通过 V2 配置架构重构修复（2026-06-23）

| 编号 | 优先级 | 问题 | 位置 | 工作量 | 影响 | 状态 |
|------|--------|------|------|--------|------|------|
| BUG-01 | 🔴 P0 | proxy/app_port 幽灵字段 | constants.js:153, schemas.py | ~1h | 用户改端口/代理不生效 | ✅ 已修复 |
| BUG-02 | 🔴 P0 | ISP 映射不一致 | api/config.py:84 vs config_service.py:66 | ~15min | 前端显示与运行时不同 | ✅ 已修复 |
| BUG-03 | 🔴 P0 | 启动诊断永远显示空 | application.py:140, engine.py:620 | ~15min | 诊断信息无意义 | ✅ 已修复 |
| BUG-04 | 🟠 P1 | login_timeout 读错配置源 | engine.py:411 | ~5min | 超时值可能不对 | ✅ 误报+已修复 |
| BUG-05 | 🟠 P1 | _handle_login 阻塞引擎 | engine.py:411-416 | ~4h | 登录期间所有命令卡死 | ⚠️ 已缓解 |
| BUG-06 | 🟠 P1 | apply_profile 忽略 profile_id | engine.py:436-445 | ~30min | 隐式契约脆弱 | ✅ 已修复 |
| BUG-07 | 🟠 P1 | container 私有属性篡改 | container.py:77-87 | ~2h | 启动竞态窗口 | ✅ 已修复 |
| BUG-08 | 🟠 P1 | FIELD_NAMES 键名错误 | api/config.py:144 | ~5min | 变更日志显示错误名称 | ✅ 已修复 |
| BUG-09 | 🟠 P1 | source_levels 覆盖竞态 | config_service.py:97-103 | ~30min | 日志级别被意外重置 | ⚪️ 可忽略 |
| BUG-10 | 🟠 P1 | script_timeout 前端缺失 | constants.js:103-121 | ~5min | 重置后丢失自定义值 | ✅ 已修复 |
| BUG-11 | 🟠 P1 | 配置验证仅 API 路径执行 | engine.py:687 | ~30min | 无效配置可启动监控 | ✅ 已修复 |
| BUG-12 | 🟡 P2 | Profile 废弃字段 | constants.js:206-242 | ~2h | 用户改无效字段无提示 | ✅ 已修复 |
| BUG-13 | 🟡 P2 | BrowserChannel 枚举死代码 | schemas.py:30-37 | ~10min | 无类型安全 | ✅ 已修复 |
| BUG-14 | 🟡 P2 | startup_action 未约束 | schemas.py | ~5min | 无效值不报错 | ❌ 未修复 |
| BUG-15 | 🟡 P2 | PauseSettings 无交叉验证 | schemas.py:269-274 | ~15min | start==end 语义不明 | ❌ 未修复 |
| BUG-16 | 🟡 P2 | config_version 不一致 | schemas.py:65, 321 | ~5min | 死字段造成困惑 | ✅ 已修复 |
| BUG-17 | 🟡 P2 | Worker dict 含 UI 字段 | login_orchestrator.py:57-59 | ~5min | IPC payload 噪音 | ❌ 未修复 |
| BUG-18 | 🟡 P2 | Worker dict 缺 carrier_custom | login_orchestrator.py:38-44 | ~5min | 字段完整性缺失 | ❌ 未修复 |
| BUG-19 | 🟡 P2 | 双重磁盘读取 | engine.py:629-631 | ~15min | 性能微损 | ✅ 已修复 |
| BUG-20 | 🟡 P2 | monitor_service 别名 | container.py:96 | ~1h | 命名误导 | ❌ 未修复 |
| BUG-21 | 🟠 P1 | 超时后命令积压 | engine.py:654-657 | 随 BUG-05 | 意外多次重载 | ⚠️ 已缓解 |
| ~~BUG-22~~ | 🟡 P2 | ~~TCP/HTTP 默认值前后不一致~~ | — | — | 已不存在 | ✅ 已清理 |
| BUG-23 | 🟡 P2 | LoggingSettings.level 无校验 | schemas.py | ~10min | 无效级别静默忽略 | ❌ 未修复 |
| BUG-24 | 🟡 P2 | 线程池生命周期耦合 | container.py:77-82 | ~30min | 双重 shutdown | ❌ 未修复 |
| BUG-25 | 🟡 P2 | user_agent 默认值不一致 | constants.js:87 | ~5min | 前端显示与实际不符 | ✅ 已修复 |
| BUG-26 | 🟡 P2 | 关键命令静默丢弃 | engine.py:144 | ~30min | 高频场景丢命令 | ⚠️ 已缓解 |

---

## 修复进度

**已修复 16 个问题**:
- ✅ BUG-01: proxy/app_port 幽灵字段
- ✅ BUG-02: ISP 映射不一致
- ✅ BUG-03: 启动诊断永远显示空
- ✅ BUG-04: login_timeout 读错配置源（误报+已修复）
- ✅ BUG-06: apply_profile 忽略 profile_id
- ✅ BUG-07: container 私有属性篡改
- ✅ BUG-08: FIELD_NAMES 键名错误
- ✅ BUG-10: script_timeout 前端缺失
- ✅ BUG-11: 配置验证仅 API 路径执行
- ✅ BUG-12: Profile 废弃字段
- ✅ BUG-13: BrowserChannel 枚举死代码
- ✅ BUG-16: config_version 不一致
- ✅ BUG-19: 双重磁盘读取
- ✅ BUG-22: TCP/HTTP 默认值不一致（已清理）
- ✅ BUG-25: user_agent 默认值不一致

**已缓解 3 个问题**（取消登录机制）:
- ⚠️ BUG-05: _handle_login 阻塞引擎（用户可取消）
- ⚠️ BUG-21: 超时后命令积压（随 BUG-05 缓解）
- ⚠️ BUG-26: 关键命令静默丢弃（随 BUG-05 缓解）

**剩余 7 个问题待修复**（按优先级）:
- P2: BUG-14/15/17/18/20/23/24

**第二批（P1）**: ✅ 已全部修复

**第三批（P2，设计改进）**:
2. BUG-14/15: schemas 类型约束
3. BUG-17/18: Worker dict 清理
4. BUG-20: monitor_service 别名
5. BUG-23/24: 一致性修复
