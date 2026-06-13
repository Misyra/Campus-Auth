# 修改日志

## 2026-06-13

### refactor: 配置更新用 model_copy 替代合并字典+全量验证

- 文件: `app/services/config_service.py`
- 变更: `_update_system_settings` 和 `_update_default_profile` 中将 `{**model.model_dump(), **update_data}` + `model_validate` 模式简化为 `model_copy(update=update_data)`
- 原因: 避免全量 dump + validate 的开销，`model_copy(update=...)` 是 Pydantic v2 推荐的浅拷贝+覆盖方式，语义更清晰且无需重新验证全部字段

### refactor: engine _enqueue 去除无意义的重试逻辑

- 文件: `app/services/engine.py`
- 变更: `_enqueue` 方法移除 `retries` 参数和 `for attempt in range(retries)` 循环，队列满时直接返回 False 并记录警告日志
- 原因: 重试仅在 50ms 后再试一次，队列满的场景下多等 50ms 无实际意义，反而增加不必要的阻塞

### docs: 补充后端代码审查报告

- 文件: `dev/后端代码审查报告.md`
- 变更: 对原报告 61 个问题进行逐行验证，确认全部成立；补充 6 个遗漏问题
  - N1: `check_update` 并发重复 API 请求（system.py）
  - N2: 脚本超时配置路径永远不生效（scripts.py）
  - N3: BrowserContextManager 浏览器关闭职责分散（browser.py + login.py）
  - N4: `_handle_debug_stop` 替代页面反检测脚本条件不一致（playwright_worker.py）
  - N5: `_persist_source_levels` 直接 setattr Pydantic model（config.py）
  - N6: `_rollback_config` 逐字段赋值依赖字段迭代顺序（config.py）
- 总计: 67 个问题（原 61 + 补充 6）
