"""版本更新检测 E2E 测试。

mock GitHub releases API 返回不同版本号，验证 /api/check-update 的 has_update 逻辑。
"""

from __future__ import annotations

from unittest.mock import patch


def _reset_update_cache() -> None:
    """重置版本检测缓存，避免上一轮测试缓存影响。"""
    from app.api import system

    system._update_cache = None
    system._update_cache_time = 0.0


def _make_fake_client(release_data):
    """构造模拟 httpx.AsyncClient，返回指定的 release 数据。"""

    class _Resp:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return release_data

    class _Client:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, url, headers=None):
            return _Resp()

    return _Client


class TestVersionDetection:
    """版本更新检测逻辑。"""

    def test_higher_version_has_update(self, real_app):
        """更高版本号触发 has_update=True。"""
        client, _ = real_app
        _reset_update_cache()
        release = {
            "tag_name": "v9.9.9",
            "html_url": "http://x",
            "body": "new release",
            "published_at": "2026-01-01",
        }
        with (
            patch("app.api.system.get_project_version", return_value="2.0.0"),
            patch("app.api.system.httpx.AsyncClient", _make_fake_client(release)),
        ):
            resp = client.get("/api/check-update")
        assert resp.status_code == 200
        data = resp.json()
        assert data["current"] == "2.0.0"
        assert data["latest"] == "9.9.9"
        assert data["has_update"] is True

    def test_same_version_no_update(self, real_app):
        """相同版本号 has_update=False。"""
        client, _ = real_app
        _reset_update_cache()
        release = {
            "tag_name": "v2.0.0",
            "html_url": "http://x",
            "body": "",
            "published_at": "",
        }
        with (
            patch("app.api.system.get_project_version", return_value="2.0.0"),
            patch("app.api.system.httpx.AsyncClient", _make_fake_client(release)),
        ):
            resp = client.get("/api/check-update")
        assert resp.status_code == 200
        data = resp.json()
        assert data["current"] == "2.0.0"
        assert data["latest"] == "2.0.0"
        assert data["has_update"] is False

    def test_lower_version_no_update(self, real_app):
        """更低版本号 has_update=False。"""
        client, _ = real_app
        _reset_update_cache()
        release = {
            "tag_name": "v1.0.0",
            "html_url": "http://x",
            "body": "",
            "published_at": "",
        }
        with (
            patch("app.api.system.get_project_version", return_value="2.0.0"),
            patch("app.api.system.httpx.AsyncClient", _make_fake_client(release)),
        ):
            resp = client.get("/api/check-update")
        assert resp.status_code == 200
        data = resp.json()
        assert data["current"] == "2.0.0"
        assert data["latest"] == "1.0.0"
        assert data["has_update"] is False
