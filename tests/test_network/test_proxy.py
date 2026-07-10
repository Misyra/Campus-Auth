"""SOCKS5 Forwarder 单元测试。"""

from __future__ import annotations

import socket
import struct

import pytest


class TestSocks5Handshake:
    """SOCKS5 握手和认证测试。"""

    def test_accepts_no_auth(self):
        from app.network.proxy import Socks5Server

        # 测试用：空接口名（不绑接口，走默认路由）
        server = Socks5Server("", "127.0.0.1")
        server.start()
        try:
            client = socket.create_connection(("127.0.0.1", server.port), timeout=2)
            # Send greeting: VER=5, NMETHODS=1, METHODS=[0x00]
            client.sendall(b"\x05\x01\x00")
            resp = client.recv(2)
            assert resp == b"\x05\x00"  # VER=5, METHOD=NO AUTH
            client.close()
        finally:
            server.stop()

    def test_rejects_auth_required(self):
        from app.network.proxy import Socks5Server

        server = Socks5Server("", "127.0.0.1")
        server.start()
        try:
            client = socket.create_connection(("127.0.0.1", server.port), timeout=2)
            # Only offer USERNAME/PASSWORD (0x02), no NO AUTH
            client.sendall(b"\x05\x01\x02")
            resp = client.recv(2)
            assert resp[1] == 0xFF  # NO ACCEPTABLE METHODS
            client.close()
        finally:
            server.stop()


class TestSocks5Connect:
    """SOCKS5 CONNECT 命令测试。"""

    def test_connect_ipv4(self):
        """CONNECT 到 IPv4 地址成功。"""
        from app.network.proxy import Socks5Server

        server = Socks5Server("", "127.0.0.1")
        server.start()
        try:
            # 超时需大于服务端 create_connection 的 10 秒超时
            client = socket.create_connection(("127.0.0.1", server.port), timeout=15)
            client.sendall(b"\x05\x01\x00")
            client.recv(2)  # greeting response

            # CONNECT to 127.0.0.1:12345 (will fail but we test the protocol)
            addr = socket.inet_aton("127.0.0.1")
            port = struct.pack("!H", 12345)
            client.sendall(b"\x05\x01\x00\x01" + addr + port)
            resp = client.recv(10)
            assert resp[0] == 0x05  # VER
            # REP could be 0x00 (success) or 0x05 (connection refused)
            client.close()
        finally:
            server.stop()

    def test_rejects_ipv6(self):
        from app.network.proxy import Socks5Server

        server = Socks5Server("", "127.0.0.1")
        server.start()
        try:
            client = socket.create_connection(("127.0.0.1", server.port), timeout=5)
            client.sendall(b"\x05\x01\x00")
            client.recv(2)

            # CONNECT with ATYP=0x04 (IPv6)
            client.sendall(b"\x05\x01\x00\x04" + b"\x00" * 16 + b"\x00\x50")
            resp = client.recv(10)
            assert resp[1] == 0x08  # ATYP not supported
            client.close()
        finally:
            server.stop()


class TestSocks5Lifecycle:
    """生命周期测试。"""

    def test_proxy_url_format(self):
        from app.network.proxy import Socks5Server

        server = Socks5Server("", "127.0.0.1")
        server.start()
        try:
            assert server.proxy_url.startswith("socks5://127.0.0.1:")
            assert server.port > 0
        finally:
            server.stop()

    def test_stop_cleans_up(self):
        from app.network.proxy import Socks5Server

        server = Socks5Server("", "127.0.0.1")
        server.start()
        port = server.port
        server.stop()

        # 端口应该已释放（Windows 上可能是 TimeoutError 而非 ConnectionRefusedError）
        with pytest.raises(OSError):
            socket.create_connection(("127.0.0.1", port), timeout=0.5)
