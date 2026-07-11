# 前端 & Workers 代码审查报告

## 前端文件

### 1. `template-loader.js`

| # | 行号 | 严重程度 | 问题 | 修复建议 |
|---|------|----------|------|----------|
| 1 | L13 | 🔴高 | **XSS 风险**: `temp.innerHTML = html` 直接将远程获取的 HTML 写入 DOM，若模板源被篡改或中间人攻击，可注入恶意脚本 | 若模板来源可信（本地文件），当前风险可控；但建议对 `html` 做 CSP 白名单过滤，或使用 DOMPurify 清洗后再写入 |
| 2 | L36 | 🟡中 | **全局变量污染**: `window.loadFrontendPartials` 挂载到全局对象 | 已在 IIFE 内，污染范围有限；可改为 ES Module export，由 `app.js` import |

### 2. `app.js`

| # | 行号 | 严重程度 | 问题 | 修复建议 |
|---|------|----------|------|----------|
| 3 | L4 | 🟡中 | **全局变量依赖**: `window.Vue` 依赖全局 Vue 脚本先加载 | 当前是 Vue CDN 方案的正常用法，风险可接受 |
| 4 | L28 | 🟢低 | **CSS 注入**: `url(${bgUrl})` 中 `bgUrl` 已做 URL 协议校验（L24-27），安全 | 已有防护，无需修改 |

### 3. `js/constants.js`

| # | 行号 | 严重程度 | 问题 | 修复建议 |
|---|------|----------|------|----------|
| 5 | L33 | 🟢低 | **可变属性污染**: `config.__retryCount` 直接修改 axios config 对象 | axios 惯用模式，可接受 |

### 4. `js/app-options.js`

| # | 行号 | 严重程度 | 问题 | 修复建议 |
|---|------|----------|------|----------|
| 6 | L125 | 🟡中 | **性能隐患**: `JSON.stringify(this.config)` 在 computed 中每次渲染都序列化整个 config 对象进行 dirty 检查 | 对于当前配置规模可接受；若 config 增大，可用快照 hash 替代 |
| 7 | L308-312 | 🟢低 | **阻塞渲染**: `mounted()` 中调用 `init()` 是 async 但不 await，依赖 isLoading 状态管理 | Vue 3 惯用模式，可接受 |

### 5. `js/logger.js`

| # | 行号 | 严重程度 | 问题 | 修复建议 |
|---|------|----------|------|----------|
| 8 | L28 | 🟢低 | **异常吞没**: `catch (_) { /* ignore send errors */ }` WS 发送失败静默 | 日志发送失败合理静默，但可加 debug 级别日志便于排查 |
| 9 | L41-52 | 🟡中 | **批量发送无背压**: `_flushBuffer` 逐条发送，若缓冲区积压大量日志可能阻塞 UI 线程 | 当前 `WS_LOG_BUFFER_MAX=100` 限制合理，可接受 |

### 6. `js/methods/lifecycle.js`

| # | 行号 | 严重程度 | 问题 | 修复建议 |
|---|------|----------|------|----------|
| 10 | L318 | 🟢低 | **冗余初始化**: `(this.fetchStatusFailCount || 0) + 1`，`fetchStatusFailCount` 在 `dashboard.js` L8 已初始化为 0 | `|| 0` 冗余但无害，可简化 |
| 11 | L228-251 | 🟢低 | **JSON.parse 无 try-catch**: `JSON.parse(event.data)` 有 try-catch 包裹（L229），安全 | 已有防护 |
| 12 | L62-81 | 🟢低 | **事件监听器**: `ws.addEventListener('open'/'close', ..., { once: true })` 使用 `once` 自动清理，且 `cleanup` 函数手动移除 | 设计正确 |

### 7. `js/methods/ui.js`

| # | 行号 | 严重程度 | 问题 | 修复建议 |
|---|------|----------|------|----------|
| 13 | L313 | 🟡中 | **innerHTML 使用**: SVG 内容是硬编码常量字符串，非用户输入，XSS 风险极低 | 可改为 `createElementNS` 逐元素创建，但当前场景安全可接受 |
| 14 | L88-90 | 🟢低 | **事件监听器管理**: `toggleNotifications` 开关时添加/移除 `mousedown` 监听器，`beforeUnmount` 中也有兜底清理（app-options L339） | 设计正确 |

### 8. `js/methods/utils.js`

| # | 行号 | 严重程度 | 问题 | 修复建议 |
|---|------|----------|------|----------|
| 15 | L52-63 | 🟢低 | **临时 DOM 元素**: `pickFile` 创建临时 `<input>` 但未 append 到 DOM（仅 click），GC 会回收 | 设计正确 |
| 16 | L74-79 | 🟢低 | **Blob URL 泄漏**: `URL.revokeObjectURL` 在 1s 后调用，合理 | 无问题 |

### 9. `js/methods/appearance.js`

| # | 行号 | 严重程度 | 问题 | 修复建议 |
|---|------|----------|------|----------|
| 17 | L126-127 | 🟡中 | **事件监听器潜在泄漏**: `startLongPress` 在 `event.target` 上添加 `touchend`/`touchmove` 监听器，若触摸取消后元素被移除，监听器可能残留 | 建议用 `AbortController` 或在元素上存储引用以便清理 |

### 10. `js/methods/formatters.js`

| # | 行号 | 严重程度 | 问题 | 修复建议 |
|---|------|----------|------|----------|
| 18 | L24 | 🟢低 | **路径穿越防护**: `extractScreenshotUrl` 检查 `..` 和控制字符，安全 | 已有防护 |

### 11. `js/data/config.js`

