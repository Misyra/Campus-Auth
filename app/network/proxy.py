"""最小 SOCKS5 Forwarder：仅 CONNECT，IPv4 + 域名，无认证。"""
from __future__ import annotations

import contextlib
import selectors
import socket
import struct
import threading

from app.utils.logging import get_logger

logger = get_logger("socks5_proxy", source="backend")

MAX_CONNECTIONS = 128


class Socks5Server:
    """SOCKS5 代理服务器，用于浏览器流量的网卡绑定。"""

    def __init__(self, bind_ip: str) -> None:
        self._bind_ip = bind_ip
        self._bind_ip_lock = threading.Lock()
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

    def update_bind_ip(self, new_ip: str) -> None:
        """更新出站连接的绑定 IP。"""
        with self._bind_ip_lock:
            old_ip = self._bind_ip
            self._bind_ip = new_ip
        logger.info("SOCKS5 bind IP updated: {} -> {}", old_ip, new_ip)

    def _get_bind_ip(self) -> str:
        with self._bind_ip_lock:
            return self._bind_ip

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

    @staticmethod
    def _is_local_address(addr: str) -> bool:
        """判断是否为本地地址（127.0.0.0/8 或 localhost）。"""
        return addr == "localhost" or addr.startswith("127.")

    def _handle_client(self, client: socket.socket) -> None:
        remote: socket.socket | None = None
        try:
            self._do_handshake(client)
            addr, port = self._do_connect_request(client)
            bind_ip = self._get_bind_ip()
            # 本地地址或绑定 IP 是回环地址时，不绑定 source_address
            # 避免 Windows 上回环 IP 连接远程地址失败
            if self._is_local_address(addr) or self._is_local_address(bind_ip):
                source_addr = None
            else:
                source_addr = (bind_ip, 0)
            remote = socket.create_connection(
                (addr, port),
                timeout=10,
                source_address=source_addr,
            )
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
                client.sendall(
                    bytes([0x05, 0x05, 0x00, 0x01, 0, 0, 0, 0, 0, 0])
                )
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
        sel.register(client, selectors.EVENT_READ)
        sel.register(remote, selectors.EVENT_READ)
        try:
            while True:
                events = sel.select(timeout=5.0)
                if not events:
                    break  # idle timeout
                for key, _ in events:
                    try:
                        data = key.fileobj.recv(65536)  # type: ignore[union-attr]
                    except OSError:
                        return
                    if not data:
                        return
                    target = remote if key.fileobj is client else client
                    try:
                        target.sendall(data)
                    except OSError:
                        return
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
