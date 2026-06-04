"""script_runner 模块测试

覆盖临时文件创建、命令构建等核心逻辑。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from src.script_runner import ScriptRunner


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
