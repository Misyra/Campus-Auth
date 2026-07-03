# 网卡绑定功能设计

## 背景

当前网络检测的所有探测（TCP socket、HTTP 204、URL 内容校验）和浏览器流量均依赖操作系统路由表选择出口网卡，无法指定具体网卡。在双网卡环境（校园网 + 手机热点、校园网 + VPN）下容易出现：

- 校园网未认证，但探测走热点 → 误判为网络正常，不触发登录
- 校园网已认证，但探测走断网网卡 → 误判为网络断开，反复登录
- 浏览器与探测走不同网卡 → 登录成功但检测失败，状态不一致

## 设计目标

1. 探测与浏览器始终使用相同出口网卡
2. 默认行为完全兼容现有版本（空字符串 = 不绑定）
3. DHCP 环境自动适应 IP 变化
4. 多平台（Windows / Linux / macOS）
5. 零额外依赖
6. 浏览器层与网络层保持解耦

## 总体架构

```
              MonitorSettings.bind_interface_name
                             │
                             ▼
                   InterfaceManager
               （唯一网卡信息管理入口）
                             │
      ┌──────────────┬───────┴────────────────┐
      │              │                        │
      ▼              ▼                        ▼
 Network Probe   HTTP Client Pool      Socks5Server
      │              │                        │
      └──────────────┴────────┬───────────────┘
                              │
                              ▼
                     Playwright Worker
```

整个系统只有 `InterfaceManager` 能访问 `psutil.net_if_addrs()` / `psutil.net_if_stats()`。其它模块全部通过 InterfaceManager 获取网卡信息。

## 设计决策

| 项目 | 方案 | 理由 |
|------|------|------|
| 配置存储 | 网卡名 `bind_interface_name` | DHCP 下 IP 会变，名称相对稳定 |
| 默认值 | 空字符串（不绑定） | 不影响现有用户 |
| 浏览器绑定 | 本地 SOCKS5 Forwarder | Chromium 无原生 bind 参数 |
| SOCKS5 | 最小自研，仅 CONNECT + IPv4 + 域名 | 无合适的服务端库 |
| SOCKS5 认证 | 无（仅监听 127.0.0.1 + 随机端口） | Chromium 不支持 SOCKS5 auth，认证失败会静默直连 |
| Worker 解耦 | 仅接收 proxy_url 字符串 | 浏览器层不依赖监控层 |
| 并发上限 | 128 连接，daemon 线程 | 现代页面单页并发常超 64 |
| IP 更新 | InterfaceManager 单一缓存源 | 探测与代理共享，避免双路径状态不一致 |
| HTTP Client 池 | 按 source_ip 缓存，最多 4 个 | 超限自动关闭最旧 Client |
| 回退策略 | 网卡不可用 → ERROR 日志 → 回退系统路由 | 可用性优先 |
| UI | 下拉选择网卡 + 刷新按钮 | 应对热插拔 |

## PoC 验证（开发前必须完成）

在正式开发前，先实现一个最小 PoC，验证以下内容：

1. Chromium 配置 `socks5://127.0.0.1:PORT` 后，所有流量均经过本地 SOCKS5，而非直连
2. SOCKS5 服务端能够收到 CONNECT 请求
3. CONNECT 请求中包含 IPv4（ATYP=0x01）和 Domain（ATYP=0x03）
4. DNS 行为：Chromium 是本地解析还是交给 SOCKS5
5. `source_address=(bind_ip, 0)` 确实固定出口网卡
6. 浏览器关闭后所有连接能够正常释放
7. DHCP 更换 IP 后 `update_bind_ip()` 生效，新连接使用新 IP

PoC 验证通过后再开始完整实现。

---

## 第一部分：配置

`app/schemas.py` 的 `MonitorSettings` 新增：

```python
bind_interface_name: str = ""  # 空 = 不绑定（默认），非空 = 网卡名
```

保存网卡名（如"以太网"、"WLAN"），不保存 IP / GUID / MAC。

---

## 第二部分：InterfaceManager

新增 `app/network/interfaces.py`。职责：网卡枚举、网关获取、IP 解析、TTL 缓存、DHCP 更新检测。

整个项目中只有此模块调用 `psutil.net_if_addrs()` 和 `psutil.net_if_stats()`。

### 数据模型

```python
@dataclass(frozen=True, slots=True)
class InterfaceInfo:
    name: str
    ip: str           # IPv4，空串表示无 IPv4
    gateway: str      # 默认网关，空串表示无
    is_up: bool
```

API 返回、Probe、Proxy、UI 统一使用此模型。

### API

```python
class InterfaceManager:
    def list_interfaces() -> list[InterfaceInfo]: ...
    def get_interface(name: str) -> InterfaceInfo | None: ...
    def resolve_ip(name: str) -> str | None: ...
    def is_interface_up(name: str) -> bool: ...
```

缓存 TTL 30 秒，缓存对象为 `InterfaceInfo`（而非单独缓存 IP），后续扩展字段零成本。

### 网卡过滤

排除：docker、veth、br-、vmnet、vboxnet、virbr、tap- 前缀 + Loopback + 无 IPv4 的接口。

