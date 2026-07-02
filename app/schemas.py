from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator, model_validator

from app.constants import DEFAULT_HTTP_TARGETS, DEFAULT_NETWORK_TARGETS, DEFAULT_URL_CHECK_URLS, URL_PATTERN, VALID_LOG_LEVELS


class StartupAction(StrEnum):
    """启动后执行什么动作"""

    NONE = "none"
    MONITOR = "monitor"
    LOGIN_ONCE = "login_once"


class RuntimeMode(StrEnum):
    """运行模式"""

    FULL = "full"
    LIGHTWEIGHT = "lightweight"


class BrowserChannel(StrEnum):
    """浏览器类型"""

    PLAYWRIGHT = "playwright"
    MSEdge = "msedge"
    CHROME = "chrome"
    FIREFOX = "firefox"
    CUSTOM = "custom"


class LaunchSource(StrEnum):
    """程序是怎么被启动的（仅用于日志和 UI 体验，不参与业务逻辑）"""

    MANUAL = "manual"
    AUTOSTART = "autostart"


class StartupResult(StrEnum):
    """启动动作执行结果"""

    CONTINUE = "continue"
    EXIT = "exit"


class LoginResult(StrEnum):
    """LOGIN_ONCE 登录结果分类"""

    SUCCESS = "success"  # 登录成功，退出进程
    CONFIG_ERROR = "config_error"  # 配置错误，退出进程
    TEMPORARY_FAILURE = "temporary_failure"  # 临时失败，继续监控


@dataclass
class AppConfig:
    startup_action: StartupAction = StartupAction.NONE
    runtime_mode: RuntimeMode = RuntimeMode.FULL  # CLI --runtime-mode 覆盖
    minimize_to_tray: bool = True
    lightweight_tray: bool = True
    auto_open_browser: bool = False

    @classmethod
    def from_runtime_config(cls, config: RuntimeConfig) -> AppConfig:
        """从 RuntimeConfig 统一派生 AppConfig，消除手动同步风险。"""
        return cls(
            startup_action=StartupAction(config.app_settings.startup_action),
            minimize_to_tray=config.app_settings.minimize_to_tray,
            lightweight_tray=config.app_settings.lightweight_tray,
            auto_open_browser=config.app_settings.auto_open_browser,
        )


@dataclass
class LaunchContext:
    source: LaunchSource = LaunchSource.MANUAL


@dataclass
class ApplicationContext:
    config: AppConfig
    launch: LaunchContext


@dataclass
class RuntimeFeatures:
    web_enabled: bool
    browser_enabled: bool
    tray_enabled: bool


def _validate_auth_url(v: str) -> str:
    v = v.strip()
    if v and not URL_PATTERN.match(v):
        raise ValueError("认证地址必须以 http:// 或 https:// 开头")
    return v


# ── 浏览器参数默认值（单一来源） ──
_BROWSER_ARGS_DEFAULT = (
    "--disable-blink-features=AutomationControlled\n"
    "--disable-software-rasterizer\n"
    "--disable-extensions\n"
    "--disable-background-timer-throttling\n"
    "--disable-backgrounding-occluded-windows\n"
    "--disable-renderer-backgrounding\n"
    "--disable-features=TranslateUI,BlinkGenPropertyTrees\n"
    "--disable-ipc-flooding-protection\n"
    "--disable-hang-monitor\n"
    "--disable-popup-blocking"
)





# ── GET 端点响应模型 ──


class ProfileSummary(BaseModel):
    """方案列表中的单个方案摘要。"""
    name: str = ""
    match_gateway_ip: str = ""
    match_ssid: str = ""
    carrier: str = "无"
    carrier_custom: str = ""
    auth_url: str = ""
    active_task: str = ""


class ProfileListResponse(BaseModel):
    """GET /api/profiles 响应。"""
    profiles: dict[str, ProfileSummary] = Field(default_factory=dict)
    active_profile: str = "default"
    auto_switch: bool = False


class ProfileDetailResponse(BaseModel):
    """GET /api/profiles/{id} 响应。"""
    profile_id: str
    settings: Profile


class BrowserInfo(BaseModel):
    """浏览器信息。"""
    channel: str
    name: str
    icon: str = ""
    installed: bool = False
    needs_download: bool = False
    description: str = ""


class BrowserListResponse(BaseModel):
    """GET /api/browsers 响应。"""
    browsers: list[BrowserInfo] = Field(default_factory=list)
    current: str = "playwright"


