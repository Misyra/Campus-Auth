"""项目统一启动入口（Web 控制台）。"""

import os
import sys
import threading
import time
import webbrowser
from pathlib import Path

from src.playwright_bootstrap import ensure_playwright_ready


def _open_browser_later(port: int) -> None:
    open_browser = os.getenv("JCU_AUTO_OPEN_BROWSER", "true").strip().lower()
    if open_browser not in {"1", "true", "yes", "on"}:
        return

    def _worker() -> None:
        time.sleep(1.2)
        webbrowser.open(f"http://127.0.0.1:{port}")

    threading.Thread(target=_worker, daemon=True).start()


if __name__ == "__main__":
    os.environ.setdefault("JCU_START_EXECUTABLE", str(Path(sys.executable).resolve()))
    ensure_playwright_ready(print)
    from backend.main import run
    from backend.main import _resolve_port

    _open_browser_later(_resolve_port())

    run()
