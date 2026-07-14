"""网络检测 E2E 测试 — 真实 TCP/URL 探测。

直接调用 app.network.probes 模块函数做真实网络探测，
并通过 POST /api/actions/test-network 验证 API 触发路径。
"""

from __future__ import annotations

import asyncio


def _ensure_probes_active() -> None:
    """清空网络探测关闭标志，避免上一轮 real_app 关闭残留影响。"""
    from app.network.probes import _shutdown_event

    _shutdown_event.clear()


class TestNetworkDetectionDirect:
    """直接调用 network 模块函数做真实探测。"""

    def test_url_check_valid_portal(self, http_portal):
        """合法门户 URL 检测返回已连接。"""
        _ensure_probes_active()
        _, _, base_url = http_portal
        from app.network.probes import is_network_available_url

        result = asyncio.run(
            is_network_available_url(
                url_checks=[(f"{base_url}/success", "Success")],
                timeout=3.0,
            )
        )
        assert result is True

    def test_url_check_nonexistent(self):
        """不存在的 URL 检测返回未连接。"""
        _ensure_probes_active()
        from app.network.probes import is_network_available_url

        result = asyncio.run(
            is_network_available_url(
                url_checks=[("http://127.0.0.1:1/nonexistent", "Success")],
                timeout=2.0,
            )
        )
        assert result is False

    def test_tcp_probe_open_port(self, http_portal):
        """TCP 探测开放端口成功。"""
        _ensure_probes_active()
        host, port, _ = http_portal
        from app.network.probes import is_network_available_socket

        result = asyncio.run(
            is_network_available_socket(
                test_sites=[(host, port)],
                timeout=2.0,
            )
        )
        assert result is True

    def test_tcp_probe_closed_port(self):
        """TCP 探测关闭端口失败。"""
        _ensure_probes_active()
        from app.network.probes import is_network_available_socket

        result = asyncio.run(
            is_network_available_socket(
                test_sites=[("127.0.0.1", 1)],
                timeout=1.5,
            )
        )
        assert result is False


class TestNetworkDetectionAPI:
    """通过 POST /api/actions/test-network 触发网络检测。"""

    def test_api_test_network_portal_passes(self, real_app, http_portal):
        """配置门户 URL 后 test-network 返回成功（已连接）。"""
        client, _ = real_app
        _ensure_probes_active()
        _, _, base_url = http_portal
        # 配置 monitor 仅启用 URL 检测指向本地门户
        patch_body = {
            "monitor": {
                "enable_tcp_check": False,
                "enable_http_check": False,
                "enable_local_check": False,
                "url_check_urls": [f"{base_url}/success|Success"],
            }
        }
        resp = client.patch("/api/config", json=patch_body)
        assert resp.status_code == 200
        resp = client.post("/api/actions/test-network")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True

    def test_api_test_network_nonexistent_fails(self, real_app):
        """配置不存在 URL 后 test-network 返回失败（未连接）。"""
        client, _ = real_app
        _ensure_probes_active()
        patch_body = {
            "monitor": {
                "enable_tcp_check": False,
                "enable_http_check": False,
                "enable_local_check": False,
                "url_check_urls": ["http://127.0.0.1:1/nonexistent|Success"],
            }
        }
        resp = client.patch("/api/config", json=patch_body)
        assert resp.status_code == 200
        resp = client.post("/api/actions/test-network")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
