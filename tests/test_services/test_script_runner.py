"""script_runner 模块测试

覆盖临时文件创建、命令构建等核心逻辑。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.workers.script_runner import (
    DEFAULT_TIMEOUT,
    ScriptRunner,
)


class TestContentTempFile:
    """脚本类型临时文件创建测试。"""

    def test_python_ext(self, tmp_path):
        """script_type="py" 应生成 .py 后缀临时文件。"""
        runner = ScriptRunner(tmp_path / "test.json", script_type="py")
        path = runner._content_temp_file("print('hello')")
        try:
            assert path.endswith(".py")
            assert Path(path).read_text(encoding="utf-8") == "print('hello')"
        finally:
            Path(path).unlink(missing_ok=True)

    def test_bat_ext(self, tmp_path):
        """script_type="bat" 应生成 .bat 后缀临时文件。"""
        runner = ScriptRunner(tmp_path / "test.json", script_type="bat")
        path = runner._content_temp_file("echo hello")
        try:
            assert path.endswith(".bat")
        finally:
            Path(path).unlink(missing_ok=True)

    def test_sh_ext(self, tmp_path):
        """script_type="sh" 应生成 .sh 后缀临时文件。"""
        runner = ScriptRunner(tmp_path / "test.json", script_type="sh")
        path = runner._content_temp_file("echo hello")
        try:
            assert path.endswith(".sh")
        finally:
            Path(path).unlink(missing_ok=True)

    def test_ps1_ext(self, tmp_path):
        """script_type="ps1" 应生成 .ps1 后缀临时文件。"""
        runner = ScriptRunner(tmp_path / "test.json", script_type="ps1")
        path = runner._content_temp_file("Write-Host hello")
        try:
            assert path.endswith(".ps1")
        finally:
            Path(path).unlink(missing_ok=True)

    def test_unknown_type_empty_ext(self, tmp_path):
        """未知 script_type 应生成无后缀临时文件。"""
        runner = ScriptRunner(tmp_path / "test.json", script_type="unknown")
        path = runner._content_temp_file("some content")
        try:
            assert not Path(path).suffix
        finally:
            Path(path).unlink(missing_ok=True)

    def test_temp_file_encoding(self, tmp_path):
        """临时文件应使用 UTF-8 编码写入中文内容。"""
        runner = ScriptRunner(tmp_path / "test.json", script_type="py")
        content = "print('你好世界')"
        path = runner._content_temp_file(content)
        try:
            assert Path(path).read_text(encoding="utf-8") == content
        finally:
            Path(path).unlink(missing_ok=True)


class TestLoadScriptContent:
    """_load_script_content JSON 解析测试。"""

    def test_invalid_json_raises_value_error(self, tmp_path):
        """格式错误的 JSON 文件应抛出 ValueError。"""
        json_file = tmp_path / "bad.json"
        json_file.write_text("{invalid json}", encoding="utf-8")
        runner = ScriptRunner(json_file, script_type="py")
        with pytest.raises(ValueError, match="JSON 脚本格式错误"):
            runner._load_script_content()

    def test_non_utf8_json_raises_value_error(self, tmp_path):
        """非 UTF-8 编码的 JSON 文件应抛出 ValueError。"""
        json_file = tmp_path / "gbk.json"
        json_file.write_bytes('{"content": "你好"}'.encode("gbk"))
        runner = ScriptRunner(json_file, script_type="py")
        with pytest.raises(ValueError, match="JSON 脚本格式错误"):
            runner._load_script_content()

    def test_valid_json_returns_content(self, tmp_path):
        """合法 JSON 文件应正确返回 content 字段。"""
        json_file = tmp_path / "good.json"
        json_file.write_text('{"content": "echo hello"}', encoding="utf-8")
        runner = ScriptRunner(json_file, script_type="bat")
        assert runner._load_script_content() == "echo hello"

    def test_non_json_file_returns_none(self, tmp_path):
        """非 JSON 文件应返回 None。"""
        py_file = tmp_path / "test.py"
        py_file.write_text("print(1)", encoding="utf-8")
        runner = ScriptRunner(py_file, script_type="py")
        assert runner._load_script_content() is None


# =====================================================================
# DEFAULT_TIMEOUT
# =====================================================================


class TestDefaultTimeout:
    def test_is_positive(self):
        assert DEFAULT_TIMEOUT > 0

    def test_is_60(self):
        assert DEFAULT_TIMEOUT == 60


# =====================================================================
# ScriptRunner._build_cmd
# =====================================================================


class TestScriptRunnerBuildCmd:
    def test_py_type(self, tmp_path: Path):
        """script_type="py" 应使用 sys.executable。"""
        script = tmp_path / "test.py"
        runner = ScriptRunner(script, script_type="py")
        cmd = runner._build_cmd(script_file=str(script))
        assert cmd[0] == sys.executable
        assert str(script) in cmd

    def test_bat_type(self, tmp_path: Path):
        """script_type="bat" 应使用 cmd.exe /c。"""
        script = tmp_path / "test.bat"
        runner = ScriptRunner(script, script_type="bat")
        cmd = runner._build_cmd(script_file=str(script))
        assert cmd[0] == "cmd.exe"
        assert "/c" in cmd
        assert str(script) in cmd

    def test_ps1_type(self, tmp_path: Path):
        """script_type="ps1" 应使用 powershell.exe -NoProfile -ExecutionPolicy Bypass -File。"""
        script = tmp_path / "test.ps1"
        runner = ScriptRunner(script, script_type="ps1")
        cmd = runner._build_cmd(script_file=str(script))
        assert cmd[0] == "powershell.exe"
        assert "-NoProfile" in cmd
        assert "-ExecutionPolicy" in cmd
        assert "Bypass" in cmd
        assert "-File" in cmd
        assert str(script) in cmd

    def test_sh_type(self, tmp_path: Path):
        """script_type="sh" 应使用 sh。"""
        script = tmp_path / "test.sh"
        runner = ScriptRunner(script, script_type="sh")
        cmd = runner._build_cmd(script_file=str(script))
        assert cmd[0] == "sh"
        assert str(script) in cmd

    def test_unsupported_type_raises(self, tmp_path: Path):
        """不支持的 script_type 应抛出 ValueError。"""
        script = tmp_path / "test.xyz"
        runner = ScriptRunner(script, script_type="xyz")
        with pytest.raises(ValueError, match="不支持的 script_type"):
            runner._build_cmd(script_file=str(script))

    def test_json_content_with_script_file(self, tmp_path: Path):
        """传入 script_file 时应构建正确的文件执行命令。"""
        script = tmp_path / "test.json"
        script.write_text(json.dumps({"content": 'print("hi")'}), encoding="utf-8")
        runner = ScriptRunner(script, script_type="py")
        cmd = runner._build_cmd(script_file="/tmp/test.py")
        assert "/tmp/test.py" in cmd

    def test_json_script_caches_content(self, tmp_path: Path):
        """JSON 内容应被缓存，文件修改后仍返回首次读取的值。"""
        script = tmp_path / "test.json"
        script.write_text(json.dumps({"content": 'print("cached")'}), encoding="utf-8")
        runner = ScriptRunner(script, script_type="py")
        content1 = runner._load_script_content()
        script.write_text(json.dumps({"content": 'print("changed")'}), encoding="utf-8")
        content2 = runner._load_script_content()
        assert content1 == content2 == 'print("cached")'

    def test_json_script_missing_content(self, tmp_path: Path):
        """JSON 中无 content 字段时应返回空字符串。"""
        script = tmp_path / "test.json"
        script.write_text(json.dumps({"name": "no content"}), encoding="utf-8")
        runner = ScriptRunner(script, script_type="py")
        content = runner._load_script_content()
        assert content == ""

    def test_invalid_json_raises_value_error(self, tmp_path: Path):
        """格式错误的 JSON 应抛出 ValueError，不再静默降级。"""
        script = tmp_path / "bad.json"
        script.write_text("not json {{{", encoding="utf-8")
        runner = ScriptRunner(script, script_type="py")
        with pytest.raises(ValueError, match="JSON 脚本格式错误"):
            runner._load_script_content()


# =====================================================================
# ScriptRunner.run — 补充边界场景
# =====================================================================


class TestScriptRunnerRunExtra:
    def test_run_py_type(self, tmp_path: Path):
        """script_type="py" 应正常执行 Python 脚本。"""
        script = tmp_path / "test.py"
        script.write_text('print("hi")', encoding="utf-8")
        runner = ScriptRunner(script, script_type="py")
        ok, _ = runner.run()
        assert ok is True

    def test_run_with_large_output(self, tmp_path: Path):
        """输出超过 500 字符时应截断"""
        script = tmp_path / "loud.py"
        script.write_text('print("x" * 1000)', encoding="utf-8")
        runner = ScriptRunner(script, timeout=10, script_type="py")
        ok, msg = runner.run()
        assert ok is True
        assert len(msg) <= 500

    def test_json_content_run_uses_temp_file(self, tmp_path: Path):
        """JSON 内容脚本应通过临时文件执行，避免引号问题。"""
        script = tmp_path / "test.json"
        script.write_text(
            json.dumps({"content": 'print("hello from json")'}), encoding="utf-8"
        )
        runner = ScriptRunner(script, script_type="py")
        ok, msg = runner.run()
        assert ok is True
        assert "hello from json" in msg

    def test_json_content_with_double_quotes(self, tmp_path: Path):
        """JSON 内容包含双引号时应正确执行（验证临时文件方案）。"""
        script = tmp_path / "test.json"
        content = 'print("It works!")'
        script.write_text(json.dumps({"content": content}), encoding="utf-8")
        runner = ScriptRunner(script, script_type="py")
        ok, msg = runner.run()
        assert ok is True
        assert "It works!" in msg


# =====================================================================
# ScriptRunner._run_exe
# =====================================================================


class TestRunExe:
    """_run_exe 方法测试。"""

    def test_run_exe_success(self, tmp_path: Path):
        """启动存在的 exe 应返回成功。"""
        exe = tmp_path / "dummy.exe"
        exe.write_text("", encoding="utf-8")
        runner = ScriptRunner(tmp_path / "test.json", script_type="exe")
        with patch("app.workers.script_runner.subprocess.Popen") as mock_popen:
            mock_popen.return_value = MagicMock()
            ok, msg = runner._run_exe(str(exe))
        assert ok is True
        assert "已启动" in msg

    def test_run_exe_file_not_found(self, tmp_path: Path):
        """启动不存在的 exe 应返回失败。"""
        runner = ScriptRunner(tmp_path / "test.json", script_type="exe")
        ok, msg = runner._run_exe("/nonexistent/path/app.exe")
        assert ok is False
        assert "文件不存在" in msg

    def test_run_exe_permission_error(self, tmp_path: Path):
        """权限不足时应返回失败。"""
        runner = ScriptRunner(tmp_path / "test.json", script_type="exe")
        with patch(
            "app.workers.script_runner.subprocess.Popen",
            side_effect=PermissionError("denied"),
        ):
            ok, msg = runner._run_exe("/some/app.exe")
        assert ok is False
        assert "权限不足" in msg

    def test_run_exe_generic_exception(self, tmp_path: Path):
        """其他异常应返回失败。"""
        runner = ScriptRunner(tmp_path / "test.json", script_type="exe")
        with patch(
            "app.workers.script_runner.subprocess.Popen",
            side_effect=OSError("unexpected"),
        ):
            ok, msg = runner._run_exe("/some/app.exe")
        assert ok is False
        assert "启动失败" in msg


# =====================================================================
# ScriptRunner.run — exe 类型集成
# =====================================================================


class TestRunExeIntegration:
    """exe 类型 run() 集成测试。"""

    def test_run_exe_missing_path_field(self, tmp_path: Path):
        """JSON 中缺少 path 字段应返回失败。"""
        script = tmp_path / "test.json"
        script.write_text(json.dumps({"type": "exe", "name": "test"}), encoding="utf-8")
        runner = ScriptRunner(script, script_type="exe")
        ok, msg = runner.run()
        assert ok is False
        assert "path" in msg

    def test_run_unsupported_type(self, tmp_path: Path):
        """不支持的 script_type 应返回失败。"""
        script = tmp_path / "test.xyz"
        script.write_text("content", encoding="utf-8")
        runner = ScriptRunner(script, script_type="xyz")
        ok, msg = runner.run()
        assert ok is False
        assert "不支持" in msg
