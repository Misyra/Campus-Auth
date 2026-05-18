# Campus-Auth 开发文档

本文档面向开发者，详细描述 Campus-Auth 的内部架构、执行流程、API 接口及配置参考。如需编写任务 JSON，请参阅 [任务编写指南](task-writing-guide.md)。

## 目录

1. [架构概览](#架构概览)
2. [任务执行流程](#任务执行流程)
3. [变量解析机制](#变量解析机制)
4. [Frame 上下文切换](#frame-上下文切换)
5. [浏览器反检测](#浏览器反检测)
6. [错误处理与重试](#错误处理与重试)
7. [截图机制](#截图机制)
8. [校验规则](#校验规则)
9. [任务文件管理](#任务文件管理)
10. [API 参考](#api-参考)
11. [环境变量参考](#环境变量参考)

---

## 架构概览

系统由四层组成，自上而下依次调用：

```
NetworkMonitorCore          网络监控循环（检测断网、触发登录、重试退避）
    └── LoginAttemptHandler     登录处理器（加载任务、构建环境变量、管理浏览器生命周期）
            └── TaskExecutor        任务执行器（解析模板、执行步骤序列、判定成功条件）
                    └── StepHandler          步骤处理器（单个步骤的具体执行逻辑）
```

### 核心模块

| 模块 | 文件 | 职责 |
|------|------|------|
| `NetworkMonitorCore` | `src/monitor_core.py` | 网络检测循环、重试退避、Profile 自动切换 |
| `LoginAttemptHandler` | `src/utils/login.py` | 任务加载、环境变量构建、浏览器生命周期管理 |
| `BrowserContextManager` | `src/utils/browser.py` | Playwright 浏览器启动与配置、反检测注入 |
| `TaskExecutor` | `src/task_executor.py` | 步骤执行引擎、变量解析、成功条件判定 |
| `TaskValidator` | `src/task_executor.py` | 任务 JSON 校验 |
| `TaskManager` | `src/task_executor.py` | 任务文件的 CRUD 操作 |
| `TaskService` | `backend/task_service.py` | 任务 API 的后端服务层 |

---

## 任务执行流程

### 从监控到登录的完整链路

**1. 网络检测（NetworkMonitorCore）**

`monitor_network()` 主循环每次迭代：
- 检查是否在暂停时段内
- 对配置的探测目标（默认 `8.8.8.8:53`、`114.114.114.114:53`、`www.baidu.com:443`）发起 TCP 连接测试
- 连接失败则调用 `attempt_login()`

**2. 登录准备（LoginAttemptHandler）**

`_perform_login_with_active_task()` 的执行步骤：
1. 通过 `TaskManager.get_active_task()` 获取当前活动任务 ID
2. 加载对应的 `TaskConfig` JSON 文件
3. 构建环境变量字典（覆盖顺序见下方）
4. 检查浏览器健康状态（如启用浏览器复用），必要时重建
5. 创建 `TaskExecutor` 并调用 `executor.execute(page)`

**环境变量构建的覆盖顺序：**
1. 系统环境变量（`os.environ`）
2. `LOGIN_URL` ← config 的 `auth_url`
3. `LOGIN_URL` ← 任务的 `url` 字段（经过模板解析）
4. `ISP`、`USERNAME`、`PASSWORD` ← config
5. 自定义变量 ← `config["custom_variables"]`（过滤掉系统保留变量名如 `PATH`、`HOME` 等）

**3. 步骤执行（TaskExecutor）**

`execute(page)` 的流程：
1. 记录任务开始时间，计算全局超时截止时间
2. 调用 `_auto_navigate(page)` 自动导航到认证地址
3. 遍历 `config.steps`：
   - 检查是否超过全局超时
   - 跳过 `navigate` 类型步骤（已由自动导航处理）
   - 步骤间休眠 0.5 秒
   - 从 `StepExecutorRegistry` 查找对应的 `StepHandler`
   - 调用 `handler.execute(page, step, resolver)`
    - 记录步骤结果；任一步骤失败立即终止
 4. 所有步骤成功后，执行网络检测兜底判断

 **4. 网络检测兜底**

 系统统一使用网络连通性检测判断任务成功与否：任务步骤全部完成后，自动检测网络是否可达。网络通 = 认证成功，网络断 = 认证失败。原有 `success_conditions` 字段仅保留兼容性，不再参与判断。

---

## 变量解析机制

### VariableResolver

模板语法：`{{变量名}}`，正则匹配 `\{\{(\w+)\}\}`。

**四级查找优先级（从高到低）：**

| 优先级 | 来源 | 说明 |
|--------|------|------|
| 1 | 运行时变量 | `eval`/`ocr` 步骤通过 `store_as` 写入，以及任务元数据（`url`、`name`、`description`） |
| 2 | 用户自定义变量 | Web 控制台设置页面中配置的自定义变量 |
| 3 | 环境变量 | OS 环境变量 + config 覆盖 |
| 4 | 任务变量 | 任务 JSON 的 `variables` 字段（自身也支持模板引用） |

**递归解析规则：**
- 解析后的值如果仍包含 `{{`，会递归解析，最大深度 8 层
- 循环引用检测：维护 `visited` 集合，重复出现的变量名会抛出 `StepError`
- 未找到的变量：原样保留 `{{VAR}}` 在输出中（不报错）
- 缓存：首次解析的结果会被缓存，`set_runtime_var()` 调用时清除缓存

**解析的触发点：**
- `StepHandler.resolve_params()` — 解析步骤的所有字段
- `_auto_navigate()` — 解析任务的 `url` 字段
- `LoginAttemptHandler` — 解析任务 URL 后存入环境变量

---

## Frame 上下文切换

通过步骤的 `frame` 字段指定目标 frame，`StepHandler._resolve_frame()` 依次尝试三种定位方式：

1. **按 name 属性：** `page.frame(name=frame_selector)`
2. **按 URL 匹配：** `page.frame(url=frame_selector)`
3. **按 CSS 选择器：** `page.frame_locator(frame_selector)`

如果三种方式都失败，系统会回退到主页面继续执行（不会直接失败），这是一种容错设计。

返回的 frame 对象作为 `ctx` 传入 `_find_element()`，所有元素查找都在该上下文中进行。

---

## 浏览器反检测

`BrowserContextManager._start_browser()` 通过 `page.add_init_script()` 在页面 JavaScript 执行前注入反检测脚本：

### 注入的 JavaScript

**隐藏自动化标志：**
```js
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
```

**伪造插件列表：** 模拟 Chrome 默认的三个插件（Chrome PDF Plugin、Chrome PDF Viewer、Native Client），包含完整的 `item()`、`namedItem()` 方法和 `Symbol.iterator` 支持。

**伪造 chrome 对象：**
```js
window.chrome = {
    runtime: { connect: function(){}, sendMessage: function(){} },
    loadTimes: function() { return {}; },
    csi: function() { return {}; },
};
```

**语言覆盖：** `navigator.languages = ['zh-CN', 'zh', 'en-US', 'en']`

**清理 Playwright 痕迹：** `delete window.__playwright; delete window.__pw_manual;`

### 浏览器上下文配置

| 配置项 | 值 | 说明 |
|--------|-----|------|
| `has_touch` | `false` | 桌面模式 |
| `color_scheme` | `"light"` | 浅色主题 |
| `locale` | `"zh-CN"` | 中文语言 |
| `timezone_id` | `"Asia/Shanghai"` | 上海时区 |
| `ignore_https_errors` | `True` | 忽略 HTTPS 证书错误 |
| `user_agent` | 可自定义 | 来自 config 的 `browser_user_agent` |
| `extra_http_headers` | 可自定义 | 来自 config 的 `browser_extra_headers_json` |

### 低资源模式

启用后通过 Playwright 的路由功能拦截以下请求类型：
- 图片（`image`）
- 字体（`font`）
- 媒体（`media`）

返回空响应，减少带宽和内存占用。

### 安全模式

使用纯净 Chromium 启动（不加载任何扩展），通过 `--disable-extensions` 参数实现，用于解决浏览器插件冲突问题。

---

## 错误处理与重试

### 任务执行层面

- 每个步骤的执行都包裹在 try/except 中，异常被捕获并返回 `(False, 错误信息)`
- 全局超时：每步执行前检查 `perf_counter() - start > timeout / 1000`，超时立即失败
- 任一步骤失败 → 调用 `_handle_failure()` → 截图 + 构建错误消息 → 返回

### 监控重试机制

`NetworkMonitorCore` 的重试策略：

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `retry_settings.max_retries` | 3 | 最大重试次数 |
| `retry_settings.retry_interval` | 5 | 基础重试间隔（秒） |

**退避算法：** 指数退避，第 N 次重试的等待时间为 `retry_interval × 2^(N-1)`。
- 默认配置下：5s → 10s → 20s

**重试结果：**
- `"retry"` — 等待后重试
- `"break"` — 等待期间监控被停止
- `"give_up"` — 所有重试用尽，重置计数器，回到正常检测间隔

**通知：** 第 2 次失败和放弃时会发送桌面通知。

### 浏览器复用与健康检查

启用浏览器复用时，每次登录前检查：
- `browser.is_connected()` — 浏览器进程是否存活
- `not page.is_closed()` — 页面是否仍然打开

检查失败则关闭旧浏览器并创建新的。

### 可中断等待

`_wait_interruptible(seconds, step)` 以 5 秒为单位分段休眠，每段检查 `self.monitoring` 标志。如果监控在等待期间被停止，立即返回 `False`，实现优雅退出。

---

## 截图机制

### 自动失败截图

当 `on_failure.screenshot` 不为 `false`（默认 `true`）时，任务失败会自动截图：

- 保存目录：`debug/{YYYY-MM-DD}/`
- 文件名格式：`{task_id}_{YYYYMMDD_HHMMSS_microseconds}.png`
- 截图方式：`page.screenshot(path=..., full_page=True)`
- 返回 URL 路径如 `/debug/2026-05-09/taskid_20260509_143022_123456.png`，追加到失败消息中

### 手动截图步骤

任务中的 `screenshot` 步骤：
- 保存目录同上
- 指定 `path` 时仅取文件名（目录由系统管理）
- 未指定时自动生成 `{task_id}_{step_id}_{timestamp}.png`

### 调试模式截图

逐步调试时，每步执行完成后都会自动截图，用于在调试面板中展示每步的页面状态。

---

## 校验规则

### 任务级校验

| 规则 | 错误信息 |
|------|----------|
| 必须包含 `name` 字段 | "任务必须包含 'name' 字段" |
| 必须包含 `steps` 字段 | "任务必须包含 'steps' 字段" |
| `steps` 必须是数组 | "'steps' 必须是数组" |

### 步骤级校验

每个步骤必须包含 `id` 和 `type` 字段。`type` 必须是以下之一：

`navigate`（已废弃）、`input`、`click`、`select`、`click_select`、`wait`、`wait_url`、`eval`、`custom_js`、`screenshot`、`sleep`、`ocr`

各类型的额外必填字段：

| 类型 | 必填字段 |
|------|----------|
| `navigate`（已废弃，请使用任务的 `url` 字段） | `url` |
| `input` | `selector` |
| `click` | `selector` |
| `select` | `selector` |
| `click_select` | `selector` |
| `wait` | `selector` |
| `wait_url` | `pattern` |
| `eval` | `script`（兼容已废弃的 `code`） |
| `custom_js` | `script`（兼容已废弃的 `code`） |
| `screenshot` | 无 |
| `sleep` | 无 |
| `ocr` | `selector` |

### 成功判断

系统统一使用网络连通性检测判断任务成功与否（详见 [任务编写指南](task-writing-guide.md)）。原有 `success_conditions` 字段仅保留兼容性，不再参与判断。

### 危险步骤检测

`eval` 和 `custom_js` 步骤会被标记为危险步骤。后端保存时会记录警告日志（包含代码内容，截断至 2000 字符），前端会弹出安全确认对话框。此检测不会阻止保存，仅做提醒。

### Task ID 校验

正则：`^[A-Za-z][A-Za-z0-9_]*$`（必须以字母开头，只能包含字母、数字、下划线）。

---

## 任务文件管理

### 存储结构

```
tasks/
├── active.txt          # 当前活动任务 ID（纯文本）
├── default.json        # 内置默认任务
└── *.json              # 用户自定义任务
```

### TaskManager 操作

| 方法 | 说明 |
|------|------|
| `load_task(task_id)` | 加载指定任务，返回 `TaskConfig` 对象 |
| `save_task(task_id, config)` | 校验后保存任务 JSON（`ensure_ascii=False, indent=2`） |
| `list_tasks()` | 列出所有任务的 `{id, name, description}` |
| `get_active_task()` | 读取 `active.txt`，不存在时返回 `"default"` |
| `set_active_task(task_id)` | 校验 ID 和文件存在性后写入 `active.txt` |
| `delete_task(task_id)` | 删除任务文件，`"default"` 不可删除 |

### 安全措施

路径遍历防护：`_safe_task_path()` 解析路径后验证是否在 `tasks_dir` 范围内，防止 `../` 攻击。

---

## API 参考

### 任务管理

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/tasks` | 列出所有任务 |
| GET | `/api/tasks/{id}` | 获取指定任务 |
| PUT | `/api/tasks/{id}` | 创建/更新任务 |
| DELETE | `/api/tasks/{id}` | 删除任务（`default` 不可删除） |
| GET | `/api/tasks/active` | 获取当前活动任务 |
| POST | `/api/tasks/active/{id}` | 设置活动任务 |

### 配置管理

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/config` | 获取当前配置 |
| PUT | `/api/config` | 保存配置 |
| GET | `/api/init-status` | 获取初始化状态 |

### 配置方案（Profiles）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/profiles` | 列出所有方案 |
| GET | `/api/profiles/active` | 获取活动方案详情 |
| GET | `/api/profiles/{id}` | 获取指定方案 |
| PUT | `/api/profiles/{id}` | 创建/更新方案（活动方案会热重载） |
| DELETE | `/api/profiles/{id}` | 删除方案（`default` 不可删除） |
| POST | `/api/profiles/active/{id}` | 设置活动方案 |
| POST | `/api/profiles/detect` | 检测当前网络环境 |
| POST | `/api/profiles/auto-switch` | 切换自动切换开关 |

### 监控控制

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/status` | 获取监控状态 |
| POST | `/api/monitor/start` | 启动监控 |
| POST | `/api/monitor/stop` | 停止监控 |

### 手动操作

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/actions/login` | 手动触发登录 |
| POST | `/api/actions/test-network` | 测试网络连通性 |

### 日志

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/logs?limit=200` | 获取历史日志（内存缓冲区，最多 1200 条） |
| WS | `/ws/logs` | WebSocket 实时日志流 |

### 自启动

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/autostart/status` | 获取自启动状态 |
| POST | `/api/autostart/enable` | 启用自启动 |
| POST | `/api/autostart/disable` | 禁用自启动 |

### 配置备份

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/backup/list` | 列出所有备份 |
| POST | `/api/backup/create` | 创建备份 |
| POST | `/api/backup/restore/{filename}` | 恢复备份 |
| GET | `/api/backup/download/{filename}` | 下载备份文件 |
| DELETE | `/api/backup/{filename}` | 删除备份 |

### 卸载

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/uninstall/detect` | 检测可清理的外部残留 |
| POST | `/api/uninstall` | 执行卸载清理 |

### 系统

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/health` | 健康检查，返回状态和版本 |
| POST | `/api/shutdown` | 关闭服务 |

### 静态文件

| 路径 | 说明 |
|------|------|
| `/debug/` | 截图文件的静态访问 |
| `/temp/` | 调试截图临时目录 |

---

## 环境变量参考

### 认证配置

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `USERNAME` | — | 校园网用户名 |
| `PASSWORD` | — | 校园网密码（支持 `ENC:` 前缀加密存储） |
| `LOGIN_URL` | `http://172.29.0.2` | 认证页面地址 |
| `ISP` | 空 | 运营商关键字 |

### 服务配置

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `APP_PORT` | `50721` | Web 控制台端口 |

### 监控配置

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `AUTO_START_MONITORING` | `false` | 启动后是否自动开始监控 |
| `MONITOR_INTERVAL` | `300` | 检测间隔（秒） |
| `PING_TARGETS` | `8.8.8.8:53,114.114.114.114:53,www.baidu.com:443` | 探测目标 |
| `MAX_CONSECUTIVE_FAILURES` | `3` | 连续失败次数上限 |

### 暂停时段

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `PAUSE_LOGIN_ENABLED` | `true` | 是否启用暂停时段 |
| `PAUSE_LOGIN_START_HOUR` | `0` | 暂停开始（0-23） |
| `PAUSE_LOGIN_END_HOUR` | `6` | 暂停结束（0-23） |

### 浏览器配置

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `BROWSER_HEADLESS` | `true` | 无头模式 |
| `BROWSER_TIMEOUT` | `8000` | 浏览器超时（毫秒） |
| `BROWSER_LOW_RESOURCE_MODE` | `false` | 低资源模式（屏蔽图片、字体、媒体） |
| `BROWSER_USER_AGENT` | 内置默认值 | 自定义 User-Agent |
| `BROWSER_EXTRA_HEADERS_JSON` | 空 | 额外请求头（JSON） |
| `BROWSER_DISABLE_WEB_SECURITY` | `false` | 禁用浏览器安全策略 |
### 重试配置

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `RETRY_MAX_RETRIES` | `3` | 最大重试次数 |
| `RETRY_INTERVAL` | `5` | 基础重试间隔（秒），退避公式：`interval × 2^(n-1)` |

### 系统配置

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `MINIMIZE_TO_TRAY` | `true` | 最小化到系统托盘 |
| `CUSTOM_VARIABLES` | `{}` | 自定义变量（JSON 格式） |
| `AUTO_INSTALL_PLAYWRIGHT` | `true` | 自动安装 Chromium |
| `PLAYWRIGHT_DOWNLOAD_HOST` | npmmirror 镜像 | Playwright 下载源 |

### 内部变量

以下变量由系统内部使用，通常无需手动设置：

| 变量 | 说明 |
|------|------|
| `Campus-Auth_PROJECT_ROOT` | 项目根目录路径 |
| `Campus-Auth_START_EXECUTABLE` | 打包可执行文件路径 |
| `Campus-Auth_AUTO_OPEN_BROWSER` | 是否自动打开浏览器 |
| `Campus-Auth_ENV_FILE` | .env 文件路径 |
