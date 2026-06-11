"""步骤处理器 — 10 个内置步骤处理器和注册表。"""

from __future__ import annotations

import asyncio
import re
import threading
import time
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Any

from app.constants import LOGS_DIR
from app.utils.logging import get_logger

from .models import PROJECT_ROOT, StepConfig, StepError, StepType
from .variable_resolver import VariableResolver

logger = get_logger("step_handlers", source="task")

# 强制输入 JS 脚本：绕过可见性检查，通过原生 setter 设置值并模拟完整用户交互事件
_FORCE_INPUT_JS = """(el, params) => {
  const val = params.val;
  const doClear = params.doClear;
  // 原生 setter 绕过 React/Vue 的 getter/setter 劫持（声明在块外，doClear=false 时仍可用）
  const proto = el.tagName === 'TEXTAREA'
    ? HTMLTextAreaElement.prototype
    : HTMLInputElement.prototype;
  const nativeSet = Object.getOwnPropertyDescriptor(proto, 'value').set;
  el.removeAttribute('readonly');
  el.removeAttribute('disabled');
  // 1. focus — 触发页面 JS 的显隐切换/占位收起
  el.dispatchEvent(new FocusEvent('focus', {bubbles:true}));
  // 2. 清空
  if (doClear) {
    nativeSet.call(el, '');
  }
  // 3. beforeinput — React 17+ 受控组件需要
  el.dispatchEvent(new InputEvent('beforeinput',
    {bubbles:true, inputType:'insertText', data:val}));
  // 4. 设置值
  nativeSet.call(el, val);
  // 5. input — 所有框架都监听此事件更新状态
  el.dispatchEvent(new InputEvent('input',
    {bubbles:true, inputType:'insertText', data:val}));
  // 6. keyup — 部分门户做逐字校验
  el.dispatchEvent(new KeyboardEvent('keyup', {bubbles:true}));
  // 7. change
  el.dispatchEvent(new Event('change', {bubbles:true}));
  // 8. blur — 触发校验/同步（如双输入框的值同步）
  el.dispatchEvent(new FocusEvent('blur', {bubbles:true}));
}"""


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
        """执行步骤。

        返回：(success, message)
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

    @staticmethod
    def _parse_selectors(selector: str) -> list[str]:
        """解析逗号分隔的候选选择器列表"""
        return [s.strip() for s in selector.split(",") if s.strip()]

    async def _try_candidates_with_fallback(
        self,
        ctx,
        selector: str,
        timeout: int,
        action_fn,
        fallback_fn,
        label: str = "",
    ) -> tuple[bool, str]:
        """候选选择器降级通用模式。

        策略1: 快速尝试可见元素（使用 timeout 的 15%，最少 1500ms）
        策略2: 降级到 attached 元素（使用完整 timeout）

        Args:
            ctx: page 或 frame 对象
            selector: 逗号分隔的选择器字符串
            timeout: 步骤超时（毫秒）
            action_fn: `(locator, timeout)` → 正常操作回调
            fallback_fn: `(locator, timeout)` → 降级操作回调
            label: 日志前缀（如 "[input]"）

        Returns:
            (success, message)
        """
        candidates = self._parse_selectors(selector)
        deadline = time.perf_counter() + timeout / 1000

        # 策略1: 快速尝试可见元素
        wait_timeout = max(1500, int(timeout * 0.15))
        for candidate in candidates:
            try:
                loc = ctx.locator(candidate).first
                await loc.wait_for(state="visible", timeout=wait_timeout)
                await action_fn(loc, timeout)
                logger.debug("{} 普通操作成功 -> {}", label, candidate)
                return True, ""
            except Exception:
                logger.debug("{} 普通操作候选失败: {}", label, candidate)
                continue

        # 策略2: 降级到 attached 元素（使用共享截止时间）
        logger.debug("{} 所有候选均未匹配可见元素，降级操作", label)
        for candidate in candidates:
            remaining = max(500, int((deadline - time.perf_counter()) * 1000))
            if remaining <= 0:
                break
            try:
                loc = ctx.locator(candidate).first
                await loc.wait_for(state="attached", timeout=remaining)
                await fallback_fn(loc, remaining)
                logger.debug("{} 降级操作成功 -> {}", label, candidate)
                return True, ""
            except Exception:
                logger.debug("{} 降级操作候选失败: {}", label, candidate)
                continue

        return False, f"未找到可用元素: {selector}"

    async def _resolve_frame(self, page, step: StepConfig):
        """解析 frame 上下文，返回实际操作的 page 或 frame 对象"""
        frame_selector = step.frame
        if not isinstance(frame_selector, str):
            if frame_selector is not None:
                logger.warning(
                    "[frame] 步骤 {} 的 frame 字段应为字符串，实际为 {} ({})，将回退到主页面执行",
                    step.id,
                    frame_selector,
                    type(frame_selector).__name__,
                )
            return page
        try:
            # 优先按 name 匹配
            frame = page.frame(name=frame_selector)
            if frame:
                logger.info("[frame] 使用 frame (name): {}", frame_selector)
                return frame
            # 回退到 URL 匹配
            frame = page.frame(url=frame_selector)
            if frame:
                logger.info("[frame] 使用 frame (url): {}", frame_selector)
                return frame
            # 最后尝试 CSS 选择器匹配 iframe 元素
            try:
                frame_element = await page.query_selector(frame_selector)
                if frame_element:
                    frame = await frame_element.content_frame()
                    if frame:
                        logger.info(
                            "[frame] 使用 frame (content_frame): {}", frame_selector
                        )
                        return frame
                    else:
                        logger.warning(
                            "[frame] content_frame() 返回 None: {}", frame_selector
                        )
                else:
                    logger.warning(
                        "[frame] CSS 选择器未匹配到 frame 元素: {}", frame_selector
                    )
            except Exception as e:
                logger.warning(
                    "[frame] 验证 frame 元素时出错: {}, 错误: {}", frame_selector, e
                )
            return page
        except Exception as e:
            logger.warning("[frame] 无法定位 frame '{}': {}", frame_selector, e)
            return page

    async def _find_element(self, ctx, selector: str, timeout: int):
        """查找元素（支持多个候选选择器，兼容 Page 和 FrameLocator）"""
        candidates = self._parse_selectors(selector)

        for candidate in candidates:
            try:
                locator = ctx.locator(candidate)
                await locator.first.wait_for(state="visible", timeout=timeout)
                logger.info("[find] 选择器命中: {}", candidate)
                return locator.first
            except Exception:
                logger.debug("[find] 选择器未匹配: {}", candidate)
                continue

        logger.warning("[find] 所有选择器均未匹配: {}", selector)
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
        _PASSWORD_KEYWORDS = ("密码", "口令", "password", "passwd", "pwd")
        desc_lower = (step.description or "").lower()
        id_lower = (step.id or "").lower()
        masked = (
            "***"
            if any(k in desc_lower or k in id_lower for k in _PASSWORD_KEYWORDS)
            else value
        )
        logger.debug(
            "[input] value={}, clear={}, timeout={}ms",
            masked,
            clear,
            timeout,
        )

        async def _normal_fill(loc, t):
            await loc.fill(value, timeout=t)

        async def _force_input(loc, t):
            await loc.evaluate(
                _FORCE_INPUT_JS,
                {"val": value, "doClear": clear},
            )

        ok, _msg = await self._try_candidates_with_fallback(
            ctx,
            selector,
            timeout,
            _normal_fill,
            _force_input,
            label="[input]",
        )
        if ok:
            return True, ""
        return False, f"强制输入未找到可用元素: {selector}"


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
        logger.debug("[click] timeout={}ms", timeout)

        async def _normal_click(loc, t):
            await loc.click(timeout=t)

        async def _force_click(loc, t):
            await loc.dispatch_event("click")

        ok, _msg = await self._try_candidates_with_fallback(
            ctx,
            selector,
            timeout,
            _normal_click,
            _force_click,
            label="[click]",
        )
        if ok:
            return True, ""
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

        # value 为空或包含未解析变量时跳过
        if not value or "{{" in value:
            logger.debug("[select] value 为空或包含未解析变量，跳过: {}", value)
            return True, ""

        ctx = await self._resolve_frame(page, step)
        logger.debug(
            "[select] selector={}, value={}, timeout={}ms", selector, value, timeout
        )

        element = await self._find_element(ctx, selector, timeout)
        if not element:
            logger.warning("[select] 未找到选择元素: {}", selector)
            if step.required:
                return False, f"选择元素未找到: {selector}"
            return True, ""

        selected = await self._select_with_fallback(element, value, timeout)
        if not selected:
            logger.warning("[select] 未匹配到选项: {}", value)
            if step.required:
                return False, f"选择选项未匹配: {value}"
        return True, ""

    async def _select_with_fallback(self, element, value: str, timeout: int) -> bool:
        """优先按 value 精确选择，失败后按标签文本包含匹配。"""
        try:
            result = await element.select_option(value, timeout=timeout)
            if result:
                logger.info("[select] 精确匹配成功: value={}", value)
                return True
        except Exception:
            logger.debug("[select] 精确匹配失败: value={}, 尝试模糊匹配", value)

        option_texts = []
        try:
            option_texts = await element.evaluate(
                "(sel) => Array.from(sel.options || []).map(o => (o.textContent || '').trim())"
            )
        except Exception as e:
            logger.debug("[select] 获取选项列表失败: {}", e)
            option_texts = []

        logger.debug("[select] 可用选项: {}", option_texts)
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
                        logger.info(
                            "[select] 模糊匹配成功: '{}' 匹配选项 '{}'", value, current
                        )
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
        # value 为空或包含未解析变量时跳过
        if not value or "{{" in value:
            logger.debug("[click_select] value 为空或包含未解析变量，跳过: {}", value)
            return True, ""

        ctx = await self._resolve_frame(page, step)
        logger.debug(
            "[click_select] trigger={}, value={}, option_sel={}, timeout={}ms",
            selector,
            value,
            option_selector or "(auto)",
            timeout,
        )

        trigger = await self._find_element(ctx, selector, timeout)
        if not trigger:
            logger.debug("[click_select] 未找到触发器，跳过: {}", selector)
            if step.required:
                return False, f"click_select 触发器未找到: {selector}"
            return True, ""

        await trigger.click(timeout=timeout)
        select_delay = step.extra.get("select_delay", 500) if step.extra else 500
        logger.info("[click_select] 触发器已点击，等待 {}ms 后查找选项", select_delay)
        await page.wait_for_timeout(select_delay)

        clicked = await self._click_option(ctx, value, option_selector, timeout)
        if not clicked:
            logger.debug("[click_select] 未匹配到选项，跳过: {}", value)
            if step.required:
                return False, f"click_select 选项未匹配: {value}"
        return True, ""

    async def _click_option(
        self, ctx, text: str, option_selector: str, timeout: int
    ) -> bool:
        try:
            if option_selector:
                container = ctx.locator(option_selector).first
                option = container.get_by_text(text, exact=False).first
                logger.debug(
                    "[click_select] 在容器 '{}' 内搜索选项 '{}'", option_selector, text
                )
            else:
                option = ctx.get_by_text(text, exact=False).first
                logger.debug("[click_select] 全局搜索选项 '{}'", text)
            await option.wait_for(state="visible", timeout=timeout)
            await option.click(timeout=timeout)
            logger.info("[click_select] 选项点击成功: '{}'", text)
            return True
        except Exception:
            logger.debug("[click_select] 选项未找到或点击失败: '{}'", text)
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
        logger.debug("[wait] selector={}, timeout={}", selector, timeout)
        try:
            await ctx.locator(selector).first.wait_for(timeout=timeout)
        except TimeoutError:
            return False, f"等待元素超时 ({timeout}ms): {selector}"
        except Exception as e:
            return False, f"等待元素失败: {selector}, 错误: {e}"
        logger.info("[wait] 元素已出现: {}", selector)
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

        logger.debug("[wait_url] pattern={}", pattern)
        deadline = asyncio.get_running_loop().time() + timeout / 1000
        while True:
            current_url = page.url
            if compiled.search(current_url):
                logger.info("[wait_url] URL 已匹配: {}", current_url)
                return True, ""
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                logger.warning("[wait_url] 超时，当前URL: {}", current_url)
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
        # 使用 JS 安全的变量解析，防止密码等特殊字符导致语法错误
        script = step.script or ""
        if not script:
            return False, "eval 步骤需要 script 字段"

        resolved_script = resolver.resolve_for_js(script)

        store_as = step.store_as
        logger.debug("[eval] store_as={}", store_as)
        try:
            result = await page.evaluate(resolved_script)
        except Exception as e:
            return False, f"JavaScript 执行失败: {e}"

        if store_as:
            resolver.set_runtime_var(store_as, result)
            logger.debug("[eval] 结果存储到变量 {}: {}", store_as, str(result)[:80])

        # 返回结果值，用于日志显示
        result_str = str(result) if result is not None else ""
        return True, result_str[:100] if result_str else ""


class ScreenshotHandler(StepHandler):
    """截图处理器 — 运行时截图存入 logs/{date}/screenshots/ 目录"""

    @property
    def step_type(self) -> str:
        return StepType.SCREENSHOT

    async def execute(
        self, page, step: StepConfig, resolver: VariableResolver
    ) -> tuple[bool, str]:
        from app.utils.files import save_screenshot

        params = self.resolve_params(step, resolver)
        path = params.get("path", "")

        date_str = datetime.now().strftime("%Y-%m-%d")
        date_dir = LOGS_DIR / date_str / "screenshots"
        date_dir.mkdir(parents=True, exist_ok=True)

        if not path:
            task_id = resolver.config.task_id or "unknown"
            step_id = step.id or "s0"
            result = await save_screenshot(
                page, date_dir, task_id=task_id, step_id=step_id
            )
        else:
            safe_name = Path(path).name
            result = await save_screenshot(
                page, date_dir, prefix=safe_name.rsplit(".", 1)[0]
            )

        if result:
            # 转为可访问的 URL
            filename = Path(result).name
            url = f"/logs/{date_str}/screenshots/{filename}"
            logger.debug("[screenshot] path={}", url)
            return True, url
        return False, "截图失败"


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
        duration = int(params.get("duration", 1000))

        if duration > self.MAX_SLEEP_MS:
            logger.warning(
                "[sleep] duration={}ms 超过上限 {}ms，已截断",
                duration,
                self.MAX_SLEEP_MS,
            )
            duration = self.MAX_SLEEP_MS

        logger.debug("[sleep] duration={}ms", duration)
        await page.wait_for_timeout(duration)
        return True, ""


class OcrHandler(StepHandler):
    """验证码识别步骤处理器"""

    _ocr_instances: dict[bool, Any] = {}
    _ocr_lock = threading.Lock()
    _cleanup_timers: dict[bool, threading.Timer] = {}
    _IDLE_TIMEOUT = 300  # 空闲超时：5 分钟未使用则卸载模型

    @classmethod
    def _get_ocr(cls, old: bool = False):
        # 取消已有的清理定时器（还在用，不需要清理了）
        cls._cancel_cleanup(old)

        with cls._ocr_lock:
            if old in cls._ocr_instances:
                return cls._ocr_instances[old]

            try:
                import ddddocr

                instance = ddddocr.DdddOcr(old=old, show_ad=False)
            except ImportError as err:
                raise StepError(
                    "ddddocr 未安装，请在「设置 → 系统与日志」中安装 OCR 依赖"
                ) from err
            cls._ocr_instances[old] = instance
            return instance

    @classmethod
    def schedule_cleanup(cls, old: bool = False):
        """OCR 使用完毕后调用，启动定时清理"""
        cls._cancel_cleanup(old)
        timer = threading.Timer(cls._IDLE_TIMEOUT, cls._do_cleanup, args=[old])
        timer.daemon = True
        timer.start()
        cls._cleanup_timers[old] = timer

    @classmethod
    def _cancel_cleanup(cls, old: bool):
        timer = cls._cleanup_timers.pop(old, None)
        if timer is not None:
            timer.cancel()

    @classmethod
    def _do_cleanup(cls, old: bool):
        """定时器回调：卸载 OCR 模型释放内存"""
        with cls._ocr_lock:
            if old in cls._ocr_instances:
                del cls._ocr_instances[old]
                logger.info(
                    "[ocr] 模型已卸载 (old={})，空闲超过 {}s", old, cls._IDLE_TIMEOUT
                )
        cls._cleanup_timers.pop(old, None)
        import gc

        gc.collect()

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
        char_range = params.get("char_range")

        if not selector:
            return False, "ocr 步骤需要 selector（验证码图片选择器）"

        timeout = step.timeout or 10000
        ctx = await self._resolve_frame(page, step)
        logger.info(
            "[ocr] selector={}, target={}, old={}, char_range={}",
            selector,
            target_selector or "(无)",
            old,
            char_range,
        )

        # 查找验证码图片元素
        element = await self._find_element(ctx, selector, timeout)
        if not element:
            return False, f"未找到验证码图片元素: {selector}"

        # 截取验证码图片
        try:
            img_bytes = await element.screenshot()
            logger.debug("[ocr] 验证码截图成功, {} bytes", len(img_bytes))
        except Exception as e:
            return False, f"验证码截图失败: {e}"

        # 保存验证码截图到 logs 目录
        screenshot_url = ""
        try:
            date_str = datetime.now().strftime("%Y-%m-%d")
            date_dir = PROJECT_ROOT / "logs" / date_str / "screenshots"
            date_dir.mkdir(parents=True, exist_ok=True)
            task_id = resolver.config.task_id or "unknown"
            step_id = step.id or "ocr"
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            filename = f"{task_id}_{step_id}_{stamp}.png"
            local_path = date_dir / filename
            local_path.write_bytes(img_bytes)
            screenshot_url = f"/logs/{date_str}/screenshots/{filename}"
            logger.info("[ocr] 验证码截图已保存: {}", screenshot_url)
        except Exception as e:
            logger.warning("[ocr] 保存验证码截图失败: {}", e)

        # OCR 识别（识别失败也需要 schedule_cleanup）
        try:
            if char_range is not None:
                # 有字符范围限制时创建独立实例，避免 set_ranges 污染缓存实例
                import ddddocr

                ocr = ddddocr.DdddOcr(old=old, show_ad=False)
                ocr.set_ranges(char_range)
                logger.debug("[ocr] set_ranges({})", char_range)
            else:
                ocr = self._get_ocr(old=old)
            result = ocr.classification(img_bytes)
        except Exception as e:
            self.schedule_cleanup(old)
            return False, f"验证码识别失败: {e}"

        # 识别成功后用 try/finally 确保 schedule_cleanup
        try:
            logger.debug("[ocr] 识别结果: '{}'", result)

            # 存储到变量
            if store_as:
                resolver.set_runtime_var(store_as, result)
                logger.info("[ocr] 结果已存入变量 {}", store_as)

            # 自动填入目标输入框
            if target_selector:
                target = await self._find_element(ctx, target_selector, timeout)
                if not target:
                    return False, f"未找到验证码输入框: {target_selector}"
                try:
                    await target.fill(result, timeout=timeout)
                    logger.info(
                        "[ocr] 普通 fill 成功 -> {}, 值='{}'", target_selector, result
                    )
                except Exception:
                    logger.info(
                        "[ocr] 普通 fill 失败，降级到强制输入 -> {}", target_selector
                    )
                    await target.wait_for(state="attached", timeout=timeout)
                    await target.evaluate(
                        _FORCE_INPUT_JS,
                        {"val": result, "doClear": False},
                    )
                    logger.info(
                        "[ocr] 强制输入成功 -> {}, 值='{}'", target_selector, result
                    )

            # 返回结果，包含截图 URL
            message = result
            if screenshot_url:
                message += f" 截图: {screenshot_url}"
            return True, message
        finally:
            self.schedule_cleanup(old)


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
