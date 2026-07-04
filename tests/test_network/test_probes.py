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


class TestTcpProbeSourceIp:
    """TCP 探测 source_ip 参数传递验证。"""

    def test_source_ip_passed_to_socket(self, monkeypatch):
        """source_ip 非空时应传递给 socket.create_connection。"""
        from app.network import probes as probes_mod

        captured: dict = {}

        def fake_create_connection(
            address, timeout=None, source_address=None
        ):
            captured["source_address"] = source_address
            raise OSError("mock")

        monkeypatch.setattr(
            "app.network.probes.socket.create_connection", fake_create_connection
        )
        probes_mod.is_network_available_socket(
            test_sites=[("8.8.8.8", 53)], timeout=1, source_ip="192.168.1.5"
        )
        assert captured["source_address"] == ("192.168.1.5", 0)

    def test_no_source_ip_uses_none(self, monkeypatch):
        """source_ip 为空时 source_address 应为 None。"""
        from app.network import probes as probes_mod

        captured: dict = {}

        def fake_create_connection(
            address, timeout=None, source_address=None
        ):
            captured["source_address"] = source_address
            raise OSError("mock")

        monkeypatch.setattr(
            "app.network.probes.socket.create_connection", fake_create_connection
        )
        probes_mod.is_network_available_socket(
            test_sites=[("8.8.8.8", 53)], timeout=1
        )
        assert captured["source_address"] is None


class TestPhysicalCheckFallback:
    """物理网络检查回退逻辑验证。"""

    def test_specific_interface_up(self, monkeypatch):
        """指定网卡 up 且连通时应返回 True。"""
        from app.network import probes as probes_mod

        fake_stats = {"Ethernet": type("S", (), {"isup": True, "speed": 1000})()}
        monkeypatch.setattr("app.network.probes.psutil.net_if_stats", lambda: fake_stats)
        monkeypatch.setattr(probes_mod, "_check_interface_connectivity", lambda name: name == "Ethernet")

        assert probes_mod.is_local_network_connected(interface_name="Ethernet") is True

    def test_specific_interface_down_fallback(self, monkeypatch):
        """指定网卡 down 时应返回 False（候选列表为空）。"""
        from app.network import probes as probes_mod

        fake_stats = {
            "Ethernet": type("S", (), {"isup": False, "speed": 0})(),
            "Wi-Fi": type("S", (), {"isup": True, "speed": 300})(),
        }
        monkeypatch.setattr("app.network.probes.psutil.net_if_stats", lambda: fake_stats)
        monkeypatch.setattr(probes_mod, "_check_interface_connectivity", lambda name: name == "Wi-Fi")

        # 指定网卡 down 时，候选列表只包含指定网卡（即使 down）
        assert probes_mod.is_local_network_connected(interface_name="Ethernet") is False

    def test_specific_interface_missing_fallback(self, monkeypatch):
        """指定网卡不存在时应返回 False（候选列表为空）。"""
        from app.network import probes as probes_mod

        fake_stats = {
            "Wi-Fi": type("S", (), {"isup": True, "speed": 300})(),
        }
        monkeypatch.setattr("app.network.probes.psutil.net_if_stats", lambda: fake_stats)
        monkeypatch.setattr(probes_mod, "_check_interface_connectivity", lambda name: name == "Wi-Fi")

        # 指定网卡不存在时，候选列表为空
        assert probes_mod.is_local_network_connected(interface_name="Ethernet") is False

    def test_no_interface_name_uses_candidate_filter(self, monkeypatch):
        """不指定网卡名时使用候选过滤 + TCP Connect。"""
        from app.network import probes as probes_mod

        fake_stats = {
            "Wi-Fi": type("S", (), {"isup": True, "speed": 300})(),
        }
        monkeypatch.setattr("app.network.probes.psutil.net_if_stats", lambda: fake_stats)
        monkeypatch.setattr(probes_mod, "_check_interface_connectivity", lambda name: name == "Wi-Fi")

        assert probes_mod.is_local_network_connected() is True


class TestBoundClientPool:
    """绑定源 IP 的 httpx Client 池验证。"""

    def _cleanup(self):
        """测试后清理绑定客户端池。"""
        from app.network import probes as probes_mod

        probes_mod._close_all_bound_clients()

    def test_get_bound_client_creates_and_caches(self):
        """首次调用创建 Client，再次调用复用。"""
        from app.network import probes as probes_mod

        self._cleanup()
        try:
            c1 = probes_mod._get_bound_client("10.0.0.1", block_proxy=True)
            c2 = probes_mod._get_bound_client("10.0.0.1", block_proxy=True)
            assert c1 is c2
            assert not c1.is_closed
        finally:
            self._cleanup()

    def test_bound_client_pool_evicts_oldest(self):
        """超过上限时关闭最旧的 Client。"""
        from app.network import probes as probes_mod

        self._cleanup()
        try:
            clients = []
            for i in range(probes_mod._MAX_BOUND_CLIENTS):
                c = probes_mod._get_bound_client(f"10.0.0.{i}", block_proxy=True)
                clients.append(c)

            # 再创建一个，应淘汰最旧的
            new_c = probes_mod._get_bound_client(
                f"10.0.0.{probes_mod._MAX_BOUND_CLIENTS}", block_proxy=True
            )
            assert clients[0].is_closed
            assert not new_c.is_closed
            assert len(probes_mod._bound_clients) == probes_mod._MAX_BOUND_CLIENTS
        finally:
            self._cleanup()

    def test_close_bound_client(self):
        """close_bound_client 关闭指定 IP 的 Client。"""
        from app.network import probes as probes_mod

        self._cleanup()
        try:
            c = probes_mod._get_bound_client("10.0.0.99", block_proxy=True)
            assert not c.is_closed
            probes_mod.close_bound_client("10.0.0.99")
            assert c.is_closed
            assert "10.0.0.99" not in probes_mod._bound_clients
        finally:
            self._cleanup()

    def test_close_all_bound_clients(self):
        """_close_all_bound_clients 清空池。"""
        from app.network import probes as probes_mod

        self._cleanup()
        try:
            probes_mod._get_bound_client("10.0.0.1", block_proxy=True)
            probes_mod._get_bound_client("10.0.0.2", block_proxy=True)
            probes_mod._close_all_bound_clients()
            assert len(probes_mod._bound_clients) == 0
        finally:
            self._cleanup()

    def test_shutdown_probes_closes_bound_clients(self, monkeypatch):
        """shutdown_probes 应关闭所有绑定 Client。"""
        import app.network.probes as probes_mod

        monkeypatch.setattr(probes_mod, "_shutdown_event", threading.Event())
        tmp_executor = ThreadPoolExecutor(
            max_workers=2, thread_name_prefix="test_bound_shutdown"
        )
        monkeypatch.setattr(probes_mod, "executor", tmp_executor)

        c = probes_mod._get_bound_client("10.0.0.1", block_proxy=True)
        probes_mod.shutdown_probes()
        assert c.is_closed
