from __future__ import annotations

from pydantic import BaseModel, Field


class MonitorConfigPayload(BaseModel):
    username: str = Field(default="")
    password: str = Field(default="")
    carrier: str = Field(default="无")
    check_interval_minutes: int = Field(default=5, ge=1, le=1440)
    auto_start: bool = False
    headless: bool = False
    pause_enabled: bool = True
    pause_start_hour: int = Field(default=0, ge=0, le=23)
    pause_end_hour: int = Field(default=6, ge=0, le=23)


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
    message: str


class AutoStartStatusResponse(BaseModel):
    platform: str
    enabled: bool
    method: str
    location: str
