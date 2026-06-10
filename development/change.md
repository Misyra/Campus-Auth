# 修改日志

本文档记录项目的所有变更，包括文档更新、代码修改、配置调整等。


## 2026-06-09

### refactor: 合并剩余重复测试文件（network/backend/api）

- 删除 `tests/test_decision.py`、`tests/test_network_probes_utils.py`（已被 `test_network_probes.py` 覆盖）
- 合并 `tests/test_profile_service.py` + `tests/test_task_service_logic.py` → `tests/test_backend_services.py`
- 删除 `tests/test_api_tools.py`
- 重命名 `tests/test_api_logfiles.py` → `tests/test_api_logfiles_routes.py`
- 合并 `tests/test_api.py` → `tests/test_routers.py`（健康检查、初始化状态、版本比较）
- 测试文件数：35 → 31

### fix: 修复 Playwright 关闭报错

- `playwright_worker.py`：修复 `_cleanup_browser` 中对 `AsyncPlaywright` 调用不存在的 `close()` 方法，改为正确的 `stop()`

### refactor: 全项目文案审计与优化

对前端 UI、后端消息、项目文档进行全面文案审计，修复描述不清、过于复杂、信息缺失三类问题约 50 处。

**后端消息优化（app/）：**
- `schemas.py`：6 处描述优化（API 请求超时→等待超时、反检测脚本→自动操作特征、TCP/HTTP 检测区分、Web 控制台→网页界面、Chromium→浏览器、JSON 格式错误→格式不正确）
- `api/system.py`：服务器关闭消息补充操作指引
- `api/backup.py`：3 处错误消息优化（settings.json→配置文件、文件名格式、异常信息保留）
- `api/tools.py`：5 处错误消息优化（录制器脚本缺失、文档缺失、下载失败、非图片格式、非法文件名）
- `api/ocr.py`：uv 安装提示补充安装链接
- `api/scheduled_tasks.py`：4 处验证消息优化（hour/minute→小时/分钟、timeout 范围说明）
- `services/task.py`：2 处优化（任务ID示例、步骤缺失引导）
- `services/autostart.py`：平台不支持提示补充操作建议
- `services/scheduler.py`：4 处优化（保存/删除失败、任务类型、Playwright 依赖）
- `services/config.py`：JSON 格式错误提示优化
- `utils/config.py`：86400 秒→24 小时
- `utils/crypto.py`：2 处优化（密钥变更提示、加密库安装指引）
- `utils/login.py`：活动任务→可执行任务
- `network/decision.py`：检测未启用提示补充操作路径
- `tasks/validator.py`：2 处优化（正则表达式→自然语言、eval 字段提示）
- `core/monitor_core.py`：3 处优化（登录失败补充检查建议、密码解密失败补充原因）

**前端 UI 文案优化（frontend/）：**
- `profiles.html`：登录前检测→检查认证页面是否可达、补充检测目标格式说明、禁用同源策略/反检测模式补充 tooltip
- `settings-browser.html`：纯净模式提示文案优化
- `settings-tasks.html`：任务录制器说明简化、文档链接改为在线链接
- `settings-monitor.html`：网址响应检测 tooltip 补充区别说明
- `settings-account.html`：认证地址 tooltip 简化、运营商 tooltip 优化
- `settings-system.html`：静默启动 tooltip 措辞优化
- `about.html`：卸载描述优化、补充项目路径指引
- `wizard.html`：监控设置描述补充、暂停时段说明优化
- `appearance.html`：毛玻璃效果说明、随机壁纸说明优化
- `scripts.html`：stdout 说明补充、Shell 平台默认行为说明
- `scheduled_tasks.html`：历史按钮→查看历史
- `methods/profiles.js`：切换自动切换失败→自动切换设置失败

**文档优化（docs/）：**
- `update_log.md`：修复 doc/→docs/ 路径笔误
- `task-writing-guide.md`：废弃字段加删除线、自动降级描述简化、变量解析优先级重写、成功判断补充超时说明、FAQ 变量设置指引
- `task-manual.md`：环境变量覆盖顺序改为表格、LOGIN_URL 补充说明、网络检测兜底补充超时
- `custom-script-guide.md`：Python 运行器示例修正为 PowerShell、binary_path 说明优化、FAQ 补充 Campus-Auth 变量说明、超时设置位置说明

**测试同步更新（tests/）：**
- `test_config_schemas.py`、`test_config_service_logic.py`、`test_config_validator.py`、`test_task_executor.py`、`test_task_validator.py`：同步更新断言匹配文案

### refactor: 日志系统全面优化

**后端日志级别调整：**
- `app/network/decision.py`：网络检测周期日志（开始/完成）从 INFO 降为 DEBUG，减少 ~90% 常规日志量
- `app/services/monitor.py`：服务层"收到请求"日志（启停监控、手动登录、网络测试）从 INFO 降为 DEBUG，消除三层重复
- `app/application.py`：启动时 settings.json 文件元数据日志从 INFO 降为 DEBUG
- `app/tasks/step_handlers.py`：`[select]` 可用选项列表、`[click_select]` 参数详情从 INFO 降为 DEBUG
- `app/services/autostart.py`：12 处中间步骤日志（文件路径、写入确认等）从 INFO 降为 DEBUG

**日志级别修正：**
- `app/workers/playwright_worker.py`：强制清理浏览器资源从 INFO 改为 WARNING；事件循环启动超时补充超时值；队列已满补充容量信息
- `app/workers/script_runner.py`：脚本 stderr 输出从 INFO 改为 WARNING

**模糊日志补充上下文：**
- `app/services/login_history.py`：4 条"失败"日志补充文件路径上下文
- `app/services/scheduler.py`：3 条模糊日志补充任务名/用途说明

**格式与风格统一：**
- `app/tasks/step_handlers.py`：`%s`/`%d` 旧式格式统一为 `{}` loguru 风格；`[click_select]` 跳过条件、`[wait]`/`[wait_url]`/`[sleep]` 参数日志从 INFO 降为 DEBUG
- `app/tasks/variable_resolver.py`：`[VariableResolver]` 前缀统一为 `[var]`
- `app/services/task.py`：唯一一条英文日志 `"Loading task"` 改为中文 `"加载任务"`
- `app/services/config.py`：运行时配置日志字段标签 `user`/`url` 改为 `用户`/`认证地址`
- `app/services/debug.py`：logger 变量名 `api_logger` 改为 `debug_logger`（非 API 路由模块）

**source 参数补全：**
- `app/schemas.py`、`app/utils/browser.py`、`app/utils/login.py`：3 个省略 source 的 logger 补充显式 `source="backend"`

**前端修复：**
- `frontend/partials/pages/dashboard.html`：`v-for` key 加入 index，防止相同时间戳+消息的条目消失
- `frontend/js/methods/status.js`：初始加载日志条目数从硬编码 250 改为 `LIMITS.LOG_MAX_ENTRIES`（100），与 WebSocket 追加上限一致
- `frontend/js/app-options.js`：日志筛选下拉框补充 `CRITICAL` 级别选项
- `frontend/js/methods/logfiles.js` + `frontend/styles/pages/logfiles.css`：CSS 类名统一为与 Dashboard 一致的 `error`/`warning`/`debug` 裸类名

### refactor: 后端 Portal → url_check/网址响应 全面重命名

- `app/schemas.py`：`portal_check_urls` → `url_check_urls`，描述改为"网址响应检测地址"
- `app/utils/network_helpers.py`：`parse_portal_checks()` → `parse_url_checks()`
- `app/network/probes.py`：`is_network_available_portal()` → `is_network_available_url()`，参数 `portal_checks` → `url_checks`，日志消息改为"网址响应检测"
- `app/network/decision.py`：全部 portal 相关变量/参数/日志重命名（`enable_portal` → `enable_url`、`portal_ok` → `url_ok` 等）
- `app/services/config.py`：配置键 `portal_check_urls` → `url_check_urls`，导入 `parse_url_checks`
- `app/services/monitor.py`：`portal_checks` → `url_checks`，模式描述 "Portal" → "网址响应"
- `app/core/monitor_core.py`：`portal_checks` → `url_checks`，模式摘要 `Portal(N)` → `网址响应(N)`
- `app/tasks/executor.py`：`parse_portal_checks` → `parse_url_checks`，`portal_checks` → `url_checks`
- `app/utils/config_helpers.py`：`PROFILE_FIELDS` 中 `portal_check_urls` → `url_check_urls`
- 测试文件同步更新（test_backend_services、test_decision、test_network_probes）
- 保留 `PORTAL_WAIT_AFTER_LOGIN` 常量和 `detectportal.firefox.com` 实际检测 URL 不变
- 全部 1897 个测试通过

### fix: logfiles 正则支持点号和连字符，匹配 name 字段

- `app/api/logfiles.py`：`_LOG_LINE_PATTERN` 正则的 source 和 name 匹配模式从 `\w+` / `[\w.]+` 改为 `[\w.-]+`，支持 `monitor.core`、`step-handler` 等含点号或连字符的名称
- 注释格式统一为 `[source][name]`
- 测试验证：32 个 logfiles 测试全部通过

### fix: NetworkMonitorCore source 从 monitor.core 改为 network + name monitor_core

- `app/core/monitor_core.py`：logger 初始化改为 `get_logger("monitor_core", source="network")`；`log_message` 中 `self.log_callback` 调用从位置参数 `"monitor.core"` 改为关键字参数 `source="network", name="monitor_core"`
- 原因：`"monitor.core"` 不是合法的 source 类别，点号导致 CSS 类名 `source-monitor.core` 无效，前端显示异常
- `tests/test_monitor_core_logic.py`：更新 `test_uses_callback_when_set` 断言匹配新的关键字参数签名
- 全部 1897 个测试通过

### refactor: LogEntry schema 字段 module → name

- `app/schemas.py`：LogEntry 模型中 `module: str = ""` 改为 `name: str = ""`，与 DashboardSink 和 loguru 内部命名保持一致
- 测试验证：5 个 LogEntry 相关测试全部通过

### refactor: record_log 解耦 name 和 source

- `app/services/monitor.py`：`record_log` 方法新增 `name` 参数（默认 `"monitor_service"`），将 `get_logger(source, source)` 改为 `get_logger(name, source)`，name（模块标识）和 source（日志类别）不再共用同一值
- `tests/test_monitor_service.py`：将两处非法 `source="test"` 改为 `source="backend"`，符合 VALID_SOURCES 校验
- 测试验证：31 个 monitor service 测试全部通过

### fix: get_logger 添加 source 校验，非法值降级为 backend

- `app/utils/logging.py`：添加 `VALID_SOURCES` 常量，`get_logger` 中校验 source 参数，非法值自动降级为 "backend"
- `tests/test_utils.py`：测试用例中的大写 source 值（FRONTEND/BACKEND）改为合法小写值

### fix: 修复前端日志模块名一直显示 "record" 的问题

- `app/services/monitor.py`：`record_log` 方法中 `get_logger("record", source)` 改为 `get_logger(source, source)`
- 原因：logger 名称 "record" 无实际意义，会作为 `name` 字段显示在前端日志中
- 修改后：模块名显示为 source 值（backend / network / monitor.core 等），与其他模块命名规范一致

### refactor: DashboardSink entry 字段 module → name

