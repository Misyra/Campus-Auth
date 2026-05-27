from __future__ import annotations

import re
import subprocess
import threading
from pathlib import Path
from typing import Any

from src.utils.file_helpers import atomic_write
from src.utils.platform_utils import is_windows, is_macos, is_linux
from src.utils.crypto import save_password_field
from src.utils.logging import get_logger

from .schemas import ProfileSettings, ProfilesData, SystemSettings

profile_logger = get_logger("backend.profile_service", side="BACKEND")

_SETTINGS_FILE = "settings.json"


def detect_gateway_ip() -> str | None:
    """检测当前默认网关 IP（跨平台）"""
    # 使用 platform_utils 进行跨平台检测
    profile_logger.debug("正在检测网关 IP")

    try:
        if is_windows():
            result = _detect_gateway_windows()
        elif is_linux():
            result = _detect_gateway_linux()
        elif is_macos():
            result = _detect_gateway_darwin()
        else:
            profile_logger.warning("不支持的平台")
            return None

        if result:
            profile_logger.info("检测到网关 IP: %s", result)
        else:
            profile_logger.warning("未能检测到网关 IP")
        return result
    except Exception as exc:
        profile_logger.error("网关检测异常: %s", exc, exc_info=True)
        return None


def detect_wifi_ssid() -> str | None:
    """检测当前连接的 WiFi SSID（跨平台）"""
    # 使用 platform_utils 进行跨平台检测
    profile_logger.debug("正在检测 SSID")

    try:
        if is_windows():
            result = _detect_ssid_windows()
        elif is_linux():
            result = _detect_ssid_linux()
        elif is_macos():
            result = _detect_ssid_darwin()
        else:
            profile_logger.warning("不支持的平台")
            return None

        if result:
            profile_logger.info("检测到 SSID: %s", result)
        else:
            profile_logger.warning("未能检测到 SSID（可能未连接 WiFi）")
        return result
    except Exception as exc:
        profile_logger.error("SSID 检测异常: %s", exc, exc_info=True)
        return None


def _detect_gateway_windows() -> str | None:
    """Windows: 检测默认网关 IP。

    优先使用 PowerShell Get-NetRoute（结构化输出，不受系统语言影响），
    失败时回退到 ipconfig + 多语言字节匹配。
    """
    creationflags = (
        subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
    )

    # 优先使用 PowerShell（结构化输出，不受语言影响）
    try:
        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "Get-NetRoute -DestinationPrefix '0.0.0.0/0' | "
                "Select-Object -First 1 -ExpandProperty NextHop",
            ],
            capture_output=True,
            text=True,
            timeout=5,
            creationflags=creationflags,
        )
        if result.returncode == 0:
            ip = result.stdout.strip()
            if ip and re.fullmatch(r"\d+\.\d+\.\d+\.\d+", ip) and ip != "0.0.0.0":
                profile_logger.info("检测到网关 IP (PowerShell): %s", ip)
                return ip
    except FileNotFoundError:
        profile_logger.debug("PowerShell 不可用，回退到 ipconfig")
    except Exception as exc:
        profile_logger.debug("PowerShell 网关检测失败: %s", exc)

    # 回退：ipconfig + 多语言字节匹配
    try:
        result = subprocess.run(
            ["ipconfig"],
            capture_output=True,
            timeout=5,
            creationflags=creationflags,
        )
        profile_logger.debug(
            "ipconfig 返回码: %d, 输出长度: %d", result.returncode, len(result.stdout)
        )

        output = result.stdout

        # 使用原始字节匹配，避免 Windows 编码问题
        # 已知的"默认网关"多语言字节序列
        gateway_patterns = [
            rb"\xc4\xac\xc8\xcf\xcd\xf8\xb9\xd8",  # "默认网关" GBK
            rb"Default\s+Gateway",  # English
            rb"Standardgateway",  # German
            rb"Passerelle\s+par\s+d\xc3\xa9faut",  # French (UTF-8)
            rb"Gateway\s+predefinito",  # Italian
            rb"Puerta\s+de\s+enlace\s+predeterminada",  # Spanish
            rb"\xe3\x83\x87\xe3\x83\x95\xe3\x82\xa9\xe3\x83\xab\xe3\x83\x88\xe3\x82\xb2\xe3\x83\xbc\xe3\x83\x88\xe3\x82\xa6\xe3\x82\xa7\xe3\x82\xa4",  # "デフォルトゲートウェイ" UTF-8
            rb"\xec\x98\xa4\xeb\xa5\xb8 \xea\xb2\x8c\xec\x9d\xb4\xed\x8a\xb8\xec\x9b\xa8\xec\x9d\xb4",  # "오른 게이트웨이" UTF-8
        ]
        combined = rb"(?:" + rb"|".join(gateway_patterns) + rb")"
        pattern = re.compile(combined + rb"[\s.:]*(\d+\.\d+\.\d+\.\d+)")
        for match in pattern.finditer(output):
            ip = match.group(1).decode("ascii")
            if ip != "0.0.0.0":
                return ip

        profile_logger.debug("ipconfig 输出中未找到网关地址")
    except FileNotFoundError:
        profile_logger.error("ipconfig 命令不存在")
    except subprocess.TimeoutExpired:
        profile_logger.error("ipconfig 执行超时")
    except Exception as exc:
        profile_logger.error("Windows 网关检测失败: %s", exc, exc_info=True)

    return None


