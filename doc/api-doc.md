# API 接口文档

> 本文档汇总 Campus-Auth 所有 HTTP API 和 WebSocket 接口，供开发联调或前后端扩展时查阅。

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
- [自启动](#自启动)
- [配置备份](#配置备份)
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
| GET | `/api/init-status` | 初始化状态（是否已设置账号密码） |
| POST | `/api/shutdown` | 关闭服务（停止监控、托盘、进程） |

## 配置管理

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/config` | 获取当前配置 |
| PUT | `/api/config` | 保存配置 |

## 配置方案

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/profiles` | 列出所有方案 |
| GET | `/api/profiles/active` | 获取活动方案详情 |
| GET | `/api/profiles/{id}` | 获取指定方案 |
| PUT | `/api/profiles/{id}` | 创建/更新方案（活动方案自动热重载） |
| DELETE | `/api/profiles/{id}` | 删除方案（`default` 不可删除） |
| POST | `/api/profiles/active/{id}` | 设置活动方案 |
| POST | `/api/profiles/detect` | 检测当前网络环境（网关 IP、SSID、匹配方案） |
| POST | `/api/profiles/auto-switch` | 切换自动切换开关 |

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
| POST | `/api/actions/test-network` | 测试网络连通性 |

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
| GET | `/api/tasks/{id}` | 获取指定任务 |
| PUT | `/api/tasks/{id}` | 创建/更新任务 |
| DELETE | `/api/tasks/{id}` | 删除任务（`default` 不可删除） |
| POST | `/api/tasks/active/{id}` | 设置活动任务 |
| POST | `/api/tasks/order` | 保存任务排序 |

## 脚本管理

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/scripts` | 列出所有脚本任务 |
| GET | `/api/scripts/{id}` | 获取指定脚本任务 |
| PUT | `/api/scripts/{id}` | 创建/更新脚本任务 |
| DELETE | `/api/scripts/{id}` | 删除脚本任务 |
| POST | `/api/scripts/{id}/run` | 执行脚本任务 |

## 日志

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/logs?limit=200` | 获取历史日志（内存缓冲区，最多 1200 条） |
| WS | `/ws/logs` | WebSocket 实时日志流 |

## 自启动

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/autostart/status` | 自启动状态（平台、方式、位置） |
| POST | `/api/autostart/enable` | 启用自启动 |
| POST | `/api/autostart/disable` | 禁用自启动 |

## 配置备份

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/backup/list` | 列出所有备份 |
| POST | `/api/backup/create` | 创建当前配置的备份 |
| POST | `/api/backup/restore/{filename}` | 从备份恢复配置 |
| GET | `/api/backup/download/{filename}` | 下载备份文件 |
| DELETE | `/api/backup/{filename}` | 删除备份 |

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
| GET | `/api/debug/status` | 获取调试会话状态 |

## 仓库代理

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/repo/fetch?url=...` | 代理获取远程任务仓库索引 |
| GET | `/api/repo/task?url=...` | 代理获取远程单个任务配置 |

## 工具与文档

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/tools/task-recorder.user.js` | 下载任务录制器 Tampermonkey 脚本 |
| GET | `/api/docs/task-writing-guide` | 下载任务编写指南文档 |

## 背景图片

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/background/upload` | 上传背景图片（支持 JPG/PNG/GIF/WebP，最大 5MB） |
| GET | `/api/background/{filename}` | 获取背景图片 |
| DELETE | `/api/background/{filename}` | 删除背景图片 |

## 静态资源

| 路径 | 说明 |
|------|------|
| `/logs/{date}/screenshots/{filename}` | 失败截图文件访问 |
| `/debug/` | 截图文件的静态访问 |
| `/temp/` | 调试截图临时目录 |
