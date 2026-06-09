"""仓库代理工具测试 — normalize_repo_url / repo_get / repo_fetch_json

覆盖：GitHub URL 转换 / Gitee URL 转换 / 非转换 URL / 网络请求 / 类型校验 / 异常处理
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest
from fastapi import HTTPException

from app.utils.repo_proxy import normalize_repo_url, repo_fetch_json, repo_get

# =====================================================================
# normalize_repo_url
# =====================================================================


class TestNormalizeRepoUrl:
    def test_github_blob_to_raw(self):
        url = "https://github.com/user/repo/blob/main/path/to/file.json"
        result = normalize_repo_url(url)
        assert (
            result
            == "https://raw.githubusercontent.com/user/repo/main/path/to/file.json"
        )

    def test_gitee_blob_to_raw(self):
        url = "https://gitee.com/user/repo/blob/master/data.json"
        result = normalize_repo_url(url)
        assert result == "https://gitee.com/user/repo/raw/master/data.json"

    def test_github_deep_path(self):
        url = "https://github.com/org/project/blob/dev/a/b/c/d.json"
        result = normalize_repo_url(url)
        assert (
            result == "https://raw.githubusercontent.com/org/project/dev/a/b/c/d.json"
        )

    def test_non_github_url_unchanged(self):
        url = "https://example.com/data.json"
        assert normalize_repo_url(url) == url

    def test_raw_github_url_unchanged(self):
        url = "https://raw.githubusercontent.com/user/repo/main/file.json"
        assert normalize_repo_url(url) == url

    def test_http_github_url(self):
        url = "http://github.com/user/repo/blob/main/file.json"
        result = normalize_repo_url(url)
        assert result == "https://raw.githubusercontent.com/user/repo/main/file.json"

    def test_empty_string(self):
        assert normalize_repo_url("") == ""

    def test_github_no_blob_path(self):
        url = "https://github.com/user/repo"
        assert normalize_repo_url(url) == url

    def test_github_tree_url_not_converted(self):
        url = "https://github.com/user/repo/tree/main"
        assert normalize_repo_url(url) == url


# =====================================================================
# repo_get
# =====================================================================


class TestRepoGet:
    @patch("app.utils.repo_proxy.httpx.Client")
    def test_returns_response(self, MockClient):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_client_instance = MagicMock()
        mock_client_instance.get.return_value = mock_response
        mock_client_instance.__enter__ = MagicMock(return_value=mock_client_instance)
        mock_client_instance.__exit__ = MagicMock(return_value=False)
        MockClient.return_value = mock_client_instance

        resp = repo_get("https://example.com/data.json")
        assert resp.status_code == 200
        mock_client_instance.get.assert_called_once()

    @patch("app.utils.repo_proxy.httpx.Client")
    def test_sends_user_agent(self, MockClient):
        mock_response = MagicMock()
        mock_client_instance = MagicMock()
        mock_client_instance.get.return_value = mock_response
        mock_client_instance.__enter__ = MagicMock(return_value=mock_client_instance)
        mock_client_instance.__exit__ = MagicMock(return_value=False)
        MockClient.return_value = mock_client_instance

        repo_get("https://example.com/data.json")
        call_kwargs = mock_client_instance.get.call_args
        assert call_kwargs[1]["headers"]["User-Agent"] == "Campus-Auth"

    @patch("app.utils.repo_proxy.httpx.Client")
    def test_passes_proxy(self, MockClient):
        mock_response = MagicMock()
        mock_client_instance = MagicMock()
        mock_client_instance.get.return_value = mock_response
        mock_client_instance.__enter__ = MagicMock(return_value=mock_client_instance)
        mock_client_instance.__exit__ = MagicMock(return_value=False)
        MockClient.return_value = mock_client_instance

        repo_get("https://example.com/data.json", proxy="http://proxy:8080")
        MockClient.assert_called_once()
        call_kwargs = MockClient.call_args[1]
        assert call_kwargs["proxy"] == "http://proxy:8080"

    @patch("app.utils.repo_proxy.httpx.Client")
    def test_empty_proxy_uses_none(self, MockClient):
        mock_response = MagicMock()
        mock_client_instance = MagicMock()
        mock_client_instance.get.return_value = mock_response
        mock_client_instance.__enter__ = MagicMock(return_value=mock_client_instance)
        mock_client_instance.__exit__ = MagicMock(return_value=False)
        MockClient.return_value = mock_client_instance

        repo_get("https://example.com/data.json", proxy="")
        call_kwargs = MockClient.call_args[1]
        assert call_kwargs["proxy"] is None


# =====================================================================
# repo_fetch_json
# =====================================================================


class TestRepoFetchJson:
    @patch("app.utils.repo_proxy.repo_get")
    def test_returns_list(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = [{"id": 1}]
        mock_get.return_value = mock_resp

        result = repo_fetch_json("https://example.com/index.json", list, "索引")
        assert result == [{"id": 1}]

    @patch("app.utils.repo_proxy.repo_get")
    def test_returns_dict(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"name": "test"}
        mock_get.return_value = mock_resp

        result = repo_fetch_json("https://example.com/task.json", dict, "任务")
        assert result == {"name": "test"}

    @patch("app.utils.repo_proxy.repo_get")
    def test_type_mismatch_raises_422(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"not": "a list"}
        mock_get.return_value = mock_resp

        with pytest.raises(HTTPException) as exc_info:
            repo_fetch_json("https://example.com/data.json", list, "索引")
        assert exc_info.value.status_code == 422
        assert "格式不正确" in exc_info.value.detail

    @patch("app.utils.repo_proxy.repo_get")
    def test_http_status_error_raises(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_get.side_effect = httpx.HTTPStatusError(
            "Not Found", request=MagicMock(), response=mock_resp
        )

        with pytest.raises(HTTPException) as exc_info:
            repo_fetch_json("https://example.com/data.json", dict, "任务")
        assert exc_info.value.status_code == 404

    @patch("app.utils.repo_proxy.repo_get")
    def test_network_error_raises_502(self, mock_get):
        mock_get.side_effect = httpx.ConnectError("Connection refused")

        with pytest.raises(HTTPException) as exc_info:
            repo_fetch_json("https://example.com/data.json", dict, "任务")
        assert exc_info.value.status_code == 502

    @patch("app.utils.repo_proxy.repo_get")
    def test_normalizes_github_url(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = [1, 2, 3]
        mock_get.return_value = mock_resp

        repo_fetch_json(
            "https://github.com/user/repo/blob/main/index.json", list, "索引"
        )
        called_url = mock_get.call_args[0][0]
        assert (
            called_url == "https://raw.githubusercontent.com/user/repo/main/index.json"
        )
