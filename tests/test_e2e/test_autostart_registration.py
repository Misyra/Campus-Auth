"""开机自启注册 E2E 测试 — Windows VBS 文件真实读写。

验证 AutoStartService 通过 API 启用/禁用自启动时：
- VBS 文件正确写入启动目录（patch APPDATA 指向 tmp_path）
- VBS 内容包含正确的启动命令（python main.py --no-browser --source autostart）
- status() 正确反映启用/禁用状态
- disable() 后 VBS 文件被删除
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# ── 平台守卫 ──

_SKIP_REASON = "Windows VBS 自启动测试仅在 Windows 上运行"


def _vbs_path(appdata_dir: Path) -> Path:
    """根据 APPDATA 根目录计算 VBS 文件路径。"""
    return (
        appdata_dir
        / "Microsoft"
        / "Windows"
        / "Start Menu"
        / "Programs"
        / "Startup"
        / "campus-auth.vbs"
    )


@pytest.mark.skipif(sys.platform != "win32", reason=_SKIP_REASON)
class TestAutoStartRegistration:
    """开机自启注册逻辑 — 真实 VBS 文件读写。"""

    def test_enable_creates_vbs_with_correct_command(
        self, real_app, tmp_path, monkeypatch
    ):
        """启用自启动后 VBS 文件创建在启动目录，内容包含正确启动命令。"""
        client, _ = real_app

        # 将 APPDATA 指向 tmp_path 子目录，避免污染真实启动目录
        fake_appdata = tmp_path / "AppData" / "Roaming"
        fake_appdata.mkdir(parents=True, exist_ok=True)
        monkeypatch.setenv("APPDATA", str(fake_appdata))

        # 绕过 CJK 路径检查（tmp_path 可能包含非 ASCII 字符）
        monkeypatch.setattr(
            "app.services.autostart.AutoStartService._has_cjk_chars",
            staticmethod(lambda path: False),
        )

        vbs_file = _vbs_path(fake_appdata)
        assert not vbs_file.exists(), "测试前 VBS 文件不应存在"

        # 调用启用接口
        resp = client.post("/api/autostart/enable")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True, f"启用自启动失败: {data.get('message', '')}"

        # 验证 VBS 文件确实创建
        assert vbs_file.exists(), f"VBS 文件未创建: {vbs_file}"

        # 验证 VBS 内容（UTF-16 编码）
        content = vbs_file.read_text(encoding="utf-16")
        assert "--no-browser --source autostart" in content, (
            "VBS 内容缺少自启动参数 --no-browser --source autostart"
        )
        assert "main.py" in content, "VBS 内容缺少 main.py 入口"
        assert "WshShell.Run" in content, "VBS 内容缺少 WshShell.Run 调用"
        assert "WScript.Shell" in content, "VBS 内容缺少 WScript.Shell 创建"

    def test_status_reflects_enabled_state(self, real_app, tmp_path, monkeypatch):
        """启用后 status 返回 enabled=True 且 method 包含 VBScript。"""
        client, _ = real_app

        fake_appdata = tmp_path / "AppData" / "Roaming"
        fake_appdata.mkdir(parents=True, exist_ok=True)
        monkeypatch.setenv("APPDATA", str(fake_appdata))
        monkeypatch.setattr(
            "app.services.autostart.AutoStartService._has_cjk_chars",
            staticmethod(lambda path: False),
        )

        # 启用前状态
        resp = client.get("/api/autostart/status")
        assert resp.status_code == 200
        assert resp.json()["enabled"] is False

        # 启用
        resp = client.post("/api/autostart/enable")
        assert resp.json()["success"] is True

        # 启用后状态
        resp = client.get("/api/autostart/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["enabled"] is True
        assert "VBScript" in data["method"] or "VBS" in data["method"].upper()
        assert "campus-auth.vbs" in data["location"]

    def test_disable_removes_vbs_file(self, real_app, tmp_path, monkeypatch):
        """禁用自启动后 VBS 文件被删除。"""
        client, _ = real_app

        fake_appdata = tmp_path / "AppData" / "Roaming"
        fake_appdata.mkdir(parents=True, exist_ok=True)
        monkeypatch.setenv("APPDATA", str(fake_appdata))
        monkeypatch.setattr(
            "app.services.autostart.AutoStartService._has_cjk_chars",
            staticmethod(lambda path: False),
        )

        vbs_file = _vbs_path(fake_appdata)

        # 先启用
        resp = client.post("/api/autostart/enable")
        assert resp.json()["success"] is True
        assert vbs_file.exists()

        # 禁用
        resp = client.post("/api/autostart/disable")
        assert resp.status_code == 200
        assert resp.json()["success"] is True

        # VBS 文件应被删除
        assert not vbs_file.exists(), "禁用后 VBS 文件仍存在"

        # 状态应为已禁用
        resp = client.get("/api/autostart/status")
        assert resp.json()["enabled"] is False

    def test_disable_when_not_enabled_is_idempotent(self, real_app, tmp_path, monkeypatch):
        """未启用时调用 disable 也返回成功（幂等）。"""
        client, _ = real_app

        fake_appdata = tmp_path / "AppData" / "Roaming"
        fake_appdata.mkdir(parents=True, exist_ok=True)
        monkeypatch.setenv("APPDATA", str(fake_appdata))

        # 直接禁用（从未启用）
        resp = client.post("/api/autostart/disable")
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_vbs_contains_python_executable_path(self, real_app, tmp_path, monkeypatch):
        """VBS 内容包含 Python 可执行文件路径（当前解释器或 .venv）。"""
        client, _ = real_app

        fake_appdata = tmp_path / "AppData" / "Roaming"
        fake_appdata.mkdir(parents=True, exist_ok=True)
        monkeypatch.setenv("APPDATA", str(fake_appdata))
        monkeypatch.setattr(
            "app.services.autostart.AutoStartService._has_cjk_chars",
            staticmethod(lambda path: False),
        )

        resp = client.post("/api/autostart/enable")
        assert resp.json()["success"] is True

        vbs_file = _vbs_path(fake_appdata)
        content = vbs_file.read_text(encoding="utf-16")

        # _start_command 返回的路径包含 python 或 .venv
        # 至少应包含 "python" 或 "python.exe" 或 .venv 路径
        import sys as _sys

        current_python = Path(_sys.executable).resolve()
        # VBS 中双引号转义为 ""，直接检查 python 关键字
        assert "python" in content.lower(), (
            f"VBS 内容缺少 python 解释器路径，当前解释器: {current_python}"
        )
