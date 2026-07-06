"""测试 system.py 更新检查缓存行为。"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest


class TestUpdateCache:
    """验证 check_update 中全局缓存行为。"""

    @pytest.mark.asyncio
    async def test_cache_hit_returns_without_network(self):
        """缓存命中时不应发起网络请求。"""
        import time as time_mod

        import app.api.system as sys_mod

        # 设置有效缓存
        sys_mod._update_cache = {
            "latest": "v99.0.0",
            "has_update": True,
            "url": "",
            "body": "",
            "published_at": "",
        }
        sys_mod._update_cache_time = time_mod.monotonic()

        call_count = 0

        async def mock_get(self, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            return MagicMock()

        with patch("httpx.AsyncClient.get", mock_get):
            result = await sys_mod.check_update()

        assert call_count == 0
        assert result.latest == "v99.0.0"

    @pytest.mark.asyncio
    async def test_cache_expired_triggers_network(self):
        """缓存过期时应发起网络请求并更新缓存。"""
        import time as time_mod

        import app.api.system as sys_mod

        # 设置过期缓存
        sys_mod._update_cache = {"latest": "v1.0.0", "has_update": False}
        sys_mod._update_cache_time = (
            time_mod.monotonic() - sys_mod._UPDATE_CACHE_TTL - 100
        )

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "tag_name": "v99.0.0",
            "html_url": "https://example.com",
            "body": "",
            "published_at": "2026-01-01T00:00:00Z",
        }

        async def mock_get(self, *args, **kwargs):
            return mock_resp

        with patch("httpx.AsyncClient.get", mock_get):
            result = await sys_mod.check_update()

        assert result.latest == "99.0.0"
        assert sys_mod._update_cache["latest"] == "99.0.0"

    @pytest.mark.asyncio
    async def test_concurrent_requests_consistent_cache(self):
        """并发请求场景下缓存状态应保持一致（无数据损坏）。"""
        import app.api.system as sys_mod

        # 重置缓存
        sys_mod._update_cache = None
        sys_mod._update_cache_time = 0

        call_count = 0

        async def mock_get(self, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            await asyncio.sleep(0.05)
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.raise_for_status = MagicMock()
            mock_resp.json.return_value = {
                "tag_name": "v99.0.0",
                "html_url": "https://example.com",
                "body": "",
                "published_at": "2026-01-01T00:00:00Z",
            }
            return mock_resp

        with patch("httpx.AsyncClient.get", mock_get):
            results = await asyncio.gather(*[sys_mod.check_update() for _ in range(5)])

        # 所有请求都应返回有效结果
        assert all(r.current for r in results)
        assert all(r.latest for r in results)
        # 缓存应被正确更新（最后一个请求的值）
        assert sys_mod._update_cache is not None
        assert sys_mod._update_cache["latest"] == "99.0.0"
