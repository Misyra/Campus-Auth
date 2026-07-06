# 网卡绑定功能 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 Campus-Auth 新增绑定网卡功能，使网络探测和浏览器流量全部走同一张网卡，解决双网卡环境下的检测误判问题。

**Architecture:** 新增 `InterfaceManager` 作为唯一网卡信息入口（封装 psutil），探测层通过 `source_address` / `local_address` 绑定指定网卡 IP，浏览器通过进程内最小 SOCKS5 Forwarder 转发。配置存网卡名，运行时解析 IP，30 秒 TTL 缓存，DHCP 变化时自动更新。

**Tech Stack:** Python 3.12+, psutil, httpx, Playwright (Chromium), Vue 3 (CDN), pytest

**Spec:** `docs/superpowers/specs/2026-07-04-nic-binding-design.md`

---

## File Structure

| File | Responsibility |
|------|---------------|
| `app/network/interfaces.py` | **新增** InterfaceInfo dataclass + InterfaceManager（唯一 psutil 入口） |
| `app/network/probes.py` | 修改：探测函数加 source_ip，物理检查加回退 |
| `app/network/decision.py` | 修改：传递 bind_interface_name，调用 InterfaceManager |
| `app/network/proxy.py` | **新增** 最小 SOCKS5 Forwarder |
| `app/network/detect.py` | 修改：扩展网关解析为按网卡索引 |
| `app/schemas.py` | 修改：MonitorSettings 加 bind_interface_name |
| `app/api/monitor.py` | 修改：GET /api/network/interfaces |
| `app/services/monitor_service.py` | 修改：Proxy 生命周期、IP 变化检测 |
| `app/services/login_orchestrator.py` | 修改：worker dict 注入 bind_proxy |
| `app/workers/playwright_worker.py` | 修改：context options 注入 proxy |
| `frontend/partials/pages/settings/settings-monitor.html` | 修改：网卡选择 UI |
| `frontend/js/api-service.js` | 修改：fetchInterfaces |
| `frontend/js/constants.js` | 修改：DEFAULT_CONFIG |
| `frontend/js/app-options.js` | 修改：下拉数据 + 刷新 |
| `tests/test_network/test_interfaces.py` | **新增** InterfaceManager 测试 |
| `tests/test_network/test_proxy.py` | **新增** SOCKS5 Forwarder 测试 |

---

## Task 0: PoC 验证

在写任何代码前，验证核心假设。创建一个独立的 PoC 脚本（不入库），验证 7 项内容。

**Files:**
- Create: `poc/nic_binding_poc.py`（临时，不提交）

- [ ] **Step 1: 编写最小 SOCKS5 server + Chromium 验证脚本**

```python
"""PoC: 验证 Chromium SOCKS5 代理行为。

验证清单:
1. Chromium 流量是否确实走 SOCKS5（而非静默直连）
2. CONNECT 请求包含 IPv4 (0x01) 和 Domain (0x03)
3. DNS 行为（本地解析 vs 交给 SOCKS5）
4. source_address 是否固定出口网卡
5. 浏览器关闭后连接释放
"""
import socket
import struct
import threading
import time
from playwright.sync_api import sync_playwright

BIND_IP = "YOUR_CAMPUS_NIC_IP"  # 替换为实际网卡 IP
connections_received = []

def handle_client(client_sock, bind_ip):
    """处理单个 SOCKS5 连接。"""
    try:
        # Greeting
        data = client_sock.recv(262)
        ver, nmethods = data[0], data[1]
        assert ver == 0x05
        # NO AUTH
        client_sock.sendall(b"\x05\x00")

        # CONNECT request
        data = client_sock.recv(4)
        ver, cmd, rsv, atyp = data
        assert ver == 0x05 and cmd == 0x01  # CONNECT only

        if atyp == 0x01:  # IPv4
            addr = socket.inet_ntoa(client_sock.recv(4))
            port = struct.unpack("!H", client_sock.recv(2))[0]
        elif atyp == 0x03:  # Domain
            domain_len = client_sock.recv(1)[0]
            addr = client_sock.recv(domain_len).decode()
            port = struct.unpack("!H", client_sock.recv(2))[0]
        else:
            # Unsupported ATYP
            client_sock.sendall(b"\x05\x08\x00\x01\x00\x00\x00\x00\x00\x00")
            return

        connections_received.append((atyp, addr, port))
        print(f"CONNECT: {addr}:{port} (ATYP=0x{atyp:02x})")

        # Connect to target with source_address binding
        remote = socket.create_connection(
            (addr, port), timeout=10,
            source_address=(bind_ip, 0)
        )
        # Success reply
        client_sock.sendall(b"\x05\x00\x00\x01\x00\x00\x00\x00\x00\x00")

        # Relay
        import selectors
        sel = selectors.DefaultSelector()
        sel.register(client_sock, selectors.EVENT_READ)
        sel.register(remote, selectors.EVENT_READ)

        while True:
            for key, _ in sel.select(timeout=5):
                data = key.fileobj.recv(65536)
                if not data:
                    sel.close()
                    remote.close()
                    return
                target = remote if key.fileobj is client_sock else client_sock
                target.sendall(data)
    except Exception as e:
        print(f"Connection error: {e}")
    finally:
        client_sock.close()

def run_poc():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("127.0.0.1", 0))
    port = server.getsockname()[1]
    server.listen(128)
    server.settimeout(30)

    print(f"SOCKS5 listening on 127.0.0.1:{port}")
    print(f"Binding outbound to {BIND_IP}")

    # Accept connections in background
    def accept_loop():
        while True:
            try:
                client, addr = server.accept()
                t = threading.Thread(target=handle_client, args=(client, BIND_IP), daemon=True)
                t.start()
            except socket.timeout:
                break

    accept_thread = threading.Thread(target=accept_loop, daemon=True)
    accept_thread.start()

    # Launch Chromium via Playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(
            proxy={"server": f"socks5://127.0.0.1:{port}"}
        )
        page = context.new_page()

        print("\n--- Test 1: Navigate to example.com ---")
        page.goto("http://example.com", timeout=15000)
        time.sleep(2)

        print(f"\nConnections received: {len(connections_received)}")
        ipv4_count = sum(1 for a, _, _ in connections_received if a == 0x01)
        domain_count = sum(1 for a, _, _ in connections_received if a == 0x03)
        print(f"  IPv4 (ATYP=0x01): {ipv4_count}")
        print(f"  Domain (ATYP=0x03): {domain_count}")

        if len(connections_received) > 0:
            print("✓ PASS: Traffic goes through SOCKS5 proxy (not silent direct)")
        else:
            print("✗ FAIL: No connections received - Chromium may be silently bypassing proxy!")

        browser.close()

    # Check connections cleaned up
    time.sleep(2)
    print(f"\nAfter browser close: checking connection cleanup...")
    server.close()
    print("Done.")

if __name__ == "__main__":
    run_poc()
```

