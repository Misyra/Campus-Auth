# 🔍 Ponytail 审计报告复核 — 问题条目

**复核日期**: 2026-06-29
**源报告**: `docs/ponytail-audit-2026-06-29.md`

---

## 一、高风险 — 不应按报告直接执行

### 1.4 test_debug_service.py — 不能直接删除

**位置**: 报告 §1.4（P0）
**问题**: 报告称"迁移 5 个独有测试类后删除"，但经逐项验证，该文件中 **6 个测试类（11 个测试）全部覆盖了 `test_debug_session_manager.py` 未触及的独特分支**：

| 独有测试类 | 测试数 | 覆盖内容 | session_manager 是否覆盖 |
|---|---|---|---|
| `TestDebugTimeoutWatcherActualTimeout` | 3 | 浏览器非活跃跳过关闭、锁内代数变化、实际超时完整路径 | ❌ 仅测试重置，未测试这些分支 |
| `TestStartTemplateVarReplacement` | 1 | URL 模板变量 `{{domain}}` 替换 | ❌ mock 为空 `{}` |
| `TestNextStepSessionReplaced` | 2 | 执行期间会话被替换的竞态条件 | ❌ |
| `TestRunAllSessionReplaced` | 3 | run_all 循环中会话被替换/停止 | ❌ |
| `TestStopTempDirCleanupError` | 2 | 清理时 `iterdir`/`unlink` 异常处理 | ❌ 仅测试成功路径 |

**操作**: 保留文件，或先将这 11 个测试完整迁移到 `test_debug_session_manager.py` 后再删除。**直接删除会丢失有价值的边缘情况覆盖**。

---

### 4.3 StepHandler ABC — 不应简化

**位置**: 报告 §4.3（P2）
**标签**: `yagni`
**问题**: 报告称"ABC 基类的 ABCMeta 开销无实际收益"。实际分析：
- `StepHandler` 提供 **5 个共享方法**（`resolve_params`、`_parse_selectors`、`_try_candidates_with_fallback`、`_resolve_frame`、`_find_element`）
- **10 个子类**（`InputHandler`、`ClickHandler`、`SelectHandler`、`ClickSelectHandler`、`WaitHandler`、`WaitUrlHandler`、`EvalHandler`、`ScreenshotHandler`、`SleepHandler`、`OcrHandler`）均复用基类功能
- `DEFAULT_HANDLERS` 路由表依赖多态调度
- `@abstractmethod` 提供了方法签名的契约约束，防止子类遗漏关键方法

**操作**: **保留现状**。这是已验证的设计模式，非过度工程。

---

### 6.5 detectPerformance — 活跃功能，非死代码

**位置**: 报告 §6.5（P3）
**标签**: `delete`
**问题**: 报告称"投机性优化"。实际：
- `setTimeout(detectPerformance, 5000)` 在 `frontend/app.js:79` **被调用执行**
- FPS 检测 < 30fps 时添加 `no-backdrop-filter` 类，禁用毛玻璃
- `appearance.js:41,43` 也管理该类——说明是**有意识的用户体验特性**
- 删除将移除自动性能降级能力，低端设备用户需手动切换

**操作**: 如需删除，应经产品/设计确认。标记为"可选优化"而非死代码。

---

### 4.5 set_autostart_mode — 前端有调用

**位置**: 报告 §4.5（P2）
**标签**: `delete`
**问题**: 报告称"与 enable_autostart 重复"但未核实前端引用：
- 后端路由 `POST /api/autostart/mode`
- 前端 `frontend/js/methods/config.js:329` 调用 `this.$apiService.autostart.setMode()`
- 删除将直接导致 404

**操作**: 如要合并，需前后端同步修改。不能单独删除后端路由。

---

## 二、描述不准确 — 需修正

### 1.1 test_monitor_service.py — 重叠比例和独有测试数量有误

**位置**: 报告 §1.1
**标签**: `delete`

| 报告声称 | 实际 |
|---------|------|
| 85% 重叠（19/21 类） | ~70% 重叠（16/23 类） |
| 21 个测试类 | 实际 23 个 |
| 仅 2 个独有类需迁移 | 7 个"独有"类，经核实： |
| | — `TestManualLoginTimeout`、`TestManualLoginConsumerDead`：**完全被 test_engine.py 覆盖**（且后者有 70s 挂起 bug，test_engine.py 版本更优） |
| | — `TestStartMonitoringPutNowait`、`TestNetworkStateSetInConsumer`：**完全被 test_engine.py 覆盖** |
| | — `TestShutdownSynchronous`：幂等测试已覆盖，仅队列变体微有不同 |
| | — **真正需保留**：`TestProfileSwitchFlag`（3 个测试，直接测试 `NetworkMonitorCore` 内部方法）+ `TestSaveProfileApplyId`（1 个，API 回归测试，建议迁移到 test_api/） |

