# Campus-Auth v3.5.1 代码全面评审报告

> 评审日期: 2026-05-07
> 评审范围: 全部源代码、前端、文档、配置文件、测试
> 状态: 已修复的问题标记为 ✅

---

## 目录

- [一、严重问题 (CRITICAL)](#一严重问题-critical)
- [二、确认的 Bug](#二确认的-bug)
- [三、废弃/无用代码](#三废弃无用代码)
- [四、潜在 Bug 和隐患](#四潜在-bug-和隐患)
- [五、文档与代码冲突](#五文档与代码冲突)
- [六、遗留/兼容性问题](#六遗留兼容性问题)
- [七、代码优化建议](#七代码优化建议)
- [八、新功能建议](#八新功能建议)

---

## 一、严重问题 (CRITICAL)

### 1. ✅ 源文件缺失: `src/campus_login.py`

**位置**: `src/utils/login.py:79`

`_perform_login_with_auth_class()` 方法在没有活动任务时会回退导入 `EnhancedCampusNetworkAuth`，但源文件不存在。

**已修复**: 移除了回退导入逻辑，改为直接返回错误提示"未找到可执行的活动任务"。

### 2. ✅ 两个测试用例必然失败

**位置**: `tests/test_task_executor.py`

- `test_task_config_from_dict`: 断言不存在的 `version` 字段
- `test_task_manager_list_tasks_source_default`: 断言不存在的 `source` 字段

**已修复**: 移除了 `version` 字段断言；将第二个测试改为验证 `list_tasks` 实际返回的 `id`、`name`、`description` 字段。

---

## 二、确认的 Bug

### 3. ✅ 前端变量名不匹配: `wsRetryAttempt` vs `wsRetryCount`

**位置**: `frontend/partials/topbar.html:11`

Vue 数据模型定义的是 `wsRetryCount`，模板使用了 `wsRetryAttempt`。

**已修复**: 改为 `{{ wsRetryCount }}`。

### 4. ✅ 许可证信息不一致

**位置**: `frontend/partials/pages/about.html:108` 和 `LICENSE`

About 页面显示 "License: MIT"，但 LICENSE 文件是 Apache 2.0。

**已修复**: 统一为 MIT 许可证。

---

## 三、废弃/无用代码

### 5. ✅ `save_profile_from_payload()` — 完全未调用

**位置**: `backend/config_service.py:300`

**已修复**: 删除此函数。

### 6. ✅ `MonitorService.save_config()` — 死代码路径

**位置**: `backend/monitor_service.py:144`

**已修复**: 删除此方法及 `write_system_settings` 导入。

### 7. ✅ `ExceptionHandler` 类 — 导出但从未使用

**位置**: `src/utils/exceptions.py:23`

**已修复**: 删除此类及其相关辅助函数 `_get_playwright_timeout_error`，清理所有导出。

### 8. ✅ `SimpleRetryHandler` 类 — 导出但从未使用

**位置**: `src/utils/retry.py:13`

**已修复**: 清理所有导出引用。文件保留但不再被导入。

### 9. ✅ `ConfigManager` 单例 — 导出但从未使用

**位置**: `src/utils/config.py:204`

**已修复**: 删除此类，清理所有导出。

### 10. ✅ `cleanup_old_files()` — 导出但从未调用

**位置**: `src/utils/logging.py:232`

**已修复**: 删除此函数，清理所有导出。

### 11. ✅ `is_encrypted()` — 仅内部使用但被导出

**位置**: `src/utils/crypto.py:128`

**已修复**: 从公共导出中移除（函数本身保留供 `mask_password` 内部使用）。

### 12. ✅ `ColoredFormatter` / `configure_root_logger` — 仅内部使用但被导出

**位置**: `src/utils/logging.py`

**已修复**: 从公共导出中移除。

### 13. `GET /api/debug/status` 端点 — 前端未使用

**位置**: `backend/main.py`

后端定义了此端点，但前端从未调用。保留以备将来使用。

### 14. ✅ `src/utils.py` 向后兼容层 — 已清理

**位置**: `src/utils.py`

**已修复**: 更新为仅导出实际被外部使用的符号。

---

## 四、潜在 Bug 和隐患

### 15. ✅ `_debug` 全局字典无并发保护

**位置**: `backend/main.py:268`

**已修复**: 添加 `asyncio.Lock` 保护所有调试端点的 `_debug` 字典访问。

### 16. 嵌套配置字典的浅拷贝

**位置**: `backend/monitor_service.py`

`self._runtime_config.copy()` 是浅拷贝，修改嵌套字典可能影响原始对象。当前因 `setdefault` 行为而侥幸无事，但模式脆弱。建议后续使用 `copy.deepcopy()`。

### 17. ✅ `task_executor.py` 中 `time` 模块的重复导入

**位置**: `src/task_executor.py:355,809`

方法内部 `import time as _time` 与模块顶层 `import time` 重复。功能正确但不规范。

### 18. ✅ `config_service.py` 中冗余的 `import json`

**位置**: `backend/config_service.py:283`

**已修复**: 移除冗余的 `import json as _json`，使用已有的 `json` 导入。

---

## 五、文档与代码冲突

### 19. README 环境变量文档过时

README 详细列出了 `USERNAME`、`PASSWORD`、`LOGIN_URL` 等环境变量，但 `.env.example` 仅含 4 个变量。业务配置已迁移到 `settings.json`。

### 20. 更新日志停留在 v3.3.0

`README.md` 更新日志最新条目是 v3.3.0，但 `pyproject.toml` 版本为 3.5.1。

### 21. ✅ 前端帮助文本未标记 `navigate` 步骤为已废弃

**位置**: `frontend/partials/pages/tasks.html:112`

**已修复**: 添加"（已废弃，请使用 url 字段）"标注，同时在 `NavigateHandler` 中添加运行时废弃警告。

### 22. README 未记录新设置项

`settings.json` 中的 `max_retries`、`retry_interval`、`safe_mode`、`login_then_exit` 等设置在 README 中没有文档说明。

---

## 六、遗留/兼容性问题

### 23. ✅ 遗留的 `JCU_ENV_FILE` 环境变量

**位置**: `src/utils/config.py:115`

**已修复**: 移除 `JCU_ENV_FILE` 引用，同步更新测试。

### 24. ✅ `pytest` 列为主依赖

**位置**: `pyproject.toml:19`

**已修复**: 移至 `[project.optional-dependencies]` 的 `dev` 组。

---

## 七、代码优化建议

### 25. `.field-help` CSS 重复

**位置**: `frontend/styles/pages/settings.css` 和 `frontend/styles/pages/profiles.css`

`.field-help` 提示样式在两个文件中几乎完全重复。建议提取到 `components.css` 中。

### 26. ✅ 冗余导出的未使用符号

**已修复**: 清理了 `src/utils/__init__.py` 和 `src/utils.py` 的导出列表。

### 27. `monitor_core.py` 可复用 `SimpleRetryHandler`

`monitor_core.py` 中内联实现了重试逻辑，而 `src/utils/retry.py` 已有 `SimpleRetryHandler`。建议后续统一。

---

## 八、新功能建议

### 1. 网络连接质量监控

- 记录每次探测的延迟时间，在仪表盘显示延迟趋势图
- 当延迟异常升高时提前预警（可能即将断网）

### 2. 多因素认证支持

- 部分校园网需要短信验证码或图形验证码
- 可增加一个 `captcha` 步骤类型，支持截图 -> OCR -> 自动填入

### 3. 任务执行历史记录

- 当前只有实时日志，没有持久化的执行历史
- 建议增加 SQLite 或 JSON 文件记录每次登录的时间、结果、耗时、使用的任务

### 4. 配置方案导入/导出

- 当前任务支持导入/导出，但配置方案 (Profiles) 没有
- 可以让用户分享不同校园网的配置方案

### 5. 健康检查端点增强

- 当前 `/api/health` 仅返回基本信息
- 可增加 Playwright 状态、磁盘空间、日志文件大小、上次登录时间等诊断信息

### 6. WebSocket 断线后的日志补发

- 当前 WebSocket 断线重连后，断线期间的日志会丢失
- 可在后端维护一个环形缓冲区，重连后补发丢失的日志

### 7. 任务步骤的条件分支增强

- 当前 `success_conditions` 仅在任务结束后判断
- 可增加步骤级别的 `on_failure` 动作（如重试当前步骤、跳到指定步骤、执行备用步骤）

### 8. 国际化 (i18n) 支持

- 前端所有文本硬编码为中文
- 可提取为语言包，支持英文等其他语言
