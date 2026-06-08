"""调试会话模型测试 — 覆盖 DebugSession 数据类、工厂函数和序列化器。"""

from __future__ import annotations

from collections import deque

from app.services.debug_session import (
    DebugSession,
    empty_debug_session,
    debug_to_response,
    _next_debug_gen,
)


# ── empty_debug_session ──


class TestEmptyDebugSession:
    """empty_debug_session 工厂函数。"""

    def test_returns_debug_session_instance(self):
        """返回 DebugSession 实例。"""
        session = empty_debug_session()
        assert isinstance(session, DebugSession)

    def test_default_values(self):
        """默认值正确。"""
        session = empty_debug_session()
        assert session._browser_active is False
        assert session.task_id is None
        assert session.executor is None
        assert session.current_step == 0
        assert session.steps == []
        assert isinstance(session.results, deque)
        assert len(session.results) == 0
        assert session.screenshot_url is None
        assert session.running is False
        assert session._last_activity == 0.0
        assert session._timer_task is None

    def test_results_maxlen(self):
        """results deque 的 maxlen 为 1000。"""
        session = empty_debug_session()
        assert session.results.maxlen == 1000


# ── debug_to_response ──


class TestDebugToResponse:
    """debug_to_response 序列化器。"""

    def test_basic_serialization(self):
        """基本序列化输出。"""
        session = empty_debug_session()
        result = debug_to_response(session)
        assert result["running"] is False
        assert result["task_id"] is None
        assert result["current_step"] == 0
        assert result["total_steps"] == 0
        assert result["steps"] == []
        assert result["results"] == []
        assert result["screenshot_url"] is None

    def test_with_data(self):
        """有数据时正确序列化。"""
        session = DebugSession(
            _browser_active=True,
            task_id="login",
            current_step=2,
            steps=[{"id": "s1"}, {"id": "s2"}, {"id": "s3"}],
            results=deque([{"step": 1, "ok": True}, {"step": 2, "ok": False}]),
            screenshot_url="/screenshots/1.png",
            running=True,
        )
        result = debug_to_response(session)
        assert result["running"] is True
        assert result["task_id"] == "login"
        assert result["current_step"] == 2
        assert result["total_steps"] == 3
        assert len(result["steps"]) == 3
        assert len(result["results"]) == 2
        assert result["screenshot_url"] == "/screenshots/1.png"

    def test_strips_internal_fields(self):
        """内部字段被剥离。"""
        session = empty_debug_session()
        session.executor = object()
        session._last_activity = 999.0
        session._timer_task = object()
        result = debug_to_response(session)
        assert "executor" not in result
        assert "_last_activity" not in result
        assert "_timer_task" not in result
        assert "_browser_active" not in result

    def test_results_converted_to_list(self):
        """results 从 deque 转换为 list。"""
        session = empty_debug_session()
        session.results.append({"ok": True})
        result = debug_to_response(session)
        assert isinstance(result["results"], list)
        assert result["results"] == [{"ok": True}]


# ── _next_debug_gen ──


class TestNextDebugGen:
    """_next_debug_gen 代数计数器。"""

    def test_increments_monotonically(self):
        """代数单调递增。"""
        gen1 = _next_debug_gen()
        gen2 = _next_debug_gen()
        gen3 = _next_debug_gen()
        assert gen2 == gen1 + 1
        assert gen3 == gen2 + 1

    def test_returns_positive_integer(self):
        """返回正整数。"""
        gen = _next_debug_gen()
        assert isinstance(gen, int)
        assert gen > 0


# ── DebugSession 数据类 ──


class TestDebugSession:
    """DebugSession 数据类属性。"""

    def test_modifiable_fields(self):
        """字段可修改。"""
        session = empty_debug_session()
        session.running = True
        session.task_id = "test"
        session.current_step = 5
        session.screenshot_url = "/test.png"
        assert session.running is True
        assert session.task_id == "test"
        assert session.current_step == 5
        assert session.screenshot_url == "/test.png"

    def test_results_append(self):
        """results 支持 append。"""
        session = empty_debug_session()
        session.results.append({"step": 1})
        session.results.append({"step": 2})
        assert len(session.results) == 2

    def test_results_maxlen_overflow(self):
        """results 超出 maxlen 时自动丢弃旧数据。"""
        session = empty_debug_session()
        for i in range(1100):
            session.results.append({"i": i})
        assert len(session.results) == 1000
        # 最早的 100 条被丢弃
        assert session.results[0]["i"] == 100