- [ ] **Step 2: 运行 PoC 并记录结果**

Run: `python poc/nic_binding_poc.py`

Expected: 至少收到 1 个 CONNECT 请求，确认流量走代理。如果 0 连接，则 SOCKS5 方案不可行，需重新评估。

- [ ] **Step 3: 根据 PoC 结果决定**

如果 PoC 通过 → 继续 Task 1。
如果 PoC 失败（Chromium 静默直连）→ 停止，重新评估浏览器绑定方案。

- [ ] **Step 4: 清理 PoC 文件**

PoC 脚本不入库，删除 `poc/` 目录。

---

## Task 1: InterfaceInfo 数据模型 + MonitorSettings 配置字段

**Files:**
- Create: `app/network/interfaces.py`
- Modify: `app/schemas.py:295-309` (MonitorSettings)
- Modify: `frontend/js/constants.js:104-123` (DEFAULT_CONFIG.monitor)
- Test: `tests/test_network/test_interfaces.py`

- [ ] **Step 1: 编写 InterfaceInfo 测试**

```python
# tests/test_network/test_interfaces.py
from __future__ import annotations

import pytest


class TestInterfaceInfo:
    """InterfaceInfo 数据模型测试。"""

    def test_frozen_dataclass(self):
        from app.network.interfaces import InterfaceInfo

        info = InterfaceInfo(name="以太网", ip="192.168.1.5", gateway="192.168.1.1", is_up=True)
        with pytest.raises(AttributeError):
            info.name = "WLAN"  # type: ignore[misc]

    def test_empty_ip_and_gateway(self):
        from app.network.interfaces import InterfaceInfo

        info = InterfaceInfo(name="eth0", ip="", gateway="", is_up=False)
        assert info.ip == ""
        assert info.gateway == ""
        assert info.is_up is False

    def test_slots(self):
        from app.network.interfaces import InterfaceInfo

        info = InterfaceInfo(name="WLAN", ip="10.0.0.1", gateway="10.0.0.254", is_up=True)
        with pytest.raises(AttributeError):
            info.extra = "field"  # type: ignore[attr-defined]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_network/test_interfaces.py::TestInterfaceInfo -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.network.interfaces'`

- [ ] **Step 3: 实现 InterfaceInfo**

```python
# app/network/interfaces.py
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class InterfaceInfo:
    """网络接口信息，统一用于 API、探测、代理、UI。"""

    name: str
    ip: str           # IPv4，空串表示无 IPv4
    gateway: str      # 默认网关，空串表示无
    is_up: bool
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_network/test_interfaces.py::TestInterfaceInfo -v`
Expected: 3 passed

- [ ] **Step 5: 给 MonitorSettings 加 bind_interface_name**

在 `app/schemas.py` 的 `MonitorSettings` 类中（`script_timeout` 字段之后）新增：

```python
    bind_interface_name: str = Field(default="", description="绑定网卡名称，空串表示不绑定")
```

- [ ] **Step 6: 更新前端 DEFAULT_CONFIG**

在 `frontend/js/constants.js` 的 `DEFAULT_CONFIG.monitor` 对象末尾添加：

```js
    bind_interface_name: '',
```

- [ ] **Step 7: 运行已有 schema 测试确认无破坏**

Run: `pytest tests/ -v -x --timeout=30`
Expected: 全部通过

- [ ] **Step 8: 提交**

```bash
git add app/network/interfaces.py app/schemas.py frontend/js/constants.js tests/test_network/test_interfaces.py
git commit -m "feat: add InterfaceInfo dataclass and bind_interface_name config field"
```

---

## Task 2: InterfaceManager 核心实现

**Files:**
- Modify: `app/network/interfaces.py`
- Test: `tests/test_network/test_interfaces.py`

- [ ] **Step 1: 编写 InterfaceManager 测试**

在 `tests/test_network/test_interfaces.py` 末尾追加：

