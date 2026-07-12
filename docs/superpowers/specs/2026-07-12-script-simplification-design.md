# 脚本任务系统简化设计

**日期**: 2026-07-12
**状态**: 设计已锁定,待实施
**作者**: brainstorming 协作产出

## 1. 背景与动机

当前脚本任务系统存在严重的过度设计:

- `ScriptRunner` 支持 15+ 种解释器(python/node/ruby/php/perl/lua/r/cmd/powershell/bash/zsh/fish...),实际用例 99% 是 Python/PS1/exe
- `binary_path` 字段让用户自选解释器,前端有 binary 选择器、`detect_binaries` 探测逻辑、`_BINARY_EXT_MAP` 语言→扩展名映射
- 定时任务 `shell` 类型(命令字符串)在后端有完整执行链路,但前端 UI 从未暴露——死代码
- 设置页的 "Shell 路径" 配置项唯一消费者是已死的 shell 任务类型
- `_execute_script` 已使用 `task_manager.get_task_detail`(bug 已修复),但仍传 `binary_path` 给 `ScriptRunner`——需随重构一并清理

本次重构目标:**按扩展名固定分发,砍掉所有解释器探测和选择逻辑**。

## 2. 目标与非目标

### 目标

- 脚本任务支持 5 种固定类型:`py` / `bat` / `ps1` / `sh` / `exe`
- 每种类型对应固定解释器,无探测、无选择、无降级
- 移除 `shell` 定时任务类型及其所有衍生代码
- 移除设置页 "Shell 路径" 配置项
- `_execute_script` 移除 `binary_path` 传参,改用 `script_type` 分发

### 非目标

- 不支持用户自定义解释器路径(需要其他语言就写 `.bat`/`.sh` 包一层)
- 不做平台预检(Windows 上跑 `.sh` 让 OS 自然报错)
- 不重写浏览器任务系统(`browser` 类型保持现状)
- 不引入新的任务类型
## 3. 设计概览

### 3.1 类型与解释器映射

| type | 解释器 | 命令模板 | 说明 |
|------|--------|----------|------|
| `py` | `sys.executable` | `[python, file]` | 项目内置 Python |
| `bat` | `cmd.exe` | `[cmd.exe, /c, file]` | Windows cmd |
| `ps1` | `powershell.exe` | `[powershell.exe, -NoProfile, -ExecutionPolicy, Bypass, -File, file]` | Windows PowerShell 5.1(系统必装) |
| `sh` | `sh` | `[sh, file]` | Unix sh;Windows 上若无 sh.exe 由 OS 报 FileNotFoundError |
| `exe` | 无 | `subprocess.Popen([path])` 不等待 | 启动即返回成功,启动失败才报错 |

**设计原则**:不限制用户。`.sh` 在 Windows 上不预检——用户装了 git bash 就能跑,没装就收到 OS 的自然错误反馈。`ps1` 统一用 `powershell.exe`(5.1,Windows 必装),不依赖可选的 `pwsh.exe`(7+)。需要 pwsh 7 特性就写 `.bat` 包一层。

### 3.2 `exe` 类型的行为定义

- **启动后立即返回成功**(不等待进程退出)
- 适合 GUI 程序(MAA、QQ、浏览器等)
- 启动失败(文件不存在/权限拒绝/路径无效)才返回失败
- 不捕获 stdout/stderr(GUI 程序通常没有有意义的控制台输出)
- 需要复杂逻辑(等待、参数拼接、环境变量)就写 `.bat`/`.sh` 任务

## 4. 详细设计

### 4.1 存储格式

统一 JSON wrapper,文件路径 `tasks/scripts/{id}.json`:

```json
// 文本脚本(py/bat/ps1/sh)
{
  "type": "py",
  "name": "示例脚本",
  "description": "",
  "content": "print('hello')"
}

// 可执行文件(exe)
{
  "type": "exe",
  "name": "自动启动MAA",
  "description": "",
  "path": "D:\\APP\\MAA\\MAA.exe"
}
```

**字段变化**:
- 移除 `binary_path`(不再让用户选解释器)
- 新增 `type` 字段(必填,枚举 `py`/`bat`/`ps1`/`sh`/`exe`)
- `content` 字段:文本脚本必填,`exe` 类型禁用
- `path` 字段:仅 `exe` 类型必填,其他类型禁用

### 4.2 ScriptRunner 简化