- `app/utils/logging.py`：DashboardSink.write 的 entry dict 中 `"module"` 改为 `"name"`，与 loguru 内部 `record["name"]` 和 LogLine 模型保持一致
- `tests/test_logging_utils.py`：断言 `entry["module"]` 改为 `entry["name"]`

### docs: 代码深度重审 v2 — 发现 v1 修复遗漏和新增问题

- `docs/code-audit-2026-06-09-v2.md`：第二轮深化审计报告
- 方法论：方案 A（深化原 7 模块）+ 五道关检查（入口边界、异常路径、调用链、状态机、修复复查）
- 发现 4 个严重问题：executor.py timeout=0 同类残留 2 处、monitor_core stop 信号忽略、debug 页面重建丢失 stealth、block_proxy null 值反转
- 发现 10 个中等问题：异常日志丢堆栈、JSON null→TypeError、JSON 序列化异常、execute_remaining 负索引等
- 发现 11 个低优问题：OCR 实例泄漏、validator 类型检查、ntpath 跨平台等
- 复查确认 v1 修复的 3 处 `or` 模式只修了 `__init__` 未修 `execute` 和 `_execute_step`

### feat: 自定义下拉选择组件 CustomSelect — 全量替换原生 select

- `frontend/js/components.js`：新增 `CustomSelect` 组件（单选、键盘导航 ↑↓/Enter/Escape、点击外部关闭、入场动画）
- `frontend/js/app-options.js`：新增 `carrierOptions`、`logLevelOptions`、`logSourceOptions`、`scheduledTaskTypeOptions` 静态选项列表 + `taskOptions`、`scriptTargetOptions`、`browserTargetOptions`、`shellPathOptions`、`binaryOptions`、`logFileOptions` 动态 computed 属性
- `frontend/app.js`：注册 `custom-select` 全局组件
- `frontend/styles/components.css`：新增 `.custom-select` 完整样式（trigger、arrow、dropdown、option、compact/logfiles 变体）
- 全量替换 8 个 HTML 模板中的 17 个原生 `<select>` 为 `<custom-select>`
- 清理不再使用的 `.log-filter-select` 和 `.logfiles-select` CSS 类

### style: 统一 select 下拉选择样式 — 自定义箭头 + hover/focus + 深色弹出菜单

- `frontend/styles/base.css`：`.log-filter-select` 添加 `appearance: none`、自定义 SVG 箭头、`color-scheme: dark`、hover/focus 效果
- `frontend/styles/pages/logfiles.css`：`.logfiles-select` 同上处理
- 所有 select 元素现在风格一致：深色背景、灰色 chevron 箭头、聚焦时青色高亮、原生弹出菜单跟随深色主题

### fix: 全面代码审查修复 — 内存安全、正确性、性能、前端

基于 `docs/code-audit-2026-06-09.md` 审查报告，修复以下问题：

**内存安全**
- `app/api/tools.py`：upload_background 和 fetch_background_url 改为流式下载，避免超大文件耗尽内存

**正确性**
- `app/tasks/executor.py`：`default_timeout or 10000` 改为 `is not None` 判断，修复 timeout=0 被忽略
- `app/tasks/step_handlers.py`：`step.description.lower()` 增加 None 值防护
- `app/tasks/validator.py`：空步骤列表 `[]` 不再被误判为缺失；非 dict 步骤输入增加类型检查
- `app/tasks/models.py`：`TaskConfig.from_dict` 过滤非 dict 步骤元素
- `app/tasks/variable_resolver.py`：None 值解析为空字符串而非 "null"
- `app/api/scheduled_tasks.py`：hour/minute 增加 0-23/0-59 范围校验；timeout 增加 ValueError 捕获
- `app/services/monitor.py`：`wait_for_login_recovery` 增加 Event 未 set 时的提前返回；`_queue_consumer` finally 块统一 set response_event；`_handle_stop` 简化等待逻辑
- `app/services/scheduler.py`：`_check_and_execute` 记录已触发分钟，防止同一分钟内重复触发
- `app/services/debug.py`：调试截图使用独立子目录 `temp/debug/`，避免清理时影响其他服务
- `app/utils/file_helpers.py`：`atomic_write` 参数类型改为 `str | Path`，内部统一转换
- `app/application.py`：`_resolve_port` 重命名为 `resolve_port`，消除跨模块私有函数导入

**性能**
- `app/api/logfiles.py`：大日志文件（>50MB）只读取末尾部分
- `app/services/login_history.py`：大历史文件（>5MB）只读取末尾部分
- `app/utils/logging.py`：`broadcast_queue.append` 移入锁保护

**前端**
- `frontend/app.js`：移除 `applyAppearanceEarly` 中的 zoom 设置（Vue 挂载前不可靠）
- `frontend/js/methods/ui.js`：`removeCustomVar` 改用整体替换策略，与 `updateCustomVarKey` 一致
- `frontend/js/app-options.js`：`filteredLogs` 三次 filter 合并为一次遍历
- `frontend/styles/components.css`：通知下拉菜单改为 `position: absolute`，修复滚动后脱离按钮
- `app/utils/config.py`：`validate_gui_config` 接受 `int | str` 类型的 check_interval

**测试更新**
- 更新 variable_resolver、validator、debug_session 相关测试以匹配新行为

---

### feat: dashboard 实时日志增加来源筛选 + 级别/来源标签

- `frontend/js/data/dashboard.js`：`logFilter` 新增 `source` 字段
- `frontend/js/app-options.js`：`filteredLogs` computed 增加 source 过滤逻辑
- `frontend/partials/pages/dashboard.html`：日志工具栏新增来源筛选 chips，日志条目用 `log-level-badge` + `log-source-badge` 替代原来的 `formatLogMeta` 文本
- `frontend/styles/pages/dashboard.css`：新增 `.source-chips` 样式

### feat: 重写日志文件查看器 — 来源筛选 + 级别/来源标签 + 视觉优化

- `frontend/js/data/logfiles.js`：`logViewer` 新增 `source` 字段
- `frontend/js/methods/logfiles.js`：导入 `LOG_SOURCES`，`fetchLogFileContent` 增加 source 参数传递，新增 `getSourceLabel`、`getSourceColor` 方法
- `frontend/partials/pages/logfiles.html`：日志工具栏新增来源筛选 chips，日志条目用 badge 替代原来的 `[LEVEL] [logger]` 文本，`line.logger` → `line.name`
- `frontend/styles/pages/logfiles.css`：新增 `.source-chip` 样式
- `frontend/styles/base.css`：新增 `.log-level-badge`、`.log-source-badge` 全局样式（dashboard 和 logfiles 共享）

### feat: 新增 VirtualScroller 虚拟滚动组件

- `frontend/js/virtual-scroller.js`（新建）：零依赖虚拟滚动组件，支持 `setItems`、`appendItems`、`scrollToBottom`、`destroy`，使用 requestAnimationFrame + DocumentFragment 优化渲染

### refactor: 前端新增 LOG_SOURCES 常量 + formatLogMeta 适配

- `frontend/js/constants.js`：新增 `LOG_SOURCES` 常量（backend/network/task/frontend/debug，含 label 和 color）
- `frontend/js/methods/formatters.js`：导入 `LOG_SOURCES`，`formatLogMeta` 默认 source 从 `monitor` 改为 `backend`，新增 `getSourceLabel` 方法

### refactor: logfiles API 响应增加 source 字段 + source 查询参数

- `app/api/logfiles.py`：`LogLine` 模型 `side` → `source`、`logger` → `name`；新增 `_VALID_SOURCES` 集合；`_parse_log_line` 使用新字段名；`get_log_file_content` 新增 `source` 查询参数和来源过滤；搜索范围扩展到 `line.name` 和 `line.source`
- `tests/test_api_logfiles.py`：更新字段断言（`side` → `source`、`logger` → `name`），所有 `get_log_file_content` 调用补充 `source=""` 参数

### refactor: MonitorService record_log 委托 loguru + 修复 filter 条件

- `app/container.py`：filter 从 `side == "BACKEND"` 修复为 `source != "frontend"`；注入整个 `DashboardSink` 实例到 `monitor_service._dashboard_sink`
- `app/utils/logging.py`：`add_file_handler` filter 从 `side == "BACKEND"` 修复为 `source != "frontend"`
- `app/services/monitor.py`：`record_log()` 改为委托 loguru（移除手动维护 `_logs` 和 `_ws_broadcast_queue`）；`list_logs()` 从 `DashboardSink.buffer` 读取；新增 `ws_broadcast_queue` property 从 `DashboardSink.broadcast_queue` 获取；移除 `_logs` deque 和 `_ws_broadcast_queue` deque；移除未使用的 `datetime` 和 `LogEntry` import
- `app/schemas.py`：`LogEntry.source` 默认值从 `"monitor"` 改为 `"backend"`
- `tests/test_monitor_service.py`：适配新架构（注入 DashboardSink + 注册 loguru handler 验证日志流）
- `tests/test_schemas.py`、`tests/test_config_schemas.py`：更新 LogEntry 默认 source 断言
- 全部 1897 个测试通过

### refactor: DashboardSink 替代 LogBroadcastSink + get_logger side→source

- 新增 `DashboardSink` 类，合并内存环形缓冲区（maxlen=1200）+ WebSocket 广播队列（maxlen=200）
- 移除 `LogBroadcastSink` 类（职责单一，仅广播；新 sink 统一内存 + 广播双路径）
- `get_logger(name, side)` → `get_logger(name, source)`，默认值 `"BACKEND"` → `"backend"`
- `LogConfigCenter.initialize/get_logger` 参数 `side` → `source`
- `_console_format` / `_file_format` 中 `extra["side"]` → `extra["source"]`
- `container.py` 同步更新：使用 `DashboardSink`，将其 `broadcast_queue` 注入 `monitor_service`
- `app/utils/__init__.py` 导出 `DashboardSink` 替代 `LogBroadcastSink`
- 全部 1897 个测试通过

### refactor: 日志系统全面优化 — 统一管道、性能提升、安全修复

- 删除 `WebSocketSink`，新增 `LogBroadcastSink`（仅写广播队列，职责单一）
- `MonitorService._push_log()` → `record_log()`（公开方法，解决 S1/L4）
- `DateRotatingSink` 改行缓冲，移除逐条 `flush()`（解决 M14）
- 前端 `extractScreenshotUrl` 改为惰性调用（解决 M23）
- `crypto.py` 密码日志脱敏（解决 M29）
- `login_history.py` 裸 except 补 debug 日志（解决 M30/M31）
- `formatters.js` 修复 success 关键词误判
- `app/utils/__init__.py` 同步更新导出
- 全部 1890 个测试通过

- 删除 `WebSocketSink` 类，新增 `LogBroadcastSink`（仅写广播队列，职责单一）
- `MonitorService._push_log()` → `record_log()`（公开方法，解决审计 S1/L4）
- `DateRotatingSink` 改行缓冲（`buffering=1`），移除逐条 `flush()`（解决审计 M14）
- 前端 `extractScreenshotUrl` 改为模板惰性调用，`filteredLogs` 不再预计算（解决审计 M23）
- `crypto.py` 密码日志脱敏，移除长度泄露（解决审计 M29）
- `login_history.py` 裸 `except Exception: continue` 补 `logger.debug`（解决审计 M30/M31）
- `formatters.js` 修复 `success` 英文关键词误判
- `app/utils/__init__.py` 同步更新导出
- 同步更新所有相关测试文件（test_container、test_monitor_service、test_monitor_service_shutdown）
- 全部 1890 个测试通过

