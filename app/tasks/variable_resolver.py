"""变量解析器 — 处理 {{VAR_NAME}} 模板替换。"""

from __future__ import annotations

import json
import re
from typing import Any

from app.utils.logging import get_logger

from .models import StepError, TaskConfig

logger = get_logger("variable_resolver", source="backend")


class VariableResolver:
    """变量解析器"""

    MAX_DEPTH = 8
    # 正则匹配 {{VAR_NAME}} 模板，无法用 str.replace 替代（需要捕获组和 re.sub 回调）
    TEMPLATE_PATTERN = re.compile(r"\{\{(\w+)\}\}")
    _CACHE_MAXSIZE = 256

    def __init__(self, config: TaskConfig, template_vars: dict[str, str]):
        self.config = config
        self.template_vars = template_vars
        self.runtime_vars: dict[str, Any] = {
            "url": config.url,
            "name": config.name,
            "description": config.description,
        }
        self._cache: dict[str, str] = {}
        self._cache_version: int = 0

    # ── 统一查找链 ──

    def _lookup(self, name: str, depth: int, visited: set[str]) -> str | None:
        """三层变量查找：runtime → template → config.variables。

        config.variables 的值会递归解析（支持链式引用如 name → user → REAL_USER）。
        非字符串值自动序列化为 JSON 字符串。

        Returns:
            解析后的字符串值，未找到返回 None（区分"找到空值"和"未找到"）

        Raises:
            StepError: 循环引用或深度超限
        """
        # 1. runtime_vars（eval 步骤结果、已注入的任务变量等）
        if name in self.runtime_vars:
            return self._to_str(self.runtime_vars[name])

        # 2. template_vars（登录凭证、ISP 等外部传入）
        if name in self.template_vars:
            return str(self.template_vars[name])

        # 3. config.variables（任务级中间变量，递归解析）
        if name in self.config.variables:
            return self.resolve(
                self.config.variables[name], depth + 1, visited | {name}
            )

        return None

    @staticmethod
    def _to_str(value: Any) -> str:
        """将变量值转为字符串，非字符串类型序列化为 JSON。"""
        if value is None:
            return ""
        if not isinstance(value, str):
            try:
                return json.dumps(value, ensure_ascii=False)
            except TypeError:
                return str(value)
        return value

    # ── 公开 API ──

    def resolve(
        self, value: Any, depth: int = 0, visited: set[str] | None = None
    ) -> Any:
        """解析变量模板（正则全局替换 + 递归展开）。"""
        if not isinstance(value, str):
            return value

        if "{{" not in value:
            return value

        # 检查缓存（key 包含版本号，避免外部修改后返回过期结果）
        cache_key = (self._cache_version, value) if depth == 0 else None
        if cache_key is not None and cache_key in self._cache:
            return self._cache[cache_key]

        visited = visited or set()
        if depth > self.MAX_DEPTH:
            raise StepError(
                f"变量展开层级超过限制({self.MAX_DEPTH})，请检查变量引用关系"
            )

        def replacer(match: re.Match) -> str:
            var_name = match.group(1)
            if var_name in visited:
                raise StepError(f"检测到变量循环引用: {var_name}")

            resolved = self._lookup(var_name, depth, visited)
            if resolved is None:
                logger.warning("[var] 未解析的变量: {}", match.group(0))
                return match.group(0)

            # 递归解析嵌套变量
            if "{{" in resolved:
                return self.resolve(resolved, depth + 1, visited | {var_name})
            return resolved

        result = self.TEMPLATE_PATTERN.sub(replacer, value)

        if cache_key is not None:
            if len(self._cache) >= self._CACHE_MAXSIZE:
                self._cache.clear()
            self._cache[cache_key] = result

        return result

    def resolve_for_js(self, value: str) -> str:
        """解析变量并进行 JSON 安全编码，用于 JavaScript 嵌入。

        与 resolve() 使用相同的三层查找优先级（runtime → template → config.variables），
        差异在于：
        - 白名单替换（非正则全局匹配），避免误处理 JS 代码中的 {{}} 语法
        - 变量值经 JSON 编码后嵌入，确保不会因引号/反斜杠等特殊字符产生语法错误
        """
        if not isinstance(value, str) or "{{" not in value:
            return value

        # 构建白名单：config.variables（递归解析）→ template_vars → runtime_vars
        # B19 修复：所有变量值都先递归解析，避免嵌套 {{...}} 在 JSON 编码后被二次替换
        known_vars: dict[str, Any] = {}
        for k, v in self.config.variables.items():
            known_vars[k] = self.resolve(v) if isinstance(v, str) else v
        for k, v in self.template_vars.items():
            known_vars[k] = self.resolve(v) if isinstance(v, str) else v
        for k, v in self.runtime_vars.items():
            known_vars[k] = self.resolve(v) if isinstance(v, str) else v

        for name, raw in known_vars.items():
            placeholder = f"{{{{{name}}}}}"
            if placeholder in value:
                value = value.replace(placeholder, json.dumps(raw, ensure_ascii=False))

        return value

    def set_runtime_var(self, name: str, value: Any) -> None:
        """设置运行时变量"""
        self.runtime_vars[name] = value
        self._cache.clear()
        self._cache_version += 1
