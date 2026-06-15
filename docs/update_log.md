# 更新日志

## v4.0.3

### 新增功能

- **轻量模式托盘支持**：轻量模式新增独立托盘开关（`lightweight_tray`），点击托盘中的"打开控制台"可按需唤醒 Web 管理界面
- **自启动设置独立卡片**：设置页面中自启动相关设置提取为独立的"启动与界面"卡片，包含启动行为、开机自启动、轻量模式托盘、界面行为

### 优化

- 设置页面布局优化：日志管理与日志级别一左一右，控制台端口与网络代理一左一右
- 完善功能描述：轻量模式降低内存占用、托盘增加约 10MB 内存、最小化到托盘降低内存占用等
- 定时任务线程池懒初始化，无任务时不创建线程
- 定时任务线程池 worker 4→2，队列 50→10
- 轻量模式使用 NullTaskExecutor 减少资源占用

### 测试

- 整体覆盖率从 ~70% 提升到 86%
- 新增集成测试：应用启动、登录流程、定时任务
- 补充单元测试：engine、task_executor、process、login、crypto 等模块

### 修复

- 修复 `--tray/--no-tray` 未同时控制轻量模式托盘
- 修复 `execute_login_async` 死锁风险
- 修复轻量模式按需启动 Web 服务时事件循环不匹配
- 修复 `NullWebSocketManager` 未接受 WebSocket 连接
- 修复 CSS 多余闭合括号导致布局失效

---

## v4.0.2

### 新增功能

- **任务编辑器双向同步**：name/description 输入框与 JSON 配置实时双向同步，修改输入框自动更新 JSON，修改 JSON 自动更新输入框

### 修复

- 修复 `is_local_network_connected()` 未正确过滤回环接口的问题（Windows `Loopback Pseudo-Interface 1`、macOS `lo0`）
- 修复手动登录在无配置时误返回 `success=True`
- 修复日志级别下拉选择后显示对应级别及更高级别，默认选中 INFO
- 修复 CustomSelect 下拉框被父容器遮挡问题（改用 `position: fixed`）
- 修复 field-help tooltip 被同级元素遮挡问题（添加 `z-index`）
- 修复 Dashboard 使用的 `getSourceLabel` 方法缺失
- 修复前端 CSS 变量 `--accent-rgb` 缺失、Firefox zoom 兼容、退出页 innerHTML 清理

### 重构

- 删除 `decision.py` 中未使用的 `check_campus_network_status()` 函数及对应测试
- 清理 `tasks` 层死代码（重复 `PROJECT_ROOT`、`execute_remaining`）
- 清理 `services` 层 3 处死代码、`monitor_service.py` 中 4 处死代码和误导注释
- 清理 `utils` 层 3 处死代码（`config_utils`、`logging`、`repo_proxy`）
- 删除 `constants.py` 中 4 个零引用常量
- 删除 `api/__init__.py` 中未使用的 `logged_action` 装饰器
- 删除 `diagnostics.py` shim 文件及对应测试
- 删除 `playwright_bootstrap` 中两个零引用查询函数及对应测试
- 删除 `container.py` 中未使用的 `NullTaskExecutor` 导入和 `_logs_dir` 属性
- 删除 `schemas.py` 方法内重复的 `import re`
- 删除日志文件查看器功能
- 清理 Task 5/6 遗留的孤立导入
- `engine.py` 移除死常量、将循环内 import 移至模块顶部

### 测试

- 补充多模块缺失的测试用例

### 文档

- 全面更新 README.md：修正项目结构、入口文件（`app.py` → `main.py`）、CLI 参数、模块路径
- 全面更新 API 文档：新增日志级别、OCR 管理、脚本二进制列表等端点，移除已删除端点
- 全面更新开发文档：修正架构概览、模块路径、环境变量参考

---

## v4.0.0

### 新增功能

