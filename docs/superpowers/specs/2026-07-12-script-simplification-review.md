# 设计审查报告：脚本任务系统简化设计

**审查日期**: 2026-07-12
**审查范围**: `docs/superpowers/specs/2026-07-12-script-simplification-design.md`
**审查方法**: 逐项与实际代码交叉验证

---

## 审查结论

设计方向正确（砍过度设计、按扩展名固定分发），但**存在多个会导致功能损坏的关键遗漏**，以及大量未覆盖的改动点。当前状态**不可直接实施**，需补全后再启动。

---

## 一、关键问题（会导致功能损坏 / 运行时崩溃）

### 1.1 缺少存量数据迁移策略

**问题**: 设计将 JSON 文件中的 `type` 字段语义从任务类别（`"script"`）改为脚本语言（`"py"`/`"bat"`/`"ps1"`/`"sh"`/`"exe"`）。但现有 `tasks/scripts/*.json` 文件中的值是 `"script"`：

```json
// 现有格式
{ "type": "script", "name": "...", "binary_path": "...", "content": "..." }
```

新代码读取时会得到 `script_type = "script"`，不在合法枚举中，`_build_cmd` 会抛 `ValueError`。

**设计 §7.2 只讨论了回滚**（"旧格式仍为 JSON，回滚后旧代码可直接读取"），但完全没有讨论前向迁移。

**建议**: 补充迁移方案，例如：
- `load_task` 读取时：若 `type == "script"`，根据 `binary_path` 推断语言类型（含 python → py，cmd → bat，powershell → ps1，bash/sh → sh，空 → py），并回写新格式
- 或提供一次性迁移脚本

---

### 1.2 `get_script` 和 `run_script` API 的 `type != "script"` 检查未更新

**问题**: `app/api/scripts.py` 中两处类型检查：

```python
# scripts.py:49 (get_script)
if not task or task.get("type") != "script":

# scripts.py:92 (run_script)
if not task or task.get("type") != "script":
```

设计将 `get_task_detail` 返回的 `type` 从 `"script"` 改为 `"py"` 等具体类型后，这两处检查会**拒绝所有脚本任务**（返回 404）。

设计 §4.5 只提到 "改用 `task["type"]` 构造 ScriptRunner"，但未提及这两处类型检查的更新。

**建议**: 明确将这两处改为 `task.get("type") not in ("py", "bat", "ps1", "sh", "exe")`。

---

### 1.3 `save_script` API 强制覆写 `type` 为 `"script"`

**问题**: `app/api/scripts.py:61`：

```python
data = {**payload, "type": "script"}
```

这会覆盖前端传来的真实类型（`py`/`bat`/...），导致保存的 JSON 文件 `type` 始终为 `"script"`。

设计 §4.5 提到 "PUT 请求: 接收 `type`/`content`/`path`"，但未提及删除此处的强制覆写。

**建议**: 改为 `data = {**payload}`，让 `type` 字段透传，并在 `_save_script_task_validated` 中校验 `type` 合法性。

---

### 1.4 `_save_script_task` / `_save_script_task_validated` 对 `exe` 类型的 content 校验会拒绝保存

**问题**: 当前保存逻辑强制要求 `content` 非空：

```python
# manager.py:409-411 (_save_script_task)
script_content = config.get("content", "")
if not script_content.strip():
    logger.warning("脚本内容不能为空")
    return False

# manager.py:589-591 (_save_script_task_validated)
content = config.get("content", "")
if not content.strip():
    return False, "脚本内容不能为空"
```

`exe` 类型只有 `path` 没有 `content`，会被直接拒绝保存。

设计 §4.5 只说 "写入新 `type` 字段，不再写 `binary_path`"，未提及校验逻辑的适配。

**建议**: 按 `type` 分支校验——文本脚本（py/bat/ps1/sh）检查 `content` 非空；`exe` 检查 `path` 非空。

---

### 1.5 `_save_script_task` 硬编码 `"type": SCRIPT_TASK_TYPE`

**问题**: `manager.py:418-424`：

```python
save_data = {
    "type": SCRIPT_TASK_TYPE,  # 硬编码 "script"
    "name": config.get("name", task_id),
    ...
}
```

设计将 `type` 改为 `py`/`bat`/... 后，此处仍会写入 `"script"`。设计说 "写入新 `type` 字段" 但未说明改为 `config.get("type", "py")`。

**建议**: 明确改为 `"type": config.get("type", "py")`。

---

### 1.6 `.py` 旧格式文件完全未提及

**问题**: `TaskManager` 支持 `scripts/` 目录下的纯 `.py` 文件（legacy 格式），相关代码分布在：

- `_safe_task_path`（manager.py:133）: 搜索 `.json` 和 `.py`
- `list_script_tasks`（manager.py:298-321）: 扫描 `.py` 文件
- `load_task`（manager.py:349-366）: 处理 `.py` 文件
- `delete_task`（manager.py:443）: 删除 `.py` 文件

