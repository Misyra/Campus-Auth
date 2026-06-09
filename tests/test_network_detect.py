"""网络检测工具测试 — 覆盖平台分发逻辑。"""

from __future__ import annotations

from unittest.mock import patch

from app.network.detect import detect_gateway_ip, detect_wifi_ssid

# ── detect_gateway_ip ──


class TestDetectGatewayIp:
    """网关 IP 检测。"""

    def test_windows_success(self):
        """Windows 成功检测。"""
        with (
            patch("app.network.detect.is_windows", return_value=True),
            patch("app.network.detect.is_linux", return_value=False),
            patch("app.network.detect.is_macos", return_value=False),
            patch(
                "app.network.detect._detect_gateway_windows", return_value="192.168.1.1"
            ),
        ):
            result = detect_gateway_ip()
            assert result == "192.168.1.1"

    def test_linux_success(self):
        """Linux 成功检测。"""
        with (
            patch("app.network.detect.is_windows", return_value=False),
            patch("app.network.detect.is_linux", return_value=True),
            patch("app.network.detect.is_macos", return_value=False),
            patch("app.network.detect._detect_gateway_linux", return_value="10.0.0.1"),
        ):
            result = detect_gateway_ip()
            assert result == "10.0.0.1"

    def test_macos_success(self):
        """macOS 成功检测。"""
        with (
            patch("app.network.detect.is_windows", return_value=False),
            patch("app.network.detect.is_linux", return_value=False),
            patch("app.network.detect.is_macos", return_value=True),
            patch(
                "app.network.detect._detect_gateway_darwin", return_value="172.16.0.1"
            ),
        ):
            result = detect_gateway_ip()
            assert result == "172.16.0.1"

    def test_unsupported_platform(self):
        """不支持的平台返回 None。"""
        with (
            patch("app.network.detect.is_windows", return_value=False),
            patch("app.network.detect.is_linux", return_value=False),
            patch("app.network.detect.is_macos", return_value=False),
        ):
            result = detect_gateway_ip()
            assert result is None

    def test_exception_returns_none(self):
        """异常返回 None。"""
        with patch("app.network.detect.is_windows", side_effect=Exception("test")):
            result = detect_gateway_ip()
            assert result is None

    def test_no_gateway_returns_none(self):
        """未检测到网关返回 None。"""
        with (
            patch("app.network.detect.is_windows", return_value=True),
            patch("app.network.detect.is_linux", return_value=False),
            patch("app.network.detect.is_macos", return_value=False),
            patch("app.network.detect._detect_gateway_windows", return_value=None),
        ):
            result = detect_gateway_ip()
            assert result is None


# ── detect_wifi_ssid ──


class TestDetectWifiSsid:
    """WiFi SSID 检测。"""

    def test_windows_success(self):
        """Windows 成功检测。"""
        with (
            patch("app.network.detect.is_windows", return_value=True),
            patch("app.network.detect.is_linux", return_value=False),
            patch("app.network.detect.is_macos", return_value=False),
            patch("app.network.detect._detect_ssid_windows", return_value="MyWiFi"),
        ):
            result = detect_wifi_ssid()
            assert result == "MyWiFi"

    def test_linux_success(self):
        """Linux 成功检测。"""
        with (
            patch("app.network.detect.is_windows", return_value=False),
            patch("app.network.detect.is_linux", return_value=True),
            patch("app.network.detect.is_macos", return_value=False),
            patch("app.network.detect._detect_ssid_linux", return_value="CampusNet"),
        ):
            result = detect_wifi_ssid()
            assert result == "CampusNet"

    def test_macos_success(self):
        """macOS 成功检测。"""
        with (
            patch("app.network.detect.is_windows", return_value=False),
            patch("app.network.detect.is_linux", return_value=False),
            patch("app.network.detect.is_macos", return_value=True),
            patch("app.network.detect._detect_ssid_darwin", return_value="Library"),
        ):
            result = detect_wifi_ssid()
            assert result == "Library"

    def test_unsupported_platform(self):
        """不支持的平台返回 None。"""
        with (
            patch("app.network.detect.is_windows", return_value=False),
            patch("app.network.detect.is_linux", return_value=False),
            patch("app.network.detect.is_macos", return_value=False),
        ):
            result = detect_wifi_ssid()
            assert result is None

    def test_exception_returns_none(self):
        """异常返回 None。"""
        with patch("app.network.detect.is_windows", side_effect=Exception("test")):
            result = detect_wifi_ssid()
            assert result is None

    def test_no_ssid_returns_none(self):
        """未检测到 SSID 返回 None。"""
        with (
            patch("app.network.detect.is_windows", return_value=True),
            patch("app.network.detect.is_linux", return_value=False),
            patch("app.network.detect.is_macos", return_value=False),
            patch("app.network.detect._detect_ssid_windows", return_value=None),
        ):
            result = detect_wifi_ssid()
            assert result is None
