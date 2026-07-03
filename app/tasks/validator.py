"""任务验证器 — 验证任务配置的合法性。"""

from __future__ import annotations

from typing import Any

from app.utils.logging import get_logger

from .models import TASK_ID_PATTERN, StepType

logger = get_logger("task_validator", source="backend")


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
            seen_ids: set[str] = set()
            for i, step in enumerate(config["steps"]):
                step_errors = cls._validate_step(step, i)
                errors.extend(step_errors)
                # 检查步骤 ID 重复
                if isinstance(step, dict):
                    sid = step.get("id", "")
                    if sid and sid in seen_ids:
                        errors.append(f"steps[{i}] 步骤ID '{sid}' 重复")
                    seen_ids.add(sid)

        variables = config.get("variables")
        if variables is not None and not isinstance(variables, dict):
            errors.append("'variables' 必须是对象（dict），当前值类型: " + type(variables).__name__)

        timeout = config.get("timeout")
        if timeout is not None and (
            not isinstance(timeout, int | float) or timeout <= 0
        ):
            errors.append(f"任务级 timeout 必须为正数，当前值: {timeout}")

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
                f"{prefix} 步骤ID格式无效，只能包含字母、数字、下划线和连字符，长度不超过64"
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
            errors.append(f"{prefix} 脚本执行步骤需要提供脚本内容")

        if step_type == StepType.OCR and not step.get("selector"):
            errors.append(f"{prefix} (ocr) 需要 'selector' 字段（验证码图片选择器）")

        # 验证 timeout 值
        timeout = step.get("timeout")
        if timeout is not None and (
            not isinstance(timeout, int | float) or timeout <= 0
        ):
            errors.append(f"{prefix} timeout 必须为正数，当前值: {timeout}")

        return errors