设计完全没有提及这些 `.py` 文件的处理。在新类型系统中，`.py` 文件应该等价于 `type: "py"`，但 `load_task` 返回的 `ScriptTaskInfo` 需要设置 `script_type="py"`。

**建议**: 明确 `.py` 文件的处理策略——保留兼容（映射为 `type: "py"`）还是删除支持。如果保留，需列出所有需要适配的位置。

---

## 二、显著遗漏（设计不完整，实施时会卡住）

### 2.1 `TaskSummary` 模型未更新

`schemas.py:176-183` 的 `TaskSummary` 有 `binary_path: str = ""` 字段，`list_scripts` 端点使用 `response_model=list[TaskSummary]`。设计未提及更新此模型（移除 `binary_path`、确保 `type` 字段）。

§5 删除清单中也未列出 `TaskSummary.binary_path`。

### 2.2 前端 `availableBinaries` 状态未提及删除

`frontend/js/data/scripts.js:5` 定义了 `availableBinaries: []`。设计提到删除 `fetchAvailableBinaries` 方法，但未提及删除此响应式状态。

### 2.3 `binaryOptions` 计算属性未提及删除

`app-options.js:220-227` 定义了 `binaryOptions` 计算属性。设计提出了替代的 `scriptTypeOptions`，但未明确说删除 `binaryOptions`。

### 2.4 `scriptTargetOptions` 计算属性未提及

`app-options.js:95-103` 的 `scriptTargetOptions` 使用 `binary_path` 和 `getBinaryName`：

```javascript
label: s.name + (s.binary_path ? ' (' + this.getBinaryName(s.binary_path) + ')' : ''),
```

需改为基于 `type` 字段显示。设计未提及。

### 2.5 `getBinaryName` 函数未处理

`frontend/js/methods/utils.js:25` 定义了 `getBinaryName`，在 `scripts.js` 和 `app-options.js` 中被引用。移除 `binary_path` 后此函数无用。设计未提及删除或改造。

### 2.6 `scripts.html` 中的 binary badge 未提及

`scripts.html:55-56`：

```html
<span v-if="script.binary_path" class="binary-badge">{{ getBinaryName(script.binary_path) }}</span>
<span v-else class="binary-badge binary-default">Python</span>
```

需改为基于 `type` 显示类型标签。设计只提到替换编辑器中的选择器，未提到列表页的 badge。

### 2.7 `_inferScriptExtension` 函数名不一致

设计提到 "`suggestExtension` 改为基于 `type` 字段"，但实际代码中的函数名是 `_inferScriptExtension`（`scripts.js:268`）。设计使用了不存在的函数名。

### 2.8 `importScript` 方法未提及

`scripts.js:178-208` 的 `importScript` 导入文件时设置 `binary_path: ''`。需改为根据文件扩展名设置 `type`（.py→py, .sh→sh, .bat→bat, .ps1→ps1）。设计未提及。

### 2.9 `scripts.html` 帮助文本未提及

`scripts.html:149-155` 的帮助文本描述了 "执行程序" 选择（Python/Shell/自定义），需要更新为类型选择说明。`scripts.html:179-184` 还有 Shell curl 示例。设计只提到 "帮助文本按 type 动态显示"（编辑器内），未提到这个独立的帮助卡片。

### 2.10 测试文件遗漏

设计 §6.1 列出的测试文件不完整，以下文件也引用了被删除的代码：

| 遗漏的测试文件 | 引用的被删内容 |
|---|---|
| `tests/test_services/test_scheduler_service.py` | `detect_shells`、`_execute_shell`、`shell_path` |
| `tests/test_services/test_scheduled_tasks.py` | `get_default_shell`、`shell_path` |
| `tests/test_services/test_task_executor_lifecycle.py` | `shell_path`、`_execute_shell`、`get_default_shell`（约 20 处） |
| `tests/test_integration/test_scheduled_task.py` | `shell` 任务类型、`shell_path`、`command` |
| `tests/test_app/test_backend_services.py` | `binary_path`（2 处） |
| `tests/test_services/test_config_builder.py` | `shell_path`（2 处） |
| `tests/test_api/test_api_scripts_routes.py` | `binary_path`（2 处）、`list_binaries` 测试 |

### 2.11 `ShellCommandPolicy` 在新 `ScriptRunner` 中的使用未展示

设计展示了 `_build_cmd` 和 `_run_exe` 的实现，但 `run()` 方法只写了 "按 script_type 分发到 `_run_text_script` / `_run_exe`"。`_run_text_script` 的完整实现（临时文件写入、ShellCommandPolicy 创建与调用、超时处理、stdout/stderr 捕获、清理）未展示。这是核心执行路径，不能省略。

### 2.12 `execute_task` 错误消息未更新

`task_executor.py:291`：

```python
f"不支持的任务类型: {task_type}，当前支持: script、browser、shell"
```

移除 shell 后应改为 "当前支持: script、browser"。设计未提及。

---

## 三、设计细节问题（需澄清/改进）

