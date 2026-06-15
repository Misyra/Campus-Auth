# 修改日志

## 2026-06-15

### refactor
- `app/utils/crypto.py` 清理 D6 `is_encrypted` 死代码
  - 删除 `is_encrypted` 函数（生产代码中无任何调用者）
  - 删除 `tests/test_utils/test_utils.py` 中 `TestIsEncrypted` 测试类和 `is_encrypted` 导入
  - 移除 `test_round_trip` 中对 `is_encrypted` 的断言

### refactor
- `app/utils/config_utils.py` 清理 D2-D5 死代码
  - 删除 `PROFILE_FIELDS` 常量（在重构后不再被生产代码使用）
  - 删除 `GLOBAL_FIELDS` 常量（在重构后不再被生产代码使用）
  - 删除 `extract_profile_fields` 函数（在重构后不再被生产代码使用）
  - 删除 `ConfigValidator.validate_gui_config` 方法（在重构后不再被生产代码使用）
  - 删除 `tests/test_utils/test_config_utils_fix.py` 文件（全部内容为 PROFILE_FIELDS 测试）
  - 删除 `tests/test_utils/test_utils.py` 中 `TestExtractProfileFields` 测试类
  - 删除 `tests/test_config/test_config_schemas.py` 中 `TestValidateGuiConfig` 测试类

### refactor
- `app/utils/notify.py` 删除 `send_notification` 死代码
  - 函数在生产代码中无任何调用者，仅在测试中使用
  - 删除 `send_notification` 函数及其测试类 `TestSendNotification`
  - 保留 `_notify_windows`、`_notify_macos`、`_notify_linux` 平台通知函数

### fix
- `app/services/config_service.py` 删除 `build_runtime_config` 中不可达的密码回退代码
  - `GlobalSettings` 没有 `password` 字段，`hasattr(global_settings, 'password')` 永远返回 `False`
  - 移除死代码分支及不再使用的 `decrypt_password`、`DecryptionError` 导入

### fix
- `app/utils/ports.py` 修复端口配置读取路径和 JSON key
  - 路径从 `PROJECT_ROOT / "settings.json"` 修正为 `PROJECT_ROOT / "config" / "settings.json"`
  - JSON key 从 `system.app_port` 修正为 `global_settings.app_port`

### feat
- `app/api/profiles.py` 开启自动切换时立即检测匹配方案
  - `toggle_auto_switch` 新增 `monitor_svc` 依赖
  - 开启自动切换后立即调用 `detect_matching_profile` 检测当前网络
  - 检测到匹配方案且与当前方案不同时，自动切换并应用
  - 检测过程异常不影响开关状态设置，仅记录警告日志

### refactor
- `frontend/partials/pages/profiles.html` 移除所有 `use_global_*` 引用
  - 方案列表：`auth_url` 和 `active_task` 标签仅检查值是否存在
  - 编辑器：移除三个 toggle 开关（使用全局账号密码、跟随全局认证地址、跟随全局任务）
  - 账号凭证、认证地址、执行任务字段现在始终显示

### refactor
- 将监控配置从 `ProfileSettings` 移动到 `GlobalSettings`
  - 移动字段：check_interval_seconds、pause_enabled、pause_start_hour、pause_end_hour、network_targets、http_targets、enable_tcp_check、enable_http_check、enable_local_check、check_auth_url、auth_url_targets、url_check_urls、network_check_timeout
  - `ProfileSettings` 不再包含监控配置字段，仅保留凭证和自定义变量

### refactor
- `app/services/runtime_config.py` 从 `global_settings` 合并监控配置
  - `_build_config_payload` 新增监控配置字段合并

### refactor
- `app/services/config_service.py` 监控配置保存到 `global_settings` 而非 `profile`
  - `_update_global_settings` 新增监控配置更新
  - `save_config_combined` 移除 profile 的监控配置更新

### refactor
- `app/utils/config_utils.py` 更新 `PROFILE_FIELDS` 和 `GLOBAL_FIELDS`
  - `PROFILE_FIELDS`：移除所有监控配置字段（保留凭证和 custom_variables）
  - `GLOBAL_FIELDS`：新增所有监控配置字段