- **Python 脚本任务**：支持通过 Python 脚本直接 HTTP 登录，无需启动 Playwright 浏览器，大幅降低资源占用。脚本运行端点使用运行时配置获取正确的登录参数，输出混合文本时仍能正确提取 JSON
- **Captive Portal 网络探测方式**：新增 `is_network_available_portal()` 函数，支持自定义 URL 和预期内容，与 TCP/HTTP 探测并发执行
- **反检测模式自定义脚本**：新增 `stealth_custom_script` 字段，支持在内置反检测脚本后追加自定义 JavaScript
- **外观设置大幅扩展**：新增动态渐变背景、背景图片上传（保存到服务器，上传时自动清理旧文件）、主题色选择、缩放、毛玻璃效果（含性能降级检测）、侧边栏颜色/透明度/高亮色自定义、卡片透明度、边框可见度等。外观设置独立为导航页面
- **任务和脚本拖拽排序**：支持拖拽调整顺序
- **前端日志面板显示完整后端日志**：打通前端日志到后端链路，刷新时保留 Python logging 系统产生的日志

### 架构重构

- **PlaywrightWorker 线程模型**：所有浏览器操作（任务执行、调试会话、手动登录）统一收归 Worker 线程，实现完整生命周期管理、健康检查、命令队列和浏览器复用。`get_worker()` 支持自动恢复，添加双重检查锁防止并发创建
- **MonitorService Actor 模型**：`queue.Queue` 命令通道替代直接跨线程调用，拉式日志广播，消除 `asyncio.Lock`。移除 `_loop/_loop_stopped` 暴露，简化 `attempt_login` task 追踪
- **网络检测模块拆分**：抽取 `network_probes.py`（TCP/HTTP/Portal 探测）、`network_decision.py`（三个独立检查函数：`check_pause`、`check_network_status`、`check_login_prerequisites`）为独立模块，与 `monitor_core.py` 解耦
- **后端架构全面重构**：`ServiceContainer` 统一管理服务依赖，实现高内聚低耦合。`config_service`、`task_service`、`profile_service`、`monitor_service` 职责清晰分离
- **消除跨模块代码重复**：`schemas.py` 提取 Mixin（`_BrowserFieldsMixin`、`_MonitorFieldsMixin`、`_SharedValidatorsMixin`），统一常量和工具方法
- **safe_mode 重命名为 pure_mode**，新增视口配置项（viewport width/height）

### 监控与状态

- **监控状态详细化**：支持暂停时段、登录重试次数、网络连接状态等详细状态文案，前端实时展示
- **NetworkState 枚举**：替代 `last_network_ok` 布尔值，状态语义更清晰
- **日志与截图目录统一**：`logs/YYYY-MM-DD/app.log` + `logs/YYYY-MM-DD/screenshots/`，合并保留天数为单一设置

### 浏览器与任务

- **网络检测配置重构**：支持独立勾选 TCP/HTTP/Portal 检测方式，检测间隔从分钟改为秒（最低 10 秒）
- **认证地址检查优化**：仅在登录前检查可达性，不影响网络状态判断；不可达时放弃而非重置计数
- **浏览器复用前检查页面存活状态**，修复连续登录失败问题
- **登录失败后浏览器关闭策略分离手动/自动场景**
- **任务执行器优化**：`reveal_hidden` 默认关闭、详细日志、iframe 支持、Captive Portal 支持
- **任务编辑器显示原始 JSON 文件内容**，任务页面与脚本页面隔离显示
- **浏览器设置页重构**：单列布局，"安全与反检测"独立分区

### 前端优化

- **拆分 data()**：将 `app-options.js` 中 110+ 个属性按功能域拆分为 12 个独立模块
- **CSS 变量统一**：扩展设计令牌，统一各页面硬编码颜色值
- **可复用组件**：新增 GlassCard、FormGroup、ToggleSwitch、StatusDot、LoadingSpinner、EmptyState 全局组件
- **设置页重构为 5 标签页**：账号、网络与监控、系统与日志、浏览器、任务
- **日志自动滚动修复**：返回日志页面时自动滚动到最新日志，网络监控横幅出现时日志窗口不再溢出
- **前端日志消息统一为中文**
- **顶栏背景共用侧边栏变量**

### 代码审查修复

共修复 60+ 项问题，涉及可靠性、线程安全和代码质量。

#### 高优先级修复