### refactor: 测试文件同步 _push_log → record_log 及 WebSocketSink → LogBroadcastSink 重命名

- `tests/test_container.py`：5 处 `@patch("app.container.WebSocketSink")` → `@patch("app.container.LogBroadcastSink")`，对应参数名 `mock_ws_sink` → `mock_broadcast_sink`
- `tests/test_monitor_service.py`：注释、类名 `TestPushLog` → `TestRecordLog`、方法名 `test_push_log` → `test_record_log`、全部 `svc._push_log(` → `svc.record_log(`（共 4 处）
- `tests/test_monitor_service_shutdown.py`：2 处 `patch.object(svc, "_push_log")` → `patch.object(svc, "record_log")`，1 处 `svc._push_log = MagicMock()` → `svc.record_log = MagicMock()`
- 全部 69 个测试通过

### refactor: MonitorService._push_log 重命名为公开方法 record_log

- `app/services/monitor.py`：方法定义 `_push_log(` → `record_log(`，全部 11 处 `self._push_log(` 调用替换为 `self.record_log(`，回调传参 `log_callback=self._push_log` 同步更新，注释中的 `_push_log` 也一并修正

### fix: 修复仪表盘日志失败消息误显示为绿色

- `frontend/js/methods/formatters.js`：`getLogClass` 移除 `text.includes('success')` 关键字匹配，避免 `success=False` 等包含 "success" 子串的失败消息被误判为成功（绿色）

### chore: 添加 pytest strict-markers、pre-commit 和 CI 覆盖率报告

- `pyproject.toml`：`[tool.pytest.ini_options]` 新增 `addopts = "--strict-markers --tb=short"`
- `.pre-commit-config.yaml`（新建）：配置 ruff-pre-commit（ruff check --fix + ruff-format）
- `.github/workflows/ci.yml`：测试步骤追加 `--cov=app --cov-report=term-missing`

### refactor: 拆分 system.py 路由，提取 autostart 和 ocr 到独立文件

- `app/api/system.py`：移除自动启动路由（4 个端点）和 OCR 路由（4 个端点），清理无用 import
- `app/api/autostart.py`（新建）：提取 `/api/shells`、`/api/autostart/status`、`/api/autostart/enable`、`/api/autostart/disable` 路由
- `app/api/ocr.py`（新建）：提取 `/api/ocr/status`、`/api/ocr/install`、`/api/ocr/uninstall` 路由及 `_check_ddddocr_installed`、`_estimate_pkg_size_mb` 辅助函数
- `app/application.py`：注册 `autostart.router` 和 `ocr.router`
- `tests/test_api_system_routes.py`：更新 mock 路径（`app.api.system` → `app.api.autostart` / `app.api.ocr`）

### fix: 为静默异常处理添加 debug 级别日志

- `app/services/login_history.py`：两处 `except Exception: pass` 改为 `logger.debug` 记录异常信息
  - 第 63 行：获取当前方案名称失败时记录 debug 日志
  - 第 73 行：获取当前任务名称失败时记录 debug 日志
- `app/network/probes.py`：macOS 网络接口检测循环中 `except Exception: continue` 改为 `logger.debug` 记录异常后 continue
- `tests/test_backend_services.py`：新增 `TestLoginHistoryService` 测试类（2 个测试用例），验证 record() 在 profile/task 名称获取失败时记录 debug 日志


## 2026-06-08

### refactor: Portal 检测改为独立开关控制，默认关闭，重命名为"网页响应校验"

- "Captive Portal 检测" 重命名为 "网页响应校验"，更直白易懂

- 新增 `enable_portal_check` 布尔字段（默认 `False`），替代原来靠 `portal_check_urls` 是否为空判断启停
- 后端：`decision.py`、`monitor_core.py`、`monitor.py`、`executor.py`、`config.py`、`config_helpers.py` 全部改为检查 `enable_portal_check`
- 前端：`app-options.js` computed property 改用新字段，开启时自动填入默认 URL
- 默认检测方式：仅 TCP + HTTP + 物理连接检查

### fix: 修复导入的备份文件无法删除

- `app/constants.py`：`BACKUP_FILENAME_PATTERN` 正则添加 `_imported` 后缀支持
  - 导入备份生成的文件名带 `_imported` 后缀，但删除时正则校验不通过

### fix: 修复端口占用检测误判导致启动失败

- `app/utils/process.py`：`is_local_port_in_use()` 在 Windows 上改用 netstat 检查 LISTENING 状态
  - 旧方案仅用 `connect_ex` 检测，TIME_WAIT/CLOSE_WAIT 残留连接也会返回成功
  - 导致程序误判端口被占用，显示"软件已启动 (PID: None)"后直接退出
  - Linux/macOS 保留 bind + connect_ex 方案（SO_REUSEADDR 行为不同）

### feat: 备份管理添加导入功能

- 后端：新增 `POST /api/backup/import` 端点，支持上传 JSON 文件导入备份
  - 验证文件类型（仅 .json）和编码（UTF-8）
  - 使用 Pydantic 模型验证配置格式
  - 自动生成带 `_imported` 后缀的备份文件名
  - 导入后自动清理超过上限的旧备份
- 前端：备份工具栏添加"导入备份"按钮
  - 点击后弹出文件选择器，仅允许选择 .json 文件
  - 上传成功后自动刷新备份列表
  - 导入过程中显示加载状态

### test: 修复假阳性测试并补充低覆盖率模块测试（+32 个测试用例）

- 修复 3 个假阳性/Mock 不当问题：
  - `tests/test_application_logic.py`：`test_removes_old_files` 核心函数 `_cleanup_temp_screenshots()` 未被调用，实际执行清理逻辑并验证结果
  - `tests/test_network_probes.py`：`_block_proxy` 全局状态污染，添加 try/finally 恢复原值
  - `tests/test_playwright_worker.py`：`test_submit_normal_path_no_restart` 跳过核心入队逻辑，捕获入队命令验证 type/data/response_event
- 补充低覆盖率模块测试：
  - `tests/test_application_logic.py`：+4 个测试（settings.json 端口回退、.jpg/.jpeg 扩展名清理）
  - `tests/test_playwright_worker.py`：+10 个测试（队列满、wait 超时、stop 行为、get_worker/shutdown_worker 单例管理）
  - `tests/test_scheduler_service.py`：+18 个测试（CRUD 操作、execute_task 主流程：类型分发、历史记录、last_run 更新、异常处理）

### test: 合并重复测试文件，减少文件数量（-9 个文件）

合并测试同一模块的分散测试文件，从 76 个文件减少到 67 个：

- 组1 Monitor Service：`test_monitor_core.py` + `test_monitor_service_shutdown.py` → `test_monitor_service.py`
- 组2 Network Detect：`test_network_detect_internals.py` → `test_network_detect.py`
- 组4 Profile Service：`test_profile_service_logic.py` → `test_profile_service.py`
- 组5a Backup API：`test_api_backup.py` → `test_api_backup_routes.py`
- 组5b Tools API：`test_api_tools.py` → `test_api_tools_routes.py`
- 组5c Scripts API：删除 `test_api_scripts.py`（2 个 trivial 测试，无实际价值）
- 组5d Logfiles API：删除 `test_logfiles.py`（已被 `test_api_logfiles.py` 完全覆盖）
- 组8 System Services：从 `test_system_services.py` 中移除 AutoStartService 重复测试（已被 `test_autostart.py` 覆盖），仅保留 uninstall 测试

### test: 补充定时任务调度服务测试覆盖（+81 个测试用例）

- `tests/test_scheduled_tasks.py`：新增 13 个测试类（+81 个测试用例），覆盖率从 49% 提升至 98%
  - `TestHasEnabledTasks`（5 个用例）：空目录、全部禁用、有一个启用、跳过 dotfile、跳过损坏 JSON
  - `TestExecuteTask`（11 个用例）：不存在的任务、未知类型、无效 ID、更新 last_run、失败状态、异常捕获、三种任务类型分发、历史记录添加、默认 timeout
  - `TestExecuteScript`（7 个用例）：无 task_service、脚本不存在、类型错误、文件缺失、路径为 None、执行成功、binary_path 传递
  - `TestExecuteBrowserTask`（11 个用例）：无 task_service、任务不存在、类型错误、无 monitor_service、执行成功/失败、等待登录恢复、ImportError、通用异常、pure_mode 传递
  - `TestRecordLoginHistory`（7 个用例）：无服务静默、成功/失败记录、profile_name 获取、monitor 异常处理、login_history.add 异常处理、无 monitor_service
  - `TestExecuteShellExtra`（13 个用例）：从 monitor_service 获取 shell_path、配置异常回退默认、PowerShell/pwsh/cmd/bash 参数构建、非零退出码（有 stderr/无 stderr/无输出）、PermissionError、通用异常、空 stdout 占位、stdout 截断
  - `TestSchedulerLoop`（9 个用例）：无启用任务自动退出、CancelledError 退出、异常继续运行、禁用任务跳过、时间不匹配/匹配、多任务同时触发、分钟不匹配、无效 schedule 默认值
  - `TestOnTaskDone`（4 个用例）：从集合移除、已取消任务、异常记录、不在集合中不报错
  - `TestEnableDisableToggle`（5 个用例）：禁用/启用切换、影响调度器循环、混合状态、默认 enabled 为 False
  - `TestSaveTaskExceptions`（1 个用例）：atomic_write 异常返回失败
  - `TestAddHistoryExceptions`（1 个用例）：atomic_write 异常不崩溃
  - `TestStartStopWithRunningTasks`（2 个用例）：stop 取消运行中任务、start 创建 task
  - `TestEdgeCases`（5 个用例）：构造函数创建目录、深层目录、默认 timeout、覆盖保存、历史往返验证

### test: 补充 API 路由测试覆盖（+81 个测试用例）

- `tests/test_api_tools_routes.py`：新增 11 个测试用例，覆盖工具路由 API 端点
  - `POST /api/background/upload`：PNG 上传成功、不支持的格式、超过 5MB、清理旧背景
  - `GET /api/background/{filename}`：获取存在的图片、不存在返回 404、路径穿越阻止
  - `DELETE /api/background/{filename}`：删除存在的图片、删除不存在返回 404
  - `GET /api/tools/task-recorder.user.js`：脚本存在下载成功、脚本不存在返回 404

- `tests/test_api_backup_routes.py`：新增 14 个测试用例，覆盖备份路由 API 端点
  - `GET /api/backup/list`：空列表、有备份返回列表
  - `POST /api/backup/create`：创建成功、settings.json 不存在返回 404
  - `POST /api/backup/restore/{filename}`：恢复成功、无效文件名、文件不存在、JSON 格式错误
  - `GET /api/backup/download/{filename}`：下载成功、无效文件名、文件不存在
  - `DELETE /api/backup/{filename}`：删除成功、无效文件名、文件不存在

- `tests/test_api_scripts_routes.py`：新增 13 个测试用例，覆盖脚本路由 API 端点
  - `GET /api/scripts`：空列表、有脚本返回列表
  - `GET /api/scripts/{task_id}`：获取存在的脚本、不存在返回 404、浏览器任务类型返回 404
  - `PUT /api/scripts/{task_id}`：保存成功、保存失败
  - `DELETE /api/scripts/{task_id}`：删除成功、删除失败
  - `POST /api/scripts/{task_id}/run`：运行成功、任务不存在返回 404、脚本文件缺失
  - `GET /api/scripts/binaries`：返回可用二进制列表

