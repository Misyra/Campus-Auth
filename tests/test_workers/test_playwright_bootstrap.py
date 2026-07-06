"""Playwright Bootstrap 测试。"""

from __future__ import annotations

import os
import stat
from pathlib import Path

from app.workers.playwright_bootstrap import _verify_chromium_install


class TestVerifyChromiumInstall:
    """Chromium 安装完整性校验。"""

    def test_windows_binary_found(self, tmp_path: Path):
        """Windows 下 chrome.exe 存在且可执行 → 通过。"""
        binary = tmp_path / "chromium-120" / "chrome-win64" / "chrome.exe"
        binary.parent.mkdir(parents=True)
        binary.write_bytes(b"\x00")
        binary.chmod(binary.stat().st_mode | stat.S_IXUSR)
        assert _verify_chromium_install(tmp_path) is True

    def test_linux_binary_found(self, tmp_path: Path):
        """Linux 下 chrome 存在且可执行 → 通过。"""
        binary = tmp_path / "chromium-120" / "chrome-linux" / "chrome"
        binary.parent.mkdir(parents=True)
        binary.write_bytes(b"\x00")
        binary.chmod(binary.stat().st_mode | stat.S_IXUSR)
        assert _verify_chromium_install(tmp_path) is True

    def test_macos_binary_found(self, tmp_path: Path):
        """macOS 下 Chromium 二进制存在且可执行 → 通过。"""
        binary = (
            tmp_path
            / "chromium-120"
            / "chrome-mac"
            / "Chromium.app"
            / "Contents"
            / "MacOS"
            / "Chromium"
        )
        binary.parent.mkdir(parents=True)
        binary.write_bytes(b"\x00")
        binary.chmod(binary.stat().st_mode | stat.S_IXUSR)
        assert _verify_chromium_install(tmp_path) is True

    def test_no_chromium_dir(self, tmp_path: Path):
        """缓存目录为空 → 失败。"""
        assert _verify_chromium_install(tmp_path) is False

    def test_binary_not_executable(self, tmp_path: Path):
        """文件存在但无执行权限 → 失败（仅 Unix，Windows 无执行位概念）。"""
        if os.name == "nt":
            # Windows 上 os.access(X_OK) 对已存在文件始终返回 True，跳过
            return
        binary = tmp_path / "chromium-120" / "chrome-linux" / "chrome"
        binary.parent.mkdir(parents=True)
        binary.write_bytes(b"\x00")
        # 移除所有执行权限
        binary.chmod(
            binary.stat().st_mode & ~(stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        )
        assert _verify_chromium_install(tmp_path) is False

    def test_wrong_chromium_dir_name(self, tmp_path: Path):
        """目录名不匹配 chromium-* 模式 → 失败。"""
        binary = tmp_path / "firefox-120" / "chrome-linux" / "chrome"
        binary.parent.mkdir(parents=True)
        binary.write_bytes(b"\x00")
        binary.chmod(binary.stat().st_mode | stat.S_IXUSR)
        assert _verify_chromium_install(tmp_path) is False

    def test_file_not_directory(self, tmp_path: Path):
        """chromium-* 匹配的是文件而非目录 → 跳过。"""
        fake = tmp_path / "chromium-120"
        fake.write_text("not a dir")
        assert _verify_chromium_install(tmp_path) is False
