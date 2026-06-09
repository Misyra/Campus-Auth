from __future__ import annotations

import os
import platform
import re
import subprocess
import sys
import xml.sax.saxutils
from pathlib import Path

from app.utils.logging import get_logger
from app.utils.platform_utils import get_platform, is_linux, is_macos, is_windows

logger = get_logger("autostart", source="backend")


class AutoStartService:
    """管理开机自启动（按平台实现）。"""

    def __init__(self, project_root: Path):
        self.project_root = project_root
        # 使用 platform_utils 获取平台标识，统一跨平台判定
        self.platform = get_platform()
        self.service_name = "campus-auth"

    def _start_command(self) -> str:
        # 优先使用打包可执行文件（环境变量覆盖）
        packaged_executable = os.getenv("CAMPUS_AUTH_START_EXECUTABLE", "").strip()
        if packaged_executable:
            return f'"{packaged_executable}"'

        app_entry = self.project_root / "app.py"

        # 优先使用项目 .venv 中的 Python（uv/venv 均适用）
        if is_windows():
            venv_python = self.project_root / ".venv" / "Scripts" / "python.exe"
        else:
            venv_python = self.project_root / ".venv" / "bin" / "python3"
        if venv_python.exists():
            return f'"{venv_python}" "{app_entry}"'

        # 当前解释器可用则直接使用
        runtime_python = Path(sys.executable).resolve()
        if runtime_python.exists():
            return f'"{runtime_python}" "{app_entry}"'

        if is_windows():
            # Windows 下检查嵌入式 Python（发布包内置）
            python_exe = self.project_root / "environment" / "python" / "python.exe"
            if python_exe.exists():
                return f'"{python_exe}" "{app_entry}"'

        # 兜底：依赖 PATH 上的 python
        return f'python "{app_entry}"'

    def _run(self, cmd: list[str]) -> tuple[bool, str]:
        try:
            logger.debug("执行命令: {}", " ".join(cmd))
            proc = subprocess.run(
                cmd, capture_output=True, text=True, check=False, timeout=30
            )
            if proc.returncode == 0:
                logger.debug("命令成功: {}", (proc.stdout or "").strip()[:200])
                return True, (proc.stdout or "").strip()
            logger.warning(
                "命令失败 (code={}): {}",
                proc.returncode,
                (proc.stderr or proc.stdout or "").strip()[:200],
            )
            return False, (proc.stderr or proc.stdout or "").strip()
        except subprocess.TimeoutExpired:
            logger.error("命令超时 (30s): {}", " ".join(cmd))
            return False, f"命令执行超时 (30s): {' '.join(cmd)}"
        except Exception as exc:
            logger.error("命令异常: {} -> {}", " ".join(cmd), exc)
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
        if is_macos():
            target = self._mac_plist_path()
            return {
                "platform": "macOS",
                "enabled": target.exists(),
                "method": "launchd",
                "location": str(target),
            }

        if is_linux():
            target = self._linux_service_path()
            return {
                "platform": "Linux",
                "enabled": target.exists(),
                "method": "systemd --user",
                "location": str(target),
            }

        if is_windows():
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
        logger.info("启用开机自启动: platform={}", self.platform)
        if is_macos():
            return self._enable_macos()
        if is_linux():
            return self._enable_linux()
        if is_windows():
            return self._enable_windows()
        logger.warning("当前平台不支持开机自启动: {}", self.platform)
        return False, "当前平台不支持自动配置开机自启动"

    def disable(self) -> tuple[bool, str]:
        logger.info("禁用开机自启动: platform={}", self.platform)
        if is_macos():
            return self._disable_macos()
        if is_linux():
            return self._disable_linux()
        if is_windows():
            return self._disable_windows()
        logger.warning("当前平台不支持开机自启动: {}", self.platform)
        return False, "当前平台不支持自动配置开机自启动"

    def _enable_macos(self) -> tuple[bool, str]:
        plist_path = self._mac_plist_path()
        logger.info("macOS plist 路径: {}", plist_path)
        plist_path.parent.mkdir(parents=True, exist_ok=True)

        log_dir = self.project_root / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)

        escaped_cmd = xml.sax.saxutils.escape(self._start_command())
        escaped_log_out = xml.sax.saxutils.escape(str(log_dir / "autostart.out.log"))
        escaped_log_err = xml.sax.saxutils.escape(str(log_dir / "autostart.err.log"))

        content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{self.service_name}</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/zsh</string>
        <string>-lc</string>
        <string>{escaped_cmd}</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>{escaped_log_out}</string>
    <key>StandardErrorPath</key>
    <string>{escaped_log_err}</string>
