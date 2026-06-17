"""test_api 共享 fixture — 消除各文件重复的 client 构建代码。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def api_client(tmp_path):
    """共享的测试客户端。

    提供：
    - 隔离的临时目录结构（frontend/, logs/, temp/）
    - 4 个 app.constants 常量的 patch
    - 已挂载 mock services 的 FastAPI TestClient

    Yields:
        (TestClient, MagicMock) — client 和 mock_services，
        测试可按需配置 mock_services 的各子服务返回值。
    """
    (tmp_path / "frontend").mkdir(exist_ok=True)
    (tmp_path / "frontend" / "index.html").write_text("<html></html>")
    (tmp_path / "logs").mkdir(exist_ok=True)
    (tmp_path / "temp").mkdir(exist_ok=True)

    with (
        patch("app.constants.PROJECT_ROOT", tmp_path),
        patch("app.constants.FRONTEND_DIR", tmp_path / "frontend"),
        patch("app.constants.LOGS_DIR", tmp_path / "logs"),
        patch("app.constants.TEMP_DIR", tmp_path / "temp"),
    ):
        from app.application import create_app

        mock_services = MagicMock()
        app = create_app()
        app.state.services = mock_services

        yield TestClient(app), mock_services
