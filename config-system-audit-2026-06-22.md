## 配置系统全链路审查报告

**审查范围**: schemas → profile_service → config_service → engine → API → frontend → worker
**审查日期**: 2026-06-22
**审查文件数**: 12 个核心文件 + 前端 4 个文件

---

### P0 — 用户数据丢失 / 配置静默失效

#### 1. `proxy` 和 `app_port` 前端有 UI，后端 Schema 不存在

前端 `constants.js:153-154` 定义了 `proxy: ""` 和 `app_port: 50721`，`settings-system.html` 提供了完整的输入控件，用户在 UI 中填写后点击保存，FastAPI 的 `payload: RuntimeConfig` 参数走 Pydantic 反序列化，由于 `RuntimeConfig` 没有这两个字段且 `extra='ignore'`（默认），它们被**静默丢弃**。

每次保存都会丢失用户填写的代理和端口值。页面刷新后恢复为默认值。

`api/config.py:154-155` 的 FIELD_NAMES 中为这两个字段定义了中文标签 `"app_port": "网页端口"` 和 `"proxy": "网络代理"`，但它们永远无法匹配到——死代码。

**影响**: 用户在 UI 中配置的代理和端口完全不生效，且无任何错误提示。
**修复方向**: 要么在 `RuntimeConfig` 中添加这两个字段并接入消费端，要么移除前端 UI 控件并在文档中说明端口只能通过 `APP_PORT` 环境变量配置、代理通过系统代理设置。

#### 2. `get_config()` API 返回的 ISP 与登录实际使用的不一致

`api/config.py:84` 在 GET `/api/config` 中直接传递 `profile.carrier` 作为 ISP 值：

```python
"isp": str(profile.carrier or "无"),
```

而 `config_service.py:66-73` 的 `build_runtime_config()` 对 carrier 做了语义转换：

- `"自定义"` → `carrier_custom` 的实际值
- `"无"` → `""`
- 其他 → 直接传递

结果是 GET API 返回 `isp="自定义"` 或 `isp="无"`，但实际登录用的 `RuntimeConfig.credentials.isp` 是转换后的值。前端展示的 ISP 和 Worker 拿到的 ISP 不同。

**影响**: 当运营商选择"自定义"时，前端 ISP 字段显示的是字面量"自定义"而非用户填的 ISP 名称；选择"无"时显示"无"而非空串。虽然前端 `_saveCredentialsToProfile()` 有反向映射逻辑（config.js:142），但 GET 和实际运行之间的不一致可能导致调试困难和潜在的自动保存回写问题。

#### 3. `script_timeout` 缺失于前端 DEFAULT_CONFIG

后端 `MonitorSettings.script_timeout` 默认 60（schemas.py:266），在 `api/scripts.py:90` 和 `utils/login.py:247` 中被消费。但 `constants.js:103-121` 的 `DEFAULT_CONFIG.monitor` 没有这个字段。

`fetchConfig()` 用 `{...DEFAULT_CONFIG.monitor, ...(data.monitor || {})}` 合并，API 返回值会补上。但 `resetConfig()` 调用 `structuredClone(DEFAULT_CONFIG)` 后，`script_timeout` 消失。用户保存后发送的 payload 不含此字段，Pydantic 填默认值 60。

**影响**: 重置配置后，自定义的 `script_timeout` 被静默恢复为默认值。

---

### P1 — 功能缺陷 / 逻辑错误

#### 4. FIELD_NAMES 键名错误，变更日志显示为原始字段名

`api/config.py:144`: `"browser.channel"` → 应为 `"browser.browser_channel"`（schemas.py:231 字段名是 `browser_channel`）

`api/config.py:152`: `"logging.backend_log_level"` → 应为 `"logging.level"`（schemas.py:278 字段名是 `level`，旧名 `backend_log_level` 已废弃）

`api/config.py:153`: `"logging.frontend_log_level"` → 应为 `"logging.frontend_level"`（schemas.py:279）

