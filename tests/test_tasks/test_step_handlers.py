"""StepHandler 单元测试。"""

from __future__ import annotations

import time
from unittest.mock import MagicMock

from app.tasks.models import StepConfig, TaskConfig
from app.tasks.step_handlers import WaitUrlHandler
from app.tasks.variable_resolver import VariableResolver


def _make_resolver() -> VariableResolver:
    """创建 VariableResolver 实例。"""
    config = TaskConfig(task_id="test", url="http://example.com")
    return VariableResolver(config, {})


def _make_step(pattern: str = ".*", timeout: int = 5000) -> StepConfig:
    """创建 WaitUrlHandler 步骤配置。"""
    return StepConfig(id="wait1", type="wait_url", pattern=pattern, timeout=timeout)


# ── WaitUrlHandler 时间源 ──


class TestWaitUrlHandlerTimeSource:
    """WaitUrlHandler 使用 monotonic 时间源。"""

    def test_uses_time_monotonic(self):
        """源码中使用 time.monotonic 而非 asyncio.get_running_loop().time()。"""
        import inspect

        source = inspect.getsource(WaitUrlHandler.execute)
        assert "time.monotonic()" in source
        assert "get_running_loop().time()" not in source

    async def test_matches_url_immediately(self):
        """URL 立即匹配时返回成功。"""
        handler = WaitUrlHandler()
        step = _make_step(pattern=r"example\.com")
        resolver = _make_resolver()

        page = MagicMock()
        page.url = "http://example.com/login"

        success, msg = await handler.execute(page, step, resolver)
        assert success is True

    async def test_timeout_returns_failure(self):
        """超时后返回失败。"""
        handler = WaitUrlHandler()
        step = _make_step(pattern=r"nonexistent\.com", timeout=300)
        resolver = _make_resolver()

        page = MagicMock()
        page.url = "http://example.com/login"

        start = time.monotonic()
        success, msg = await handler.execute(page, step, resolver)
        elapsed = time.monotonic() - start

        assert success is False
        assert "超时" in msg
        # 应在约 300ms 内超时（允许少量误差）
        assert elapsed < 1.0

    async def test_empty_pattern_returns_error(self):
        """空 pattern 返回错误。"""
        handler = WaitUrlHandler()
        step = _make_step(pattern="")
        resolver = _make_resolver()

        page = MagicMock()
        success, msg = await handler.execute(page, step, resolver)
        assert success is False
        assert "pattern" in msg

    async def test_invalid_regex_returns_error(self):
        """无效正则表达式返回错误。"""
        handler = WaitUrlHandler()
        step = _make_step(pattern="[invalid")
        resolver = _make_resolver()

        page = MagicMock()
        success, msg = await handler.execute(page, step, resolver)
        assert success is False
        assert "正则" in msg or "pattern" in msg

    async def test_url_changes_to_match(self):
        """URL 变化后匹配成功。"""
        handler = WaitUrlHandler()
        step = _make_step(pattern=r"success", timeout=2000)
        resolver = _make_resolver()

        page = MagicMock()
        # 前两次返回不匹配的 URL，第三次返回匹配的 URL
        page.url = "http://example.com/pending"
        call_count = 0

        original_url = page.url

        async def side_effect():
            nonlocal call_count
            call_count += 1
            if call_count >= 3:
                page.url = "http://example.com/success"

        # 使用属性模拟
        class MockPage:
            def __init__(self):
                self._url = "http://example.com/pending"
                self._call_count = 0

            @property
            def url(self):
                self._call_count += 1
                if self._call_count >= 5:
                    self._url = "http://example.com/success"
                return self._url

        mock_page = MockPage()
        success, msg = await handler.execute(mock_page, step, resolver)
        assert success is True
