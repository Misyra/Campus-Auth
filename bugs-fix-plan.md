# V2 配置架构重构方案

**目标**: 彻底解决配置链路中的重复注入、双配置对象、ISP 不一致、启动诊断失效等问题。
**原则**: 不保留兼容层，直接重构到位。

---

## 一、设计目标

```
持久化模型（Disk Model）
       ↓
运行时模型（Runtime Model）
       ↓
API DTO（View Model）
```

每层只做自己的事，禁止跨层复用。

---

## 二、新模型定义

### 1. Disk Model — `app/schemas.py`

#### GlobalConfig（替代原 RuntimeConfig 中的全局配置段）

```python
class GlobalConfig(BaseModel):
    """持久化配置 — 仅全局共享设置，不含凭据和 active_task。"""
    browser: BrowserSettings = Field(default_factory=BrowserSettings)
    monitor: MonitorSettings = Field(default_factory=MonitorSettings)
    retry: RetrySettings = Field(default_factory=RetrySettings)
    pause: PauseSettings = Field(default_factory=PauseSettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)

    # 透传字段
    block_proxy: bool = True
    shell_path: str = ""
    minimize_to_tray: bool = True
    startup_action: str = "none"
    autostart_lightweight: bool = True
    lightweight_tray: bool = True
    auto_open_browser: bool = False
    proxy: str = ""
    app_port: int = Field(default=50721, ge=1, le=65535)
```

禁止出现 `credentials`、`active_task`。

#### Profile（保持不变）

```python
class Profile(BaseModel):
    """认证方案 — 凭证 + 匹配规则。"""
    name: str = Field(default="默认方案")
    match_gateway_ip: str = ""
    match_ssid: str = ""
    username: str = ""
    password: str = ""          # ENC: 加密存储
    auth_url: str = ""
    carrier: str = "无"
    carrier_custom: str = ""
    active_task: str = ""
```

#### ProfilesData

```python
class ProfilesData(BaseModel):
    """settings.json 顶层结构（v4）"""
    config_version: int = Field(default=4)
    global_config: GlobalConfig = Field(default_factory=GlobalConfig)
    auto_switch: bool = Field(default=False)
    active_profile: str = Field(default="default")
    profiles: dict[str, Profile] = Field(default_factory=dict)
```

### 2. Runtime Model — `app/schemas.py`

```python
class RuntimeConfig(BaseModel, frozen=True):
    """运行时配置 — 仅存在于内存，不直接写盘。"""
    browser: BrowserSettings
    monitor: MonitorSettings
    retry: RetrySettings
    pause: PauseSettings
    logging: LoggingSettings

    credentials: LoginCredentials
    active_task: str

    # 透传字段
    block_proxy: bool = True
    shell_path: str = ""
    minimize_to_tray: bool = True
    startup_action: str = "none"
    autostart_lightweight: bool = True
    lightweight_tray: bool = True
    auto_open_browser: bool = False
    proxy: str = ""
    app_port: int = Field(default=50721, ge=1, le=65535)
```

### 3. API DTO — `app/schemas.py`

```python
class ConfigResponseDTO(BaseModel):
    """API 响应专用 — 不暴露内部结构。"""
    browser: BrowserSettings
    monitor: MonitorSettings
    retry: RetrySettings
    pause: PauseSettings
    logging: LoggingSettings

    # 凭据（密码已掩码）
    username: str = ""
    password: str = ""          # "••••••••" 或空
    auth_url: str = ""
    isp: str = ""
    carrier_custom: str = ""

    active_task: str = ""

    block_proxy: bool = True
    shell_path: str = ""
    minimize_to_tray: bool = True
    startup_action: str = "none"
    autostart_lightweight: bool = True
    lightweight_tray: bool = True
    auto_open_browser: bool = False
    proxy: str = ""
    app_port: int = 50721
```

---

## 三、唯一配置构建器 — `app/services/config_builder.py`（新建）

