"""
任务执行器 v2 - 标准化任务处理模块

提供标准化的任务执行流程，支持多种步骤类型，内置完善的验证和错误处理机制。
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger("task_executor")

# 任务ID验证正则
TASK_ID_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")


class TaskError(Exception):
    """任务执行错误"""

    pass


class StepError(TaskError):
    """步骤执行错误"""

    def __init__(
        self, message: str, step_id: str | None = None, step_type: str | None = None
    ):
        super().__init__(message)
        self.step_id = step_id
        self.step_type = step_type


class ValidationError(TaskError):
    """任务验证错误"""

    pass


class StepType(str, Enum):
    """标准步骤类型"""

    NAVIGATE = "navigate"
    INPUT = "input"
    CLICK = "click"
    SELECT = "select"
    WAIT = "wait"
    WAIT_URL = "wait_url"
    EVAL = "eval"
    CUSTOM_JS = "custom_js"
    SCREENSHOT = "screenshot"
    SLEEP = "sleep"


class ConditionType(str, Enum):
    """条件类型"""

    VARIABLE = "variable"
    URL_CONTAINS = "url_contains"
    URL_MATCHES = "url_matches"
    ELEMENT_EXISTS = "element_exists"
    JS_EXPRESSION = "js_expression"


@dataclass
class StepConfig:
    """步骤配置"""

    id: str
    type: str
    description: str = ""
    timeout: int | None = None
    # 各类型专用参数
    url: str | None = None
    selector: str | None = None
    value: str | None = None
    pattern: str | None = None
    script: str | None = None
    store_as: str | None = None
    clear: bool = True
    wait_until: str = "networkidle"
    path: str | None = None
    duration: int = 1000  # sleep duration in ms
    # 扩展参数
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StepConfig:
        """从字典创建步骤配置"""
        base_fields = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        extra_fields = {
            k: v for k, v in data.items() if k not in cls.__dataclass_fields__
        }
        return cls(**base_fields, extra=extra_fields)


@dataclass
class ConditionConfig:
    """条件配置"""

    type: str
    variable: str | None = None
    value: Any = None
    pattern: str | None = None
    selector: str | None = None
    script: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ConditionConfig:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class TaskConfig:
    """任务配置"""

    name: str = "未命名任务"
    description: str = ""
    version: str = "1.0.0"
    url: str = ""
    timeout: int = 30000
    variables: dict[str, str] = field(default_factory=dict)
    steps: list[StepConfig] = field(default_factory=list)
    success_conditions: list[ConditionConfig] = field(default_factory=list)
    on_success: dict[str, Any] = field(default_factory=dict)
    on_failure: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TaskConfig:
        """从字典创建任务配置"""
        return cls(
            name=data.get("name", "未命名任务"),
            description=data.get("description", ""),
            version=data.get("version", "1.0.0"),
            url=data.get("url", ""),
            timeout=data.get("timeout", 30000),
            variables=data.get("variables", {}),
            steps=[StepConfig.from_dict(s) for s in data.get("steps", [])],
            success_conditions=[
                ConditionConfig.from_dict(c) for c in data.get("success_conditions", [])
            ],
            on_success=data.get("on_success", {}),
            on_failure=data.get("on_failure", {}),
            metadata=data.get("metadata", {}),
        )


class VariableResolver:
    """变量解析器"""

    MAX_DEPTH = 8
    TEMPLATE_PATTERN = re.compile(r"\{\{(\w+)\}\}")

    def __init__(self, config: TaskConfig, env_vars: dict[str, str]):
        self.config = config
        self.env_vars = env_vars
        self.runtime_vars: dict[str, Any] = {
            "url": config.url,
            "name": config.name,
            "description": config.description,
            "version": config.version,
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
        if depth > self.MAX_DEPTH * 2:
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
                resolved = str(self.runtime_vars[var_name])
            elif var_name in self.env_vars:
                resolved = str(self.env_vars[var_name])
            elif var_name in self.config.variables:
                resolved = self.resolve(
                    self.config.variables[var_name], depth + 1, visited | {var_name}
                )
            else:
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


class StepHandler(ABC):
    """步骤处理器基类"""

    @property
    @abstractmethod
    def step_type(self) -> str:
        """支持的步骤类型"""
        pass

    @abstractmethod
    async def execute(
        self, page, step: StepConfig, resolver: VariableResolver
    ) -> tuple[bool, str]:
        """执行步骤

        Returns:
            (success, message)
        """
        pass

    def resolve_params(
        self, step: StepConfig, resolver: VariableResolver
    ) -> dict[str, Any]:
        """解析步骤参数"""
        params = {}
        for key, value in step.__dict__.items():
            if key != "extra" and value is not None:
                params[key] = resolver.resolve(value)
        for key, value in step.extra.items():
            params[key] = resolver.resolve(value)
        return params


class NavigateHandler(StepHandler):
    """导航步骤处理器"""

    @property
    def step_type(self) -> str:
        return StepType.NAVIGATE

    async def execute(
        self, page, step: StepConfig, resolver: VariableResolver
    ) -> tuple[bool, str]:
        params = self.resolve_params(step, resolver)
        url = params.get("url", "")
        wait_until = params.get("wait_until", "networkidle")
        timeout = step.timeout or 30000

        if not url:
            return False, "导航地址不能为空"

        logger.info(f"[navigate] url={url}, wait_until={wait_until}")
        await page.goto(url, wait_until=wait_until, timeout=timeout)
        return True, ""


class InputHandler(StepHandler):
    """输入步骤处理器"""

    @property
    def step_type(self) -> str:
        return StepType.INPUT

    async def execute(
        self, page, step: StepConfig, resolver: VariableResolver
    ) -> tuple[bool, str]:
        params = self.resolve_params(step, resolver)
        selector = params.get("selector", "")
        value = params.get("value", "")
        clear = params.get("clear", True)
        timeout = step.timeout or 5000

        if not selector:
            return False, "输入步骤需要 selector"

        logger.info(f"[input] selector={selector}, clear={clear}")

        # 等待并查找元素
        element = await self._find_element(page, selector, timeout)
        if not element:
            return False, f"未找到输入元素: {selector}"

        if clear:
            await element.fill("", timeout=timeout)
        await element.fill(value, timeout=timeout)
        return True, ""

    async def _find_element(self, page, selector: str, timeout: int):
        """查找元素（支持多个候选选择器）"""
        candidates = [s.strip() for s in selector.split(",") if s.strip()]
        deadline = time.monotonic() + timeout / 1000

        while time.monotonic() < deadline:
            for candidate in candidates:
                try:
                    locator = page.locator(candidate)
                    if await locator.count() > 0:
                        element = locator.first
                        if await element.is_visible(timeout=100):
                            return element
                except Exception:
                    continue
            await page.wait_for_timeout(100)

        return None


class ClickHandler(StepHandler):
    """点击步骤处理器"""

    @property
    def step_type(self) -> str:
        return StepType.CLICK

    async def execute(
        self, page, step: StepConfig, resolver: VariableResolver
    ) -> tuple[bool, str]:
        params = self.resolve_params(step, resolver)
        selector = params.get("selector", "")
        timeout = step.timeout or 5000

        if not selector:
            return False, "点击步骤需要 selector"

        logger.info(f"[click] selector={selector}")

        element = await self._find_element(page, selector, timeout)
        if not element:
            return False, f"未找到点击元素: {selector}"

        await element.click(timeout=timeout)
        return True, ""

    async def _find_element(self, page, selector: str, timeout: int):
        """查找元素"""
        candidates = [s.strip() for s in selector.split(",") if s.strip()]
        deadline = time.monotonic() + timeout / 1000

        while time.monotonic() < deadline:
            for candidate in candidates:
                try:
                    locator = page.locator(candidate)
                    if await locator.count() > 0:
                        element = locator.first
                        if await element.is_visible(timeout=100):
                            return element
                except Exception:
                    continue
            await page.wait_for_timeout(100)

        return None


class SelectHandler(StepHandler):
    """选择步骤处理器"""

    @property
    def step_type(self) -> str:
        return StepType.SELECT

    async def execute(
        self, page, step: StepConfig, resolver: VariableResolver
    ) -> tuple[bool, str]:
        params = self.resolve_params(step, resolver)
        selector = params.get("selector", "")
        value = str(params.get("value", "") or "").strip()
        timeout = step.timeout or 5000

        if not selector:
            return False, "选择步骤需要 selector"

        if not value:
            logger.info("[select] value 为空，跳过选择步骤")
            return True, ""

        logger.info(f"[select] selector={selector}, value={value}")

        element = await self._find_element(page, selector, timeout)
        if not element:
            logger.info(f"[select] 未找到选择元素，跳过: {selector}")
            return True, ""

        selected = await self._select_with_fallback(element, value, timeout)
        if not selected:
            logger.info(f"[select] 未匹配到运营商选项，跳过: {value}")
        return True, ""

    async def _select_with_fallback(self, element, value: str, timeout: int) -> bool:
        """优先按 value 精确选择，失败后按标签文本包含匹配。"""
        try:
            result = await element.select_option(value, timeout=timeout)
            if result:
                return True
        except Exception:
            pass

        option_texts = []
        try:
            option_texts = await element.evaluate(
                "(sel) => Array.from(sel.options || []).map(o => (o.textContent || '').trim())"
            )
        except Exception:
            option_texts = []

        normalized_target = value.strip().lower()
        for text in option_texts:
            current = str(text or "").strip()
            if not current:
                continue
            normalized = current.lower()
            if normalized_target in normalized or normalized in normalized_target:
                try:
                    result = await element.select_option(label=current, timeout=timeout)
                    if result:
                        return True
                except Exception:
                    continue

        return False

    async def _find_element(self, page, selector: str, timeout: int):
        """查找元素"""
        candidates = [s.strip() for s in selector.split(",") if s.strip()]
        deadline = time.monotonic() + timeout / 1000

        while time.monotonic() < deadline:
            for candidate in candidates:
                try:
                    locator = page.locator(candidate)
                    if await locator.count() > 0:
                        element = locator.first
                        if await element.is_visible(timeout=100):
                            return element
                except Exception:
                    continue
            await page.wait_for_timeout(100)

        return None


class WaitHandler(StepHandler):
    """等待步骤处理器"""

    @property
    def step_type(self) -> str:
        return StepType.WAIT

    async def execute(
        self, page, step: StepConfig, resolver: VariableResolver
    ) -> tuple[bool, str]:
        params = self.resolve_params(step, resolver)
        selector = params.get("selector", "")
        timeout = step.timeout or 5000

        if not selector:
            return False, "等待步骤需要 selector"

        logger.info(f"[wait] selector={selector}, timeout={timeout}")
        await page.wait_for_selector(selector, timeout=timeout)
        return True, ""


class WaitUrlHandler(StepHandler):
    """等待URL处理器"""

    @property
    def step_type(self) -> str:
        return StepType.WAIT_URL

    async def execute(
        self, page, step: StepConfig, resolver: VariableResolver
    ) -> tuple[bool, str]:
        params = self.resolve_params(step, resolver)
        pattern = params.get("pattern", "")
        timeout = step.timeout or 5000

        if not pattern:
            return False, "wait_url 步骤需要 pattern"

        logger.info(f"[wait_url] pattern={pattern}")
        await page.wait_for_url(re.compile(pattern), timeout=timeout)
        return True, ""


class EvalHandler(StepHandler):
    """JavaScript求值处理器"""

    @property
    def step_type(self) -> str:
        return StepType.EVAL

    async def execute(
        self, page, step: StepConfig, resolver: VariableResolver
    ) -> tuple[bool, str]:
        params = self.resolve_params(step, resolver)
        script = params.get("script", "")
        store_as = params.get("store_as")

        if not script:
            return False, "eval 步骤需要 script"

        logger.info(f"[eval] store_as={store_as}")
        result = await page.evaluate(script)

        if store_as:
            resolver.set_runtime_var(store_as, result)
            logger.info(f"[eval] 结果存储到变量 {store_as}: {result}")

        return True, ""


class CustomJsHandler(StepHandler):
    """自定义JavaScript处理器"""

    @property
    def step_type(self) -> str:
        return StepType.CUSTOM_JS

    async def execute(
        self, page, step: StepConfig, resolver: VariableResolver
    ) -> tuple[bool, str]:
        params = self.resolve_params(step, resolver)
        script = params.get("script", "")

        if not script:
            return False, "custom_js 步骤需要 script"

        logger.info("[custom_js] 执行自定义脚本")
        await page.evaluate(script)
        return True, ""


class ScreenshotHandler(StepHandler):
    """截图处理器"""

    PROJECT_ROOT = Path(__file__).resolve().parents[1]

    @property
    def step_type(self) -> str:
        return StepType.SCREENSHOT

    async def execute(
        self, page, step: StepConfig, resolver: VariableResolver
    ) -> tuple[bool, str]:
        params = self.resolve_params(step, resolver)
        path = params.get("path", "")

        if not path:
            debug_dir = self.PROJECT_ROOT / "debug"
            debug_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            path = str(debug_dir / f"step_screenshot_{stamp}.png")
        else:
            os.makedirs(os.path.dirname(path) or "debug", exist_ok=True)

        logger.info(f"[screenshot] path={path}")
        await page.screenshot(path=path, full_page=True)
        return True, ""


class SleepHandler(StepHandler):
    """休眠处理器"""

    @property
    def step_type(self) -> str:
        return StepType.SLEEP

    async def execute(
        self, page, step: StepConfig, resolver: VariableResolver
    ) -> tuple[bool, str]:
        params = self.resolve_params(step, resolver)
        duration = params.get("duration", 1000)

        logger.info(f"[sleep] duration={duration}ms")
        await page.wait_for_timeout(duration)
        return True, ""


class StepExecutorRegistry:
    """步骤执行器注册表"""

    def __init__(self):
        self._handlers: dict[str, StepHandler] = {}
        self._register_defaults()

    def _register_defaults(self) -> None:
        """注册默认处理器"""
        handlers = [
            NavigateHandler(),
            InputHandler(),
            ClickHandler(),
            SelectHandler(),
            WaitHandler(),
            WaitUrlHandler(),
            EvalHandler(),
            CustomJsHandler(),
            ScreenshotHandler(),
            SleepHandler(),
        ]
        for handler in handlers:
            self.register(handler)

    def register(self, handler: StepHandler) -> None:
        """注册处理器"""
        self._handlers[handler.step_type] = handler

    def get(self, step_type: str) -> StepHandler | None:
        """获取处理器"""
        return self._handlers.get(step_type)

    def list_types(self) -> list[str]:
        """列出支持的类型"""
        return list(self._handlers.keys())


class TaskValidator:
    """任务验证器"""

    REQUIRED_STEP_FIELDS = {"id", "type"}
    VALID_STEP_TYPES = {t.value for t in StepType}

    @classmethod
    def validate(cls, config: dict[str, Any]) -> tuple[bool, list[str]]:
        """验证任务配置

        Returns:
            (is_valid, error_messages)
        """
        errors = []

        # 验证基本字段
        if not config.get("name"):
            errors.append("任务必须包含 'name' 字段")

        if not config.get("steps"):
            errors.append("任务必须包含 'steps' 字段")
        elif not isinstance(config["steps"], list):
            errors.append("'steps' 必须是数组")
        else:
            # 验证每个步骤
            for i, step in enumerate(config["steps"]):
                step_errors = cls._validate_step(step, i)
                errors.extend(step_errors)

        # 验证成功条件
        if "success_conditions" in config:
            for i, cond in enumerate(config["success_conditions"]):
                if not cond.get("type"):
                    errors.append(f"success_conditions[{i}] 必须包含 'type'")

        return len(errors) == 0, errors

    @classmethod
    def _validate_step(cls, step: dict[str, Any], index: int) -> list[str]:
        """验证单个步骤"""
        errors = []
        prefix = f"steps[{index}]"

        # 检查必需字段
        missing = cls.REQUIRED_STEP_FIELDS - set(step.keys())
        if missing:
            errors.append(f"{prefix} 缺少必需字段: {missing}")
            return errors

        # 验证步骤类型
        step_type = step.get("type", "")
        if step_type not in cls.VALID_STEP_TYPES:
            errors.append(f"{prefix} 未知的步骤类型: '{step_type}'")

        # 根据类型验证特定字段
        if step_type == StepType.NAVIGATE and not step.get("url"):
            errors.append(f"{prefix} (navigate) 需要 'url' 字段")

        if step_type == StepType.INPUT:
            if not step.get("selector"):
                errors.append(f"{prefix} (input) 需要 'selector' 字段")

        if step_type == StepType.CLICK and not step.get("selector"):
            errors.append(f"{prefix} (click) 需要 'selector' 字段")

        if step_type == StepType.SELECT and not step.get("selector"):
            errors.append(f"{prefix} (select) 需要 'selector' 字段")

        if step_type == StepType.WAIT and not step.get("selector"):
            errors.append(f"{prefix} (wait) 需要 'selector' 字段")

        if step_type == StepType.WAIT_URL and not step.get("pattern"):
            errors.append(f"{prefix} (wait_url) 需要 'pattern' 字段")

        if step_type in (StepType.EVAL, StepType.CUSTOM_JS) and not step.get("script"):
            errors.append(f"{prefix} ({step_type}) 需要 'script' 字段")

        return errors


class TaskExecutor:
    """任务执行器 v2"""

    PROJECT_ROOT = Path(__file__).resolve().parents[1]

    def __init__(self, config: TaskConfig, env_vars: dict[str, str] | None = None):
        self.config = config
        self.env_vars = env_vars or {}
        self.resolver = VariableResolver(config, self.env_vars)
        self.registry = StepExecutorRegistry()
        self._step_results: list[dict[str, Any]] = []

    async def execute(self, page) -> tuple[bool, str]:
        """执行任务

        Returns:
            (success, message)
        """
        logger.info(f"开始执行任务: {self.config.name} (v{self.config.version})")
        self._step_results = []

        try:
            # 自动导航到任务URL（如果步骤中没有导航）
            await self._auto_navigate_if_needed(page)

            # 执行步骤
            for step in self.config.steps:
                success, message = await self._execute_step(page, step)
                self._step_results.append(
                    {
                        "step_id": step.id,
                        "type": step.type,
                        "success": success,
                        "message": message,
                    }
                )

                if not success:
                    return await self._handle_failure(page, step, message)

            # 检查成功条件
            if not await self._check_success_conditions(page):
                return await self._handle_failure(page, None, "成功条件不满足")

            # 执行成功
            return await self._handle_success(page)

        except Exception as e:
            logger.error(f"任务执行异常: {e}")
            return await self._handle_failure(page, None, str(e))

    async def _auto_navigate_if_needed(self, page) -> None:
        """如果第一个步骤不是导航，自动导航到任务URL"""
        if not self.config.steps:
            return

        first_step = self.config.steps[0]
        if first_step.type != StepType.NAVIGATE and self.config.url:
            url = self.resolver.resolve(self.config.url)
            if url:
                logger.info(f"自动导航到任务URL: {url}")
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)

    async def _execute_step(self, page, step: StepConfig) -> tuple[bool, str]:
        """执行单个步骤"""
        handler = self.registry.get(step.type)
        if not handler:
            return False, f"未知的步骤类型: {step.type}"

        logger.info(f"执行步骤 [{step.id}]: {step.description or step.type}")

        try:
            return await handler.execute(page, step, self.resolver)
        except Exception as e:
            logger.error(f"步骤 [{step.id}] 执行失败: {e}")
            return False, str(e)

    async def _check_success_conditions(self, page) -> bool:
        """检查成功条件"""
        if not self.config.success_conditions:
            return True

        current_url = page.url if hasattr(page, "url") else ""
        self.resolver.set_runtime_var("_current_url", current_url)

        for cond in self.config.success_conditions:
            if not self._evaluate_condition(cond, current_url, page):
                logger.warning(f"成功条件不满足: {cond}")
                return False

        return True

    def _evaluate_condition(
        self, cond: ConditionConfig, current_url: str, page
    ) -> bool:
        """评估单个条件"""
        cond_type = cond.type

        if cond_type == ConditionType.VARIABLE:
            actual = self.resolver.runtime_vars.get(cond.variable)
            return actual == cond.value

        elif cond_type == ConditionType.URL_CONTAINS:
            pattern = cond.pattern or ""
            return pattern in current_url

        elif cond_type == ConditionType.URL_MATCHES:
            pattern = cond.pattern or ""
            try:
                return bool(re.search(pattern, current_url))
            except re.error:
                return False

        return True

    async def _handle_success(self, page) -> tuple[bool, str]:
        """处理成功情况"""
        message = self.config.on_success.get("message", "任务执行成功")
        logger.info(f"任务执行成功: {message}")
        return True, message

    async def _handle_failure(
        self, page, failed_step: StepConfig | None, reason: str
    ) -> tuple[bool, str]:
        """处理失败情况"""
        # 截图
        screenshot_url = None
        if self.config.on_failure.get("screenshot", True):
            screenshot_url = await self._capture_screenshot(page)

        # 构建错误消息
        base_message = self.config.on_failure.get("message", "任务执行失败")
        message = f"{base_message}: {reason}"

        if screenshot_url:
            message += f" 截图: {screenshot_url}"

        logger.error(f"任务执行失败: {message}")
        return False, message

    async def _capture_screenshot(self, page) -> str | None:
        """捕获失败截图"""
        try:
            debug_dir = self.PROJECT_ROOT / "debug"
            debug_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            filename = f"task_failure_{stamp}.png"
            local_path = str(debug_dir / filename)
            await page.screenshot(path=local_path, full_page=True)
            return f"/debug/{filename}"
        except Exception as e:
            logger.warning(f"截图失败: {e}")
            return None

    def get_execution_summary(self) -> dict[str, Any]:
        """获取执行摘要"""
        return {
            "task_name": self.config.name,
            "steps_total": len(self.config.steps),
            "steps_executed": len(self._step_results),
            "steps_succeeded": sum(1 for r in self._step_results if r["success"]),
            "steps_failed": sum(1 for r in self._step_results if not r["success"]),
            "step_results": self._step_results,
        }


# 向后兼容
def normalize_task_id(task_id: str | None) -> str:
    if not isinstance(task_id, str):
        return ""
    return task_id.strip()


def is_valid_task_id(task_id: str | None) -> bool:
    normalized = normalize_task_id(task_id)
    return bool(normalized and TASK_ID_PATTERN.fullmatch(normalized))


class TaskManager:
    """任务管理器"""

    def __init__(self, tasks_dir: Path):
        self.tasks_dir = tasks_dir
        self.tasks_dir.mkdir(parents=True, exist_ok=True)

    def _safe_task_path(self, task_id: str) -> Path | None:
        normalized = normalize_task_id(task_id)
        if not is_valid_task_id(normalized):
            return None

        base = self.tasks_dir.resolve()
        candidate = (self.tasks_dir / f"{normalized}.json").resolve()
        try:
            candidate.relative_to(base)
        except ValueError:
            return None
        return candidate

    def list_tasks(self) -> list[dict[str, str]]:
        tasks = []
        for file in self.tasks_dir.glob("*.json"):
            try:
                config = json.loads(file.read_text(encoding="utf-8"))
                tasks.append(
                    {
                        "id": file.stem,
                        "name": config.get("name", file.stem),
                        "description": config.get("description", ""),
                        "version": config.get("version", "1.0"),
                    }
                )
            except Exception as e:
                logger.warning(f"无法读取任务文件 {file}: {e}")
        return tasks

    def load_task(self, task_id: str) -> TaskConfig | None:
        file = self._safe_task_path(task_id)
        if file is None or not file.exists():
            return None
        try:
            data = json.loads(file.read_text(encoding="utf-8"))
            return TaskConfig.from_dict(data)
        except Exception as e:
            logger.error(f"无法加载任务 {task_id}: {e}")
            return None

    def save_task(self, task_id: str, config: dict[str, Any]) -> bool:
        """保存任务（带验证）"""
        # 验证任务
        is_valid, errors = TaskValidator.validate(config)
        if not is_valid:
            logger.error(f"任务验证失败: {errors}")
            return False

        file = self._safe_task_path(task_id)
        if file is None:
            return False

        try:
            file.write_text(
                json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            return True
        except Exception as e:
            logger.error(f"无法保存任务 {task_id}: {e}")
            return False

    def delete_task(self, task_id: str) -> bool:
        if task_id == "default":
            return False
        file = self._safe_task_path(task_id)
        if file is None:
            return False
        try:
            file.unlink(missing_ok=True)
            return True
        except Exception as e:
            logger.error(f"无法删除任务 {task_id}: {e}")
            return False

    def get_active_task(self) -> str:
        config_file = self.tasks_dir / "active.txt"
        if config_file.exists():
            return config_file.read_text(encoding="utf-8").strip()
        return "default"

    def set_active_task(self, task_id: str) -> bool:
        normalized = normalize_task_id(task_id)
        if not is_valid_task_id(normalized):
            return False
        file = self._safe_task_path(normalized)
        if file is None or not file.exists():
            return False
        config_file = self.tasks_dir / "active.txt"
        try:
            config_file.write_text(normalized, encoding="utf-8")
            return True
        except Exception as e:
            logger.error(f"无法设置活动任务: {e}")
            return False
