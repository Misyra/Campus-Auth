"""配置合并覆盖语义测试 — 验证 Profile 值优先于全局默认值。"""

from __future__ import annotations

from pathlib import Path

from app.services.profile_service import ProfileService
from app.services.runtime_config import load_runtime_config


def test_profile_active_task_overrides_global(tmp_path: Path):
    """Profile 的 active_task 应优先于全局 active_task。"""
    svc = ProfileService(tmp_path)
    data = svc.load()
    data.profiles["default"].active_task = "task_123"
    data.global_settings.active_task = ""
    svc.save(data)

    payload, _ = load_runtime_config(svc)
    assert payload.active_task == "task_123"


def test_global_active_task_used_when_profile_empty(tmp_path: Path):
    """Profile 的 active_task 为空时，应使用全局 active_task。"""
    svc = ProfileService(tmp_path)
    data = svc.load()
    data.profiles["default"].active_task = ""
    data.global_settings.active_task = "task_global"
    svc.save(data)

    payload, _ = load_runtime_config(svc)
    assert payload.active_task == "task_global"


def test_profile_auth_url_overrides_global(tmp_path: Path):
    """Profile 的 auth_url 应优先于全局 auth_url。"""
    svc = ProfileService(tmp_path)
    data = svc.load()
    data.profiles["default"].auth_url = "http://profile.example.com"
    data.global_settings.auth_url = "http://global.example.com"
    svc.save(data)

    payload, _ = load_runtime_config(svc)
    assert payload.auth_url == "http://profile.example.com"
