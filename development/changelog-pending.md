# 待合并更新日志

以下变更尚未合并到 README 更新日志中，待发布新版本时合并。

## v3.6.x (待定)

### 修复

- **修复监控运行时保存设置后端卡死**：`reload_config()` 持锁期间调用 `update_config()` → `_push_log()` 触发同一 `threading.Lock` 的不可重入死锁。改为 `RLock` + 将热更新调用移到锁外执行，同时修复 `_on_profile_switch` 中的同类型死锁。
- **修复 `save_task()` 非原子写入**：改为临时文件 + `os.replace()` 原子替换，防止崩溃时损坏任务 JSON 文件。
- **修复 `is_in_pause_period` 边界条件**：`start_hour == end_hour` 时区间退化为零长度（永不为真），改为视为全天暂停。
- **修复 `set_active_profile` 返回值被丢弃**：TOCTOU 场景下方案切换可能静默失败，现检查返回值并回退缓存状态。
- **修复 `LOG_LEVELS` 缺少 `CRITICAL` 级别**：前端 logger 对 CRITICAL 静默降级为 INFO，现与后端对齐。
- **修复通知面板关闭时也清零未读计数**：改为仅在打开面板时清零。
- **`_setTrayIcon` → `_set_tray_icon`**：统一 snake_case 命名。
- **`schemas.py` `safe_mode` 默认值 `True` → `False`**：与其他代码路径和文档保持一致。

### 移除

- **移除废弃的 `NavigateHandler` 类**：navigate 步骤已不再支持（由任务 URL 字段自动导航取代），保留 `StepType.NAVIGATE` 枚举和 TaskValidator 弃用提示以兼容旧任务文件。

### 文档

- 删除 `task-manual.md` 中不存在的 `BROWSER_SAFE_MODE` 环境变量条目
- 修正 `task-manual.md` 中 `MAX_RETRIES` → `RETRY_MAX_RETRIES`
- 标注 `task-manual.md` 中 navigate 步骤类型为已废弃
- 补充 `README.md` 中 `browser_args` 配置项文档
- 删除 `main.py` 中冗余的 `import re as _re`
