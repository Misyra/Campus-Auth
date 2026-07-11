"""网络决策层测试。

验证 check_network_status、is_network_available 等函数的 async 行为。
"""

from __future__ import annotations


class TestCheckNetworkStatus:
    """check_network_status async 行为验证。"""

    async def test_check_network_status_calls_is_network_available(self, monkeypatch):
        """check_network_status 调用 is_network_available。"""
        from app.network import decision as decision_mod
        from app.schemas import MonitorSettings

        called_with = {}

        async def fake_is_network_available(**kwargs):
            called_with.update(kwargs)
            return True

        monkeypatch.setattr(
            decision_mod, "is_network_available", fake_is_network_available
        )

        monitor = MonitorSettings(
            enable_tcp_check=True,
            enable_http_check=False,
            ping_targets=["8.8.8.8:53"],
            test_urls=[],
            url_check_urls=[],
            network_check_timeout=2,
        )
        ok, status, method = await decision_mod.check_network_status(monitor)

        assert ok is True
        assert "enable_tcp" in called_with

    async def test_check_network_status_all_disabled(self):
        """所有检测方式关闭时返回 all_disabled。"""
        from app.network import decision as decision_mod
        from app.schemas import MonitorSettings

        monitor = MonitorSettings(
            enable_tcp_check=False,
            enable_http_check=False,
            url_check_urls=[],
        )
        ok, status, method = await decision_mod.check_network_status(monitor)

        assert ok is False
        assert status == "all_disabled"


class TestResolveInterface:
    """_resolve_interface 解析逻辑验证。"""

    def test_no_bind_interface_returns_empty(self):
        """未绑定网卡时返回空接口名。"""
        from app.network import decision as decision_mod
        from app.schemas import MonitorSettings

        monitor = MonitorSettings(bind_interface_name="")
        name, ip = decision_mod._resolve_interface(monitor)
        assert name == ""
        assert ip is None

    def test_resolves_interface_and_ip(self, monkeypatch):
        """绑定网卡存在时返回接口名和 IP。"""
        from app.network import decision as decision_mod
        from app.schemas import MonitorSettings

        fake_mgr = type("M", (), {"resolve_ip": lambda self, name: "192.168.1.5"})()
        monkeypatch.setattr(decision_mod, "_interface_mgr", fake_mgr)

        monitor = MonitorSettings(bind_interface_name="Ethernet")
        name, ip = decision_mod._resolve_interface(monitor)
        assert name == "Ethernet"
        assert ip == "192.168.1.5"

    def test_unresolvable_returns_empty(self, monkeypatch):
        """绑定网卡无 IP 时返回空接口名。"""
        from app.network import decision as decision_mod
        from app.schemas import MonitorSettings

        fake_mgr = type("M", (), {"resolve_ip": lambda self, name: None})()
        monkeypatch.setattr(decision_mod, "_interface_mgr", fake_mgr)

        monitor = MonitorSettings(bind_interface_name="Ethernet")
        name, ip = decision_mod._resolve_interface(monitor)
        assert name == ""
        assert ip is None


class TestCheckNetworkStatusPassesInterface:
    """check_network_status 传递 interface_name 到 is_network_available。"""

    async def test_interface_forwarded(self, monkeypatch):
        """interface_name 和 fallback_source_ip 应传递给 is_network_available。"""
        from app.network import decision as decision_mod
        from app.schemas import MonitorSettings

        called_with: dict = {}

        async def fake_is_network_available(**kwargs):
            called_with.update(kwargs)
            return True

        fake_mgr = type("M", (), {"resolve_ip": lambda self, name: "10.0.0.1"})()
        monkeypatch.setattr(decision_mod, "_interface_mgr", fake_mgr)
        monkeypatch.setattr(
            decision_mod, "is_network_available", fake_is_network_available
        )

        monitor = MonitorSettings(
            enable_tcp_check=True,
            enable_http_check=False,
            ping_targets=["8.8.8.8:53"],
            test_urls=[],
            url_check_urls=[],
            bind_interface_name="Ethernet",
        )
        await decision_mod.check_network_status(monitor)

        assert called_with.get("interface_name") == "Ethernet"
        assert called_with.get("fallback_source_ip") == "10.0.0.1"


class TestNoExecutorRemnants:
    """确认决策层 executor 已被移除。"""

    def test_no_decision_executor(self):
        """decision 模块不再有 _decision_executor 属性。"""
        import app.network.decision as decision_mod

        assert not hasattr(decision_mod, "_decision_executor")

    def test_no_shutdown_decision_executor(self):
        """decision 模块不再有 shutdown_decision_executor 函数。"""
        import app.network.decision as decision_mod

        assert not hasattr(decision_mod, "shutdown_decision_executor")
