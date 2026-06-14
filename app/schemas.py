from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator

from app.constants import DEFAULT_HTTP_TARGETS, DEFAULT_NETWORK_TARGETS
from app.utils.logging import VALID_LOG_LEVELS
from app.utils.platform import get_default_ua

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
    auto_open_browser: bool = False


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


# ── 共享字段 mixin（消除 MonitorConfigPayload 与 ProfileSettings 之间的重复） ──


class _BrowserFieldsMixin(BaseModel):
    """浏览器相关共享字段"""

    headless: bool = True
    browser_timeout: int = Field(
        default=8, ge=1, le=60, description="页面操作超时（秒）"
    )
    login_timeout: int = Field(
        default=60, ge=10, le=600, description="手动登录等待超时（秒）"
    )
    browser_navigation_timeout: int = Field(
        default=15, ge=3, le=60, description="打开登录页面超时（秒）"
    )
    browser_user_agent: str = Field(default_factory=get_default_ua)
    browser_low_resource_mode: bool = False
    browser_disable_web_security: bool = False
    browser_extra_headers_json: str = Field(default="")
    browser_args: str = Field(
        default=_BROWSER_ARGS_DEFAULT, description="自定义 Chromium 启动参数，每行一个"
    )
    stealth_mode: bool = Field(
        default=False, description="隐藏浏览器自动操作特征，降低被识别为工具操作的风险"
    )
    stealth_custom_script: str = Field(
        default="",
        description="在反检测模式开启时额外执行的自定义 JavaScript 脚本",
    )
    browser_locale: str = Field(default="zh-CN", description="浏览器语言区域")
    browser_timezone: str = Field(default="Asia/Shanghai", description="浏览器时区 ID")
    browser_viewport_width: int = Field(
        default=1280, ge=320, le=3840, description="浏览器视口宽度"
    )
    browser_viewport_height: int = Field(
        default=720, ge=240, le=2160, description="浏览器视口高度"
    )

    @field_validator("browser_extra_headers_json")
    @classmethod
    def validate_headers_json(cls, v: str) -> str:
        v = v.strip()
        if not v:
            return ""
        try:
            parsed = json.loads(v)
        except json.JSONDecodeError as e:
            raise ValueError(
                f"浏览器请求头格式不正确，请确认输入的是合法的 JSON 对象: {e}"
            ) from e
        if not isinstance(parsed, dict):
            raise ValueError(
                '浏览器请求头格式不正确，应为键值对形式，例如: {"Referer": "https://example.com"}'
            )
        return json.dumps(parsed, ensure_ascii=False, separators=(",", ":"))


class _MonitorFieldsMixin(BaseModel):
    """监控与网络检测相关共享字段"""

    auth_url: str = Field(default="")
    active_task: str = Field(default="")
    carrier: str = Field(default="无")
    carrier_custom: str = Field(default="")
    check_interval_seconds: int = Field(
        default=300, ge=10, le=86400, description="检测间隔（秒）"
    )
    network_targets: str = Field(default=DEFAULT_NETWORK_TARGETS)
    http_targets: str = Field(
        default=DEFAULT_HTTP_TARGETS,
        description="HTTP 检测目标地址，逗号分隔",
    )
    enable_tcp_check: bool = Field(
        default=False, description="通过 TCP 端口连接检测目标地址是否可达"
    )
    enable_http_check: bool = Field(
        default=False, description="通过 HTTP 请求检测网页是否可正常访问"
    )
    enable_local_check: bool = Field(
        default=True,
        description="物理网络连接检查：未连接 WiFi/网线时跳过登录",
    )
    check_auth_url: bool = Field(
        default=False, description="登录前检测认证地址是否可达，不可达则跳过登录"
    )
    auth_url_targets: str = Field(
        default="",
        description="认证地址可达性附加检测目标，逗号分隔的 host:port，留空则仅检测认证地址本身",
    )
    url_check_urls: str = Field(
        default="http://captive.apple.com/hotspot-detect.html|Success\nhttp://www.msftconnecttest.com/connecttest.txt|Microsoft Connect Test\nhttp://detectportal.firefox.com/success.txt|success",
        description="网址响应检测地址，每行一个：URL|预期内容，留空不启用",
    )
    block_proxy: bool = Field(
        default=True, description="屏蔽系统代理：开启后网络检测时忽略系统代理设置"
    )
    custom_variables: dict[str, str] = Field(default_factory=dict)

    @field_validator("auth_url")
    @classmethod
    def validate_auth_url(cls, v: str) -> str:
        return _validate_auth_url(v)


