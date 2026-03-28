from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger("task_executor")


class TaskConfig:
    def __init__(self, config: dict[str, Any]):
        self.name: str = config.get("name", "未命名任务")
        self.description: str = config.get("description", "")
        self.version: str = config.get("version", "1.0")
        self.url: str = config.get("url", "")
        self.variables: dict[str, str] = config.get("variables", {})
        self.timeout: int = config.get("timeout", 30000)
        self.steps: list[dict[str, Any]] = config.get("steps", [])
        self.success_conditions: list[dict[str, Any]] = config.get("success_conditions", [])
        self.on_success: dict[str, Any] = config.get("on_success", {})
        self.on_failure: dict[str, Any] = config.get("on_failure", {})


class TaskManager:
    def __init__(self, tasks_dir: Path):
        self.tasks_dir = tasks_dir
        self.tasks_dir.mkdir(parents=True, exist_ok=True)

    def list_tasks(self) -> list[dict[str, str]]:
        tasks = []
        for file in self.tasks_dir.glob("*.json"):
            try:
                config = json.loads(file.read_text(encoding="utf-8"))
                tasks.append({
                    "id": file.stem,
                    "name": config.get("name", file.stem),
                    "description": config.get("description", ""),
                    "file": str(file),
                })
            except Exception as e:
                logger.warning(f"无法读取任务文件 {file}: {e}")
        return tasks

    def load_task(self, task_id: str) -> TaskConfig | None:
        file = self.tasks_dir / f"{task_id}.json"
        if not file.exists():
            return None
        try:
            config = json.loads(file.read_text(encoding="utf-8"))
            return TaskConfig(config)
        except Exception as e:
            logger.error(f"无法加载任务 {task_id}: {e}")
            return None

    def save_task(self, task_id: str, config: dict[str, Any]) -> bool:
        file = self.tasks_dir / f"{task_id}.json"
        try:
            file.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
            return True
        except Exception as e:
            logger.error(f"无法保存任务 {task_id}: {e}")
            return False

    def delete_task(self, task_id: str) -> bool:
        file = self.tasks_dir / f"{task_id}.json"
        if task_id == "default":
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
        config_file = self.tasks_dir / "active.txt"
        try:
            config_file.write_text(task_id, encoding="utf-8")
            return True
        except Exception as e:
            logger.error(f"无法设置活动任务: {e}")
            return False


class TaskExecutor:
    def __init__(self, config: TaskConfig, env_vars: dict[str, str]):
        self.config = config
        self.env_vars = env_vars
        self.variables: dict[str, Any] = {}

    def _resolve_variable(self, value: str) -> str:
        if not isinstance(value, str):
            return value

        def replacer(match):
            var_name = match.group(1)
            if var_name in self.variables:
                return str(self.variables[var_name])
            if var_name in self.env_vars:
                return str(self.env_vars[var_name])
            if var_name in self.config.variables:
                val = self.config.variables[var_name]
                return self._resolve_variable(val)
            return match.group(0)

        return re.sub(r'\{\{(\w+)\}\}', replacer, value)

    async def execute(self, page) -> tuple[bool, str]:
        try:
            for step in self.config.steps:
                success, message = await self._execute_step(page, step)
                if not success:
                    if self.config.on_failure.get("screenshot"):
                        os.makedirs("debug", exist_ok=True)
                        await page.screenshot(path="debug/task_failure.png")
                    return False, message or step.get("description", "步骤执行失败")

            for condition in self.config.success_conditions:
                if not self._check_condition(condition):
                    return False, self.config.on_failure.get("message", "条件不满足")

            return True, self.config.on_success.get("message", "任务执行成功")

        except Exception as e:
            logger.error(f"任务执行异常: {e}")
            return False, str(e)

    async def _execute_step(self, page, step: dict[str, Any]) -> tuple[bool, str]:
        step_type = step.get("type")
        description = step.get("description", "")
        logger.info(f"执行步骤: {description}")

        try:
            if step_type == "navigate":
                url = self._resolve_variable(step.get("url", ""))
                wait_until = step.get("wait_until", "networkidle")
                await page.goto(url, wait_until=wait_until, timeout=self.config.timeout)
                return True, ""

            elif step_type == "input":
                selector = step.get("selector", "")
                value = self._resolve_variable(step.get("value", ""))
                clear = step.get("clear", True)
                element = page.locator(selector).first
                if clear:
                    await element.fill("")
                await element.fill(value)
                return True, ""

            elif step_type == "click":
                selector = step.get("selector", "")
                element = page.locator(selector).first
                await element.click()
                return True, ""

            elif step_type == "select":
                selector = step.get("selector", "")
                value = self._resolve_variable(step.get("value", ""))
                await page.select_option(selector, value)
                return True, ""

            elif step_type == "wait":
                selector = step.get("selector", "")
                timeout = step.get("timeout", 10000)
                await page.wait_for_selector(selector, timeout=timeout)
                return True, ""

            elif step_type == "wait_url":
                pattern = step.get("pattern", "")
                timeout = step.get("timeout", 10000)
                await page.wait_for_url(re.compile(pattern), timeout=timeout)
                return True, ""

            elif step_type == "eval":
                script = step.get("script", "")
                store_as = step.get("store_as")
                result = await page.evaluate(script)
                if store_as:
                    self.variables[store_as] = result
                return True, ""

            elif step_type == "custom_js":
                script = step.get("script", "")
                await page.evaluate(script)
                return True, ""

            elif step_type == "screenshot":
                path = step.get("path", "debug/step_screenshot.png")
                os.makedirs("debug", exist_ok=True)
                await page.screenshot(path=path)
                return True, ""

            else:
                return False, f"未知步骤类型: {step_type}"

        except Exception as e:
            return False, f"{description} 失败: {str(e)}"

    def _check_condition(self, condition: dict[str, Any]) -> bool:
        cond_type = condition.get("type")

        if cond_type == "variable":
            var_name = condition.get("variable")
            expected = condition.get("value")
            actual = self.variables.get(var_name)
            return actual == expected

        elif cond_type == "url_contains":
            pattern = condition.get("pattern", "")
            return pattern in str(self.variables.get("_current_url", ""))

        return True
