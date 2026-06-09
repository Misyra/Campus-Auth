from __future__ import annotations

import json
import re

from pydantic import BaseModel, Field, field_validator, model_validator

from app.constants import DEFAULT_HTTP_TARGETS, DEFAULT_NETWORK_TARGETS
from app.utils.logging import VALID_LOG_LEVELS
from app.utils.platform_utils import get_default_ua

_URL_PATTERN = re.compile(r"^https?://")

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


class _ClampMixin(BaseModel):
    """自动将越界的数值字段钳制到合法范围，而非校验失败。"""

    @model_validator(mode="before")
    @classmethod
    def _clamp_numeric_fields(cls, data: dict) -> dict:
        if not isinstance(data, dict):
            return data
        from app.utils.logging import get_logger

        _logger = get_logger("schemas")
        for name, field_info in cls.model_fields.items():
            if name not in data:
                continue
            meta = field_info.metadata
            if not meta:
                continue
            ge_val = le_val = None
            for m in meta:
                if hasattr(m, "ge") and m.ge is not None:
                    ge_val = m.ge
                if hasattr(m, "le") and m.le is not None:
                    le_val = m.le
            if ge_val is None and le_val is None:
                continue
            try:
                v = int(data[name])
            except (ValueError, TypeError):
                continue
            if ge_val is not None and v < ge_val:
                _logger.warning(
                    "字段 '{}' 值 {} 低于下限 {}，已自动钳制", name, v, ge_val
                )
                data[name] = ge_val
            elif le_val is not None and v > le_val:
                _logger.warning(
                    "字段 '{}' 值 {} 超过上限 {}，已自动钳制", name, v, le_val
                )
                data[name] = le_val
        return data


class _BrowserFieldsMixin(_ClampMixin):
    """浏览器相关共享字段"""

    headless: bool = True
    browser_timeout: int = Field(
        default=8, ge=1, le=60, description="页面操作超时（秒）"
    )
    login_timeout: int = Field(
        default=60, ge=10, le=600, description="手动登录 API 请求超时（秒）"
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
        default=False, description="注入反检测脚本，隐藏浏览器自动化痕迹"
    )
    stealth_custom_script: str = Field(
        default="",
        description="自定义反检测 JavaScript 脚本，stealth_mode 开启时追加执行",
    )
    browser_locale: str = Field(default="zh-CN", description="浏览器语言区域")
    browser_timezone: str = Field(default="Asia/Shanghai", description="浏览器时区 ID")
    browser_viewport_width: int = Field(
        default=1280, ge=320, le=3840, description="浏览器视口宽度"
    )
    browser_viewport_height: int = Field(
        default=720, ge=240, le=2160, description="浏览器视口高度"
    )


class _MonitorFieldsMixin(_ClampMixin):
    """监控与网络检测相关共享字段"""

    auth_url: str = Field(default="")
    active_task: str = Field(default="")
    carrier: str = Field(default="无")
    carrier_custom: str = Field(default="")
    check_interval_seconds: int = Field(
        default=300, ge=10, le=86400, description="检测间隔（秒）"
    )
    auto_start: bool = False
    pause_enabled: bool = True
    pause_start_hour: int = Field(default=0, ge=0, le=23)
    pause_end_hour: int = Field(default=6, ge=0, le=23)
    network_targets: str = Field(default=DEFAULT_NETWORK_TARGETS)
    http_targets: str = Field(
        default=DEFAULT_HTTP_TARGETS,
        description="HTTP 检测目标地址，逗号分隔",
    )
    enable_tcp_check: bool = Field(default=True, description="启用 TCP 检测网络连通性")
    enable_http_check: bool = Field(
        default=True, description="启用 HTTP 检测网络连通性"
    )
    enable_local_check: bool = Field(
        default=True,
        description="物理网络连接检查：未连接 WiFi/网线时跳过登录",
    )
    check_auth_url: bool = Field(
        default=True, description="登录前检测认证地址是否可达，不可达则跳过登录"
    )
    auth_url_targets: str = Field(
        default="",
        description="认证地址可达性附加检测目标，逗号分隔的 host:port，留空则仅检测认证地址本身",
    )
    portal_check_urls: str = Field(
        default="http://captive.apple.com/hotspot-detect.html|Success\n"
        "http://www.msftconnecttest.com/connecttest.txt|Microsoft Connect Test\n"
        "http://detectportal.firefox.com/success.txt|success",
        description="Captive portal 检测地址，每行一个：URL|预期内容，留空不启用",
    )
    block_proxy: bool = Field(
        default=True, description="屏蔽系统代理：开启后网络检测时忽略系统代理设置"
    )
    custom_variables: dict[str, str] = Field(default_factory=dict)