- `tests/test_api_scheduled_tasks_routes.py`：新增 22 个测试用例，覆盖定时任务路由 API 端点
  - `POST /api/scheduled-tasks`：shell/script/browser 创建成功、缺名称/类型/命令/target/schedule、启用时启动调度器
  - `PUT /api/scheduled-tasks/{task_id}`：更新成功、任务不存在、空名称、无效类型、shell 缺命令
  - `POST /api/scheduled-tasks/{task_id}/toggle`：启用切换、禁用切换、不存在
  - `POST /api/scheduled-tasks/{task_id}/run`：执行成功、执行失败、不存在
  - `GET /api/scheduled-tasks/{task_id}/history`：获取历史、不存在返回 404

- `tests/test_api_system_routes.py`：新增 21 个测试用例，覆盖系统管理路由 API 端点
  - `GET /api/health`：返回 ok 状态
  - `GET /api/init-status`：已初始化、未初始化
  - `GET /api/shells`：返回可用 Shell 列表
  - `GET /api/autostart/status`：返回状态
  - `POST /api/autostart/enable` / `disable`：启用/禁用自启动
  - `GET /api/ocr/status`：已安装/未安装
  - `POST /api/ocr/install`：已安装直接成功、安装成功/失败/超时
  - `POST /api/ocr/uninstall`：未安装直接成功、卸载成功
  - `POST /api/shutdown`：关机请求触发 shutdown_event
  - `GET /api/uninstall/detect`：检测可清理项
  - `POST /api/uninstall`：执行清理、无效 keys 返回 400
  - `GET /api/check-update`：更新检测成功、网络错误

### test: 补充任务执行器和登录处理器测试（+51 个测试用例）

- `tests/test_task_executor.py`：新增 `TestTaskExecutorExecute` 类（+28 个测试用例），覆盖率从 55% 提升至 97%
  - `execute()` 主流程：空步骤成功、单步骤成功、任务超时停止执行、OSError/未知异常捕获、`_handle_failure` 兜底异常
  - `_auto_navigate`：任务 URL 导航、LOGIN_URL 回退、无 URL 跳过、URL 稳定等待
  - `_reveal_hidden_inputs`：启用时调用、纯 eval 步骤跳过、iframe 遍历、跨域异常跳过
  - `_execute_step`：未知步骤类型、handler 异常捕获
  - `_check_success`：无 monitor_config 直接成功、有 monitor_config 调用网络检测、网络不可用/异常返回 False
  - `_handle_failure`：截图启用/禁用
  - `_handle_success`：自定义成功消息
  - `execute_step_at`：成功路径
  - `execute_remaining`：全部成功、中途失败停止
  - `_capture_screenshot`：指定目录、失败返回 None、异常返回 None
  - 其他：步骤间延迟、`wait_for_selector` 超时忽略

- `tests/test_monitor.py`：新增 `TestAttemptLoginFullFlow` 类（+23 个测试用例），覆盖率从 59% 提升至 98%
  - `_perform_login_with_auth_class`：成功路径、未找到活动任务、LoginCancelledError/通用异常捕获
  - `_perform_login_with_active_task`：profile_task_id 优先、回退到 get_active_task()、任务未找到返回 None
  - `_execute_browser_task`：成功路径（关闭浏览器）、失败+close_on_failure=True（关闭）、失败+close_on_failure=False（不关闭）、取消事件、页面为 None 抛异常、dialog 监听器注册/清理、已有上下文先关闭
  - `_execute_script_task`：脚本成功+网络通过、脚本失败、网络检测未通过、取消事件
  - `_ensure_task_manager`：懒初始化、幂等性

### test: 补充自启动服务和卸载服务测试（+44 个测试用例）

- `tests/test_autostart.py`：新增 24 个测试用例
  - `_enable_windows`：VBS 写入成功、mkdir 权限错误、mkdir 通用异常、write_text 权限错误（杀毒拦截）、文件被占用（中/英文错误信息）、其他 OSError、未知异常、文件写入后被拦截删除
  - `_disable_windows`：删除成功、文件不存在
  - `_enable_macos`：bootstrap 成功、bootstrap 失败回退 load 成功、两者均失败、plist XML 转义
  - `_disable_macos`：plist 存在执行 bootout 并删除、bootout 失败回退 unload、plist 不存在
  - `_enable_linux`：成功写入并启用、systemctl enable 失败、单引号转义
  - `_disable_linux`：成功禁用并删除、文件不存在
- `tests/test_uninstall.py`：新增 20 个测试用例
  - `detect()`：自启动启用/禁用、用户数据存在/不存在、Playwright 缓存存在/不存在/None、全部项目检查、缺少 location 字段安全处理
  - `_remove_user_data`：目录不存在、成功删除、权限错误
  - `_remove_playwright_cache`：缓存不存在、成功删除、权限错误
  - `_check_autostart`：正常返回、异常回退
  - `_remove_autostart`：成功移除、异常失败
  - `_dir_size_mb`：rg OSError、stat OSError

### test: 新增 DebugSessionManager 测试文件（+39 个测试用例）

- 创建 `tests/test_debug_session_manager.py`，覆盖 `app/services/debug.py` 中 `DebugSessionManager` 的核心逻辑
- 覆盖范围：
  - `__init__`：初始状态、project_root 存储、锁和信号量创建
  - `get_status` / `_debug_response`：返回格式、初始状态、状态变更反映、排除内部字段
  - `_require_debug_session`：未运行时抛 400、运行中不抛异常
  - `_cancel_debug_timer`：None 定时器、已完成定时器、活跃定时器取消
  - `_close_debug_browser`：正常关闭重置标记、Worker 异常不抛出仍重置
  - `start`：缺少 task_id、空 task_id、任务不存在、成功启动、Worker 失败回滚、已有浏览器关闭
  - `next_step`：未运行抛异常、成功执行、全部完成提示、Worker 失败记录
  - `run_all`：未运行抛异常、成功执行、全部完成、失败停止后续、Worker 提交错误
  - `stop`：未运行不抛异常、运行中关闭浏览器、清理临时文件、保留子目录
  - `close`：浏览器活跃关闭、浏览器未活跃重置、异常处理
  - `_debug_timeout_watcher`：超时重置会话、代数不匹配退出

### test: 新增步骤处理器测试文件（+86 个测试用例）

- 创建 `tests/test_step_handlers.py`，覆盖 `app/tasks/step_handlers.py` 的核心功能
- 覆盖范围：
  - `StepExecutorRegistry`：注册表初始化、获取已注册处理器、custom_js 别名、未知类型返回 None、自定义处理器注册、实例单例
  - `StepHandler` 基类：`_parse_selectors`（单/多/空/空格）、`resolve_params`（基础/模板变量/extra/None 跳过）
  - `InputHandler`：缺 selector 报错、fill 成功、降级到强制输入 JS、全部候选失败、多候选顺序尝试
  - `ClickHandler`：缺 selector 报错、点击成功、降级到 dispatch_event、全部失败
  - `SelectHandler`：缺 selector 报错、空值跳过、未解析变量跳过、精确匹配、required/非 required 元素未找到
  - `ClickSelectHandler`：缺 selector 报错、空值跳过、未解析变量跳过、触发器未找到（required/非 required）、选项未找到
  - `WaitHandler`：缺 selector 报错、等待成功、超时、通用异常
  - `WaitUrlHandler`：缺 pattern 报错、无效正则、URL 已匹配、URL 变为匹配、超时
  - `EvalHandler`：缺 script 报错、执行成功、store_as 存储变量、JS 异常、结果截断、模板变量解析
  - `ScreenshotHandler`：成功截图、自定义 path、截图失败
  - `SleepHandler`：默认时长、自定义时长、超过上限截断、恰好等于上限、MAX_SLEEP_MS 值验证
  - `OcrHandler`：缺 selector 报错、图片未找到、识别成功+store_as、target_selector 自动填入、char_range 独立实例、识别失败+清理、schedule_cleanup 定时器、_do_cleanup 清除缓存、_get_ocr 复用缓存
  - `_resolve_frame`：无 frame 返回 page、按 name 匹配、按 URL 回退、非字符串清除、全部失败回退
  - `_try_candidates_with_fallback`：首个候选可见成功、可见降级到 attached、全部失败、多候选顺序

### test: 补充 monitor_core 未覆盖的核心逻辑测试（+26 个测试用例）

- `tests/test_monitor_core_logic.py`：新增 `TestMonitorNetwork`、`TestLoginRecoveryLoop`、`TestCheckProfileSwitch` 三个测试类
- `TestMonitorNetwork`（8 个用例）：覆盖 `monitor_network()` 主循环的暂停时段分支、网络正常等待、网络异常触发恢复、停止事件退出、BREAK 退出、all_disabled 跳过、GIVE_UP/NET_DISCONNECT 状态设置
- `TestLoginRecoveryLoop`（10 个用例）：覆盖 `_login_recovery_loop()` 的登录成功、超限放弃、停止退出、物理断开、暂停时段、认证不可达、登录前超限检查、失败重试、标志位管理、monitoring 中断
- `TestCheckProfileSwitch`（8 个用例）：覆盖 `_check_profile_switch()` 的无 service 提前返回、auto_switch 禁用、匹配切换、无匹配不切换、冷却防重复、同方案不切换、失败回退缓存、异常捕获
- 测试用例数：24 → 50（+26），全部通过

### refactor: 重构 test_backend_services.py 和 test_scheduled_tasks.py，删除重复测试

- `tests/test_backend_services.py`：删除 `TestCheckDangerousSteps` 类（8 个测试用例），功能已被 `test_task_service_logic.py::TestCheckDangerousSteps` 更全面地覆盖（15 个用例）；清理 `_check_dangerous_steps` 导入
- `tests/test_scheduled_tasks.py`：删除 `TestExecuteShellUsesPolicy` 类（3 个测试用例），功能已被 `test_scheduler_service.py` 更全面地覆盖；清理未使用的 `unittest.mock` 导入
- 测试用例数：141 → 130（减少 11 个重复测试），全部通过


### refactor: 重构 test_monitor.py，移除 NetworkMonitorCore 重复测试

- 删除 13 个 `NetworkMonitorCore` 相关测试类（TestEnums、TestMonitorCoreInit、TestMonitorCoreSnapshot、TestMonitorCoreUpdateConfig、TestMonitorCoreGetRetryConfig、TestMonitorCoreGetTestSites、TestMonitorCoreWaitInterruptible、TestMonitorCoreGetMonitorInterval、TestMonitorCoreLoginRetryOrBreak、TestMonitorCoreStartStop、TestMonitorCoreStopMonitoring、TestLogMessageExcInfo、TestDefaultPingTargets），这些已由 `test_monitor_core_logic.py` 更全面地覆盖
- 移除 `from app.core.monitor_core import NetworkMonitorCore, NetworkState, RecoveryResult` 和 `import time`
- 更新模块文档字符串
- 测试用例数：47 → 19（减少 28 个重复测试），全部通过

### refactor: 重构 test_network_probes.py，移除 decision 模块测试并补充线程安全测试

