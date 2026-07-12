"""最小 SOCKS5 Forwarder：仅 CONNECT，IPv4 + 域名，无认证。"""

from __future__ import annotations

import contextlib
import selectors
import socket
import struct
import threading

from app.network.interface_bind import bind_socket_to_interface
from app.network.utils import is_local_address
from app.utils.logging import get_logger

logger = get_logger("socks5_proxy", source="backend")

MAX_CONNECTIONS = 128


class Socks5Server:
    """SOCKS5 代理服务器，用于浏览器流量的网卡绑定。

    通过 IP_UNICAST_IF/SO_BINDTODEVICE/IP_BOUND_IF 绑定出站接口，
    确保浏览器流量真正走指定网卡（而非被默认路由接管）。
    """

    def __init__(self, interface_name: str, fallback_source_ip: str) -> None:
        self._interface_name = interface_name
        self._fallback_ip = fallback_source_ip  # Linux 无 CAP_NET_RAW 时降级用
        self._server_sock: socket.socket | None = None
        self._accept_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._semaphore = threading.Semaphore(MAX_CONNECTIONS)
        self._port: int = 0

    @property
    def port(self) -> int:
        return self._port

    @property
    def proxy_url(self) -> str:
        return f"socks5://127.0.0.1:{self._port}"

    def start(self) -> None:
        """启动 SOCKS5 服务器。"""
        self._server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server_sock.bind(("127.0.0.1", 0))
        self._port = self._server_sock.getsockname()[1]
        self._server_sock.listen(MAX_CONNECTIONS)
        self._server_sock.settimeout(1.0)
        self._stop_event.clear()
        self._accept_thread = threading.Thread(
            target=self._accept_loop, daemon=True, name="socks5-accept"
        )
        self._accept_thread.start()
        logger.info("SOCKS5 Forwarder started on 127.0.0.1:{}", self._port)

    def stop(self) -> None:
        """停止 SOCKS5 服务器并释放资源。"""
        self._stop_event.set()
        if self._server_sock:
            with contextlib.suppress(OSError):
                self._server_sock.close()
        if self._accept_thread:
            self._accept_thread.join(timeout=5)
        logger.info("SOCKS5 Forwarder stopped")

    def _accept_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                client, _addr = self._server_sock.accept()  # type: ignore[union-attr]
                if not self._semaphore.acquire(blocking=False):
                    logger.warning("SOCKS5 max connections reached, rejecting")
                    client.close()
                    continue
                t = threading.Thread(
                    target=self._handle_client,
                    args=(client,),
                    daemon=True,
                    name="socks5-relay",
                )
                t.start()
            except TimeoutError:
                continue
            except OSError:
                if not self._stop_event.is_set():
                    logger.error("SOCKS5 accept error")
                break

    def _handle_client(self, client: socket.socket) -> None:
        remote: socket.socket | None = None
        try:
            self._do_handshake(client)
            addr, port = self._do_connect_request(client)

            # 目标是本地地址时不绑接口（本地回环不该走外部网卡）
            if is_local_address(addr):
                remote = socket.create_connection((addr, port), timeout=10)
            else:
                # 绑接口：手动建 socket + bind_socket_to_interface + connect
                remote = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                remote.settimeout(10)
                bind_socket_to_interface(
                    remote, self._interface_name, self._fallback_ip
                )
                remote.connect((addr, port))

            # Success reply
            client.sendall(b"\x05\x00\x00\x01\x00\x00\x00\x00\x00\x00")
            self._relay(client, remote)
        except _Socks5Error as e:
            logger.debug("SOCKS5 protocol error: {}", e)
            with contextlib.suppress(OSError):
                client.sendall(
                    bytes([0x05, e.reply_code, 0x00, 0x01, 0, 0, 0, 0, 0, 0])
                )
        except Exception as e:
            logger.debug("SOCKS5 connection error: {}", e)
            with contextlib.suppress(OSError):
                client.sendall(bytes([0x05, 0x05, 0x00, 0x01, 0, 0, 0, 0, 0, 0]))
        finally:
            # 半关闭写端，确保对端能读取到已发送的数据后再关闭
            with contextlib.suppress(OSError):
                client.shutdown(socket.SHUT_WR)
            client.close()
            if remote:
                remote.close()
            self._semaphore.release()

    def _do_handshake(self, client: socket.socket) -> None:
        data = self._recv_exact(client, 2)
        ver, nmethods = data[0], data[1]
        if ver != 0x05:
            raise _Socks5Error(0xFF, f"Unsupported version: {ver}")
        methods = self._recv_exact(client, nmethods)
        if 0x00 not in methods:
            client.sendall(b"\x05\xff")
            raise _Socks5Error(0xFF, "NO AUTH not offered")
        client.sendall(b"\x05\x00")

    def _do_connect_request(self, client: socket.socket) -> tuple[str, int]:
        header = self._recv_exact(client, 4)
        ver, cmd, _rsv, atyp = header
        if ver != 0x05:
            raise _Socks5Error(0x01, "Bad version in request")
        if cmd != 0x01:
            raise _Socks5Error(0x07, f"Command not supported: {cmd}")

        if atyp == 0x01:  # IPv4
            raw = self._recv_exact(client, 4)
            addr = socket.inet_ntoa(raw)
            port = struct.unpack("!H", self._recv_exact(client, 2))[0]
        elif atyp == 0x03:  # Domain
            domain_len = self._recv_exact(client, 1)[0]
            addr = self._recv_exact(client, domain_len).decode("ascii")
            port = struct.unpack("!H", self._recv_exact(client, 2))[0]
        elif atyp == 0x04:  # IPv6
            raise _Socks5Error(0x08, "IPv6 not supported")
        else:
            raise _Socks5Error(0x01, f"Unknown ATYP: {atyp}")

        return addr, port

    def _relay(self, client: socket.socket, remote: socket.socket) -> None:
        sel = selectors.DefaultSelector()
        client_alive = True
        remote_alive = True
        try:
            sel.register(client, selectors.EVENT_READ, "client")
            sel.register(remote, selectors.EVENT_READ, "remote")
            while (client_alive or remote_alive) and not self._stop_event.is_set():
                events = sel.select(timeout=1.0)
                for key, _ in events:
                    data = key.fileobj.recv(4096)
                    if not data:
                        if key.data == "client":
                            client_alive = False
                            sel.unregister(client)
                            with contextlib.suppress(OSError):
                                remote.shutdown(socket.SHUT_WR)
                        else:
                            remote_alive = False
                            sel.unregister(remote)
                            with contextlib.suppress(OSError):
                                client.shutdown(socket.SHUT_WR)
                        continue
                    if key.fileobj is client:
                        remote.sendall(data)
                    else:
                        client.sendall(data)
        finally:
            sel.close()

    @staticmethod
    def _recv_exact(sock: socket.socket, n: int) -> bytes:
        buf = bytearray()
        while len(buf) < n:
            chunk = sock.recv(n - len(buf))
            if not chunk:
                raise _Socks5Error(0x01, "Connection closed during read")
            buf.extend(chunk)
        return bytes(buf)


class _Socks5Error(Exception):
    """SOCKS5 协议错误，携带 reply code。"""

    def __init__(self, reply_code: int, message: str = "") -> None:
        super().__init__(message)
        self.reply_code = reply_code
