from __future__ import annotations

import json
import re

from pydantic import BaseModel, Field, field_validator

DEFAULT_BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

_VALID_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
_URL_PATTERN = re.compile(r"^https?://")


class MonitorConfigPayload(BaseModel):
    username: str = Field(default="")
    password: str = Field(default="")
    use_global_credentials: bool = Field(
        default=True,
        description="当前是否使用全局凭证（前端只读，后端填充）",
    )
    auth_url: str = Field(default="http://172.29.0.2")
    carrier: str = Field(default="无")
    carrier_custom: str = Field(default="")
    check_interval_minutes: int = Field(default=5, ge=1, le=1440)
    auto_start: bool = False
    headless: bool = True
    browser_timeout: int = Field(default=8000, ge=1000, le=60000)
    browser_user_agent: str = Field(default=DEFAULT_BROWSER_USER_AGENT)
    browser_low_resource_mode: bool = True
    browser_disable_web_security: bool = False
    browser_extra_headers_json: str = Field(default="")
    pause_enabled: bool = True
    pause_start_hour: int = Field(default=0, ge=0, le=23)
    pause_end_hour: int = Field(default=6, ge=0, le=23)
    network_targets: str = Field(
        default="8.8.8.8:53,114.114.114.114:53,www.baidu.com:443"
    )
    backend_log_level: str = Field(default="WARNING")
    frontend_log_level: str = Field(default="WARNING")
    access_log: bool = False
    minimize_to_tray: bool = True
    custom_variables: dict[str, str] = Field(default_factory=dict)

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
        if v and v not in _VALID_LOG_LEVELS:
            raise ValueError(f"无效的日志级别: {v}，可选值: {', '.join(_VALID_LOG_LEVELS)}")
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


class LogEntry(BaseModel):
    timestamp: str
    level: str = "INFO"
    source: str = "monitor"
    message: str

    @field_validator("level")
    @classmethod
    def validate_level(cls, v: str) -> str:
        v = v.upper().strip()
        return v if v in _VALID_LOG_LEVELS else "INFO"


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
        description="是否使用全局高级设置（true 时忽略以下高级字段，使用 .env 中的值）",
    )
    auth_url: str = Field(default="http://172.29.0.2")
    carrier: str = Field(default="无")
    carrier_custom: str = Field(default="")
    check_interval_minutes: int = Field(default=5, ge=1, le=1440)
    auto_start: bool = False
    headless: bool = True
    browser_timeout: int = Field(default=8000, ge=1000, le=60000)
    browser_user_agent: str = Field(default="")
    browser_low_resource_mode: bool = True
    browser_disable_web_security: bool = False
    browser_extra_headers_json: str = Field(default="")
    pause_enabled: bool = True
    pause_start_hour: int = Field(default=0, ge=0, le=23)
    pause_end_hour: int = Field(default=6, ge=0, le=23)
    network_targets: str = Field(
        default="8.8.8.8:53,114.114.114.114:53,www.baidu.com:443"
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


class ProfilesData(BaseModel):
    """Top-level structure of settings.json"""

    auto_switch: bool = Field(
        default=True, description="是否根据网关 IP 自动切换方案"
    )
    active_profile: str = Field(default="default")
    profiles: dict[str, ProfileSettings] = Field(default_factory=dict)
