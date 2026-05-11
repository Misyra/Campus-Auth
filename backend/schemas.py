from __future__ import annotations

import json
import re

from pydantic import BaseModel, Field, field_validator

VALID_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
_URL_PATTERN = re.compile(r"^https?://")


class MonitorConfigPayload(BaseModel):
    username: str = Field(default="")
    password: str = Field(default="")
    use_global_credentials: bool = Field(
        default=True,
        description="当前是否使用全局凭证（前端只读，后端填充）",
    )
    auth_url: str = Field(default="")
    active_task: str = Field(default="")
    carrier: str = Field(default="无")
    carrier_custom: str = Field(default="")
    check_interval_minutes: int = Field(default=5, ge=1, le=1440)
    auto_start: bool = False
    headless: bool = True
    browser_timeout: int = Field(default=8000, ge=1000, le=60000)
    login_timeout: int = Field(default=120, ge=10, le=600, description="手动登录 API 请求超时（秒）")
    browser_user_agent: str = Field(
        default="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    )
    browser_low_resource_mode: bool = False
    browser_disable_web_security: bool = False
    browser_extra_headers_json: str = Field(default="")
    browser_args: str = Field(default="--disable-blink-features=AutomationControlled\n--disable-software-rasterizer\n--disable-extensions\n--disable-background-timer-throttling\n--disable-backgrounding-occluded-windows\n--disable-renderer-backgrounding\n--disable-features=TranslateUI,BlinkGenPropertyTrees\n--disable-ipc-flooding-protection\n--disable-hang-monitor\n--disable-popup-blocking")
    stealth_mode: bool = Field(default=False, description="注入反检测脚本，隐藏浏览器自动化痕迹")
    pause_enabled: bool = True
    pause_start_hour: int = Field(default=0, ge=0, le=23)
    pause_end_hour: int = Field(default=6, ge=0, le=23)
    network_targets: str = Field(
        default="8.8.8.8:53,114.114.114.114:53,www.baidu.com:443"
    )
    network_strict_mode: bool = Field(
        default=True,
        description="网络检测严格模式：开启后 TCP 和 HTTP 必须同时通过才算联网成功",
    )
    backend_log_level: str = Field(default="INFO")
    frontend_log_level: str = Field(default="INFO")
    access_log: bool = False
    minimize_to_tray: bool = True
    auto_open_browser: bool = False
    login_then_exit: bool = False
    log_retention_days: int = Field(default=7, ge=1, le=365)
    screenshot_retention_days: int = Field(default=7, ge=1, le=90)
    custom_variables: dict[str, str] = Field(default_factory=dict)
    proxy: str = Field(default="", description="网络代理地址，留空不使用代理")

    @field_validator("auth_url")
    @classmethod
    def validate_auth_url(cls, v: str) -> str:
        v = v.strip()
        if v and not _URL_PATTERN.match(v):
            raise ValueError("认证地址必须以 http:// 或 https:// 开头")
        return v

    @field_validator("backend_log_level", "frontend_log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        v = v.upper().strip()
        if v and v not in VALID_LOG_LEVELS:
            raise ValueError(f"无效的日志级别: {v}，可选值: {', '.join(VALID_LOG_LEVELS)}")
        return v

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

    @field_validator("custom_variables")
    @classmethod
    def validate_custom_variables(cls, v: dict[str, str]) -> dict[str, str]:
        if len(v) > 50:
            raise ValueError("自定义变量最多 50 个")
        for key, val in v.items():
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


class LogEntry(BaseModel):
    timestamp: str
    level: str = "INFO"
    source: str = "monitor"
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


class ProfileSettings(BaseModel):
    """Profile-specific non-sensitive settings stored in settings.json"""

    name: str = Field(default="默认方案")
    match_gateway_ip: str = Field(
        default="",
        description="匹配的网关 IP，留空表示不匹配（手动选择时使用）",
    )
    match_ssid: str = Field(
        default="",
        description="匹配的 WiFi SSID，留空表示不匹配",
    )
    username: str = Field(
        default="",
        description="方案独立账号，留空则使用全局账号",
    )
    password: str = Field(
        default="",
        description="方案独立密码（加密存储），留空则使用全局密码",
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
    auth_url: str = Field(default="")
    active_task: str = Field(default="", description="方案使用的任务 ID，留空使用默认任务")
    carrier: str = Field(default="无")
    carrier_custom: str = Field(default="")
    check_interval_minutes: int = Field(default=5, ge=1, le=1440)
    auto_start: bool = False
    headless: bool = True
    browser_timeout: int = Field(default=8000, ge=1000, le=60000)
    login_timeout: int = Field(default=120, ge=10, le=600, description="手动登录 API 请求超时（秒）")
    browser_user_agent: str = Field(
        default="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    )
    browser_low_resource_mode: bool = False
    browser_disable_web_security: bool = False
    browser_extra_headers_json: str = Field(default="")
    browser_args: str = Field(default="--disable-blink-features=AutomationControlled\n--disable-software-rasterizer\n--disable-extensions\n--disable-background-timer-throttling\n--disable-backgrounding-occluded-windows\n--disable-renderer-backgrounding\n--disable-features=TranslateUI,BlinkGenPropertyTrees\n--disable-ipc-flooding-protection\n--disable-hang-monitor\n--disable-popup-blocking", description="自定义 Chromium 启动参数，每行一个")
    stealth_mode: bool = Field(default=False, description="注入反检测脚本，隐藏浏览器自动化痕迹")
    pause_enabled: bool = True
    pause_start_hour: int = Field(default=0, ge=0, le=23)
    pause_end_hour: int = Field(default=6, ge=0, le=23)
    network_targets: str = Field(
        default="8.8.8.8:53,114.114.114.114:53,www.baidu.com:443"
    )
    network_strict_mode: bool = Field(
        default=True,
        description="网络检测严格模式：开启后 TCP 和 HTTP 必须同时通过才算联网成功",
    )
    custom_variables: dict[str, str] = Field(default_factory=dict)

    @field_validator("auth_url")
    @classmethod
    def validate_auth_url(cls, v: str) -> str:
        v = v.strip()
        if v and not _URL_PATTERN.match(v):
            raise ValueError("认证地址必须以 http:// 或 https:// 开头")
        return v

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


class SystemSettings(BaseModel):
    """全局系统配置（原 .env 中的业务配置）"""

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
    login_then_exit: bool = Field(default=False, description="登录一次后退出软件")
    max_retries: int = Field(default=3, ge=0, le=10)
    retry_interval: int = Field(default=5, ge=1, le=300, description="重试间隔（秒）")
    safe_mode: bool = Field(default=True, description="安全模式：不注入浏览器自定义参数")
    log_retention_days: int = Field(default=7, ge=1, le=365, description="日志文件保留天数")
    screenshot_retention_days: int = Field(default=7, ge=1, le=90, description="失败截图保留天数")
    proxy: str = Field(default="", description="网络代理地址")

    @field_validator("backend_log_level", "frontend_log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        v = v.upper().strip()
        if v and v not in VALID_LOG_LEVELS:
            raise ValueError(f"无效的日志级别: {v}，可选值: {', '.join(VALID_LOG_LEVELS)}")
        return v


class ProfilesData(BaseModel):
    """Top-level structure of settings.json"""

    auto_switch: bool = Field(
        default=False, description="是否根据网关 IP 自动切换方案"
    )
    active_profile: str = Field(default="default")
    system: SystemSettings = Field(default_factory=SystemSettings)
    profiles: dict[str, ProfileSettings] = Field(default_factory=dict)