**删除**:
- `_BINARY_EXT_MAP`(15+ 语言映射)
- `_get_interpreter_name`、`_get_temp_extension`
- `binary_path` 参数
- `detect_available_binaries` 调用和 allowlist 自动添加逻辑
- `detect_available_binaries = detect_binaries` 兼容别名
- `_build_cmd` 中的解释器名判断分支

**保留**:
- 临时文件机制(JSON `content` → 临时文件 → 执行 → 清理,避免命令行转义问题)
- `ShellCommandPolicy` 安全策略(allowlist 改为固定 5 类解释器路径)
- 超时、stdout/stderr 捕获(仅文本脚本)
- `_build_minimal_env` 最小环境变量

**新接口**:
```python
class ScriptRunner:
    def __init__(self, script_path: Path, script_type: str, timeout: int = 60):
        self.script_path = script_path
        self.script_type = script_type  # py/bat/ps1/sh/exe
        self.timeout = timeout

    def run(self) -> tuple[bool, str]:
        # 按 script_type 分发到 _run_text_script / _run_exe
        ...
```

**临时文件后缀**:固定映射,不再探测解释器:
```python
_TEMP_EXT = {"py": ".py", "bat": ".bat", "ps1": ".ps1", "sh": ".sh"}
```

**命令构建**(无平台判断,固定模板):
```python
def _build_cmd(self, script_file: str) -> list[str]:
    if self.script_type == "py":
        return [sys.executable, script_file]
    if self.script_type == "bat":
        return ["cmd.exe", "/c", script_file]
    if self.script_type == "ps1":
        return ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script_file]
    if self.script_type == "sh":
        return ["sh", script_file]
    raise ValueError(f"不支持的文本脚本类型: {self.script_type}")
```

**exe 分支**(极简,fire-and-forget):
```python
def _run_exe(self, path: str) -> tuple[bool, str]:
    try:
        subprocess.Popen([path], close_fds=True)
        return True, f"已启动: {path}"
    except FileNotFoundError:
        return False, f"文件不存在: {path}"
    except PermissionError as e:
        return False, f"权限不足: {e}"
    except Exception as e:
        return False, f"启动失败: {e}"
```

**ShellCommandPolicy allowlist**:改为固定列表(不再运行时探测):
```python
_ALLOWED_BINARIES = [
    sys.executable,           # py
    "cmd.exe",                # bat (Windows)
    "powershell.exe",         # ps1 (Windows)
    "sh",                     # sh (Unix)
]
```
`exe` 类型不经过 ShellCommandPolicy(直接 `Popen`)。

**`run()` 核心流程**:
```python
def run(self) -> tuple[bool, str]:
    if self.script_type == "exe":
        return self._run_exe(self._load_exe_path())

    # 文本脚本: content → 临时文件 → 执行 → 清理
    content = self._load_script_content()  # 从 JSON 读取
    temp_path = self._content_temp_file(content)
    try:
        cmd = self._build_cmd(script_file=temp_path)
        policy = ShellCommandPolicy(allowlist=_ALLOWED_BINARIES)
        returncode, stdout, stderr = policy.run_sync(cmd, timeout=self.timeout)
        return returncode == 0, (stdout or stderr)[:500]
    finally:
        os.unlink(temp_path)  # 清理临时文件
```
### 4.3 TaskExecutor 改动

**`_execute_script` 重构**:当前代码已使用 `task_manager.get_task_detail`(非 `registry.get_task`),但仍通过 `binary_path` 传参给 `ScriptRunner`。改为按 `task["type"]` 构造 `ScriptRunner`,类型检查逻辑从 `!= "script"` 变为 `not in ("py", "bat", "ps1", "sh", "exe")`。

**新 `_execute_script`**:
```python
def _execute_script(self, script_id: str, timeout: int, cancel_event=None):
    if self._task_manager is None:
        return False, "TaskManager 未注入"
    task = self._task_manager.get_task_detail(script_id)
    if not task or task.get("type") not in ("py", "bat", "ps1", "sh", "exe"):
        return False, f"脚本任务不存在: {script_id}"

    if cancel_event is not None and cancel_event.is_set():
        return False, "任务已被取消"

    from app.workers.script_runner import ScriptRunner
    runner = ScriptRunner(
        script_path=self._task_manager.get_script_path(script_id),
        script_type=task["type"],
        timeout=timeout,
    )
    return runner.run()
```

