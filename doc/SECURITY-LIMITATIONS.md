# Campus-Auth 已知安全限制

> 生成于 2026-06-03
>
> 本文档记录 Campus-Auth 在本地约束下的已知安全限制,所有项目均经审计报告 `doc/audit-2026-06-02.md` 评估并在 CLAUDE.md 设计决策(本地仅运行/无鉴权/无 CORS)前提下文档化。

---

## P1-SEC-3: 定时任务 API 无命令白名单

### 描述

定时任务 `type=shell` 允许用户通过 API 指定任意 `command` 和 `shell_path`,由 `scheduler_service._execute_shell()` 直接执行。同样,ScriptRunner 的 `binary_path` 支持 `python -c` 等模式,可执行任意代码。

这是本项目的**显式设计特性**,而非安全漏洞。Campus-Auth 是单用户本地工具,用户拥有完整的文件系统和进程权限,命令白名单在此场景下无实际安全收益,反而会限制合法使用。

### 触发条件

- 创建/更新定时任务时 `type=shell`,`command` 字段可为任意字符串
- 脚本任务的 `binary_path` 可指定任意可执行文件或解释器

### 已知缓解

- `src/utils/shell_policy.py` 中的 `ShellCommandPolicy` 提供了统一安全策略:
  - **执行路径白名单**: `shell_path` / `binary_path` 需通过 `allowlist` 验证(不验证命令内容本身)
  - **超时上限钳制**: timeout 被限制在 `[1, 300]` 秒范围内,防止失控进程
  - **执行前审计日志**: 每次执行前记录命令详情、超时设置等信息

### 升级路径

如未来需要支持多用户或远程访问,应引入命令内容白名单或沙箱执行环境。

---

## P1-SEC-4: 背景图片无魔数验证

### 描述

`/api/background/upload` 和 `/api/background/fetch-url` 两个端点仅通过文件扩展名(`.jpg`/`.png`/`.gif`/`.webp`)和 HTTP `Content-Type` 头校验上传内容,不校验二进制文件头(魔数/magic bytes)。理论上攻击者可上传一个伪装为图片的非图片文件。

### 触发条件

- 上传文件时,扩展名合法但文件内容与扩展名不匹配
- 通过 `fetch-url` 下载时,服务器返回的 `Content-Type` 包含 `image` 但实际内容非图片

### 已知缓解

- 上传的文件大小限制为 5MB (`MAX_FILE_SIZE`)
- 背景图片仅存储于 `frontend/background/` 目录,通过 CSS `background-image` 属性由本地浏览器加载渲染
- 浏览器对非图片内容会直接忽略或显示为空,不会触发 JavaScript 执行
- 服务仅监听 `127.0.0.1`,无远程上传路径

### 升级路径

如需加强校验,可在保存前增加 `filetype` 或 `python-magic` 库进行二进制魔数检测。

---

## P1-SEC-5: portal 检测用户 URL SSRF

### 描述

`portal_check_urls` 配置项允许用户填入任意 HTTP URL,用于 captive portal 网络连通性检测。实现中使用 `httpx.Client(verify=False, follow_redirects=True)` 发起请求,理论上可被用于服务端请求伪造(SSRF)。

### 触发条件

- 用户在监控配置中设置 `portal_check_urls` 为内网地址或敏感 URL
- `follow_redirects=True` 可能跟随重定向到非预期目标

### 已知缓解

- 本项目设计为**仅本地运行**,服务监听 `127.0.0.1`,不存在远程攻击面
- `portal_check_urls` 由用户自行配置,用户控制自己的数据,不存在第三方注入风险
- `verify=False` 是为兼容校园网自签名证书的**设计决策**(与 `browser.py` 中的 `ignore_https_errors=True` 一致)
- 默认情况下 portal 检测使用内置 URL(`captive.apple.com`/`msftconnecttest.com`/`detectportal.firefox.com`),仅在用户主动配置时才使用自定义 URL

### 升级路径

如需支持多用户场景,应对 `portal_check_urls` 增加 URL scheme 和目标地址限制。

---

## CSS-11: `color-mix()` 兼容性

### 描述

项目 CSS 中使用了 `color-mix(in srgb, ...)` 函数。该 CSS 特性在较旧浏览器中不受支持。

### 触发条件

- 使用低于以下版本的浏览器访问前端界面:
  - Chrome 111 以下
  - Firefox 113 以下
  - Safari 16.2 以下

### 已知缓解

- `color-mix()` 自 2023 年起在主流浏览器中已全面 GA(Generally Available)
- Campus-Auth 是本地工具,用户使用自己安装的浏览器,通常为较新版本
- 不使用 `color-mix()` 的回退值时,浏览器会忽略该声明,使用上一层级的 CSS 变量或默认值

### 升级路径

如需兼容更旧浏览器,可将 `color-mix()` 替换为预计算的颜色值或使用 CSS 变量嵌套方案。

---

## API 无鉴权与 CORS 全开

### 描述

所有 API 端点无认证/授权机制，CORS 策略设置为允许所有来源 (`allow_origins=["*"]`)。任何本地进程均可调用任意接口。

### 设计决策

Campus-Auth 仅监听 `127.0.0.1`，不存在远程访问面。在单用户本地工具场景下，API 鉴权和 CORS 限制无法提供实际安全收益（用户已拥有完整系统权限），反而增加使用复杂度。此为**有意设计**，非遗漏。

### 升级路径

如需支持远程访问或多用户场景，应引入 token 认证并收紧 CORS 来源白名单。

---

## 前端 console.log 可能暴露信息

### 描述

前端代码中存在 `console.log` / `console.warn` 调用，可能在浏览器开发者工具中输出敏感信息（如配置项、网络状态、错误详情）。

### 已知缓解

- 仅本地运行，开发者工具需用户主动打开
- 生产环境可通过构建流程或 `console` 覆盖层移除

### 升级路径

统一使用日志级别控制，生产模式下静默非错误输出。

---

## settings.json 加密但 key 与 ciphertext 同目录

### 描述

密码字段使用 Fernet 加密（`ENC:` 前缀），但加密 key 文件与 `settings.json` 存储在同一目录。拥有文件系统读权限的进程可同时获取 key 和密文，等同于明文存储。

### 已知缓解

- 本项目仅本地运行，用户已拥有完整文件系统权限
- 加密的主要目的是防止配置文件意外泄露时密码被直接读取（如截图、日志误输出）

### 升级路径

如需加强密钥保护，可将 key 存储于系统 keyring（Windows Credential Manager / macOS Keychain）。

---

## login_history_service 锁内 I/O 风险

### 描述

`login_history_service` 在持锁期间执行文件 I/O 操作（读写登录历史 JSON），高并发场景下可能导致锁持有时间过长，阻塞其他线程。

### 修复状态

Stage 3 已将文件 I/O 移至锁外执行：先在锁内拷贝数据引用，释放锁后再进行磁盘读写。