### 3.1 ps1 命令缺少 `-WindowStyle Hidden`

当前代码的 ps1 命令包含 `"-WindowStyle", "Hidden"` 来抑制 PowerShell 窗口弹出。设计的 `_build_cmd` 去掉了此参数。

`ShellCommandPolicy.run_sync` 使用 `CREATE_NO_WINDOW_FLAG`，理论上可以补偿。但 `CREATE_NO_WINDOW` 针对控制台窗口，`-WindowStyle Hidden` 针对 PowerShell 的 WPF 窗口，两者机制不同。建议验证在 Windows 上跑 ps1 脚本时是否会有窗口闪现，或在设计中说明去掉的理由。

### 3.2 `exe` 类型绕过安全策略

设计明确 `exe` 类型不经过 `ShellCommandPolicy`，直接 `subprocess.Popen`。这意味着任意路径的可执行文件都可以被启动，没有白名单校验。

虽然这是用户主动配置的，但与当前系统"所有执行路径必须通过白名单"的安全模型不一致。建议在设计中说明显式接受此风险，或至少做基本的路径校验（如禁止 UNC 路径、禁止相对路径）。

### 3.3 `exe` 类型的 `timeout` 参数无意义

`ScriptRunner.__init__` 接受 `timeout`，但 `_run_exe` 是 fire-and-forget，不使用 timeout。这不算 bug，但 `timeout` 参数对 exe 类型完全无效，建议在文档或类型签名中标注。

### 3.4 章节编号跳号

设计从 §4.5 直接跳到 §4.7，缺少 §4.6。格式问题，但影响引用。

### 3.5 `_ALLOWED_BINARIES` 使用裸名称

设计的 allowlist 使用裸名称 `"cmd.exe"` / `"powershell.exe"` / `"sh"`，而 `sys.executable` 是绝对路径。`ShellCommandPolicy._is_allowed` 做大小写不敏感比较。这在 Windows 上可以工作（因为 `_build_cmd` 也用裸名称），但与当前系统使用 `shutil.which()` 解析完整路径的做法不同。建议确认这种混用不会导致匹配问题。

### 3.6 回滚方案过于乐观

§7.2 说 "旧格式脚本任务文件仍为 JSON，回滚后旧代码可直接读取"。但如果新代码已经将文件改写为新格式（`type: "py"` 而非 `type: "script"`），旧代码的 `_save_script_task` 会硬编码写回 `"type": "script"`，但 `load_task` 读取时 `data.get("binary_path", "")` 会得到空串（因为新格式不写 `binary_path`）。功能上可以工作，但用户配置的 `binary_path` 信息会丢失。建议在回滚方案中说明此数据损失。

---

## 四、已验证正确的部分

以下设计断言已与代码交叉验证，确认准确：

- ✅ `ScriptRunner` 支持 15+ 种解释器（`_BINARY_EXT_MAP` 确有 16 个映射）
- ✅ `binary_path` 字段的存在和传参链路（`ScriptRunner.__init__` → `_build_cmd` → `_content_temp_file`）
- ✅ `shell` 定时任务类型后端有完整执行链路但前端从未暴露（`scheduledTaskTypeOptions` 只有 script/browser）
- ✅ 设置页 "Shell 路径" 唯一消费者是已死的 shell 任务类型
- ✅ `_execute_script` 已使用 `task_manager.get_task_detail`（非 `registry.get_task`）
- ✅ `_execute_script` 仍传 `binary_path` 给 `ScriptRunner`（manager.py:340）
- ✅ `shell_utils.py` 仅 3 个函数，消费者均可追溯
- ✅ `login_orchestrator.py:56` 确有 `d["shell_path"]` 透传，且 worker 进程不消费此字段
- ✅ `app/api/config.py:176` 确有 `"app_settings.shell_path": "Shell路径"` 别名
- ✅ 前端 `fetchShells` 初始化调用在 `lifecycle.js:29`
- ✅ `constants.js:150` 确有 `shell_path: ""` 默认值
- ✅ `settings.css:736` 确有 `.shell-custom-input` 样式

---

## 五、建议的补充工作清单

在实施前，设计文档需补充以下内容：

1. **存量数据迁移方案**（§1.1）—— 最高优先级
2. **`get_script` / `run_script` / `save_script` 三处 API 适配**（§1.2, §1.3）
3. **`_save_script_task` / `_save_script_task_validated` 的 exe 校验逻辑**（§1.4, §1.5）
4. **`.py` 旧格式文件处理策略**（§1.6）
5. **`TaskSummary` 模型更新**（§2.1）
6. **前端遗漏项清单**（§2.2-§2.9）—— 建议整理成与后端同等粒度的改动表
7. **完整测试文件清单**（§2.10）—— 补全所有受影响测试
8. **`_run_text_script` 完整实现**（§2.11）
9. **`execute_task` 错误消息更新**（§2.12）
10. **ps1 `-WindowStyle Hidden` 去除说明**（§3.1）