```python
from unittest.mock import patch, MagicMock


class TestInterfaceManager:
    """InterfaceManager 测试。"""

    def test_list_interfaces_filters_virtual(self):
        from app.network.interfaces import InterfaceManager

        mock_stats = {
            "以太网": MagicMock(isup=True, isloopback=False),
            "lo": MagicMock(isup=True, isloopback=True),
            "docker0": MagicMock(isup=True, isloopback=False),
            "veth123": MagicMock(isup=True, isloopback=False),
        }
        mock_addrs = {
            "以太网": [MagicMock(family=2, address="192.168.1.5")],
            "lo": [MagicMock(family=2, address="127.0.0.1")],
            "docker0": [MagicMock(family=2, address="172.17.0.1")],
            "veth123": [MagicMock(family=2, address="10.0.0.1")],
        }
        with patch("app.network.interfaces.psutil.net_if_stats", return_value=mock_stats), \
             patch("app.network.interfaces.psutil.net_if_addrs", return_value=mock_addrs):
            mgr = InterfaceManager()
            result = mgr.list_interfaces()

        names = [i.name for i in result]
        assert "以太网" in names
        assert "lo" not in names
        assert "docker0" not in names
        assert "veth123" not in names

    def test_list_interfaces_excludes_no_ipv4(self):
        from app.network.interfaces import InterfaceManager

        mock_stats = {
            "tun0": MagicMock(isup=True, isloopback=False),
        }
        mock_addrs = {
            "tun0": [],  # 无 IPv4
        }
        with patch("app.network.interfaces.psutil.net_if_stats", return_value=mock_stats), \
             patch("app.network.interfaces.psutil.net_if_addrs", return_value=mock_addrs):
            mgr = InterfaceManager()
            result = mgr.list_interfaces()

        assert len(result) == 0

    def test_resolve_ip_returns_ipv4(self):
        from app.network.interfaces import InterfaceManager

        mock_addrs = {
            "以太网": [
                MagicMock(family=2, address="192.168.1.5"),   # AF_INET
                MagicMock(family=23, address="fe80::1"),       # AF_INET6
            ],
        }
        mock_stats = {
            "以太网": MagicMock(isup=True, isloopback=False),
        }
        with patch("app.network.interfaces.psutil.net_if_addrs", return_value=mock_addrs), \
             patch("app.network.interfaces.psutil.net_if_stats", return_value=mock_stats):
            mgr = InterfaceManager()
            ip = mgr.resolve_ip("以太网")

        assert ip == "192.168.1.5"

    def test_resolve_ip_returns_none_for_missing(self):
        from app.network.interfaces import InterfaceManager

        with patch("app.network.interfaces.psutil.net_if_addrs", return_value={}), \
             patch("app.network.interfaces.psutil.net_if_stats", return_value={}):
            mgr = InterfaceManager()
            assert mgr.resolve_ip("不存在") is None

    def test_resolve_ip_caching_30s_ttl(self):
        from app.network.interfaces import InterfaceManager
        import time

        call_count = 0
        def fake_addrs():
            nonlocal call_count
            call_count += 1
            return {"以太网": [MagicMock(family=2, address="192.168.1.5")]}

        mock_stats = {"以太网": MagicMock(isup=True, isloopback=False)}
        with patch("app.network.interfaces.psutil.net_if_addrs", side_effect=fake_addrs), \
             patch("app.network.interfaces.psutil.net_if_stats", return_value=mock_stats), \
             patch("app.network.interfaces.time.monotonic", side_effect=[0, 0, 10, 31]):
            mgr = InterfaceManager()
            mgr.resolve_ip("以太网")  # t=0, cache miss
            mgr.resolve_ip("以太网")  # t=0, cache hit
            mgr.resolve_ip("以太网")  # t=10, cache hit
            mgr.resolve_ip("以太网")  # t=31, cache expired

        assert call_count == 2  # 首次 + 过期后

    def test_is_interface_up(self):
        from app.network.interfaces import InterfaceManager

        mock_stats = {
            "以太网": MagicMock(isup=True, isloopback=False),
            "WLAN": MagicMock(isup=False, isloopback=False),
        }
        with patch("app.network.interfaces.psutil.net_if_stats", return_value=mock_stats):
            mgr = InterfaceManager()
            assert mgr.is_interface_up("以太网") is True
            assert mgr.is_interface_up("WLAN") is False
            assert mgr.is_interface_up("不存在") is False
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_network/test_interfaces.py::TestInterfaceManager -v`
Expected: FAIL — `ImportError` 或 `AttributeError`

- [ ] **Step 3: 实现 InterfaceManager**

在 `app/network/interfaces.py` 中追加：