```python
class ConfigBuilder:
    """GlobalConfig + Profile → RuntimeConfig，全项目唯一的凭据注入点。"""

    @staticmethod
    def build(global_config: GlobalConfig, profile: Profile) -> RuntimeConfig:
        """构建运行时配置。ISP 转换、密码过滤只在此处发生。"""
        username = profile.username.strip()
        raw_password = profile.password.strip()
        password = raw_password if (raw_password and not raw_password.startswith("•")) else ""
        auth_url = profile.auth_url.strip()

        # ISP 转换 — 全项目唯一
        carrier = str(profile.carrier or "无").strip() or "无"
        custom_isp = str(profile.carrier_custom or "").strip()
        if carrier == "自定义":
            isp = custom_isp
        elif carrier == "无":
            isp = ""
        else:
            isp = carrier

        credentials = LoginCredentials(
            username=username,
            password=password,
            auth_url=auth_url,
            isp=isp,
            carrier_custom=custom_isp,
        )

        return RuntimeConfig(
            browser=global_config.browser,
            monitor=global_config.monitor,
            retry=global_config.retry,
            pause=global_config.pause,
            logging=global_config.logging,
            credentials=credentials,
            active_task=profile.active_task.strip(),
            block_proxy=global_config.block_proxy,
            shell_path=global_config.shell_path,
            minimize_to_tray=global_config.minimize_to_tray,
            startup_action=global_config.startup_action,
            autostart_lightweight=global_config.autostart_lightweight,
            lightweight_tray=global_config.lightweight_tray,
            auto_open_browser=global_config.auto_open_browser,
            proxy=global_config.proxy,
            app_port=global_config.app_port,
        )
```

---

## 四、ProfileService 重构 — `app/services/profile_service.py`

新增两个方法：

```python
def get_runtime_config(self) -> RuntimeConfig:
    """读磁盘 → 构建运行时配置。"""
    data = self.load()
    profile = self._get_active_profile(data)
    return ConfigBuilder.build(data.global_config, profile)

def build_runtime_config(self, data: ProfilesData) -> RuntimeConfig:
    """从已加载的 data 构建运行时配置（避免重复读盘）。"""
    profile = self._get_active_profile(data)
    return ConfigBuilder.build(data.global_config, profile)

def _get_active_profile(self, data: ProfilesData) -> Profile:
    profile = data.profiles.get(data.active_profile)
    if profile is None:
        profile = data.profiles.get("default", Profile())
    # 解密密码
    if profile.password:
        from app.utils.crypto import decrypt_password_field
        decrypted, err = decrypt_password_field(profile.password)
        if err:
            logger.warning("密码解密失败")
        profile = profile.model_copy(update={"password": decrypted or ""})
    return profile
```

---

## 五、Engine 重构 — `app/services/engine.py`

### 删除 `_ui_config`

```python
# 删除
self._ui_config: RuntimeConfig = RuntimeConfig()

# 保留
self._runtime_config: RuntimeConfig = RuntimeConfig()
```

### `_reload_config_internal` 简化

```python
def _reload_config_internal(self) -> bool:
    try:
        with self._reload_lock:
            data = self._profile_service.load()
            self._runtime_config = self._profile_service.build_runtime_config(data)
            self._runtime_snapshot = self._runtime_config
            with self._pure_mode_lock:
                self._pure_mode = data.global_config.browser.pure_mode
        return True
    except Exception:
        logger.exception("配置重载失败")
        return False
```

一次读盘，一次构建。无双重 load。

### `get_config` 改为返回运行时配置

```python
def get_config(self) -> RuntimeConfig:
    return self._runtime_config
```

### `_handle_login` / `run_manual_login`

```python
# 改读 _runtime_config
login_timeout = self._runtime_config.browser.login_timeout
```

---

## 六、API 重构 — `app/api/config.py`

### GET /api/config — 删除全部注入逻辑

```python
@router.get("/api/config", response_model=ConfigResponseDTO)
def get_config(
    svc: ScheduleEngine = Depends(get_monitor_service),
) -> ConfigResponseDTO:
    cfg = svc.get_config()
    return ConfigResponseDTO(
        browser=cfg.browser,
        monitor=cfg.monitor,
        retry=cfg.retry,
        pause=cfg.pause,
        logging=cfg.logging,
        username=cfg.credentials.username,
        password="••••••••" if cfg.credentials.password else "",
        auth_url=cfg.credentials.auth_url,
        isp=cfg.credentials.isp,
        carrier_custom=cfg.credentials.carrier_custom,
        active_task=cfg.active_task,
        block_proxy=cfg.block_proxy,
        shell_path=cfg.shell_path,
        minimize_to_tray=cfg.minimize_to_tray,
        startup_action=cfg.startup_action,
        autostart_lightweight=cfg.autostart_lightweight,
        lightweight_tray=cfg.lightweight_tray,
        auto_open_browser=cfg.auto_open_browser,
        proxy=cfg.proxy,
        app_port=cfg.app_port,
    )
```

不再知道 `Profile`、`carrier`、`carrier_custom`。

### PUT /api/config — 简化保存