| # | 行号 | 严重程度 | 问题 | 修复建议 |
|---|------|----------|------|----------|
| 19 | L4-15 | 🟡中 | **浅拷贝**: `cloneConfig` 仅展开一层，若嵌套对象（如 `ping_targets` 数组）被修改会污染 `DEFAULT_CONFIG` | 建议对数组/嵌套对象做深拷贝，或使用 `structuredClone` |

### 12. `js/data/appearance.js`

| # | 行号 | 严重程度 | 问题 | 修复建议 |
|---|------|----------|------|----------|
| 20 | L6-27 | 🟢低 | **localStorage 解析失败处理**: 已有 try-catch 并清除损坏数据 | 设计正确 |

### 13. `js/data/status.js`

| # | 行号 | 严重程度 | 问题 | 修复建议 |
|---|------|----------|------|----------|
| 21 | - | 🟢低 | 数据结构清晰，状态字段完整 | 无问题 |

### 14. `js/data/timers.js`

| # | 行号 | 严重程度 | 问题 | 修复建议 |
|---|------|----------|------|----------|
| 22 | - | 🟢低 | 定时器引用集中管理，`beforeUnmount` 中统一清理 | 设计正确 |

### 15. `js/data/websocket.js`

| # | 行号 | 严重程度 | 问题 | 修复建议 |
|---|------|----------|------|----------|
| 23 | - | 🟢低 | WebSocket 状态管理完整，含重试计数和销毁标志 | 无问题 |

---

## Workers 文件

### 16. `app/workers/playwright_worker.py`

| # | 行号 | 严重程度 | 问题 | 修复建议 |
|---|------|----------|------|----------|
| 24 | L97 | 🟢低 | **队列大小硬编码**: `asyncio.Queue(maxsize=50)` 无配置化 | 对当前使用场景足够 |
| 25 | L189-210 | 🟡中 | **stop() 中 loop 生命周期竞态**: `loop.call_soon_threadsafe` 可能在 loop 已关闭后抛 `RuntimeError`，已有 `try/except` 捕获 | 处理正确 |
| 26 | L310-313 | 🟡中 | **超时后命令残留**: `cmd.cancelled = True` 标记取消，但命令仍在队列中，`_dispatch` 会跳过执行，`response_event` 不会被 set | 超时后 `response_event.wait()` 已返回 False，等待方已放弃；`_dispatch` 跳过时不会 set event，但等待方已不关心。设计可接受 |
| 27 | L881-884 | 🟢低 | **异常回滚**: `_start_browser` 失败时调用 `_close_browser()` 清理资源 | 设计正确 |
| 28 | L1157-1168 | 🟡中 | **单例重建竞态**: `get_worker()` 双重检查锁定，但 `stop()` 调用和 `new_worker.start()` 之间若有异常，`_worker` 可能指向死亡实例 | 建议 `start()` 后检查 `is_alive()`，失败则置 `_worker = None` |
| 29 | L1195-1213 | 🟢低 | **孤儿进程清理**: `psutil.process_iter` 遍历所有进程，已有异常处理 | 设计正确 |

### 17. `app/workers/script_runner.py`

| # | 行号 | 严重程度 | 问题 | 修复建议 |
|---|------|----------|------|----------|
| 30 | L174-182 | 🟡中 | **临时文件清理**: `_content_temp_file` 创建 `delete=False` 的临时文件，`run()` 的 `finally` 块（L240-242）负责清理 | 设计正确，但若 `run()` 在 `temp_path` 赋值前异常退出，临时文件可能残留 |
| 31 | L240-242 | 🟢低 | **清理异常抑制**: `contextlib.suppress(OSError)` 忽略删除失败 | 合理，避免清理失败影响主流程 |
| 32 | L266-289 | 🟢低 | **最小化环境变量**: `_build_minimal_env` 仅保留必要变量，安全 | 设计正确 |

### 18. `app/workers/playwright_bootstrap.py`

| # | 行号 | 严重程度 | 问题 | 修复建议 |
|---|------|----------|------|----------|
| 33 | L134 | 🟢低 | **全局状态**: `_BOOTSTRAP_DONE`/`_BOOTSTRAP_SKIPPED` 模块级变量，已有 `_BOOTSTRAP_LOCK` 保护 | 设计正确 |
| 34 | L201-231 | 🟡中 | **下载失败循环**: 遍历候选下载源，任一成功即返回；全部失败返回 False | 逻辑正确，但 `_BOOTSTRAP_DONE = True` 后若完整性校验失败（L223），重置为 False，再次调用会重新进入整个流程（因为 `_BOOTSTRAP_SKIPPED` 也是 False），这是正确的重试行为 |

---

## 总结统计

| 严重程度 | 数量 | 说明 |
|----------|------|------|
| 🔴高 | 1 | `template-loader.js` innerHTML XSS 风险 |
| 🟡中 | 8 | 性能隐患、事件泄漏风险、浅拷贝、单例竞态等 |
| 🟢低 | 16 | 设计正确、已有防护、可接受的惯用模式 |

### 关键发现

1. **最高优先级**: `template-loader.js` L13 的 `innerHTML` 写入远程 HTML — 虽然模板源是本地服务器，但若部署到公网或遭受中间人攻击则有 XSS 风险，建议加 DOMPurify
2. **事件监听器管理**: 整体良好，`beforeUnmount` 有系统性清理，但 `appearance.js` 的 `startLongPress` 触摸事件绑定在 `event.target` 上存在边界情况泄漏风险
3. **数据克隆**: `config.js` 的 `cloneConfig` 浅拷贝可能污染默认配置常量
4. **Workers 资源管理**: Playwright Worker 的生命周期管理设计完善，有防御性重置、健康检查、强制清理机制，质量较高
5. **无未处理 Promise rejection**: 所有 async 方法都有 try-catch 或 `.catch()` 处理
6. **无回调地狱**: 使用 async/await 管理异步流程，结构清晰
