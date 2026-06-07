"""任务执行引擎 — 拆分自 src/task_executor.py。

重新导出所有公开接口，保持向后兼容。
"""

from .models import (
    DEFAULT_STEP_TIMEOUT,
    DEFAULT_TASK_TIMEOUT,
    PROJECT_ROOT,
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
    StepExecutorRegistry,
    StepHandler,
    WaitHandler,
    WaitUrlHandler,
)
from .variable_resolver import VariableResolver
from .validator import TaskValidator
from .executor import TaskExecutor
from .manager import TaskManager, is_valid_task_id, normalize_task_id

__all__ = [
    "DEFAULT_STEP_TIMEOUT",
    "DEFAULT_TASK_TIMEOUT",
    "PROJECT_ROOT",
    "TASK_ID_PATTERN",
    "ScriptTaskInfo",
    "StepConfig",
    "StepError",
    "StepType",
    "TaskConfig",
    "TaskError",
    "ClickHandler",
    "ClickSelectHandler",
    "EvalHandler",
    "InputHandler",
    "OcrHandler",
    "ScreenshotHandler",
    "SelectHandler",
    "SleepHandler",
    "StepExecutorRegistry",
    "StepHandler",
    "WaitHandler",
    "WaitUrlHandler",
    "VariableResolver",
    "TaskValidator",
    "TaskExecutor",
    "TaskManager",
    "is_valid_task_id",
    "normalize_task_id",
]