### refactor
- 将浏览器配置从 `ProfileSettings` 移动到 `GlobalSettings`
  - 移动字段：headless、browser_timeout、browser_navigation_timeout、login_timeout、browser_user_agent、browser_low_resource_mode、browser_disable_web_security、browser_extra_headers_json、browser_args、stealth_mode、stealth_custom_script、browser_locale、browser_timezone、browser_viewport_width、browser_viewport_height
  - 删除 `_BrowserFieldsMixin` 类
  - `ProfileSettings` 不再继承 `_BrowserFieldsMixin`
  - `MonitorConfigPayload` 不再继承 `_BrowserFieldsMixin`

### refactor
- `app/utils/config_utils.py` 更新 `PROFILE_FIELDS` 和 `GLOBAL_FIELDS`
  - `PROFILE_FIELDS`：移除所有浏览器配置字段
  - `GLOBAL_FIELDS`：新增所有浏览器配置字段

### refactor
- `app/services/runtime_config.py` 从 `global_settings` 合并浏览器配置
  - `_build_config_payload` 函数新增浏览器配置合并逻辑

### refactor
- `app/services/config_service.py` 更新配置保存逻辑
  - `_update_global_settings` 移除浏览器配置更新（浏览器配置现在是 GlobalSettings 的一部分）
  - `build_runtime_config` 新增 `global_settings` 参数，从 `GlobalSettings` 获取浏览器配置

### fix
- `app/api/autostart.py` 修复 `data.system` 引用为 `data.global_settings`
- `app/api/repo.py` 修复 `data.system` 引用为 `data.global_settings`

### test
- 更新测试文件适配浏览器配置移动到 `GlobalSettings`
  - `tests/test_config/test_config_schemas.py`：浏览器字段测试改用 `GlobalSettings`
  - `tests/test_services/test_config_service.py`：更新 `test_updates_browser_config` 测试
  - `tests/test_utils/test_config_utils_fix.py`：移除 `headless` 字段检查
  - `tests/test_app/test_backend_services.py`：更新测试数据结构
  - `tests/test_api/test_config_fix.py`：更新测试数据结构

### refactor
- `app/utils/config_utils.py` 更新 `PROFILE_FIELDS` 和新增 `GLOBAL_FIELDS`
  - `PROFILE_FIELDS`：移除全局配置字段（`backend_log_level`、`frontend_log_level`、`access_log`、`minimize_to_tray`、`auto_open_browser`、`startup_action`、`autostart_lightweight`、`max_retries`、`retry_interval`、`log_retention_days`、`proxy`、`app_port`、`use_global_credentials`、`shell_path`），新增 `active_task`
  - 新增 `GLOBAL_FIELDS` 常量，包含 `GlobalSettings` 中的所有字段

### refactor
- `app/services/profile_service.py` 更新 ProfileService 支持新的 ProfilesData 结构
  - `load` 方法：移除 profiles 目录的单独读写，直接从 `settings.json` 加载完整 ProfilesData
  - `save` 方法：移除 profiles 目录的单独写入，所有数据（含 profiles）保存到单个 `settings.json`
  - 移除 `_profiles_dir` 属性和 profiles 目录创建逻辑
  - 代码行数从 255 行减少到 220 行（减少 35 行）

### test
- `tests/test_services/test_profile_service.py` 添加 ProfileService 测试
  - `TestProfileServiceLoad` 测试类：测试文件缺失返回默认值、读取 settings.json、损坏文件处理、缓存行为
  - `TestProfileServiceSave` 测试类：测试创建 settings.json、保存后加载 roundtrip、不再创建 profiles 目录

### refactor
- `app/services/config_service.py` 简化配置保存逻辑，凭证保存到 profile
  - 将 `_update_system_settings` 重写为 `_update_global_settings`
  - 函数不再处理凭证字段（username/password/auth_url/carrier），仅更新系统级配置
  - 更新 `save_config_combined` 函数，将凭证保存到活动 profile 而非 system
  - 保存逻辑从 "system + default 方案" 改为 "global_settings + 活动 profile"
  - 自动创建不存在的活动 profile

