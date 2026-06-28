"""任务执行引擎 — 拆分自 src/task_executor.py。

重新导出所有公开接口，保持向后兼容。
"""

from app.constants import DEFAULT_STEP_TIMEOUT_MS, DEFAULT_TASK_TIMEOUT_MS

from .browser_runner import BrowserTaskRunner
from .manager import TaskManager, is_valid_task_id, normalize_task_id
from .models import (
    TASK_ID_PATTERN,
    ScriptTaskInfo,
    StepConfig,
    StepError,
    StepType,
    TaskConfig,
    TaskError,
)
from .step_handlers import (
    ClickHandler,
    ClickSelectHandler,
    EvalHandler,
    InputHandler,
    OcrHandler,
    ScreenshotHandler,
    SelectHandler,
    SleepHandler,
    StepHandler,
    WaitHandler,
    WaitUrlHandler,
)
from .validator import TaskValidator
from .variable_resolver import VariableResolver

__all__ = [
    "DEFAULT_STEP_TIMEOUT_MS",
    "DEFAULT_TASK_TIMEOUT_MS",
    "TASK_ID_PATTERN",
    "ClickHandler",
    "ClickSelectHandler",
    "EvalHandler",
    "InputHandler",
    "OcrHandler",
    "ScreenshotHandler",
    "ScriptTaskInfo",
    "SelectHandler",
    "SleepHandler",
    "StepConfig",
    "StepError",
    "StepHandler",
    "StepType",
    "TaskConfig",
    "TaskError",
    "BrowserTaskRunner",
    "TaskManager",
    "TaskValidator",
    "VariableResolver",
    "WaitHandler",
    "WaitUrlHandler",
    "is_valid_task_id",
    "normalize_task_id",
]