</dict>
</plist>
"""
        plist_path.write_text(content, encoding="utf-8")
        logger.info("macOS plist 已写入: {}", plist_path)

        # 优先使用新版 API (macOS 10.10+)，失败则回退到旧版 load/unload
        uid = os.getuid()
        gui_domain = f"gui/{uid}"

        # 尝试卸载旧配置（忽略错误）
        self._run(["launchctl", "bootout", gui_domain, str(plist_path)])
        ok, msg = self._run(["launchctl", "bootstrap", gui_domain, str(plist_path)])
        if ok:
            logger.info("macOS launchctl bootstrap 成功")
            return True, f"已启用 macOS 开机自启动: {plist_path}"

        # 回退到旧版 API
        logger.debug("launchctl bootstrap 失败，回退到 load/unload: {}", msg)
        self._run(["launchctl", "unload", str(plist_path)])
        ok, msg = self._run(["launchctl", "load", str(plist_path)])
        if ok:
            logger.info("macOS launchctl load 成功")
            return True, f"已启用 macOS 开机自启动: {plist_path}"
        logger.error("macOS launchctl load 失败: {}", msg)
        return False, f"已写入配置但加载失败: {msg}"

    def _disable_macos(self) -> tuple[bool, str]:
        plist_path = self._mac_plist_path()
        if plist_path.exists():
            logger.info("macOS 移除 plist: {}", plist_path)
            # 优先使用新版 API bootout，失败则回退到 unload
            uid = os.getuid()
            gui_domain = f"gui/{uid}"
            ok, _ = self._run(["launchctl", "bootout", gui_domain, str(plist_path)])
            if not ok:
                self._run(["launchctl", "unload", str(plist_path)])
            plist_path.unlink(missing_ok=True)
        else:
            logger.debug("macOS plist 不存在: {}", plist_path)
        return True, "已关闭 macOS 开机自启动"

    def _enable_linux(self) -> tuple[bool, str]:
        service_path = self._linux_service_path()
        logger.info("Linux service 路径: {}", service_path)
        service_path.parent.mkdir(parents=True, exist_ok=True)

        # 用单引号包裹命令，确保路径含空格时 systemd 正确解析
        # 如果命令本身含单引号，用 '\'' 转义
        cmd = self._start_command().replace("'", "'\\''")
        content = f"""[Unit]
Description=Campus-Auth Auto Network Web Console
After=network.target

[Service]
Type=simple
WorkingDirectory={self.project_root}
ExecStart=/bin/sh -lc '{cmd}'
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
"""
        service_path.write_text(content, encoding="utf-8")
        logger.info("Linux service 已写入: {}", service_path)

        self._run(["systemctl", "--user", "daemon-reload"])
        ok, msg = self._run(
            ["systemctl", "--user", "enable", "--now", self.service_name]
        )
        if ok:
            logger.info("Linux systemd 启用成功")
            return True, f"已启用 Linux 开机自启动: {service_path}"
        logger.error("Linux systemd 启用失败: {}", msg)
        return False, f"已写入配置但 systemd 启用失败: {msg}"

    def _disable_linux(self) -> tuple[bool, str]:
        service_path = self._linux_service_path()
        logger.info("Linux 禁用自启动: {}", service_path)
        self._run(["systemctl", "--user", "disable", "--now", self.service_name])
        service_path.unlink(missing_ok=True)
        self._run(["systemctl", "--user", "daemon-reload"])
        return True, "已关闭 Linux 开机自启动"

    @staticmethod
    def _build_vbs_content(run_command: str) -> str:
        """生成 Windows 自启动 VBScript 内容。

        Args:
            run_command: VBScript 中用于启动程序的两行代码
                （targetExe 赋值 + WshShell.Run 调用）。
        """
        return f"""Set WshShell = CreateObject("WScript.Shell")
