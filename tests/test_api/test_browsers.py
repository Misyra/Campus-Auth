"""浏览器 API 端点测试。"""

from unittest.mock import MagicMock

from app.schemas import MonitorStatusResponse, RuntimeConfig


def _setup_browser_mocks(mock_services):
    """配置 engine 和 profile_service mock 返回值。"""
    mock_services.engine.get_config.return_value = RuntimeConfig()
    mock_services.engine.get_status.return_value = MonitorStatusResponse(
        monitoring=False,
        network_check_count=0,
        login_attempt_count=0,
        last_check_time=None,
        runtime_seconds=0,
    )
    mock_services.engine.list_logs.return_value = []


def test_get_browsers_returns_200(api_client):
    """GET /api/browsers 应返回 200。"""
    test_client, mock_services = api_client
    _setup_browser_mocks(mock_services)
    mock_profile = MagicMock()
    mock_profile_data = MagicMock()
    mock_profile_data.config.browser.browser_channel = "playwright"
    mock_profile.load.return_value = mock_profile_data
    mock_services.profile_service = mock_profile

    response = test_client.get("/api/browsers")
    assert response.status_code == 200


def test_get_browsers_structure(api_client):
    """响应应包含 browsers 列表和 current 字段。"""
    test_client, mock_services = api_client
    _setup_browser_mocks(mock_services)
    mock_profile = MagicMock()
    mock_profile_data = MagicMock()
    mock_profile_data.config.browser.browser_channel = "playwright"
    mock_profile.load.return_value = mock_profile_data
    mock_services.profile_service = mock_profile

    response = test_client.get("/api/browsers")
    data = response.json()
    assert "browsers" in data
    assert "current" in data
    assert isinstance(data["browsers"], list)


def test_get_browsers_contains_all_channels(api_client):
    """browsers 列表应包含所有 5 种选项。"""
    test_client, mock_services = api_client
    _setup_browser_mocks(mock_services)
    mock_profile = MagicMock()
    mock_profile_data = MagicMock()
    mock_profile_data.config.browser.browser_channel = "playwright"
    mock_profile.load.return_value = mock_profile_data
    mock_services.profile_service = mock_profile

    response = test_client.get("/api/browsers")
    data = response.json()
    channels = [b["channel"] for b in data["browsers"]]
    assert "playwright" in channels
    assert "msedge" in channels
    assert "chrome" in channels
    assert "firefox" in channels
    assert "custom" in channels
    assert len(channels) == 5


def test_get_browsers_current_field(api_client):
    """current 字段应返回当前配置的 browser_channel。"""
    test_client, mock_services = api_client
    _setup_browser_mocks(mock_services)
    mock_profile = MagicMock()
    mock_profile_data = MagicMock()
    mock_profile_data.config.browser.browser_channel = "playwright"
    mock_profile.load.return_value = mock_profile_data
    mock_services.profile_service = mock_profile

    response = test_client.get("/api/browsers")
    data = response.json()
    assert data["current"] in ["playwright", "msedge", "chrome", "firefox", "custom"]


def test_get_browsers_item_structure(api_client):
    """每个浏览器项应包含必要字段。"""
    test_client, mock_services = api_client
    _setup_browser_mocks(mock_services)
    mock_profile = MagicMock()
    mock_profile_data = MagicMock()
    mock_profile_data.config.browser.browser_channel = "playwright"
    mock_profile.load.return_value = mock_profile_data
    mock_services.profile_service = mock_profile

    response = test_client.get("/api/browsers")
    data = response.json()
    for b in data["browsers"]:
        assert "channel" in b
        assert "name" in b
        assert "icon" in b
        assert "installed" in b
        assert "needs_download" in b
        assert "description" in b