### test
- `tests/test_services/test_config_service.py` 添加配置保存逻辑测试
  - `TestUpdateGlobalSettings` 测试类：测试全局设置更新、日志级别归一化、代理地址去空白、不更新凭证
  - `TestSaveConfigCombined` 测试类：测试保存到活动 profile、自动创建 profile、更新全局设置、保存凭证、更新监控/浏览器配置、密码加密

### fix
- `main.py` 修复 `build_runtime_config` 调用，移除 `data.system` 参数
  - `ProfilesData` 已无 `system` 字段，改为 `global_settings`
- `app/services/engine.py` 修复 `build_runtime_config` 调用，移除 `data.system` 参数

### refactor
- `app/services/runtime_config.py` 简化配置加载逻辑，删除 `use_global_*` 相关代码
  - 删除 `extract_profile_fields` 和 `PROFILE_FIELDS` 的导入和使用
  - 删除 `use_global_*` 相关的条件判断（10+ 个分支）
  - 简化为直接从 profile 构建 payload，合并 global_settings 系统配置
  - 调用 `migrate_config_if_needed` 进行迁移
  - 代码行数从 232 行减少到 199 行（减少 33 行）

### feat
- `app/services/runtime_config.py` 实现配置迁移逻辑
  - 新增 `migrate_config_if_needed()` 函数
  - 将旧格式 `SystemSettings` 中的凭证迁移到 default profile
  - 迁移后清空 system 中的凭证数据
  - 添加 `ProfileSettings` 到导入列表

### test
- `tests/test_services/test_runtime_config.py` 添加配置迁移测试
  - `TestMigrateConfig` 测试类包含 3 个测试用例
  - 测试迁移凭证到 default profile
  - 测试没有凭证时不执行迁移
  - 测试迁移保留现有 profile 配置

### feat
- `app/schemas.py` 扩展 `ProfileSettings` 类，添加浏览器配置和监控配置字段
  - 继承 `_BrowserFieldsMixin` 获取所有浏览器配置字段
  - 添加监控配置字段：check_interval_seconds、pause_enabled、pause_start_hour、pause_end_hour、network_targets、http_targets、enable_tcp_check、enable_http_check、enable_local_check、check_auth_url、auth_url_targets、url_check_urls、network_check_timeout、custom_variables
  - 保留 use_global_credentials、use_global_auth_url、use_global_task 标志位
  - 添加 auth_url 验证器
  - 更新类文档字符串为"方案配置 — 所有业务配置的唯一数据源"

### test
- `tests/test_config/test_config_schemas.py` 添加 `TestProfileSettings` 测试类
  - 测试默认值、自定义值、无效认证地址
  - 测试浏览器字段默认值、监控字段默认值
  - 测试浏览器请求头 JSON 验证

### feat
- `app/schemas.py` 添加 `GlobalSettings` 类
  - 仅包含系统级设置：日志、UI、网络、应用、重试、source 级别配置
  - 不包含业务逻辑（凭证、监控、浏览器配置）
  - 位于 `_SystemFieldsMixin` 之后，作为统一 Profile 配置架构的第一步

### test
- `tests/test_config/test_config_schemas.py` 添加 `TestGlobalSettings` 测试类
  - 测试默认值、自定义值、无效日志级别、日志级别归一化

### feat
- `app/schemas.py` 更新 `ProfilesData` 类，使用 `GlobalSettings` 替代 `SystemSettings`
  - `system: SystemSettings` 改为 `global_settings: GlobalSettings`
  - 添加 `ensure_default_profile` model_validator 确保 default profile 自动创建

### test
- `tests/test_config/test_config_schemas.py` 更新 `TestProfilesData` 测试类
  - 新增 test_default_profile_auto_created、test_global_settings_default、test_custom_profiles
  - 更新已有测试适配字段重命名和自动创建 default profile 行为

### test
- `tests/test_services/test_monitor_service.py` 添加自动切换方案标志位测试用例
  - `test_check_profile_switch_sets_flag`: 方案切换时设置标志位
  - `test_check_profile_switch_no_change`: 方案未变化时不设置标志位
  - `test_consume_profile_switch_flag`: 消费标志位行为验证

### fix
- `app/services/engine.py` 自动切换方案后重启监控
  - `_do_network_check` 中检查 `consume_profile_switch_flag()` 标志位
  - 检测到方案切换时执行停止 → 重载配置 → 重启监控流程