- 删除 6 个测试 decision 模块的类（TestCheckPause、TestCheckNetworkStatus、TestCheckLoginPrerequisites、TestIsAuthUrlReachable、TestIsNetworkAvailable、TestCheckCampusNetworkStatus），这些已由 `test_decision.py` 覆盖
- 移除顶部 `from app.network.decision import ...` 和 `import socket`（不再需要）
- 新增 `is_block_proxy` 到 probes import 列表
- 在 `TestSetBlockProxy` 中补充线程安全测试（来自已删除的 `test_network_probes_utils.py`）
- 更新模块文档字符串，移除对 network_decision 的提及
- 测试用例数：35 → 22（减少 13 个重复测试），全部通过


## 2026-06-07（代码审查修复）

### fix: 代码审查修复的二次审核修正

- #1: 恢复 `close_browser` 中 `__aexit__` 兜底调用（login.py）
- #2: 新增 `shutdown_worker()` 公开函数替代直接导入 `_worker`（playwright_worker.py + container.py）
- #3: `apply_profile` 改为接收 profile_id，内部解析可读名称用于日志（monitor.py）
- #4: `save_config_combined` 日志移入 `update` 闭包内，消除锁外读竞态（config.py）
- #5: route 异常处理从 `pass` 改为 `logger.debug`（playwright_worker.py）

### fix: 基于代码审查报告修复 18 项问题

**第一优先级（严重问题）：**
- S5: `wsConnected` 未定义 → 改用 `this.ws?.readyState !== WebSocket.OPEN`（lifecycle.js）
- S1: `_loop` TOCTOU 竞态 → 三处统一先捕获再检查 + try/except（playwright_worker.py）
- S3: `_simple_deobfuscate` 静默返回损坏数据 → 改为抛出 DecryptionError（crypto.py）
- S4: 调试页面加载失败后继续执行 → 返回 WorkerResponse(success=False)（playwright_worker.py）
- S2/C1: `_login_in_progress` 超时后永久阻塞 → 超时分支主动清除标志（monitor.py）

**第二优先级（重要问题）：**
- A1: `save_config_combined` Lost Update → 改用 `profile_service.update()` 原子模式（config.py）
- A2: `_save_unsafe` 缓存引用泄露 → 改为 `model_copy(deep=True)`（profile.py）
- B4: `toggle_pure_mode` 非原子更新 → 改用 `profile_service.update()` 模式（monitor.py）
- M2: WS 重试耗尽后无恢复 → visibilitychange 中重置 wsRetryCount（lifecycle.js）
- M7: 路由拦截异常处理缺失 → 添加 try/except 包裹（playwright_worker.py）
- M1: Worker shutdown 未关闭 → shutdown 末尾添加条件停止（container.py）
- M4: `togglePureMode` 快速点击竞态 → 添加 _pureModeLoading 标志（editor.js + debug.js）
- 新增: `_wsPingTimer` 重连累积 → 重连前清理旧 timer（lifecycle.js）

**第三优先级（一般问题）：**
- C4: 浏览器生命周期脆弱模式 → 先赋值再 __aenter__（login.py）
- L12: visibilitychange 监听器未清理 → beforeUnmount 中移除（app-options.js）
- C2: close_browser 双重关闭 → 移除多余的 __aexit__ 调用（login.py）
- B3: _reload_config_internal 三次 load → 缓存到局部变量（monitor.py + config.py）
- B1: apply_profile ID/Name 混用 → 统一传 profile_id（profiles.py）

**测试更新：**
- test_close_browser_with_context: 移除 __aexit__ 断言（test_monitor.py）
- test_toggle_pure_mode: save → update 断言（test_monitor_service.py）


## 2026-06-07（全面代码审查）

### docs: 两轮 10 维度全面代码审查报告

- `development/code-review-report.md`：新建综合代码审查报告
- 审查方法：10 个子代理并行深度审查，覆盖 10 个维度
  - 第一轮：逻辑正确性、错误处理、性能优化、线程安全、代码质量
  - 第二轮：安全漏洞、前端代码、状态机、测试覆盖、API 契约
- 发现：🔴 严重 5 项、🟠 重要 11 项、🟡 一般 17 项、🔵 信息 10 项
- 安全审计结论：路径遍历优秀、XSS/CSRF/密码/子进程良好，无重大安全问题
- Top 5 修复项：wsConnected 未定义、_loop TOCTOU、_login_in_progress 阻塞、_simple_deobfuscate 静默损坏、Worker shutdown 未关闭


## 2026-06-07（通知下拉菜单修复）

### fix: 通知历史下拉菜单被内容区域遮挡

- `frontend/styles/components.css`：`.notification-dropdown` 从 `position: absolute` 改为 `position: fixed`，z-index 从 `100` 提升至 `var(--z-overlay)`（150），脱离 `.top-bar` 的层叠上下文
- `frontend/styles/responsive.css`：768px 断点下调整下拉菜单定位（`top: 60px; right: 16px`）


## 2026-06-07（登录模块导入修复）

### fix: login.py 模块导入路径错误

- `app/utils/login.py`：修复 5 个错误的模块导入路径
  - `from ..task_executor import ScriptTaskInfo` → `from ..tasks.models import ScriptTaskInfo`
  - `from ..task_executor import TaskManager` → `from ..tasks.manager import TaskManager`
  - `from ..task_executor import TaskExecutor` → `from ..tasks.executor import TaskExecutor`
  - `from ..network_decision import check_network_status` → `from ..network.decision import check_network_status`
  - `from ..script_runner import ScriptRunner` → `from ..workers.script_runner import ScriptRunner`
- 原因：模块重组后导入路径未同步更新，导致 `No module named 'app.task_executor'` 错误


## 2026-06-07（项目审查报告验证）

### docs: 项目审查报告代码验证

- `development/project-review-verified.md`：新建经代码验证的审查报告，5 个并行 Agent 对照源码逐项验证原始报告
- 原始报告 17 项高严重度问题中：5 项已在阶段 1-4 修复、6 项确认属实、6 项描述夸大/有偏差
- 17 项正面发现全部属实，4 项文档问题全部属实


## 2026-06-07（项目审查优化 - 阶段1-4）

### fix: 监控线程绕过暂停时段检查

- `app/core/monitor_core.py`：在 `_login_recovery_inner` 入口处插入暂停时段检查，修复重试期间跨越暂停时段边界不会停止的问题
- 新增 `RecoveryResult.PAUSED` 枚举值

### fix: os._exit(0) 绕过 lifespan 正常清理

- `app/api/system.py`：删除 `from app.main import app` 死代码，改用 `shutdown_event` 触发 lifespan 正常关闭
- `app/application.py`：lifespan 中创建 `shutdown_event` 并挂载到 `app.state`
- `tests/test_system_shutdown.py`：更新测试适配新实现

### fix: 日志白名单正则不匹配

- `app/api/logfiles.py`：修正 `_SAFE_FILE_PATTERN` 正则从 `r"^app\.log(?:\.\d)?$"` 到 `r"^app\.log(?:\.\d+)?$"`，支持多位数字的轮转文件

### fix: Windows --stop 优雅路径修复

- `main.py`：Windows 路径直接使用 `taskkill /F /PID` 一次到位，避免无效的 WM_CLOSE 尝试
- `tests/test_main.py`：更新测试断言消息

### refactor: 移除未使用的 Vue 组件

- `frontend/js/components.js`：删除 `GlassCard`、`FormGroup`、`StatusDot`、`LoadingSpinner`、`EmptyState` 5 个未使用组件，保留 `ToggleSwitch`
- `frontend/app.js`：移除对应的导入和注册代码
- **注意**：`components.css` 中的 `.form-group`、`.status-dot` 等 CSS 样式类保留（HTML 模板中仍在使用）

### fix: _ClampMixin 添加 warning 日志

- `app/schemas.py`：`_ClampMixin` 钳制数值时记录 warning 日志，避免用户输入被静默修改

### feat: WebSocket visibilitychange + ping/pong

- `frontend/js/methods/lifecycle.js`：添加 `visibilitychange` 监听，切回页面时主动重连；添加应用层 ping/pong 防止代理切断空闲连接
- `app/application.py`：后端 WebSocket 处理支持 `ping` 消息类型，返回 `pong` 响应

### fix: Dashboard 加载失败提示

- `frontend/js/methods/lifecycle.js`：初始化失败时显示 toast 提示用户刷新重试

### docs: CLAUDE.md 数据同步

- `CLAUDE.md`：修正测试文件数量从 32 到 35

### refactor: 修复 AI 生成的代码异味

**英文 docstring 改中文：**
- `app/services/debug_session.py`：模块 docstring 从英文改为中文
- `app/workers/playwright_worker.py`：模块 docstring 从英文改为中文
- `app/utils/browser.py`：模块 docstring 从英文改为中文

**移除不必要的 shebang：**
- `app/utils/browser.py`：移除 `#!/usr/bin/env python3`
- `app/utils/login.py`：移除 `#!/usr/bin/env python3`
- `app/utils/crypto.py`：移除 `#!/usr/bin/env python3`

**移除死代码：**
- `app/api/system.py`：移除 `_get_uv_exe()` 函数（仅 `return "uv"`），内联为字符串字面量

**优化代码结构：**
- `app/services/profile.py`：`detect_matching_profile` 从两次循环合并为单次循环，保持网关 IP > SSID 优先级

**移除 AI 装饰性样式：**
- `frontend/styles/layout.css`：移除 `.logo-text` 渐变效果，改用纯色 `var(--accent)`
- `frontend/styles/components.css`：移除 `.btn-primary::after` 高光扫过动画
- `frontend/styles/components.css`：添加 `.exit-overlay` 样式
- `frontend/js/methods/ui.js`：`quitApp` 失败兜底改用 CSS class，移除内联 style

**修复 loguru 风格：**
- `app/api/profiles.py`：移除 `exc_info=True`（loguru 默认记录异常）


## 2026-06-07（日志级别设置移除 + 日志系统优化收尾）

### refactor: 移除前端/后端日志级别设置，简化日志系统

**移除日志级别设置：**
- `frontend/partials/pages/settings/settings-system.html`：移除"后端日志级别"和"前端日志级别"两个下拉框
- `frontend/js/constants.js`：移除 `backend_log_level` 和 `frontend_log_level` 默认值
- `frontend/js/methods/config.js`：移除 2 处 `setFrontendLogLevel` 调用
- `frontend/js/methods/lifecycle.js`：`_shouldShowLog` 改为始终返回 `true`
- `frontend/js/methods/ui.js`：移除 `setFrontendLogLevel` 方法
- `app/api/config.py`：移除 `LogConfigCenter.set_level()` 调用和 import
- `app/application.py`：固定使用 `"INFO"` 级别，不再从配置读取
- `app/schemas.py`：保留 `backend_log_level` / `frontend_log_level` 字段（兼容已有 settings.json）

**日志系统收尾优化：**
- `app/network/probes.py`：移除 `_check_portal` 和 `_check_one` 内部冗余的 SSL 调试日志（每个 URL 检测都打印一次，改为不打印）
- `app/core/monitor_core.py`：移除启动/停止时的 `=` 分隔线和 `LOG_DIVIDER_LENGTH` 常量
- `app/utils/logging.py`：日志系统启动信息合并为单行
- `main.py`：`%.3fs` → `{:.3f}s`（统一 loguru `{}` 占位符风格）
- `frontend/styles/pages/dashboard.css`：`.log-message` 补充 `font-family: var(--font-mono)`
- `tests/test_network_probes.py`：更新测试移除已删除的 SSL 日志断言


## 2026-06-07（日志系统全面优化）

