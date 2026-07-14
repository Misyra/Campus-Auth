"""脚本执行 E2E 测试 — 通过 API 真实执行 py/bat/ps1/sh 子进程。

验证 ScriptRunner + ShellCommandPolicy 在真实子进程场景下的行为：
- 各脚本类型使用正确的解释器（py→python, bat→cmd, ps1→powershell, sh→sh）
- 脚本输出正确传递
- 失败退出码与错误信息正确传递
- 超时机制正确工作
"""

import sys
import pytest

pytestmark = pytest.mark.slow

import shutil

# ── 辅助函数 ──


def _save_script(client, task_id: str, script_type: str, content: str, name: str = ""):
    """通过 API 保存脚本任务，返回响应体。"""
    payload = {
        "type": script_type,
        "name": name or f"E2E {script_type} 脚本",
        "description": "E2E 测试脚本",
        "content": content,
    }
    resp = client.put(f"/api/scripts/{task_id}", json=payload)
    assert resp.status_code == 200, f"保存脚本失败: {resp.text}"
    return resp.json()


def _run_script(client, task_id: str):
    """通过 API 执行脚本任务，返回 (success, message)。"""
    resp = client.post(f"/api/scripts/{task_id}/run")
    assert resp.status_code == 200, f"执行脚本失败: {resp.text}"
    data = resp.json()
    return data["success"], data["message"]


# ── 测试类 ──


class TestScriptExecution:
    """验证脚本任务通过 API 真实执行子进程。"""

    def test_py_script_output(self, real_app):
        """py 脚本通过项目 Python 解释器执行并返回 stdout。"""
        client, _ = real_app
        _save_script(client, "e2e_py", "py", 'print("hello from py")')
        success, message = _run_script(client, "e2e_py")
        assert success is True
        assert "hello from py" in message

    @pytest.mark.skipif(sys.platform != "win32", reason="bat 脚本仅 Windows 可用")
    def test_bat_script_output(self, real_app):
        """bat 脚本通过 cmd.exe 执行并返回 stdout。"""
        client, _ = real_app
        _save_script(client, "e2e_bat", "bat", "@echo hello from bat")
        success, message = _run_script(client, "e2e_bat")
        assert success is True
        assert "hello from bat" in message
    @pytest.mark.skipif(sys.platform != "win32", reason="ps1 脚本仅 Windows 可用")
    def test_ps1_script_output(self, real_app):
        """ps1 脚本通过 PowerShell 执行并返回 stdout。"""
        client, _ = real_app
        _save_script(client, "e2e_ps1", "ps1", 'Write-Output "hello from ps1"')
        success, message = _run_script(client, "e2e_ps1")
        assert success is True
        assert "hello from ps1" in message

    def test_sh_script_behavior(self, real_app):
        """sh 脚本：git bash 存在则验证输出，不存在则验证报错。"""
        client, _ = real_app
        _save_script(client, "e2e_sh", "sh", 'echo "hello from sh"')
        success, message = _run_script(client, "e2e_sh")

        if shutil.which("sh"):
            # git bash 或 WSL 提供了 sh
            assert success is True
            assert "hello from sh" in message
        else:
            # Windows 上无 sh，应报错
            assert success is False
            assert "不存在" in message or "sh" in message.lower()

    def test_py_script_failure_exitcode(self, real_app):
        """脚本失败时退出码非零，错误信息正确传递。"""
        client, _ = real_app
        # 故意引发异常，exit code = 1
        _save_script(client, "e2e_fail", "py", "import sys; sys.exit(1)")
        success, message = _run_script(client, "e2e_fail")
        assert success is False
        # 失败时返回 stderr 或 stdout，或 "(无输出, exit code 1)"
        assert "exit code 1" in message or message.strip() != ""

    def test_py_script_stderr_output(self, real_app):
        """脚本写入 stderr 时，失败信息从 stderr 读取。"""
        client, _ = real_app
        _save_script(
            client,
            "e2e_stderr",
            "py",
            'import sys; sys.stderr.write("error_marker_xyz\\n"); sys.exit(2)',
        )
        success, message = _run_script(client, "e2e_stderr")
        assert success is False
        assert "error_marker_xyz" in message

    def test_script_timeout(self, real_app):
        """脚本超时机制：超时后返回超时错误信息。

        conftest 的 settings.json 中 script_timeout=10，
        写一个 sleep 30 的脚本验证超时。
        """
        client, _ = real_app
        _save_script(
            client,
            "e2e_timeout",
            "py",
            "import time; time.sleep(30)",
        )
        success, message = _run_script(client, "e2e_timeout")
        assert success is False
        assert "超时" in message

    def test_exe_task_nonexistent_path(self, real_app):
        """exe 任务路径不存在时返回失败。"""
        client, _ = real_app
        payload = {
            "type": "exe",
            "name": "E2E exe 测试",
            "description": "不存在的 exe",
            "path": "Z:/nonexistent/path/to/exe.exe",
        }
        resp = client.put("/api/scripts/e2e_exe", json=payload)
        assert resp.status_code == 200
        success, message = _run_script(client, "e2e_exe")
        assert success is False
        assert "不存在" in message or "失败" in message

    def test_py_script_unicode_output(self, real_app):
        """py 脚本输出中文字符时正确传递。"""
        client, _ = real_app
        _save_script(client, "e2e_unicode", "py", 'print("中文输出测试")')
        success, message = _run_script(client, "e2e_unicode")
        assert success is True
        assert "中文输出测试" in message
