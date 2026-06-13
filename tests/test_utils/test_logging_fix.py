"""logging.py 中两个修复点的验证测试

修复内容：
1. _rotate_file 中重新打开文件缺少 buffering=1（应与 _open_file 一致）
2. should_emit 每次调用重建 level_order 字典（应提取为类常量）
"""

from __future__ import annotations

import os
import tempfile
from unittest.mock import MagicMock, patch

from app.utils.logging import DateRotatingSink, LogConfigCenter


class TestRotateFileBuffering:
    """验证 _rotate_file 使用 buffering=1 行缓冲"""

    def test_rotate_file_opens_with_buffering(self, tmp_path):
        """轮转后重新打开的文件应使用 buffering=1（行缓冲）"""
        sink = DateRotatingSink(log_dir=str(tmp_path), file_max_bytes=100)

        # 手动触发一次 write 以打开初始文件
        msg = MagicMock()
        msg.record = {
            "extra": {"source": "backend"},
            "level": MagicMock(name="INFO"),
            "time": MagicMock(timestamp=lambda: 1700000000),
        }
        msg.__str__ = lambda self: "test message"
        msg.record["level"].name = "INFO"
        sink.write(msg)

        # 记录 _open_file 的参数
        opened_args = {}
        original_open = open

        def spy_open(*args, **kwargs):
            opened_args.update(kwargs)
            return original_open(*args, **kwargs)

        # 用大量数据触发轮转
        with patch("builtins.open", side_effect=spy_open):
            # 手动调用 _rotate_file 来检查 open 参数
            sink._rotate_file()

        # 轮转后 open 应包含 buffering=1
        assert opened_args.get("buffering") == 1, (
            f"_rotate_file 重新打开文件时应使用 buffering=1，"
            f"实际参数: {opened_args}"
        )

    def test_open_file_has_buffering(self, tmp_path):
        """_open_file 应使用 buffering=1"""
        sink = DateRotatingSink(log_dir=str(tmp_path))

        opened_args = {}
        original_open = open

        def spy_open(*args, **kwargs):
            opened_args.update(kwargs)
            return original_open(*args, **kwargs)

        log_file = str(tmp_path / "test.log")
        with patch("builtins.open", side_effect=spy_open):
            sink._open_file(log_file)

        assert opened_args.get("buffering") == 1, (
            f"_open_file 应使用 buffering=1，实际参数: {opened_args}"
        )


class TestShouldEmitLevelOrder:
    """验证 should_emit 使用类级别常量而非每次重建字典"""

    def test_level_order_is_class_constant(self):
        """LogConfigCenter 应有 _LEVEL_ORDER 类常量"""
        assert hasattr(LogConfigCenter, "_LEVEL_ORDER"), (
            "LogConfigCenter 缺少 _LEVEL_ORDER 类常量"
        )
        expected = {"DEBUG": 0, "INFO": 1, "WARNING": 2, "ERROR": 3, "CRITICAL": 4}
        assert LogConfigCenter._LEVEL_ORDER == expected

    def test_should_emit_uses_class_constant(self):
        """should_emit 应使用 _LEVEL_ORDER 而非局部变量"""
        import inspect

        source = inspect.getsource(LogConfigCenter.should_emit)
        assert "_LEVEL_ORDER" in source, (
            "should_emit 应引用类常量 _LEVEL_ORDER，而非局部 level_order 字典"
        )

    def test_should_emit_basic_functionality(self):
        """should_emit 基本功能验证"""
        cc = LogConfigCenter.get_instance()
        # 默认全局级别是 INFO
        assert cc.should_emit("backend", "INFO") is True
        assert cc.should_emit("backend", "DEBUG") is False
        assert cc.should_emit("backend", "WARNING") is True
        assert cc.should_emit("backend", "ERROR") is True
        assert cc.should_emit("backend", "CRITICAL") is True