### refactor: 日志系统 Bug 修复 + 格式统一 + 级别修正

涉及 22 个文件，103 行变更。

**Bug 修复：**
- `app/core/monitor_core.py`：修复 `log_message` 中无效的 `if exc_info` / `else` 条件分支（两个分支执行完全相同的代码）

**日志级别修正（8 处）：**
- `app/application.py`：配置迁移失败 `warning` → `error`；temp 截图清理失败 `debug` → `warning`；旧日志清理失败 `debug` → `warning`
- `app/container.py`：临时目录清理失败 `debug` → `warning`
- `app/core/monitor_core.py`：记录登录历史失败 `DEBUG` → `WARNING` + 补充 `exc_info=True`
- `app/api/system.py`：关闭流程 5 处 `debug` → `warning`（监控服务、PlaywrightWorker、孤儿浏览器、PID 文件、services.shutdown）
- `app/services/debug.py`：调试临时目录清理失败 `debug` → `warning`

**中英文统一（全中文，30+ 处）：**
- `app/api/` 路由文件（monitor、tasks、scripts、scheduled_tasks、system、profiles、config）：API 审计日志统一为中文
- `app/services/` 服务文件（task、monitor、debug）：服务层日志统一为中文
- `app/services/autostart.py`：`"Linux systemd enable"` → `"Linux systemd 启用"`

**格式化风格统一：**
- `app/utils/login.py`：f-string + ❌ emoji → `{}` 占位符；`%s` → `{}`；`→` → `->`
- `app/tasks/step_handlers.py`：`%d` → `{}`；`→` → `->`
- `main.py`：`%d` → `{}`

**分隔符统一（→ 改为 ->，— 改为 --）：**
- `app/core/monitor_core.py`、`app/services/monitor.py`、`app/tasks/executor.py`、`app/tasks/step_handlers.py`、`app/network/decision.py`、`app/network/probes.py`、`app/api/backup.py`

**Emoji 移除：**
- `app/core/monitor_core.py`：移除 `✓` 和 `✗`（前端 `getLogClass()` 通过 `text.includes('成功')` 和 `level === 'ERROR'` 兜底）

**文档改进：**
- `app/utils/logging.py`：`set_level()` 补充 docstring 说明影响范围；sink 内部 `print` 补充递归原因注释；`_cleanup_old_dirs` 记录清理失败到 stderr

**风险缓解：**
- `app/services/monitor.py`：`drain_ws_queue` 添加内层 try/except 防止单条消息异常中断整个排空循环


## 2026-06-07（优化计划执行）

### refactor: 全面优化计划 — 阶段一（快速修复）+ 阶段五.1（核心测试补充）

**阶段一 — 快速修复：**
- `app/utils/logging.py`：删除重复的 `from pathlib import Path`；移除 4 个向后兼容别名（`_VALID_LOG_LEVELS`、`_normalize_level`、`WebSocketLogHandler`、`_DateRotatingFileHandler`）；更新内部引用使用正式名称
- `app/utils/__init__.py`：导出 `WebSocketSink` 替代 `WebSocketLogHandler`
- `app/network/probes.py`、`app/network/detect.py`、`app/utils/shell_policy.py`：统一使用 `CREATE_NO_WINDOW_FLAG` 常量，消除 `getattr(subprocess, "CREATE_NO_WINDOW", 0)` 和 `0x08000000` 硬编码
- `frontend/styles/components.css`：删除重复的 `@keyframes spin`（统一定义在 `base.css`）
- `pyproject.toml`：删除重复的 `[project.optional-dependencies].dev`，保留 `[dependency-groups].dev`
- `app/application.py`：启动时自动清理 `temp/` 目录中超过 7 天的截图文件
- `app/services/monitor.py`：`_ws_drain_loop` 重命名为 `ws_drain_loop`（公开方法）
- `app/container.py`：更新为调用 `ws_drain_loop()`
- `app/services/monitor.py`：更新 `WebSocketLogHandler` 引用为 `WebSocketSink`

**阶段五.1 — 核心模块测试补充（+54 个测试用例）：**
- 新建 `tests/test_variable_resolver.py`：覆盖 VariableResolver 的基础解析、优先级、递归/循环引用、缓存、JS 安全编码
- 新建 `tests/test_decision.py`：覆盖 check_pause、check_network_status、check_login_prerequisites、is_network_available、_is_auth_url_reachable
- 新建 `tests/test_login_handler.py`：覆盖 LoginAttemptHandler 的截图正则、前置检查流程、初始化
- `tests/test_utils.py`：更新 `_normalize_level` → `normalize_level` 引用

**阶段三 — 代码质量改进：**
- `app/utils/shell_utils.py`（新建）：提取 `detect_shells()`、`detect_binaries()`、`get_default_shell()` 共享函数
- `app/services/scheduler.py`：Shell 检测逻辑改为从 `shell_utils` 导入
- `app/workers/script_runner.py`：二进制检测逻辑改为从 `shell_utils` 导入
- `app/utils/login.py`：拆分 `_perform_login_with_active_task()`（~120 行）为 `_ensure_task_manager()` + `_execute_browser_task()` + 主方法
- `app/tasks/step_handlers.py`：提取 `_try_candidates_with_fallback()` 基类方法，消除 InputHandler/ClickHandler 的重复降级模式
- `frontend/styles/`：`border-radius: 10px` → `var(--radius-lg)`（11 处）；`transition: all` → 显式属性列表（3 处）

**阶段四 — 架构改进：**
- `app/deps.py`：新增 `get_scheduler_service()` 依赖注入函数
- `app/api/scheduled_tasks.py`：使用 `get_scheduler_service()` 替代直接访问 `request.app.state.services`
- `app/api/system.py`：Shell 检测导入改为从 `shell_utils` 直接导入
- `app/services/task.py`：新增 `get_script_path(task_id)` 公开方法
- `app/api/scripts.py`、`app/services/scheduler.py`：使用 `get_script_path()` 替代穿透访问 `task_manager._safe_task_path()`

## 2026-06-07

### feat: 启动时压缩旧日志目录为 zip + 日志查看支持 zip 归档

在应用启动时自动将非今天的日期目录压缩为 zip，并支持从 zip 中查看历史日志。

**压缩功能：**
- `app/utils/logging.py`：新增 `compress_old_logs()` 函数 — 遍历 `logs/` 下的 YYYY-MM-DD 目录，跳过今天，压缩为同名 .zip（保留目录结构），删除原目录；清理超过 `retention_days` 的 zip 文件
- `app/application.py`：启动时调用 `compress_old_logs(log_dir, retention_days)`

**日志查看 zip 支持：**
- `app/api/logfiles.py`：重写，支持从目录和 zip 两种来源读取日志
  - `list_log_files()`：同时扫描日期目录和 `.zip` 归档
  - `get_log_file_content()`：优先从目录读取，其次从 zip 读取
  - 新增 `_list_zip_files()`、`_read_from_zip()` 辅助函数
- `tests/test_logfiles.py`：重写，新增 zip 支持测试（8 个用例）

**行为：**
- 今天目录保持原始状态（日志正在写入）
- 非今天目录 → `2026-06-06.zip`（包含 `2026-06-06/app.log`、`2026-06-06/screenshots/xxx.png`）
- zip 保留天数由 `log_retention_days` 设置控制（默认 7 天）
- 前端日志页面可正常查看已压缩的历史日志
- 压缩在后台守护线程执行，不阻塞启动

**测试结果：** 1077 passed, 2 skipped

### refactor: 合并 debug 目录到 logs 目录

将 OCR 验证码截图从 `debug/` 目录移入 `logs/{date}/screenshots/`，删除 `debug/` 目录和静态挂载。

**改动：**
- `app/tasks/step_handlers.py`：截图保存路径 `debug/{date}/` → `logs/{date}/screenshots/`，URL 前缀同步更新
- `app/constants.py`：删除 `DEBUG_DIR` 常量
- `app/application.py`：删除 `DEBUG_DIR` 导入、目录创建、`/debug` 静态挂载
- 静态挂载从 4 个减为 3 个：`/static`、`/logs`、`/temp`

**测试结果：** 1069 passed, 2 skipped

### refactor: 基于审计报告的系统性修复（REFACTOR_PLAN_4）

基于代码质量审计报告，实施 10 项修复（P0×7 + P1×3 + P2×1）。

**P0 立即修复（7 项）：**

1. **修复 tools.py 路径 bug** — `app/api/tools.py:46`：`doc/` → `docs/`，修复任务编写指南下载 API 永久 404
2. **删除 shortcuts.js 死代码** — `frontend/js/methods/shortcuts.js`：删除 2 行空导出文件（全仓零 import）
3. **删除 lifecycle.js log_batch 死分支** — `frontend/js/methods/lifecycle.js:236-241`：后端从不发送 `log_batch` 类型
4. **删除 login.py 死代码** — `app/utils/login.py:21-22`：删除 `if False:` 引用已不存在的 `task_executor` 模块路径
5. **pyproject.toml 添加 asyncio_mode** — 添加 `asyncio_mode = "auto"`，async 测试不再需要 `@pytest.mark.asyncio` 装饰器
6. **删除 tools/get-pip.py** — 27,509 行死代码，全项目零引用
7. **更新 CLAUDE.md 目录结构** — 批量更新 `backend/` → `app/api/`、`src/` → `app/`、`app.py` → `main.py`、测试文件数 39 → 32 等 15+ 处过时引用

**P1 中等修复（3 项）：**

8. **_update_status_snapshot 异常不跳过 WS 推送** — `app/services/monitor.py:419`：删除 `return`，快照失败时仍广播上次状态
9. **scheduler 任务保存改用 atomic_write** — `app/services/scheduler.py:146`：非原子写改为原子写，防止崩溃损坏任务文件
10. **active.txt 写入改用 atomic_write** — `app/tasks/manager.py:429`：非原子写改为原子写

**P2 文档修复（1 项）：**

11. **README.md 修复 doc/ → docs/ 链接** — 5 处断链修复 + 测试文件数 39 → 32

**删除 requirements.txt** — `pyproject.toml` 为唯一依赖来源，消除 `loguru` 缺失导致的非 uv 用户崩溃问题

**测试结果：** 1069 passed, 2 skipped

### refactor: 全面代码质量优化（REFACTOR_PLAN_3 全部实施）

基于全面代码审查，系统性实施 23 项重构优化。

**P0 紧急修复（3 项）：**

1. **消灭 18 处 `except Exception: pass`** — 所有位置添加 `logger.debug` 或 `logger.warning` 日志记录
   - `app/core/system_tray.py`、`app/tasks/manager.py`（3 处）、`app/tasks/executor.py`
   - `app/workers/playwright_worker.py`（4 处）、`app/workers/playwright_bootstrap.py`（2 处）
   - `app/utils/logging.py`（2 处，使用 print 避免递归）、`app/utils/login.py`、`app/utils/notify.py`（2 处）
   - `app/services/monitor.py`、`app/services/scheduler.py`

2. **`_block_proxy` 全局变量加锁** — `app/network/probes.py`：添加 `threading.Lock` 保护读写，新增 `is_block_proxy()` 函数

3. **浏览器关闭异常记录** — `app/utils/login.py`：`__aexit__` 异常从 `pass` 改为 `logger.warning`

**P1 高优先级（8 项）：**

4. **登录历史记录统一** — `app/services/login_history.py`：新增 `record()` 方法，自动从 ProfileService/TaskManager 提取名称；`app/services/monitor.py` 简化调用