def _detect_gateway_linux() -> str | None:
    """Linux: 解析 /proc/net/route 获取默认网关"""
    try:
        with open("/proc/net/route", "r") as f:
            for line in f:
                parts = line.strip().split()
                if len(parts) >= 3 and parts[1] == "00000000":
                    # 网关字段是小端序十六进制
                    gateway_hex = parts[2]
                    gateway_bytes = bytes.fromhex(gateway_hex)
                    ip = ".".join(str(b) for b in reversed(gateway_bytes))
                    if ip != "0.0.0.0":
                        return ip
    except Exception as exc:
        profile_logger.debug("Linux 网关检测失败: %s", exc)

    return None


def _detect_gateway_darwin() -> str | None:
    """macOS: 解析 netstat -nr 获取默认网关"""
    try:
        result = subprocess.run(
            ["netstat", "-nr"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        for line in result.stdout.splitlines():
            if line.startswith("default"):
                parts = line.split()
                if len(parts) >= 2:
                    ip = parts[1]
                    if re.fullmatch(r"\d+\.\d+\.\d+\.\d+", ip) and ip != "0.0.0.0":
                        return ip
    except Exception as exc:
        profile_logger.debug("macOS 网关检测失败: %s", exc)

    return None


def _detect_ssid_windows() -> str | None:
    """Windows: 解析 netsh wlan show interfaces 获取当前 WiFi SSID。

    netsh 输出使用系统默认编码（中文 Windows 为 GBK/cp936），
    SSID 可能包含非 ASCII 字符（如中文），需用系统编码解码。
    """
    try:
        creationflags = (
            subprocess.CREATE_NO_WINDOW
            if hasattr(subprocess, "CREATE_NO_WINDOW")
            else 0
        )
        result = subprocess.run(
            ["netsh", "wlan", "show", "interfaces"],
            capture_output=True,
            timeout=5,
            creationflags=creationflags,
        )
        output = result.stdout

        # 使用系统默认编码解码（中文 Windows 为 GBK，英文为 cp1252）
        import locale

        encoding = locale.getpreferredencoding(False) or "utf-8"

        pattern = re.compile(rb"^\s*SSID\s*:\s*(.+)$", re.MULTILINE)
        match = pattern.search(output)
        if match:
            raw = match.group(1).strip()
            try:
                ssid = raw.decode(encoding)
            except (UnicodeDecodeError, LookupError):
                ssid = raw.decode("utf-8", errors="replace")
            if ssid:
                return ssid
    except Exception as exc:
        profile_logger.debug("Windows SSID 检测失败: %s", exc)

    return None


def _detect_ssid_linux() -> str | None:
    """Linux: 使用 iwgetid 或解析 /proc/net/wireless 获取当前 WiFi SSID"""
    try:
        result = subprocess.run(
            ["iwgetid", "-r"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        ssid = result.stdout.strip()
        if ssid:
            return ssid
    except FileNotFoundError:
        pass
    except Exception as exc:
        profile_logger.debug("Linux SSID 检测失败 (iwgetid): %s", exc)

    # Fallback: nmcli
    try:
        result = subprocess.run(
            ["nmcli", "-t", "-f", "active,ssid", "dev", "wifi"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        for line in result.stdout.splitlines():
            if line.startswith("yes:"):
                return line.split(":", 1)[1].strip()
    except Exception as exc:
        profile_logger.debug("Linux SSID 检测失败 (nmcli): %s", exc)

    return None


def _detect_ssid_darwin() -> str | None:
    """macOS: 获取当前 WiFi SSID。

    优先使用 airport 命令，失败时回退到 networksetup。
    注意：较新版本的 macOS 可能已移除 airport 工具。
    """
    # 方式 1：airport 命令（较旧 macOS）
    try:
        result = subprocess.run(
            [
                "/System/Library/PrivateFrameworks/Apple80211.framework"
                "/Versions/Current/Resources/airport",
                "-I",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                if "SSID:" in line and "BSSID:" not in line:
                    ssid = line.split(":", 1)[1].strip()
                    if ssid:
                        return ssid
    except FileNotFoundError:
        profile_logger.debug("airport 命令不存在（较新 macOS 版本）")
    except Exception as exc:
        profile_logger.debug("macOS SSID 检测失败 (airport): %s", exc)

    # 方式 2：networksetup（所有 macOS 版本可用）
    try:
        # 先获取 Wi-Fi 硬件端口名
        result = subprocess.run(
            ["networksetup", "-listallhardwareports"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        wifi_device = None
        lines = result.stdout.splitlines()
        for i, line in enumerate(lines):
            if "Wi-Fi" in line or "AirPort" in line:
                # 下一行是 Device
                if i + 1 < len(lines):
                    wifi_device = lines[i + 1].split(":")[-1].strip()
                    break

        if wifi_device:
            result = subprocess.run(
                ["networksetup", "-getairportnetwork", wifi_device],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                output = result.stdout.strip()
                # 输出格式: "Current Wi-Fi Network: MyNetwork"
                if ":" in output:
                    ssid = output.split(":", 1)[1].strip()
                    if ssid and "not associated" not in ssid.lower():
                        return ssid
    except Exception as exc:
        profile_logger.debug("macOS SSID 检测失败 (networksetup): %s", exc)

    return None


class ProfileService:
    """配置方案管理服务"""

    def __init__(self, project_root: Path):
        self.project_root = project_root
        self._settings_path = project_root / _SETTINGS_FILE
        self._lock = threading.Lock()
        self._data: ProfilesData | None = None

    def invalidate_cache(self) -> None:
        """清除缓存，强制下次 load() 从磁盘读取"""
        with self._lock:
            self._data = None

    def _load_unsafe(self) -> ProfilesData:
        """加载 settings.json（不加锁，由调用者持有锁）"""
        if self._data is not None:
            return self._data.model_copy(deep=True)

        if self._settings_path.exists():
            try:
                raw = self._settings_path.read_text(encoding="utf-8")
                self._data = ProfilesData.model_validate_json(raw)
                return self._data.model_copy(deep=True)
            except Exception as exc:
                profile_logger.error("加载 settings.json 失败: %s", exc)

        self._data = ProfilesData()
        return self._data.model_copy(deep=True)

    def _save_unsafe(self, data: ProfilesData) -> None:
        """原子写入 settings.json（不加锁，由调用者持有锁）"""
        content = data.model_dump_json(indent=2)
        atomic_write(self._settings_path, content)

        self._data = data
        profile_logger.info("settings.json 已保存")

    def load(self) -> ProfilesData:
        """加载 settings.json，不存在则返回空结构"""
        with self._lock:
            return self._load_unsafe()

    def save(self, data: ProfilesData) -> None:
        """原子写入 settings.json"""
        with self._lock:
            self._save_unsafe(data)

    def get_active_profile(self) -> ProfileSettings:
        """获取当前活动方案的设置（返回值由 load() 深拷贝保护，无需再次拷贝）"""
        data = self.load()
        profile_id = data.active_profile
        profile = data.profiles.get(profile_id)
        if profile:
            return profile
        # 如果活动方案不存在，返回第一个或默认
        if data.profiles:
            first_id = next(iter(data.profiles))
            return data.profiles[first_id]
        return ProfileSettings()

    def get_active_profile_id(self) -> str:
        """获取当前活动方案 ID"""
        data = self.load()
        return data.active_profile

    def set_active_profile(self, profile_id: str) -> tuple[bool, str]:
        """设置活动方案"""
        with self._lock:
            data = self._load_unsafe()
            if profile_id not in data.profiles:
                return False, f"方案 '{profile_id}' 不存在"

            data.active_profile = profile_id
            self._save_unsafe(data)
        profile_logger.info("活动方案已切换: %s", profile_id)
        return True, f"已切换到方案: {data.profiles[profile_id].name}"

    def save_profile(
        self, profile_id: str, settings: ProfileSettings
    ) -> tuple[bool, str]:
        """创建或更新一个方案"""
        if not profile_id or not profile_id.strip():
            return False, "方案 ID 不能为空"

        profile_id = profile_id.strip()
        if not re.fullmatch(r"[a-zA-Z0-9_]+", profile_id):
            return False, "方案 ID 只能包含字母、数字和下划线"

        with self._lock:
            data = self._load_unsafe()
            existing = data.profiles.get(profile_id)
            settings.password = save_password_field(
                settings.password or "",
                existing.password if existing else "",
            )
            data.profiles[profile_id] = settings

            if len(data.profiles) == 1:
                data.active_profile = profile_id

            self._save_unsafe(data)
        profile_logger.info("方案已保存: %s (%s)", profile_id, settings.name)
        return True, f"方案 '{settings.name}' 保存成功"

    def delete_profile(self, profile_id: str) -> tuple[bool, str]:
        """删除一个方案"""
        if profile_id == "default":
            return False, "不能删除默认方案"

        with self._lock:
            data = self._load_unsafe()
            if profile_id not in data.profiles:
                return False, f"方案 '{profile_id}' 不存在"

            if len(data.profiles) <= 1:
                return False, "至少需要保留一个方案"

            del data.profiles[profile_id]

            if data.active_profile == profile_id:
                data.active_profile = next(iter(data.profiles))

            self._save_unsafe(data)
        profile_logger.info("方案已删除: %s", profile_id)
        return True, "方案删除成功"

    def detect_matching_profile(self) -> str | None:
        """检测当前网络环境并返回匹配的方案 ID，无匹配返回 None

        匹配优先级：网关 IP > SSID
        """
        gateway = detect_gateway_ip()
        ssid = detect_wifi_ssid()

        profile_logger.debug("检测到网关: %s, SSID: %s", gateway, ssid)

        data = self.load()

        # 优先匹配网关 IP
        if gateway:
            for profile_id, settings in data.profiles.items():
                match_ip = (settings.match_gateway_ip or "").strip()
                if match_ip and match_ip == gateway:
                    profile_logger.info(
                        "网关 %s 匹配方案: %s (%s)",
                        gateway,
                        profile_id,
                        settings.name,
                    )
                    return profile_id

        # 其次匹配 SSID
        if ssid:
            for profile_id, settings in data.profiles.items():
                match_ssid = (settings.match_ssid or "").strip()
                if match_ssid and match_ssid == ssid:
                    profile_logger.info(
                        "SSID '%s' 匹配方案: %s (%s)",
                        ssid,
                        profile_id,
                        settings.name,
                    )
                    return profile_id

        return None

    def set_auto_switch(self, enabled: bool) -> None:
        """设置自动切换开关"""
        with self._lock:
            data = self._load_unsafe()
            data.auto_switch = enabled
            self._save_unsafe(data)
        profile_logger.info("自动切换: %s", "开启" if enabled else "关闭")
