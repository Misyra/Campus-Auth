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
- **不要给脚本执行加沙箱** — 用户自己写的脚本，增加复杂度无收益
- **不要校验 TaskConfig 的 URL scheme** — 任务文件由用户创建
- **不要给 background_url 做 CSS 注入防护** — 用户自己设置的 URL

## 竞态/并发类 — 单用户桌面应用，概率极低

- **不要给 save_config_combined 加原子性** — 单用户不会同时保存
- **不要给 monitoring bool 加锁** — CPython GIL 保证原子性
- **不要给 _block_proxy 加同步** — 同上
- **不要给 stop() 加竞态保护** — 仅在关闭时触发，窗口极短
- **不要给 PID 文件检查加锁** — 两个实例同毫秒启动的概率几乎为零
- **不要给备份操作加原子性** — 用户手动触发，与配置写入同时发生的概率极低

## 代码质量类 — 功能正确，不需要改

- **不要给 debug 路由加 response_model** — 会截断调试状态
- **不要给 save_task 加 Pydantic 校验** — 任务 JSON 结构灵活，严格校验可能拒绝合法任务
- **不要改 toggle_auto_switch 的 Query 参数** — FastAPI 能正确处理
- **不要改拖拽状态为 Vue 响应式** — 单一实例，模块级变量正常工作
- **不要优化 configDirty 的 JSON.stringify** — 配置对象体量下不会卡顿
- **不要给 API 调用加 loading 状态** — 单用户场景下并发请求概率低
- **不要改日志文件为 POSIX 权限** — 仅 Windows 运行
- **不要更新硬编码的 Chrome UA** — 需要时手动更新即可
- **不要给用户名密码加最小长度** — 应匹配实际校园网账号格式
- **不要擦除密钥内存** — Python 字符串不可变，bytearray 方案需重构整个接口
- **不要改 quitApp 的 innerHTML** — 退出场景下由 OS 进程终止处理
- **不要给 exportBackup 加路径遍历检查** — 备份列表来自后端 listdir
- **不要提取 applyAppearance 的公共颜色解析函数** — 功能正确，属重构范畴

## 误判/假阳性 — 问题不成立

- **asyncio.Lock 从后台线程调用** — 所有调用都在事件循环线程中
- **os._exit(0) 跳过清理** — 守护线程中是唯一正确方式，调用前已做清理
- **Base64 伪加密回退** — cryptography 是必需依赖，回退代码已有 warning
- **close_browser 命令顺序** — CLOSE-then-RELEASE 是正确的资源管理顺序
- **login_attempt_count 重置重复** — 两处在互斥的代码路径中
- **DOM 元素内存泄漏** — detached 节点，GC 可正常回收
- **Promise 闭包泄漏** — beforeUnmount 已清除 timer
- **profile_service.load() 冗余深拷贝** — _load_unsafe() 内部已做 model_copy(deep=True)