- **修复 pure_mode 配置污染**：`_runtime_config` 浅拷贝导致 `browser_settings` 嵌套字典被意外修改
- **修复 Worker 单例无法恢复**：`get_worker()` 检测 Worker 线程存活状态，停止后自动重建
- **修复 submit() 永久阻塞**：添加默认超时 300s
- **修复 fetch 初始化阻塞**：`/openapi.json` 请求添加 5 秒 AbortController 超时
- **修复 debug_start 并发竞态**：`POST /api/actions/login` 添加并发守卫，防止多浏览器实例
- **修复消费者线程停止后永久死亡**及手动登录网络检测问题
- **修复调试会话双重启动**与 `run_all` 信号量阻塞
- **修复 `_cleanup_browser` 异常吞没**、`reuse_browser` 不重置、关闭时浏览器残留
- **修复 `_handle_debug_stop`**：创建替代页面而非清空 `_page`
- **修复 network_test TOCTOU** 和 thread-local httpx 缓存泄漏
- **修复 login.py dialog handler 泄漏**：恢复 `page.on("dialog")` 方式并确保每次清理
- **修复 DateRotatingFileHandler close/emit 竞态**，简化 deferred-open
- **HTTP 探测跳过 SSL 证书验证**：避免校园网门户自签名证书误判网络异常
- **过滤 APIPA 地址**、浏览器健康检查超时等多处 WiFi 断连修复

#### 中优先级修复

- **PID 锁文件稳健化**：进程身份验证 + 退出清理 + VBS 兼容
- **跨平台探活修复**：处理 `os.kill(pid,0)` 的 CPython SystemError 和 WinError 87
- **收窄异常捕获范围**：`wait_for_selector` 只捕获 `TimeoutError`，分离业务异常与编程 bug
- **添加线程安全**：`_root_configured` 使用双检锁模式，`OcrHandler` 添加锁保护
- **消除 utils → backend 反向依赖**：`VALID_LOG_LEVELS` 直接定义在 `logging.py`
- **统一日志级别判断**：前端 `getLogClass()` 改用 `item.level` 字段
- **settings.json 数值越界时自动钳制**而非校验失败
- **signal handler 简化**：统一使用 `os._exit(0)`
- **移除 requests 依赖**，移除 WebSocketManager `asyncio.Lock`
- **前端 `beforeUnmount` 添加定时器清理**
- **pip 安装子进程添加 `--proxy` 空值参数**，避免 Windows 注册表代理导致安装失败

### 测试

- 全面扩展测试覆盖，新增 PlaywrightWorker、网络探测层、决策层、任务执行器等模块测试
- 测试数量从 281 增至 747，全部通过

### 工程化

- **ruff format 全项目格式化**
- **删除 ConfigLoader 类及级联死代码**，移除独立卸载脚本 `uninstall.py`
- **time.py 重命名为 time_utils.py** 避免遮蔽标准库
- **API 文档迁移**至 `docs/api-doc.md`，README 精简
- **pyrightconfig.json、CLAUDE.md、.omo 等加入 gitignore**

---

## v3.7.2

### 前端优化

- **拆分 data()**：将 app-options.js 中 110+ 个属性按功能域拆分为 12 个独立模块（dashboard, config, tasks, scripts, debug, profiles, repo, uninstall, ui, websocket, timers, status）
- **CSS 变量统一**：扩展设计令牌（bg-glass, border-accent, shadow-accent, blur 等），统一各页面硬编码颜色值，添加毛玻璃效果降级规则
- **可复用组件**：新增 GlassCard, FormGroup, ToggleSwitch, StatusDot, LoadingSpinner, EmptyState 全局组件
- **日志优化**：日志列表上限从 300 降低到 100，减少 DOM 元素数量

### 代码审查修复

共修复 25 项问题，涉及 15 个文件。

#### 高优先级修复（可靠性/性能）

- **修复 pure_mode 配置污染**：`_runtime_config` 浅拷贝导致 `browser_settings` 嵌套字典被意外修改，影响后续非 pure_mode 登录场景
- **修复 Worker 单例无法恢复**：`get_worker()` 现在检测 Worker 线程存活状态，停止后自动重建
- **修复 submit() 永久阻塞**：添加默认超时 300s（`_DEFAULT_SUBMIT_TIMEOUT`），防止 Worker 崩溃时调用线程挂起
- **修复 fetch 初始化阻塞**：`/openapi.json` 请求添加 5 秒 AbortController 超时
- **收窄异常捕获范围**：`wait_for_selector` 只捕获 `TimeoutError`，`execute()` 分离业务异常与编程 bug
- **修复 read_text() 未捕获异常**：脚本文件读取失败时返回 None 而非 500 崩溃
- **添加端口配置日志**：`_resolve_port` 配置解析失败时记录 warning 而非静默回退
- **添加 WebSocket 异常日志**：通信异常时记录完整堆栈

