from __future__ import annotations

from pydantic import BaseModel, Field

DEFAULT_BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


class MonitorConfigPayload(BaseModel):
    username: str = Field(default="")
    password: str = Field(default="")
    auth_url: str = Field(default="http://172.29.0.2")
    carrier: str = Field(default="无")
    carrier_custom: str = Field(default="")
    check_interval_minutes: int = Field(default=5, ge=1, le=1440)
    auto_start: bool = False
    headless: bool = False
    browser_timeout: int = Field(default=8000, ge=1000, le=60000)
    browser_user_agent: str = Field(default=DEFAULT_BROWSER_USER_AGENT)
    browser_low_resource_mode: bool = False
    browser_disable_web_security: bool = False
    browser_extra_headers_json: str = Field(default="")
    pause_enabled: bool = True
    pause_start_hour: int = Field(default=0, ge=0, le=23)
    pause_end_hour: int = Field(default=6, ge=0, le=23)
    network_targets: str = Field(
        default="8.8.8.8:53,114.114.114.114:53,www.baidu.com:443"
    )
    backend_log_level: str = Field(default="INFO")
    frontend_log_level: str = Field(default="INFO")
    access_log: bool = False
    minimize_to_tray: bool = False
    custom_variables: dict[str, str] = Field(default_factory=dict)


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


class AutoStartStatusResponse(BaseModel):
    platform: str
    enabled: bool
    method: str
    location: str
