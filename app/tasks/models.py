"""任务模型定义 — 数据结构、枚举和异常类。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from app.utils.logging import get_logger

logger = get_logger("task_models", side="BACKEND")

# 项目根目录（模块级，避免各处重复计算）
PROJECT_ROOT = Path(__file__).resolve().parents[2]

# 任务ID验证正则
TASK_ID_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")

# 默认超时配置（毫秒）
DEFAULT_STEP_TIMEOUT = 10000
DEFAULT_TASK_TIMEOUT = 30000


class TaskError(Exception):
    """任务执行错误"""

    pass


class StepError(TaskError):
    """步骤执行错误"""

    pass


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
    # click_select 步骤专用
    option_selector: str | None = None  # 选项容器选择器
    # ocr 步骤专用
    target_selector: str | None = None  # 验证码输入框选择器
    old: bool = False  # 是否使用旧版 OCR 模型
    char_range: str | int | None = None  # OCR 识别字符范围（0-7 或自定义字符串）
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
        "option_selector": None,
        "target_selector": None,
        "old": False,
        "char_range": None,
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
                "[StepConfig] 步骤 {} 的 frame 字段应为字符串，实际为 {}，已忽略",
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
        if extra_fields:
            logger.warning(
                "[StepConfig] 步骤 {} 包含未知字段（可能为 typo）: {}",
                data.get("id", "?"),
                ", ".join(sorted(extra_fields.keys())),
            )
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
    timeout: int = DEFAULT_TASK_TIMEOUT
    variables: dict[str, str] = field(default_factory=dict)
    steps: list[StepConfig] = field(default_factory=list)
    on_success: dict[str, Any] = field(default_factory=dict)
    on_failure: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(
        default_factory=dict
    )  # 用户自定义元数据，执行器不使用
    reveal_hidden: bool = False  # 默认关闭，由每个步骤的 force 降级自动处理隐藏输入框
    step_delay: float = 0.5

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TaskConfig:
        """从字典创建任务配置"""
        return cls(
            task_id=data.get("task_id", ""),
            name=data.get("name", "未命名任务"),
            description=data.get("description", ""),
            url=data.get("url", ""),
            timeout=data.get("timeout", DEFAULT_TASK_TIMEOUT),
            variables=data.get("variables", {}),
            steps=[StepConfig.from_dict(s) for s in data.get("steps", [])],
            on_success=data.get("on_success", {}),
            on_failure=data.get("on_failure", {}),
            metadata=data.get("metadata", {}),
            reveal_hidden=data.get("reveal_hidden", False),
            step_delay=float(data.get("step_delay", 0.5)),
        )

    def to_dict(self) -> dict[str, Any]:
        """序列化为紧凑字典，跳过空值和默认值"""
        result: dict[str, Any] = {
            "task_id": self.task_id,
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
        if self.reveal_hidden:
            result["reveal_hidden"] = True
        if self.step_delay != 0.5:
            result["step_delay"] = self.step_delay
        return result


@dataclass
class ScriptTaskInfo:
    """自定义脚本任务信息（不含 Playwright 步骤，直接通过子进程执行）"""

    task_id: str = ""
    name: str = "未命名脚本任务"
    description: str = ""
    script_path: Path = field(default_factory=Path)
    binary_path: str = ""  # 执行二进制路径，为空则使用 Python 解释器