#### 中优先级修复（代码质量）

- **消除 utils → backend 反向依赖**：`VALID_LOG_LEVELS` 直接定义在 `logging.py`
- **添加线程安全**：`_root_configured` 使用双检锁模式
- **统一日志级别判断**：前端 `getLogClass()` 改用 `item.level` 字段
- **统一日志级别常量**：`_shouldShowLog` 使用 `LOG_LEVELS` 替代硬编码
- **修复 checkInitStatus 向导抑制**：区分网络错误和服务端错误
- **添加 auto_open_browser 默认值**：配置加载失败时显式设为 False
- **改进异常日志**：`close_browser` 异常从 DEBUG 提升为 WARNING
- **添加 chmod exc_info**：密钥文件权限失败时保留完整错误信息
- **修复 __aexit__ 格式化异常**：添加 try/except 防止二次异常
- **更新过时注释**：browser.py 文档与实现保持一致
- **清理 _toastLeavingTimer**：beforeUnmount 中添加定时器清理
- **添加 URL 格式验证**：`validate_env_config` 检查 auth_url 协议前缀
- **返回缓存副本**：`_get_test_sites` 返回 list 副本防止缓存污染
- **暴露公共属性**：MonitorService 添加 `ws_broadcast_queue`、`logs` property

### 测试

- 更新 `test_caching` 测试适配副本返回语义
- 全部 747 个测试通过

---

## v3.7.1

### 新增功能

- **Captive Portal 网络探测方式**：新增 `is_network_available_portal()` 函数，支持自定义 URL 和预期内容，与 TCP/HTTP 探测并发执行，降低总检测延时
- **反检测模式自定义脚本**：新增 `stealth_custom_script` 字段，支持在内置反检测脚本后追加自定义 JavaScript 脚本

### 重构优化

- **统一文案**：全项目"探测"统一改为"检测"
- **日志系统优化**：敏感信息降级 DEBUG、冗余日志降级 DEBUG、级别修正、补充上下文、统一格式
- **任务执行器优化**：`reveal_hidden` 默认关闭、详细日志、iframe 支持、`ClickHandler` 超时动态计算
- **检测间隔单位调整**：从分钟改为秒，最低 10 秒，移除 `*60` 转换
- **认证地址检查重构**：仅在登录前检查，不影响网络状态判断；不可达时放弃而非重置计数
- **代码去重**：schemas.py 提取 Mixin、task_executor 基类提取 `_parse_selectors()`、playwright_worker 合并清理方法
- **设置页重构**：浏览器设置页"禁用同源策略"和"反检测模式"独立为"安全与反检测"分区

### 修复

- 手动网络测试遗漏 `portal_checks` 参数传递
- 修复 Portal toggle 状态不同步，探测方式独立成卡片
- 修复网络探测方式 toggle 样式重叠
- 登录失败后浏览器关闭策略分离手动/自动场景
- 浏览器复用前检查页面存活状态，修复连续登录失败问题
- 认证地址不可达时改为放弃而非重置计数

### 测试

- 合并精简测试文件，扩展测试覆盖（测试数量从 158 增至 281）

### 文档

- 更新 README.md

---

## v3.7.0

### 架构重构

- **PlaywrightWorker 线程模型**：所有浏览器操作（任务执行、调试会话、手动登录）统一收归 Worker 线程，消除跨线程 asyncio 竞态。新增健康检查、命令队列、浏览器复用与生命周期管理
- **MonitorService Actor 模型**：queue.Queue 命令通道替代直接跨线程调用，拉式日志广播，消除 asyncio.Lock
- **网络探测层拆分**：抽取 `network_probes.py`（TCP/HTTP 探测）、`network_decision.py`（决策编排）为独立模块，与 `monitor_core.py` 解耦
- **schemas.py DRY 重构**：提取 `_BrowserFieldsMixin`、`_MonitorFieldsMixin`、`_SharedValidatorsMixin`，消除 `MonitorConfigPayload` 与 `ProfileSettings` 约 30 个重复字段

