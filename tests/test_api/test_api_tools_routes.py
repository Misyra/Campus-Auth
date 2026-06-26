"""工具路由 API 测试 — 覆盖纯函数、常量和 API 端点。"""

from __future__ import annotations

import io
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

from app.api.tools import (
    ALLOWED_EXTENSIONS,
    MAX_FILE_SIZE,
    _cleanup_old_backgrounds,
)
from app.schemas import FetchUrlRequest


@pytest.fixture
def client(tmp_path):
    """创建测试客户端，使用临时背景目录。"""
    bg_dir = tmp_path / "frontend" / "background"
    bg_dir.mkdir(parents=True, exist_ok=True)
    tools_dir = tmp_path / "res" / "tools"
    tools_dir.mkdir(parents=True, exist_ok=True)
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir(exist_ok=True)

    (tmp_path / "frontend" / "index.html").write_text("<html></html>")
    (tmp_path / "logs").mkdir(exist_ok=True)
    (tmp_path / "temp").mkdir(exist_ok=True)

    with (
        patch("app.api.tools.BG_DIR", bg_dir),
        patch("app.api.tools.PROJECT_ROOT", tmp_path),
        patch("app.constants.PROJECT_ROOT", tmp_path),
        patch("app.constants.FRONTEND_DIR", tmp_path / "frontend"),
        patch("app.constants.LOGS_DIR", tmp_path / "logs"),
        patch("app.constants.TEMP_DIR", tmp_path / "temp"),
    ):
        from app.application import create_app

        mock_services = MagicMock()
        app = create_app()
        app.state.services = mock_services

        test_client = TestClient(app)
        yield test_client, bg_dir, tmp_path


# ── 上传背景图片 ──


