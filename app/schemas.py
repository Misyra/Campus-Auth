from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator, model_validator

from app.utils.logging import VALID_LOG_LEVELS

_URL_PATTERN = re.compile(r"^https?://")


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
    UNKNOWN = "unknown"


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
    config_version: int = 2
    startup_action: StartupAction = StartupAction.NONE
    runtime_mode: RuntimeMode = RuntimeMode.FULL  # CLI --runtime-mode 覆盖
    minimize_to_tray: bool = True
    lightweight_tray: bool = True
    auto_open_browser: bool = False

    @classmethod
    def from_runtime_config(cls, config: RuntimeConfig) -> AppConfig:
        """从 RuntimeConfig 统一派生 AppConfig，消除手动同步风险。"""
        return cls(
            startup_action=StartupAction(config.startup_action),
            minimize_to_tray=config.minimize_to_tray,
            lightweight_tray=config.lightweight_tray,
            auto_open_browser=config.auto_open_browser,
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
    if v and not _URL_PATTERN.match(v):
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



class ActionResponse(BaseModel):
    success: bool
    message: str


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


# 向后兼容别名
AuthProfile = Profile


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
    navigation_timeout: int = Field(default=15, ge=3, le=60)
    login_timeout: int = Field(default=90, ge=10, le=600)
    user_agent: str = ""
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
    browser_channel: str = "playwright"
    browser_custom_path: str = ""
    custom_browser_engine: str = "auto"


class LoginCredentials(BaseModel, frozen=True):
    """登录凭证 — LoginAttemptHandler / LoginOrchestrator 消费。"""

    username: str = ""
    password: str = ""
    auth_url: str = ""
    isp: str = ""
    carrier_custom: str = ""


class MonitorSettings(BaseModel, frozen=True):
    """网络监控参数 — NetworkMonitorCore 消费。"""

    check_interval_seconds: int = Field(default=300, ge=10, le=86400)
    network_check_timeout: int = Field(default=2, ge=1, le=30)
    ping_targets: list[str] = Field(default_factory=list)
    enable_tcp_check: bool = False
    enable_http_check: bool = False
    enable_local_check: bool = True
    test_urls: list[str] = Field(default_factory=list)
    check_auth_url: bool = False
    auth_url_targets: list[str] = Field(default_factory=list)
    url_check_urls: list[dict] = Field(default_factory=list)
    script_timeout: int = Field(default=60, ge=5, le=600)


class PauseSettings(BaseModel, frozen=True):
    """暂停时段配置 — check_pause() 消费。"""

    enabled: bool = True
    start_hour: int = Field(default=0, ge=0, le=23)
    end_hour: int = Field(default=6, ge=0, le=23)


class LoggingSettings(BaseModel, frozen=True):
    """日志配置 — 日志初始化模块消费。"""

    level: str = "INFO"
    frontend_level: str = "INFO"
    log_retention_days: int = Field(default=7, ge=1, le=365)
    access_log: bool = False
    source_levels: dict[str, str] = Field(default_factory=dict)


class RetrySettings(BaseModel, frozen=True):
    """重试策略 — LoginOrchestrator 消费。"""

    max_retries: int = Field(default=3, ge=0, le=10)
    retry_interval: int = Field(default=5, ge=1, le=300)


class RuntimeConfig(BaseModel, frozen=True):
    """运行时配置根模型 — 替代旧 dict[str, Any]。

    组合所有子集模型 + 直接透传字段。
    frozen=True 保证线程安全，无需 deepcopy。
    """

    browser: BrowserSettings = Field(default_factory=BrowserSettings)
    credentials: LoginCredentials = Field(default_factory=LoginCredentials)
    monitor: MonitorSettings = Field(default_factory=MonitorSettings)
    pause: PauseSettings = Field(default_factory=PauseSettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)
    retry: RetrySettings = Field(default_factory=RetrySettings)

    # 直接透传字段
    active_task: str = ""
    custom_variables: dict[str, str] = Field(default_factory=dict)
    block_proxy: bool = False
    shell_path: str = ""
    minimize_to_tray: bool = False
    startup_action: str = "none"
    autostart_lightweight: bool = True
    lightweight_tray: bool = True
    auto_open_browser: bool = False


class ProfilesData(BaseModel):
    """settings.json 顶层结构（v3）"""

    config_version: int = Field(default=3)
    config: RuntimeConfig = Field(default_factory=RuntimeConfig)
    auto_switch: bool = Field(default=False, description="是否根据网关 IP 自动切换方案")
    active_profile: str = Field(default="default")
    profiles: dict[str, Profile] = Field(default_factory=dict)

    @model_validator(mode="after")
    def ensure_default_profile(self) -> ProfilesData:
        """确保 default profile 存在"""
        if "default" not in self.profiles:
            self.profiles["default"] = Profile()
        return self