class TaskSummary(BaseModel):
    """任务列表中的单个任务。"""
    id: str = ""
    name: str = ""
    description: str = ""
    type: str = ""
    binary_path: str = ""


class LogLevelResponse(BaseModel):
    level: str = "INFO"


class MonitorStatusResponse(BaseModel):
    monitoring: bool
    network_check_count: int
    login_attempt_count: int
    last_check_time: str | None
    runtime_seconds: int
    network_connected: bool = False
    status_detail: str = "正常"
    network_state: str = "unknown"


class LogEntry(BaseModel):
    timestamp: str
    level: str = "INFO"
    source: str = "backend"
    name: str = ""
    message: str

    @field_validator("level")
    @classmethod
    def validate_level(cls, v: str) -> str:
        v = v.upper().strip()
        return v if v in VALID_LOG_LEVELS else "INFO"


class AutoStartStatusResponse(BaseModel):
    platform: str
    enabled: bool
    method: str
    location: str
    lightweight: bool = True


class Profile(BaseModel):
    """认证方案 — 凭证 + 匹配规则。

    每个方案独立持有自己的凭证，不存在"留空回退到全局"语义。
    替代 AuthProfile，用于新的 ProfilesData 结构。
    """
    name: str = Field(default="默认方案")
    match_gateway_ip: str = ""
    match_ssid: str = ""
    username: str = ""
    password: str = ""          # ENC: 加密存储
    auth_url: str = ""
    carrier: str = "无"
    carrier_custom: str = ""
    active_task: str = ""

    @field_validator("auth_url")
    @classmethod
    def validate_auth_url(cls, v: str) -> str:
        return _validate_auth_url(v)


def get_runtime_features(
    mode: RuntimeMode | str, minimize_to_tray: bool, auto_open_browser: bool,
    lightweight_tray: bool = True
) -> RuntimeFeatures:
    """根据运行模式派生特性标志"""
    if mode == RuntimeMode.LIGHTWEIGHT:
        return RuntimeFeatures(
            web_enabled=False,
            browser_enabled=False,
            tray_enabled=lightweight_tray,
        )
    return RuntimeFeatures(
        web_enabled=True,
        browser_enabled=auto_open_browser,
        tray_enabled=minimize_to_tray,
    )


# ── 类型化配置子集模型 ──


class BrowserSettings(BaseModel, frozen=True):
    """浏览器运行参数 — PlaywrightWorker / LoginAttemptHandler 消费。

    字段名与旧 dict 键名保持兼容，最小化消费端迁移量。
    """

    headless: bool = True
    timeout: int = Field(default=8, ge=1, le=60)
    navigation_timeout: int = Field(default=8, ge=3, le=60)
    login_timeout: int = Field(default=90, ge=10, le=600)
    user_agent: str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    low_resource_mode: bool = False
    disable_web_security: bool = False
    extra_headers_json: str = ""
    browser_args: str = _BROWSER_ARGS_DEFAULT
    stealth_mode: bool = False
    stealth_custom_script: str = ""
    locale: str = "zh-CN"
    timezone_id: str = "Asia/Shanghai"
    viewport_width: int = Field(default=1280, ge=320, le=3840)
    viewport_height: int = Field(default=720, ge=240, le=2160)
    pure_mode: bool = True
    browser_channel: BrowserChannel = BrowserChannel.MSEdge
    browser_custom_path: str = ""
    custom_browser_engine: str = "auto"


class LoginCredentials(BaseModel, frozen=True):
    """登录凭证 — LoginAttemptHandler / LoginOrchestrator 消费。"""

    username: str = ""
    password: str = ""
    auth_url: str = ""
    isp: str = ""
    carrier_custom: str = ""


def _parse_targets(raw: str) -> list[str]:
    return [s.strip() for s in re.split(r'[,\n]', raw) if s.strip()]


class MonitorSettings(BaseModel, frozen=True):
    """网络监控参数 — NetworkMonitorCore 消费。"""

    check_interval_seconds: int = Field(default=300, ge=10, le=86400)
    network_check_timeout: int = Field(default=2, ge=1, le=30)
    ping_targets: list[str] = Field(default_factory=lambda: _parse_targets(DEFAULT_NETWORK_TARGETS))
    enable_tcp_check: bool = False
    enable_http_check: bool = False
    enable_local_check: bool = True
    test_urls: list[str] = Field(default_factory=lambda: _parse_targets(DEFAULT_HTTP_TARGETS))
    check_auth_url: bool = False
    auth_url_targets: list[str] = Field(default_factory=list)
    url_check_urls: list[str] = Field(default_factory=lambda: _parse_targets(DEFAULT_URL_CHECK_URLS))
    script_timeout: int = Field(default=60, ge=5, le=600)


