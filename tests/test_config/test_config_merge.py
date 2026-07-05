"""配置合并覆盖语义测试 — 验证 Profile 值优先于全局默认值。"""

from __future__ import annotations

from pathlib import Path

from app.services.profile_service import ProfileService


def test_profile_active_task_overrides_global(tmp_path: Path):
    """Profile 的 active_task 应优先于全局 active_task。"""
    svc = ProfileService(tmp_path)
    data = svc.load()
    old_profile = data.profiles["default"]
    new_profile = old_profile.model_copy(update={"active_task": "task_123"})
    new_profiles = {**data.profiles, "default": new_profile}
    svc.save(data.model_copy(update={"profiles": new_profiles}))

    config = svc.get_runtime_config()
    assert config.active_task == "task_123"


def test_profile_auth_url_overrides_global(tmp_path: Path):
    """Profile 的 auth_url 应优先于全局 auth_url。"""
    svc = ProfileService(tmp_path)
    data = svc.load()
    old_profile = data.profiles["default"]
    new_profile = old_profile.model_copy(
        update={"auth_url": "http://profile.example.com"}
    )
    new_profiles = {**data.profiles, "default": new_profile}
    svc.save(data.model_copy(update={"profiles": new_profiles}))

    config = svc.get_runtime_config()
    assert config.credentials.auth_url == "http://profile.example.com"
