"""变量解析器 — 处理 {{VAR_NAME}} 模板替换。"""

from __future__ import annotations

import json
import re
from typing import Any

from app.utils.logging import get_logger

from .models import StepError, TaskConfig

logger = get_logger("variable_resolver", side="BACKEND")


class VariableResolver:
    """变量解析器"""

    MAX_DEPTH = 8
    TEMPLATE_PATTERN = re.compile(r"\{\{(\w+)\}\}")

    def __init__(self, config: TaskConfig, template_vars: dict[str, str]):
        self.config = config
        self.template_vars = template_vars
        self.runtime_vars: dict[str, Any] = {
            "url": config.url,
            "name": config.name,
            "description": config.description,
        }
        self._cache: dict[str, str] = {}

    def resolve(
        self, value: Any, depth: int = 0, visited: set[str] | None = None
    ) -> Any:
        """解析变量模板"""
        if not isinstance(value, str):
            return value

        if "{{" not in value:
            return value

        # 检查缓存
        if depth == 0 and value in self._cache:
            return self._cache[value]

        visited = visited or set()
        if depth > self.MAX_DEPTH:
            raise StepError(
                f"变量展开层级超过限制({self.MAX_DEPTH})，请检查变量引用关系"
            )

        def replacer(match: re.Match) -> str:
            var_name = match.group(1)

            # 检查循环引用
            if var_name in visited:
                raise StepError(f"检测到变量循环引用: {var_name}")

            # 按优先级查找变量
            if var_name in self.runtime_vars:
                raw = self.runtime_vars[var_name]
                resolved = (
                    json.dumps(raw, ensure_ascii=False)
                    if not isinstance(raw, str)
                    else raw
                )
            elif var_name in self.template_vars:
                resolved = str(self.template_vars[var_name])
            elif var_name in self.config.variables:
                resolved = self.resolve(
                    self.config.variables[var_name], depth + 1, visited | {var_name}
                )
            else:
                logger.warning("[VariableResolver] 未解析的变量: {}", match.group(0))
                return match.group(0)  # 保留原样

            # 递归解析
            if "{{" in resolved:
                return self.resolve(resolved, depth + 1, visited | {var_name})
            return resolved

        result = self.TEMPLATE_PATTERN.sub(replacer, value)

        # 缓存结果
        if depth == 0:
            self._cache[value] = result

        return result

    def set_runtime_var(self, name: str, value: Any) -> None:
        """设置运行时变量"""
        self.runtime_vars[name] = value
        self._cache.clear()

    def resolve_for_js(self, value: str) -> str:
        """解析变量并进行 JSON 安全编码，用于 JavaScript 嵌入。

        与 resolve() 不同，此方法将解析后的值进行 JSON 编码，
        确保可以安全嵌入 JavaScript 代码而不会产生语法错误。
        示例：password "admin'123" → '"admin\'123"'（合法的 JS 字符串字面量）
        """
        if not isinstance(value, str) or "{{" not in value:
            return value

        def replacer(match: re.Match) -> str:
            resolved = self.resolve(match.group(0))
            # If variable not found, resolve returns the original pattern
            if resolved == match.group(0):
                logger.warning("[VariableResolver] 未解析的变量: {}", match.group(0))
                return '""'  # Default to empty string
            return json.dumps(resolved)

        return self.TEMPLATE_PATTERN.sub(replacer, value)