### 监控与状态显示

- **监控状态详细化**：支持暂停时段、登录重试次数、网络连接状态等详细状态文案，前端实时展示
- **NetworkState 枚举**：替代 `last_network_ok` 布尔值，状态语义更清晰
- **网络验证日志优化**："网络检测兜底"→"验证网络连通性"，"成功条件不满足"→"网络验证未通过"
- **修复监控重试次数 off-by-one** 和浏览器关闭不一致问题
- **修复首次检测状态显示**，区分"正在检测"和"网络异常"

### 日志与截图

- **统一日志与截图目录结构**：`logs/YYYY-MM-DD/app.log` + `logs/YYYY-MM-DD/screenshots/`，替代原来分散的 `logs/` 和 `debug/`
- **合并日志与截图保留天数**为单一"日志保留天数"设置，过期日期目录整体删除
- **日志文件写入优化**：缓冲写入，每 10 行或 5 秒刷新
- **DateRotatingFileHandler 竞态修复**：close/emit 线程安全

### 浏览器与任务

- **safe_mode 重命名为 pure_mode**，新增视口配置项（viewport width/height）
- **网络检测配置重构**：支持独立勾选 TCP/HTTP 检测方式，新增 `check_auth_url` 开关
- **OcrHandler 线程安全**：添加锁保护，移除 navigate 死代码
- **HTTP 探测跳过 SSL 证书验证**：避免校园网门户自签名证书误判网络异常
- **登录弹窗监听修复**：恢复 `page.on("dialog")` 方式，确保每次执行后清理监听器
- **前端日志消息统一为中文**

### 进程与系统

- **PID 锁文件稳健化**：进程身份验证 + 退出清理 + VBS 兼容
- **跨平台探活修复**：处理 `os.kill(pid,0)` 的 CPython SystemError 和 WinError 87
- **signal handler 简化**：统一使用 `os._exit(0)`
- **get_worker() 双重检查锁**：防止并发创建 Worker 实例

### 工程化

- **项目系统性审查优化**：18 项问题修复（socket 上下文管理器、密码掩码长度泄漏、依赖版本上界、ThreadPoolExecutor atexit 钩子等）
- **补充 158 个单元测试**：覆盖 crypto、time_utils、network_helpers、config_validator、schemas、file_helpers、platform_utils、config_helpers、str_to_bool、version、network_decision
- **uv.lock 纳入版本控制**，`.gitignore` 移除 `tests/` 和 `uv.lock` 条目
- **pyproject.toml 依赖版本上界**：fastapi、pydantic、httpx、uvicorn、websockets

### 前端

- **设置页重构为 5 标签页**：账号、网络与监控、系统与日志、浏览器、任务
- **远程仓库导入弹窗滚动优化**
- **提取 `BROWSER_ARGS_DEFAULT` 常量**、`getApiError` 工具函数、`_showToast` 复用
- **autostart enable/disable 合并**为 `_toggleAutostart`
- **系统托盘菜单动态文本**：反映实际监控运行状态

### 修复

- 修复调试会话双重启动与 run_all 信号量阻塞
- 修复消费者线程停止后永久死亡及手动登录网络检测问题
- 修复 network_test TOCTOU 和 thread-local httpx 缓存泄漏
- 修复 login.py dialog handler 泄漏
- 修复 `_cleanup_browser` 异常吞没、reuse_browser 不重置、关闭时浏览器残留
- 修复 debug_start 并发竞态、`_handle_debug_stop` 页面清空问题
- 过滤 APIPA 地址、浏览器健康检查超时、认证地址前置探测等多处 WiFi 断连修复
- 修复 task_executor 及录制器的 6 项问题
- 修复密码输入相关 6 个 bug

---

## v3.6.7