class _SystemFieldsMixin(BaseModel):
    """SystemSettings 与 MonitorConfigPayload 共享的系统配置字段"""

    username: str = Field(default="", description="全局校园网用户名")
    password: str = Field(default="", description="全局校园网密码（ENC: 加密）")
    auth_url: str = Field(default="", description="全局认证地址")
    carrier: str = Field(default="无", description="全局运营商")
    carrier_custom: str = Field(default="", description="自定义运营商关键字")
    pause_enabled: bool = Field(default=True, description="启用暂停时段")
    pause_start_hour: int = Field(default=0, ge=0, le=23, description="暂停开始（小时）")
    pause_end_hour: int = Field(default=6, ge=0, le=23, description="暂停结束（小时）")
    backend_log_level: str = Field(default="INFO")
    frontend_log_level: str = Field(default="INFO")
    access_log: bool = Field(default=False, description="Uvicorn HTTP 请求日志")
    startup_action: StartupAction = Field(
        default=StartupAction.NONE,
        description="启动行为：none=不自动执行, monitor=自动监控, login_once=自动登录成功后退出",
    )
    autostart_lightweight: bool = Field(
        default=True, description="自启动轻量模式：True=仅监控, False=完整模式(含Web)"
    )
    minimize_to_tray: bool = Field(default=True, description="最小化到系统托盘")
    auto_open_browser: bool = Field(default=False, description="启动后自动打开浏览器")
    max_retries: int = Field(default=3, ge=0, le=10)
    retry_interval: int = Field(default=5, ge=1, le=300, description="重试间隔（秒）")
    log_retention_days: int = Field(
        default=7, ge=1, le=365, description="日志保留天数"
    )
    app_port: int = Field(default=50721, ge=1024, le=65535, description="网页界面端口")
    proxy: str = Field(default="", description="网络代理地址")
    shell_path: str = Field(
        default="", description="自定义 Shell 路径（留空使用系统默认）"
    )

    @field_validator("auth_url")
    @classmethod
    def validate_auth_url(cls, v: str) -> str:
        return _validate_auth_url(v)

    @field_validator("backend_log_level", "frontend_log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        v = v.upper().strip()
        if v and v not in VALID_LOG_LEVELS:
            raise ValueError(
                f"无效的日志级别: {v}，可选值: {', '.join(VALID_LOG_LEVELS)}"
            )
        return v


class GlobalSettings(BaseModel):
    """全局系统配置 — 仅系统级设置，不包含业务逻辑"""

    # 日志配置
    backend_log_level: str = Field(default="INFO")
    frontend_log_level: str = Field(default="INFO")
    access_log: bool = Field(default=False, description="Uvicorn HTTP 请求日志")
    log_retention_days: int = Field(default=7, ge=1, le=365, description="日志保留天数")

    # UI 配置
    minimize_to_tray: bool = Field(default=True, description="最小化到系统托盘")
    auto_open_browser: bool = Field(default=False, description="启动后自动打开浏览器")
    startup_action: StartupAction = Field(default=StartupAction.NONE)
    autostart_lightweight: bool = Field(default=True)

    # 网络配置
    proxy: str = Field(default="", description="网络代理地址")
    block_proxy: bool = Field(default=True, description="屏蔽系统代理")

    # 应用配置
    app_port: int = Field(default=50721, ge=1024, le=65535)
    shell_path: str = Field(default="", description="自定义 Shell 路径")
    pure_mode: bool = Field(default=True, description="纯净模式")

    # 重试配置
    max_retries: int = Field(default=3, ge=0, le=10)
    retry_interval: int = Field(default=5, ge=1, le=300, description="重试间隔（秒）")

    # Source 级别配置
    source_levels: dict[str, str] = {}

    @field_validator("backend_log_level", "frontend_log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        v = v.upper().strip()
        if v and v not in VALID_LOG_LEVELS:
            raise ValueError(
                f"无效的日志级别: {v}，可选值: {', '.join(VALID_LOG_LEVELS)}"
            )
        return v


# ── 主要模型 ──


class MonitorConfigPayload(
    _BrowserFieldsMixin,
    _MonitorFieldsMixin,
    _SystemFieldsMixin,
):
    network_check_timeout: int = Field(
        default=2,
        ge=1,
        le=30,
        description="TCP 网络检测超时（秒），检测网络连通性时使用",
    )
    use_global_credentials: bool = Field(
        default=True, description="当前是否使用全局凭证（前端只读，后端填充）"
    )

    @field_validator("custom_variables")
    @classmethod
    def validate_custom_variables(cls, v: dict[str, str]) -> dict[str, str]:
        _ENV_KEY_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
        if len(v) > 50:
            raise ValueError("自定义变量最多 50 个")
        for key, val in v.items():
            if not _ENV_KEY_PATTERN.match(key):
                raise ValueError(
                    f"变量名格式无效: {key}，须以字母或下划线开头，仅含字母、数字和下划线"
                )
            if len(key) > 100:
                raise ValueError(f"变量名过长（最大 100 字符）: {key}")
            if len(val) > 10000:
                raise ValueError(f"变量 {key} 的值过长（最大 10000 字符）")
        return v


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


class ProfileSettings(_BrowserFieldsMixin):
    """方案配置 — 所有业务配置的唯一数据源"""

    # 基本信息
    name: str = Field(default="默认方案")
    match_gateway_ip: str = Field(
        default="", description="匹配的网关 IP，留空表示不匹配（手动选择时使用）"
    )
    match_ssid: str = Field(default="", description="匹配的 WiFi SSID，留空表示不匹配")

    # 凭证配置
    username: str = Field(default="", description="方案独立账号，留空则使用全局账号")
    password: str = Field(
        default="", description="方案独立密码（加密存储），留空则使用全局密码"
    )
    carrier: str = Field(default="无", description="方案独立运营商，留空则使用全局")
    carrier_custom: str = Field(default="", description="自定义运营商关键字")
    auth_url: str = Field(default="", description="方案独立认证地址，留空则使用全局")
    active_task: str = Field(default="", description="方案独立任务，留空则使用全局任务")

    # 监控配置
    check_interval_seconds: int = Field(
        default=300, ge=10, le=86400, description="检测间隔（秒）"
    )
    pause_enabled: bool = Field(default=True, description="启用暂停时段")
    pause_start_hour: int = Field(default=0, ge=0, le=23, description="暂停开始（小时）")
    pause_end_hour: int = Field(default=6, ge=0, le=23, description="暂停结束（小时）")
    network_targets: str = Field(default=DEFAULT_NETWORK_TARGETS)
    http_targets: str = Field(
        default=DEFAULT_HTTP_TARGETS, description="HTTP 检测目标地址，逗号分隔"
    )
    enable_tcp_check: bool = Field(
        default=False, description="通过 TCP 端口连接检测目标地址是否可达"
    )
    enable_http_check: bool = Field(
        default=False, description="通过 HTTP 请求检测网页是否可正常访问"
    )
    enable_local_check: bool = Field(
        default=True,
        description="物理网络连接检查：未连接 WiFi/网线时跳过登录",
    )
    check_auth_url: bool = Field(
        default=False, description="登录前检测认证地址是否可达，不可达则跳过登录"
    )
    auth_url_targets: str = Field(
        default="",
        description="认证地址可达性附加检测目标，逗号分隔的 host:port，留空则仅检测认证地址本身",
    )
    url_check_urls: str = Field(
        default="http://captive.apple.com/hotspot-detect.html|Success\nhttp://www.msftconnecttest.com/connecttest.txt|Microsoft Connect Test\nhttp://detectportal.firefox.com/success.txt|success",
        description="网址响应检测地址，每行一个：URL|预期内容，留空不启用",
    )
    network_check_timeout: int = Field(
        default=2, ge=1, le=30, description="TCP 网络检测超时（秒）"
    )

    # 自定义变量
    custom_variables: dict[str, str] = Field(default_factory=dict)

    # 全局配置覆盖标志
    use_global_credentials: bool = Field(
        default=True,
        description="是否使用全局账号密码（true 时忽略 username/password/carrier）",
    )
    use_global_auth_url: bool = Field(
        default=True,
        description="是否使用全局认证地址（true 时忽略 auth_url，使用系统设置中的认证地址）",
    )
    use_global_task: bool = Field(
        default=True,
        description="是否使用全局活动任务（true 时忽略 active_task，使用全局任务）",
    )

    @field_validator("auth_url")
    @classmethod
    def validate_auth_url(cls, v: str) -> str:
        return _validate_auth_url(v)


class SystemSettings(_SystemFieldsMixin):
    """全局系统配置（原 .env 中的业务配置）"""

    pure_mode: bool = Field(
        default=True, description="纯净模式：使用浏览器原始默认设置，不添加额外启动参数"
    )
    network_check_timeout: int = Field(
        default=2, ge=1, le=30, description="TCP 网络检测超时（秒）"
    )
    block_proxy: bool = Field(
        default=True, description="屏蔽系统代理：开启后网络检测时忽略系统代理设置"
    )
    # 新增：source 级别配置
    source_levels: dict[str, str] = {}


class ProfilesData(BaseModel):
    """Top-level structure of settings.json"""

    auto_switch: bool = Field(default=False, description="是否根据网关 IP 自动切换方案")
    active_profile: str = Field(default="default")
    system: SystemSettings = Field(default_factory=SystemSettings)
    profiles: dict[str, ProfileSettings] = Field(default_factory=dict)


def get_runtime_features(
    mode: RuntimeMode | str, minimize_to_tray: bool, auto_open_browser: bool
) -> RuntimeFeatures:
    """根据运行模式派生特性标志"""
    if mode == RuntimeMode.LIGHTWEIGHT:
        return RuntimeFeatures(
            web_enabled=False,
            browser_enabled=False,
            tray_enabled=minimize_to_tray,
        )
    return RuntimeFeatures(
        web_enabled=True,
        browser_enabled=auto_open_browser,
        tray_enabled=minimize_to_tray,
    )
