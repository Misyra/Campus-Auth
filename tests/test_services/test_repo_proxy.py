"""仓库代理工具测试 — _normalize_repo_url / repo_get / repo_fetch_json

覆盖：GitHub URL 转换 / Gitee URL 转换 / 非转换 URL / 网络请求 / 类型校验 / 异步版本
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi import HTTPException

from app.utils.repo_proxy import (
    _normalize_repo_url,
    async_repo_fetch_json,
)

# =====================================================================
# _normalize_repo_url
# =====================================================================


class TestNormalizeRepoUrl:
    def test_github_blob_to_raw(self):
        url = "https://github.com/user/repo/blob/main/path/to/file.json"
        result = _normalize_repo_url(url)
        assert (
            result
            == "https://raw.githubusercontent.com/user/repo/main/path/to/file.json"
        )

    def test_gitee_blob_to_raw(self):
        url = "https://gitee.com/user/repo/blob/master/data.json"
        result = _normalize_repo_url(url)
        assert result == "https://gitee.com/user/repo/raw/master/data.json"

    def test_github_deep_path(self):
        url = "https://github.com/org/project/blob/dev/a/b/c/d.json"
        result = _normalize_repo_url(url)
        assert (
            result == "https://raw.githubusercontent.com/org/project/dev/a/b/c/d.json"
        )

    def test_non_github_url_unchanged(self):
        url = "https://example.com/data.json"
        assert _normalize_repo_url(url) == url

    def test_raw_github_url_unchanged(self):
        url = "https://raw.githubusercontent.com/user/repo/main/file.json"
        assert _normalize_repo_url(url) == url

    def test_http_github_url(self):
        url = "http://github.com/user/repo/blob/main/file.json"
        result = _normalize_repo_url(url)
        assert result == "https://raw.githubusercontent.com/user/repo/main/file.json"

    def test_empty_string(self):
        assert _normalize_repo_url("") == ""

    def test_github_no_blob_path(self):
        url = "https://github.com/user/repo"
        assert _normalize_repo_url(url) == url

    def test_github_tree_url_not_converted(self):
        url = "https://github.com/user/repo/tree/main"
        assert _normalize_repo_url(url) == url


# =====================================================================
# async_repo_fetch_json
# =====================================================================


def _make_mock_client(mock_response):
    """创建 mock httpx.AsyncClient 实例。"""
    mock_client = AsyncMock()
    mock_client.get.return_value = mock_response
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    return mock_client


class TestAsyncRepoFetchJson:
    @pytest.mark.asyncio
    @patch("app.utils.repo_proxy.httpx.AsyncClient")
    async def test_returns_list(self, MockClient):
        mock_resp = MagicMock()
        mock_resp.json.return_value = [{"id": 1}]
        MockClient.return_value = _make_mock_client(mock_resp)

        result = await async_repo_fetch_json("https://example.com/index.json", list, "索引")
        assert result == [{"id": 1}]

    @pytest.mark.asyncio
    @patch("app.utils.repo_proxy.httpx.AsyncClient")
    async def test_returns_dict(self, MockClient):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"name": "test"}
        MockClient.return_value = _make_mock_client(mock_resp)

        result = await async_repo_fetch_json("https://example.com/task.json", dict, "任务")
        assert result == {"name": "test"}

    @pytest.mark.asyncio
    @patch("app.utils.repo_proxy.httpx.AsyncClient")
    async def test_type_mismatch_raises_422(self, MockClient):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"not": "a list"}
        MockClient.return_value = _make_mock_client(mock_resp)

        with pytest.raises(HTTPException) as exc_info:
            await async_repo_fetch_json("https://example.com/data.json", list, "索引")
        assert exc_info.value.status_code == 422
        assert "格式不正确" in exc_info.value.detail

    @pytest.mark.asyncio
    @patch("app.utils.repo_proxy.httpx.AsyncClient")
    async def test_http_status_error_raises(self, MockClient):
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Not Found", request=MagicMock(), response=mock_resp
        )
        MockClient.return_value = _make_mock_client(mock_resp)

        with pytest.raises(HTTPException) as exc_info:
            await async_repo_fetch_json("https://example.com/data.json", dict, "任务")
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    @patch("app.utils.repo_proxy.httpx.AsyncClient")
    async def test_network_error_raises_502(self, MockClient):
        mock_client = AsyncMock()
        mock_client.get.side_effect = httpx.ConnectError("Connection refused")
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        MockClient.return_value = mock_client

        with pytest.raises(HTTPException) as exc_info:
            await async_repo_fetch_json("https://example.com/data.json", dict, "任务")
        assert exc_info.value.status_code == 502

    @pytest.mark.asyncio
    @patch("app.utils.repo_proxy.httpx.AsyncClient")
    async def test_normalizes_github_url(self, MockClient):
        mock_resp = MagicMock()
        mock_resp.json.return_value = [1, 2, 3]
        mock_client = _make_mock_client(mock_resp)
        MockClient.return_value = mock_client

        await async_repo_fetch_json(
            "https://github.com/user/repo/blob/main/index.json", list, "索引"
        )
        called_url = mock_client.get.call_args[0][0]
        assert (
            called_url == "https://raw.githubusercontent.com/user/repo/main/index.json"
        )