- **隐藏输入框处理全面重构**：新增 `reveal_hidden` 配置，执行前自动显示所有隐藏输入框；普通 fill/click 失败后自动降级到 force 模式，无需手动配置
- **任务录制器重大升级**：智能检测统一模式、成功条件下拉选择、步骤可编辑；点击高亮元素弹出步骤选择菜单；新增显示隐藏模式（绿色虚线高亮 + 浮动标签 + 左侧独立面板）
- **成功条件判断逻辑重构**：移除录制器中的成功条件判断，统一由后端网络检测兜底；修复 success_conditions 空数组被静默丢弃的问题
- **环境变量命名规范化**：所有 `Campus-Auth_` 前缀改为 `CAMPUS_AUTH_`，移除 python-dotenv 依赖和 .env 文件加载
- **登录流程优化**：提取 `build_login_template_vars` 为共享工具；修复浏览器初始化时 `browser_manager` 未绑定警告；页面弹窗拦截并延迟 1.5s 关闭，记录内容到日志
- **性能优化**：普通 fill/click 首次超时从 3s 降到 1.5s；URL 稳定检测上限从 5s 降至 3s；导航后页面稳定等待从 2s 降至 1s；登录成功后等待 2s 再做网络检测；监控循环增加 2s 缓冲
- **设置页支持 `app_port` 配置**：修复 shutdown 和端口解析问题
- **新增核心模块单元测试覆盖**
- **修复嵌入式 Python 启动报错**：启动时自动将项目根目录加入 `sys.path`
- **合并 `custom_js` 到 `eval`**：简化任务类型，统一使用 `eval` 执行 JS，保留向后兼容
- **录制器 Prompt 优化**：优先推荐 `type="password"` 选择密码框，增加失败后 AI 反馈循环机制（提供 `eval` 兜底脚本）
- **清理前端 UI 重复的 `eval` 描述**

---

## v3.6.4

- **`login_then_exit` 改为重试直到成功**：不再一次失败就退出，指数退避重试（最多 3 次），超限后回退到正常模式启动服务器，避免误判导致服务停止。
- **新增 `--no-auto` 启动参数**：跳过自动登录和自动启动监控，用于 `login_then_exit` 开启后无法进入 Web 控制台的恢复场景。
- **设置页新增重试配置**：最大登录重试次数（1~5）和重试间隔秒数（1~300），`monitor_core` 侧强制限幅 1~5 防止异常配置。
- **任务录制器改为生成 AI 提示词**：移除直接导出 JSON/Markdown，改为复制结构化提示词，发送给 AI 模型即可生成任务 JSON。提示词自动汇总步骤类型映射、隐藏输入框警告、验证码说明和成功条件。
- **任务录制器快捷键改为 `Ctrl+Shift+E`**：避免与浏览器强制刷新快捷键冲突。
- **任务编写指南禁止硬编码 URL**：分享/提交任务时 `url` 字段须留空或使用 `{{LOGIN_URL}}`，由用户自行配置认证地址。
- 文档/打包/环境脚本配套更新。

---

## v3.6.3

- **`input` 步骤新增 `force` 参数**：支持对 `display:none` 的隐藏输入框强制填入值，通过 JS 原生 setter + 事件派发实现，解决部分校园网门户密码框隐藏的问题。
- **任务录制器（油猴脚本）隐藏输入框检测**：统一检测假 type=text 占位框和 readonly 占位框 + 隐藏输入框两类隐藏输入框模式，同时覆盖账号和密码输入框；检测到后导出自动生成 click 占位 + force 输入步骤。
- **任务录制器（油猴脚本）独立功能开关**：新增「多步录制」和「隐藏检测」两个独立按钮，多步录制开启后每次点击记录一步不自动停止，隐藏检测控制是否自动扫描 `display:none` 输入框；Enter 键在录制模式下可记录悬停元素而不触发页面 click；面板内建可折叠详细说明和使用手册弹窗。
- **任务录制器（油猴脚本）DOM 守护**：MutationObserver + 定时轮询双保险，防止门户 JS 在 `document-idle` 后冲刷 `body.innerHTML` 导致浮动按钮/面板消失。
- 修复部分校园网门户录制时密码步骤选择器指向假输入框导致填表失败的问题。

---

## v3.6.2

- 重构配置读写分离：设置页面始终展示和修改全局设置，方案页面管理方案独立设置。
- 修复方案启用"使用全局高级设置"时，设置页面修改 headless 等高级选项保存后刷新又变回默认值的问题。
- 修复网络状态 UI 不能准确反映实际连接状态的问题。
- 反检测脚本改为默认关闭，修复首页一键登录页面空白问题。

