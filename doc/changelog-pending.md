# 待合并更新日志

以下变更尚未合并到 README 更新日志中，待发布新版本时合并。

## v3.5.x (待定)

### 功能变更

- 移除 API_TOKEN 鉴权功能（本地项目无需对外鉴权）。

### 改进

- 改进网络连接检测：支持有线/无线网络实际连接状态检查（Windows 通过 PowerShell Get-NetAdapter 检测适配器状态，Linux 通过路由表检测，macOS 通过 ifconfig 检测接口状态），避免无网络时徒增功耗。
- Windows 网关检测改用 PowerShell Get-NetRoute（结构化输出，不受系统语言影响），回退到 ipconfig 时扩展多语言支持。
- macOS SSID 检测添加 networksetup 回退方案（airport 工具在新版 macOS 上可能不存在）。
- Windows SSID 检测修复非 ASCII SSID 的编码问题（使用系统默认编码解码）。
- Linux 自启动 ExecStart 修复路径含空格时的引号处理问题。
- HTTP 网络检测仅将 2xx 状态码视为成功（之前 3xx/4xx 也被视为已连接，导致认证门户 302 重定向时跳过登录）。
- 改进浏览器反检测脚本：模拟真实 PluginArray、完善 chrome 对象属性、覆盖 languages。
- 改进低资源模式：除图片外同时屏蔽字体和媒体文件。
- 浏览器复用前添加健康检查，避免使用已崩溃的浏览器实例。

### Bug 修复

- 修复复制任务时 ID 覆盖问题（重复复制同一任务会静默覆盖之前的副本）。
- 修复危险确认对话框页面切换后 Promise 永久挂起问题。
- 修复 CORS 端口与实际服务端口不一致问题（无效 APP_PORT 导致所有 API 请求被 CORS 阻断）。