```python
import socket
import time
from collections.abc import Sequence

import psutil

from app.network.probes import _VIRTUAL_NIC_PREFIXES, _is_virtual_nic
from app.utils.logging import get_logger

logger = get_logger("interfaces", source="backend")

# psutil 的 AF_INET 在不同平台值不同，用 socket.AF_INET
_AF_INET = socket.AF_INET  # Windows=2, Linux=2, macOS=2

_CACHE_TTL = 30.0  # 秒


class InterfaceManager:
    """网卡信息管理入口。整个项目只有此模块调用 psutil 的网卡 API。"""

    def __init__(self) -> None:
        self._cache: dict[str, tuple[InterfaceInfo, float]] = {}

    def _get_ipv4(self, name: str) -> str:
        """获取指定网卡的 IPv4 地址，无则返回空串。"""
        for addr in psutil.net_if_addrs().get(name, []):
            if addr.family == _AF_INET:
                return addr.address
        return ""

    def _build_info(self, name: str, stats) -> InterfaceInfo:
        return InterfaceInfo(
            name=name,
            ip=self._get_ipv4(name),
            gateway="",  # 由 list_interfaces 填充
            is_up=stats.isup,
        )

    def _is_physical(self, name: str, stats) -> bool:
        """判断是否为物理网卡。"""
        if stats.isloopback:
            return False
        if name.lower().startswith("lo"):
            return False
        if _is_virtual_nic(name):
            return False
        # 无 IPv4 的排除
        if not self._get_ipv4(name):
            return False
        return True

    def list_interfaces(self) -> list[InterfaceInfo]:
        """枚举物理网卡列表。"""
        result: list[InterfaceInfo] = []
        stats_all = psutil.net_if_stats()
        for name, stats in stats_all.items():
            if self._is_physical(name, stats):
                info = self._build_info(name, stats)
                result.append(info)
        return result

    def get_interface(self, name: str) -> InterfaceInfo | None:
        """获取指定网卡信息，优先走缓存。"""
        cached = self._cache.get(name)
        if cached:
            info, ts = cached
            if time.monotonic() - ts < _CACHE_TTL:
                return info

        stats = psutil.net_if_stats().get(name)
        if stats is None:
            return None
        info = self._build_info(name, stats)
        self._cache[name] = (info, time.monotonic())
        return info

    def resolve_ip(self, name: str) -> str | None:
        """解析网卡 IPv4 地址，30 秒 TTL 缓存。"""
        info = self.get_interface(name)
        if info and info.ip:
            return info.ip
        return None

    def is_interface_up(self, name: str) -> bool:
        """检查指定网卡是否 up。"""
        stats = psutil.net_if_stats().get(name)
        return stats is not None and stats.isup
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_network/test_interfaces.py -v`
Expected: 全部通过

- [ ] **Step 5: 提交**

```bash
git add app/network/interfaces.py tests/test_network/test_interfaces.py
git commit -m "feat: implement InterfaceManager with 30s TTL cache and virtual NIC filtering"
```

---

## Task 3: 网关解析扩展

**Files:**
- Modify: `app/network/interfaces.py`
- Modify: `app/network/detect.py`
- Test: `tests/test_network/test_interfaces.py`

- [ ] **Step 1: 编写按网卡索引获取网关的测试**

```python
# 在 test_interfaces.py 中追加

class TestInterfaceManagerGateway:
    """网关解析测试。"""

    def test_build_ip_to_name_map(self):
        from app.network.interfaces import InterfaceManager

        mock_addrs = {
            "以太网": [MagicMock(family=2, address="192.168.1.5")],
            "WLAN": [MagicMock(family=2, address="10.0.0.3")],
        }
        with patch("app.network.interfaces.psutil.net_if_addrs", return_value=mock_addrs):
            mgr = InterfaceManager()
            mapping = mgr._build_ip_to_name_map()

        assert mapping == {"192.168.1.5": "以太网", "10.0.0.3": "WLAN"}

    def test_gateways_linux(self):
        from app.network.interfaces import InterfaceManager

        proc_content = (
            "Iface\tDestination\tGateway\tFlags\tRefCnt\tUse\tMetric\tMask\n"
            "eth0\t00000000\t0101A8C0\t0003\t0\t0\t100\t00000000\n"
            "wlan0\t00000000\tFE00A8C0\t0003\t0\t0\t600\t00000000\n"
        )
        ip_map = {"192.168.1.5": "eth0", "192.168.0.3": "wlan0"}
        mgr = InterfaceManager()

        from unittest.mock import mock_open
        with patch("builtins.open", mock_open(read_data=proc_content)):
            result = mgr._gateways_linux(ip_map)

        # 0101A8C0 → 192.168.1.1 (little-endian hex)
        assert result.get("eth0") == "192.168.1.1"
```

- [ ] **Step 2: 在 InterfaceManager 中实现 get_gateways_by_name()**

在 `app/network/interfaces.py` 的 `InterfaceManager` 类中追加方法。实现逻辑：

1. 构建 IP→网卡名的映射（从 `psutil.net_if_addrs()` 获取）
2. 根据平台调用不同的网关获取方式：
   - Windows：`subprocess.run(["route", "print", "0.0.0.0"])` 解析输出，匹配接口 IP
   - Linux：解析 `/proc/net/route` 中 Destination=`00000000` 的行
   - macOS：`subprocess.run(["netstat", "-rn"])` 解析

```python
def get_gateways_by_name(self) -> dict[str, str]:
    """返回 {网卡名: 网关IP} 映射。"""
    ip_to_name = self._build_ip_to_name_map()
    import platform
    if platform.system() == "Windows":
        return self._gateways_windows(ip_to_name)
    elif platform.system() == "Linux":
        return self._gateways_linux(ip_to_name)
    else:
        return self._gateways_macos(ip_to_name)

def _build_ip_to_name_map(self) -> dict[str, str]:
    """构建 IP → 网卡名映射。"""
    mapping: dict[str, str] = {}
    for name, addrs in psutil.net_if_addrs().items():
        for addr in addrs:
            if addr.family == _AF_INET:
                mapping[addr.address] = name
    return mapping
```

各平台的 `_gateways_*` 方法应**复用** `detect.py` 已有的解析辅助函数（`_parse_windows_route_print`、`_hex_to_ipv4` 等），不要复制解析逻辑。具体做法：从 `detect.py` import 这些函数，在 `interfaces.py` 中做 IP→名称映射后调用。如果现有辅助函数签名不适合直接复用（如只返回单条网关），则提取核心解析逻辑为更通用的辅助函数。

- [ ] **Step 3: 更新 list_interfaces 填充 gateway**