class TestUploadBackground:
    """POST /api/background/upload"""

    def test_upload_png_success(self, client):
        """上传 PNG 文件成功。"""
        test_client, bg_dir, _ = client
        # 创建一个最小的 PNG 文件头
        png_data = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        resp = test_client.post(
            "/api/background/upload",
            files={"file": ("bg.png", io.BytesIO(png_data), "image/png")},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        data = body["data"]
        assert "filename" in data
        assert data["url"].startswith("/api/background/")
        assert data["filename"].endswith(".png")

    def test_upload_unsupported_extension(self, client):
        """上传不支持的文件格式返回 400。"""
        test_client, _, _ = client
        resp = test_client.post(
            "/api/background/upload",
            files={"file": ("test.bmp", io.BytesIO(b"data"), "image/bmp")},
        )
        assert resp.status_code == 400

    def test_upload_file_too_large(self, client):
        """上传超过 5MB 的文件返回 400。"""
        test_client, _, _ = client
        large_data = b"\x00" * (5 * 1024 * 1024 + 1)
        resp = test_client.post(
            "/api/background/upload",
            files={"file": ("big.jpg", io.BytesIO(large_data), "image/jpeg")},
        )
        assert resp.status_code == 400

    def test_upload_cleans_old_backgrounds(self, client):
        """上传新背景时清理旧文件。"""
        test_client, bg_dir, _ = client
        # 预先放置旧文件
        (bg_dir / "old_bg.png").write_bytes(b"old")
        png_data = b"\x89PNG\r\n\x1a\n" + b"\x00" * 10
        resp = test_client.post(
            "/api/background/upload",
            files={"file": ("new.png", io.BytesIO(png_data), "image/png")},
        )
        assert resp.status_code == 200
        assert not (bg_dir / "old_bg.png").exists()


# ── 获取背景图片 ──


class TestGetBackground:
    """GET /api/background/{filename}"""

    def test_get_existing_background(self, client):
        """获取存在的背景图片。"""
        test_client, bg_dir, _ = client
        (bg_dir / "test.jpg").write_bytes(b"fake image data")
        resp = test_client.get("/api/background/test.jpg")
        assert resp.status_code == 200

    def test_get_nonexistent_background(self, client):
        """获取不存在的背景图片返回 404。"""
        test_client, _, _ = client
        resp = test_client.get("/api/background/nonexistent.jpg")
        assert resp.status_code == 404

    def test_path_traversal_blocked(self, client):
        """路径穿越被阻止。"""
        test_client, _, _ = client
        resp = test_client.get("/api/background/../../etc/passwd")
        # Path("...").name 会提取最后一段，导致文件不存在 → 404
        assert resp.status_code in (400, 404)


# ── 删除背景图片 ──


class TestDeleteBackground:
    """DELETE /api/background/{filename}"""

    def test_delete_existing_background(self, client):
        """删除存在的背景图片。"""
        test_client, bg_dir, _ = client
        (bg_dir / "to_delete.jpg").write_bytes(b"data")
        resp = test_client.delete("/api/background/to_delete.jpg")
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        assert not (bg_dir / "to_delete.jpg").exists()

    def test_delete_nonexistent_background(self, client):
        """删除不存在的背景图片返回 404。"""
        test_client, _, _ = client
        resp = test_client.delete("/api/background/no_such.jpg")
        assert resp.status_code == 404


# ── 下载任务录制器脚本 ──


class TestDownloadTaskRecorder:
    """GET /api/tools/task-recorder.user.js"""

    def test_download_when_exists(self, client):
        """脚本存在时成功下载。"""
        test_client, _, tmp_path = client
        script_path = tmp_path / "res" / "tools" / "task-recorder.user.js"
        script_path.write_text(
            "// ==UserScript==\nconsole.log('test');", encoding="utf-8"
        )
        resp = test_client.get("/api/tools/task-recorder.user.js")
        assert resp.status_code == 200
        assert "UserScript" in resp.text

    def test_download_when_not_exists(self, client):
        """脚本不存在时返回 404。"""
        test_client, _, tmp_path = client
        # 确保 tools 目录为空
        tools_dir = tmp_path / "res" / "tools"
        for f in tools_dir.iterdir():
            f.unlink()
        resp = test_client.get("/api/tools/task-recorder.user.js")
        assert resp.status_code == 404


# ── 常量 ──


class TestConstants:
    """常量定义。"""

    def test_allowed_extensions(self):
        """允许的扩展名。"""
        assert ".jpg" in ALLOWED_EXTENSIONS
        assert ".jpeg" in ALLOWED_EXTENSIONS
        assert ".png" in ALLOWED_EXTENSIONS
        assert ".gif" in ALLOWED_EXTENSIONS
        assert ".webp" in ALLOWED_EXTENSIONS
        assert ".exe" not in ALLOWED_EXTENSIONS

    def test_max_file_size(self):
        """最大文件大小 5MB。"""
        assert MAX_FILE_SIZE == 5 * 1024 * 1024


# ── _cleanup_old_backgrounds 纯函数 ──


class TestCleanupOldBackgrounds:
    """旧背景清理。"""

    def test_removes_other_files(self, tmp_path):
        """删除其他文件。"""
        (tmp_path / "old.jpg").write_bytes(b"old")
        (tmp_path / "keep.jpg").write_bytes(b"keep")

        with patch("app.api.tools.BG_DIR", tmp_path):
            _cleanup_old_backgrounds("keep.jpg")

        assert not (tmp_path / "old.jpg").exists()
        assert (tmp_path / "keep.jpg").exists()

    def test_no_files(self, tmp_path):
        """无文件时不抛异常。"""
        with patch("app.api.tools.BG_DIR", tmp_path):
            _cleanup_old_backgrounds("keep.jpg")

    def test_empty_exclude(self, tmp_path):
        """空排除名删除所有。"""
        (tmp_path / "test.jpg").write_bytes(b"test")

        with patch("app.api.tools.BG_DIR", tmp_path):
            _cleanup_old_backgrounds("")

        assert not (tmp_path / "test.jpg").exists()


# ── 路径安全 ──


class TestPathSafety:
    """路径安全校验。"""

    def test_path_traversal_detection(self):
        """路径穿越检测。"""
        filename = "../../etc/passwd"
        safe_name = Path(filename).name
        assert safe_name == "passwd"
        assert safe_name != filename

    def test_normal_filename(self):
        """正常文件名。"""
        filename = "test.jpg"
        safe_name = Path(filename).name
        assert safe_name == filename


# ── 远程 URL 下载 Content-Length 检查 ──


class TestFetchUrlContentLength:
    """POST /api/background/fetch-url — Content-Length 预检查。

    通过直接调用 fetch_background_url 函数来避免 ASGI transport 的 mock 问题。
    """

    @staticmethod
    def _mock_response(content_length: str | None, body: bytes = b"") -> httpx.Response:
        """构造模拟的 httpx.Response。"""
        headers = {}
        if content_length is not None:
            headers["content-length"] = content_length
        headers["content-type"] = "image/png"
        request = httpx.Request("GET", "https://example.com/img.png")
        return httpx.Response(
            status_code=200,
            headers=headers,
            content=body,
            request=request,
        )

    @staticmethod
    def _mock_stream_context(mock_resp):
        """构造模拟的 stream 异步上下文管理器。"""
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=mock_resp)
        cm.__aexit__ = AsyncMock(return_value=False)
        return cm

    def _mock_stream_response(self, content_length: str | None, body: bytes = b""):
        """构造支持 aiter_bytes 的 mock 响应和 stream 上下文管理器。"""
        mock_resp = AsyncMock()
        headers = {"content-type": "image/png"}
        if content_length is not None:
            headers["content-length"] = content_length
        mock_resp.headers = headers
        mock_resp.raise_for_status = MagicMock()

        async def _aiter_bytes(chunk_size=8192):
            for i in range(0, len(body), chunk_size):
                yield body[i : i + chunk_size]

        mock_resp.aiter_bytes = _aiter_bytes
        return self._mock_stream_context(mock_resp)

    @pytest.mark.asyncio
    async def test_rejects_when_content_length_exceeds_limit(self, tmp_path):
        """Content-Length 超过限制时拒绝，不加载响应体。"""
        bg_dir = tmp_path / "frontend" / "background"
        bg_dir.mkdir(parents=True, exist_ok=True)

        huge_size = str(10 * 1024 * 1024)  # 10MB
        stream_cm = self._mock_stream_response(huge_size)

        mock_client = AsyncMock()
        mock_client.stream = MagicMock(return_value=stream_cm)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("app.api.tools.validate_url"),
            patch("app.api.tools.httpx.AsyncClient", return_value=mock_client),
            patch("app.api.tools.BG_DIR", bg_dir),
        ):
            from app.api.tools import fetch_background_url

            with pytest.raises(Exception) as exc_info:
                await fetch_background_url(FetchUrlRequest(url="https://example.com/big.png"))
            assert exc_info.value.status_code == 400
            assert "5MB" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_accepts_when_content_length_within_limit(self, tmp_path):
        """Content-Length 在限制内时正常处理。"""
        bg_dir = tmp_path / "frontend" / "background"
        bg_dir.mkdir(parents=True, exist_ok=True)

        small_body = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        stream_cm = self._mock_stream_response(str(len(small_body)), small_body)

        mock_client = AsyncMock()
        mock_client.stream = MagicMock(return_value=stream_cm)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("app.api.tools.validate_url"),
            patch("app.api.tools.httpx.AsyncClient", return_value=mock_client),
            patch("app.api.tools.BG_DIR", bg_dir),
            patch("app.api.tools._cleanup_old_backgrounds"),
        ):
            from app.api.tools import fetch_background_url

            result = await fetch_background_url(FetchUrlRequest(url="https://example.com/small.png"))
            assert result.success is True
            assert "filename" in result.data
            assert result.data["url"].startswith("/api/background/")

    @pytest.mark.asyncio
    async def test_falls_back_to_body_size_when_no_content_length(self, tmp_path):
        """无 Content-Length 头时回退到响应体大小检查。"""
        bg_dir = tmp_path / "frontend" / "background"
        bg_dir.mkdir(parents=True, exist_ok=True)

        small_body = b"\x89PNG\r\n\x1a\n" + b"\x00" * 10
        stream_cm = self._mock_stream_response(None, small_body)

        mock_client = AsyncMock()
        mock_client.stream = MagicMock(return_value=stream_cm)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("app.api.tools.validate_url"),
            patch("app.api.tools.httpx.AsyncClient", return_value=mock_client),
            patch("app.api.tools.BG_DIR", bg_dir),
            patch("app.api.tools._cleanup_old_backgrounds"),
        ):
            from app.api.tools import fetch_background_url

            result = await fetch_background_url(FetchUrlRequest(url="https://example.com/no-header.png"))
            assert result.success is True
            assert "filename" in result.data
