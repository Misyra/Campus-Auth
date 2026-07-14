"""配置持久化 E2E 测试 — 真实文件读写。

通过 PUT /api/config 修改配置，验证 API 返回新值、settings.json 落盘、
以及重启后（新建 ProfileService）从文件加载。
"""

from __future__ import annotations

import json


def _get_config(client):
    """获取当前配置。"""
    resp = client.get("/api/config")
    assert resp.status_code == 200
    return resp.json()


def _put_config(client, cfg, **overrides):
    """根据当前配置构造完整 PUT 体并提交。

    password 固定为 None（不修改密码），其余字段从 cfg 取值。
    顶层字段可通过 overrides 覆盖；嵌套字段（browser/monitor/retry 等）
    需在调用前直接修改 cfg 的对应字典。
    """
    body = {
        "browser": cfg["browser"],
        "monitor": cfg["monitor"],
        "retry": cfg["retry"],
        "pause": cfg["pause"],
        "logging": cfg["logging"],
        "app_settings": cfg["app_settings"],
        "username": cfg["username"],
        "password": None,  # 不修改密码
        "auth_url": cfg["auth_url"],
        "isp": cfg["isp"],
        "carrier_custom": cfg["carrier_custom"],
        "active_task": cfg["active_task"],
    }
    body.update(overrides)
    resp = client.put("/api/config", json=body)
    assert resp.status_code == 200, resp.text
    assert resp.json()["success"] is True


def _read_settings(e2e_project):
    """读取 settings.json。"""
    return json.loads(
        (e2e_project / "config" / "settings.json").read_text(encoding="utf-8")
    )


class TestConfigPersistence:
    """配置修改持久化到文件。"""

    def test_modify_credentials(self, real_app, e2e_project):
        """修改 username/auth_url/isp 并验证持久化。"""
        client, _ = real_app
        cfg = _get_config(client)
        _put_config(
            client,
            cfg,
            username="persist_user",
            auth_url="http://persist.example/",
            isp="中国移动",
        )
        # API 返回新值
        new_cfg = _get_config(client)
        assert new_cfg["username"] == "persist_user"
        assert new_cfg["auth_url"] == "http://persist.example/"
        assert new_cfg["isp"] == "中国移动"
        # 文件写入新值
        data = _read_settings(e2e_project)
        profile = data["profiles"]["default"]
        assert profile["username"] == "persist_user"
        assert profile["auth_url"] == "http://persist.example/"
        assert profile["carrier"] == "中国移动"

    def test_modify_browser_settings(self, real_app, e2e_project):
        """修改 browser settings 持久化。"""
        client, _ = real_app
        cfg = _get_config(client)
        cfg["browser"]["headless"] = False
        cfg["browser"]["timeout"] = 30
        _put_config(client, cfg)
        # API 返回新值
        new_cfg = _get_config(client)
        assert new_cfg["browser"]["headless"] is False
        assert new_cfg["browser"]["timeout"] == 30
        # 文件写入新值
        data = _read_settings(e2e_project)
        assert data["global_config"]["browser"]["headless"] is False
        assert data["global_config"]["browser"]["timeout"] == 30

    def test_modify_monitor_settings(self, real_app, e2e_project):
        """修改 monitor settings 持久化。"""
        client, _ = real_app
        cfg = _get_config(client)
        cfg["monitor"]["check_interval_seconds"] = 600
        _put_config(client, cfg)
        new_cfg = _get_config(client)
        assert new_cfg["monitor"]["check_interval_seconds"] == 600
        data = _read_settings(e2e_project)
        assert data["global_config"]["monitor"]["check_interval_seconds"] == 600

    def test_modify_retry_settings(self, real_app, e2e_project):
        """修改 retry settings 持久化。"""
        client, _ = real_app
        cfg = _get_config(client)
        cfg["retry"]["max_retries"] = 5
        cfg["retry"]["retry_interval"] = 60
        _put_config(client, cfg)
        new_cfg = _get_config(client)
        assert new_cfg["retry"]["max_retries"] == 5
        assert new_cfg["retry"]["retry_interval"] == 60
        data = _read_settings(e2e_project)
        assert data["global_config"]["retry"]["max_retries"] == 5
        assert data["global_config"]["retry"]["retry_interval"] == 60

    def test_restart_loads_from_file(self, real_app, e2e_project):
        """重启后配置从文件加载（新建 ProfileService 模拟重启）。"""
        client, _ = real_app
        cfg = _get_config(client)
        _put_config(
            client,
            cfg,
            username="restart_user",
            auth_url="http://restart.example/",
        )
        # 模拟重启：创建新的 ProfileService 从磁盘读取（不经过单例缓存）
        from app.services.profile_service import ProfileService

        fresh = ProfileService(e2e_project)
        data = fresh.load()
        profile = data.profiles[data.active_profile]
        assert profile.username == "restart_user"
        assert profile.auth_url == "http://restart.example/"