**不排除** `vEthernet`——psutil 不提供跨平台接口类型字段，无法可靠区分 Hyper-V / Docker Desktop / WSL。Docker Desktop 的 `vEthernet (DockerNAT)` 可能出现在列表中，属已知限制。

### 网关解析

需扩展现有 `detect.py`（当前只返回默认网关）：

- Windows：`route print 0.0.0.0`，接口列给出的是接口 IP（非名称），需先用 psutil 获取各网卡 IPv4 做 IP→名称映射
- Linux：解析 `/proc/net/route` 按接口名索引
- macOS：`route -n get default` 只返回默认路由，改用 `netstat -rn` 解析多条

---

## 第三部分：网卡枚举 API

新增 `GET /api/network/interfaces`，放在 `app/api/monitor.py`。

返回格式：

```json
[
  {
    "id": "以太网",
    "name": "以太网",
    "ip": "192.168.1.12",
    "gateway": "192.168.1.1",
    "is_up": true
  }
]
```

`id` 当前等于 `name`，为未来切换到 GUID 预留。前端使用 `id` 作为 value，`name + ip + gateway` 作为显示标签。

---

## 第四部分：探测绑定

### TCP

`is_network_available_socket` 新增 `source_ip` 参数：

```python
socket.create_connection(target, timeout, source_address=(source_ip, 0))
```

### HTTP

```python
httpx.Client(
    transport=httpx.HTTPTransport(local_address=source_ip),
    verify=False, follow_redirects=True, ...
)
```

按 `source_ip` 缓存 Client，最多 4 个，超限自动关闭最旧的。IP 变化时主动关闭旧 IP 对应的 Client。

### URL Probe

与 HTTP 共用 Client。

### Auth URL

同样使用 `source_address` 绑定。

### 物理检查

`is_local_network_connected` 新增 `interface_name` 参数：

```python
def is_local_network_connected(interface_name: str = "") -> bool:
    if interface_name:
        if InterfaceManager.is_interface_up(interface_name):
            return True
        # 绑定网卡不可用 → 回退到"任一物理网卡 up"的原逻辑
        logger.error("绑定网卡 {} 不可用，回退检查物理网络", interface_name)
    # 原逻辑
```

绑定网卡消失时不直接返回 False，避免误报断网。

---

## 第五部分：回退策略

`InterfaceManager.resolve_ip()` 返回 `None` 时：

1. 日志 ERROR："绑定网卡 XXX 不可用，回退系统路由"
2. 所有 Probe 以 `source_ip=None` 调用（当前默认行为）
3. `NetworkCheckResult` 增加 `warning` 字段，供前端展示

启动时校验 `bind_interface_name`，解析失败以 ERROR 级别输出。不做硬校验拒绝保存（网卡可能临时不可用）。

---

## 第六部分：SOCKS5 Forwarder

新增 `app/network/proxy.py`。仅功能启用时动态导入，不启用时零开销。

### 为什么自研

调研了现有 Python 库：`python-socks` 纯客户端（无 server API），`pproxy` 不支持 `source_address` 绑定。无同时满足两个需求的维护中库。协议在限定范围内可控，预计 ~150 行。

### 不做认证

Chromium 不支持 SOCKS5 USERNAME/PASSWORD 认证——认证失败后**静默回退直连**，这是本功能要避免的最坏场景。安全依赖：仅监听 `127.0.0.1` + OS 随机端口。

### Socks5Server

```python
class Socks5Server:
    """最小 SOCKS5 服务端：仅 CONNECT，IPv4 + 域名，无认证。"""

    def __init__(self, bind_ip: str): ...

    @property
    def proxy_url(self) -> str:
        """返回 socks5://127.0.0.1:{port}"""

    def start(self) -> None: ...
    def stop(self) -> None: ...
    def update_bind_ip(self, ip: str) -> None: ...
```

实现要点：

- 绑定 `127.0.0.1:0`，OS 自动分配端口
- accept 循环用 `threading.Event` 控制退出，daemon 线程
- 每连接起转发线程（daemon），信号量控制最大并发 `MAX_CONNECTIONS = 128`
- SOCKS5 握手：仅接受 NO AUTH（0x00）
- CONNECT：仅支持 ATYP 0x01（IPv4）和 0x03（域名），拒绝 0x04（IPv6）
- 出站：`socket.create_connection(target, source_address=(self._bind_ip, 0))`，`_bind_ip` 加锁读写
- 双向转发：`selectors.DefaultSelector`，64KB buffer
- 半关闭：一端关闭后继续转发另一端直到 EOF 或超时（5 秒）
- 不支持：UDP ASSOCIATE、BIND、IPv6、SOCKS4

### IP 更新

Proxy 自身**禁止**直接调用 psutil。每次网络检测时：

```
InterfaceManager.resolve_ip()
  → IP 变化
  → Proxy.update_bind_ip()
  → 关闭旧 HTTP Client
```

### 生命周期

跟随 `NetworkMonitorCore`：