**影响**: 用户修改浏览器类型、后端日志级别、前端日志级别时，配置变更日志显示原始字段名而非中文友好名称。

#### 5. `source_levels` 可能被主配置保存覆盖

`source_levels` 通过独立的 `PUT /api/config/source-level` 端点写入（`_persist_source_levels`），直接修改 `settings.json`。但主配置保存 `save_and_apply()` 会**整体替换** `data.config`，用 payload 构造新的 `RuntimeConfig`。

竞态场景：
1. 用户在日志面板设置某 source 的级别 → `_persist_source_levels` 写入磁盘 ✓
2. 用户在同一会话中修改其他设置 → 主配置保存
3. payload 的 `logging.source_levels` 来自 `fetchConfig()` 时的快照
4. 如果在步骤 1 之后没有重新 `fetchConfig()`，payload 中的 `source_levels` 是旧的
5. `_apply` 用 payload 覆盖 `data.config`，旧的 `source_levels` 写入磁盘

实际上这个窗口很窄（前端 `saveConfig()` 成功后会立即 `fetchConfig()` 刷新快照），但在快速操作时仍可能触发。

**修复方向**: `save_and_apply()` 的 `_apply` 函数可以 merge 而非 replace `source_levels`——从当前磁盘数据保留 `source_levels`，而非用 payload 的值。

#### 6. `_handle_login` 阻塞引擎线程 120-660 秒

`engine.py:414` 同步等待 `handle.result(timeout=worker_timeout + 60)`。在此期间引擎命令队列完全停滞：

- RELOAD 命令无法处理 → 配置重载延迟
- STOP 命令无法处理 → 用户点击"停止"无响应
- 网络检查无法执行 → 监控数据断档
- `reload_config()` 等待 10 秒超时 → 用户看到"配置重载失败"，但命令仍在队列中等待

**影响**: 在手动登录期间（最长 11 分钟），所有配置变更和引擎控制命令被阻塞。这是已知问题（MEMORY.md），但尚未修复。

**约束检查**: not-to-do.md 没有禁止修复此项。但 not-to-do.md 第 56 条禁止拆分 engine.py，所以修复必须在 engine.py 内部完成——可参考 `_do_async_login` 的非阻塞提交模式。

#### 7. Worker dict 遗漏 `carrier_custom`

`login_orchestrator.py:38-44` 的 `_runtime_config_to_worker_dict()` 从 `LoginCredentials` 提取了 4 个字段（username, password, auth_url, isp），遗漏了第 5 个字段 `carrier_custom`。

由于 `build_runtime_config()` 在 carrier="自定义" 时已将 `carrier_custom` 的值赋给 `isp`，所以 `carrier_custom` 本身的值在 Worker 端可以通过 `isp` 间接获取。但如果 Worker 将来需要区分"原生 ISP"和"自定义 ISP"，这个字段就不可用了。

**影响**: 当前不造成 bug，但破坏了 LoginCredentials → Worker 的字段完整性。

#### 8. 配置验证仅在外部 API 路径执行

`start_monitoring()` (engine.py:688) 调用 `ConfigValidator.validate_env_config()` 验证配置。但 `_handle_start()` 还被以下路径调用，均跳过验证：

- `_handle_reload()` (line 432) — 配置重载后重启监控
- `_do_network_check()` (line 267) — 自动切换方案后重启监控
- `_handle_apply_profile()` (line 457) — 手动切换方案后重启监控

**影响**: 如果重载后的配置无效（如所有网络检查被禁用、ping 目标格式错误），监控会以无效配置启动，可能导致误判网络状态。

#### 9. `get_config()` 返回的凭据永远为空，启动诊断失真

`engine.py:620` 的 `get_config()` 返回 `_ui_config` 的深拷贝。由于 `_ui_config = data.config`（settings.json 的全局配置段），而 `save_and_apply._apply()` 在保存时将 `credentials` 替换为空的 `LoginCredentials()`，所以 `_ui_config.credentials` 永远为空。

