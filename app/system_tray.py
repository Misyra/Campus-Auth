import threading
import webbrowser
from pathlib import Path

from app.utils.logging import get_logger

logger = get_logger("system_tray", source="backend")


class SystemTray:
    def __init__(self, port: int = 50721, on_exit=None, on_open_console=None):
        self.port = port
        self.on_exit = on_exit
        self.on_open_console = on_open_console
        self.icon = None
        self._thread = None
        self._monitoring = False
        self._pystray = None
        self._Image = None

    def _load_icon(self):
        """加载托盘图标（需要先调用 start() 初始化模块）。"""
        icon_path = Path(__file__).parent.parent / "frontend" / "tray-icon.svg"
        if icon_path.exists():
            try:
                import io

                import cairosvg

                # 使用 as_uri() 生成跨平台文件 URI（Windows: file:///C:/...，POSIX: file:///...）
                png_data = cairosvg.svg2png(
                    url=icon_path.as_uri(), output_width=64, output_height=64
                )
                img = self._Image.open(io.BytesIO(png_data))
                logger.debug(
                    "SVG 图标加载成功: {}x{}, mode={}", img.width, img.height, img.mode
                )
                return img
            except Exception:
                logger.warning("SVG 图标加载失败，使用默认图标", exc_info=True)
        else:
            logger.warning("加载图标失败: 文件不存在: {}", icon_path)
        return self._Image.new("RGBA", (64, 64), (34, 211, 238, 255))

    def _get_status_label(self, item) -> str:
        return f"状态: {'运行中' if self._monitoring else '已停止'}"

    def _create_menu(self):
        """创建托盘菜单（需要先调用 start() 初始化模块）。"""
        def _open_console(icon, item):
            if self.on_open_console:
                self.on_open_console()
            else:
                webbrowser.open(f"http://127.0.0.1:{self.port}")

        return self._pystray.Menu(
            self._pystray.MenuItem(
                "打开控制台",
                _open_console,
                default=True,
            ),
            self._pystray.MenuItem(
                self._get_status_label,
                lambda: None,
                enabled=False,
            ),
            self._pystray.Menu.SEPARATOR,
            self._pystray.MenuItem(
                "退出",
                self._quit,
            ),
        )

    def _quit(self, icon, item):
        logger.info("用户通过托盘菜单退出")
        if self.icon:
            self.icon.stop()
        if self.on_exit:
            self.on_exit()

    def start(self):
        if self._thread and self._thread.is_alive():
            return

        # 延迟导入 pystray 和 PIL（只在实际启用托盘时才加载）
        if self._pystray is None:
            import pystray

            self._pystray = pystray
        if self._Image is None:
            from PIL import Image

            self._Image = Image

        self.icon = self._pystray.Icon(
            "campus_auth",
            self._load_icon(),
            "校园网认证助手",
            self._create_menu(),
        )
        self._thread = threading.Thread(target=self.icon.run, daemon=True)
        self._thread.start()
        logger.info("启动系统托盘成功")

    def stop(self):
        if self.icon:
            self.icon.stop()
            self.icon = None
        logger.info("停止系统托盘成功")

    def update_status(self, monitoring: bool):
        self._monitoring = monitoring
        logger.debug("监控状态切换: {}", monitoring)
        icon = self.icon
        if not icon:
            return
        status_text = "运行中" if monitoring else "已停止"
        icon.title = f"Campus-Auth 校园网认证 - {status_text}"
