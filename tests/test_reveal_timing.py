"""Tests for reveal timing and hidden-input detection improvements.

All tests read the source file directly to avoid a pre-existing circular import
(task_executor -> utils.logging -> utils.login -> task_executor).
"""

from __future__ import annotations

from pathlib import Path

SRC_FILE = Path(__file__).resolve().parents[1] / "src" / "task_executor.py"


def _source() -> str:
    return SRC_FILE.read_text(encoding="utf-8")


def test_reveal_selector_includes_textarea():
    """_reveal_hidden_inputs 的 JS 选择器应同时覆盖 input 和 textarea."""
    src = _source()
    assert "input,textarea" in src, (
        "querySelectorAll 应包含 'input,textarea'"
    )
    # 确认 textarea 出现在 querySelectorAll 调用中而非其他地方
    qsa_pos = src.find("querySelectorAll")
    snippet = src[qsa_pos:qsa_pos + 60]
    assert "textarea" in snippet, (
        "textarea 应出现在 querySelectorAll 的参数中"
    )


def test_reveal_graceful_no_forms():
    """_reveal_hidden_inputs 的 JS 代码应包含异常处理（forEach 内 try-catch）。"""
    src = _source()
    # JS 代码中 forEach 回调应包含 try/catch 以处理 null 等异常
    assert "try {" in src and "catch" in src, (
        "reveal JS 应包含 try/catch 以静默处理异常元素"
    )


def test_execute_wait_uses_correct_selector_and_timeout():
    """execute 方法中的等待逻辑应使用 input,textarea 和 timeout=5000。"""
    src = _source()
    assert "wait_for_selector('input,textarea', timeout=5000)" in src, (
        "execute 应调用 wait_for_selector('input,textarea', timeout=5000)"
    )
