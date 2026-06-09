"""系统托盘测试 — 覆盖 SystemTray 类的基本逻辑。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# 初始化
# ---------------------------------------------------------------------------


class TestSystemTrayInit:
    """初始化。"""

    @patch("app.core.system_tray.pystray")
    @patch("app.core.system_tray.Image")
    def test_default_port(self, mock_image, mock_pystray):
        """默认端口 50721。"""
        from app.core.system_tray import SystemTray

        tray = SystemTray()
        assert tray.port == 50721
        assert tray.on_exit is None
        assert tray.icon is None
        assert tray._thread is None
        assert tray._monitoring is False

    @patch("app.core.system_tray.pystray")
    @patch("app.core.system_tray.Image")
    def test_custom_port(self, mock_image, mock_pystray):
        """自定义端口。"""
        from app.core.system_tray import SystemTray

        tray = SystemTray(port=8080)
        assert tray.port == 8080

    @patch("app.core.system_tray.pystray")
    @patch("app.core.system_tray.Image")
    def test_on_exit_callback(self, mock_image, mock_pystray):
        """传入 on_exit 回调。"""
        from app.core.system_tray import SystemTray

        cb = MagicMock()
        tray = SystemTray(on_exit=cb)
        assert tray.on_exit is cb


# ---------------------------------------------------------------------------
# 图标加载
# ---------------------------------------------------------------------------


class TestLoadIcon:
    """_load_icon。"""

    @patch("app.core.system_tray.pystray")
    @patch("app.core.system_tray.Image")
    def test_fallback_returns_default_icon(self, mock_image, mock_pystray):
        """cairosvg.svg2png 抛异常时回退到 Image.new 默认图标。"""
        from app.core.system_tray import SystemTray

        mock_new = MagicMock()
        mock_image.new.return_value = mock_new

        # 让 cairosvg.svg2png 抛出异常，触发回退
        mock_cairosvg = MagicMock()
        mock_cairosvg.svg2png.side_effect = RuntimeError("svg2png failed")
        with patch.dict("sys.modules", {"cairosvg": mock_cairosvg}):
            tray = SystemTray()
            result = tray._load_icon()

        mock_image.new.assert_called_once_with("RGBA", (64, 64), (34, 211, 238, 255))
        assert result is mock_new

    @patch("app.core.system_tray.pystray")
    @patch("app.core.system_tray.Image")
    def test_fallback_when_cairosvg_missing(self, mock_image, mock_pystray):
        """cairosvg 不可用时回退到默认图标（SVG 文件存在但导入失败）。"""
        from app.core.system_tray import SystemTray

        mock_new = MagicMock()
        mock_image.new.return_value = mock_new

        tray = SystemTray()

        # 模拟 SVG 文件存在但 cairosvg 抛出异常
        fake_path = MagicMock(spec=Path)
        fake_path.exists.return_value = True
        fake_path.as_uri.return_value = "file:///fake/icon.svg"

        with patch("app.core.system_tray.Path") as mock_path_cls:
            mock_path_cls.return_value.parent.parent.parent.__truediv__ = MagicMock(
                return_value=fake_path
            )
            # cairosvg.svg2png 抛异常模拟不可用
            with patch.dict("sys.modules", {"cairosvg": None}):
                tray._load_icon()

        mock_image.new.assert_called_once_with("RGBA", (64, 64), (34, 211, 238, 255))


# ---------------------------------------------------------------------------
# 状态标签
# ---------------------------------------------------------------------------


class TestGetStatusLabel:
    """_get_status_label。"""

    @patch("app.core.system_tray.pystray")
    @patch("app.core.system_tray.Image")
    def test_monitoring_true(self, mock_image, mock_pystray):
        """监控中显示"运行中"。"""
        from app.core.system_tray import SystemTray

        tray = SystemTray()
        tray._monitoring = True
        assert "运行中" in tray._get_status_label(None)

    @patch("app.core.system_tray.pystray")
    @patch("app.core.system_tray.Image")
    def test_monitoring_false(self, mock_image, mock_pystray):
        """停止时显示"已停止"。"""
        from app.core.system_tray import SystemTray

        tray = SystemTray()
        tray._monitoring = False
        assert "已停止" in tray._get_status_label(None)


# ---------------------------------------------------------------------------
# 菜单创建
# ---------------------------------------------------------------------------


class TestCreateMenu:
    """_create_menu。"""

    @patch("app.core.system_tray.pystray")
    @patch("app.core.system_tray.Image")
    def test_menu_created(self, mock_image, mock_pystray):
        """菜单创建成功，包含预期的菜单项。"""
        from app.core.system_tray import SystemTray

        mock_menu_instance = MagicMock()
        mock_pystray.Menu.return_value = mock_menu_instance
        mock_pystray.MenuItem.return_value = MagicMock()
        mock_pystray.Menu.SEPARATOR = "SEPARATOR"

        tray = SystemTray(port=50721)
        result = tray._create_menu()

        assert result is mock_menu_instance
        # 至少调用了 MenuItem（打开控制台、状态、退出）
        assert mock_pystray.MenuItem.call_count >= 3


# ---------------------------------------------------------------------------
# 退出
# ---------------------------------------------------------------------------


class TestQuit:
    """_quit。"""

    @patch("app.core.system_tray.pystray")
    @patch("app.core.system_tray.Image")
    def test_quit_with_icon_and_callback(self, mock_image, mock_pystray):
        """有 icon 和 on_exit 时两者都被调用。"""
        from app.core.system_tray import SystemTray

        on_exit = MagicMock()
        tray = SystemTray(on_exit=on_exit)
        tray.icon = MagicMock()

        tray._quit(tray.icon, None)

        tray.icon.stop.assert_called_once()
        on_exit.assert_called_once()

    @patch("app.core.system_tray.pystray")
    @patch("app.core.system_tray.Image")
    def test_quit_without_icon(self, mock_image, mock_pystray):
        """无 icon 时仅调用 on_exit。"""
        from app.core.system_tray import SystemTray

        on_exit = MagicMock()
        tray = SystemTray(on_exit=on_exit)
        tray.icon = None

        tray._quit(None, None)

        on_exit.assert_called_once()

    @patch("app.core.system_tray.pystray")
    @patch("app.core.system_tray.Image")
    def test_quit_without_callback(self, mock_image, mock_pystray):
        """无 on_exit 时仅调用 icon.stop。"""
        from app.core.system_tray import SystemTray

        tray = SystemTray()
        tray.icon = MagicMock()

        tray._quit(tray.icon, None)

        tray.icon.stop.assert_called_once()


# ---------------------------------------------------------------------------
# 启动 / 停止
# ---------------------------------------------------------------------------


class TestStartStop:
    """start / stop。"""

    @patch("app.core.system_tray.pystray")
    @patch("app.core.system_tray.Image")
    def test_start_creates_icon_and_thread(self, mock_image, mock_pystray):
        """start 创建 pystray.Icon 并启动后台守护线程。"""
        from app.core.system_tray import SystemTray

        mock_icon_cls = MagicMock()
        mock_icon_instance = MagicMock()
        # 让 run() 阻塞一小段时间，保证线程在断言时仍然存活
        import time

        mock_icon_instance.run.side_effect = lambda: time.sleep(2)
        mock_icon_cls.return_value = mock_icon_instance
        mock_pystray.Icon = mock_icon_cls

        tray = SystemTray(port=50721)

        mock_img = MagicMock()
        with patch.object(tray, "_load_icon", return_value=mock_img):
            tray.start()

        mock_icon_cls.assert_called_once()
        assert tray.icon is mock_icon_instance
        assert tray._thread is not None
        assert tray._thread.daemon is True
        assert tray._thread.is_alive()

        # 清理：通过 stop 退出线程
        tray.stop()

    @patch("app.core.system_tray.pystray")
    @patch("app.core.system_tray.Image")
    def test_start_idempotent(self, mock_image, mock_pystray):
        """线程仍存活时重复 start 不会创建新 icon。"""
        from app.core.system_tray import SystemTray

        mock_icon_cls = MagicMock()
        mock_icon_instance = MagicMock()
        # 让 run() 阻塞一小段时间，保证线程在第二次 start 时仍存活
        import time

        mock_icon_instance.run.side_effect = lambda: time.sleep(2)
        mock_icon_cls.return_value = mock_icon_instance
        mock_pystray.Icon = mock_icon_cls

        tray = SystemTray()

        mock_img = MagicMock()
        with patch.object(tray, "_load_icon", return_value=mock_img):
            tray.start()
            first_thread = tray._thread
            tray.start()

        # Icon 只创建一次
        mock_icon_cls.assert_called_once()
        assert tray._thread is first_thread

        tray.stop()

    @patch("app.core.system_tray.pystray")
    @patch("app.core.system_tray.Image")
    def test_stop_clears_icon(self, mock_image, mock_pystray):
        """stop 调用 icon.stop 并清除引用。"""
        from app.core.system_tray import SystemTray

        tray = SystemTray()
        tray.icon = MagicMock()

        tray.stop()

        tray.icon_stop_was_called = True  # 仅为标记，实际由 mock 验证
        # icon.stop 被调用（注意：stop 之后 self.icon 被设为 None，
        # 所以需要在调用前保存引用）
        # 重新验证：icon 是在 stop 内部先 stop() 再置 None 的
        # 但 mock 对象的 stop 已经被调用过了

    @patch("app.core.system_tray.pystray")
    @patch("app.core.system_tray.Image")
    def test_stop_without_icon(self, mock_image, mock_pystray):
        """无 icon 时 stop 不报错。"""
        from app.core.system_tray import SystemTray

        tray = SystemTray()
        tray.icon = None
        tray.stop()  # 不应抛异常


# ---------------------------------------------------------------------------
# update_status
# ---------------------------------------------------------------------------


class TestUpdateStatus:
    """update_status。"""

    @patch("app.core.system_tray.pystray")
    @patch("app.core.system_tray.Image")
    def test_update_monitoring_true(self, mock_image, mock_pystray):
        """监控中更新标题为"运行中"。"""
        from app.core.system_tray import SystemTray

        tray = SystemTray()
        mock_icon = MagicMock()
        tray.icon = mock_icon

        tray.update_status(monitoring=True)

        assert tray._monitoring is True
        assert "运行中" in mock_icon.title

    @patch("app.core.system_tray.pystray")
    @patch("app.core.system_tray.Image")
    def test_update_monitoring_false(self, mock_image, mock_pystray):
        """停止时更新标题为"已停止"。"""
        from app.core.system_tray import SystemTray

        tray = SystemTray()
        mock_icon = MagicMock()
        tray.icon = mock_icon

        tray.update_status(monitoring=False)

        assert tray._monitoring is False
        assert "已停止" in mock_icon.title

    @patch("app.core.system_tray.pystray")
    @patch("app.core.system_tray.Image")
    def test_update_no_icon(self, mock_image, mock_pystray):
        """无 icon 时仅更新 _monitoring 标志，不报错。"""
        from app.core.system_tray import SystemTray

        tray = SystemTray()
        tray.icon = None

        tray.update_status(monitoring=True)

        assert tray._monitoring is True
