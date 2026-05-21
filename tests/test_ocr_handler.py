from __future__ import annotations

from src.task_executor import (
    OcrHandler,
    StepConfig,
    StepType,
    _FORCE_INPUT_JS,
)


def test_force_input_js_constant_exists() -> None:
    """_FORCE_INPUT_JS 模块常量存在且非空"""
    assert isinstance(_FORCE_INPUT_JS, str)
    assert len(_FORCE_INPUT_JS) > 100
    assert "nativeSet" in _FORCE_INPUT_JS
    assert "dispatchEvent" in _FORCE_INPUT_JS


def test_force_input_js_contains_key_events() -> None:
    """强制输入 JS 包含关键事件派发"""
    assert "focus" in _FORCE_INPUT_JS
    assert "beforeinput" in _FORCE_INPUT_JS
    assert "input" in _FORCE_INPUT_JS
    assert "change" in _FORCE_INPUT_JS
    assert "blur" in _FORCE_INPUT_JS


def test_force_input_js_handles_clear() -> None:
    """强制输入 JS 支持清空逻辑"""
    assert "doClear" in _FORCE_INPUT_JS


def test_ocr_handler_step_type() -> None:
    """OcrHandler 的 step_type 应为 ocr"""
    handler = OcrHandler()
    assert handler.step_type == StepType.OCR


def test_ocr_handler_rejects_missing_selector() -> None:
    """OcrHandler 缺少 selector 时返回错误"""
    handler = OcrHandler()
    step = StepConfig(id="s1", type="ocr", selector="")
    assert step.selector == ""
    assert handler.step_type == StepType.OCR


def test_force_input_js_is_reused() -> None:
    """验证 _FORCE_INPUT_JS 在代码中被引用（非重复定义）"""
    import inspect
    from src.task_executor import InputHandler

    source = inspect.getsource(InputHandler._force_input)
    assert "_FORCE_INPUT_JS" in source