修改 `list_interfaces()` 方法，调用 `get_gateways_by_name()` 填充每个 `InterfaceInfo` 的 `gateway` 字段。

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_network/test_interfaces.py tests/test_network/test_detect.py -v`
Expected: 全部通过（已有 detect 测试不受影响）

- [ ] **Step 5: 提交**

```bash
git add app/network/interfaces.py app/network/detect.py tests/test_network/test_interfaces.py
git commit -m "feat: extend gateway detection to per-interface indexing"
```

---

## Task 4: 网卡枚举 API

**Files:**
- Modify: `app/api/monitor.py`
- Test: `tests/test_api/` 下新增或追加

- [ ] **Step 1: 编写 API 端点测试**

```python
class TestNetworkInterfacesAPI:
    def test_get_interfaces_returns_list(self, api_client):
        from unittest.mock import patch, MagicMock
        from app.network.interfaces import InterfaceInfo

        fake_interfaces = [
            InterfaceInfo(name="以太网", ip="192.168.1.5", gateway="192.168.1.1", is_up=True),
        ]
        with patch("app.api.monitor.InterfaceManager") as MockMgr:
            MockMgr.return_value.list_interfaces.return_value = fake_interfaces
            resp = api_client.get("/api/network/interfaces")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["id"] == "以太网"
        assert data[0]["ip"] == "192.168.1.5"

    def test_get_interfaces_empty(self, api_client):
        with patch("app.api.monitor.InterfaceManager") as MockMgr:
            MockMgr.return_value.list_interfaces.return_value = []
            resp = api_client.get("/api/network/interfaces")

        assert resp.status_code == 200
        assert resp.json() == []
```

- [ ] **Step 2: 实现 API 端点**

在 `app/api/monitor.py` 中新增：

```python
from app.network.interfaces import InterfaceManager

@router.get("/api/network/interfaces")
async def get_network_interfaces():
    """枚举可用物理网卡。"""
    mgr = InterfaceManager()
    interfaces = mgr.list_interfaces()
    return [
        {
            "id": info.name,
            "name": info.name,
            "ip": info.ip,
            "gateway": info.gateway,
            "is_up": info.is_up,
        }
        for info in interfaces
    ]
```

- [ ] **Step 3: 运行测试确认通过**

Run: `pytest tests/test_api/ -v -k "interfaces"`
Expected: PASS

- [ ] **Step 4: 提交**

```bash
git add app/api/monitor.py tests/test_api/
git commit -m "feat: add GET /api/network/interfaces endpoint"
```

---

## Task 5: 探测层绑定（TCP + HTTP + 物理检查）

**Files:**
- Modify: `app/network/probes.py`
- Modify: `app/network/decision.py`
- Test: `tests/test_network/test_probes.py`, `tests/test_network/test_decision.py`

- [ ] **Step 1: TCP 探测加 source_ip 测试**

```python
class TestTcpProbeSourceIp:
    def test_source_ip_passed_to_socket(self, monkeypatch):
        from app.network import probes as probes_mod

        captured = {}
        def fake_create_connection(address, timeout=None, source_address=None):
            captured["source_address"] = source_address
            raise OSError("mock")

        monkeypatch.setattr("app.network.probes.socket.create_connection", fake_create_connection)
        probes_mod.is_network_available_socket(
            test_sites=[("8.8.8.8", 53)], timeout=1, source_ip="192.168.1.5"
        )
        assert captured["source_address"] == ("192.168.1.5", 0)

    def test_no_source_ip_uses_none(self, monkeypatch):
        from app.network import probes as probes_mod

        captured = {}
        def fake_create_connection(address, timeout=None, source_address=None):
            captured["source_address"] = source_address
            raise OSError("mock")

        monkeypatch.setattr("app.network.probes.socket.create_connection", fake_create_connection)
        probes_mod.is_network_available_socket(
            test_sites=[("8.8.8.8", 53)], timeout=1
        )
        assert captured["source_address"] is None
```

- [ ] **Step 2: 修改 is_network_available_socket 加 source_ip 参数**

在 `probes.py` 中修改函数签名和 `_connect_one` 内部：

```python
def is_network_available_socket(
    test_sites: Sequence[tuple[str, int]] | None = None,
    timeout: float = 1.5,
    source_ip: str | None = None,
) -> bool:
    # ... 现有代码 ...
    def _connect_one(host: str, port: int) -> tuple[str, bool, str]:
        start = time.perf_counter()
        try:
            sa = (source_ip, 0) if source_ip else None
            with socket.create_connection((host, port), timeout=timeout, source_address=sa):
                # ... 现有代码 ...
```

- [ ] **Step 3: HTTP 探测加 source_ip + Client 池**

修改 `_get_probe_client` 或新增 `_get_bound_client` 函数：

```python
_bound_clients: dict[str, httpx.Client] = {}
_bound_clients_lock = threading.Lock()
_MAX_BOUND_CLIENTS = 4

def _get_bound_client(source_ip: str, block_proxy: bool) -> httpx.Client:
    with _bound_clients_lock:
        if source_ip in _bound_clients:
            client = _bound_clients[source_ip]
            if not client.is_closed:
                return client
        # 超限关闭最旧的
        while len(_bound_clients) >= _MAX_BOUND_CLIENTS:
            oldest_key = next(iter(_bound_clients))
            _bound_clients.pop(oldest_key).close()

        client = httpx.Client(
            transport=httpx.HTTPTransport(local_address=source_ip),
            verify=False,
            follow_redirects=True,
            trust_env=not block_proxy,
            limits=httpx.Limits(max_connections=4, max_keepalive_connections=2),
        )
        _bound_clients[source_ip] = client
        return client

