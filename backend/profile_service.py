from __future__ import annotations

import json
import logging
import os
import platform
import re
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Any

from src.utils.crypto import decrypt_password, encrypt_password, mask_password
from src.utils.logging import get_logger

from .schemas import ProfileSettings, ProfilesData

profile_logger = get_logger("backend.profile_service", side="BACKEND")

_SETTINGS_FILE = "settings.json"


def _normalize_isp_to_carrier(isp: str) -> tuple[str, str]:
    """将 ISP 环境变量值转换为 (carrier, carrier_custom) 元组"""
    builtin = {"移动", "联通", "电信"}
    isp_value = str(isp or "").strip()
    if not isp_value:
        return "无", ""
    if isp_value in builtin:
        return isp_value, ""
    return "自定义", isp_value


def detect_gateway_ip() -> str | None:
    """检测当前默认网关 IP（跨平台）"""
    system = platform.system()
    profile_logger.debug("正在检测网关 IP，平台: %s", system)

    try:
        if system == "Windows":
            result = _detect_gateway_windows()
        elif system == "Linux":
            result = _detect_gateway_linux()
        elif system == "Darwin":
            result = _detect_gateway_darwin()
        else:
            profile_logger.warning("不支持的平台: %s", system)
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
    system = platform.system()
    profile_logger.debug("正在检测 SSID，平台: %s", system)

    try:
        if system == "Windows":
            result = _detect_ssid_windows()
        elif system == "Linux":
            result = _detect_ssid_linux()
        elif system == "Darwin":
            result = _detect_ssid_darwin()
        else:
            profile_logger.warning("不支持的平台: %s", system)
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
    """Windows: 解析 ipconfig 输出获取默认网关（使用原始字节匹配，避免编码问题）"""
    try:
        creationflags = (
            subprocess.CREATE_NO_WINDOW
            if hasattr(subprocess, "CREATE_NO_WINDOW")
            else 0
        )
        result = subprocess.run(
            ["ipconfig"],
            capture_output=True,
            timeout=5,
            creationflags=creationflags,
        )
        profile_logger.debug("ipconfig 返回码: %d, 输出长度: %d", result.returncode, len(result.stdout))

        output = result.stdout

        # 使用原始字节匹配，避免 Windows 中文编码问题
        # "默认网关" GBK: c4ac c8cf cdf8 b9d8
        # "Default Gateway" ASCII
        pattern = re.compile(
            rb"(?:\xc4\xac\xc8\xcf\xcd\xf8\xb9\xd8|Default\s+Gateway)"
            rb"[\s.:]*(\d+\.\d+\.\d+\.\d+)"
        )
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
                    ip = ".".join(str(b) for b in gateway_bytes)
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
    """Windows: 解析 netsh wlan show interfaces 获取当前 WiFi SSID"""
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

        # "SSID" is always ASCII in netsh output, so raw bytes matching works
        # Format: "    SSID                   : MyNetwork"
        pattern = re.compile(rb"^\s*SSID\s*:\s*(.+)$", re.MULTILINE)
        match = pattern.search(output)
        if match:
            ssid = match.group(1).strip().decode("utf-8", errors="replace")
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
    """macOS: 使用 airport 命令获取当前 WiFi SSID"""
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
        for line in result.stdout.splitlines():
            if "SSID:" in line and "BSSID:" not in line:
                return line.split(":", 1)[1].strip()
    except Exception as exc:
        profile_logger.debug("macOS SSID 检测失败: %s", exc)

    return None


