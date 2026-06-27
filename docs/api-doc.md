# API 接口文档

> 本文档汇总 Campus-Auth 所有 HTTP API 和 WebSocket 接口，供开发联调或前后端扩展时查阅。

## API 错误响应规范

| 场景 | 响应方式 | 状态码 |
|------|----------|:------:|
| 资源不存在 | `HTTPException` | 404 |
| 参数非法 | `HTTPException` | 422 |
| 权限问题 | `HTTPException` | 403 |
| 业务可预期失败 | `ActionResponse(success=False)` | 200 |
| 程序异常（未捕获） | `HTTPException` | 500 |

**关键原则：**
1. `ActionResponse(success=False)` 只用于业务可预期失败
2. 未捕获异常统一返回 500，不要用 `ActionResponse(success=False, message=str(e))` 掩盖
3. 资源不存在用 404，不要返回 200 + `success=false`

**前端处理：**
- 4xx/5xx 状态码 → Axios 拦截器统一处理
- 200 + `success=false` → 业务层处理

---

## 目录

- [健康检查与系统](#健康检查与系统)
- [配置管理](#配置管理)
- [配置方案](#配置方案)
- [监控控制](#监控控制)
- [手动操作](#手动操作)
- [纯净模式](#纯净模式)
- [任务管理](#任务管理)
- [脚本管理](#脚本管理)
- [日志](#日志)
- [登录历史](#登录历史)
- [定时任务](#定时任务)
- [自启动](#自启动)
- [OCR 文字识别](#ocr-文字识别)
- [卸载](#卸载)
- [调试](#调试)
- [仓库代理](#仓库代理)
- [工具与文档](#工具与文档)
- [背景图片](#背景图片)
- [静态资源](#静态资源)

---

## 健康检查与系统

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/health` | 健康检查，返回状态和版本 |
| GET | `/api/check-update` | 检查 GitHub 更新版本 |
| GET | `/api/init-status` | 初始化状态（返回 `initialized`、`agreed`、`password_decryption_failed`） |
| POST | `/api/agree` | 同意使用协议 |
| POST | `/api/shutdown` | 关闭服务（停止监控、托盘、进程） |

## 配置管理

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/config` | 获取当前配置 |
| PUT | `/api/config` | 保存配置 |
| GET | `/api/config/log-levels` | 获取日志级别配置（全局级别 + 各来源级别） |
| PUT | `/api/config/source-level` | 设置日志级别（source=global 时设置全局级别，否则设置指定来源级别） |
| GET | `/api/config/default-stealth-script` | 获取默认反检测脚本 |

## 配置方案

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/profiles` | 列出所有方案 |
| GET | `/api/profiles/{profile_id}` | 获取指定方案 |
| PUT | `/api/profiles/{profile_id}` | 创建/更新方案（活动方案自动热重载） |
| DELETE | `/api/profiles/{profile_id}` | 删除方案（`default` 不可删除） |
| POST | `/api/profiles/active/{profile_id}` | 设置活动方案 |
| POST | `/api/profiles/detect` | 检测当前网络环境（网关 IP、SSID、匹配方案） |
| POST | `/api/profiles/auto-switch?enabled=` | 切换自动切换开关 |

## 监控控制

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/status` | 监控状态 |
| POST | `/api/monitor/start` | 启动监控 |
| POST | `/api/monitor/stop` | 停止监控 |

## 手动操作

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/actions/login` | 手动触发登录 |
| POST | `/api/actions/cancel-login` | 取消当前登录 |
| POST | `/api/actions/test-network` | 测试网络连通性 |

## 浏览器管理

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/browsers` | 获取浏览器列表和当前配置 |
| POST | `/api/browsers/install-playwright` | 安装 Playwright Chromium |

## 纯净模式

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/pure-mode` | 获取纯净模式状态 |
| POST | `/api/pure-mode` | 切换纯净模式 |

## 任务管理

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/tasks` | 列出所有任务 |
| GET | `/api/tasks/active` | 获取当前活动任务 |
| GET | `/api/tasks/{task_id}` | 获取指定任务 |
| PUT | `/api/tasks/{task_id}` | 创建/更新任务 |
| DELETE | `/api/tasks/{task_id}` | 删除任务（`default` 不可删除） |
| POST | `/api/tasks/active/{task_id}` | 设置活动任务 |
| POST | `/api/tasks/order` | 保存任务排序 |

## 脚本管理

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/scripts` | 列出所有脚本任务 |
| GET | `/api/scripts/binaries` | 列出可用的脚本解释器 |
| GET | `/api/scripts/{task_id}` | 获取指定脚本任务 |
| PUT | `/api/scripts/{task_id}` | 创建/更新脚本任务 |
| DELETE | `/api/scripts/{task_id}` | 删除脚本任务 |
| POST | `/api/scripts/{task_id}/run` | 执行脚本任务 |

## 日志

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/logs?limit=` | 获取历史日志（默认 200，最大 1000 条） |
| WS | `/ws/logs` | WebSocket 实时日志流 |

## 登录历史

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/login-history?limit=` | 获取最近的登录历史记录（limit 范围 1~500，默认 30） |
| DELETE | `/api/login-history` | 清空所有登录历史记录 |

## 定时任务

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/scheduled-tasks` | 列出所有定时任务 |
| POST | `/api/scheduled-tasks` | 创建定时任务（type: script/browser/shell） |
| PUT | `/api/scheduled-tasks/{task_id}` | 更新定时任务 |
| DELETE | `/api/scheduled-tasks/{task_id}` | 删除定时任务 |
| POST | `/api/scheduled-tasks/{task_id}/run` | 手动执行定时任务 |
| POST | `/api/scheduled-tasks/{task_id}/toggle` | 启用/禁用定时任务 |
| GET | `/api/scheduled-tasks/{task_id}/history` | 获取定时任务执行历史 |

## 自启动

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/shells` | 列出可用的系统 Shell |
| GET | `/api/autostart/status` | 自启动状态（平台、方式、位置） |
| POST | `/api/autostart/enable` | 启用自启动 |
| POST | `/api/autostart/disable` | 禁用自启动 |
| POST | `/api/autostart/mode` | 切换自启动模式 |

## OCR 文字识别

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/ocr/status` | 获取 OCR 引擎安装状态 |
| POST | `/api/ocr/install` | 安装 OCR 引擎 |
| POST | `/api/ocr/uninstall` | 卸载 OCR 引擎 |

## 卸载

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/uninstall/detect` | 检测可清理的外部残留项目 |
| POST | `/api/uninstall` | 执行卸载清理 |

## 调试

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/debug/start` | 启动调试会话，打开浏览器并加载任务 |
| POST | `/api/debug/next` | 执行下一步骤 |
| POST | `/api/debug/run-all` | 执行所有剩余步骤 |
| POST | `/api/debug/stop` | 停止调试会话并关闭浏览器 |

## 仓库代理

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/repo/fetch?url=` | 代理获取远程任务仓库索引 |
| GET | `/api/repo/task?url=` | 代理获取远程单个任务配置 |

## 工具与文档

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/tools/task-recorder.user.js` | 下载任务录制器 Tampermonkey 脚本 |
| GET | `/api/docs/task-writing-guide` | 下载任务编写指南文档 |
| GET | `/api/docs/task-manual` | 下载任务操作手册 |

## 背景图片

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/background/upload` | 上传背景图片（支持 JPG/PNG/GIF/WebP，最大 5MB） |
| POST | `/api/background/fetch-url` | 从远程 URL 下载图片并保存 |
| GET | `/api/background/{filename}` | 获取背景图片 |
| DELETE | `/api/background/{filename}` | 删除背景图片 |

## 图标

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/icons/{filename}` | 获取 SVG 图标文件 |

## 静态资源

| 路径 | 说明 |
|------|------|
| `/` | 前端页面入口 |
| `/debug/` | 调试截图静态目录 |
| `/temp/` | 调试截图临时目录 |
