"""浏览器配置持久化与切换 E2E 测试。

验证 BrowserSettings 通过 API 修改后的持久化和读取：
- PATCH /api/config 修改 browser_channel 后 GET /api/config 验证持久化
- GET /api/browsers 的 current 字段与配置一致
- 重启应用（新建 ProfileService 模拟）后配置仍然存在
- headless、timeout 等其他浏览器参数的持久化
"""

from __future__ import annotations

import json
from pathlib import Path

# ── 辅助函数 ──


def _get_browser_config(client) -> dict:
    """获取当前浏览器配置。"""
    resp = client.get("/api/config")
    assert resp.status_code == 200
    return resp.json()["browser"]


def _patch_browser_config(client, browser_patch: dict) -> dict:
    """PATCH 更新浏览器配置，返回响应体。"""
    resp = client.patch("/api/config", json={"browser": browser_patch})
    assert resp.status_code == 200, f"PATCH 配置失败: {resp.text}"
    return resp.json()


def _read_settings_json(tmp_path: Path) -> dict:
    """直接读取 settings.json 文件内容（验证落盘）。"""
    settings_path = tmp_path / "config" / "settings.json"
    assert settings_path.exists(), f"settings.json 不存在: {settings_path}"
    return json.loads(settings_path.read_text(encoding="utf-8"))


# ── 测试类 ──


class TestBrowserConfigPersistence:
    """浏览器配置持久化与切换。"""

    def test_patch_browser_channel_persists(self, real_app):
        """PATCH browser_channel 后 GET /api/config 返回新值。"""
        client, _ = real_app

        # 默认值应为 msedge
        initial = _get_browser_config(client)
        assert initial["browser_channel"] == "msedge"

        # 修改为 playwright
        _patch_browser_config(client, {"browser_channel": "playwright"})

        # 验证 GET 返回新值
        updated = _get_browser_config(client)
        assert updated["browser_channel"] == "playwright"

    def test_browsers_endpoint_current_matches_config(self, real_app):
        """GET /api/browsers 的 current 字段与配置中的 browser_channel 一致。"""
        client, _ = real_app

        # 修改为 chrome
        _patch_browser_config(client, {"browser_channel": "chrome"})

        # 验证 /api/browsers 返回的 current
        resp = client.get("/api/browsers")
        assert resp.status_code == 200
        data = resp.json()
        assert data["current"] == "chrome"

    def test_browser_config_written_to_settings_json(self, real_app, tmp_path):
        """PATCH 后配置写入 settings.json 文件。"""
        client, _ = real_app

        _patch_browser_config(client, {"browser_channel": "firefox"})

        # 直接读取文件验证
        settings = _read_settings_json(tmp_path)
        # settings.json 结构：global_config.browser.browser_channel
        global_browser = settings.get("global_config", {}).get("browser", {})
        assert global_browser.get("browser_channel") == "firefox"

    def test_restart_loads_persisted_config(self, real_app, tmp_path):
        """重启应用（新建 ProfileService）后配置仍然存在。"""
        client, _ = real_app

        # 修改多个浏览器参数
        _patch_browser_config(
            client,
            {
                "browser_channel": "playwright",
                "headless": False,
                "timeout": 15,
                "navigation_timeout": 20,
            },
        )

        # 新建 ProfileService 模拟重启（无缓存，从磁盘读取）
        from app.services.profile_service import ProfileService

        new_ps = ProfileService(tmp_path)
        data = new_ps.load()
        cfg = new_ps.build_runtime_config(data)

        # 验证浏览器配置已持久化
        assert cfg.browser.browser_channel == "playwright"
        assert cfg.browser.headless is False
        assert cfg.browser.timeout == 15
        assert cfg.browser.navigation_timeout == 20

    def test_patch_multiple_browser_settings(self, real_app):
        """一次 PATCH 多个浏览器参数，全部持久化。"""
        client, _ = real_app

        _patch_browser_config(
            client,
            {
                "browser_channel": "playwright",
                "headless": False,
                "timeout": 30,
                "viewport_width": 1920,
                "viewport_height": 1080,
                "locale": "en-US",
            },
        )

        browser = _get_browser_config(client)
        assert browser["browser_channel"] == "playwright"
        assert browser["headless"] is False
        assert browser["timeout"] == 30
        assert browser["viewport_width"] == 1920
        assert browser["viewport_height"] == 1080
        assert browser["locale"] == "en-US"

    def test_patch_headless_and_timeout_persist(self, real_app, tmp_path):
        """headless 和 timeout 参数修改后持久化到文件。

        注意：ConfigPatchRequest.browser 是完整 BrowserSettings 类型，
        每次 PATCH 会用 BrowserSettings 默认值覆盖未传字段。
        因此需在单次 PATCH 中同时传入所有需修改的字段。
        """
        client, _ = real_app

        # 单次 PATCH 同时修改 headless 和 timeout
        _patch_browser_config(
            client,
            {"headless": False, "timeout": 25},
        )

        # 验证 API 返回值
        browser = _get_browser_config(client)
        assert browser["headless"] is False
        assert browser["timeout"] == 25

        # 验证文件中也持久化
        settings = _read_settings_json(tmp_path)
        global_browser = settings.get("global_config", {}).get("browser", {})
        assert global_browser.get("headless") is False
        assert global_browser.get("timeout") == 25

    def test_patch_pure_mode_persists(self, real_app):
        """pure_mode 参数修改后持久化。"""
        client, _ = real_app

        # 默认 pure_mode=True
        initial = _get_browser_config(client)
        assert initial["pure_mode"] is True

        # 修改为 False
        _patch_browser_config(client, {"pure_mode": False})
        updated = _get_browser_config(client)
        assert updated["pure_mode"] is False

    def test_browser_settings_default_values(self, real_app):
        """首次 GET /api/config 返回 BrowserSettings 默认值。"""
        client, _ = real_app

        browser = _get_browser_config(client)
        # 验证关键字段都有默认值
        assert browser["browser_channel"] == "msedge"
        assert browser["headless"] is True
        assert browser["timeout"] == 8
        assert browser["navigation_timeout"] == 8
        assert browser["pure_mode"] is True
        assert browser["viewport_width"] == 1280
        assert browser["viewport_height"] == 720
        assert browser["locale"] == "zh-CN"
        assert browser["timezone_id"] == "Asia/Shanghai"

    def test_channel_switch_multiple_times(self, real_app):
        """多次切换 browser_channel，每次都正确持久化。"""
        client, _ = real_app

        for channel in ["playwright", "chrome", "msedge", "firefox", "playwright"]:
            _patch_browser_config(client, {"browser_channel": channel})
            browser = _get_browser_config(client)
            assert browser["browser_channel"] == channel, (
                f"切换到 {channel} 后验证失败，实际: {browser['browser_channel']}"
            )

    def test_config_defaults_endpoint_returns_browser_defaults(self, real_app):
        """GET /api/config/defaults 返回 BrowserSettings 默认值。"""
        client, _ = real_app

        resp = client.get("/api/config/defaults")
        assert resp.status_code == 200
        defaults = resp.json()
        assert "browser" in defaults
        browser = defaults["browser"]
        assert browser["browser_channel"] == "msedge"
        assert browser["headless"] is True
        assert browser["timeout"] == 8
