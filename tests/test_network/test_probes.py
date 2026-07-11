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


class TestTcpProbeInterfaceBind:
    """TCP 探测 interface_name 参数传递验证。"""

    async def test_no_interface_uses_default_route(self, monkeypatch):
        """interface_name 为空时走 asyncio.open_connection（默认路由）。"""
        from app.network import probes as probes_mod

        captured: dict = {}

        async def fake_open_connection(host, port, **kwargs):
            captured["called"] = True
            raise OSError("mock")

        monkeypatch.setattr("asyncio.open_connection", fake_open_connection)
        await probes_mod.is_network_available_socket(
            test_sites=[("8.8.8.8", 53)], timeout=1
        )
        assert captured.get("called") is True

    async def test_interface_name_triggers_socket_bind(self, monkeypatch):
        """interface_name 非空时应走手动 socket + 绑接口路径。"""
        from app.network import probes as probes_mod

        # 绑接口路径不调用 asyncio.open_connection，而是 loop.sock_connect
        sock_connect_called: dict = {}

        class FakeLoop:
            def sock_connect(self, sock, addr):
                sock_connect_called["called"] = True
                raise OSError("mock")

        async def fake_get_event_loop():
            return FakeLoop()

        monkeypatch.setattr(
            "asyncio.get_running_loop", lambda: FakeLoop()
        )
        # bind_socket_to_interface 需要 mock，否则 Windows 上会真绑
        monkeypatch.setattr(
            "app.network.probes.bind_socket_to_interface",
            lambda sock, name, ip=None: "interface_index",
        )
        await probes_mod.is_network_available_socket(
            test_sites=[("8.8.8.8", 53)],
            timeout=1,
            interface_name="Ethernet",
            fallback_source_ip="192.168.1.5",
        )
        assert sock_connect_called.get("called") is True


class TestPhysicalCheckFallback:
    """物理网络检查回退逻辑验证。"""

    async def test_specific_interface_up(self, monkeypatch):
        """指定网卡 up 且连通时应返回 True。"""
        from app.network import probes as probes_mod

        fake_stats = {"Ethernet": type("S", (), {"isup": True, "speed": 1000})()}
        monkeypatch.setattr(
            "app.network.probes.psutil.net_if_stats", lambda: fake_stats
        )

        async def _fake_connectivity(name: str) -> bool:
            return name == "Ethernet"

        monkeypatch.setattr(probes_mod, "_check_interface_connectivity", _fake_connectivity)

        assert await probes_mod.is_local_network_connected(interface_name="Ethernet") is True

    async def test_specific_interface_down_fallback(self, monkeypatch):
        """指定网卡 down 时应返回 False（候选列表为空）。"""
        from app.network import probes as probes_mod

        fake_stats = {
            "Ethernet": type("S", (), {"isup": False, "speed": 0})(),
            "Wi-Fi": type("S", (), {"isup": True, "speed": 300})(),
        }
        monkeypatch.setattr(
            "app.network.probes.psutil.net_if_stats", lambda: fake_stats
        )

        async def _fake_connectivity(name: str) -> bool:
            return name == "Wi-Fi"

        monkeypatch.setattr(probes_mod, "_check_interface_connectivity", _fake_connectivity)

        # 指定网卡 down 时，候选列表只包含指定网卡（即使 down）
        assert await probes_mod.is_local_network_connected(interface_name="Ethernet") is False

    async def test_specific_interface_missing_fallback(self, monkeypatch):
        """指定网卡不存在时应返回 False（候选列表为空）。"""
        from app.network import probes as probes_mod

        fake_stats = {
            "Wi-Fi": type("S", (), {"isup": True, "speed": 300})(),
        }
        monkeypatch.setattr(
            "app.network.probes.psutil.net_if_stats", lambda: fake_stats
        )

        async def _fake_connectivity(name: str) -> bool:
            return name == "Wi-Fi"

        monkeypatch.setattr(probes_mod, "_check_interface_connectivity", _fake_connectivity)

        # 指定网卡不存在时，候选列表为空
        assert await probes_mod.is_local_network_connected(interface_name="Ethernet") is False

    async def test_no_interface_name_uses_candidate_filter(self, monkeypatch):
        """不指定网卡名时使用候选过滤 + TCP Connect。"""
        from app.network import probes as probes_mod

        fake_stats = {
            "Wi-Fi": type("S", (), {"isup": True, "speed": 300})(),
        }
        monkeypatch.setattr(
            "app.network.probes.psutil.net_if_stats", lambda: fake_stats
        )

        async def _fake_connectivity(name: str) -> bool:
            return name == "Wi-Fi"

        monkeypatch.setattr(probes_mod, "_check_interface_connectivity", _fake_connectivity)

        assert await probes_mod.is_local_network_connected() is True


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
