from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from PIL import Image


class TestSystemTrayLoadIcon:
    """测试 SystemTray._load_icon() 图标加载逻辑"""

    def test_as_uri_used_instead_of_str(self):
        """验证 icon_path.as_uri() 被调用而非 str(icon_path)"""
        from src.system_tray import SystemTray

        tray = SystemTray(port=50721)

        # cairosvg 是函数内导入的，需要通过 sys.modules 注入 mock
        mock_cairosvg = MagicMock()
        mock_cairosvg.svg2png.return_value = b"fake_png_data"

        with patch.object(Path, "exists", return_value=True):
            with patch.dict("sys.modules", {"cairosvg": mock_cairosvg}):
                with patch("src.system_tray.Image.open") as mock_open:
                    mock_open.return_value = MagicMock(spec=Image.Image)
                    with patch.object(Path, "as_uri") as mock_as_uri:
                        mock_as_uri.return_value = "file:///fake/path/tray-icon.svg"

                        tray._load_icon()

                        mock_as_uri.assert_called_once()
                        _, kwargs = mock_cairosvg.svg2png.call_args
                        assert kwargs["url"] == "file:///fake/path/tray-icon.svg"

    def test_cairosvg_import_fail_returns_default_icon(self):
        """cairosvg 导入失败时应返回默认 RGBA 图标"""
        from src.system_tray import SystemTray

        tray = SystemTray(port=50721)

        with patch("src.system_tray.Path.exists", return_value=True):
            with patch.dict("sys.modules", {"cairosvg": None}):
                with patch("builtins.__import__", side_effect=ImportError("no module named cairosvg")):
                    icon = tray._load_icon()
                    assert isinstance(icon, Image.Image)
                    assert icon.mode == "RGBA"
                    assert icon.size == (64, 64)

    def test_cairosvg_exception_returns_default_icon(self):
        """cairosvg.svg2png 抛出异常时应返回默认 RGBA 图标"""
        from src.system_tray import SystemTray

        tray = SystemTray(port=50721)
        mock_cairosvg = MagicMock()
        mock_cairosvg.svg2png.side_effect = Exception("svg parse error")

        with patch.object(Path, "exists", return_value=True):
            with patch.dict("sys.modules", {"cairosvg": mock_cairosvg}):
                icon = tray._load_icon()
                assert isinstance(icon, Image.Image)
                assert icon.mode == "RGBA"
                assert icon.size == (64, 64)


class TestSystemTrayStartStop:
    """测试 SystemTray 启动和停止流程"""

    def test_stop_without_start_no_error(self):
        """未启动时调用 stop() 不应引发异常"""
        from src.system_tray import SystemTray

        tray = SystemTray(port=50721)
        tray.stop()

    def test_start_stop_flow(self):
        """测试正常的 start / stop 流程"""
        from src.system_tray import SystemTray

        tray = SystemTray(port=50721, on_exit=lambda: None)
        mock_cairosvg = MagicMock()
        mock_cairosvg.svg2png.return_value = b"fake_png"

        with patch.object(Path, "exists", return_value=True):
            with patch.dict("sys.modules", {"cairosvg": mock_cairosvg}):
                with patch("src.system_tray.Image.open") as mock_open:
                    mock_open.return_value = MagicMock(spec=Image.Image)
                    with patch("src.system_tray.threading.Thread") as mock_thread:
                        mock_thread_instance = MagicMock()
                        mock_thread.return_value = mock_thread_instance

                        tray.start()
                        mock_thread.assert_called_once()
                        mock_thread_instance.start.assert_called_once()

                        tray.stop()
                        tray.stop()