class PauseSettings(BaseModel, frozen=True):
    """暂停时段配置 — check_pause() 消费。

    start_hour == end_hour 语义为全天暂停（见 is_in_pause_period）。
    start_hour > end_hour 语义为跨天（如 23:00-06:00）。
    """

    enabled: bool = True
    start_hour: int = Field(default=0, ge=0, le=23)
    end_hour: int = Field(default=6, ge=0, le=23)


class LoggingSettings(BaseModel, frozen=True):
    level: str = Field(default="INFO", pattern=r"^(DEBUG|INFO|WARNING|ERROR)$")
    log_retention_days: int = Field(default=7, ge=1, le=365)
    access_log: bool = False


class RetrySettings(BaseModel, frozen=True):
    """重试策略 — LoginOrchestrator 消费。"""

    max_retries: int = Field(default=3, ge=0, le=10)
    retry_interval: int = Field(default=5, ge=1, le=300)


class AppSettings(BaseModel, frozen=True):
    """应用级设置 — 全局共享，不含凭据。

    被 GlobalConfig、RuntimeConfig 组合复用。
    """

    block_proxy: bool = True
    shell_path: str = ""
    minimize_to_tray: bool = True
    startup_action: StartupAction = StartupAction.NONE
    autostart_lightweight: bool = True
    lightweight_tray: bool = True
    auto_open_browser: bool = False
    proxy: str = ""
    app_port: int = Field(default=50721, ge=1, le=65535)
    custom_variables: dict[str, str] = Field(default_factory=dict)


# ── API 请求/响应模型 ──


class ApiResponse(BaseModel):
    """所有写操作的标准响应信封。

    success=True 表示业务成功；success=False 表示业务失败（HTTP 200）。
    data 可选，用于附加返回数据。
    """
    success: bool
    message: str = ""
    data: dict | None = None



class ConfigSaveRequest(BaseModel):
    """PUT /api/config 请求体 — 嵌套结构，与 RuntimeConfig 对齐。"""
    browser: BrowserSettings = Field(default_factory=BrowserSettings)
    monitor: MonitorSettings = Field(default_factory=MonitorSettings)
    retry: RetrySettings = Field(default_factory=RetrySettings)
    pause: PauseSettings = Field(default_factory=PauseSettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)
    app_settings: AppSettings = Field(default_factory=AppSettings)
    # 凭据（平铺）
    username: str = ""
    password: str = ""
    auth_url: str = ""
    isp: str = ""
    carrier_custom: str = ""
    active_task: str = ""


class ConfigPatchRequest(BaseModel):
    """PATCH /api/config 请求体 — 仅包含变更字段。

    所有字段均为 Optional，未传的字段不修改。
    """
    browser: BrowserSettings | None = None
    monitor: MonitorSettings | None = None
    retry: RetrySettings | None = None
    pause: PauseSettings | None = None
    logging: LoggingSettings | None = None
    app_settings: AppSettings | None = None
    # 凭据字段：None 表示不修改
    username: str | None = None
    password: str | None = None
    auth_url: str | None = None
    isp: str | None = None
    carrier_custom: str | None = None
    active_task: str | None = None


class LogLevelRequest(BaseModel):
    level: str = Field(min_length=1, description="日志级别（DEBUG/INFO/WARNING/ERROR）")


class AutoSwitchRequest(BaseModel):
    """POST /api/profiles/auto-switch 请求体。"""
    enabled: bool = True


class UninstallRequest(BaseModel):
    """POST /api/uninstall 请求体。"""
    keys: list[str] = Field(default_factory=list)


class FetchUrlRequest(BaseModel):
    """POST /api/background/fetch-url 请求体。"""
    url: str = Field(min_length=1, description="图片 URL")


class InitStatusResponse(BaseModel):
    """GET /api/init-status 响应。"""
    initialized: bool
    agreed: bool
    password_decryption_failed: bool = False


class HealthResponse(BaseModel):
    """GET /api/health 响应。"""
    status: str = "ok"
    version: str = ""
    python_version: str = ""
    memory: dict = Field(default_factory=dict)
    process: dict = Field(default_factory=dict)


class ShellListResponse(BaseModel):
    """GET /api/shells 响应。"""
    shells: list[str] = Field(default_factory=list)
    default: str = ""