5. **`_normalize_level` 统一** — `app/utils/logging.py`：导出 `normalize_level` 和 `VALID_LOG_LEVELS`；`app/schemas.py` 和 `app/services/config.py` 改为导入

6. **MonitorService 配置预处理统一** — `app/services/monitor.py`：提取 `_prepare_command_config()` 方法

7. **密码解密分支简化** — `app/services/config.py`：提取 `_decrypt_password_field()` 函数，40 行 7 层嵌套简化为 10 行调用

8. **截图保存逻辑统一** — `app/utils/file_helpers.py`：新增 `save_screenshot()` 函数；`app/tasks/step_handlers.py` 和 `app/tasks/executor.py` 改为调用

9. **`_start_browser` 拆分** — `app/workers/playwright_worker.py`：拆分为 `_build_launch_args()`、`_build_context_options()`、`_apply_stealth_and_routes()`

10. **`build_runtime_config` 拆分** — `app/services/config.py`：拆分为 `_build_credential_config()`、`_build_browser_config()`、`_build_monitor_config()`

11. **`save_config_combined` 拆分** — `app/services/config.py`：拆分为 `_update_system_settings()`、`_update_default_profile()`

**P2 中优先级（7 项）：**

12. **命令派发字典化** — `app/workers/playwright_worker.py` 和 `app/services/monitor.py`：if-elif 链改为 `_CMD_ROUTES` 字典映射

13. **超时值提取为常量** — `app/constants.py`：新增 15+ 个超时/容量常量；`app/workers/playwright_worker.py` 和 `app/services/monitor.py` 更新引用

14. **MonitorCommand.type 改用 Enum** — `app/services/monitor.py`：新增 `MonitorCmdType(StrEnum)`，所有命令创建和路由使用枚举

15. **变量名 `pld` 改为 `payload_dict`** — `app/services/config.py`：全部 30+ 处 `pld` 重命名为 `payload_dict`

16. **Portal URL 解析统一** — `app/utils/network_helpers.py`：新增 `parse_portal_checks()` 函数；`app/services/config.py` 和 `app/tasks/executor.py` 改为调用

17. **`_cleanup_browser` 重复逻辑提取** — `app/workers/playwright_worker.py`：提取 `_is_normal_close_error()` 和 `_close_resource()` 方法

**P3 低优先级（2 项）：**

18. **消除 WebSocketManager 测试重复** — `tests/test_monitor_service.py`：删除 8 个重复测试（保留 `test_ws_manager.py` 完整版本）

19. **移除脆弱的 AST 检查** — `tests/test_constants.py`：删除 `TestNoFunctionLocalImport` 类

**测试结果：** 1069 passed, 2 skipped（减少 9 个重复/脆弱测试）

### refactor: P3 低优先级重构 — DebugBrowserSession 内联、测试 fixture 提取、合并 _extra 文件

**P3-1 DebugBrowserSession 内联：**
- `app/services/debug.py`：删除 `DebugBrowserSession` 类，将 `close()` 逻辑内联为 `_close_debug_browser()` 方法
- `app/services/debug_session.py`：`DebugSession.session` 字段改为 `_browser_active: bool`
- `tests/test_backend_services.py`：更新测试断言

**P3-2 测试 fixture 提取：**
- `tests/test_monitor_service.py`：提取 `_make_monitor_service()` 共享函数，替换 14 处重复的 4 层 `@patch` 装饰器和 mock 构建逻辑

**P3-3 合并 _extra 测试文件：**
- `test_scheduler_extra.py` → 合并到 `test_scheduled_tasks.py`，删除原文件
- `test_script_runner_extra.py` → 合并到 `test_script_runner.py`，删除原文件
- `test_task_service_extra.py` → 合并到 `test_backend_services.py`，删除原文件

**测试结果：** 1069 passed, 2 skipped

### chore: 迁移至 Python 3.12，移除依赖版本约束

将项目最低 Python 版本从 3.10 提升到 3.12，移除所有依赖版本约束以使用最新版本。

**主要变更：**

- `.python-version`：`3.10` → `3.12`
- `pyproject.toml`：`requires-python` 从 `>=3.10` 改为 `>=3.12`，移除所有依赖版本约束
- `launcher.py`：嵌入式 Python 版本号 `3.10` → `3.12`，CLI 默认参数同步
- `setup_env.sh`：版本检查逻辑从精确匹配 `3.10` 改为 `>=3.12` 范围判断
- `README.md`：Python 版本要求更新
- `requirements.txt`：移除所有版本约束
- `docs/migration-python-3.12.md`：新增迁移计划文档

**依赖升级：**

| 包 | 旧版本 | 新版本 |
|---|--------|--------|
| playwright | 1.57.0 | 1.60.0 |
| fastapi | 0.135.1 | 0.136.3 |
| uvicorn | 0.41.0 | 0.49.0 |
| pydantic | 2.12.5 | 2.13.4 |
| onnxruntime | 1.20.1 | 1.26.0 |
| cryptography | 47.0.0 | 48.0.0 |
| pillow | 12.1.1 | 12.2.0 |
| starlette | 0.52.1 | 1.2.1 |
| python-multipart | 0.0.27 | 0.0.32 |

### refactor: 日志系统从标准 logging 迁移到 loguru

全面迁移日志系统，使用 loguru 替代标准 logging 模块，提供更简洁的 API。

**主要变更：**

- `pyproject.toml`：添加 `loguru>=0.7.0` 依赖
- `src/utils/logging.py`：完全重写（~280 行 → ~250 行）
  - 使用 loguru 的 `logger.bind()` 实现 `get_logger(name, side)` 接口
  - 实现 `DateRotatingSink`（原 `_DateRotatingFileHandler`）— 按日期目录存储 + 大小轮转
  - 实现 `WebSocketSink`（原 `WebSocketLogHandler`）— 推送到前端 WebSocket 广播队列
  - 实现标准 logging 桥接 sink — 保持 pytest `caplog` 兼容性
  - 保留 `_normalize_level()` 和 `LogConfigCenter` 单例配置中心
  - 保留 `_DateRotatingFileHandler` 和 `WebSocketLogHandler` 别名（向后兼容）

- `src/monitor_core.py`：将 `log_message()` 参数从 `int`（logging.INFO）改为 `str`（"INFO"）
- `backend/container.py`：使用 loguru 的 `logger.add()` 注册 WebSocket sink
- `backend/main.py`：移除顶层 `import logging`，保留局部导入用于压制第三方库日志
- `backend/monitor_service.py`：移除 `import logging`，使用 loguru 的动态方法调用
- `src/playwright_worker.py`：移除未使用的 `import logging`
- `src/utils/env.py`：从 `logging.getLogger()` 改为 `get_logger()`
- `tests/test_monitor.py`：更新测试用例使用字符串级别参数
- `tests/test_utils.py`：移除 `_level_value` 和 `SideFilter` 测试，更新 `DateRotatingSink` 测试

**API 变化：**
- `get_logger(name, side)` 返回 loguru logger（支持 `.info()`、`.warning()` 等直接调用）
- `setup_logger(name, config)` — `config` 参数被忽略，保持向后兼容
- `log_message(message, level)` — `level` 参数从 `int` 改为 `str`

**测试结果：** 1080 passed, 2 skipped

### chore: 移除未使用的依赖 websockets 和 pysocks

`pyproject.toml`：从 `dependencies` 中移除 `websockets` 和 `pysocks`。验证发现 `python-multipart` 不能移除（项目使用了 `UploadFile`，且 FastAPI 不会自动拉入此依赖），已修正分析报告。

### docs: 新增依赖分析报告

`development/dependency-analysis.md`：对项目所有运行时依赖进行评估，识别出可移除的无用依赖，确认其余依赖均为合理选择，并记录 loguru 替代 logging 的可行性分析。


## 2026-06-06

### fix: 修复发布版本首次启动因 debug/logs/temp 目录不存在而崩溃

`backend/main.py`：将 `LOGS_DIR`、`DEBUG_DIR`、`TEMP_DIR` 的 `mkdir` 调用从 `run()` 函数内移至模块级别（`app.mount()` 之前），确保目录在静态文件挂载前已存在。删除 `run()` 中重复的 `DEBUG_DIR.mkdir()`。

### fix: 修复 setup_env.sh uv 模式下无进度反馈且内嵌 Python 缺少 venv 导致失败

`setup_env.sh`：
- `uv sync` 添加 `--python python3` 强制使用系统 Python，避免使用 release 包内嵌的 `environment/python/`（Debian/Ubuntu 缺少 `python3-venv`）
- 移除所有 `>/dev/null` 重定向，`uv sync`、`pip install`、`playwright install` 均显示输出
- `uv sync` 完成后验证 `.venv` 目录是否存在，失败时回退到系统 Python
- `AUTO_INSTALL_PLAYWRIGHT` 改为根据 Playwright 实际安装状态动态设置，安装失败时保留 `true` 让 `app.py` 兜底

### fix: 自启动服务使用当前 Python 环境而非硬编码解释器

`backend/autostart_service.py`：
- `_start_command()` 优先使用 `sys.executable`（uv/venv/系统 Python 均适用），嵌入式 Python 降级为兜底
- Windows `_enable_windows` 复用 `_start_command()` 替代重复的嵌入式 Python 检测逻辑


## 2026-06-04

### 全面功能性问题修复（14 项，代码审查后）

**高严重度：**

1. **Windows 关机不执行 lifespan 清理** — `backend/routers/system.py`：`os.kill(SIGTERM)` 改为 `asyncio.run_coroutine_threadsafe(services.shutdown())` + `os._exit(0)`，确保所有服务资源正常释放
2. **删除活动方案后不通知 MonitorService** — `backend/routers/profiles.py`：`delete_profile` 添加 `monitor_svc` 依赖注入，删除成功后调用 `apply_profile()`
3. **网络验证遗漏 test_urls** — `src/task_executor.py`：`_network_detection_check` 补充 `test_urls` 参数传递

**中严重度：**

4. **方案切换检测异常中断监控** — `src/monitor_core.py`：`_check_profile_switch` 添加 try/except，异常仅 WARNING 日志不终止监控
5. **调试停止后浏览器半损坏** — `src/playwright_worker.py`：`ensure_browser` 增加 `_page is None` 检查，触发浏览器重建
6. **定时任务历史并发写入数据损坏** — `backend/scheduler_service.py`：`_add_history` 改为 async，使用 `asyncio.Lock` 保护读-改-写，`atomic_write` 替代 `write_text`
7. **调试会话竞态条件** — `backend/debug_manager.py`：`run_all`/`next_step` 保存 session 引用 + `self._session is session` generation check，防止写入被替换的新 session
8. **登录历史 clear 无锁** — `backend/login_history_service.py`：`clear` 方法添加 `with self._lock:` 保护

**低严重度：**

9. **日志文件句柄泄漏** — `src/utils/logging.py`：`_open_file` 改为先打开新流成功后再关闭旧流
10. **浏览器上下文泄漏** — `src/utils/login.py`：`close_browser` 将 `__aexit__` 放入独立 finally 块
11. **卸载请求 keys 类型未验证** — `backend/routers/system.py`：添加 `isinstance(keys, list)` 检查
12. **bash 端口检测不可靠** — `setup_env.sh`：移除 `[[ -r /dev/tcp ]]` 检测，直接执行 bash 兜底
13. **侧边栏"更多"菜单注释** — `frontend/partials/sidebar.html`：添加注释说明子页面使用 `currentPage` 赋值（保持菜单展开）而非 `navigateTo()`（会关闭菜单），防止后续误改
14. **监控队列满日志不足** — `backend/monitor_service.py`：warning 日志添加 `qsize()` 信息

