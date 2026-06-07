"""script_runner 模块测试

覆盖临时文件创建、命令构建等核心逻辑。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from app.workers.script_runner import (
    ScriptRunner,
    get_default_binary,
    detect_available_binaries,
    DEFAULT_TIMEOUT,
)


class TestContentTempFile:
    """JSON 内容脚本临时文件创建测试。"""

    def test_python_ext(self, tmp_path):
        """Python 解释器应生成 .py 后缀临时文件。"""
        runner = ScriptRunner(tmp_path / "test.json", binary_path=sys.executable)
        path = runner._content_temp_file("print('hello')")
        try:
            assert path.endswith(".py")
            assert Path(path).read_text(encoding="utf-8") == "print('hello')"
        finally:
            Path(path).unlink(missing_ok=True)

    def test_unknown_binary_ext(self, tmp_path):
        """未知解释器应生成无后缀临时文件。"""
        runner = ScriptRunner(tmp_path / "test.json", binary_path="/usr/bin/foo")
        path = runner._content_temp_file("some content")
        try:
            # 无后缀，临时文件名只含随机字符
            assert not Path(path).suffix
        finally:
            Path(path).unlink(missing_ok=True)

    def test_temp_file_encoding(self, tmp_path):
        """临时文件应使用 UTF-8 编码写入中文内容。"""
        runner = ScriptRunner(tmp_path / "test.json", binary_path=sys.executable)
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
        runner = ScriptRunner(json_file, binary_path=sys.executable)
        with pytest.raises(ValueError, match="JSON 脚本格式错误"):
            runner._load_script_content()

    def test_non_utf8_json_raises_value_error(self, tmp_path):
        """非 UTF-8 编码的 JSON 文件应抛出 ValueError。"""
        json_file = tmp_path / "gbk.json"
        json_file.write_bytes('{"content": "你好"}'.encode("gbk"))
        runner = ScriptRunner(json_file, binary_path=sys.executable)
        with pytest.raises(ValueError, match="JSON 脚本格式错误"):
            runner._load_script_content()

    def test_valid_json_returns_content(self, tmp_path):
        """合法 JSON 文件应正确返回 content 字段。"""
        json_file = tmp_path / "good.json"
        json_file.write_text('{"content": "echo hello"}', encoding="utf-8")
        runner = ScriptRunner(json_file, binary_path="cmd.exe")
        assert runner._load_script_content() == "echo hello"

    def test_py_file_returns_none(self, tmp_path):
        """.py 文件应返回 None。"""
        py_file = tmp_path / "test.py"
        py_file.write_text("print(1)", encoding="utf-8")
        runner = ScriptRunner(py_file, binary_path=sys.executable)
        assert runner._load_script_content() is None


class TestGetDefaultBinary:
    def test_returns_sys_executable(self):
        assert get_default_binary() == sys.executable


# =====================================================================
# DEFAULT_TIMEOUT
# =====================================================================


class TestDefaultTimeout:
    def test_is_positive(self):
        assert DEFAULT_TIMEOUT > 0

    def test_is_60(self):
        assert DEFAULT_TIMEOUT == 60


# =====================================================================
# detect_available_binaries
# =====================================================================


class TestDetectAvailableBinaries:
    def test_returns_list(self):
        result = detect_available_binaries()
        assert isinstance(result, list)

    def test_contains_python(self):
        result = detect_available_binaries()
        names = [b["name"] for b in result]
        assert "Python" in names

    def test_each_entry_has_required_keys(self):
        result = detect_available_binaries()
        for entry in result:
            assert "name" in entry
            assert "path" in entry
            assert "description" in entry

    def test_python_path_is_sys_executable(self):
        result = detect_available_binaries()
        python_entry = next(b for b in result if b["name"] == "Python")
        assert python_entry["path"] == sys.executable


# =====================================================================
# ScriptRunner._build_cmd
# =====================================================================


class TestScriptRunnerBuildCmd:
    @patch("app.workers.script_runner.platform.system", return_value="Windows")
    def test_py_file_default_binary(self, mock_system, tmp_path: Path):
        script = tmp_path / "test.py"
        runner = ScriptRunner(script, binary_path=sys.executable)
        cmd = runner._build_cmd()
        assert cmd[0] == sys.executable
        assert str(script) in cmd

    def test_json_content_raises_without_script_file(self, tmp_path: Path):
        """JSON 内容脚本不传 script_file 应抛出 RuntimeError。"""
        script = tmp_path / "test.json"
        script.write_text(json.dumps({"content": 'print("hi")'}), encoding="utf-8")
        runner = ScriptRunner(script, binary_path=sys.executable)
        with pytest.raises(RuntimeError, match="临时文件"):
            runner._build_cmd()

    def test_json_content_with_script_file(self, tmp_path: Path):
        """传入 script_file 时应构建正确的文件执行命令。"""
        script = tmp_path / "test.json"
        script.write_text(json.dumps({"content": 'print("hi")'}), encoding="utf-8")
        runner = ScriptRunner(script, binary_path=sys.executable)
        cmd = runner._build_cmd(script_file="/tmp/test.py")
        assert "/tmp/test.py" in cmd
        assert "-c" not in cmd

    def test_json_script_caches_content(self, tmp_path: Path):
        script = tmp_path / "test.json"
        script.write_text(json.dumps({"content": 'print("cached")'}), encoding="utf-8")
        runner = ScriptRunner(script, binary_path=sys.executable)
        # 第一次加载
        content1 = runner._load_script_content()
        # 修改文件内容
        script.write_text(json.dumps({"content": 'print("changed")'}), encoding="utf-8")
        # 第二次应返回缓存
        content2 = runner._load_script_content()
        assert content1 == content2 == 'print("cached")'

    def test_json_script_missing_content(self, tmp_path: Path):
        script = tmp_path / "test.json"
        script.write_text(json.dumps({"name": "no content"}), encoding="utf-8")
        runner = ScriptRunner(script, binary_path=sys.executable)
        content = runner._load_script_content()
        assert content == ""

    def test_invalid_json_raises_value_error(self, tmp_path: Path):
        """格式错误的 JSON 应抛出 ValueError，不再静默降级。"""
        script = tmp_path / "bad.json"
        script.write_text("not json {{{", encoding="utf-8")
        runner = ScriptRunner(script, binary_path=sys.executable)
        with pytest.raises(ValueError, match="JSON 脚本格式错误"):
            runner._load_script_content()

    @patch("app.workers.script_runner.platform.system", return_value="Windows")
    def test_cmd_binary_on_windows(self, _mock_sys, tmp_path: Path):
        script = tmp_path / "test.py"
        script.write_text('print("hi")', encoding="utf-8")
        runner = ScriptRunner(script, binary_path="C:\\Windows\\cmd.exe")
        cmd = runner._build_cmd()
        assert cmd[0] == "C:\\Windows\\cmd.exe"
        assert "/c" in cmd
        # CMD 应使用 call 规避路径特殊字符问题
        assert "call" in cmd[2]

    @patch("app.workers.script_runner.platform.system", return_value="Linux")
    def test_bash_binary_on_linux(self, _mock_sys, tmp_path: Path):
        script = tmp_path / "test.sh"
        script.write_text("echo hi", encoding="utf-8")
        runner = ScriptRunner(script, binary_path="/bin/bash")
        cmd = runner._build_cmd()
        assert cmd[0] == "/bin/bash"
        assert str(script) in cmd


# =====================================================================
# ScriptRunner.run — 补充边界场景
# =====================================================================


class TestScriptRunnerRunExtra:
    def test_empty_binary_path_falls_back_to_default(self, tmp_path: Path):
        script = tmp_path / "test.py"
        script.write_text('print("hi")', encoding="utf-8")
        runner = ScriptRunner(script, binary_path="")
        # 空字符串会 fallback 到 sys.executable，不应失败
        ok, _ = runner.run()
        assert ok is True

    def test_run_with_large_output(self, tmp_path: Path):
        """输出超过 500 字符时应截断"""
        script = tmp_path / "loud.py"
        script.write_text('print("x" * 1000)', encoding="utf-8")
        runner = ScriptRunner(script, timeout=10)
        ok, msg = runner.run()
        assert ok is True
        assert len(msg) <= 500

    def test_json_content_run_uses_temp_file(self, tmp_path: Path):
        """JSON 内容脚本应通过临时文件执行，避免引号问题。"""
        script = tmp_path / "test.json"
        script.write_text(
            json.dumps({"content": 'print("hello from json")'}), encoding="utf-8"
        )
        runner = ScriptRunner(script, binary_path=sys.executable)
        ok, msg = runner.run()
        assert ok is True
        assert "hello from json" in msg

    def test_json_content_with_double_quotes(self, tmp_path: Path):
        """JSON 内容包含双引号时应正确执行（验证临时文件方案）。"""
        script = tmp_path / "test.json"
        content = 'print("It works!")'
        script.write_text(json.dumps({"content": content}), encoding="utf-8")
        runner = ScriptRunner(script, binary_path=sys.executable)
        ok, msg = runner.run()
        assert ok is True
        assert "It works!" in msg