---

## v3.6.1

- Mac/Linux 支持下载嵌入式 Python 3.10，与 Windows 保持一致。
- 物理网络断开时跳过登录，避免无意义的浏览器启动。
- Playwright 检测同步检查 chromium_headless_shell，确保完整浏览器环境就绪。
- 修复登录失败时前端重复渲染截图的问题。
- 修复日志自动滚动失效的问题。

---

## v3.6.0

- 新增 OCR 验证码自动识别（ddddocr），支持截图识别并填入输入框。
- 新增任务步骤支持 `<frame>` 上下文（frameset/iframe 页面）。
- 新增录制器支持 `<frame>` 元素检测和事件绑定。
- 新增远程任务仓库导入，支持浏览、搜索、一键下载社区适配方案。
- 新增卸载功能，支持前端界面和命令行两种方式，清理自启动、加密密钥、浏览器缓存等外部残留。
- 新增关于页面检查更新功能。
- 新增登录请求超时设置。
- 重构任务系统，优化任务编辑器和 JSON 配置体验。
- 重构日志系统，打通前端日志到后端链路，支持 WebSocket 实时推送和按级别筛选。
- 监控重试时复用浏览器实例，避免重复开关。
- 浏览器复用前添加健康检查，避免使用已崩溃的实例。
- 改进网络连接检测：支持有线/无线网络实际连接状态检查，避免无网络时徒增功耗。
- HTTP 网络检测仅将 2xx 状态码视为成功（修复认证门户 302 重定向误判）。
- Windows 网关检测改用 PowerShell Get-NetRoute（结构化输出，不受系统语言影响）。
- macOS SSID 检测添加 networksetup 回退方案。
- Windows SSID 检测修复非 ASCII SSID 的编码问题。
- Linux 自启动修复路径含空格时的引号处理问题。
- 改进浏览器反检测脚本：模拟真实 PluginArray、完善 chrome 对象属性、覆盖 languages。
- 改进低资源模式：除图片外同时屏蔽字体和媒体文件。
- setup/launcher 镜像源优先级改为 CERNET，Python 下载添加多源回退和进度条。
- 前端 UI 优化：任务页标题改为"任务列表"，关于页标题分行显示中英文。
- 移除 API_TOKEN 鉴权功能（本地项目无需对外鉴权）。
- 修复复制任务时 ID 覆盖问题。
- 修复危险确认对话框页面切换后 Promise 永久挂起问题。
- 修复 CORS 端口与实际服务端口不一致问题。
- 修复代码审查发现的多项 Bug。

---

## v3.3.0

- 替换项目 Logo 为新图标。
- 全面更新文档：合并任务文档、同步新特性、清理过时内容。
- 清理仓库：移除废弃代码、更新 .gitignore。

---

## v3.2.0

- 新增多网络配置方案（Profiles）系统：支持为不同网络环境创建独立配置，按网关 IP 或 WiFi SSID 自动切换。
- 新增配置方案管理页面（profiles.html）。
- 新增网关 IP 和 WiFi SSID 跨平台检测。
- 优化任务执行器序列化（to_dict），输出更紧凑。
- 规范化 eval 步骤字段：统一使用 script，兼容已废弃的 code。
- 新增任务导入导出、复制功能。
- 新增 eval 步骤安全确认对话框。
- 新增 API 写操作鉴权（API_TOKEN）。
- 新增日志按级别筛选和文本搜索。
- 新增截图链接点击查看。
- 新增 WebSocket 断线重连（指数退避）。
- 新增未保存配置检测提醒。
- 新增服务关闭 API（/api/shutdown）。
- 移除未使用的骨架屏动画和代码预览样式。
- 新增 step/condition 的 to_dict 方法，优化任务存储格式。
- 添加任务执行器单元测试覆盖。

---

## v3.1.0

- 优化 WebSocket 实时日志推送。
- 添加日志自动滚动功能。
- 精细化异常处理。
- 添加配置管理单例模式。
- 添加任务执行器变量解析缓存。

---

## v3.0.1

- 初始稳定版本。
- Web 控制台。
- 任务系统。
- 系统托盘支持。
