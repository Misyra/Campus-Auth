"""常量存在性与代码规范测试"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest


class TestWSConstant:
    """WS_DRAIN_INTERVAL_SECONDS 常量测试"""

    def test_ws_drain_interval_constant_exists(self):
        """monitor_service 中应存在 WS_DRAIN_INTERVAL_SECONDS 常量"""
        from backend.monitor_service import WS_DRAIN_INTERVAL_SECONDS

        assert WS_DRAIN_INTERVAL_SECONDS == 0.05


class TestLoginConstant:
    """LOGIN_SUCCESS_SETTLE_SECONDS 常量测试"""

    def test_login_settle_seconds_constant_exists(self):
        """login 模块中应存在 LOGIN_SUCCESS_SETTLE_SECONDS 常量"""
        from src.utils.login import LOGIN_SUCCESS_SETTLE_SECONDS

        assert LOGIN_SUCCESS_SETTLE_SECONDS == 2


class TestNoFunctionLocalImport:
    """函数内不应有局部 import 语句"""

    def test_no_function_local_json_import(self):
        """backend/task_service.py 中不应有函数内的 import 语句"""
        source_path = Path(__file__).parent.parent / "backend" / "task_service.py"
        source = source_path.read_text(encoding="utf-8")
        tree = ast.parse(source)

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for child in ast.walk(node):
                    if isinstance(child, (ast.Import, ast.ImportFrom)):
                        pytest.fail(
                            f"函数 '{node.name}' (行 {node.lineno}) "
                            f"中存在局部 import (行 {child.lineno})，"
                            f"应移至模块顶层"
                        )
