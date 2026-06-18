# Not To Do

> 经审查判定为不修复的问题。这些都是设计决策，不是 bug。不要尝试"修复"它们。

---

## 安全类 — 本地单用户，无需处理

- **不要加 API 鉴权/CORS 限制** — 仅监听 127.0.0.1，无远程访问面
- **不要给定时任务加命令白名单** — 用户已拥有完整系统权限
- **不要校验上传图片的魔数** — 浏览器会忽略非图片内容
- **不要阻止 portal 检测的 SSRF** — 用户自己配置的 URL，verify=False 是兼容自签名证书的设计
- **不要把密钥移到 keyring** — 密钥在 `~/.campus_network_auth/.enc_key`，密文在 `config/settings.json`，已分离存储；加密主要是防止配置文件意外泄露时密码直接可读
- **不要删除 console.log** — 仅本地运行，开发者工具需用户主动打开
- **不要替换 CSS color-mix()** — 2023 年起主流浏览器已全面 GA
- **不要给 repo_proxy 加 SSRF 防护** — 用户需手动输入恶意 URL，已限制 https?:// 协议
- **不要脱敏 repo_proxy 的错误信息** — 本地单用户，详细错误信息帮助排查；用户自己配置的 URL
- **不要给 `_is_auth_url_reachable` 拆分独立线程池** — 网络探测每 300 秒一次，登录前检查仅一次，同时跑满 3 worker 概率极低，都有超时保护
- **不要给 `run_script` 端点加并发限制** — 单用户桌面应用，前端无批量执行功能，不可能并发大量请求
- **不要给 PID 宽限期加进程名校验** — PID 复用 × 创建时间 1 秒巧合 × 30 秒宽限期同时满足的概率几乎为零，桌面应用启动一次就跑着
- **不要从 `_build_minimal_env` 移除 APPDATA/LOCALAPPDATA/USERPROFILE** — 用户自己写的脚本已有完整系统权限，这些变量是解释器和包管理器正常工作必需的
- **不要脱敏 browsers.py 的异常信息** — 与 repo_proxy 同理，本地单用户，详细错误帮助排查
- **不要给 SVG 图标加路径遍历防护** — localhost 访问，`.svg` 扩展名已限制，`startswith` 足够
- **不要给异步 ShellCommandPolicy.run 加 kwargs 白名单** — 用户自己写的脚本，与 `run_sync` 的白名单一致即可
- **不要给 ShellCommandPolicy 加路径规范化** — `shutil.which` 返回的已是规范路径，单用户场景
- **不要给临时文件删除加告警** — 用户自己的脚本，desktop app
- **不要给 browser_args 加黑名单过滤** — 用户自己配置的启动参数
- **不要给 `_execute_shell` 的 command 做消毒** — 用户自己写的 shell 命令，桌面应用场景
- **不要给 /debug /temp 静态目录加认证** — localhost 访问，单用户桌面应用
- **不要给 `is_local_port_in_use` 加 IPv6 检测** — 纯 IPv6 环境几乎不存在，校园网场景必有 IPv4
- **不要处理 `cancel_futures` 的 Python 3.8 兼容性** — 项目最低要求 Python 3.10，默认 3.12
- **不要优化 `delete_profile` 后的方案切换逻辑** — `next(iter())` 取第一个方案即可，方案数量少，用户可手动切换
- **不要给 `ProfileService._load_unsafe` 加文件修改时间检查** — 正常使用通过 UI/API 修改配置，不会在运行时手动改 settings.json
- **不要脱敏启动日志中的 username/auth_url** — 本地单用户桌面应用，日志文件在本地，用户自己配置的值
- **不要给脚本执行加沙箱** — 用户自己写的脚本，增加复杂度无收益
- **不要删除 script_runner 的白名单自动追加** — 白名单是已知解释器发现机制而非安全防线；自动追加是合理的降级策略，warning 已提示用户；若优化应改到前端保存时提示"该路径不在已知列表中，是否继续？"，后端只做路径存在性检查
- **不要给 delete_task 加 _safe_subdir_path** — TASK_ID_PATTERN `^[A-Za-z][A-Za-z0-9_]*$` 已排除路径穿越字符，当前安全；单用户桌面应用场景
- **不要改网络探测为"任一成功即返回 True"** — 当前"任一失败即返回 False"是故意设计的严格模式：宁可误报断网触发多余登录，不可漏报导致断网不处理；HTTP 200 可能是 portal 拦截页面
- **不要改 `is_in_pause_period` 的默认 `enabled=True`** — 空配置默认启用暂停是故意设计，校园网凌晨 0-6 点一般不需要认证；文档字符串已说明
- **不要校验 TaskConfig 的 URL scheme** — 任务文件由用户创建
- **不要给 background_url 做 CSS 注入防护** — 用户自己设置的 URL

