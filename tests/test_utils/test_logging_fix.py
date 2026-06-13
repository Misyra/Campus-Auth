"""logging.py 中修复点的验证测试

修复内容：
1. should_emit 使用类级别常量 _LEVEL_ORDER
"""

from __future__ import annotations

from app.utils.logging import LogConfigCenter


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