class DebugSessionResponse(BaseModel):
    """调试会话状态响应（start/next/run-all/stop 共用）。"""
    running: bool = False
    task_id: str | None = None
    current_step: int = 0
    total_steps: int = 0
    steps: list = Field(default_factory=list)
    results: list = Field(default_factory=list)
    screenshot_url: str | None = None
    message: str = ""


class AutostartEnableRequest(BaseModel):
    """POST /api/autostart/enable|mode 请求体。"""
    lightweight: bool = True


class TaskOrderRequest(BaseModel):
    """POST /api/tasks/order 请求体。"""
    order: list[str] = Field(default_factory=list, description="任务 ID 有序列表")


class PureModeResponse(BaseModel):
    """GET/POST /api/pure-mode 响应。"""
    enabled: bool


class StealthScriptResponse(BaseModel):
    """GET /api/config/default-stealth-script 响应。"""
    script: str = ""


class NetworkDetectResponse(BaseModel):
    """POST /api/profiles/detect 响应。"""
    gateway_ip: str | None = None
    ssid: str | None = None
    matched_profile_id: str | None = None
    matched_profile_name: str | None = None


class BinaryInfo(BaseModel):
    """可执行二进制信息。"""
    path: str = ""
    name: str = ""


class OcrStatusResponse(BaseModel):
    """GET /api/ocr/status 响应。"""
    installed: bool = False
    size_mb: float = 0.0


class UpdateCheckResponse(BaseModel):
    """GET /api/check-update 响应。"""
    current: str = ""
    latest: str | None = None
    has_update: bool = False
    url: str = ""
    body: str = ""
    published_at: str = ""
    cached: bool = False
    error: str | None = None


class UninstallItem(BaseModel):
    """可清理项目。"""
    key: str
    label: str
    exists: bool = False
    path: str = ""
    size_mb: float = 0.0


class RuntimeConfig(BaseModel, frozen=True):
    """运行时配置根模型 — 替代旧 dict[str, Any]。

    组合所有子集模型。
    frozen=True 保证线程安全，无需 deepcopy。

    注意：此模型仅存在于内存，不直接写盘。
    """

    browser: BrowserSettings = Field(default_factory=BrowserSettings)
    credentials: LoginCredentials = Field(default_factory=LoginCredentials)
    monitor: MonitorSettings = Field(default_factory=MonitorSettings)
    pause: PauseSettings = Field(default_factory=PauseSettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)
    retry: RetrySettings = Field(default_factory=RetrySettings)
    app_settings: AppSettings = Field(default_factory=AppSettings)

    active_task: str = ""


class GlobalConfig(BaseModel):
    """持久化配置 — 仅全局共享设置，不含凭据和 active_task。"""

    browser: BrowserSettings = Field(default_factory=BrowserSettings)
    monitor: MonitorSettings = Field(default_factory=MonitorSettings)
    retry: RetrySettings = Field(default_factory=RetrySettings)
    pause: PauseSettings = Field(default_factory=PauseSettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)
    app_settings: AppSettings = Field(default_factory=AppSettings)


class ProfilesData(BaseModel):
    """settings.json 顶层结构（v5）"""

    config_version: int = Field(default=5)
    global_config: GlobalConfig = Field(default_factory=GlobalConfig)
    auto_switch: bool = Field(default=False, description="是否根据网关 IP 自动切换方案")
    active_profile: str = Field(default="default")
    profiles: dict[str, Profile] = Field(default_factory=dict)

    @model_validator(mode="after")
    def ensure_default_profile(self) -> ProfilesData:
        """确保 default profile 存在"""
        if "default" not in self.profiles:
            self.profiles["default"] = Profile()
        return self


class ScheduleTime(BaseModel):
    """定时任务执行时间。"""

    hour: int = Field(ge=0, le=23)
    minute: int = Field(ge=0, le=59)


class ScheduledTaskConfig(BaseModel):
    """定时任务配置 — 替代 scheduled_tasks.py 中的手写校验。"""

    name: str = Field(min_length=1, description="任务名称")
    description: str = ""
    type: str = Field(pattern=r"^(script|browser|shell)$", description="任务类型")
    target_id: str = ""
    command: str = ""
    shell_path: str = ""
    enabled: bool = True
    schedule: ScheduleTime
    timeout: int = Field(default=60, ge=5, le=3600)

    @model_validator(mode="after")
    def validate_type_fields(self) -> "ScheduledTaskConfig":
        if self.type == "shell" and not self.command:
            raise ValueError("Shell 命令不能为空")
        if self.type in ("script", "browser") and not self.target_id:
            raise ValueError("请选择目标任务")
        return self