## 竞态/并发类 — 单用户桌面应用，概率极低

- **不要给 save_config_combined 加原子性** — 单用户不会同时保存
- **不要给 monitoring bool 加锁** — CPython GIL 保证原子性
- **不要给 _block_proxy 加同步** — 同上
- **不要给 stop() 加竞态保护** — 仅在关闭时触发，窗口极短
- **不要给 PID 文件检查加锁** — 两个实例同毫秒启动的概率几乎为零

## 架构类 — 核心设计决策，不要重构

- **不要将 `except Exception` 缩窄为具体异常类型** — 130 处防御性捕获全部配有日志，桌面应用"永不崩溃"是核心目标；Playwright/httpx/网络操作的异常类型不可穷举，缩窄只会引入漏网崩溃
- **不要将 threading 架构迁移为 asyncio** — engine/worker/tray 等核心组件基于 daemon thread + 队列通信，FastAPI 仅用于 API 层；统一为 asyncio 牵动整条链路，收益不抵风险
- **不要给前端加 TypeScript/构建工具链** — 原生 HTML/JS/CSS 无构建步骤，用户可直接修改前端文件；加入 bundler 会破坏这个优势
- **不要拆分 engine.py** — ScheduleEngine 是调度核心，职责清晰（命令队列、监控循环、重试逻辑、调度器），拆分只会增加模块间耦合
- **不要拆分 playwright_worker.py** — Worker 是浏览器自动化核心，生命周期紧密（启动、命令分发、清理），拆分收益不大反而增加复杂度

## 代码质量类 — 功能正确，不需要改

- **不要给 debug 路由加 response_model** — 会截断调试状态
- **不要给 save_task 加 Pydantic 校验** — 任务 JSON 结构灵活，严格校验可能拒绝合法任务
- **不要改拖拽状态为 Vue 响应式** — 单一实例，模块级变量正常工作
- **不要优化 configDirty 的 JSON.stringify** — 配置对象体量下不会卡顿
- **不要给 API 调用加 loading 状态** — 单用户场景下并发请求概率低
- **不要改日志文件为 POSIX 权限** — 日志轮转由 loguru 处理，无需手动设置
- **不要更新硬编码的 Chrome UA** — 需要时手动更新即可
- **不要给用户名密码加最小长度** — 应匹配实际校园网账号格式
- **不要擦除密钥内存** — Python 字符串不可变，bytearray 方案需重构整个接口
- **不要改 quitApp 的 innerHTML** — 退出场景下由 OS 进程终止处理
- **不要提取 applyAppearance 的公共颜色解析函数** — 功能正确，属重构范畴

## 误判/假阳性 — 问题不成立

- **asyncio.Lock 从后台线程调用** — 所有调用都在事件循环线程中
- **os._exit(0) 跳过清理** — 信号处理器/回退路径中无法优雅关闭，调用前已做清理
- **明文存储回退 (cryptography 缺失)** — cryptography 是必需依赖，缺少时回退为明文存储，已有 warning
- **close_browser 命令顺序** — CLOSE-then-RELEASE 是正确的资源管理顺序
- **login_attempt_count 重置重复** — 两处在互斥的代码路径中
- **DOM 元素内存泄漏** — detached 节点，GC 可正常回收
- **Promise 闭包泄漏** — beforeUnmount 已清除 timer
- **profile_service.load() 冗余深拷贝** — _load_unsafe() 内部已做 model_copy(deep=True)
