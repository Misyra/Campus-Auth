"""ScriptRunner 扩展测试 — _build_cmd / _load_script_content / detect_available_binaries / get_default_binary

补充 test_script_runner.py 和 test_script_task.py 中未覆盖的部分。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from src.script_runner import (
    ScriptRunner,
    get_default_binary,
    detect_available_binaries,
    DEFAULT_TIMEOUT,
)


# =====================================================================
# get_default_binary
# =====================================================================


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
    def test_py_file_default_binary(self, tmp_path: Path):
        script = tmp_path / "test.py"
        script.write_text('print("hello")')
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

    @patch("src.script_runner.platform.system", return_value="Windows")
    def test_cmd_binary_on_windows(self, _mock_sys, tmp_path: Path):
        script = tmp_path / "test.py"
        script.write_text('print("hi")')
        runner = ScriptRunner(script, binary_path="C:\\Windows\\cmd.exe")
        cmd = runner._build_cmd()
        assert cmd[0] == "C:\\Windows\\cmd.exe"
        assert "/c" in cmd
        # CMD 应使用 call 规避路径特殊字符问题
        assert "call" in cmd[2]

    @patch("src.script_runner.platform.system", return_value="Linux")
    def test_bash_binary_on_linux(self, _mock_sys, tmp_path: Path):
        script = tmp_path / "test.sh"
        script.write_text('echo hi')
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
        script.write_text('print("hi")')
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
        script.write_text(json.dumps({"content": 'print("hello from json")'}), encoding="utf-8")
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
