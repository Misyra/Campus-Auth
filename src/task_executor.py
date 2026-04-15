from __future__ import annotations

import json
import logging
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger("task_executor")
TASK_ID_PATTERN = re.compile(r"^[A-Za-z0-9_]+$")


def normalize_task_id(task_id: str | None) -> str:
    if not isinstance(task_id, str):
        return ""
    return task_id.strip()


def is_valid_task_id(task_id: str | None) -> bool:
    normalized = normalize_task_id(task_id)
    return bool(normalized and TASK_ID_PATTERN.fullmatch(normalized))


class TaskConfig:
    def __init__(self, config: dict[str, Any]):
        self.name: str = config.get("name", "未命名任务")
        self.description: str = config.get("description", "")
        self.version: str = config.get("version", "1.0")
        self.url: str = config.get("url", "")
        self.variables: dict[str, str] = config.get("variables", {})
        self.timeout: int = config.get("timeout", 5000)
        self.steps: list[dict[str, Any]] = config.get("steps", [])
        self.success_conditions: list[dict[str, Any]] = config.get(
            "success_conditions", []
        )
        self.on_success: dict[str, Any] = config.get("on_success", {})
        self.on_failure: dict[str, Any] = config.get("on_failure", {})


class TaskManager:
    def __init__(self, tasks_dir: Path):
        self.tasks_dir = tasks_dir
        self.tasks_dir.mkdir(parents=True, exist_ok=True)

    def _is_valid_task_id(self, task_id: str) -> bool:
        return is_valid_task_id(task_id)

    def _safe_task_path(self, task_id: str) -> Path | None:
        normalized_task_id = normalize_task_id(task_id)
        if not self._is_valid_task_id(normalized_task_id):
            return None

        base = self.tasks_dir.resolve()
        candidate = (self.tasks_dir / f"{normalized_task_id}.json").resolve()
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
                        "file": str(file),
                    }
                )
            except Exception as e:
                logger.warning(f"无法读取任务文件 {file}: {e}")
        return tasks

    def load_task(self, task_id: str) -> TaskConfig | None:
        file = self._safe_task_path(task_id)
        if file is None:
            return None
        if not file.exists():
            return None
        try:
            config = json.loads(file.read_text(encoding="utf-8"))
            return TaskConfig(config)
        except Exception as e:
            logger.error(f"无法加载任务 {task_id}: {e}")
            return None

    def save_task(self, task_id: str, config: dict[str, Any]) -> bool:
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
        normalized_task_id = normalize_task_id(task_id)
        if not self._is_valid_task_id(normalized_task_id):
            return False
        file = self._safe_task_path(normalized_task_id)
        if file is None or not file.exists():
            return False
        config_file = self.tasks_dir / "active.txt"
        try:
            config_file.write_text(normalized_task_id, encoding="utf-8")
            return True
        except Exception as e:
            logger.error(f"无法设置活动任务: {e}")
            return False