**删除**:
- `_execute_shell` 方法
- `execute_task` 中的 `elif task_type == "shell"` 分支
- `self._shell_policy` 实例属性(仅 `_execute_shell` 用)
- `ShellCommandPolicy` 和 `detect_shells`/`get_default_shell` 的导入

### 4.4 Schema 改动

**`ScheduledTaskConfig`** ([schemas.py:645](file:///e:/Campus-Auth/app/schemas.py#L645)):
- `type` 字段 pattern: `^(script|browser|shell)$` → `^(script|browser)$`
- 移除 `command` 字段
- 移除 `shell_path` 字段
- `validate_type_fields` 中 shell 校验删除

**`AppSettings`** ([schemas.py:370](file:///e:/Campus-Auth/app/schemas.py#L370)):
- 移除 `shell_path` 字段

**`ShellListResponse`**:整个模型删除(无消费者)

**`TaskSummary`** ([schemas.py:176](file:///e:/Campus-Auth/app/schemas.py#L176)):
- 移除 `binary_path` 字段

### 4.5 TaskManager 改动

**`ScriptTaskInfo`** ([models.py:230](file:///e:/Campus-Auth/app/tasks/models.py#L230)):
- 移除 `binary_path` 字段
- 新增 `script_type: str` 字段(取值 py/bat/ps1/sh/exe)

**`_save_script_task`** ([manager.py:407](file:///e:/Campus-Auth/app/tasks/manager.py#L407)):
- 移除 content 非空强制校验(exe 类型只有 path,没有 content)
- `"type": SCRIPT_TASK_TYPE` → `"type": config["type"]`(写入真实类型)
- 移除 `"binary_path"` 字段
- 新增:exe 类型校验 `path` 非空;文本脚本类型校验 `content` 非空

**`_save_script_task_validated`** ([manager.py:585](file:///e:/Campus-Auth/app/tasks/manager.py#L585)):
- 同上:移除 content 非空强制,按 type 分别校验 content/path
- 移除 `"binary_path"` 字段,新增 `"type"` 字段写入

**`load_task`**:直接读取新格式(`type` 字段必填),不再处理旧格式

**`list_script_tasks`**:返回字段包含 `type`(新),不再返回 `binary_path`

**`get_task_detail`**:返回字段包含 `type` 和 `content`/`path`(根据类型),不再返回 `binary_path`

**`.py` 文件处理移除**:
- `_safe_task_path`:搜索顺序移除 `.py` 后缀([manager.py:133,139](file:///e:/Campus-Auth/app/tasks/manager.py#L133))
- `_extract_script_metadata`:整个方法删除([manager.py:185](file:///e:/Campus-Auth/app/tasks/manager.py#L185))
- `list_script_tasks`:移除 `.py` 文件扫描分支([manager.py:297-311](file:///e:/Campus-Auth/app/tasks/manager.py#L297))
- `get_task_detail`:移除 `.py` 文件和 `.meta.json` 处理([manager.py:347-359](file:///e:/Campus-Auth/app/tasks/manager.py#L347))
- `delete_task`:移除 `.py` 和 `.meta.json` 删除([manager.py:443](file:///e:/Campus-Auth/app/tasks/manager.py#L443))
- `_task_type_from_id`:移除 `.py` 搜索([manager.py:471](file:///e:/Campus-Auth/app/tasks/manager.py#L471))
- `_read_meta` / `_safe_meta_path`:无其他消费者则删除

**`app/api/config.py`**:
- 移除 `"app_settings.shell_path": "Shell路径"` 配置 key 别名

**`app/api/scripts.py`**:
- 移除 `GET /api/scripts/binaries` 端点(`list_binaries` 函数)
- 移除 `detect_available_binaries` 导入(来自 `script_runner`)
- 移除 `BinaryInfo` 导入(来自 `schemas`)
- `get_script`([scripts.py:49](file:///e:/Campus-Auth/app/api/scripts.py#L49)):类型检查 `task.get("type") != "script"` → `task.get("type") not in ("py", "bat", "ps1", "sh", "exe")`
- `run_script`([scripts.py:92](file:///e:/Campus-Auth/app/api/scripts.py#L92)):同上
- `save_script`([scripts.py:61](file:///e:/Campus-Auth/app/api/scripts.py#L61)):移除 `data = {**payload, "type": "script"}` 硬编码,改为直接透传 payload(前端已发送正确的 `type` 字段)
- `save_script`:改用 `task["type"]` 构造 ScriptRunner,不再传 `binary_path`
- `shutdown_script_executor` 无变化(仅关闭线程池,与 binary 无关)

**`app/services/login_orchestrator.py`**:
- 移除 `d["shell_path"] = config.app_settings.shell_path` 透传([login_orchestrator.py:56](file:///e:/Campus-Auth/app/services/login_orchestrator.py#L56))

**`frontend/js/app-options.js`** ([app-options.js:71](file:///e:/Campus-Auth/frontend/js/app-options.js#L71)):
- `scheduledTaskTypeOptions` 无变化(已只有 script/browser)
- 移除 `shellCustomMode` 状态、`shellPathMode` / `shellPathOptions` 计算属性
- 移除 `binaryOptions` 计算属性([app-options.js:220](file:///e:/Campus-Auth/frontend/js/app-options.js#L220))
- 移除 `getBinaryName` 调用([app-options.js:100](file:///e:/Campus-Auth/frontend/js/app-options.js#L100))

**`frontend/js/data/scheduled_tasks.js`**:
- 移除 `shell_path` 默认值([scheduled_tasks.js:12](file:///e:/Campus-Auth/frontend/js/data/scheduled_tasks.js#L12))
- 移除 `command` 默认值(如存在)

**`frontend/js/methods/config.js`**:
- 移除 `fetchShells` 方法、`onShellFileSelected` 方法

**`frontend/js/methods/lifecycle.js`** ([lifecycle.js:29](file:///e:/Campus-Auth/frontend/js/methods/lifecycle.js#L29)):
- 移除 `this.fetchShells()` 初始化调用

**`frontend/js/data/config.js`**:
- 移除 `availableShells` / `defaultShell` 响应式状态

**`frontend/js/data/scripts.js`** ([scripts.js:5](file:///e:/Campus-Auth/frontend/js/data/scripts.js#L5)):
- 移除 `availableBinaries` 响应式状态

**`frontend/js/methods/scripts.js`**:
- 移除 binary 选择相关逻辑(`binary_path`、`_customBinary`、`_customPythonBinary`、`onBinarySelectChange`)
- 移除 `fetchAvailableBinaries` 方法([scripts.js:17](file:///e:/Campus-Auth/frontend/js/methods/scripts.js#L17))
- 移除 `availableBinaries` 引用([scripts.js:18,26,34](file:///e:/Campus-Auth/frontend/js/methods/scripts.js#L18))
- 移除 `getBinaryName` 导入和重导出([scripts.js:1,4](file:///e:/Campus-Auth/frontend/js/methods/scripts.js#L1))
- 移除 `_inferScriptExtension` 方法([scripts.js:268](file:///e:/Campus-Auth/frontend/js/methods/scripts.js#L268)),替换为基于 `type` 字段的简单映射
- `editingTask` 初始 shape 变更:
  ```js
  // 新建任务
  { id: '', name: '', description: '', type: 'py', content: '', _isNew: true }
  // 编辑任务(从 API 返回填充)
  { id, name, description, type, content/path, _isNew: false }
  ```
- 默认类型:新建任务 `type` 默认 `"py"`
- 类型切换:编辑器顶部 `<custom-select>` 绑定 `editingTask.type`,切换类型时:
  - `py/bat/ps1/sh` → 显示 content 编辑器,隐藏 path 输入框
  - `exe` → 显示 path 输入框(带文件选择器),隐藏 content 编辑器
  - 切换不清空已填内容(用户可能先写 content 再改 type)
- `loadScriptTemplate()` 按 `type` 加载对应模板(而非固定 Python 模板)
- `saveScript()` 提交字段:发送 `type`/`content`(文本脚本)或 `type`/`path`(exe),不再发送 `binary_path`

**`frontend/js/methods/utils.js`** ([utils.js:25](file:///e:/Campus-Auth/frontend/js/methods/utils.js#L25)):
- 移除 `getBinaryName` 函数

**`frontend/js/api-service.js`** ([api-service.js:64](file:///e:/Campus-Auth/frontend/js/api-service.js#L64)):
- 移除 `fetchShells` 方法

**`frontend/partials/pages/scripts.html`**:
- 移除 `binary-badge` 显示([scripts.html:55-56](file:///e:/Campus-Auth/frontend/partials/pages/scripts.html#L55)):替换为按 `type` 显示类型标签
- 移除执行程序选择器(`binary_path` dropdown + `binaryOptions` 绑定)([scripts.html:100-118](file:///e:/Campus-Auth/frontend/partials/pages/scripts.html#L100))
- `scriptTypeOptions` 定义:
  ```js
  [
    { value: 'py', label: 'Python (.py)' },
    { value: 'bat', label: '批处理 (.bat)' },
    { value: 'ps1', label: 'PowerShell (.ps1)' },
    { value: 'sh', label: 'Shell (.sh)' },
    { value: 'exe', label: '可执行文件 (.exe)' },
  ]
  ```
- `exe` 类型:显示 path 输入框(文件选择器),隐藏 content 编辑器
- 文本脚本类型:显示 content 编辑器,隐藏 path 输入框
- 帮助文本按 type 动态显示(py: "Python 脚本,使用项目内置解释器执行"; bat: "Windows 批处理"; ps1: "PowerShell 脚本"; sh: "Unix Shell 脚本"; exe: "启动可执行文件,不等待退出")
**`frontend/partials/pages/settings/settings-system.html`** ([settings-system.html:189-212](file:///e:/Campus-Auth/frontend/partials/pages/settings/settings-system.html#L189)):
- 移除整个 "Shell 路径" form-group(含 hint span,至 line 212)
- 移除 `shellFileInput` ref

**`frontend/styles/pages/settings.css`**:
- 移除 `.shell-custom-input` 相关样式([settings.css:736-744](file:///e:/Campus-Auth/frontend/styles/pages/settings.css#L736))

**`frontend/styles/pages/scripts.css`** ([scripts.css:28](file:///e:/Campus-Auth/frontend/styles/pages/scripts.css#L28)):
- 移除 `.binary-badge` 样式

## 5. 完整删除清单
### 后端文件删除
- `app/utils/shell_utils.py`(整个文件:3 个函数全部删除,无剩余逻辑)

### 后端代码删除
| 文件 | 删除内容 |
| `app/schemas.py` | `AppSettings.shell_path`、`ScheduledTaskConfig.command`、`ScheduledTaskConfig.shell_path`、`ShellListResponse`、`ShellInfo`、`BinaryInfo`、`TaskSummary.binary_path`、`validate_type_fields` 中 shell 分支 |
| `app/api/autostart.py` | `GET /api/shells` 端点、`detect_shells`/`get_default_shell` 导入 |
| `app/api/scripts.py` | `GET /api/scripts/binaries` 端点、`detect_available_binaries`/`BinaryInfo` 导入、`get_script`/`run_script` 类型检查修复、`save_script` 移除 `type` 硬编码 |
| `app/api/config.py` | `"app_settings.shell_path"` 配置 key 别名 |
| `app/services/login_orchestrator.py` | `d["shell_path"]` 透传 |
| `app/tasks/manager.py` | `_save_script_task`/`_save_script_task_validated` 重构(type 写入、content 校验)、`.py` 文件搜索/元数据提取/删除、`_extract_script_metadata`、`_read_meta`/`_safe_meta_path`、`SCRIPT_TASK_TYPE` 常量 |
| `app/tasks/models.py` | `ScriptTaskInfo.binary_path` |
| `app/workers/script_runner.py` | `_BINARY_EXT_MAP`、`_get_interpreter_name`、`_get_temp_extension`、`detect_available_binaries` 别名、`binary_path` 参数、解释器名判断分支、`.py` 文件直接执行路径 |

### 前端代码删除
| 文件 | 删除内容 |
|------|----------|
| `frontend/js/constants.js` | `app_settings.shell_path` 默认值 |
| `frontend/js/api-service.js` | `fetchShells` 方法 |
| `frontend/js/app-options.js` | `shellCustomMode` 状态、`shellPathMode`/`shellPathOptions` 计算属性、`binaryOptions` 计算属性、`getBinaryName` 调用 |
| `frontend/js/data/config.js` | `availableShells`/`defaultShell` 响应式状态 |
| `frontend/js/data/scripts.js` | `availableBinaries` 响应式状态 |
| `frontend/js/methods/config.js` | `fetchShells` 方法、`onShellFileSelected` 方法 |
| `frontend/js/methods/lifecycle.js` | `this.fetchShells()` 初始化调用 |
| `frontend/js/methods/scripts.js` | `fetchAvailableBinaries`、`availableBinaries` 引用、`getBinaryName` 导入/重导出、`_inferScriptExtension`、binary 选择逻辑 |
| `frontend/js/methods/utils.js` | `getBinaryName` 函数 |
| `frontend/js/data/scheduled_tasks.js` | `shell_path`、`command` 默认值 |
| `frontend/partials/pages/scripts.html` | `binary-badge` 显示、执行程序选择器(`binary_path` dropdown) |
| `frontend/partials/pages/settings/settings-system.html` | "Shell 路径" form-group(含 hint span)、`shellFileInput` ref |
| `frontend/styles/pages/settings.css` | `.shell-custom-input` 样式 |
| `frontend/styles/pages/scripts.css` | `.binary-badge` 样式 |

### 文档删除
| 文件 | 改动 |
|------|------|
| `docs/guides/custom-script-guide.md` | 重写"执行程序选择"章节为"脚本类型选择",移除 binary_path 示例 |
| `docs/dev/api-reference.md` | 移除 `GET /api/shells`、`GET /api/scripts/binaries` 条目 |

## 6. 测试策略

### 6.1 测试改动

| 测试文件 | 改动 |
|----------|------|
| `tests/test_utils/test_shell_utils.py` | 删除文件(`shell_utils.py` 整体删除) |
| `tests/test_utils/test_shell_policy.py` | 保留(`ShellCommandPolicy` 仍被 ScriptRunner 使用) |
| `tests/test_api/test_api_autostart_routes.py` | 移除 `TestListShells` 类 |
| `tests/test_api/test_api_system_routes.py` | 移除 `TestShells` 类 |
| `tests/test_api/test_api_scripts_routes.py` | 适配新 `type` 字段,移除 `binary_path`;移除 `list_binaries` 端点测试;修复 `type: "script"` → 新类型 |
| `tests/test_app/test_backend_services.py` | 移除 `test_save_script_with_binary_path`、适配 `binary_path` → `type`([line 1014](file:///e:/Campus-Auth/tests/test_app/test_backend_services.py#L1014)) |
| `tests/test_services/test_scheduled_tasks.py` | 移除 `TestExecuteShellUsesPolicy` 类([line 149](file:///e:/Campus-Auth/tests/test_services/test_scheduled_tasks.py#L149)) |
| `tests/test_services/test_scheduler_service.py` | 移除 `detect_shells` 导入、`TestExecuteShellUsesPolicy` 类([line 48](file:///e:/Campus-Auth/tests/test_services/test_scheduler_service.py#L48)) |
| `tests/test_workers/test_script_runner.py` | 适配新 `script_type` 参数(替换所有 `binary_path=`),移除 `.py` 文件直接执行测试 |

### 6.2 新增测试

- **ScriptRunner 类型分发**:5 种 type 各一个用例,验证命令构建正确
- **exe fire-and-forget**:`Popen` 不等待,启动失败返回 False
- **_execute_script 类型分发回归**:验证 `task_manager.get_task_detail` + 新 `type` 字段正确分发(而非旧 `binary_path`)

### 6.3 验证命令

```bash
uv run pytest tests/test_integration tests/test_workers tests/test_api tests/test_app tests/test_services tests/test_utils -v
uv run ruff check .
uv run ruff format .
```

## 7. 风险与回滚

### 7.1 风险

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| `ps1` 用户依赖 pwsh 7 特性 | 低 | 用 powershell 5.1 执行可能失败 | 文档说明:需要 pwsh 7 就写 `.bat` 包一层 |
| Windows 用户想跑 `.sh` 但没装 sh | 中 | 收到 FileNotFoundError | 错误信息清晰,用户改用 `.bat`/`.ps1` |

### 7.2 回滚

本次重构涉及文件多但逻辑独立,回滚策略:
- 代码回滚:`git revert` 重构 commit
- 旧格式脚本任务文件(`tasks/scripts/*.json`)仍为 JSON,回滚后旧代码可直接读取

## 8. 实施顺序建议

1. **后端核心**:`ScriptRunner` 简化 + `ScriptTaskInfo`/`TaskManager` 适配新 `type` 字段 + `_execute_script` 重构(移除 `binary_path` 传参)
2. **Schema 收紧**:移除 shell 类型、`command`/`shell_path` 字段、`BinaryInfo`
3. **删除死代码**:`_execute_shell`、`/api/shells`、`/api/scripts/binaries`、`detect_shells`、设置页 Shell 配置、`shell_utils.py` 整文件
4. **前端适配**:type 选择器、exe path 输入、移除 binary 选择器
5. **测试更新**:移除 shell 测试,新增 type 分发测试
6. **文档更新**:custom-script-guide.md、api-reference.md
7. **修改日志**:`.claude/change.md` 同步记录