def close_bound_client(old_ip: str) -> None:
    """IP 变化时关闭旧 Client。"""
    with _bound_clients_lock:
        client = _bound_clients.pop(old_ip, None)
        if client and not client.is_closed:
            client.close()

def _close_all_bound_clients() -> None:
    """关闭时清理所有绑定 Client。"""
    with _bound_clients_lock:
        for client in _bound_clients.values():
            if not client.is_closed:
                client.close()
        _bound_clients.clear()
```

**重要**：在 `shutdown_probes()` 中追加调用 `_close_all_bound_clients()`，避免进程退出时资源泄漏。

修改 `is_network_available_http` 和 `is_network_available_url` 加 `source_ip` 参数，非空时用 `_get_bound_client` 替代 `_get_probe_client`。

- [ ] **Step 4: 物理检查加回退逻辑**

修改 `is_local_network_connected`：

```python
def is_local_network_connected(interface_name: str = "") -> bool:
    try:
        if interface_name:
            stats = psutil.net_if_stats().get(interface_name)
            if stats is not None and stats.isup:
                logger.debug("绑定网卡已连接: {}", interface_name)
                return True
            logger.error("绑定网卡 {} 不可用，回退检查物理网络", interface_name)
        # 原逻辑：任一物理网卡 up
        for name, stats in psutil.net_if_stats().items():
            if (
                stats.isup
                and not name.lower().startswith("lo")
                and not _is_virtual_nic(name)
            ):
                return True
    except Exception as exc:
        logger.debug("psutil 网络检测失败: {}", exc)
    logger.warning("未检测到本地网络连接")
    return False
```

- [ ] **Step 5: decision.py 传递 bind_interface_name**

修改 `check_network_status` 和 `check_login_prerequisites`，新增内部辅助函数：

```python
# decision.py 新增
from app.network.interfaces import InterfaceManager

_interface_mgr: InterfaceManager | None = None

def _get_interface_mgr() -> InterfaceManager:
    global _interface_mgr
    if _interface_mgr is None:
        _interface_mgr = InterfaceManager()
    return _interface_mgr

def _resolve_source_ip(monitor: MonitorSettings) -> str | None:
    """从 MonitorSettings 解析绑定网卡的 source_ip。"""
    name = monitor.bind_interface_name
    if not name:
        return None
    ip = _get_interface_mgr().resolve_ip(name)
    if ip is None:
        logger.error("绑定网卡 {} 不可用，回退到系统默认路由", name)
    return ip
```

在 `check_network_status` 中调用 `_resolve_source_ip` 并将结果透传给 `is_network_available`。`is_network_available` 新增 `source_ip` 参数并传递给三个探测函数。

在 `check_login_prerequisites` 中同样传递 `source_ip` 给 `is_local_network_connected` 和 `_is_auth_url_reachable`。`_is_auth_url_reachable` 的 `_check_host_port` 中 `socket.create_connection` 加 `source_address=(source_ip, 0) if source_ip else None`。

- [ ] **Step 6: 运行全部网络测试**

Run: `pytest tests/test_network/ -v`
Expected: 全部通过

- [ ] **Step 7: 提交**

```bash
git add app/network/probes.py app/network/decision.py tests/test_network/
git commit -m "feat: add source_ip binding to TCP/HTTP probes and physical check fallback"
```

---

## Task 6: SOCKS5 Forwarder

**Files:**
- Create: `app/network/proxy.py`
- Test: `tests/test_network/test_proxy.py`

这是最复杂的 Task，拆为多个 step。

- [ ] **Step 1: 编写 SOCKS5 握手测试**

```python
# tests/test_network/test_proxy.py
from __future__ import annotations

import socket
import struct
import threading
import time

import pytest


class TestSocks5Handshake:
    """SOCKS5 握手和认证测试。"""

    def test_accepts_no_auth(self):
        from app.network.proxy import Socks5Server

        server = Socks5Server("127.0.0.1")  # 绑定到回环（测试用）
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

        server = Socks5Server("127.0.0.1")
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

        server = Socks5Server("127.0.0.1")
        server.start()
        try:
            client = socket.create_connection(("127.0.0.1", server.port), timeout=2)
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

        server = Socks5Server("127.0.0.1")
        server.start()
        try:
            client = socket.create_connection(("127.0.0.1", server.port), timeout=2)
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

        server = Socks5Server("127.0.0.1")
        server.start()
        try:
            assert server.proxy_url.startswith("socks5://127.0.0.1:")
            assert server.port > 0
        finally:
            server.stop()

    def test_stop_cleans_up(self):
        from app.network.proxy import Socks5Server

        server = Socks5Server("127.0.0.1")
        server.start()
        port = server.port
        server.stop()

        # 端口应该已释放
        with pytest.raises(ConnectionRefusedError):
            socket.create_connection(("127.0.0.1", port), timeout=0.5)

    def test_update_bind_ip(self):
        from app.network.proxy import Socks5Server

        server = Socks5Server("127.0.0.1")
        server.start()
        try:
            server.update_bind_ip("192.168.1.100")
            # 内部 _bind_ip 应更新（通过后续 CONNECT 验证）
        finally:
            server.stop()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_network/test_proxy.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: 实现 Socks5Server**

在 `app/network/proxy.py` 中实现。核心结构：

