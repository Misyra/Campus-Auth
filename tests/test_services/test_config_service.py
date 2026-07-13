"""ConfigService 测试 — 运行时配置持有与更新。"""

from __future__ import annotations

import threading
from unittest.mock import MagicMock

import pytest

from app.schemas import (
    BrowserSettings,
    GlobalConfig,
    ProfilesData,
    RuntimeConfig,
)
from app.services.config_service import ConfigService


def _make_profile_service(
    *,
    pure_mode: bool = False,
    runtime_config: RuntimeConfig | None = None,
) -> MagicMock:
    """创建 mock ProfileService。

    Args:
        pure_mode: data.global_config.browser.pure_mode 的值
        runtime_config: build_runtime_config 返回值；默认与 pure_mode 一致
    """
    ps = MagicMock()
    data = ProfilesData(
        global_config=GlobalConfig(browser=BrowserSettings(pure_mode=pure_mode)),
    )
    ps.load.return_value = data
    if runtime_config is None:
        runtime_config = RuntimeConfig(browser=BrowserSettings(pure_mode=pure_mode))
    ps.build_runtime_config.return_value = runtime_config
    return ps


# ── 初始化 ──


class TestConfigServiceInitialization:
    """初始化测试。"""

    def test_init_loads_config_from_profile_service(self):
        ps = _make_profile_service()
        ConfigService(ps)
        ps.load.assert_called_once()
        ps.build_runtime_config.assert_called_once_with(ps.load.return_value)

    def test_init_default_pure_mode_from_global_config(self):
        ps = _make_profile_service(pure_mode=True)
        svc = ConfigService(ps)
        assert svc.pure_mode is True

    def test_init_load_failure_returns_default_config(self):
        ps = MagicMock()
        ps.load.side_effect = RuntimeError("disk error")
        svc = ConfigService(ps)
        # 加载失败时使用 RuntimeConfig() 默认值，pure_mode=False
        assert svc.get_runtime_config() == RuntimeConfig()
        assert svc.pure_mode is False


# ── 获取配置 ──


class TestGetRuntimeConfig:
    """获取配置测试。"""

    def test_get_runtime_config_returns_frozen_reference(self):
        ps = _make_profile_service()
        svc = ConfigService(ps)
        c1 = svc.get_runtime_config()
        c2 = svc.get_runtime_config()
        # 多次调用返回同一引用（除非 reload）
        assert c1 is c2

    def test_get_runtime_config_thread_safe(self):
        ps = _make_profile_service()
        svc = ConfigService(ps)
        results: list[RuntimeConfig] = []
        barrier = threading.Barrier(10)

        def worker():
            barrier.wait()
            for _ in range(50):
                results.append(svc.get_runtime_config())

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        # 并发调用不抛异常，且返回同一引用
        assert len(results) == 500
        assert all(r is results[0] for r in results)


# ── 纯净模式 ──


class TestPureMode:
    """纯净模式测试。"""

    def test_pure_mode_property_reads_under_lock(self):
        ps = _make_profile_service(pure_mode=True)
        svc = ConfigService(ps)
        results: list[bool] = []
        barrier = threading.Barrier(10)

        def worker():
            barrier.wait()
            for _ in range(50):
                results.append(svc.pure_mode)

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert all(r is True for r in results)

    def test_toggle_pure_mode_flips_value(self):
        ps = _make_profile_service(pure_mode=False)
        svc = ConfigService(ps)
        new_value = svc.toggle_pure_mode()
        assert new_value is True
        assert svc.pure_mode is True

        new_value2 = svc.toggle_pure_mode()
        assert new_value2 is False
        assert svc.pure_mode is False

    def test_toggle_pure_mode_persists_to_profile_service(self):
        ps = _make_profile_service(pure_mode=False)
        svc = ConfigService(ps)
        svc.toggle_pure_mode()
        ps.update.assert_called_once()

    def test_toggle_pure_mode_updates_runtime_config(self):
        ps = _make_profile_service(pure_mode=False)
        svc = ConfigService(ps)
        assert svc.get_runtime_config().browser.pure_mode is False
        svc.toggle_pure_mode()
        assert svc.get_runtime_config().browser.pure_mode is True


# ── 日志级别 ──


class TestUpdateLogLevel:
    """日志级别测试。"""

    def test_update_log_level_valid_level(self):
        ps = _make_profile_service()
        svc = ConfigService(ps)
        svc.update_log_level("DEBUG")
        assert svc.get_runtime_config().logging.level == "DEBUG"

    def test_update_log_level_invalid_raises_value_error(self):
        ps = _make_profile_service()
        svc = ConfigService(ps)
        with pytest.raises(ValueError):
            svc.update_log_level("INVALID")

    def test_update_log_level_atomic_swap(self):
        ps = _make_profile_service()
        svc = ConfigService(ps)
        old_browser = svc.get_runtime_config().browser
        svc.update_log_level("ERROR")
        new_config = svc.get_runtime_config()
        # 日志级别已更新
        assert new_config.logging.level == "ERROR"
        # 其他字段保持同一引用（model_copy 浅拷贝未涉及的字段）
        assert new_config.browser is old_browser


# ── 重载 ──


class TestReload:
    """重载配置测试。"""

    def test_reload_success(self):
        ps = _make_profile_service()
        svc = ConfigService(ps)
        new_rc = RuntimeConfig(browser=BrowserSettings(timeout=30))
        ps.build_runtime_config.return_value = new_rc
        ok = svc.reload()
        assert ok is True
        assert svc.get_runtime_config() is new_rc

    def test_reload_failure_returns_false(self):
        ps = _make_profile_service()
        svc = ConfigService(ps)
        old_config = svc.get_runtime_config()
        ps.load.side_effect = RuntimeError("disk error")
        ok = svc.reload()
        assert ok is False
        # 旧配置保持不变（同一引用）
        assert svc.get_runtime_config() is old_config

    def test_reload_syncs_pure_mode(self):
        ps = _make_profile_service(pure_mode=False)
        svc = ConfigService(ps)
        assert svc.pure_mode is False
        # 修改磁盘配置：pure_mode=True
        new_data = ProfilesData(
            global_config=GlobalConfig(browser=BrowserSettings(pure_mode=True)),
        )
        ps.load.return_value = new_data
        ok = svc.reload()
        assert ok is True
        assert svc.pure_mode is True


# ── 线程安全 ──


class TestThreadSafety:
    """线程安全测试。"""

    def test_concurrent_reload_and_get(self):
        ps = _make_profile_service()
        svc = ConfigService(ps)
        errors: list[Exception] = []
        barrier = threading.Barrier(6)

        def reader():
            barrier.wait()
            try:
                for _ in range(50):
                    svc.get_runtime_config()
            except Exception as e:
                errors.append(e)

        def reloader():
            barrier.wait()
            try:
                for _ in range(20):
                    svc.reload()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=reader) for _ in range(4)]
        threads += [threading.Thread(target=reloader) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert not errors

    def test_swap_runtime_config_atomic(self):
        ps = _make_profile_service()
        svc = ConfigService(ps)
        new_config = RuntimeConfig(browser=BrowserSettings(headless=False))
        # _swap 在锁保护下原子替换
        svc._swap(new_config, pure_mode=True)
        assert svc.get_runtime_config() is new_config
        assert svc.pure_mode is True
