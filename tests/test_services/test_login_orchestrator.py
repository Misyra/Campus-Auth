"""LoginOrchestrator 单元测试。"""

import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from app.schemas import RuntimeConfig
from app.services.login_orchestrator import (
    LoginHandle,
    LoginOrchestrator,
    resolve_worker_timeout,
    validate_login_config,
)


def _make_runtime_config(**overrides) -> RuntimeConfig:
    """创建测试用 RuntimeConfig，默认凭据完整。"""
    creds = {
        "username": overrides.get("username", "u"),
        "password": overrides.get("password", "p"),
        "auth_url": overrides.get("auth_url", "http://x"),
    }
    browser = {}
    if "login_timeout" in overrides:
        browser["login_timeout"] = overrides["login_timeout"]
    return RuntimeConfig(
        credentials=creds,
        browser=browser,
    )


VALID_CONFIG = _make_runtime_config()


# ── validate_login_config ──


class TestValidateLoginConfig:
    def test_valid_config_returns_none(self):
        assert validate_login_config(VALID_CONFIG) is None

    def test_missing_username(self):
        cfg = _make_runtime_config(username="")
        assert validate_login_config(cfg) is not None

    def test_missing_password(self):
        cfg = _make_runtime_config(password="")
        assert validate_login_config(cfg) is not None

    def test_missing_auth_url(self):
        cfg = _make_runtime_config(auth_url="")
        assert validate_login_config(cfg) is not None

    def test_default_config_fails(self):
        """默认 RuntimeConfig 无凭据，校验应失败。"""
        assert validate_login_config(RuntimeConfig()) is not None


# ── resolve_worker_timeout ──


class TestResolveWorkerTimeout:
    def test_uses_login_timeout(self):
        cfg = _make_runtime_config(login_timeout=120)
        assert resolve_worker_timeout(cfg) == 120

    def test_default_login_timeout(self):
        """默认 login_timeout=90，直接返回（不触发 fallback）。"""
        cfg = RuntimeConfig()
        assert resolve_worker_timeout(cfg) == 90

    def test_custom_fallback_only_when_invalid(self):
        """fallback 仅在 login_timeout 无法解析时使用。
        RuntimeConfig 保证 login_timeout 是 int，所以 fallback 实际不会触发。"""
        cfg = _make_runtime_config(login_timeout=120)
        assert resolve_worker_timeout(cfg, fallback=200) == 120

    def test_floor_60(self):
        cfg = _make_runtime_config(login_timeout=10)
        assert resolve_worker_timeout(cfg) == 60

    def test_ceiling_clamped_by_pydantic(self):
        """Pydantic 约束 le=600，超过 600 的值无法构造 RuntimeConfig。
        测试边界值 600。"""
        cfg = _make_runtime_config(login_timeout=600)
        assert resolve_worker_timeout(cfg) == 600


# ── LoginHandle ──


class TestLoginHandle:
    def test_rejected_handle_returns_reason(self):
        h = LoginHandle(
            future=None,
            source="auto",
            cancel_event=threading.Event(),
            rejected_reason="配置不完整",
        )
        assert h.result() == (False, "配置不完整")

    def test_no_future_returns_not_submitted(self):
        h = LoginHandle(
            future=None,
            source="auto",
            cancel_event=threading.Event(),
        )
        assert h.result() == (False, "登录未提交")

    def test_cancel_sets_event(self):
        evt = threading.Event()
        h = LoginHandle(future=None, source="auto", cancel_event=evt)
        assert not evt.is_set()
        h.cancel()
        assert evt.is_set()

    def test_done_true_when_no_future(self):
        h = LoginHandle(
            future=None,
            source="auto",
            cancel_event=threading.Event(),
        )
        assert h.done() is True

    def test_done_delegates_to_future(self):
        f = MagicMock()
        f.done.return_value = False
        h = LoginHandle(future=f, source="auto", cancel_event=threading.Event())
        assert h.done() is False
        f.done.return_value = True
        assert h.done() is True


# ── Fixtures ──


def _make_mock_worker():
    """创建立即返回成功的 mock worker。"""
    worker = MagicMock()
    result = MagicMock()
    result.success = True
    result.data = "登录成功"
    result.error = None
    worker.submit.return_value = result
    return worker


def _make_slow_worker(delay: float = 0.1):
    """创建延迟返回的 mock worker，避免 done_callback 死锁。"""
    worker = MagicMock()
    result = MagicMock()
    result.success = True
    result.data = "登录成功"
    result.error = None

    def slow_submit(*args, **kwargs):
        time.sleep(delay)
        return result

    worker.submit.side_effect = slow_submit
    return worker


@pytest.fixture
def orchestrator():
    """创建使用慢速 worker 的编排器，避免 done_callback 死锁。"""
    worker = _make_slow_worker()
    return LoginOrchestrator(
        worker_getter=lambda: worker,
        login_history=MagicMock(),
        profile_service=MagicMock(),
    )


# ── submit ──


