"""任务验证器 — 验证任务配置的合法性。"""

from __future__ import annotations

from typing import Any

from app.utils.logging import get_logger

from .models import TASK_ID_PATTERN, StepType

logger = get_logger("task_validator", source="task")


class TaskValidator:
    """任务验证器"""

    REQUIRED_STEP_FIELDS = {"id", "type"}
    VALID_STEP_TYPES = {t.value for t in StepType} | {"custom_js"}

    @classmethod
    def validate(cls, config: dict[str, Any]) -> tuple[bool, list[str]]:
        """验证任务配置

        Returns:
            (is_valid, error_messages)
        """
        errors = []

        if not isinstance(config, dict):
            errors.append("配置必须是对象")
            return False, errors

        # 验证基本字段
        if not config.get("name"):
            errors.append("任务必须包含 'name' 字段")

        if "steps" not in config:
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

        if not isinstance(step, dict):
            errors.append(f"{prefix} 必须是对象")
            return errors

        # 检查必需字段
        missing = cls.REQUIRED_STEP_FIELDS - set(step.keys())
        if missing:
            errors.append(f"{prefix} 缺少必需字段: {missing}")
            return errors

        # 验证步骤 ID 格式
        step_id = step.get("id", "")
        if not isinstance(step_id, str) or not TASK_ID_PATTERN.fullmatch(step_id):
            errors.append(
                f"{prefix} id '{step_id}' 格式无效，须匹配 ^[A-Za-z][A-Za-z0-9_]*$"
            )

        # 验证步骤类型
        step_type = step.get("type", "")
        if step_type not in cls.VALID_STEP_TYPES:
            errors.append(f"{prefix} 未知的步骤类型: '{step_type}'")

        # 根据类型验证特定字段
        _SELECTOR_REQUIRED = {
            StepType.INPUT,
            StepType.CLICK,
            StepType.SELECT,
            StepType.CLICK_SELECT,
            StepType.WAIT,
        }
        if step_type in _SELECTOR_REQUIRED and not step.get("selector"):
            errors.append(f"{prefix} ({step_type}) 需要 'selector' 字段")

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