class _SharedValidatorsMixin:
    """包含 auth_url 的模型共享的验证器"""

    @field_validator("auth_url")
    @classmethod
    def validate_auth_url(cls, v: str) -> str:
        v = v.strip()
        if v and not _URL_PATTERN.match(v):
            raise ValueError("认证地址必须以 http:// 或 https:// 开头")
        return v


class _BrowserValidatorsMixin:
    """包含浏览器请求头字段的模型共享的验证器"""

    @field_validator("browser_extra_headers_json")
    @classmethod
    def validate_headers_json(cls, v: str) -> str:
        v = v.strip()
        if not v:
            return ""
        try:
            parsed = json.loads(v)
        except json.JSONDecodeError as e:
            raise ValueError(f"浏览器请求头 JSON 格式错误: {e}") from e
        if not isinstance(parsed, dict):
            raise ValueError("浏览器请求头必须是 JSON 对象")
        return v


class _SystemFieldsMixin(_ClampMixin):
    """SystemSettings 与 MonitorConfigPayload 共享的系统配置字段"""

    username: str = Field(default="", description="全局校园网用户名")
    password: str = Field(default="", description="全局校园网密码（ENC: 加密）")
    auth_url: str = Field(default="", description="全局认证地址")
    carrier: str = Field(default="无", description="全局运营商")
    carrier_custom: str = Field(default="", description="自定义运营商关键字")
    backend_log_level: str = Field(default="INFO")
    frontend_log_level: str = Field(default="INFO")
    access_log: bool = Field(default=False, description="Uvicorn HTTP 请求日志")
    minimize_to_tray: bool = Field(default=True, description="最小化到系统托盘")
    auto_open_browser: bool = Field(default=False, description="启动后自动打开浏览器")
    login_then_exit: bool = Field(default=False, description="登录成功后退出软件")
    max_retries: int = Field(default=3, ge=0, le=10)
    retry_interval: int = Field(default=5, ge=1, le=300, description="重试间隔（秒）")
    log_retention_days: int = Field(
        default=7, ge=1, le=365, description="日志与截图保留天数"
    )
    app_port: int = Field(
        default=50721, ge=1024, le=65535, description="Web 控制台端口"
    )
    proxy: str = Field(default="", description="网络代理地址")
    shell_path: str = Field(
        default="", description="自定义 Shell 路径（留空使用系统默认）"
    )

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
    _SharedValidatorsMixin,
    _BrowserValidatorsMixin,
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
        import re

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
    module: str = ""
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


class ProfileSettings(
    _BrowserFieldsMixin,
    _MonitorFieldsMixin,
    _SharedValidatorsMixin,
    _BrowserValidatorsMixin,
):
    """Profile-specific non-sensitive settings stored in settings.json"""

    name: str = Field(default="默认方案")
    match_gateway_ip: str = Field(
        default="", description="匹配的网关 IP，留空表示不匹配（手动选择时使用）"
    )
    match_ssid: str = Field(default="", description="匹配的 WiFi SSID，留空表示不匹配")
    username: str = Field(default="", description="方案独立账号，留空则使用全局账号")
    password: str = Field(
        default="", description="方案独立密码（加密存储），留空则使用全局密码"
    )
    use_global_credentials: bool = Field(
        default=True,
        description="是否使用全局账号密码（true 时忽略 username/password）",
    )
    use_global_advanced: bool = Field(
        default=True,
        description="是否使用全局高级设置（true 时忽略以下高级字段，使用系统设置中的值）",
    )
    use_global_auth_url: bool = Field(
        default=True,
        description="是否使用全局认证地址（true 时忽略 auth_url，使用系统设置中的认证地址）",
    )
    use_global_task: bool = Field(
        default=True,
        description="是否使用全局活动任务（true 时忽略 active_task，使用全局任务）",
    )


class SystemSettings(_SystemFieldsMixin, _SharedValidatorsMixin):
    """全局系统配置（原 .env 中的业务配置）"""

    pure_mode: bool = Field(
        default=False, description="纯净模式：使用 Chromium 原始设置，不注入自定义参数"
    )
    network_check_timeout: int = Field(
        default=2, ge=1, le=30, description="TCP 网络检测超时（秒）"
    )
    block_proxy: bool = Field(
        default=True, description="屏蔽系统代理：开启后网络检测时忽略系统代理设置"
    )


class ProfilesData(BaseModel):
    """Top-level structure of settings.json"""

    auto_switch: bool = Field(default=False, description="是否根据网关 IP 自动切换方案")
    active_profile: str = Field(default="default")
    system: SystemSettings = Field(default_factory=SystemSettings)
    profiles: dict[str, ProfileSettings] = Field(default_factory=dict)