class TaskExecutor:
    MAX_TEMPLATE_DEPTH = 8

    # 项目根目录基准，用于截图等绝对路径
    _PROJECT_ROOT = Path(__file__).resolve().parents[1]

    def __init__(self, config: TaskConfig, env_vars: dict[str, str]):
        self.config = config
        self.env_vars = env_vars
        self.variables: dict[str, Any] = {
            "url": config.url,
            "name": config.name,
            "description": config.description,
            "version": config.version,
        }
        # 变量解析缓存：避免重复解析相同的模板
        self._variable_cache: dict[str, str] = {}

    def _resolve_variable(
        self,
        value: Any,
        depth: int = 0,
        visited: set[str] | None = None,
    ) -> Any:
        if not isinstance(value, str):
            return value

        # 快速路径：无模板标记直接返回
        if "{{" not in value and "}}" not in value:
            return value

        # 检查缓存（只在顶层调用时缓存）
        cache_key = value
        if depth == 0 and cache_key in self._variable_cache:
            return self._variable_cache[cache_key]

        visited_names = set() if visited is None else set(visited)
        if depth > self.MAX_TEMPLATE_DEPTH * 2:
            raise RuntimeError(
                f"变量展开层级超过限制({self.MAX_TEMPLATE_DEPTH})，请检查变量引用关系"
            )

        def replacer(match):
            var_name = match.group(1)
            if var_name in self.variables:
                resolved = str(self.variables[var_name])
                # 递归解析：如果结果仍包含模板标记，继续解析
                return self._resolve_variable(resolved, depth=depth + 1, visited=visited_names | {var_name})
            if hasattr(self.config, var_name):
                return str(getattr(self.config, var_name))
            if var_name in self.env_vars:
                return str(self.env_vars[var_name])
            if var_name in self.config.variables:
                if var_name in visited_names:
                    raise RuntimeError(f"检测到变量循环引用: {var_name}")
                val = self.config.variables[var_name]
                return self._resolve_variable(val, depth=depth + 1, visited=visited_names | {var_name})
            return match.group(0)  # 未找到的变量保留原样

        result = re.sub(r"\{\{(\w+)\}\}", replacer, value)
        # 如果结果仍有未解析的模板标记，再做一轮完整解析（处理链式引用如 url→AUTH_URL）
        if "{{" in result and depth <= self.MAX_TEMPLATE_DEPTH:
            result = self._resolve_variable(result, depth=depth + 1, visited=visited_names)

        # 缓存结果（只在顶层调用时缓存）
        if depth == 0:
            self._variable_cache[cache_key] = result

        return result

    def _resolve_timeout(
        self, step: dict[str, Any], default_timeout: int | None = None
    ) -> int:
        fallback = (
            default_timeout if default_timeout is not None else self.config.timeout
        )
        raw = step.get("timeout")
        if raw is None:
            return int(fallback)
        try:
            timeout = int(raw)
            return timeout if timeout > 0 else int(fallback)
        except (TypeError, ValueError):
            return int(fallback)

    def _assert_no_unresolved_template(self, text: str, field_name: str) -> None:
        if not isinstance(text, str):
            return
        match = re.search(r"\{\{[A-Za-z_][A-Za-z0-9_]*\}\}", text)
        if match:
            raise RuntimeError(f"{field_name} 存在未解析变量: {match.group(0)}")

    def _selector_candidates(self, selector: str) -> list[str]:
        if not isinstance(selector, str):
            return []
        return [item.strip() for item in selector.split(",") if item.strip()]

    async def _capture_failure_screenshot(self, page) -> str | None:
        if not self.config.on_failure.get("screenshot"):
            return None
        try:
            debug_dir = self._PROJECT_ROOT / "debug"
            debug_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            filename = f"task_failure_{stamp}.png"
            local_path = str(debug_dir / filename)
            await page.screenshot(path=local_path, full_page=True)
            web_path = f"/debug/{filename}"
            self.variables["_last_failure_screenshot"] = web_path
            return web_path
        except Exception as screenshot_error:
            logger.warning(f"失败截图保存失败: {screenshot_error}")
            return None

    def _attach_screenshot_hint(self, message: str, screenshot_url: str | None) -> str:
        base = message or self.config.on_failure.get("message", "步骤执行失败")
        if screenshot_url:
            return f"{base} 截图: {screenshot_url}"
        return base

    async def _find_first_visible_locator(self, page, selector: str, timeout: int):
        candidates = self._selector_candidates(selector)
        if not candidates:
            raise RuntimeError("选择器不能为空")

        deadline = time.monotonic() + max(0.2, timeout / 1000)
        last_error: Exception | None = None

        while time.monotonic() < deadline:
            for candidate in candidates:
                locator = page.locator(candidate)
                try:
                    count = await locator.count()
                except Exception as e:
                    last_error = e
                    continue

                for i in range(count):
                    element = locator.nth(i)
                    try:
                        if await element.is_visible(timeout=50):
                            return element
                    except Exception as e:
                        last_error = e

            await page.wait_for_timeout(100)

        if last_error:
            raise RuntimeError(
                f"未找到可见元素: {selector}; 已等待 {timeout}ms; 最后错误: {last_error}"
            )
        raise RuntimeError(f"未找到可见元素: {selector}; 已等待 {timeout}ms")

    async def execute(self, page) -> tuple[bool, str]:
        try:
            if self.config.steps:
                first_step_type = (
                    str(self.config.steps[0].get("type", "")).strip().lower()
                )
                if first_step_type != "navigate":
                    default_url = self._resolve_variable(self.config.url)
                    if default_url:
                        logger.info("任务未配置首步导航，自动打开任务URL")
                        await page.goto(
                            default_url,
                            wait_until="domcontentloaded",
                            timeout=self.config.timeout,
                        )

            for step in self.config.steps:
                success, message = await self._execute_step(page, step)
                if not success:
                    screenshot_url = await self._capture_failure_screenshot(page)
                    error_message = message or step.get("description", "步骤执行失败")
                    return False, self._attach_screenshot_hint(
                        error_message, screenshot_url
                    )

            current_url = getattr(page, "url", "") or ""
            self.variables["_current_url"] = current_url

            for condition in self.config.success_conditions:
                if not self._check_condition(condition, current_url):
                    screenshot_url = await self._capture_failure_screenshot(page)
                    return False, self._attach_screenshot_hint(
                        self.config.on_failure.get("message", "条件不满足"),
                        screenshot_url,
                    )

            return True, self.config.on_success.get("message", "任务执行成功")

        except Exception as e:
            logger.error(f"任务执行异常: {e}")
            screenshot_url = await self._capture_failure_screenshot(page)
            return False, self._attach_screenshot_hint(str(e), screenshot_url)

    async def _execute_step(self, page, step: dict[str, Any]) -> tuple[bool, str]:
        step_type = step.get("type")
        description = step.get("description", "")
        logger.info(f"执行步骤: {description}")

        try:
            if step_type == "navigate":
                url = self._resolve_variable(step.get("url", ""))
                self._assert_no_unresolved_template(url, "导航地址")
                wait_until = step.get("wait_until", "networkidle")
                timeout = self._resolve_timeout(step)
                logger.info(
                    f"步骤详情[navigate]: url={url}, wait_until={wait_until}, timeout={timeout}ms"
                )
                await page.goto(url, wait_until=wait_until, timeout=timeout)
                return True, ""

            elif step_type == "input":
                selector = step.get("selector", "")
                value = self._resolve_variable(step.get("value", ""))
                self._assert_no_unresolved_template(value, "输入值")
                clear = step.get("clear", True)
                timeout = self._resolve_timeout(step)
                logger.info(
                    f"步骤详情[input]: selector={selector}, clear={clear}, timeout={timeout}ms"
                )
                element = await self._find_first_visible_locator(
                    page, selector, timeout
                )
                if clear:
                    await element.fill("", timeout=timeout)
                await element.fill(value, timeout=timeout)
                return True, ""

            elif step_type == "click":
                selector = step.get("selector", "")
                timeout = self._resolve_timeout(step)
                logger.info(
                    f"步骤详情[click]: selector={selector}, timeout={timeout}ms"
                )
                element = await self._find_first_visible_locator(
                    page, selector, timeout
                )
                await element.click(timeout=timeout)
                return True, ""

            elif step_type == "select":
                selector = step.get("selector", "")
                value = self._resolve_variable(step.get("value", ""))
                self._assert_no_unresolved_template(value, "下拉选项值")
                timeout = self._resolve_timeout(step)
                logger.info(
                    f"步骤详情[select]: selector={selector}, value={value}, timeout={timeout}ms"
                )
                element = await self._find_first_visible_locator(
                    page, selector, timeout
                )
                await element.select_option(value, timeout=timeout)
                return True, ""

            elif step_type == "wait":
                selector = step.get("selector", "")
                timeout = self._resolve_timeout(step, default_timeout=5000)
                logger.info(f"步骤详情[wait]: selector={selector}, timeout={timeout}ms")
                await page.wait_for_selector(selector, timeout=timeout)
                return True, ""

            elif step_type == "wait_url":
                pattern = step.get("pattern", "")
                timeout = self._resolve_timeout(step, default_timeout=5000)
                logger.info(
                    f"步骤详情[wait_url]: pattern={pattern}, timeout={timeout}ms"
                )
                await page.wait_for_url(re.compile(pattern), timeout=timeout)
                return True, ""

            elif step_type == "eval":
                script = self._resolve_variable(step.get("script", ""))
                self._assert_no_unresolved_template(script, "eval脚本")
                store_as = step.get("store_as")
                result = await page.evaluate(script)
                if store_as:
                    self.variables[store_as] = result
                return True, ""

            elif step_type == "custom_js":
                script = self._resolve_variable(step.get("script", ""))
                self._assert_no_unresolved_template(script, "custom_js脚本")
                await page.evaluate(script)
                return True, ""

            elif step_type == "screenshot":
                path = step.get("path", "")
                if not path:
                    debug_dir = self._PROJECT_ROOT / "debug"
                    debug_dir.mkdir(parents=True, exist_ok=True)
                    path = str(debug_dir / "step_screenshot.png")
                else:
                    os.makedirs(os.path.dirname(path) or "debug", exist_ok=True)
                await page.screenshot(path=path)
                return True, ""

            else:
                return False, f"未知步骤类型: {step_type}"

        except Exception as e:
            return False, f"{description} 失败: {str(e)}"

    def _check_condition(
        self, condition: dict[str, Any], current_url: str = ""
    ) -> bool:
        cond_type = condition.get("type")

        if cond_type == "variable":
            var_name = condition.get("variable")
            expected = condition.get("value")
            if not isinstance(var_name, str) or not var_name:
                return False
            actual = self.variables.get(var_name)
            return actual == expected

        elif cond_type == "url_contains":
            pattern = condition.get("pattern", "")
            url = current_url or str(self.variables.get("_current_url", ""))
            if not pattern:
                return bool(url)
            if pattern in url:
                return True
            try:
                return bool(re.search(pattern, url))
            except re.error:
                return False

        return True