**测试更新：**

- `tests/test_system_shutdown.py`：断言从 `os.kill(SIGTERM)` 改为 `os._exit(0)`
- `tests/test_scheduled_tasks.py` + `tests/test_scheduler_extra.py`：`_add_history` 调用添加 `await`


### 全面功能性问题修复（12 项）

**严重问题：**

1. **检测间隔验证单位错误** — `src/utils/config.py:54`：验证器将秒当分钟处理，上限 1440（24分钟）改为 86400（24小时）
2. **浏览器视口尺寸保存后丢失** — `src/utils/config_helpers.py`：`PROFILE_FIELDS` 添加 `browser_viewport_width`、`browser_viewport_height`；`config_service.py` 保存列表同步添加
3. **浏览器导航超时保存后加载丢失** — `src/utils/config_helpers.py`：`PROFILE_FIELDS` 添加 `browser_navigation_timeout`
4. **Ctrl+S 不能保存脚本** — 快捷键功能已整体移除（用户要求）

**中等问题：**

5. **登录操作无法中断** — 保持现状（复杂度高，影响有限）
6. **toggleAutoSwitch 无防抖保护** — `frontend/js/methods/profiles.js`：添加 `_autoSwitchInFlight` 进行中请求保护
7. **脚本导出始终 .py 扩展名** — `frontend/js/methods/scripts.js`：添加 `_inferScriptExtension` 方法，根据 `binary_path` 和 shebang 推断扩展名
8. **脚本导入接受 .exe 但按文本读取** — `frontend/js/methods/scripts.js`：移除 `.exe`，添加 `.ps1`
9. **手动登录网络验证可能误报失败** — `src/task_executor.py`：验证等待时间从 2 秒增加到 5 秒

**低优先级问题：**

10. **调试截图文件名前缀错误** — `src/task_executor.py`：`TaskConfig.from_dict` 和 `to_dict` 添加 `task_id` 序列化
11. **Windows 标准用户孤儿浏览器清理失败** — `src/playwright_worker.py`：`_cleanup_windows` 添加命令行参数回退匹配
12. **自定义变量保留名被静默丢弃** — `src/utils/env.py`：添加 `logger.warning` 日志提示

**其他变更：**

- **移除全部快捷键** — `frontend/js/methods/shortcuts.js` 清空为空导出；`app-options.js` 移除 import、mounted/beforeUnmount 调用、methods 展开
- 测试更新：`tests/test_config_schemas.py` 更新 `test_interval_too_large` 阈值


### 清理任务文件

- `default.json` / `hidden_input.json`: 移除 `metadata.type: "builtin"`（后端无引用）
- `test_http_login.meta.json`: 删除孤立 meta 文件


### 修复 Shell 路径设置无法保存 + 支持自定义路径

**问题：** 设置页面中 Shell 路径选择后保存，刷新后恢复为"自动检测"。

**原因：** `shell_path` 字段在保存、加载、运行时配置构建三个环节均缺失，导致值从未被持久化。

**修复（后端）：**

- `src/utils/config_helpers.py` — `PROFILE_FIELDS` 添加 `shell_path`
- `backend/config_service.py` — `save_config_combined` 系统字段列表添加 `shell_path`
- `backend/config_service.py` — `build_runtime_config` 字段列表添加 `shell_path`
- `backend/scheduler_service.py` — 运行时配置查找路径修正（`config.get("shell_path")` 替代不存在的嵌套路径）

**新增（前端）：**

- 下拉菜单新增「自定义路径...」选项，选择后显示文本输入框
- `app-options.js` — 新增 `shellPathMode` 计算属性（get/set），自动判断当前值是否匹配已知 Shell

**修复（脚本页）：**

- `src/script_runner.py` — `detect_available_binaries()` 候选列表补充 Git Bash（Windows）和 fish（Linux/macOS），与 `detect_available_shells()` 保持一致
- `frontend/partials/pages/scripts.html` — 执行程序下拉选中后显示完整路径提示


### 通知历史分类优化

**前端通知系统重构：**

- `notify()` 新增 `category` 和 `action` 参数，支持通知分类（login / monitor / network / update / security）
- 通知条目增加分类图标（内联 SVG）+ 分类标签（登录/监控/网络/更新/安全）+ 完整日期时间（M/D HH:MM:SS）
- 去掉独立的成功/失败指示器，改用颜色区分（成功绿色、失败红色），作用于图标、标签和消息文字
- 版本更新通知增加「前往下载」链接，点击跳转到关于页面

**通知历史精简（约 50 处改为 toastOnly）：**

- 配置保存、备份创建/恢复/删除/导出
- 任务保存/删除/设置活动任务
- 脚本保存/删除/执行/导出/设为活动
- 调试启动/停止/执行步骤
- 方案保存/删除/切换
- 定时任务创建/删除/切换/手动执行
- 远程任务导入、开机自启动设置、向导保存

**涉及文件：**
- `frontend/js/methods/ui.js` — notify() 方法重构
- `frontend/partials/topbar.html` — 通知模板
- `frontend/styles/components.css` — 通知样式
- `frontend/js/methods/actions.js` — login/monitor 分类
- `frontend/js/methods/status.js` — network 分类
- `frontend/js/methods/lifecycle.js` — update/security/network 分类
- `frontend/js/methods/config.js` — 全部改 toastOnly
- `frontend/js/methods/profiles.js` — 全部改 toastOnly
- `frontend/js/methods/scripts.js` — 全部改 toastOnly
- `frontend/js/methods/autostart.js` — 全部改 toastOnly
- `frontend/js/methods/scheduled_tasks.js` — 全部改 toastOnly
- `frontend/js/tasks/core.js` — 全部改 toastOnly
- `frontend/js/tasks/debug.js` — 全部改 toastOnly
- `frontend/js/tasks/editor.js` — 全部改 toastOnly


### 定时任务调度器按需启动

- `backend/scheduler_service.py`
  - 新增 `has_enabled_tasks()` 方法，检查是否存在启用的定时任务
  - `_scheduler_loop` 轮询间隔从 `sleep(1)` 改为 `sleep(30)`，减少无意义唤醒
  - 循环内检测到无启用任务时自动退出，`_running` 置 False
- `backend/container.py`
  - 启动调度器前检查 `has_enabled_tasks()`，无启用任务则不启动
- `backend/routers/scheduled_tasks.py`
  - 创建、更新、切换启用状态后，若任务为启用状态则调用 `scheduler.start()` 拉起调度器（幂等操作）


### 添加核心逻辑流程图

#### doc/diagrams/ (新增目录)

创建了 6 个 D2 流程图文件，可视化项目核心逻辑：

- **monitor-flow.d2** - 监控主循环流程
  - 暂停时段检查
  - 网络状态检测
  - 登录恢复循环
  - 检测间隔等待

- **login-recovery-flow.d2** - 登录恢复循环详细流程
  - 登录前置检查（物理网络 + 认证地址）
  - 配置方案自动切换
  - 重试次数检查
  - 指数退避重试机制

- **network-detection-flow.d2** - 网络检测流程
  - TCP 连接检测
  - HTTP 请求检测
  - Captive Portal 检测
  - 并行执行与结果汇总

- **task-execution-flow.d2** - 任务执行流程
  - 任务类型判断（脚本/浏览器）
  - 步骤执行循环
  - 各步骤处理器分发

- **variable-resolution-flow.d2** - 变量解析流程
  - 缓存检查
  - 深度限制与循环引用检测
  - 优先级查找（运行时 > 环境 > 任务）

- **architecture-overview.d2** - 架构概览
  - 分层架构展示
  - 组件关系连接

- **README.md** - 流程图说明文档
  - 流程图列表与说明
  - D2 安装与渲染方法
  - 更新维护指南


## 2026-06-04

### 添加核心流程图

- `doc/diagrams/monitor-flow.d2` - 监控主循环流程
- `doc/diagrams/login-flow.d2` - 登录执行流程


## 2026-06-03

### 文档全面更新

#### CLAUDE.md

- **路由文件**：10 → 13 个（新增 `history`, `logfiles`, `scheduled_tasks`）
- **Utils 文件**：10 → 16 个（新增 `config_helpers`, `env`, `exceptions`, `repo_proxy`, `shell_policy`）
- **后端服务文件**：补充了 `container.py`, `deps.py`, `ws_manager.py`, `scheduler_service.py`, `login_history_service.py`, `debug_manager.py`, `debug_session.py`
- **入口点**：补充了 `launcher.py`, `setup_env.sh`
- **核心逻辑**：补充了 `network_detect.py`, `network_test.py`, `script_runner.py`, `version.py`
- **前端结构**：补充了 `bootstrap.js`, `constants.js`, `icons.js`, `logger.js` 和完整的目录结构
- **任务目录**：更新为新的 `browser/`, `scheduled/`, `scripts/` 结构
- **Key Patterns**：补充了 OCR 模型生命周期、两层超时、步骤自动降级等
- **Important Notes**：修复了路由拆分描述、补充了静态挂载、SSL 验证、密钥管理等
- **CLI 参数**：新增 app.py 命令行参数说明

#### README.md

- 更新了完整的项目结构树（包含所有新文件和目录）
- 更新了主要模块说明（按入口、后端、核心逻辑、工具模块分类）

#### doc/api-doc.md

- 新增「登录历史」章节（2 个端点）
- 新增「日志文件」章节（2 个端点）
- 新增「定时任务」章节（8 个端点）

#### doc/task-manual.md

- 更新了网络检测描述（TCP/HTTP/Portal 并发检测）
- 更新了登录流程（区分浏览器任务和脚本任务）

#### doc/change.md

- 创建修改日志文件，用于记录项目所有变更

### 2026-06-09

#### tests/ 测试套件全面优化

- **Phase 1**: 删除 23 个纯重复测试文件（254 个重复用例）
- **Phase 2**: 合并 20 个独立文件的独有测试到综合文件，删除原文件
- **Phase 3**: 新增 8 个 API 路由测试文件（53 个新用例），覆盖 config/tasks/debug/profiles/monitor/history/repo/autostart
- **Phase 4**: 清理 conftest.py 未使用 fixtures，合并剩余重复文件
- **成果**: 80 → 49 文件，1899 → 1584 用例（删除重复 + 新增覆盖），所有测试通过

#### 测试警告修复

- 抑制 StarletteDeprecationWarning（httpx 兼容性，继承自 UserWarning）
- 抑制 RuntimeWarning（Python 3.12 AsyncMockMixin 内部问题）
- 在 pyproject.toml 添加 filterwarnings 配置
- 最终状态：1584 passed, 2 skipped, 0 warnings

### 2026-06-09

#### psutil 简化进程管理和网络检测

- `get_process_name()`: 用 `psutil.Process(pid).name()` 替代 tasklist/ps subprocess（~30 行 → 5 行）
- `is_local_network_connected()`: 用 `psutil.net_if_stats()` 替代 socket + 平台特判（~140 行 → 10 行）
- 删除 `_check_windows_adapter`、`_check_linux_route`、`_check_macos_service`
- 新增 psutil 依赖