```python
"""最小 SOCKS5 Forwarder：仅 CONNECT，IPv4 + 域名，无认证。"""
from __future__ import annotations

import selectors
import socket
import struct
import threading

from app.utils.logging import get_logger

logger = get_logger("socks5_proxy", source="backend")

MAX_CONNECTIONS = 128


class Socks5Server:
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
        self._stop_event.set()
        if self._server_sock:
            try:
                self._server_sock.close()
            except OSError:
                pass
        if self._accept_thread:
            self._accept_thread.join(timeout=5)
        logger.info("SOCKS5 Forwarder stopped")

    def update_bind_ip(self, new_ip: str) -> None:
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
                client, addr = self._server_sock.accept()  # type: ignore[union-attr]
                if not self._semaphore.acquire(blocking=False):
                    logger.warning("SOCKS5 max connections reached, rejecting")
                    client.close()
                    continue
                t = threading.Thread(
                    target=self._handle_client, args=(client,),
                    daemon=True, name="socks5-relay"
                )
                t.start()
            except socket.timeout:
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
            bind_ip = self._get_bind_ip()
            remote = socket.create_connection(
                (addr, port), timeout=10,
                source_address=(bind_ip, 0),
            )
            # Success reply
            client.sendall(b"\x05\x00\x00\x01\x00\x00\x00\x00\x00\x00")
            self._relay(client, remote)
        except _Socks5Error as e:
            logger.debug("SOCKS5 protocol error: {}", e)
            try:
                client.sendall(bytes([0x05, e.reply_code, 0x00, 0x01,
                                      0, 0, 0, 0, 0, 0]))
            except OSError:
                pass
        except Exception as e:
            logger.debug("SOCKS5 connection error: {}", e)
        finally:
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
        ver, cmd, rsv, atyp = header
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
                        sel.close()
                        return
                    if not data:
                        sel.close()
                        return
                    target = remote if key.fileobj is client else client
                    try:
                        target.sendall(data)
                    except OSError:
                        sel.close()
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
    def __init__(self, reply_code: int, message: str = "") -> None:
        super().__init__(message)
        self.reply_code = reply_code
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_network/test_proxy.py -v`
Expected: 全部通过

- [ ] **Step 5: 提交**

```bash
git add app/network/proxy.py tests/test_network/test_proxy.py
git commit -m "feat: implement minimal SOCKS5 Forwarder (CONNECT, IPv4+Domain, no auth)"
```

---

## Task 7: MonitorCore 集成（代理生命周期 + IP 变化检测）

**Files:**
- Modify: `app/services/monitor_service.py`
- Modify: `app/services/login_orchestrator.py`

- [ ] **Step 1: 在 NetworkMonitorCore 中管理代理生命周期**

修改 `init_monitoring()`：

```python
def init_monitoring(self) -> None:
    # ... 现有逻辑 ...

    # 绑定网卡：启动 SOCKS5 Forwarder
    bind_name = self.config.monitor.bind_interface_name
    if bind_name:
        from app.network.interfaces import InterfaceManager
        self._interface_mgr = InterfaceManager()
        bind_ip = self._interface_mgr.resolve_ip(bind_name)
        if bind_ip:
            from app.network.proxy import Socks5Server
            self._socks5_server = Socks5Server(bind_ip)
            try:
                self._socks5_server.start()
                self._bind_proxy_url = self._socks5_server.proxy_url
                logger.info("网卡绑定已启用: {} ({}) -> {}", bind_name, bind_ip, self._bind_proxy_url)
            except Exception as e:
                logger.error("SOCKS5 Forwarder 启动失败，关闭绑定功能: {}", e)
                self._socks5_server = None
                self._bind_proxy_url = None
        else:
            logger.error("绑定网卡 {} 不可用，回退系统路由", bind_name)
            self._bind_proxy_url = None
```

修改 `stop_monitoring()` / shutdown 逻辑：

```python
# 停止代理
if hasattr(self, '_socks5_server') and self._socks5_server:
    self._socks5_server.stop()
    self._socks5_server = None
```

- [ ] **Step 2: 在 check_once() 中检测 IP 变化**

在 `check_once()` 的网络检测前加入 IP 变化检查：

```python
def check_once(self) -> CheckOnceResult:
    # ... 现有 pause 检查 ...

    # IP 变化检测
    bind_name = self.config.monitor.bind_interface_name
    if bind_name and hasattr(self, '_interface_mgr'):
        new_ip = self._interface_mgr.resolve_ip(bind_name)
        old_ip = getattr(self, '_last_bind_ip', None)
        if new_ip != old_ip:
            self._last_bind_ip = new_ip
            if new_ip and hasattr(self, '_socks5_server') and self._socks5_server:
                self._socks5_server.update_bind_ip(new_ip)
                logger.info("DHCP IP 变化: {} -> {}，已更新代理", old_ip, new_ip)
            if old_ip:
                from app.network.probes import close_bound_client
                close_bound_client(old_ip)
```

- [ ] **Step 3: 在 runtime_config_to_worker_dict 中注入 bind_proxy**

修改 `app/services/login_orchestrator.py` 的 `runtime_config_to_worker_dict()`，新增可选参数：

```python
def runtime_config_to_worker_dict(config: RuntimeConfig, bind_proxy: str | None = None) -> dict:
    # ... 现有代码不变 ...
    d = { ... }  # 现有的 dict 构建

    # 注入 bind_proxy（如果有）
    if bind_proxy:
        d["browser_settings"]["bind_proxy"] = bind_proxy

    return d
```

调用方在 `LoginOrchestrator._dispatch()` 中（或 `ScheduleEngine._do_async_login()` 中）从 `NetworkMonitorCore.bind_proxy_url` 获取值并传入。