class ProfileService:
    """配置方案管理服务"""

    def __init__(self, project_root: Path):
        self.project_root = project_root
        self._settings_path = project_root / _SETTINGS_FILE
        self._lock = threading.Lock()
        self._data: ProfilesData | None = None

    def load(self) -> ProfilesData:
        """加载 settings.json，不存在则返回空结构"""
        with self._lock:
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

    def save(self, data: ProfilesData) -> None:
        """原子写入 settings.json"""
        content = data.model_dump_json(indent=2)
        tmp_fd, tmp_path = tempfile.mkstemp(
            dir=self._settings_path.parent, suffix=".tmp", prefix="settings."
        )
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                f.write(content)
            os.replace(tmp_path, self._settings_path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

        with self._lock:
            self._data = data

        profile_logger.info("settings.json 已保存")

    def get_active_profile(self) -> ProfileSettings:
        """获取当前活动方案的设置"""
        data = self.load()
        profile_id = data.active_profile
        profile = data.profiles.get(profile_id)
        if profile:
            return profile.model_copy(deep=True)
        # 如果活动方案不存在，返回第一个或默认
        if data.profiles:
            first_id = next(iter(data.profiles))
            return data.profiles[first_id].model_copy(deep=True)
        return ProfileSettings()

    def get_active_profile_id(self) -> str:
        """获取当前活动方案 ID"""
        data = self.load()
        return data.active_profile

    def set_active_profile(self, profile_id: str) -> tuple[bool, str]:
        """设置活动方案"""
        data = self.load()
        if profile_id not in data.profiles:
            return False, f"方案 '{profile_id}' 不存在"

        data.active_profile = profile_id
        self.save(data)
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

        # 处理密码：掩码不更新，明文则加密存储
        if settings.password and not settings.password.startswith("•") and not settings.password.startswith("ENC:"):
            settings.password = encrypt_password(settings.password)
        elif settings.password and settings.password.startswith("•"):
            # 保留已有的加密密码
            data = self.load()
            existing = data.profiles.get(profile_id)
            if existing and existing.password:
                settings.password = existing.password

        data = self.load()
        data.profiles[profile_id] = settings

        # 如果是第一个方案，设为活动方案
        if len(data.profiles) == 1:
            data.active_profile = profile_id

        self.save(data)
        profile_logger.info("方案已保存: %s (%s)", profile_id, settings.name)
        return True, f"方案 '{settings.name}' 保存成功"

    def delete_profile(self, profile_id: str) -> tuple[bool, str]:
        """删除一个方案"""
        if profile_id == "default":
            return False, "不能删除默认方案"

        data = self.load()
        if profile_id not in data.profiles:
            return False, f"方案 '{profile_id}' 不存在"

        if len(data.profiles) <= 1:
            return False, "至少需要保留一个方案"

        del data.profiles[profile_id]

        # 如果删除的是活动方案，切换到第一个
        if data.active_profile == profile_id:
            data.active_profile = next(iter(data.profiles))

        self.save(data)
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
        data = self.load()
        data.auto_switch = enabled
        self.save(data)
        profile_logger.info("自动切换: %s", "开启" if enabled else "关闭")

    def migrate_from_env(self, config: dict[str, Any]) -> None:
        """从 .env 配置迁移，创建默认方案（仅在 settings.json 不存在时执行）"""
        if self._settings_path.exists():
            return

        profile_logger.info("执行首次迁移：从 .env 创建默认配置方案")

        browser_config = config.get("browser_settings", {})
        pause_config = config.get("pause_login", {})
        monitor_config = config.get("monitor", {})
        ping_targets = monitor_config.get("ping_targets", [])

        carrier, carrier_custom = _normalize_isp_to_carrier(config.get("isp", ""))

        interval_seconds = int(monitor_config.get("interval", 300))

        default_profile = ProfileSettings(
            name="默认方案",
            match_gateway_ip="",
            auth_url=str(config.get("auth_url", "http://172.29.0.2")),
            carrier=carrier,
            carrier_custom=carrier_custom,
            check_interval_minutes=max(1, interval_seconds // 60),
            auto_start=bool(config.get("auto_start_monitoring", False)),
            headless=bool(browser_config.get("headless", True)),
            browser_timeout=int(browser_config.get("timeout", 8000)),
            browser_user_agent=str(browser_config.get("user_agent", "")),
            browser_low_resource_mode=bool(
                browser_config.get("low_resource_mode", True)
            ),
            browser_disable_web_security=bool(
                browser_config.get("disable_web_security", False)
            ),
            browser_extra_headers_json=str(
                browser_config.get("extra_headers_json", "")
            ),
            pause_enabled=bool(pause_config.get("enabled", True)),
            pause_start_hour=int(pause_config.get("start_hour", 0)),
            pause_end_hour=int(pause_config.get("end_hour", 6)),
            network_targets=",".join(str(t) for t in ping_targets)
            if ping_targets
            else "8.8.8.8:53,114.114.114.114:53,www.baidu.com:443",
            custom_variables=config.get("custom_variables", {}),
        )

        data = ProfilesData(
            auto_switch=True,
            active_profile="default",
            profiles={"default": default_profile},
        )
        self.save(data)
        profile_logger.info("默认方案已创建")