class TestOrchestratorSubmit:
    def test_submit_returns_handle_with_future(self, orchestrator):
        handle = orchestrator.submit(source="auto", config=VALID_CONFIG)
        assert handle.future is not None
        assert handle.rejected_reason is None
        # 等待完成以避免线程泄漏
        handle.result(timeout=5)

    def test_submit_rejected_on_bad_config(self, orchestrator):
        handle = orchestrator.submit(source="auto", config=RuntimeConfig())
        assert handle.future is None
        assert handle.rejected_reason is not None

    def test_login_once_always_creates_new_handle(self, orchestrator):
        h1 = orchestrator.submit(source="login_once", config=VALID_CONFIG)
        h1.result(timeout=5)
        h2 = orchestrator.submit(source="login_once", config=VALID_CONFIG)
        assert h2 is not h1
        h2.result(timeout=5)

    def test_manual_preempts_auto(self, orchestrator):
        auto = orchestrator.submit(source="auto", config=VALID_CONFIG)
        manual = orchestrator.submit(source="manual", config=VALID_CONFIG)
        assert manual is not auto
        assert auto.cancel_event.is_set()
        manual.result(timeout=5)
        auto.result(timeout=5)

    def test_auto_deduplicates(self, orchestrator):
        h1 = orchestrator.submit(source="auto", config=VALID_CONFIG)
        h2 = orchestrator.submit(source="auto", config=VALID_CONFIG)
        assert h1 is h2
        h1.result(timeout=5)

    def test_submit_uses_runtime_config(self):
        worker = _make_slow_worker()
        orch = LoginOrchestrator(
            worker_getter=lambda: worker,
            get_runtime_config=lambda: VALID_CONFIG,
        )
        handle = orch.submit(source="auto")
        assert handle.future is not None
        handle.result(timeout=5)

    def test_manual_does_not_dedup_with_manual(self, orchestrator):
        """manual 遇到已有的 manual 时走复用分支（非 auto 不抢占）。"""
        h1 = orchestrator.submit(source="manual", config=VALID_CONFIG)
        h2 = orchestrator.submit(source="manual", config=VALID_CONFIG)
        assert h1 is h2
        h1.result(timeout=5)

    def test_submit_passes_cancel_event(self, orchestrator):
        """外部传入的 cancel_event 被包装为 CompositeCancelEvent，原事件作为源。"""
        evt = threading.Event()
        handle = orchestrator.submit(
            source="auto", config=VALID_CONFIG, cancel_event=evt
        )
        # 原事件被包装，不是同一个对象，但设置原事件会传播
        assert handle.cancel_event is not evt
        assert not handle.cancel_event.is_set()
        evt.set()
        assert handle.cancel_event.is_set()
        handle.result(timeout=5)


# ── is_running ──


class TestOrchestratorIsRunning:
    def test_false_initially(self, orchestrator):
        assert orchestrator.is_running() is False

    def test_true_while_running(self, orchestrator):
        orchestrator.submit(source="auto", config=VALID_CONFIG)
        # 慢速 worker (0.1s) 应使 is_running 为 True
        assert orchestrator.is_running() is True

    def test_false_after_completion(self, orchestrator):
        handle = orchestrator.submit(source="auto", config=VALID_CONFIG)
        handle.result(timeout=5)
        # 等待 done_callback 清理 slot
        time.sleep(0.05)
        assert orchestrator.is_running() is False


# ── cancel_running ──


class TestOrchestratorCancel:
    def test_cancel_running_sets_event(self, orchestrator):
        handle = orchestrator.submit(source="auto", config=VALID_CONFIG)
        orchestrator.cancel_running()
        assert handle.cancel_event.is_set()
        handle.result(timeout=5)

    def test_cancel_running_no_op_when_idle(self, orchestrator):
        orchestrator.cancel_running()


# ── validate ──


class TestOrchestratorValidate:
    def test_validate_passes_valid_config(self, orchestrator):
        assert orchestrator.validate(VALID_CONFIG) is None

    def test_validate_fails_bad_config(self, orchestrator):
        assert orchestrator.validate(RuntimeConfig()) is not None

    def test_validate_uses_runtime_config(self):
        worker = _make_slow_worker()
        orch = LoginOrchestrator(
            worker_getter=lambda: worker,
            get_runtime_config=lambda: VALID_CONFIG,
        )
        assert orch.validate() is None


# ── shutdown ──


class TestOrchestratorShutdown:
    def test_shutdown(self, orchestrator):
        orchestrator.shutdown(wait=False)


# ── _dispatch cancel_event 源清理 ──


class TestDispatchClearsCancelSources:
    """_dispatch 的 _on_done 回调应清理 CompositeCancelEvent 源列表。"""

    def test_on_done_clears_composite_cancel_sources(self):
        """登录完成后，cancel_event 的源列表应被清空。"""
        from app.utils.cancel_token import CompositeCancelEvent

        worker = _make_mock_worker()
        orch = LoginOrchestrator(
            worker_getter=lambda: worker,
            login_history=MagicMock(),
            profile_service=MagicMock(),
        )

        cancel_event = CompositeCancelEvent()
        src1 = threading.Event()
        src2 = threading.Event()
        cancel_event.add_source(src1)
        cancel_event.add_source(src2)
        assert len(cancel_event._sources) == 2

        # 通过 _dispatch 提交，触发 _on_done 回调
        handle = orch._dispatch(VALID_CONFIG, "auto", cancel_event)
        assert handle.future is not None

        # 等待 future 完成 + done_callback 执行
        handle.result(timeout=5)
        time.sleep(0.1)

        # 源列表应被清空
        assert len(cancel_event._sources) == 0
