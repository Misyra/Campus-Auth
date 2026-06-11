import threading
import webbrowser
from pathlib import Path

import pystray
from PIL import Image

from app.utils.logging import get_logger

logger = get_logger("system_tray", source="backend")


class SystemTray:
    def __init__(self, port: int = 50721, on_exit=None):
        self.port = port
        self.on_exit = on_exit
        self.icon = None
        self._thread = None
        self._monitoring = False

    def _load_icon(self) -> Image.Image:
        icon_path = Path(__file__).parent.parent.parent / "frontend" / "tray-icon.svg"
        if icon_path.exists():
            try:
                import io

                import cairosvg

                # 使用 as_uri() 生成跨平台文件 URI（Windows: file:///C:/...，POSIX: file:///...）
                png_data = cairosvg.svg2png(
                    url=icon_path.as_uri(), output_width=64, output_height=64
                )
                img = Image.open(io.BytesIO(png_data))
                logger.debug(
                    "SVG 图标加载成功: {}x{}, mode={}", img.width, img.height, img.mode
                )
                return img
            except Exception:
                logger.warning("SVG 图标加载失败，使用默认图标", exc_info=True)
        else:
            logger.warning("图标文件不存在: {}", icon_path)
        return Image.new("RGBA", (64, 64), (34, 211, 238, 255))

    def _get_status_label(self, item) -> str:
        return f"状态: {'运行中' if self._monitoring else '已停止'}"

    def _create_menu(self) -> pystray.Menu:
        return pystray.Menu(
            pystray.MenuItem(
                "打开控制台",
                lambda: webbrowser.open(f"http://127.0.0.1:{self.port}"),
                default=True,
            ),
            pystray.MenuItem(
                self._get_status_label,
                lambda: None,
                enabled=False,
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "退出",
                self._quit,
            ),
        )

    def _quit(self, icon, item):
        if self.icon:
            self.icon.stop()
        if self.on_exit:
            self.on_exit()

    def start(self):
        if self._thread and self._thread.is_alive():
            return

        self.icon = pystray.Icon(
            "campus_auth",
            self._load_icon(),
            "校园网认证助手",
            self._create_menu(),
        )
        self._thread = threading.Thread(target=self.icon.run, daemon=True)
        self._thread.start()

    def stop(self):
        if self.icon:
            self.icon.stop()
            self.icon = None

    def update_status(self, monitoring: bool):
        self._monitoring = monitoring
        icon = self.icon
        if not icon:
            return
        status_text = "运行中" if monitoring else "已停止"
        icon.title = f"Campus-Auth 校园网认证 - {status_text}"
