"""安装 Playwright Chromium API 路由。"""

import subprocess
import sys

from fastapi import APIRouter

router = APIRouter()


@router.post("/api/browsers/install-playwright")
async def install_playwright_chromium():
    """安装 Playwright Chromium 浏览器。"""
    try:
        result = subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            capture_output=True,
            text=True,
            timeout=300,  # 5 分钟超时
        )
        if result.returncode == 0:
            return {"success": True, "message": "Playwright Chromium 安装成功"}
        else:
            return {"success": False, "message": result.stderr or result.stdout}
    except subprocess.TimeoutExpired:
        return {"success": False, "message": "安装超时，请重试"}
    except Exception as e:
        return {"success": False, "message": str(e)}