- `init_monitoring()`：若 `bind_interface_name` 非空，解析 IP 并启动代理
- `shutdown()`：停止代理（Event + 关 socket + join）
- 浏览器重启不需要重启代理

启动时代理创建失败 → ERROR → 关闭绑定功能 → 继续运行，不影响软件启动。

### 健壮性

- 网卡消失 → 出站 socket 异常 → catch 关闭该连接，代理继续运行
- DHCP 换 IP → MonitorCore 检测 → `update_bind_ip()` → 后续出站用新 IP
- 代理线程异常退出 → ERROR，前端通过下一次网络检测展示回退警告

---

## 第七部分：Playwright 集成

Worker 仅知道 `proxy_url` 字符串，不知道 `Socks5Server` 对象。

```python
# PlaywrightWorker._build_context_options()
if browser_settings.get("bind_proxy"):
    opts["proxy"] = {"server": browser_settings["bind_proxy"]}
```

传递链路：

```
MonitorSettings.bind_interface_name
  → NetworkMonitorCore 启动代理
  → runtime_config_to_worker_dict() 注入 bind_proxy = "socks5://127.0.0.1:{port}"
  → PlaywrightWorker._build_context_options()
  → browser.new_context(**opts)
```

不启用绑定时不注入 `bind_proxy`，Playwright 行为完全不变。

`bind_proxy` 加入 `_settings_changed` 比较范围，切换网卡后触发浏览器重启。

---

## 第八部分：前端 UI

在 `settings-monitor.html` 的"检测与重试"卡片中，"屏蔽系统代理"开关下方新增：

```html
<div class="form-group">
  <div class="field-label-row">
    <label>绑定网卡</label>
    <span class="field-help" tabindex="0" role="note"
      data-tip="指定网络检测和浏览器流量走哪张网卡。多网卡环境下避免检测走错网卡导致误判。留空则使用系统默认路由。">?</span>
  </div>
  <custom-select
    v-model="config.monitor.bind_interface_name"
    :options="networkInterfaceOptions"
    placeholder="自动（系统默认路由）"
  ></custom-select>
</div>
```

- 数据来源：`GET /api/network/interfaces`，在"网络与监控" tab 激活时调用
- 下拉框旁加刷新按钮，应对热插拔
- 选项格式：`{ id: "以太网", label: "以太网 (192.168.1.5 / 网关 192.168.1.1)" }`
- `constants.js` 的 `DEFAULT_CONFIG.monitor` 加 `bind_interface_name: ""`
- 所选网卡 `is_up: false` 时显示警告提示

---

## 第九部分：启动流程

```
读取配置
  → InterfaceManager 初始化
  → resolve_ip()
  → 有 IP → 启动 SOCKS5 Forwarder + 创建绑定 HTTP Client
  → 无 IP → ERROR + 关闭绑定功能
  → 启动 Monitor
```

代理启动失败不影响软件启动。

---

## 第十部分：运行流程

```
check_once()
  → InterfaceManager.resolve_ip()
  → IP 变化？
    → 是 → Proxy.update_bind_ip() + 关闭旧 HTTP Client
  → Probe（source_ip 绑定）
  → 需要登录？
    → Playwright（通过 SOCKS5 Forwarder）
    → 绑定出口网卡
```

---

## 已知限制

1. **Windows USB 网卡改名**：插拔后可能"以太网 2"→"以太网 3"，`bind_interface_name` 失效。可用 GUID 持久化但跨平台复杂，当前不做。用户需重新选择。
2. **Docker Desktop vEthernet 误显示**：`vEthernet (DockerNAT)` 有 IPv4 且非 Loopback，会出现在列表。用户根据 IP 段（通常 172.x.x.x）自行识别。
3. **协议限制**：不支持 IPv6、SOCKS4、UDP ASSOCIATE、BIND。

## 受影响文件清单

| 文件 | 变更类型 | 说明 |
|------|----------|------|
| `app/schemas.py` | 修改 | MonitorSettings 加 bind_interface_name |
| `app/network/interfaces.py` | **新增** | InterfaceManager：网卡枚举、IP 解析、TTL 缓存 |
| `app/network/probes.py` | 修改 | 探测函数加 source_ip，物理检查加回退逻辑 |
| `app/network/proxy.py` | **新增** | SOCKS5 Forwarder |
| `app/network/detect.py` | 修改 | 扩展网关解析为按网卡索引 |
| `app/api/monitor.py` | 修改 | GET /api/network/interfaces |
| `app/services/monitor_service.py` | 修改 | Proxy 生命周期、IP 变化检测 |
| `app/services/login_orchestrator.py` | 修改 | worker dict 注入 bind_proxy |
| `app/workers/playwright_worker.py` | 修改 | context options 注入 proxy，settings_changed |
| `frontend/partials/pages/settings/settings-monitor.html` | 修改 | 网卡选择下拉框 + 刷新按钮 |
| `frontend/js/api-service.js` | 修改 | fetchInterfaces 方法 |
| `frontend/js/constants.js` | 修改 | DEFAULT_CONFIG 加 bind_interface_name |
| `frontend/js/app-options.js` | 修改 | networkInterfaceOptions + 刷新逻辑 |
