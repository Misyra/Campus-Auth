#!/usr/bin/env python3
"""跨平台桌面通知模块"""

from __future__ import annotations

import os
import platform
import subprocess

from src.utils.logging import get_logger

logger = get_logger("notify", side="BACKEND")

_SYSTEM = platform.system()


def send_notification(title: str, message: str, duration_ms: int = 5000) -> bool:
    """发送桌面通知（跨平台）

    Returns:
        True 如果通知发送成功
    """
    try:
        if _SYSTEM == "Windows":
            return _notify_windows(title, message, duration_ms)
        elif _SYSTEM == "Darwin":
            return _notify_macos(title, message)
        elif _SYSTEM == "Linux":
            return _notify_linux(title, message, duration_ms)
        else:
            logger.debug("不支持的操作系统: %s", _SYSTEM)
            return False
    except Exception as exc:
        logger.warning("发送桌面通知失败: %s", exc)
        return False


def _notify_windows(title: str, message: str, duration_ms: int) -> bool:
    """Windows: 使用 PowerShell Toast 通知"""
    # 转义特殊字符
    safe_title = title.replace("'", "''")
    safe_msg = message.replace("'", "''")
    duration_sec = max(1, duration_ms // 1000)

    ps_script = f'''
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null
$template = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
$textNodes = $template.GetElementsByTagName("text")
$textNodes.Item(0).AppendChild($template.CreateTextNode("{safe_title}")) > $null
$textNodes.Item(1).AppendChild($template.CreateTextNode("{safe_msg}")) > $null
$toast = [Windows.UI.Notifications.ToastNotification]::new($template)
$toast.ExpirationTime = [DateTimeOffset]::Now.AddSeconds({duration_sec})
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("Campus-Auth").Show($toast)
'''

    try:
        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy", "Bypass",
                "-Command", ps_script,
            ],
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
        )
        if result.returncode == 0:
            logger.debug("Windows 通知已发送: %s", title)
            return True
    except Exception:
        pass

    # PowerShell 方案失败时回退到 msg（仅显示在命令行）
    try:
        subprocess.run(
            ["msg", os.environ.get("USERNAME", "*"), f"{title}: {message}"],
            capture_output=True,
            timeout=5,
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
        )
        return True
    except Exception:
        pass

    return False


def _notify_macos(title: str, message: str) -> bool:
    """macOS: 使用 osascript 发送通知"""
    safe_title = title.replace('"', '\\"')
    safe_msg = message.replace('"', '\\"')
    script = f'display notification "{safe_msg}" with title "{safe_title}"'
    result = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True, text=True, timeout=5,
    )
    return result.returncode == 0


def _notify_linux(title: str, message: str, duration_ms: int) -> bool:
    """Linux: 使用 notify-send"""
    duration_sec = max(1, duration_ms // 1000) * 1000
    result = subprocess.run(
        ["notify-send", title, message, "-t", str(duration_sec), "-a", "Campus-Auth"],
        capture_output=True, text=True, timeout=5,
    )
    return result.returncode == 0
