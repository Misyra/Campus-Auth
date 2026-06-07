"""任务执行器 — 执行浏览器自动化任务。"""

from __future__ import annotations

import asyncio
import time
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any

from .models import StepConfig, StepType, TaskConfig, PROJECT_ROOT
from .step_handlers import StepExecutorRegistry
from .variable_resolver import VariableResolver

from app.utils.logging import get_logger

logger = get_logger("task_executor", side="BACKEND")


class TaskExecutor:
    """任务执行器"""

    DEFAULT_STEP_TIMEOUT = 10000
    DEFAULT_TASK_TIMEOUT = 30000
    DEFAULT_NAVIGATION_TIMEOUT = 15000

    def __init__(
        self,
        config: TaskConfig,
        template_vars: dict[str, str] | None = None,
        screenshot_dir: Path | str | None = None,
        default_timeout: int | None = None,
        navigation_timeout: int | None = None,
        monitor_config: dict[str, Any] | None = None,
    ):
        self.config = config
        self.template_vars = template_vars or {}
        self.default_timeout = default_timeout or self.DEFAULT_STEP_TIMEOUT
        self.navigation_timeout = navigation_timeout or self.DEFAULT_NAVIGATION_TIMEOUT
        self.resolver = VariableResolver(config, self.template_vars)
        self.registry = StepExecutorRegistry()
        self._step_results: list[dict[str, Any]] = []
        self._screenshot_dir = Path(screenshot_dir) if screenshot_dir else None
        self.monitor_config = monitor_config

    async def execute(self, page) -> tuple[bool, str]:
        """执行任务

        Returns:
            (success, message)
        """
        task_start = time.perf_counter()
        task_timeout_ms = self.config.timeout or self.DEFAULT_TASK_TIMEOUT
        task_deadline = task_start + task_timeout_ms / 1000
        logger.info(
            "任务开始 [{}], {} 个步骤, 超时 {}ms",
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
                await page.wait_for_selector("input,textarea", timeout=5000)
            except TimeoutError:
                pass  # 表单元素未出现，非致命，继续执行

            # reveal_hidden: 强制显示所有隐藏输入框，让后续 fill() 可以直接操作
            if self.config.reveal_hidden and any(
                s.type != StepType.EVAL for s in self.config.steps
            ):
                await self._reveal_hidden_inputs(page)

            for i, step in enumerate(self.config.steps):
                # 任务超时检查
                remaining_s = task_deadline - time.perf_counter()
                if remaining_s <= 0:
                    return await self._handle_failure(
                        page, None, f"任务超时 ({task_timeout_ms}ms)"
                    )
                if i > 0:
                    await asyncio.sleep(self.config.step_delay)
                step_start = time.perf_counter()
                success, message = await self._execute_step(page, step, task_deadline)
                step_elapsed = (time.perf_counter() - step_start) * 1000
                status = "OK" if success else "FAIL"
                logger.info(
                    "  步骤[{}/{}] {} ({}) → {} ({:.0f}ms){}",
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
                return await self._handle_failure(page, None, "网络验证未通过")

            total_elapsed = (time.perf_counter() - task_start) * 1000
            logger.info("任务成功 [{}] 总耗时 {:.0f}ms", self.config.name, total_elapsed)
            return await self._handle_success(page)

        except (TimeoutError, OSError) as e:
            total_elapsed = (time.perf_counter() - task_start) * 1000
            logger.error(
                "任务异常 [{}] 耗时 {:.0f}ms: {}", self.config.name, total_elapsed, e
            )
            return await self._handle_failure(page, None, str(e))
        except Exception as e:
            total_elapsed = (time.perf_counter() - task_start) * 1000
            logger.exception(
                "任务未知异常 [{}] 耗时 {:.0f}ms", self.config.name, total_elapsed
            )
            try:
                return await self._handle_failure(page, None, f"内部错误: {e}")
            except Exception:
                return (False, f"内部错误: {e}")

    async def _auto_navigate(self, page) -> None:
        """自动导航到任务URL（优先任务 url，回退到 LOGIN_URL）

        使用 'load' 事件 + URL 稳定检测处理 JS 重定向链：
        - 校园网门户常有 DNS 劫持 → 重定向到认证页
        - SSO 统一认证 → 多次 JS redirect
        """
        url = self.resolver.resolve(self.config.url) if self.config.url else ""
        if not url:
            url = self.template_vars.get("LOGIN_URL", "").strip()
        if url:
            logger.info("自动导航到任务URL: {} (超时 {}ms)", url, self.navigation_timeout)
            await page.goto(url, wait_until="load", timeout=self.navigation_timeout)
            await self._wait_url_stable(page)

    async def _wait_url_stable(self, page, timeout_ms: int = 3000):
        """等待 URL 稳定，处理 JS 重定向链（最多 5 跳）"""

        deadline = time.perf_counter() + timeout_ms / 1000
        last_url = page.url
        redirects = 0
        max_redirects = 5
        while time.perf_counter() < deadline and redirects < max_redirects:
            await asyncio.sleep(0.5)
            current = page.url
            if current != last_url:
                logger.info("URL 重定向: {} → {}", last_url, current)
                last_url = current
                redirects += 1
                deadline = max(deadline, time.perf_counter() + timeout_ms / 1000)

    async def _reveal_hidden_inputs(self, page) -> int:
        """强制显示所有隐藏的表单输入框（含同源 iframe）。
        通过 JS 将 display:none / visibility:hidden / opacity:0 的 input 变为可见，
        后续 fill()/click() 可直接操作，无需 force 降级。覆盖 text/password/checkbox/radio 等。"""
        logger.info("[reveal] 强制显示隐藏输入框")
        reveal_js = """
            () => {
                const inputs = document.querySelectorAll('input,textarea');
                let count = 0;
                inputs.forEach(el => {
                    try {
                        if (el.type === 'hidden') return;
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
        """
        total = 0
        # 主文档
        total += await page.evaluate(reveal_js)
        # 同源 iframe
        for frame in page.frames[1:]:
            try:
                total += await frame.evaluate(reveal_js)
            except Exception:
                pass  # 跨域 frame 会抛错，静默跳过
        logger.info("[reveal] 已强制显示 {} 个隐藏输入框", total)
        return total

    async def _execute_step(
        self, page, step: StepConfig, task_deadline: float | None = None
    ) -> tuple[bool, str]:
        """执行单个步骤。

        Args:
            task_deadline: 任务截止时间（perf_counter），用于截断步骤超时/时长，
                          防止 sleep 等长耗时步骤超过任务总超时。
                          仅在主执行流程中传入，调试模式不传。
        """
        handler = self.registry.get(step.type)
        if not handler:
            return False, f"未知的步骤类型: {step.type}"

        # 创建副本而非修改原对象，避免并发安全问题
        effective_step = step
        if task_deadline is not None:
            remaining_ms = max(0, int((task_deadline - time.perf_counter()) * 1000))
            effective_timeout = step.timeout or 10000
            overrides = {}
            if remaining_ms < effective_timeout:
                logger.debug(
                    "[timeout] 步骤 {} 超时从 {}ms 截断到 {}ms",
                    step.id, effective_timeout, remaining_ms,
                )
                overrides['timeout'] = remaining_ms
            if step.type == StepType.SLEEP and remaining_ms < step.duration:
                logger.debug(
                    "[timeout] 步骤 {} 时长从 {}ms 截断到 {}ms",
                    step.id, step.duration, remaining_ms,
                )
                overrides['duration'] = remaining_ms
            if overrides:
                effective_step = replace(step, **overrides)

        try:
            return await handler.execute(page, effective_step, self.resolver)
        except Exception as e:
            logger.error("步骤 [{}/{}] 执行失败: {}", step.id, step.type, e)
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
        if self.monitor_config:
            return await self._network_detection_check()
        return True

    async def _network_detection_check(self) -> bool:
        """任务步骤全部通过后，验证网络是否已恢复连通。"""
        try:
            from app.network.decision import is_network_available

            await asyncio.sleep(5)  # 等待 Portal 处理认证请求

            cfg = self.monitor_config
            enable_tcp = cfg.get("enable_tcp_check", True)
            enable_http = cfg.get("enable_http_check", True)
            timeout = cfg.get("network_check_timeout", 2)

            # 解析 portal 检测 URL
            portal_checks = None
            portal_raw = cfg.get("portal_check_urls", "")
            if isinstance(portal_raw, str) and portal_raw.strip():
                portal_checks = []
                for line in portal_raw.splitlines():
                    line = line.strip()
                    if "|" in line:
                        url, _, expected = line.partition("|")
                        url, expected = url.strip(), expected.strip()
                        if url and expected:
                            portal_checks.append((url, expected))
            elif isinstance(portal_raw, list) and portal_raw:
                portal_checks = [
                    (e[0], e[1]) for e in portal_raw if len(e) >= 2 and e[0] and e[1]
                ]

            # 解析 TCP 检测目标
            from app.utils.network_helpers import parse_host_port
            targets = cfg.get("ping_targets", [])
            if isinstance(targets, str):
                targets = [t.strip() for t in targets.split(",") if t.strip()]
            test_sites = parse_host_port(targets) or None

            logger.info(
                "验证网络连通性 (网络检测方式: TCP={}, HTTP={}, Portal={}, 超时={}s)",
                "开" if enable_tcp else "关",
                "开" if enable_http else "关",
                "开" if bool(portal_checks) else "关",
                timeout,
            )

            test_urls = cfg.get("test_urls", None)

            result = await asyncio.to_thread(
                is_network_available,
                test_sites=test_sites,
                test_urls=test_urls,
                timeout=timeout,
                enable_tcp=enable_tcp,
                enable_http=enable_http,
                portal_checks=portal_checks,
            )

            if result:
                logger.info("网络已恢复，登录认证生效")
            else:
                logger.warning("网络仍不可达，登录认证未生效")

            return result

        except Exception as e:
            logger.error("网络验证异常: {}", e)
            return False

    async def _handle_success(self, page) -> tuple[bool, str]:
        """处理成功情况"""
        message = self.config.on_success.get("message", "任务执行成功")
        logger.info("任务执行成功: {}", message)
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
        logger.error("任务执行失败: {}: {}", base_message, reason)
        return False, message

    async def _capture_screenshot(self, page) -> str | None:
        """捕获截图 → 指定目录或 logs/{date}/screenshots/ 目录"""
        try:
            if self._screenshot_dir:
                out_dir = self._screenshot_dir
                url_prefix = "/temp"
            else:
                date_str = datetime.now().strftime("%Y-%m-%d")
                out_dir = PROJECT_ROOT / "logs" / date_str / "screenshots"
                url_prefix = f"/logs/{date_str}/screenshots"
            out_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            task_id = self.config.task_id or "unknown"
            filename = f"{task_id}_{stamp}.png"
            local_path = str(out_dir / filename)
            await page.screenshot(path=local_path, full_page=True)
            return f"{url_prefix}/{filename}"
        except Exception as e:
            logger.warning("截图失败: {}", e)
            return None
