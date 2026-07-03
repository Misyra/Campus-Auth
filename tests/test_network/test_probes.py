"""网络探测模块生命周期管理测试。

验证 shutdown_probes() 正确关闭 executor 和 HTTP 客户端，
以及探测函数在关闭后拒绝新任务。
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest


class TestShutdownProbesBehavior:
    """shutdown_probes 关闭行为验证。

    使用 monkeypatch 替换模块级 executor 和 _shutdown_event，
    避免影响其他测试。
    """

    def _make_replacement_executor(self):
        """创建用于测试的临时 executor。"""
        return ThreadPoolExecutor(
            max_workers=2, thread_name_prefix="test_probe_shutdown"
        )

    def test_shutdown_probes_sets_event(self, monkeypatch):
        """shutdown_probes 设置 _shutdown_event。"""
        import app.network.probes as probes_mod

        tmp_event = threading.Event()
        monkeypatch.setattr(probes_mod, "_shutdown_event", tmp_event)
        monkeypatch.setattr(probes_mod, "executor", self._make_replacement_executor())

        from app.network.probes import shutdown_probes

        shutdown_probes()

        assert tmp_event.is_set()

    def test_shutdown_probes_waits_for_inflight(self, monkeypatch):
        """shutdown_probes(wait=True) 等待 in-flight 任务完成。"""
        import app.network.probes as probes_mod

        monkeypatch.setattr(probes_mod, "_shutdown_event", threading.Event())
        tmp_executor = self._make_replacement_executor()
        monkeypatch.setattr(probes_mod, "executor", tmp_executor)

        completed = threading.Event()

        def slow_task():
            time.sleep(0.1)
            completed.set()

        tmp_executor.submit(slow_task)

        from app.network.probes import shutdown_probes

        shutdown_probes()

        assert completed.is_set()

    def test_shutdown_probes_rejects_new_work(self, monkeypatch):
        """shutdown_probes 后 executor 拒绝新任务。"""
        import app.network.probes as probes_mod

        monkeypatch.setattr(probes_mod, "_shutdown_event", threading.Event())
        tmp_executor = self._make_replacement_executor()
        monkeypatch.setattr(probes_mod, "executor", tmp_executor)

        from app.network.probes import shutdown_probes

        shutdown_probes()

        with pytest.raises(RuntimeError, match="cannot schedule new futures"):
            tmp_executor.submit(lambda: 42)

    def test_shutdown_probes_closes_probe_client(self, monkeypatch):
        """shutdown_probes 关闭 HTTP 探测客户端。"""
        import httpx

        import app.network.probes as probes_mod

        monkeypatch.setattr(probes_mod, "_shutdown_event", threading.Event())
        monkeypatch.setattr(probes_mod, "executor", self._make_replacement_executor())

        # 创建一个假的 probe client
        fake_client = httpx.Client()
        monkeypatch.setattr(probes_mod, "_probe_client", fake_client)

        from app.network.probes import shutdown_probes

        shutdown_probes()

        assert fake_client.is_closed


class TestShutdownEventGuards:
    """探测函数在 _shutdown_event 被 set 后拒绝执行。"""

    def test_socket_probe_returns_false_after_shutdown(self, monkeypatch):
        """is_network_available_socket 在关闭后返回 False。"""
        import app.network.probes as probes_mod

        tmp_event = threading.Event()
        tmp_event.set()  # 模拟已关闭
        monkeypatch.setattr(probes_mod, "_shutdown_event", tmp_event)

        result = probes_mod.is_network_available_socket(test_sites=[("127.0.0.1", 1)])
        assert result is False

    def test_url_probe_returns_false_after_shutdown(self, monkeypatch):
        """is_network_available_url 在关闭后返回 False。"""
        import app.network.probes as probes_mod

        tmp_event = threading.Event()
        tmp_event.set()
        monkeypatch.setattr(probes_mod, "_shutdown_event", tmp_event)

        result = probes_mod.is_network_available_url(url_checks=[("http://test", "ok")])
        assert result is False

    def test_http_probe_returns_false_after_shutdown(self, monkeypatch):
        """is_network_available_http 在关闭后返回 False。"""
        import app.network.probes as probes_mod

        tmp_event = threading.Event()
        tmp_event.set()
        monkeypatch.setattr(probes_mod, "_shutdown_event", tmp_event)

        result = probes_mod.is_network_available_http(test_urls=["http://test"])
        assert result is False


class TestAtexitRemoved:
    """确认 atexit 注册已被移除。"""

    def test_no_atexit_import(self):
        """probes.py 不再导入 atexit 模块。"""
        import importlib

        import app.network.probes as probes_mod

        source = importlib.util.find_spec(probes_mod.__name__).origin
        with open(source, encoding="utf-8") as f:
            lines = f.readlines()

        # atexit 不应再被导入（排除注释行）
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            assert "import atexit" not in stripped

    def test_atexit_register_commented_out(self):
        """atexit.register 调用应被注释掉。"""
        import importlib

        import app.network.probes as probes_mod

        source = importlib.util.find_spec(probes_mod.__name__).origin
        with open(source, encoding="utf-8") as f:
            lines = f.readlines()

        for line in lines:
            stripped = line.strip()
            # 跳过注释行
            if stripped.startswith("#"):
                continue
            assert "atexit.register" not in stripped