具体传递路径：
1. `NetworkMonitorCore` 暴露 `_bind_proxy_url` 属性
2. `ScheduleEngine` 持有 `NetworkMonitorCore` 引用
3. `ScheduleEngine` 调用 orchestrator 时传入 `bind_proxy=core._bind_proxy_url`
4. orchestrator 在构建 worker dict 时注入

- [ ] **Step 4: PlaywrightWorker 注入 proxy**

修改 `app/workers/playwright_worker.py` 的 `_build_context_options()`：

```python
if browser_settings.get("bind_proxy"):
    opts["proxy"] = {"server": browser_settings["bind_proxy"]}
```

设置变更检测：`ensure_browser()` 已有 `self._last_browser_settings == browser_settings` 比较逻辑（line 658-673）。当 `bind_proxy` 注入到 `browser_settings` dict 后，值变化会自动触发浏览器重启，无需额外代码。

- [ ] **Step 5: 运行集成测试**

Run: `pytest tests/test_services/ tests/test_integration/ -v`
Expected: 全部通过

- [ ] **Step 6: 提交**

```bash
git add app/services/monitor_service.py app/services/login_orchestrator.py app/workers/playwright_worker.py
git commit -m "feat: integrate SOCKS5 lifecycle and IP change detection into MonitorCore"
```

---

## Task 8: 前端 UI

**Files:**
- Modify: `frontend/partials/pages/settings/settings-monitor.html`
- Modify: `frontend/js/api-service.js`
- Modify: `frontend/js/app-options.js`
- Modify: `frontend/js/constants.js`（已在 Task 1 添加 DEFAULT_CONFIG）

- [ ] **Step 1: api-service.js 添加 fetchInterfaces**

在 `api-service.js` 的 `monitor` 分组中追加：

```js
monitor: {
    // ... 现有方法 ...
    fetchInterfaces() {
        return api.get('/api/network/interfaces');
    },
},
```

- [ ] **Step 2: app-options.js 添加数据和方法**

在 `data()` 中添加：

```js
networkInterfaces: [],
```

添加 computed：

```js
networkInterfaceOptions() {
    return this.networkInterfaces.map(iface => ({
        value: iface.id,
        label: `${iface.name} (${iface.ip} / 网关 ${iface.gateway || '无'})`,
    }));
},
selectedInterfaceDown() {
    const name = this.config.monitor.bind_interface_name;
    if (!name) return false;
    const iface = this.networkInterfaces.find(i => i.id === name);
    return iface ? !iface.is_up : true;
},
```

添加 method：

```js
async loadNetworkInterfaces() {
    try {
        const resp = await this.$apiService.network.fetchInterfaces();
        this.networkInterfaces = resp.data;
    } catch (e) {
        console.error('Failed to load network interfaces:', e);
    }
},
```

- [ ] **Step 3: settings-monitor.html 添加 UI**

在"屏蔽系统代理"开关的 `</div>` 之后、"登录请求超时"之前添加：

```html
<div class="form-group">
  <div class="field-label-row">
    <label for="settings-bind-interface">绑定网卡</label>
    <button type="button" class="icon-btn-refresh" @click="loadNetworkInterfaces" title="刷新网卡列表">
      <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2">
        <polyline points="23 4 23 10 17 10"/><polyline points="1 20 1 14 7 14"/>
        <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/>
      </svg>
    </button>
    <span class="field-help" tabindex="0" role="note"
      data-tip="指定网络检测和浏览器流量走哪张网卡。多网卡环境下避免检测走错网卡导致误判。留空则使用系统默认路由。">?</span>
  </div>
  <custom-select
    v-model="config.monitor.bind_interface_name"
    :options="networkInterfaceOptions"
    placeholder="自动（系统默认路由）"
  ></custom-select>
  <p v-if="selectedInterfaceDown" class="form-warning">
    所选网卡当前未连接，网络检测将回退到系统默认路由
  </p>
</div>
```

- [ ] **Step 4: tab 切换时加载网卡列表**

在 `app-options.js` 的 `watch` 中（如果已有 watch section 则追加，否则新增）添加对 `currentSettingsTab` 的监听：

```js
watch: {
    // ... 现有 watch ...
    currentSettingsTab(newTab) {
        if (newTab === 'monitor' && this.networkInterfaces.length === 0) {
            this.loadNetworkInterfaces();
        }
    },
},
```

同时在 `mounted()` 中不需要自动加载（仅切换到 monitor tab 时才需要）。

- [ ] **Step 5: 手动测试**

1. 启动应用
2. 打开设置 → 网络与监控
3. 确认下拉框显示网卡列表
4. 点击刷新按钮确认重新加载
5. 选择一个网卡，保存配置
6. 确认配置持久化和热加载正常

- [ ] **Step 6: 提交**

```bash
git add frontend/
git commit -m "feat: add NIC binding dropdown with refresh in monitor settings"
```

---

## Task 9: 端到端集成验证

**Files:** 无新增文件，运行全部测试

- [ ] **Step 1: 运行完整测试套件**

Run: `pytest tests/ -v --timeout=60`
Expected: 全部通过

- [ ] **Step 2: 手动验证双网卡场景**

1. 连接两张网卡（如网线 + WiFi）
2. 设置绑定其中一张
3. 断开绑定网卡 → 确认日志 ERROR + 回退到系统路由
4. 重新连接 → 确认自动恢复绑定
5. DHCP 换 IP → 确认代理和探测自动更新

- [ ] **Step 3: 验证 Chromium 流量确实走代理**

使用 PoC 脚本或在代理日志中确认 CONNECT 请求存在。

- [ ] **Step 4: 最终提交**

```bash
git add -A
git commit -m "feat: NIC binding feature - end-to-end integration"
```