**操作**: 迁移 4 个测试后可安全删除 ~900 行，但比例从 85% 修正为约 70%。

---

### 1.5 文件名错误 — test_src_utils.py ≠ test_utils.py

**位置**: 报告 §1.5
**标签**: `shrink`

| 报告声称 | 实际 |
|---------|------|
| 目标文件 | `tests/test_utils/test_src_utils.py`（1,674 行） |
| 实际应操作文件 | `tests/test_utils/test_utils.py`（1,117 行） |
| 测试内容 | `test_src_utils.py`：浏览器、系统托盘、Playwright 引导/Worker |
| | `test_utils.py`：crypto、logging、files、platform 等工具函数 |

`test_src_utils.py` 与 `test_crypto.py`、`test_logging_fix.py`、`test_files_fix.py` **无重叠**。报告中的重叠对照表对应的是 `test_utils.py`。

**操作**: 重审时修正目标文件为 `test_utils.py`。

---

### 1.6 test_logging_fix.py — 对比文件错误

**位置**: 报告 §1.6
**标签**: `shrink`
**问题**: 报告称该文件是 `test_src_utils.py` `TestLogConfigCenter` 的严格子集。但：
- `test_src_utils.py` 中**不存在** `TestLogConfigCenter`（该文件测试的是 browser/system_tray）
- 正确的对照对象是 `test_utils.py`，而 `test_logging_fix.py` 的 3 个测试验证的是 **`_LEVEL_ORDER` 类常量行为**——`test_utils.py` 的 `TestLogConfigCenter` 中无对应测试

**操作**: 修正描述。可合并但非删除。合并时保留 `_LEVEL_ORDER` 相关的 2 个独有测试。

---

### 4.6 404 guard 数量低估

**位置**: 报告 §4.6
**标签**: `native`
**问题**: 报告称"7 个 404 guard 重复"。实际统计：

| 文件 | 数量 |
|------|------|
| `app/api/tasks.py` | 1 |
| `app/api/scheduled_tasks.py` | 4 |
| `app/api/scripts.py` | 2 |
| `app/api/tools.py` | 4 |
| `app/api/profiles.py` | 1 |
| `app/api/icons.py` | 1 |
| **合计** | **13** |

**操作**: 修正数量。提取 FastAPI 依赖可削减 ~30 行（非 15 行）。

---

### 6.4 _validateConfig — "调用方不检查"不准确

**位置**: 报告 §6.4
**标签**: `delete`
**问题**: 报告称"调用方不检查返回值，不阻止保存"。实际 `config.js:117`：

```javascript
saveConfig() {
    const warnings = this._validateConfig();
    if (warnings.length > 0) {
        warnings.forEach(w => this._showToast(false, w));
    }
    // ... 继续保存
}
```

调用方 **检查了** `.length` 并 **toast 展示警告**。不阻止保存的判断正确，但"不检查返回值"的描述失实。该方法是 advisory validation，非死代码。

**操作**: 如需修改，应改为实际阻止保存或删除；不可按"死代码"处理。

---

### 5.3 _temp_dir 非重复

**位置**: 报告 §5.3
**标签**: `shrink`
**问题**: 报告称 `container.py:28` 的 `self._temp_dir = project_root / "temp"` 与 `constants.TEMP_DIR` 重复。实际：
- `container.py` 的 `self._temp_dir` = `project_root / "temp"`
- `debug_service.py:38` 的 `self._temp_dir` = `project_root / "temp" / "debug"`
- 两者路径**不同**，非重复计算

**操作**: 条目应仅涉及 container.py 一处可改用 `TEMP_DIR`。debug_service.py 不应列为重复。

---

## 三、执行优先级修正

| 优先级 | 范围 | 原风险 | 复核后风险 |
|--------|------|--------|-----------|
| P0 | 测试瘦身 | 最低 | — **1.4 提升至中（需先迁移）** |
| P1 | 死代码删除 | 低 | — **4.5 提升至中（前端有调用）** — **6.5 标记为活跃功能** |
| P2 | 服务层内联 | 中 | — **4.3 移除（不应执行）** |
| P3-P4 | 前端/工具层 | 低/中 | 不影响优先级 |

---

## 汇总

| 类别 | 数量 |
|------|------|
| 不应执行 | 4 项（1.4 直接删、4.3、6.5、4.5 直接删） |
| 描述需修正 | 9 项（1.1、1.5、1.6、3.1、4.6、5.3、6.4、3.2、1.2） |
| 数量/比例修正 | 5 项（1.1 重叠率、4.6 404 计数、1.4 测试类计数、1.5 文件名、1.6 对照对象） |
| 可安全执行 | 约 44 项（死代码删除、包装内联、导出缩减等） |