`application.py` 的启动诊断代码通过 `monitor_service.get_config()` 获取配置并输出 `cfg.credentials.username` 和 `cfg.credentials.password`——永远显示 "(空)"。

**影响**: 启动日志中的凭据诊断信息完全无意义，无法帮助排查"凭据是否正确加载"的问题。

---

### P2 — 设计缺陷 / 一致性问题

#### 10. `DEFAULT_PROFILE_SETTINGS` 默认值与后端不一致

`constants.js:237-238` 的新方案默认 `enable_tcp_check: true, enable_http_check: true`，而后端 `MonitorSettings` 默认为 `false, false`。

**影响**: 新建方案默认启用 TCP/HTTP 检测，但全局配置默认禁用。用户新建方案后如果不保存就直接运行，行为与预期不符。

#### 11. `active_task` 双源权威

`Profile.active_task`（schemas.py:176）和 `RuntimeConfig.active_task`（schemas.py:309）同时存在。`build_runtime_config()` 明确以 Profile 为准（line 85），`save_and_apply._apply()` 在保存时将全局 config 的 `active_task` 清空（line 102）。但语义上"哪个字段决定当前活跃任务"仍需查看代码才能确定。

#### 12. `startup_action` 类型未约束

`RuntimeConfig.startup_action` 类型为 `str = "none"`，而非 `StartupAction` 枚举。无效值如 `"bogus"` 只在 `AppConfig.from_runtime_config()` 转换时才失败，配置解析阶段不做校验。

#### 13. `PauseSettings` 缺少跨字段验证

`start_hour` 和 `end_hour` 各自约束 `[0, 23]`，但没有交叉验证。`start_hour == end_hour` 的语义不明确（全天暂停？永不暂停？），`start_hour > end_hour` 需要明确的跨夜语义。

#### 14. `BrowserChannel` 枚举是死代码

定义了 5 个值（PLAYWRIGHT, MSEdge, CHROME, FIREFOX, CUSTOM），但 `BrowserSettings.browser_channel` 类型为 `str`，枚举未被任何字段引用。零类型安全保障。

#### 15. `config_version` 不一致

`AppConfig.config_version` 默认 `2`，`ProfilesData.config_version` 默认 `3`。`AppConfig.from_runtime_config()` 未设置此字段，所以永远为 `2`。

#### 16. Worker dict 包含无关 UI 字段

`login_orchestrator.py:57-59` 向 Worker 传递 `minimize_to_tray`、`startup_action`、`autostart_lightweight`——这些是应用层 UI 关注点，Playwright Worker 进程不需要它们。不造成 bug，但增加了 IPC payload 噪音。

#### 17. `_reload_config_internal` 双重磁盘读取

`engine.py:629` 直接调用 `profile_service.load()`，然后 line 631 的 `load_active_config()` 内部又调用一次。由于 `ProfileService._load_unsafe()` 明确不缓存，每次重载会读两次磁盘。

**影响**: 性能微损（文件 <10KB），但逻辑上可以优化为单次读取后传递 data 对象。

#### 18. `LoggingSettings.level` 未做枚举校验

接受任意字符串。`LogEntry` DTO 有 `VALID_LOG_LEVELS` 校验，但配置模型没有。无效的日志级别（如 `"VERBOSE"`）在配置保存时不报错，运行时被静默忽略或回退。

---

### 约束交叉审查

| 发现项 | not-to-do.md 冲突? | 说明 |
|--------|-------------------|------|
| #1 proxy/app_port | 无冲突 | 新增 Schema 字段或移除 UI |
| #4 FIELD_NAMES 修正 | 无冲突 | 纯字符串修正 |
| #5 source_levels merge | 无直接冲突 | 第 45 条关于 `save_config_combined` 原子性约束说的是不同场景 |
| #6 engine 非阻塞 | 第 56 条禁止拆分 engine.py | 修复必须在 engine.py 内部完成 |
| #17 单次读取 | 第 33 条禁止给 `_load_unsafe` 加缓存 | 修复方向是传递 data 对象而非加缓存，不冲突 |

