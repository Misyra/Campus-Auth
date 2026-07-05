"""网络探测模块生命周期管理测试。

验证 shutdown_probes() 正确设置关闭标志，
以及探测函数在关闭后拒绝新任务。
"""

from __future__ import annotations

import threading


class TestShutdownProbesBehavior:
    """shutdown_probes 关闭行为验证。"""

    def test_shutdown_probes_sets_event(self, monkeypatch):
        """shutdown_probes 设置 _shutdown_event。"""
        import app.network.probes as probes_mod

        tmp_event = threading.Event()
        monkeypatch.setattr(probes_mod, "_shutdown_event", tmp_event)

        from app.network.probes import shutdown_probes

        shutdown_probes()

        assert tmp_event.is_set()


class TestShutdownEventGuards:
    """探测函数在 _shutdown_event 被 set 后拒绝执行。"""

    async def test_socket_probe_returns_false_after_shutdown(self, monkeypatch):
        """is_network_available_socket 在关闭后返回 False。"""
        import app.network.probes as probes_mod

        tmp_event = threading.Event()
        tmp_event.set()  # 模拟已关闭
        monkeypatch.setattr(probes_mod, "_shutdown_event", tmp_event)

        result = await probes_mod.is_network_available_socket(
            test_sites=[("127.0.0.1", 1)]
        )
        assert result is False

    async def test_url_probe_returns_false_after_shutdown(self, monkeypatch):
        """is_network_available_url 在关闭后返回 False。"""
        import app.network.probes as probes_mod

        tmp_event = threading.Event()
        tmp_event.set()
        monkeypatch.setattr(probes_mod, "_shutdown_event", tmp_event)

        result = await probes_mod.is_network_available_url(
            url_checks=[("http://test", "ok")]
        )
        assert result is False

    async def test_http_probe_returns_false_after_shutdown(self, monkeypatch):
        """is_network_available_http 在关闭后返回 False。"""
        import app.network.probes as probes_mod

        tmp_event = threading.Event()
        tmp_event.set()
        monkeypatch.setattr(probes_mod, "_shutdown_event", tmp_event)

        result = await probes_mod.is_network_available_http(test_urls=["http://test"])
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

    async def test_source_ip_passed_to_open_connection(self, monkeypatch):
        """source_ip 非空时应传递 local_addr 给 asyncio.open_connection。"""
        from app.network import probes as probes_mod

        captured: dict = {}

        async def fake_open_connection(host, port, **kwargs):
            captured["local_addr"] = kwargs.get("local_addr")
            raise OSError("mock")

        monkeypatch.setattr("asyncio.open_connection", fake_open_connection)
        await probes_mod.is_network_available_socket(
            test_sites=[("8.8.8.8", 53)], timeout=1, source_ip="192.168.1.5"
        )
        assert captured["local_addr"] == ("192.168.1.5", 0)

    async def test_no_source_ip_uses_none(self, monkeypatch):
        """source_ip 为空时 local_addr 应为 None。"""
        from app.network import probes as probes_mod

        captured: dict = {}

        async def fake_open_connection(host, port, **kwargs):
            captured["local_addr"] = kwargs.get("local_addr")
            raise OSError("mock")

        monkeypatch.setattr("asyncio.open_connection", fake_open_connection)
        await probes_mod.is_network_available_socket(
            test_sites=[("8.8.8.8", 53)], timeout=1
        )
        assert captured["local_addr"] is None


class TestPhysicalCheckFallback:
    """物理网络检查回退逻辑验证。"""

    def test_specific_interface_up(self, monkeypatch):
        """指定网卡 up 且连通时应返回 True。"""
        from app.network import probes as probes_mod

        fake_stats = {"Ethernet": type("S", (), {"isup": True, "speed": 1000})()}
        monkeypatch.setattr(
            "app.network.probes.psutil.net_if_stats", lambda: fake_stats
        )
        monkeypatch.setattr(
            probes_mod, "_check_interface_connectivity", lambda name: name == "Ethernet"
        )

        assert probes_mod.is_local_network_connected(interface_name="Ethernet") is True

    def test_specific_interface_down_fallback(self, monkeypatch):
        """指定网卡 down 时应返回 False（候选列表为空）。"""
        from app.network import probes as probes_mod

        fake_stats = {
            "Ethernet": type("S", (), {"isup": False, "speed": 0})(),
            "Wi-Fi": type("S", (), {"isup": True, "speed": 300})(),
        }
        monkeypatch.setattr(
            "app.network.probes.psutil.net_if_stats", lambda: fake_stats
        )
        monkeypatch.setattr(
            probes_mod, "_check_interface_connectivity", lambda name: name == "Wi-Fi"
        )

        # 指定网卡 down 时，候选列表只包含指定网卡（即使 down）
        assert probes_mod.is_local_network_connected(interface_name="Ethernet") is False

    def test_specific_interface_missing_fallback(self, monkeypatch):
        """指定网卡不存在时应返回 False（候选列表为空）。"""
        from app.network import probes as probes_mod

        fake_stats = {
            "Wi-Fi": type("S", (), {"isup": True, "speed": 300})(),
        }
        monkeypatch.setattr(
            "app.network.probes.psutil.net_if_stats", lambda: fake_stats
        )
        monkeypatch.setattr(
            probes_mod, "_check_interface_connectivity", lambda name: name == "Wi-Fi"
        )

        # 指定网卡不存在时，候选列表为空
        assert probes_mod.is_local_network_connected(interface_name="Ethernet") is False

    def test_no_interface_name_uses_candidate_filter(self, monkeypatch):
        """不指定网卡名时使用候选过滤 + TCP Connect。"""
        from app.network import probes as probes_mod

        fake_stats = {
            "Wi-Fi": type("S", (), {"isup": True, "speed": 300})(),
        }
        monkeypatch.setattr(
            "app.network.probes.psutil.net_if_stats", lambda: fake_stats
        )
        monkeypatch.setattr(
            probes_mod, "_check_interface_connectivity", lambda name: name == "Wi-Fi"
        )

        assert probes_mod.is_local_network_connected() is True


class TestNoExecutorRemnants:
    """确认 executor 和客户端池已被移除。"""

    def test_no_executor_attribute(self):
        """probes 模块不再有 executor 属性。"""
        import app.network.probes as probes_mod

        assert not hasattr(probes_mod, "executor")

    def test_no_probe_client_attribute(self):
        """probes 模块不再有 _probe_client 属性。"""
        import app.network.probes as probes_mod

        assert not hasattr(probes_mod, "_probe_client")

    def test_no_bound_clients_attribute(self):
        """probes 模块不再有 _bound_clients 属性。"""
        import app.network.probes as probes_mod

        assert not hasattr(probes_mod, "_bound_clients")