### feat
- `app/services/monitor_service.py` 添加自动切换方案的重启标志位
  - 新增 `_profile_switch_needed` 实例变量
  - `_check_profile_switch` 方案切换成功时设置标志位
  - 新增 `consume_profile_switch_flag()` 方法供 engine 消费标志位

### refactor
- 删除 `app/services/monitor_service.py` 中形同虚设的冷却时间机制
  - 删除 `GATEWAY_CHECK_COOLDOWN_SECONDS = 60` 常量
  - 删除 `_last_gateway_check_time` 实例变量
  - 删除 `_check_profile_switch` 中的冷却时间检查逻辑
  - 原因：检测间隔 300 秒远大于冷却 60 秒，冷却永远不会触发

## 2026-06-14

### feat
- 任务编辑器 name/description 输入框与 JSON 配置双向实时同步
  - 修改输入框自动更新 JSON 中的对应字段
  - 修改 JSON 中的 name/description 自动更新输入框
  - 加载模板时同步字段

### fix
- 修复 `is_local_network_connected()` 未正确过滤回环接口的问题
  - Windows: `Loopback Pseudo-Interface 1`，原精确匹配无法命中
  - Linux: `lo`，macOS: `lo0`
  - 改为 `name.lower().startswith("lo")`，一条规则兼容三平台

### docs
- 全面更新 README.md：修正项目结构（`backend/`→`app/`、`src/`→`app/`子目录）、入口文件（`app.py`→`main.py`）、CLI 参数、模块路径、技术栈
- 全面更新 `docs/api-doc.md`：新增日志级别、OCR 管理、脚本二进制列表、自启动模式等端点；移除已删除的配置备份、日志文件查看器等端点
- 全面更新 `docs/task-manual.md`：修正架构概览、核心模块路径、环境变量参考（仅保留 6 个仍在使用的环境变量）、任务存储结构
- 更新 `docs/update_log.md`：新增 v4.0.2 版本条目

### refactor
- 移除 `CAMPUS_AUTH_AUTOSTART` 环境变量，改用 `--source autostart` CLI 参数
  - 删除 macOS/Linux/Windows 三处环境变量注入
  - `_autostart_cli_args()` 返回值加 `--source autostart`
  - 删除 `_detect_launch_context()` 函数，直接从 argparse 读取
- 删除 `app/network/decision.py` 中未使用的 `check_campus_network_status()` 函数
- 清理 `tests/test_core/test_network_probes.py` 中对应的导入和测试类 `TestCheckCampusNetworkStatus`
- 删除 `app/schemas.py` `validate_custom_variables` 方法内重复的 `import re`（模块级已有）
- 删除 4 个前端未调用的 API 路由及对应测试：
  - `DELETE /api/config/source-level/{source}`（`app/api/config.py`）
  - `GET /api/debug/status`（`app/api/debug.py`）
  - `GET /api/profiles/active`（`app/api/profiles.py`）
  - `GET /api/scheduled-tasks/{task_id}`（`app/api/scheduled_tasks.py`）
- 重写 `docs/api-doc.md`，使其与实际代码中的 API 端点完全一致：
  - 新增 log-levels、source-level、default-stealth-script、scripts/binaries、shells、autostart/mode、OCR 相关、task-manual 端点
  - 移除不存在的 profiles/active、debug/status、scheduled-tasks/{task_id} GET、配置备份段
  - 更新静态资源路径
- 重写 `docs/task-manual.md`，修复所有过时的模块路径和引用：
  - 架构概览：更新模块表和调用链，新增 ScheduleEngine、TaskRegistry 等模块
  - 所有导入路径：`src/` → `app/`，`backend/` → `app/`
  - 环境变量：移除已迁移至 `config/settings.json` 的大量配置项，仅保留 6 个仍需环境变量的项
  - 任务文件存储：更新目录结构为 `tasks/browser/`、`tasks/scripts/`、`tasks/scheduled/`
  - TaskManager：`active.txt` 改为通过 API 管理活动任务
  - 网络探测：更新为 URL 响应检测、TCP/HTTP 可配置目标、psutil 本地网络检测