---

### 配置完整流转链路图

```
用户 UI 操作
    │
    ▼
frontend saveConfig() ──PUT /api/config──► payload: RuntimeConfig
    │                                          │
    │                                          ▼ (Pydantic 反序列化, extra='ignore')
    │                                     proxy/app_port 被丢弃 ← 【P0 #1】
    │                                          │
    │                                          ▼
    │                                     save_and_apply()
    │                                          │
    │                                     ┌────┴────┐
    │                                     │  _apply  │
    │                                     │  剥离     │
    │                                     │  credentials
    │                                     │  + active_task
    │                                     └────┬────┘
    │                                          │
    │                                     profile_service.update()
    │                                     (原子锁-加载-修改-保存)
    │                                          │
    │                                     settings.json ← 磁盘持久化
    │                                          │
    │                                     reload_fn() = engine.reload_config()
    │                                          │
    │                                     引擎命令队列 ──RELOAD──►
    │                                          │                  │
    │                                     [如果 login 正在进行]     │
    │                                     阻塞 120-660s ← 【P1 #6】│
    │                                                             ▼
    │                                     _reload_config_internal()
    │                                          │
    │                                     ┌────┴──────────────────┐
    │                                     │                       │
    │                               _ui_config              load_active_config()
    │                           (全局配置,空凭据)              │
    │                                                     build_runtime_config()
    │                                                        │
    │                                               Profile.carrier → ISP 转换
    │                                               Profile.password → 解密
    │                                               Profile.active_task
    │                                                        │
    │                                                  _runtime_config
    │                                               (完整合并,含凭据)
    │                                                        │
    │                                     ┌──────────────────┼──────────────────┐
    │                                     ▼                  ▼                  ▼
    │                              MonitorService      LoginOrchestrator     API GET
    │                              (config ref)        (config ref)       (get_config)
    │                                     │                  │                  │
    │                               所有子模型           to_worker_dict     深拷贝返回
    │                               正确传递               │             (凭据为空 ← 【P1 #9】)
    │                                                     │
    │                                              browser.model_dump() ← 包含 custom_browser_engine ✓
    │                                              pause.model_dump()
    │                                              monitor.model_dump()
    │                                              retry.model_dump()
    │                                              + 平铺字段
    │                                                     │
    │                                              carrier_custom 被丢弃 ← 【P1 #7】
    │                                              UI 字段被传递 ← 【P2 #16】
    │                                                     │
    │                                              Worker 进程启动
```

---

### 修复优先级建议

**第一批（P0，数据丢失）**:

1. `proxy` / `app_port`：在 `RuntimeConfig` 添加字段 + `resolve_port()` 读取 config + `repo_proxy` 读取 config；或者移除前端 UI 并加说明
2. `get_config()` ISP 映射：用 `build_runtime_config()` 同样的 carrier→ISP 逻辑替换 line 84 的直接传递
3. `script_timeout` 加入 `DEFAULT_CONFIG.monitor`

**第二批（P1，功能缺陷）**:

4. `FIELD_NAMES` 键名修正（3 处）
5. `save_and_apply._apply` 中 merge `source_levels` 而非覆盖
6. `_handle_login` 改为非阻塞提交 + 回调模式（在 engine.py 内部）
7. Worker dict 补全 `carrier_custom`
8. `_handle_start()` 统一增加配置验证（或提取验证为独立函数，所有入口调用）

**第三批（P2，设计改进）**:

9. 前端 `DEFAULT_PROFILE_SETTINGS` 默认值对齐后端
10. `startup_action` 类型改为 `StartupAction` 枚举
11. `PauseSettings` 增加交叉验证
12. `_reload_config_internal` 改为单次读取后传递 data
13. `BrowserChannel` 枚举接入 `browser_channel` 字段或删除
