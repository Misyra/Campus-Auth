from __future__ import annotations

import os
import platform
import subprocess
import sys
from pathlib import Path


class AutoStartService:
    """管理开机自启动（按平台实现）。"""

    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.platform_name = platform.system().lower()
        self.service_name = "campus-auth"

    def _start_command(self) -> str:
        python_exe = self.project_root / "environment" / "python" / "python.exe"
        app_entry = self.project_root / "app.py"
        if python_exe.exists():
            return f'"{python_exe}" "{app_entry}"'
        packaged_executable = os.getenv("Campus-Auth_START_EXECUTABLE", "").strip()
        if packaged_executable:
            return f'"{packaged_executable}"'
        runtime_python = Path(sys.executable).resolve()
        if runtime_python.exists():
            return f'"{runtime_python}" "{app_entry}"'
        return f'python "{app_entry}"'

    def _run(self, cmd: list[str]) -> tuple[bool, str]:
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
            if proc.returncode == 0:
                return True, (proc.stdout or "").strip()
            return False, (proc.stderr or proc.stdout or "").strip()
        except Exception as exc:
            return False, str(exc)

    def _mac_plist_path(self) -> Path:
        return Path.home() / "Library" / "LaunchAgents" / f"{self.service_name}.plist"

    def _linux_service_path(self) -> Path:
        return (
            Path.home()
            / ".config"
            / "systemd"
            / "user"
            / f"{self.service_name}.service"
        )

    def _windows_startup_vbs(self) -> Path:
        appdata = os.getenv("APPDATA", "")
        return (
            Path(appdata)
            / "Microsoft"
            / "Windows"
            / "Start Menu"
            / "Programs"
            / "Startup"
            / f"{self.service_name}.vbs"
        )

    def status(self) -> dict[str, str | bool]:
        if self.platform_name == "darwin":
            target = self._mac_plist_path()
            return {
                "platform": "macOS",
                "enabled": target.exists(),
                "method": "launchd",
                "location": str(target),
            }

        if self.platform_name == "linux":
            target = self._linux_service_path()
            return {
                "platform": "Linux",
                "enabled": target.exists(),
                "method": "systemd --user",
                "location": str(target),
            }

        if self.platform_name.startswith("win"):
            target = self._windows_startup_vbs()
            return {
                "platform": "Windows",
                "enabled": target.exists(),
                "method": "VBScript startup",
                "location": str(target),
            }

        return {
            "platform": platform.system(),
            "enabled": False,
            "method": "unsupported",
            "location": "",
        }

    def enable(self) -> tuple[bool, str]:
        if self.platform_name == "darwin":
            return self._enable_macos()
        if self.platform_name == "linux":
            return self._enable_linux()
        if self.platform_name.startswith("win"):
            return self._enable_windows()
        return False, "当前平台不支持自动配置开机自启动"

    def disable(self) -> tuple[bool, str]:
        if self.platform_name == "darwin":
            return self._disable_macos()
        if self.platform_name == "linux":
            return self._disable_linux()
        if self.platform_name.startswith("win"):
            return self._disable_windows()
        return False, "当前平台不支持自动配置开机自启动"

    def _enable_macos(self) -> tuple[bool, str]:
        plist_path = self._mac_plist_path()
        plist_path.parent.mkdir(parents=True, exist_ok=True)

        log_dir = self.project_root / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)

        content = f"""<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<!DOCTYPE plist PUBLIC \"-//Apple//DTD PLIST 1.0//EN\" \"http://www.apple.com/DTDs/PropertyList-1.0.dtd\">
<plist version=\"1.0\">
<dict>
    <key>Label</key>
    <string>{self.service_name}</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/zsh</string>
        <string>-lc</string>
        <string>{self._start_command()}</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>{log_dir / "autostart.out.log"}</string>
    <key>StandardErrorPath</key>
    <string>{log_dir / "autostart.err.log"}</string>
</dict>
</plist>
"""
        plist_path.write_text(content, encoding="utf-8")

        self._run(["launchctl", "unload", str(plist_path)])
        ok, msg = self._run(["launchctl", "load", str(plist_path)])
        if ok:
            return True, f"已启用 macOS 开机自启动: {plist_path}"
        return False, f"已写入配置但加载失败: {msg}"

    def _disable_macos(self) -> tuple[bool, str]:
        plist_path = self._mac_plist_path()
        if plist_path.exists():
            self._run(["launchctl", "unload", str(plist_path)])
            plist_path.unlink(missing_ok=True)
        return True, "已关闭 macOS 开机自启动"

    def _enable_linux(self) -> tuple[bool, str]:
        service_path = self._linux_service_path()
        service_path.parent.mkdir(parents=True, exist_ok=True)

        content = f"""[Unit]
Description=Campus-Auth Auto Network Web Console
After=network.target

[Service]
Type=simple
WorkingDirectory={self.project_root}
ExecStart=/bin/bash -lc \"{self._start_command()}\"
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
"""
        service_path.write_text(content, encoding="utf-8")

        self._run(["systemctl", "--user", "daemon-reload"])
        self._run(["systemctl", "--user", "enable", "--now", self.service_name])
        return True, f"已启用 Linux 开机自启动: {service_path}"

    def _disable_linux(self) -> tuple[bool, str]:
        service_path = self._linux_service_path()
        self._run(["systemctl", "--user", "disable", "--now", self.service_name])
        service_path.unlink(missing_ok=True)
        self._run(["systemctl", "--user", "daemon-reload"])
        return True, "已关闭 Linux 开机自启动"

    def _enable_windows(self) -> tuple[bool, str]:
        startup_vbs = self._windows_startup_vbs()

        try:
            startup_vbs.parent.mkdir(parents=True, exist_ok=True)
        except PermissionError:
            return False, "无法创建启动文件夹，请检查权限或杀毒软件是否拦截"
        except Exception as exc:
            return False, f"创建启动文件夹失败: {exc}"

        python_exe = self.project_root / "environment" / "python" / "python.exe"
        app_py = self.project_root / "app.py"

        if python_exe.exists():
            content = f'''Set WshShell = CreateObject("WScript.Shell")
WshShell.Environment("PROCESS")("Campus-Auth_AUTO_OPEN_BROWSER") = "false"

' 检查是否已经在运行
Set fso = CreateObject("Scripting.FileSystemObject")
pidFile = WshShell.ExpandEnvironmentStrings("%USERPROFILE%") & "\\.campus_network_auth\\campus_network_auth.pid"

If fso.FileExists(pidFile) Then
    Set file = fso.OpenTextFile(pidFile, 1)
    pid = Trim(file.ReadAll)
    file.Close
    
    ' 尝试检查进程是否在运行
    On Error Resume Next
    Set objWMIService = GetObject("winmgmts:\\\\.\\root\\cimv2")
    Set colProcessList = objWMIService.ExecQuery("Select * from Win32_Process where ProcessId = " & pid)
    If colProcessList.Count > 0 Then
        WScript.Quit
    End If
    On Error GoTo 0
End If

WshShell.Run Chr(34) & "{python_exe}" & Chr(34) & " " & Chr(34) & "{app_py}" & Chr(34) & " --no-browser", 0, False
'''
        else:
            packaged = os.getenv("Campus-Auth_START_EXECUTABLE", "").strip()
            content = f'''Set WshShell = CreateObject("WScript.Shell")
WshShell.Environment("PROCESS")("Campus-Auth_AUTO_OPEN_BROWSER") = "false"

' 检查是否已经在运行
Set fso = CreateObject("Scripting.FileSystemObject")
pidFile = WshShell.ExpandEnvironmentStrings("%USERPROFILE%") & "\\.campus_network_auth\\campus_network_auth.pid"

If fso.FileExists(pidFile) Then
    Set file = fso.OpenTextFile(pidFile, 1)
    pid = Trim(file.ReadAll)
    file.Close
    
    ' 尝试检查进程是否在运行
    On Error Resume Next
    Set objWMIService = GetObject("winmgmts:\\\\.\\root\\cimv2")
    Set colProcessList = objWMIService.ExecQuery("Select * from Win32_Process where ProcessId = " & pid)
    If colProcessList.Count > 0 Then
        WScript.Quit
    End If
    On Error GoTo 0
End If

WshShell.Run Chr(34) & "{packaged}" & Chr(34) & " --no-browser", 0, False
'''

        try:
            startup_vbs.write_text(content, encoding="utf-8")
        except PermissionError:
            return (
                False,
                "写入启动文件失败，可能被杀毒软件拦截，请将程序添加到白名单后重试",
            )
        except OSError as exc:
            if "另一个程序正在使用此文件" in str(
                exc
            ) or "being used by another process" in str(exc):
                return False, "启动文件被占用，请关闭可能占用该文件的程序后重试"
            return False, f"写入启动文件失败: {exc}"
        except Exception as exc:
            return False, f"创建启动文件时发生未知错误: {exc}"

        return True, f"已启用 Windows 开机自启动: {startup_vbs}"

    def _disable_windows(self) -> tuple[bool, str]:
        startup_vbs = self._windows_startup_vbs()
        startup_vbs.unlink(missing_ok=True)
        return True, "已关闭 Windows 开机自启动"