WshShell.Environment("PROCESS")("CAMPUS_AUTH_AUTO_OPEN_BROWSER") = "false"

' Check if already running
Set fso = CreateObject("Scripting.FileSystemObject")
pidFile = WshShell.ExpandEnvironmentStrings("%USERPROFILE%") & "\\.campus_network_auth\\campus_network_auth.pid"

If fso.FileExists(pidFile) Then
    Set file = fso.OpenTextFile(pidFile, 1)
    pid = Trim(file.ReadLine)
    file.Close

    ' Check if the process is still alive
    On Error Resume Next
    Set objWMIService = GetObject("winmgmts:\\\\.\\root\\cimv2")
    Set colProcessList = objWMIService.ExecQuery("Select * from Win32_Process where ProcessId = " & pid)
    If colProcessList.Count > 0 Then
        WScript.Quit
    End If
    On Error GoTo 0
End If

{run_command}
"""

    @staticmethod
    def _has_cjk_chars(path: str) -> bool:
        """检查路径是否包含中日韩(CJK)统一表意文字。"""
        return bool(re.search(r"[一-鿿㐀-䶿豈-﫿]", path))

    def _enable_windows(self) -> tuple[bool, str]:
        project_root_str = str(self.project_root)
        if self._has_cjk_chars(project_root_str):
            logger.error("项目路径包含中日韩字符: {}", project_root_str)
            return (
                False,
                f"项目路径包含中文/日文/韩文字符，自启动可能无法正常启动。\n"
                f"请将 Campus-Auth 文件夹移动到纯英文路径（如 D:\\Campus-Auth）后重新启用自启动。\n"
                f"当前路径: {project_root_str}",
            )

        startup_vbs = self._windows_startup_vbs()
        logger.info("Windows VBS 路径: {}", startup_vbs)

        try:
            startup_vbs.parent.mkdir(parents=True, exist_ok=True)
        except PermissionError:
            logger.error("无法创建启动文件夹: PermissionError")
            return False, "无法创建启动文件夹，请检查权限或杀毒软件是否拦截"
        except Exception as exc:
            logger.error("创建启动文件夹失败: {}", exc)
            return False, f"创建启动文件夹失败: {exc}"

        # 复用 _start_command() 获取启动命令（自动处理 uv/venv/嵌入式 Python）
        # VBS 字符串中双引号用 "" 转义
        start_cmd_escaped = self._start_command().replace('"', '""')
        run_command = (
            f'targetCmd = "{start_cmd_escaped} --no-browser"\n'
            f"WshShell.Run targetCmd, 0, False"
        )

        content = self._build_vbs_content(run_command)

        try:
            startup_vbs.write_text(content, encoding="utf-8")
        except PermissionError:
            logger.error("写入启动文件失败: PermissionError，可能被杀毒软件拦截")
            return (
                False,
                "写入启动文件失败，可能被杀毒软件拦截，请暂时关闭杀毒软件后重试",
            )
        except OSError as exc:
            if "另一个程序正在使用此文件" in str(
                exc
            ) or "being used by another process" in str(exc):
                logger.error("启动文件被占用: {}", exc)
                return False, "启动文件被占用，请关闭可能占用该文件的程序后重试"
            logger.error("写入启动文件失败: {}", exc)
            return False, f"写入启动文件失败: {exc}"
        except Exception as exc:
            logger.error("创建启动文件时发生未知错误: {}", exc)
            return False, f"创建启动文件时发生未知错误: {exc}"

        if not startup_vbs.exists():
            logger.error("自启动脚本创建后被拦截，疑似杀毒软件: {}", startup_vbs)
            return (
                False,
                f"自启动脚本创建后被拦截，请暂时关闭杀毒软件后重试\n预期位置: {startup_vbs}",
            )

        logger.info("Windows VBS 已写入: {}", startup_vbs)
        return True, f"已启用 Windows 开机自启动: {startup_vbs}"

    def _disable_windows(self) -> tuple[bool, str]:
        startup_vbs = self._windows_startup_vbs()
        logger.info("Windows 移除自启动脚本: {}", startup_vbs)
        startup_vbs.unlink(missing_ok=True)
        return True, "已关闭 Windows 开机自启动"
