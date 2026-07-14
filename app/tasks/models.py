"""任务模型定义 — 数据结构、枚举和异常类。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from app.constants import DEFAULT_TASK_TIMEOUT_MS
from app.utils.logging import get_logger

logger = get_logger("task_models", source="backend")

# 任务ID验证正则
TASK_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


def _is_valid_step(s: Any) -> bool:
    """检查 step 是否为有效的 dict，非 dict 的 step 记录警告。"""
    if isinstance(s, dict):
        return True
    logger.warning("steps 中包含非对象元素，已跳过: {}", type(s).__name__)
    return False


def _safe_float(value: Any, default: float) -> float:
    """安全的 float 转换，异常时返回默认值。"""
    if value is None:
        return default
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


class StepError(Exception):
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
    ASSERT_TEXT = "assert_text"


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
        from dataclasses import MISSING, fields as dc_fields

        for f in dc_fields(self):
            if f.name in ("id", "type", "extra"):
                continue
            value = getattr(self, f.name)
            # 跳过 None 和等于默认值的字段
            if value is None:
                continue
            if f.default is not MISSING and value == f.default:
                continue
            if f.default_factory is not MISSING and value == f.default_factory():
                continue
            result[f.name] = value
        if self.extra:
            result.update(self.extra)
        return result


@dataclass
class JsCheck:
    """JS 表达式断言 — runner 在步骤跑完后评估，返回真值即命中。

    用于 success_checks / failure_checks，可覆盖 DOM 文本、URL、Cookie、
    localStorage 等任意页面状态判定。

    expr 经 VariableResolver.resolve_for_js 解析，支持 {{VAR}} 模板。
    """

    expr: str                            # JS 表达式，需返回真值即命中
    message: str = ""                    # 命中时显示的消息（可省略，默认用 expr 前 40 字符）
    timeout: int = 2000                  # 等待/轮询超时（ms），超时未命中视为 false

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> JsCheck:
        """从字典创建，仅识别 expr/message/timeout 三个字段。"""
        return cls(
            expr=str(data.get("expr", "")),
            message=str(data.get("message", "")),
            timeout=int(data.get("timeout", 2000)),
        )

    def to_dict(self) -> dict[str, Any]:
        """序列化为紧凑字典，跳过默认值。"""
        result: dict[str, Any] = {"expr": self.expr}
        if self.message:
            result["message"] = self.message
        if self.timeout != 2000:
            result["timeout"] = self.timeout
        return result


@dataclass
class TaskConfig:
    """任务配置"""

    task_id: str = ""
    name: str = "未命名任务"
    description: str = ""
    url: str = ""
    timeout: int = DEFAULT_TASK_TIMEOUT_MS
    variables: dict[str, str] = field(default_factory=dict)
    steps: list[StepConfig] = field(default_factory=list)
    on_success: dict[str, Any] = field(default_factory=dict)
    on_failure: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(
        default_factory=dict
    )  # 用户自定义元数据，执行器不使用
    reveal_hidden: bool = False  # 默认关闭，由每个步骤的 force 降级自动处理隐藏输入框
    step_delay: float = 0.5
    navigation_wait: float = 1  # 页面加载后额外等待秒数，用于等待 AJAX 初始化
    # JS 表达式断言列表
    # - failure_checks 任一命中 → INVALID_CREDENTIAL（终态，不重试）
    # - success_checks 任一命中 → SUCCESS
    # - 两者均未命中 → 走兜底（登录路径网络检测，通用路径信任步骤）
    success_checks: list[JsCheck] = field(default_factory=list)
    failure_checks: list[JsCheck] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TaskConfig:
        """从字典创建任务配置"""
        return cls(
            task_id=data.get("task_id", ""),
            name=data.get("name", "未命名任务"),
            description=data.get("description", ""),
            url=data.get("url", ""),
            timeout=data.get("timeout", DEFAULT_TASK_TIMEOUT_MS),
            variables=data.get("variables", {}),
            steps=[
                StepConfig.from_dict(s)
                for s in data.get("steps", [])
                if _is_valid_step(s)
            ],
            on_success=data.get("on_success", {}),
            on_failure=data.get("on_failure", {}),
            metadata=data.get("metadata", {}),
            reveal_hidden=data.get("reveal_hidden", False),
            step_delay=_safe_float(data.get("step_delay"), 0.5),
            navigation_wait=_safe_float(data.get("navigation_wait"), 1),
            success_checks=[
                JsCheck.from_dict(c)
                for c in data.get("success_checks", [])
                if isinstance(c, dict) and c.get("expr")
            ],
            failure_checks=[
                JsCheck.from_dict(c)
                for c in data.get("failure_checks", [])
                if isinstance(c, dict) and c.get("expr")
            ],
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
        if self.navigation_wait != 1:
            result["navigation_wait"] = self.navigation_wait
        if self.success_checks:
            result["success_checks"] = [c.to_dict() for c in self.success_checks]
        if self.failure_checks:
            result["failure_checks"] = [c.to_dict() for c in self.failure_checks]
        return result


@dataclass
class ScriptTaskInfo:
    """自定义脚本任务信息（不含 Playwright 步骤，直接通过子进程执行）"""

    task_id: str = ""
    name: str = "未命名脚本任务"
    description: str = ""
    script_path: Path = field(default_factory=Path)
    script_type: str = ""  # 脚本类型: py/bat/ps1/sh/exe