```python
@router.put("/api/config", response_model=ActionResponse)
def save_config(
    payload: ConfigResponseDTO,
    profile_svc: ProfileService = Depends(get_profile_service),
    svc: ScheduleEngine = Depends(get_monitor_service),
):
    # 构建 GlobalConfig（剥离凭据）
    global_config = GlobalConfig(
        browser=payload.browser,
        monitor=payload.monitor,
        retry=payload.retry,
        pause=payload.pause,
        logging=payload.logging,
        block_proxy=payload.block_proxy,
        shell_path=payload.shell_path,
        minimize_to_tray=payload.minimize_to_tray,
        startup_action=payload.startup_action,
        autostart_lightweight=payload.autostart_lightweight,
        lightweight_tray=payload.lightweight_tray,
        auto_open_browser=payload.auto_open_browser,
        proxy=payload.proxy,
        app_port=payload.app_port,
    )

    # 构建 Profile（只更新凭据段）
    profile = Profile(
        username=payload.username,
        password=payload.password,
        auth_url=payload.auth_url,
        carrier="自定义" if payload.carrier_custom else ("无" if not payload.isp else payload.isp),
        carrier_custom=payload.carrier_custom,
        active_task=payload.active_task,
    )

    # 一次性保存
    result = save_global_and_profile(global_config, profile, profile_svc, svc.reload_config)
    return ActionResponse(success=result.success, message=result.message)
```

一次 PUT 完成全局配置 + 方案凭据的保存。前端不再需要 `_saveCredentialsToProfile`。

---

## 七、前端适配 — `frontend/js/methods/config.js`

### `fetchConfig` 适配 DTO

```js
// 响应从 RuntimeConfig 改为 ConfigResponseDTO
// 字段从 credentials.username 改为顶层 username
// 需要适配前端 config 对象结构，或在 fetch 时做映射
```

### `saveConfig` 简化

```js
async saveConfig() {
    // 不再需要 _saveCredentialsToProfile
    const payload = this.buildConfigDTO();  // 映射为 ConfigResponseDTO
    const { data } = await this.$api.put('/api/config', payload);
    if (data.success) {
        await this.fetchConfig(true);
        // 不再需要 fetchProfiles
    }
}
```

### 删除 `_saveCredentialsToProfile`

不再需要，一次 PUT 搞定。

---

## 八、migration — settings.json v3 → v4

```python
def migrate_v3_to_v4(data: dict) -> dict:
    """将 v3 的 config 字段重命名为 global_config，剥离 credentials/active_task。"""
    if data.get("config_version", 3) >= 4:
        return data
    old_config = data.get("config", {})
    # 剥离运行时字段
    old_config.pop("credentials", None)
    old_config.pop("active_task", None)
    data["global_config"] = old_config
    data.pop("config", None)
    data["config_version"] = 4
    return data
```

在 `ProfileService._load_unsafe` 中调用。

---

## 九、实施步骤

| 步骤 | 内容 | 验证 |
|------|------|------|
| 1 | `schemas.py`: 新增 `GlobalConfig`、`ConfigResponseDTO`，保留旧 `RuntimeConfig` | 模型可实例化 |
| 2 | `config_builder.py`: 新建，含 `ConfigBuilder.build` | 单元测试：carrier→isp 转换 |
| 3 | `profile_service.py`: 新增 `get_runtime_config` / `build_runtime_config` | 单元测试：完整构建 |
| 4 | `engine.py`: 删除 `_ui_config`，`_reload_config_internal` 改用 `build_runtime_config` | 引擎启动正常 |
| 5 | `api/config.py`: GET 改用 `ConfigResponseDTO`，删除注入逻辑 | API 返回正确 |
| 6 | `api/config.py`: PUT 改为一次保存 global + profile | 保存生效 |
| 7 | `application.py`: 启动诊断改读 `_runtime_config` | 日志显示凭据 |
| 8 | 前端适配：`fetchConfig` / `saveConfig` | UI 正常 |
| 9 | migration: v3 → v4 | 旧配置文件兼容 |
| 10 | 清理：删除 `load_active_config`、旧 `build_runtime_config`、`_saveCredentialsToProfile` | 无残留 |

---

## 十、可顺手修复的 BUG

| BUG | 修复方式 |
|-----|---------|
| BUG-01 proxy/app_port | `GlobalConfig` 包含这两个字段 |
| BUG-02 ISP 不一致 | ISP 转换只在 `ConfigBuilder.build` 一处 |
| BUG-03 启动诊断空凭据 | `get_config()` 返回 `_runtime_config` |
| ~~BUG-04~~ | 已排除（误报） |
| 双重磁盘读取 | `_reload_config_internal` 只读一次 |
| 配置流难理解 | 三层模型职责清晰 |

---

## 十一、约束检查

| 约束 | 状态 |
|------|------|
| not-to-do 第 56 条：禁止拆分 engine.py | ✅ 修改在 engine.py 内部 |
| not-to-do 第 33 条：禁止给 `_load_unsafe` 加缓存 | ✅ 不加缓存，传递 data 对象 |
| not-to-do 第 45 条：`save_config_combined` 原子性 | ✅ 一次 PUT 原子保存 |
