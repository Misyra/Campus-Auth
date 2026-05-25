"""
任务执行器 - 标准化任务处理模块

提供标准化的任务执行流程，支持多种步骤类型，内置完善的验证和错误处理机制。
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import tempfile
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from src.utils.logging import get_logger

logger = get_logger("task_executor", side="BACKEND")

# 任务ID验证正则
TASK_ID_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")

# 强制输入 JS 脚本：绕过可见性检查，通过原生 setter 设置值并模拟完整用户交互事件
_FORCE_INPUT_JS = """(el, params) => {
  const val = params.val;
  const doClear = params.doClear;
  el.removeAttribute('readonly');
  el.removeAttribute('disabled');
  // 1. focus — 触发页面 JS 的显隐切换/占位收起
  el.dispatchEvent(new FocusEvent('focus', {bubbles:true}));
  // 2. 清空
  if (doClear) {
    const nativeSet = Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype, 'value').set;
    nativeSet.call(el, '');
  }
  // 3. beforeinput — React 17+ 受控组件需要
  el.dispatchEvent(new InputEvent('beforeinput',
    {bubbles:true, inputType:'insertText', data:val}));
  // 4. 设置值（原生 setter 绕过 React/Vue 的 getter/setter 劫持）
  const nativeSet = Object.getOwnPropertyDescriptor(
    HTMLInputElement.prototype, 'value').set;
    nativeSet.call(el, val);
  // 5. input — 所有框架都监听此事件更新状态
  el.dispatchEvent(new InputEvent('input',
    {bubbles:true, inputType:'insertText', data:val}));
  // 6. keyup — 部分门户做逐字校验
  el.dispatchEvent(new KeyboardEvent('keyup', {bubbles:true}));
  // 7. change
  el.dispatchEvent(new Event('change', {bubbles:true}));
  // 8. blur — 触发校验/同步（如深澜双输入框的值同步）
  el.dispatchEvent(new FocusEvent('blur', {bubbles:true}));
}"""


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


class StepType(str, Enum):
    """标准步骤类型"""

    INPUT = "input"
    CLICK = "click"
    SELECT = "select"
    WAIT = "wait"
    WAIT_URL = "wait_url"
    EVAL = "eval"
    SCREENSHOT = "screenshot"
    SLEEP = "sleep"
    OCR = "ocr"
    CLICK_SELECT = "click_select"


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
    frame: str | None = None  # frame 选择器（URL、name 或 CSS 选择器）
    required: bool = False  # 当为 True 时，元素/选项未找到则返回失败
    # 扩展参数
    extra: dict[str, Any] = field(default_factory=dict)

    # 字段默认值映射，to_dict 时跳过与默认值相同的字段
    _DEFAULTS = {
        "description": "",
        "timeout": None,
        "url": None,
        "selector": None,
        "value": None,
        "pattern": None,
        "script": None,
        "store_as": None,
        "clear": True,
        "wait_until": "networkidle",
        "path": None,
        "duration": 1000,
        "frame": None,
        "required": False,
        "extra": {},
    }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StepConfig:
        """从字典创建步骤配置，自动将 code 规范化为 script"""
        # code → script 规范化
        if "code" in data and "script" not in data:
            data = dict(data)
            data["script"] = data.pop("code")
        # frame 类型规范化：非字符串非 None 的值（如布尔值 true）静默清空
        if (
            "frame" in data
            and data["frame"] is not None
            and not isinstance(data["frame"], str)
        ):
            logger.warning(
                "[StepConfig] 步骤 %s 的 frame 字段应为字符串，实际为 %s，已忽略",
                data.get("id", "?"),
                type(data["frame"]).__name__,
            )
            data = dict(data)
            data["frame"] = None
        base_fields = {
            k: v
            for k, v in data.items()
            if k in cls.__dataclass_fields__ and k != "extra"
        }
        extra_fields = {
            k: v for k, v in data.items() if k not in cls.__dataclass_fields__
        }
        # 合并数据中自带的 extra 和不在 dataclass 中的字段
        merged_extra = {**data.get("extra", {}), **extra_fields}
        return cls(**base_fields, extra=merged_extra)

    def to_dict(self) -> dict[str, Any]:
        """序列化为紧凑字典，跳过默认值和 None，合并 extra 回顶层"""
        result: dict[str, Any] = {"id": self.id, "type": self.type}
        for field_name in self.__dataclass_fields__:
            if field_name in ("id", "type", "extra"):
                continue
            value = getattr(self, field_name)
            default = self._DEFAULTS.get(field_name)
            if value is not None and value != default:
                result[field_name] = value
        # 把 extra 里的扩展字段合并回顶层
        if self.extra:
            result.update(self.extra)
        return result


@dataclass
class TaskConfig:
    """任务配置"""

    task_id: str = ""
    name: str = "未命名任务"
    description: str = ""
    url: str = ""
    timeout: int = 30000
    variables: dict[str, str] = field(default_factory=dict)
    steps: list[StepConfig] = field(default_factory=list)
    on_success: dict[str, Any] = field(default_factory=dict)
    on_failure: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(
        default_factory=dict
    )  # 用户自定义元数据，执行器不使用
    reveal_hidden: bool = True  # 执行前默认显示所有隐藏输入框
    step_delay: float = 0.5

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TaskConfig:
        """从字典创建任务配置"""
        return cls(
            name=data.get("name", "未命名任务"),
            description=data.get("description", ""),
            url=data.get("url", ""),
            timeout=data.get("timeout", 30000),
            variables=data.get("variables", {}),
            steps=[StepConfig.from_dict(s) for s in data.get("steps", [])],
            on_success=data.get("on_success", {}),
            on_failure=data.get("on_failure", {}),
            metadata=data.get("metadata", {}),
            reveal_hidden=data.get("reveal_hidden", True),
            step_delay=float(data.get("step_delay", 0.5)),
        )

    def to_dict(self) -> dict[str, Any]:
        """序列化为紧凑字典，跳过空值和默认值"""
        result: dict[str, Any] = {
            "name": self.name,
            "description": self.description,
            "url": self.url,
            "timeout": self.timeout,
            "steps": [s.to_dict() for s in self.steps],
        }
        if self.variables:
            result["variables"] = self.variables
        if self.on_success:
            result["on_success"] = self.on_success
        if self.on_failure:
            result["on_failure"] = self.on_failure
        if self.metadata:
            result["metadata"] = self.metadata
        result["reveal_hidden"] = self.reveal_hidden
        if self.step_delay != 0.5:
            result["step_delay"] = self.step_delay
        return result


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
        self._cache.clear()

    def resolve_for_js(self, value: str) -> str:
        """Resolve variables with JSON-safe encoding for JavaScript embedding.

        Unlike resolve(), this method JSON-encodes resolved values so they can
        be safely embedded in JavaScript code without syntax errors.
        Example: password "admin'123" → '"admin\'123"' (valid JS string literal)
        """
        if not isinstance(value, str) or "{{" not in value:
            return value

        def replacer(match: re.Match) -> str:
            resolved = self.resolve(match.group(0))
            # If variable not found, resolve returns the original pattern
            if resolved == match.group(0):
                logger.warning("[VariableResolver] 未解析的变量: %s", match.group(0))
                return '""'  # Default to empty string
            return json.dumps(resolved)

        return self.TEMPLATE_PATTERN.sub(replacer, value)


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

    async def _resolve_frame(self, page, step: StepConfig):
        """解析 frame 上下文，返回实际操作的 page 或 frame 对象"""
        frame_selector = step.frame
        if not isinstance(frame_selector, str):
            if frame_selector is not None:
                logger.warning(
                    "[frame] 步骤 %s 的 frame 字段应为字符串，实际为 %s (%s)，将回退到主页面执行",
                    step.id,
                    frame_selector,
                    type(frame_selector).__name__,
                )
            return page
        try:
            # 优先按 name 匹配
            frame = page.frame(name=frame_selector)
            if frame:
                logger.info("[frame] 使用 frame (name): %s", frame_selector)
                return frame
            # 回退到 URL 匹配
            frame = page.frame(url=frame_selector)
            if frame:
                logger.info("[frame] 使用 frame (url): %s", frame_selector)
                return frame
            # 最后尝试 CSS 选择器匹配 iframe 元素
            try:
                frame_element = await page.query_selector(frame_selector)
                if frame_element:
                    frame = await frame_element.content_frame()
                    if frame:
                        logger.info("[frame] 使用 frame (content_frame): %s", frame_selector)
                        return frame
                    else:
                        logger.warning("[frame] content_frame() 返回 None: %s", frame_selector)
                else:
                    logger.warning("[frame] CSS 选择器未匹配到 frame 元素: %s", frame_selector)
            except Exception as e:
                logger.warning("[frame] 验证 frame 元素时出错: %s, 错误: %s", frame_selector, e)
            return page
        except Exception as e:
            logger.warning("[frame] 无法定位 frame '%s': %s", frame_selector, e)
            return page

    async def _find_element(self, ctx, selector: str, timeout: int):
        """查找元素（支持多个候选选择器，兼容 Page 和 FrameLocator）"""
        candidates = [s.strip() for s in selector.split(",") if s.strip()]

        for candidate in candidates:
            try:
                locator = ctx.locator(candidate)
                await locator.first.wait_for(state="visible", timeout=timeout)
                return locator.first
            except Exception:
                logger.debug("选择器未匹配: %s", candidate)
                continue

        logger.warning("所有选择器均未匹配: %s", selector)
        return None


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
        timeout = step.timeout or 10000

        if not selector:
            return False, "输入步骤需要 selector"

        ctx = await self._resolve_frame(page, step)
        logger.info("输入 → %s (clear=%s)", selector, clear)

        # 策略1: 快速尝试普通 fill（使用步骤 timeout 的 15%，最少 1500ms）
        candidates = [s.strip() for s in selector.split(",") if s.strip()]
        wait_timeout = max(1500, int(timeout * 0.15))
        for candidate in candidates:
            try:
                loc = ctx.locator(candidate).first
                await loc.wait_for(state="visible", timeout=wait_timeout)
                if clear:
                    await loc.fill("", timeout=timeout)
                await loc.fill(value, timeout=timeout)
                logger.info("输入完成(普通) → %s", candidate)
                return True, ""
            except Exception:
                logger.debug("普通 fill 候选失败: %s", candidate)
                continue

        # 策略2: 自动降级到强制输入（隐藏/不可交互的输入框）
        logger.info("普通 fill 失败，自动降级到强制输入模式")
        return await self._force_input(ctx, selector, value, clear, timeout)

    async def _force_input(
        self, ctx, selector: str, value: str, clear: bool, timeout: int
    ) -> tuple[bool, str]:
        """强制输入：跳过可见性检查，通过 JS 设置值并模拟完整用户交互事件。
        适用于 display:none / visibility:hidden / opacity:0 等隐藏输入框。
        支持逗号分隔的候选选择器，按顺序尝试，取第一个 attached 的元素。

        事件序列（模拟真实用户操作）：
          focus → (clear) → beforeinput → set value → input → keyup → change → blur
        """
        candidates = [s.strip() for s in selector.split(",") if s.strip()]

        for candidate in candidates:
            try:
                el = ctx.locator(candidate).first
                await el.wait_for(state="attached", timeout=timeout)
                await el.evaluate(
                    _FORCE_INPUT_JS,
                    {"val": value, "doClear": clear},
                )
                logger.info("强制输入完成 → %s", candidate)
                return True, ""
            except Exception:
                logger.debug("force_input 候选失败: %s", candidate)
                continue

        return False, f"force_input 未找到可用的输入元素: {selector}"


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
        timeout = step.timeout or 10000

        if not selector:
            return False, "点击步骤需要 selector"

        ctx = await self._resolve_frame(page, step)
        logger.info("点击 → %s", selector)

        # 策略1: 快速尝试普通 click（3s 超时）
        candidates = [s.strip() for s in selector.split(",") if s.strip()]
        for candidate in candidates:
            try:
                loc = ctx.locator(candidate).first
                await loc.wait_for(state="visible", timeout=1500)
                await loc.click(timeout=timeout)
                logger.info("点击完成(普通) → %s", candidate)
                return True, ""
            except Exception:
                logger.debug("普通 click 候选失败: %s", candidate)
                continue

        # 策略2: 自动降级到 force click（隐藏/不可交互的元素用 JS click）
        logger.info("普通 click 失败，自动降级到 force click")
        for candidate in candidates:
            try:
                loc = ctx.locator(candidate).first
                await loc.wait_for(state="attached", timeout=timeout)
                await loc.dispatch_event("click")
                logger.info("点击完成(force) → %s", candidate)
                return True, ""
            except Exception:
                logger.debug("force click 候选失败: %s", candidate)
                continue

        return False, f"未找到可点击的元素: {selector}"


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
        timeout = step.timeout or 10000

        if not selector:
            return False, "选择步骤需要 selector"

        if not value:
            logger.info("[select] value 为空，跳过选择步骤")
            return True, ""

        ctx = await self._resolve_frame(page, step)
        logger.info(f"[select] selector={selector}, value={value}")

        element = await self._find_element(ctx, selector, timeout)
        if not element:
            logger.info(f"[select] 未找到选择元素，跳过: {selector}")
            if step.required:
                return False, f"选择元素未找到: {selector}"
            return True, ""

        selected = await self._select_with_fallback(element, value, timeout)
        if not selected:
            logger.info(f"[select] 未匹配到运营商选项，跳过: {value}")
            if step.required:
                return False, f"选择选项未匹配: {value}"
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
            if normalized_target == normalized or normalized_target in normalized:
                try:
                    result = await element.select_option(label=current, timeout=timeout)
                    if result:
                        return True
                except Exception:
                    continue

        return False


class ClickSelectHandler(StepHandler):
    """点击-选择步骤 — 用于自定义 div 下拉框（非原生 select）"""

    @property
    def step_type(self) -> str:
        return StepType.CLICK_SELECT

    async def execute(
        self, page, step: StepConfig, resolver: VariableResolver
    ) -> tuple[bool, str]:
        params = self.resolve_params(step, resolver)
        selector = params.get("selector", "")
        value = str(params.get("value", "") or "").strip()
        option_selector = params.get("option_selector", "")
        timeout = step.timeout or 10000

        if not selector:
            return False, "click_select 步骤需要 selector"
        if not value:
            logger.info("[click_select] value 为空，跳过")
            return True, ""

        ctx = await self._resolve_frame(page, step)
        logger.info(
            "[click_select] trigger=%s, value=%s, option_sel=%s",
            selector,
            value,
            option_selector or "(auto)",
        )

        trigger = await self._find_element(ctx, selector, timeout)
        if not trigger:
            logger.info("[click_select] 未找到触发器，跳过: %s", selector)
            if step.required:
                return False, f"click_select 触发器未找到: {selector}"
            return True, ""

        await trigger.click(timeout=timeout)
        await page.wait_for_timeout(500)

        clicked = await self._click_option(ctx, value, option_selector, timeout)
        if not clicked:
            logger.info("[click_select] 未匹配到选项，跳过: %s", value)
            if step.required:
                return False, f"click_select 选项未匹配: {value}"
        return True, ""

    async def _click_option(
        self, ctx, text: str, option_selector: str, timeout: int
    ) -> bool:
        try:
            if option_selector:
                # 限定容器内搜索，更精准
                container = ctx.locator(option_selector).first
                option = container.get_by_text(text, exact=False).first
            else:
                option = ctx.get_by_text(text, exact=False).first
            await option.wait_for(state="visible", timeout=timeout)
            await option.click(timeout=timeout)
            logger.info("[click_select] 点击选项: %s", text)
            return True
        except Exception:
            return False


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
        timeout = step.timeout or 10000

        if not selector:
            return False, "等待步骤需要 selector"

        ctx = await self._resolve_frame(page, step)
        logger.info(f"[wait] selector={selector}, timeout={timeout}")
        await ctx.locator(selector).first.wait_for(timeout=timeout)
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
        timeout = step.timeout or 10000

        if not pattern:
            return False, "wait_url 步骤需要 pattern"

        try:
            compiled = re.compile(pattern)
        except re.error:
            return False, f"wait_url 步骤的 pattern 不是有效的正则表达式: {pattern}"

        logger.info(f"[wait_url] pattern={pattern}")
        deadline = asyncio.get_running_loop().time() + timeout / 1000
        while True:
            current_url = page.url
            if compiled.search(current_url):
                logger.info(f"[wait_url] URL 已匹配: {current_url}")
                return True, ""
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                return False, f"等待 URL 匹配 '{pattern}' 超时，当前: {current_url}"
            await asyncio.sleep(min(0.2, remaining))


class EvalHandler(StepHandler):
    """JavaScript求值处理器"""

    @property
    def step_type(self) -> str:
        return StepType.EVAL

    async def execute(
        self, page, step: StepConfig, resolver: VariableResolver
    ) -> tuple[bool, str]:
        # Use JS-safe variable resolution to prevent syntax errors from
        # special characters in passwords, usernames, etc.
        script = step.script or ""
        if not script:
            return False, "eval 步骤需要 script 字段"

        resolved_script = resolver.resolve_for_js(script)

        store_as = step.store_as
        logger.info(f"[eval] store_as={store_as}")
        result = await page.evaluate(resolved_script)

        if store_as:
            resolver.set_runtime_var(store_as, result)
            logger.info(f"[eval] 结果存储到变量 {store_as}: {result}")

        return True, ""


class ScreenshotHandler(StepHandler):
    """截图处理器 — 运行时截图存入 debug/{date}/ 目录"""

    PROJECT_ROOT = Path(__file__).resolve().parents[1]

    @property
    def step_type(self) -> str:
        return StepType.SCREENSHOT

    async def execute(
        self, page, step: StepConfig, resolver: VariableResolver
    ) -> tuple[bool, str]:
        params = self.resolve_params(step, resolver)
        path = params.get("path", "")

        date_dir = self.PROJECT_ROOT / "debug" / datetime.now().strftime("%Y-%m-%d")
        date_dir.mkdir(parents=True, exist_ok=True)

        if not path:
            task_id = resolver.config.task_id or "unknown"
            step_id = step.id or "s0"
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            filename = f"{task_id}_{step_id}_{stamp}.png"
            path = str(date_dir / filename)
        else:
            safe_name = Path(path).name
            path = str(date_dir / safe_name)

        logger.info(f"[screenshot] path={path}")
        await page.screenshot(path=path, full_page=True)
        return True, ""


class SleepHandler(StepHandler):
    """休眠处理器"""

    MAX_SLEEP_MS = 300000  # 最大 5 分钟

    @property
    def step_type(self) -> str:
        return StepType.SLEEP

    async def execute(
        self, page, step: StepConfig, resolver: VariableResolver
    ) -> tuple[bool, str]:
        params = self.resolve_params(step, resolver)
        duration = params.get("duration", 1000)

        if duration > self.MAX_SLEEP_MS:
            logger.warning(
                f"[sleep] duration={duration}ms 超过上限 {self.MAX_SLEEP_MS}ms，已截断"
            )
            duration = self.MAX_SLEEP_MS

        logger.info(f"[sleep] duration={duration}ms")
        await page.wait_for_timeout(duration)
        return True, ""


class OcrHandler(StepHandler):
    """验证码识别步骤处理器"""

    _ocr_instances: dict[bool, Any] = {}

    @classmethod
    def _get_ocr(cls, old: bool = False):
        if old not in cls._ocr_instances:
            try:
                import ddddocr

                cls._ocr_instances[old] = ddddocr.DdddOcr(old=old, show_ad=False)
            except ImportError:
                raise StepError("ddddocr 未安装，请运行: uv add ddddocr")
        return cls._ocr_instances[old]

    @property
    def step_type(self) -> str:
        return StepType.OCR

    async def execute(
        self, page, step: StepConfig, resolver: VariableResolver
    ) -> tuple[bool, str]:
        params = self.resolve_params(step, resolver)
        selector = params.get("selector", "")
        store_as = params.get("store_as")
        target_selector = params.get("target_selector", "")
        old = params.get("old", False)

        if not selector:
            return False, "ocr 步骤需要 selector（验证码图片选择器）"

        timeout = step.timeout or 10000
        ctx = await self._resolve_frame(page, step)

        # 查找验证码图片元素
        element = await self._find_element(ctx, selector, timeout)
        if not element:
            return False, f"未找到验证码图片元素: {selector}"

        # 截取验证码图片
        try:
            img_bytes = await element.screenshot()
        except Exception as e:
            return False, f"验证码截图失败: {e}"

        # OCR 识别
        try:
            ocr = self._get_ocr(old=old)
            result = ocr.classification(img_bytes)
        except Exception as e:
            return False, f"验证码识别失败: {e}"

        logger.info("[ocr] 识别结果: %s", result)

        # 存储到变量
        if store_as:
            resolver.set_runtime_var(store_as, result)

        # 自动填入目标输入框
        if target_selector:
            target = await self._find_element(ctx, target_selector, timeout)
            if not target:
                return False, f"未找到验证码输入框: {target_selector}"
            try:
                await target.fill(result, timeout=timeout)
                logger.info("[ocr] 填入验证码成功(普通): %s", target_selector)
            except Exception:
                logger.info("[ocr] 普通 fill 失败，降级到强制输入: %s", target_selector)
                await target.wait_for(state="attached", timeout=timeout)
                await target.evaluate(
                    _FORCE_INPUT_JS,
                    {"val": result, "doClear": False},
                )
                logger.info("[ocr] 强制输入完成 → %s", target_selector)

        return True, result


class StepExecutorRegistry:
    """步骤执行器注册表"""

    def __init__(self):
        self._handlers: dict[str, StepHandler] = {}
        self._register_defaults()

    def _register_defaults(self) -> None:
        """注册默认处理器"""
        handlers = [
            InputHandler(),
            ClickHandler(),
            SelectHandler(),
            ClickSelectHandler(),
            WaitHandler(),
            WaitUrlHandler(),
            EvalHandler(),
            ScreenshotHandler(),
            SleepHandler(),
            OcrHandler(),
        ]
        for handler in handlers:
            self.register(handler)

        # custom_js 已合并到 eval，保留映射以兼容旧任务
        self._handlers["custom_js"] = self._handlers.get(StepType.EVAL)

    def register(self, handler: StepHandler) -> None:
        """注册处理器"""
        self._handlers[handler.step_type] = handler

    def get(self, step_type: str) -> StepHandler | None:
        """获取处理器"""
        return self._handlers.get(step_type)


class TaskValidator:
    """任务验证器"""

    REQUIRED_STEP_FIELDS = {"id", "type"}
    VALID_STEP_TYPES = {t.value for t in StepType} | {"navigate", "custom_js"}

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

        # 验证步骤 ID 格式
        step_id = step.get("id", "")
        if not TASK_ID_PATTERN.fullmatch(step_id):
            errors.append(
                f"{prefix} id '{step_id}' 格式无效，须匹配 ^[A-Za-z][A-Za-z0-9_]*$"
            )

        # 验证步骤类型
        step_type = step.get("type", "")
        if step_type not in cls.VALID_STEP_TYPES:
            errors.append(f"{prefix} 未知的步骤类型: '{step_type}'")

        # 根据类型验证特定字段
        if step_type == "navigate":
            # navigate 已废弃：统一使用任务的 url 字段自动导航
            errors.append(f"{prefix} (navigate) 已废弃，请使用任务的 url 字段")
            return errors

        if step_type == StepType.INPUT:
            if not step.get("selector"):
                errors.append(f"{prefix} (input) 需要 'selector' 字段")

        if step_type == StepType.CLICK and not step.get("selector"):
            errors.append(f"{prefix} (click) 需要 'selector' 字段")

        if step_type == StepType.SELECT and not step.get("selector"):
            errors.append(f"{prefix} (select) 需要 'selector' 字段")

        if step_type == StepType.CLICK_SELECT and not step.get("selector"):
            errors.append(f"{prefix} (click_select) 需要 'selector' 字段")

        if step_type == StepType.WAIT and not step.get("selector"):
            errors.append(f"{prefix} (wait) 需要 'selector' 字段")

        if step_type == StepType.WAIT_URL and not step.get("pattern"):
            errors.append(f"{prefix} (wait_url) 需要 'pattern' 字段")

        if (
            step_type in (StepType.EVAL, "custom_js")
            and not step.get("script")
            and not step.get("code")
        ):
            errors.append(
                f"{prefix} (eval) 需要 'script' 字段（'code' 仍兼容但已废弃）"
            )

        if step_type == StepType.OCR and not step.get("selector"):
            errors.append(f"{prefix} (ocr) 需要 'selector' 字段（验证码图片选择器）")

        return errors


class TaskExecutor:
    """任务执行器"""

    PROJECT_ROOT = Path(__file__).resolve().parents[1]

    DEFAULT_STEP_TIMEOUT = 10000

    def __init__(
        self,
        config: TaskConfig,
        env_vars: dict[str, str] | None = None,
        screenshot_dir: Path | str | None = None,
        default_timeout: int | None = None,
        network_test_config: dict[str, Any] | None = None,
    ):
        self.config = config
        self.env_vars = env_vars or {}
        self.default_timeout = default_timeout or self.DEFAULT_STEP_TIMEOUT
        self.resolver = VariableResolver(config, self.env_vars)
        self.registry = StepExecutorRegistry()
        self._step_results: list[dict[str, Any]] = []
        self._screenshot_dir = Path(screenshot_dir) if screenshot_dir else None
        self.network_test_config = network_test_config

    async def execute(self, page) -> tuple[bool, str]:
        """执行任务

        Returns:
            (success, message)
        """
        import time as _time

        task_start = _time.perf_counter()
        task_timeout_ms = self.config.timeout or 30000
        task_deadline = task_start + task_timeout_ms / 1000
        logger.info(
            "任务开始 [%s], %d 个步骤, 超时 %dms",
            self.config.name,
            len(self.config.steps),
            task_timeout_ms,
        )
        self._step_results = []

        try:
            await self._auto_navigate(page)

            # 等待表单元素出现（最长 5s），覆盖 SPA 门户延迟渲染的场景
            # 如果页面没有表单元素，静默跳过，不阻塞流程
            try:
                await page.wait_for_selector('input,textarea', timeout=5000)
            except Exception:
                pass

            # reveal_hidden: 强制显示所有隐藏输入框，让后续 fill() 可以直接操作
            if self.config.reveal_hidden and any(s.type != StepType.EVAL for s in self.config.steps):
                count = await self._reveal_hidden_inputs(page)

            for i, step in enumerate(self.config.steps):
                # 任务超时检查
                remaining_s = task_deadline - _time.perf_counter()
                if remaining_s <= 0:
                    return await self._handle_failure(
                        page, None, f"任务超时 ({task_timeout_ms}ms)"
                    )
                # 跳过 navigate 步骤，已由 _auto_navigate 统一处理
                if step.type == "navigate":
                    logger.info(
                        "  步骤[%d/%d] %s (navigate) → 跳过，已自动导航",
                        i + 1,
                        len(self.config.steps),
                        step.id,
                    )
                    continue
                if i > 0:
                    await asyncio.sleep(self.config.step_delay)
                step_start = _time.perf_counter()
                success, message = await self._execute_step(page, step)
                step_elapsed = (_time.perf_counter() - step_start) * 1000
                status = "OK" if success else "FAIL"
                logger.info(
                    "  步骤[%d/%d] %s (%s) → %s (%.0fms)%s",
                    i + 1,
                    len(self.config.steps),
                    step.id,
                    step.type,
                    status,
                    step_elapsed,
                    f" — {message}" if message else "",
                )
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

            if not await self._check_success(page):
                return await self._handle_failure(page, None, "成功条件不满足")

            total_elapsed = (_time.perf_counter() - task_start) * 1000
            logger.info("任务成功 [%s] 总耗时 %.0fms", self.config.name, total_elapsed)
            return await self._handle_success(page)

        except Exception as e:
            total_elapsed = (_time.perf_counter() - task_start) * 1000
            logger.error(
                "任务异常 [%s] 耗时 %.0fms: %s", self.config.name, total_elapsed, e
            )
            return await self._handle_failure(page, None, str(e))

    async def _auto_navigate(self, page) -> None:
        """自动导航到任务URL（优先任务 url，回退到 LOGIN_URL）

        使用 'load' 事件 + URL 稳定检测处理 JS 重定向链：
        - 校园网门户常有 DNS 劫持 → 重定向到认证页
        - SSO 统一认证 → 多次 JS redirect
        """
        url = self.resolver.resolve(self.config.url) if self.config.url else ""
        if not url:
            url = self.env_vars.get("LOGIN_URL", "").strip()
        if url:
            logger.info(f"自动导航到任务URL: {url}")
            await page.goto(url, wait_until="load", timeout=30000)
            await self._wait_url_stable(page)

    async def _wait_url_stable(self, page, timeout_ms: int = 3000):
        """等待 URL 稳定，处理 JS 重定向链（最多 5 跳）"""
        import time as _time

        deadline = _time.perf_counter() + timeout_ms / 1000
        last_url = page.url
        redirects = 0
        max_redirects = 5
        while _time.perf_counter() < deadline and redirects < max_redirects:
            await asyncio.sleep(0.5)
            current = page.url
            if current != last_url:
                logger.info(f"URL 重定向: {last_url} → {current}")
                last_url = current
                redirects += 1
                deadline = max(deadline, _time.perf_counter() + timeout_ms / 1000)

    async def _reveal_hidden_inputs(self, page) -> int:
        """强制显示所有隐藏的表单输入框。
        通过 JS 将 display:none / visibility:hidden / opacity:0 的 input 变为可见，
        后续 fill()/click() 可直接操作，无需 force 降级。覆盖 text/password/checkbox/radio 等。"""
        logger.info("[reveal] 强制显示隐藏输入框")
        count = await page.evaluate("""
            () => {
                const inputs = document.querySelectorAll('input,textarea');
                let count = 0;
                inputs.forEach(el => {
                    try {
                        if (el.type === 'hidden') return;  // 跳过 type=hidden 元数据字段
                        const s = getComputedStyle(el);
                        const hidden = s.display === 'none'
                            || s.visibility === 'hidden'
                            || parseFloat(s.opacity) <= 0;
                        if (hidden) {
                            el.style.setProperty('display', 'inline-block', 'important');
                            el.style.setProperty('visibility', 'visible', 'important');
                            el.style.setProperty('opacity', '1', 'important');
                            count++;
                        }
                    } catch (_) {}
                });
                return count;
            }
        """)
        logger.info("[reveal] 已强制显示 %d 个隐藏输入框", count)
        return count

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

    async def execute_step_at(self, page, step_index: int) -> dict[str, Any]:
        """执行单个步骤（调试模式），返回结果字典"""
        if step_index < 0 or step_index >= len(self.config.steps):
            return {
                "step_index": step_index,
                "success": False,
                "message": "步骤索引超出范围",
                "screenshot_url": None,
            }

        step = self.config.steps[step_index]
        success, message = await self._execute_step(page, step)
        screenshot_url = await self._capture_screenshot(page)

        result = {
            "step_index": step_index,
            "step_id": step.id,
            "step_type": step.type,
            "description": step.description or step.type,
            "success": success,
            "message": message or "",
            "screenshot_url": screenshot_url,
        }
        self._step_results.append(result)
        return result

    async def execute_remaining(self, page, from_index: int) -> dict[str, Any]:
        """从指定索引开始执行所有步骤（调试模式）"""
        results = []
        for i in range(from_index, len(self.config.steps)):
            result = await self.execute_step_at(page, i)
            results.append(result)
            if not result["success"]:
                return {
                    "results": results,
                    "all_success": False,
                    "stopped_at": i,
                    "message": f"步骤 {i + 1} 失败: {result['message']}",
                }
        return {
            "results": results,
            "all_success": True,
            "stopped_at": len(self.config.steps) - 1,
            "message": "所有步骤执行完成",
        }

    async def _check_success(self, page) -> bool:
        if self.network_test_config:
            return await self._network_detection_check()
        return True

    async def _network_detection_check(self) -> bool:
        """通过网络连通性检测判断任务是否成功。

        网络检测成功 → 判定任务成功（登录已生效）
        网络检测失败 → 判定任务失败（认证未生效，可能密码错误或运营商不匹配）
        """
        try:
            from src.network_test import is_network_available

            await asyncio.sleep(2)  # 等待页面响应登录请求后再检测网络

            test_sites = self.network_test_config.get("test_sites")
            timeout = self.network_test_config.get("timeout", 2)
            strict_mode = self.network_test_config.get("strict_mode", True)

            logger.info(
                "开始网络检测兜底 (test_sites=%s, timeout=%s, strict_mode=%s)",
                test_sites,
                timeout,
                strict_mode,
            )

            result = await asyncio.to_thread(
                is_network_available,
                test_sites=test_sites,
                timeout=timeout,
                require_both=strict_mode,
            )

            if result:
                logger.info("网络检测成功，判定任务成功")
            else:
                logger.warning("网络检测失败，判定任务失败")

            return result

        except Exception as e:
            logger.error("网络检测兜底异常，判定为失败: %s", e)
            return False

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

        # 日志只输出不含截图 URL 的部分，避免上层重复打印时出现两张截图
        logger.error(f"任务执行失败: {base_message}: {reason}")
        return False, message

    async def _capture_screenshot(self, page) -> str | None:
        """捕获截图 → 指定目录或 debug/{date}/ 目录"""
        try:
            if self._screenshot_dir:
                out_dir = self._screenshot_dir
                url_prefix = "/temp"
            else:
                out_dir = (
                    self.PROJECT_ROOT / "debug" / datetime.now().strftime("%Y-%m-%d")
                )
                url_prefix = f"/debug/{out_dir.name}"
            out_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            task_id = self.config.task_id or "unknown"
            filename = f"{task_id}_{stamp}.png"
            local_path = str(out_dir / filename)
            await page.screenshot(path=local_path, full_page=True)
            return f"{url_prefix}/{filename}"
        except Exception as e:
            logger.warning(f"截图失败: {e}")
            return None


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

        base = self.tasks_dir.absolute()
        candidate = (self.tasks_dir / f"{normalized}.json").absolute()
        try:
            candidate.relative_to(base)
        except ValueError:
            return None
        return candidate

    def list_tasks(self) -> list[dict[str, str]]:
        tasks = []
        for file in self.tasks_dir.glob("*.json"):
            # 跳过任务 ID 格式无效的文件（如含连字符的文件名）
            if not is_valid_task_id(file.stem):
                continue
            try:
                config = json.loads(file.read_text(encoding="utf-8"))
                tasks.append(
                    {
                        "id": file.stem,
                        "name": config.get("name", file.stem),
                        "description": config.get("description", ""),
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
            config = TaskConfig.from_dict(data)
            config.task_id = task_id
            return config
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
            # 原子写入：先写临时文件，再 os.replace 原子替换，防止崩溃时损坏任务文件
            tmp_fd, tmp_path = tempfile.mkstemp(
                dir=file.parent, suffix=".tmp", prefix="task."
            )
            try:
                with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                    f.write(json.dumps(config, ensure_ascii=False, indent=2))
                os.replace(tmp_path, file)
            except Exception:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise
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
