# 重构计划：目录统一 + 嵌入式 Python 移除 + 代码优化

## 目标

1. 将 `backend/` 和 `src/` 合并到统一的 `app/` 包下，建立清晰的分层架构
2. 全平台统一使用 `uv`，移除嵌入式 Python 和 PyInstaller 打包方案
3. 在搬迁过程中同步完成 11 项代码质量优化

## 新目录结构

```
main.py                    # 入口文件（原 app.py）
launcher.py                # uv 启动器（重写）
setup_env.sh               # 安装脚本（简化）

app/
├── __init__.py            # 包定义（版本号由 version.py 管理）
├── application.py         # FastAPI app、lifespan（原 backend/main.py，避免与 main.py 混淆）
├── container.py           # ServiceContainer
├── deps.py                # FastAPI 依赖注入
├── constants.py           # 常量定义
├── schemas.py             # Pydantic 模型
├── ws_manager.py          # WebSocket 管理
├── version.py             # 版本号
│
├── api/                   # 路由层（13 个文件）
│   ├── __init__.py
│   ├── monitor.py
│   ├── config.py
│   ├── tasks.py
│   ├── profiles.py
│   ├── debug.py
│   ├── backup.py
│   ├── repo.py
│   ├── system.py
│   ├── tools.py
│   ├── scripts.py
│   ├── scheduled_tasks.py
│   ├── history.py
│   └── logfiles.py
│
├── services/              # 业务服务层
│   ├── __init__.py
│   ├── monitor.py         # MonitorService（含 _enqueue_cmd 简化）
│   ├── config.py          # config_service（含解密逻辑统一）
│   ├── profile.py         # ProfileService
│   ├── task.py            # TaskService
│   ├── scheduler.py       # SchedulerService（含惰性锁修复）
│   ├── login_history.py   # LoginHistoryService
│   ├── autostart.py       # AutoStartService（移除嵌入式 Python）
│   ├── uninstall.py       # UninstallService
│   └── debug.py           # DebugSessionManager + DebugSession
│
├── tasks/                 # 任务执行引擎（从 task_executor.py 拆分）
│   ├── __init__.py        # 重新导出所有公开接口
│   ├── models.py          # StepConfig、TaskConfig、StepType、TaskError、StepError
│   ├── step_handlers.py   # 10 个步骤处理器 + StepExecutorRegistry
│   ├── variable_resolver.py # VariableResolver
│   ├── validator.py       # TaskValidator
│   ├── executor.py        # TaskExecutor
│   └── manager.py         # TaskManager + normalize_task_id + is_valid_task_id
│
├── network/               # 网络检测
│   ├── __init__.py
│   ├── probes.py          # TCP/HTTP/Portal 探针（合并线程池）
│   ├── decision.py        # 检测决策层
│   ├── detect.py          # 检测工具（gateway/wifi）
│   └── diagnostics.py     # 网络诊断脚本（原 network_test.py，避免与 tests/ 和 services/debug.py 混淆）
│
├── workers/               # 浏览器自动化
│   ├── __init__.py
│   ├── playwright_worker.py  # （含浏览器启动参数提取）
│   ├── playwright_bootstrap.py
│   └── script_runner.py   # （移除 frozen 检测）
│
├── core/                  # 核心业务逻辑
│   ├── __init__.py
│   ├── monitor_core.py    # 网络监控循环（含登录路径统一）
│   └── system_tray.py     # 系统托盘
│
└── utils/                 # 工具层
    ├── __init__.py
    ├── browser.py         # （与 workers 去重后简化）
    ├── config.py
    ├── config_helpers.py
    ├── crypto.py
    ├── env.py
    ├── exceptions.py
    ├── file_helpers.py
    ├── logging.py         # （移除 setup_logger 别名）
    ├── login.py
    ├── network_helpers.py
    ├── notify.py
    ├── platform_utils.py
    ├── process.py         # 新增：从 main.py 提取的 PID 管理 + 进程检测
    ├── repo_proxy.py
    ├── shell_policy.py
    └── time_utils.py
```

---

## 前置条件

- `app.py` **必须在创建 `app/` 目录之前**重命名为 `main.py`（否则 Python 会优先导入 `app/` 包，导致 `python app.py` 失败）
- `backend/main.py` 改名为 `app/application.py`（避免与 `main.py` 混淆）
- 启动命令：`uv run main.py`
- 测试文件先搬后修（统一修复导入路径）

> **`main` 模块名风险提示：** `main` 是较通用的模块名，但本项目仅本地运行且不作为库发布，不会与标准库冲突。
> 测试中 `from main import xxx` 依赖 `pythonpath = ["."]` 配置（已在 `pyproject.toml` 中声明），确保测试运行时项目根目录在 `sys.path` 中。

---

## 命名冲突处理

| 冲突 | 解决方案 |
|------|----------|
| `app.py`（入口）与 `app/`（包）同名 | 入口重命名为 `main.py` |
| `backend/main.py`（FastAPI）与 `main.py`（入口）混淆 | FastAPI 模块改名为 `app/application.py` |
| `app/network/test.py` 与 `tests/` 目录混淆 | 改名为 `app/network/diagnostics.py` |

**测试中的引用变更：**
- `from app import xxx` → `from main import xxx`
- `patch("app.xxx")` → `patch("main.xxx")`
- `monkeypatch.setattr("app.AUTH_DATA_DIR", ...)` → `monkeypatch.setattr("main.AUTH_DATA_DIR", ...)`

---

## 反向依赖处理

| 源文件 | 导入 | 处理方式 |
|--------|------|----------|
| `src/utils/crypto.py` | `from backend.constants import AUTH_DATA_DIR` | 搬迁后变为 `from app.constants import AUTH_DATA_DIR` |
| `src/monitor_core.py` | `from backend.constants import DEFAULT_NETWORK_TARGETS` | 搬迁后变为 `from app.constants import DEFAULT_NETWORK_TARGETS` |

统一到 `app/` 包后自然解决。

---

## 移除嵌入式 Python，全面使用 uv

### 变更范围

| 文件 | 变更 |
|------|------|
| `launcher.py`（921 行） | **重写**为 ~130 行 uv 启动脚本（含自动下载 + 镜像回退） |
| `setup_env.sh`（605 行） | **简化**为 ~30 行（复用 launcher.py 的 uv 下载逻辑） |
| `main.py`（原 app.py） | **删除** `_is_packaged()`、`_setup_packaged_env()`、嵌入式 sys.path 补丁 |
| `app/services/autostart.py` | **删除** `environment/python/python.exe` 回退，启动命令改为 `uv run main.py` |
| `app/workers/script_runner.py` | **删除** `getattr(sys, 'frozen', False)` 分支 |
| `pyproject.toml` | **删除** `build = ["pyinstaller"]` |
| `Campus-Auth-Setup.spec` | **删除**文件 |
| `tests/test_app.py` | **删除** `TestIsPackaged` 类、`_setup_packaged_env` 相关测试和 mock |
| `README.md` | 更新安装和启动说明 |

### 新 launcher.py 完整代码（~130 行）

```python
#!/usr/bin/env python3
"""Campus-Auth 启动器 — 自动下载 uv、安装依赖、启动应用。"""
import platform
import shutil
import subprocess
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
UV_DIR = PROJECT_ROOT / ".uv"  # 本地 uv 存放目录（加入 .gitignore）


# ── uv 下载 ──────────────────────────────────────────────


def _uv_filename() -> str:
    """根据平台返回 uv 二进制文件名。"""
    system = platform.system()
    machine = platform.machine().lower()
    if system == "Windows":
        return "uv-x86_64-pc-windows-msvc.zip"
    elif system == "Darwin":
        arch = "aarch64" if machine == "arm64" else "x86_64"
        return f"uv-{arch}-apple-darwin.tar.gz"
    else:
        arch = "aarch64" if machine in ("aarch64", "arm64") else "x86_64"
        return f"uv-{arch}-unknown-linux-gnu.tar.gz"


# uv 版本锁定——避免 latest 导致不同时间下载不同版本，行为不可预测
# 注意：这是 uv 工具自身的版本（下载二进制），与 pyproject.toml 中的 uv Python 包版本无关
_UV_VERSION = "0.7.3"  # 定期手动升级


def _uv_download_urls() -> list[str]:
    """返回下载地址列表，优先国内镜像，回退 GitHub。"""
    filename = _uv_filename()
    return [
        f"https://npmmirror.com/mirrors/uv/{_UV_VERSION}/{filename}",
        f"https://github.com/astral-sh/uv/releases/download/{_UV_VERSION}/{filename}",
    ]


def _download_uv() -> str:
    """下载 uv 到本地目录，返回可执行文件路径。"""
    UV_DIR.mkdir(exist_ok=True)
    is_zip = platform.system() == "Windows"
    archive = UV_DIR / ("uv.zip" if is_zip else "uv.tar.gz")

    for url in _uv_download_urls():
        try:
            print(f"正在下载 uv ... ({url.split('/')[2]})")
            urllib.request.urlretrieve(url, archive)
            break
        except Exception as e:
            print(f"  下载失败: {e}")
            continue
    else:
        print("错误：所有下载源均失败，请手动安装 uv：https://docs.astral.sh/uv/")
        sys.exit(1)

    if is_zip:
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(UV_DIR)
    else:
        with tarfile.open(archive) as tf:
            tf.extractall(UV_DIR, filter="data")
    archive.unlink()

    uv_exe = UV_DIR / ("uv.exe" if platform.system() == "Windows" else "uv")
    if platform.system() != "Windows":
        uv_exe.chmod(0o755)
    return str(uv_exe)


def _ensure_uv() -> str:
    """确保 uv 可用：PATH 中有就直接用，没有就下载到本地。"""
    found = shutil.which("uv")
    if found:
        return found
    local = UV_DIR / ("uv.exe" if platform.system() == "Windows" else "uv")
    if local.exists():
        return str(local)
    return _download_uv()


# ── 主流程 ───────────────────────────────────────────────


def main():
    uv = _ensure_uv()

    # 1. uv sync（安装依赖）
    try:
        subprocess.run([uv, "sync"], cwd=PROJECT_ROOT, check=True)
    except subprocess.CalledProcessError as e:
        print(f"错误：依赖安装失败（退出码 {e.returncode}）。")
        print("请尝试手动运行: uv sync")
        print("如 uv.lock 损坏，可运行: uv lock --upgrade")
        sys.exit(1)

    # 2. 确保 Playwright Chromium 已安装
    try:
        subprocess.run([uv, "run", "playwright", "install", "chromium"],
                       cwd=PROJECT_ROOT, check=True)
    except subprocess.CalledProcessError as e:
        print(f"警告：Playwright Chromium 安装失败（退出码 {e.returncode}）。")
        print("如已安装可忽略，否则手动运行: uv run playwright install chromium")

    # 3. 启动应用
    subprocess.run([uv, "run", "main.py"] + sys.argv[1:], cwd=PROJECT_ROOT)


if __name__ == "__main__":
    main()
```

**配套变更：** `.gitignore` 添加 `.uv/` 目录。

### 新 setup_env.sh 完整代码（~30 行）

```bash
#!/usr/bin/env bash
# Campus-Auth 环境安装脚本（macOS / Linux）
# 复用 launcher.py 的 uv 下载逻辑，不重复实现
set -euo pipefail
PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"

# 如果系统没有 uv 且没有 Python 3，提示手动安装
if ! command -v uv &>/dev/null; then
    if command -v python3 &>/dev/null; then
        python3 "$PROJECT_ROOT/launcher.py"
        exit $?
    else
        echo "错误：未找到 uv 和 python3。请先安装其中之一："
        echo "  uv:     https://docs.astral.sh/uv/getting-started/installation/"
        echo "  python: https://www.python.org/downloads/"
        exit 1
    fi
fi

# 系统已有 uv，直接用
cd "$PROJECT_ROOT"
uv sync
uv run playwright install chromium
echo "环境准备完成。启动：uv run main.py"
```

### main.py（原 app.py）中删除的代码

```python
# ── 删除：嵌入式 Python sys.path 补丁（行 16-19）──
# 理由：uv 环境下 sys.path 已由 uv 管理，不需要手动插入
_project_root = Path(__file__).resolve().parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

# ── 删除：打包环境段落（行 154-167）──
# 理由：不再支持 PyInstaller 打包
def _is_packaged() -> bool:
    return bool(getattr(sys, "frozen", False) or globals().get("__compiled__"))

def _setup_packaged_env() -> None:
    if not _is_packaged():
        return
    exe_path = Path(sys.argv[0]).resolve()
    project_root = exe_path.parent
    os.environ.setdefault("CAMPUS_AUTH_START_EXECUTABLE", str(exe_path))
    os.environ.setdefault("CAMPUS_AUTH_PROJECT_ROOT", str(project_root))

# ── 删除：main() 中的调用（行 545）──
_setup_packaged_env()  # 删除此行
```

### autostart_service.py 中删除的代码

```python
# ── 删除：嵌入式 Python 回退逻辑（约行 48-52）──
# 理由：不再使用嵌入式 Python，统一用 uv
if is_windows():
    python_exe = self.project_root / "environment" / "python" / "python.exe"
    if python_exe.exists():
        return f'"{python_exe}" "{app_entry}"'

# ── 新增：uv 路径探测方法 ──
def _find_uv(self) -> str:
    """查找 uv 可执行文件路径：系统 PATH → 本地 .uv/ → 回退 'uv'。"""
    import shutil
    found = shutil.which("uv")
    if found:
        return found
    local = self.project_root / ".uv" / ("uv.exe" if is_windows() else "uv")
    if local.exists():
        return str(local)
    return "uv"  # 回退，依赖 PATH

# ── 修改：启动命令 ──
# 旧：f'"{python_exe}" "{app_entry}"'
# 新：f'{self._find_uv()} run main.py'
```

### script_runner.py 中删除的代码

```python
# ── 删除：frozen 检测分支（行 36-41）──
# 理由：不再支持 PyInstaller 打包，sys.frozen 永远为 False
def get_default_binary() -> str:
    """获取默认执行二进制（当前运行的 Python）。"""
    if getattr(sys, 'frozen', False):       # 删除这 3 行
        import shutil                       # 删除
        return shutil.which("python") or shutil.which("python3") or ""  # 删除
    return sys.executable
```

### test_app.py 中删除的测试

```python
# ── 删除整个类（行 742-757）──
class TestIsPackaged:
    """_is_packaged — sys.frozen / 未打包。"""
    def test_frozen(self):
        from app import _is_packaged
        with patch.object(sys, "frozen", True, create=True):
            assert _is_packaged() is True
    def test_not_packaged(self):
        from app import _is_packaged
        result = _is_packaged()
        assert result is False

# ── 删除所有 _setup_packaged_env mock（行 832, 845）──
patch("app._setup_packaged_env"),  # 删除

# ── 重命名所有 app 引用（约 60 处）──
# from app import xxx          → from main import xxx
# from app import main         → from main import main
# patch("app._xxx")            → patch("main._xxx")
# patch("app.xxx")             → patch("main.xxx")
# patch("app.atexit.register") → patch("main.atexit.register")
# patch("app.signal.signal")   → patch("main.signal.signal")
# patch("app.os._exit")        → patch("main.os._exit")
# patch("app.webbrowser.open") → patch("main.webbrowser.open")
```

---

## 代码优化项（搬迁过程中同步完成）

### 优化 1：拆分 task_executor.py（阶段 7）

2000 行拆为 6 个文件，详见阶段 7。

### 优化 2：MonitorService 简化

**文件：** `app/services/monitor.py`（原 `backend/monitor_service.py`）

**变更：**
- 提取 `_enqueue_cmd()` 辅助方法，消除 4 处重复的 `except queue.Full` 处理
- 将 `_handle_login` 中的历史记录逻辑提取为 `_record_login_result()` 方法
- 删除 `_copy_runtime_config()` 薄包装，**直接在原调用处用 `copy.deepcopy(self._runtime_config)`**（必须保留深拷贝，防止 `browser_settings.pure_mode` 跨调用污染）

### 优化 3：config_service 解密逻辑统一

**文件：** `app/services/config.py`（原 `backend/config_service.py`）

**变更：**
- 将 5 次重复的 `_safe_decrypt` + `any_error` 模式提取为 `_decrypt_password_field()` 函数
- `save_config_combined` 中用 Pydantic `model_dump()` 替代逐字段手动赋值

### 优化 4：浏览器启动逻辑去重

**文件：** `app/workers/playwright_worker.py` + `app/utils/browser.py`

**变更：**
- 提取 `build_browser_launch_args(config)` 和 `build_context_options(config)` 两个函数
- `PlaywrightWorker._start_browser` 和 `BrowserContextManager.__aenter__` 都调用这两个函数
- `STEALTH_INIT_SCRIPT` 移到 `app/workers/playwright_worker.py`（使用者）

### 优化 5：PID 管理提取

**文件：** `main.py` → `app/utils/process.py`

**变更：**
- 提取 `_get_pid_file`、`_read_pid_file`、`_write_pid`、`_cleanup_pid`、`_get_process_name`、`_normalize_proc_name`、`_is_service_running`、`_is_local_port_in_use` 到 `app/utils/process.py`
- `main.py` 只保留 CLI 解析和调度，从 `app.utils.process` 导入
- 测试从 `from main import xxx` 改为 `from app.utils.process import xxx`

**`app/utils/process.py` 导出接口：**
```python
__all__ = [
    "get_pid_file",        # () -> Path
    "read_pid_file",       # () -> int | None
    "write_pid",           # (pid: int) -> None
    "cleanup_pid",         # () -> None
    "get_process_name",    # (pid: int) -> str
    "normalize_proc_name", # (name: str) -> str
    "is_service_running",  # () -> bool
    "is_local_port_in_use",# (port: int) -> bool
]
```

**消费者：** `main.py`（PID 管理）+ `app/workers/playwright_worker.py`（进程清理，优化 11）

### 优化 6：登录路径统一

**文件：** `app/core/monitor_core.py` + `app/services/monitor.py`

**变更：**
- `NetworkMonitorCore.attempt_login` 和 `MonitorService._handle_login` 都调用同一个 `_do_login()` 方法
- 统一历史记录逻辑（都通过 `login_history_service.add()`）
- 统一取消事件传递

### 优化 7：schemas.py Mixin 简化

**文件：** `app/schemas.py`（原 `backend/schemas.py`）

**变更：**
- `_SharedValidatorsMixin` 和 `_BrowserValidatorsMixin` 各只有 1 个方法，直接放到需要的模型上
- 合并 `_ClampMixin` 到基类，或用 Pydantic `Field(ge=..., le=...)` 替代
- `_BROWSER_ARGS_DEFAULT` 与 `playwright_worker.py` 的默认参数对齐

### 优化 8：移除 setup_logger 别名

**文件：** `app/utils/logging.py` + 所有引用文件

**变更：**
- 删除 `setup_logger = get_logger` 别名
- 全局替换 `setup_logger` → `get_logger`（约 5 个文件）

### 优化 9：合并网络探针线程池

**文件：** `app/network/probes.py` + `app/network/decision.py`

**变更：**
- 删除 `decision.py` 中的 `ThreadPoolExecutor(max_workers=3)`
- `probes.py` 导出共享线程池，`decision.py` 直接使用

### 优化 10：scheduler_service 惰性锁修复

**文件：** `app/services/scheduler.py`（原 `backend/scheduler_service.py`）

**变更：**
- 删除 `if not hasattr(self, "_history_lock")` 反模式
- 在 `start()` 方法中初始化 `self._history_lock = asyncio.Lock()`

### 优化 11：进程清理统一

**文件：** `app/workers/playwright_worker.py` + `app/utils/process.py`

**变更：**
- `_cleanup_windows` 和 `_cleanup_posix` 中的进程检测逻辑复用 `app.utils.process` 中的函数
- 统一 PowerShell 调用方式

---

## 实施阶段

### 阶段 1：入口重命名 + 创建目录结构

> ⚠️ **必须先重命名 `app.py`，再创建 `app/` 目录。** 否则 Python 会将 `app` 解析为包而非模块，导致入口文件无法运行。

**步骤 1：重命名入口文件**
```bash
git mv app.py main.py
```

**步骤 2：更新 `main.py` 内部导入（先用旧路径，后续阶段逐步替换）**
```python
# 暂时保留旧导入，待各模块搬迁完成后在对应阶段替换
# 例如：from backend.constants import AUTH_DATA_DIR  → 阶段 8 时改为 from app.constants import ...
```

**步骤 3：创建目录结构**
```bash
mkdir -p app/{api,services,tasks,network,workers,core,utils}
# 为每个目录创建 __init__.py
```

**步骤 4：同步重命名测试文件**
```bash
git mv tests/test_app.py tests/test_main.py
# test_main.py 内部的 from app import xxx / patch("app.xxx") 在阶段 13 统一修复
```

创建 `app/__init__.py`：
```python
"""Campus-Auth 校园网自动认证工具。"""
# 版本号统一由 app/version.py 管理，不在 __init__.py 中重复定义
```

> **版本号唯一来源：** `app/version.py`（从 `pyproject.toml` 读取）。`app/__init__.py` 不定义 `__version__`，避免双写不一致。

### 阶段 2：移除嵌入式 Python

1. 重写 `launcher.py`（921 行 → ~130 行，含 uv 自动下载 + 镜像回退）
2. 简化 `setup_env.sh`（605 行 → ~30 行，复用 launcher.py）
3. 删除 `Campus-Auth-Setup.spec`
4. 从 `pyproject.toml` 删除 `build = ["pyinstaller"]`
5. 从 `script_runner.py` 删除 `frozen` 检测分支
6. `.gitignore` 添加 `.uv/`

### 阶段 3：搬迁 utils/（基础层）

**移动文件：** `src/utils/*.py` → `app/utils/*.py`（16 个文件）

**额外操作：**
- 新增 `app/utils/process.py`（从 `main.py` 提取 PID 管理 + 进程检测，约 120 行）
- `app/utils/logging.py` 中删除 `setup_logger` 别名，全局替换为 `get_logger`

**导入变更：**
| 文件 | 旧导入 | 新导入 |
|------|--------|--------|
| `app/utils/crypto.py` | `from backend.constants import AUTH_DATA_DIR` | `from app.constants import AUTH_DATA_DIR` |
| `app/utils/crypto.py` | `from src.utils.file_helpers import ...` | `from .file_helpers import ...` |
| `app/utils/crypto.py` | `from src.utils.logging import ...` | `from .logging import ...` |
| `app/utils/crypto.py` | `from src.utils.exceptions import ...` | `from .exceptions import ...` |
| `app/utils/crypto.py` | `from src.utils.platform_utils import ...` | `from .platform_utils import ...` |
| `app/utils/env.py` | `from src.utils.logging import ...` | `from .logging import ...` |
| `app/utils/file_helpers.py` | `from src.utils.logging import ...` | `from .logging import ...` |
| `app/utils/notify.py` | `from src.utils.platform_utils import ...` | `from .platform_utils import ...` |
| `app/utils/notify.py` | `from src.utils.logging import ...` | `from .logging import ...` |
| `app/utils/repo_proxy.py` | `from src.utils.logging import ...` | `from .logging import ...` |
| `app/utils/shell_policy.py` | `from src.utils.logging import ...` | `from .logging import ...` |

**全局替换（优化 8）：**
- 所有文件中 `setup_logger` → `get_logger`

### 阶段 4：搬迁 network/

**移动文件：**
| 源 | 目标 |
|----|------|
| `src/network_probes.py` | `app/network/probes.py` |
| `src/network_decision.py` | `app/network/decision.py` |
| `src/network_detect.py` | `app/network/detect.py` |
| `src/network_test.py` | `app/network/diagnostics.py`（改名，避免与 tests/ 和 services/debug.py 混淆） |

**导入变更：**
| 文件 | 旧导入 | 新导入 |
|------|--------|--------|
| `app/network/probes.py` | `from src.utils.logging import ...` | `from app.utils.logging import ...` |
| `app/network/probes.py` | `from src.utils.platform_utils import ...` | `from app.utils.platform_utils import ...` |
| `app/network/decision.py` | `from src.network_probes import ...` | `from .probes import ...` |
| `app/network/decision.py` | `from src.utils.logging import ...` | `from app.utils.logging import ...` |
| `app/network/decision.py` | `from src.utils.time_utils import ...` | `from app.utils.time_utils import ...` |
| `app/network/detect.py` | `from src.utils.logging import ...` | `from app.utils.logging import ...` |
| `app/network/detect.py` | `from src.utils.platform_utils import ...` | `from app.utils.platform_utils import ...` |
| `app/network/diagnostics.py` | `from src.network_probes import ...` | `from .probes import ...` |
| `app/network/diagnostics.py` | `from src.network_decision import ...` | `from .decision import ...` |

**优化 9（合并线程池）：**
- 删除 `app/network/decision.py` 中的 `ThreadPoolExecutor`
- `app/network/probes.py` 导出共享线程池实例

### 阶段 5：搬迁 workers/

**移动文件：**
| 源 | 目标 |
|----|------|
| `src/playwright_worker.py` | `app/workers/playwright_worker.py` |
| `src/playwright_bootstrap.py` | `app/workers/playwright_bootstrap.py` |
| `src/script_runner.py` | `app/workers/script_runner.py` |

**导入变更：**
| 文件 | 旧导入 | 新导入 |
|------|--------|--------|
| `app/workers/playwright_bootstrap.py` | `from src.utils.platform_utils import ...` | `from app.utils.platform_utils import ...` |
| `app/workers/script_runner.py` | `from src.utils.logging import ...` | `from app.utils.logging import ...` |
| `app/workers/script_runner.py` | `from src.utils.shell_policy import ...` | `from app.utils.shell_policy import ...` |
| `app/workers/playwright_worker.py` | `from src.utils.logging import ...` | `from app.utils.logging import ...` |
| `app/workers/playwright_worker.py` | `from src.utils.platform_utils import ...` | `from app.utils.platform_utils import ...` |

**优化 4（浏览器启动去重）：**
- 提取 `build_browser_launch_args()` 和 `build_context_options()` 到 `app/workers/playwright_worker.py`
- `STEALTH_INIT_SCRIPT` 从 `app/utils/browser.py` 移到 `app/workers/playwright_worker.py`

**优化 11（进程清理统一）：**
- `_cleanup_windows` 和 `_cleanup_posix` 复用 `app.utils.process` 中的进程检测函数

### 阶段 6：搬迁 core/

**移动文件：**
| 源 | 目标 |
|----|------|
| `src/monitor_core.py` | `app/core/monitor_core.py` |
| `src/system_tray.py` | `app/core/system_tray.py` |

**导入变更：**
| 文件 | 旧导入 | 新导入 |
|------|--------|--------|
| `app/core/monitor_core.py` | `from backend.constants import ...` | `from app.constants import ...` |
| `app/core/monitor_core.py` | `from src.network_decision import ...` | `from app.network.decision import ...` |
| `app/core/monitor_core.py` | `from src.network_probes import ...` | `from app.network.probes import ...` |
| `app/core/monitor_core.py` | `from src.utils import ...` | `from app.utils import ...` |
| `app/core/monitor_core.py` | `from src.utils.network_helpers import ...` | `from app.utils.network_helpers import ...` |
| `app/core/monitor_core.py` | `from src.utils.notify import ...` | `from app.utils.notify import ...` |
| `app/core/monitor_core.py` (TYPE_CHECKING) | `from backend.profile_service import ...` | `from app.services.profile import ...` |

### 阶段 7：拆分 task_executor.py → app/tasks/（优化 1）

`src/task_executor.py` (~2000 行) 拆为 6 个文件。

**内部依赖关系：**
```
models.py          ← 无依赖（纯数据结构）
variable_resolver.py ← models.py（导入常量）
step_handlers.py   ← models.py, variable_resolver.py
validator.py       ← models.py
executor.py        ← models.py, step_handlers.py, variable_resolver.py, validator.py
manager.py         ← models.py（文件 CRUD）
```

**拆分方案：**

#### `app/tasks/models.py`（~200 行）
- `StepType` 枚举
- `StepConfig` 数据类（含 `_DEFAULTS`、`from_dict`、`to_dict`）
- `TaskConfig` 数据类（含 `from_dict`、`to_dict`）
- `TaskError`、`StepError` 异常类
- `ScriptTaskInfo` 数据类
- 常量：`DEFAULT_STEP_TIMEOUT`、`DEFAULT_TASK_TIMEOUT` 等

#### `app/tasks/variable_resolver.py`（~100 行）
- `VariableResolver` 类
- `resolve_variable` 函数

#### `app/tasks/step_handlers.py`（~500 行）
- `StepHandler` 基类
- 10 个步骤处理器子类
- `StepExecutorRegistry`

#### `app/tasks/validator.py`（~100 行）
- `TaskValidator` 类

#### `app/tasks/executor.py`（~300 行）
- `TaskExecutor` 类

#### `app/tasks/manager.py`（~400 行）
- `TaskManager` 类
- `normalize_task_id` 函数
- `is_valid_task_id` 函数

#### `app/tasks/__init__.py`
重新导出所有公开接口（必须与原 `src/task_executor.py` 完全一致）：
```python
from .models import StepConfig, TaskConfig, TaskError, StepError, StepType, ScriptTaskInfo
from .step_handlers import StepHandler, InputHandler, ClickHandler, SelectHandler, ...
from .variable_resolver import VariableResolver
from .validator import TaskValidator
from .executor import TaskExecutor
from .manager import TaskManager, normalize_task_id, is_valid_task_id
```

### 阶段 8：搬迁 constants + schemas + version

**移动文件：**
| 源 | 目标 |
|----|------|
| `backend/constants.py` | `app/constants.py` |
| `backend/schemas.py` | `app/schemas.py` |
| `src/version.py` | `app/version.py` |

**导入变更：**
| 文件 | 旧导入 | 新导入 |
|------|--------|--------|
| `app/schemas.py` | `from src.utils.platform_utils import ...` | `from app.utils.platform_utils import ...` |

**优化 7（schemas Mixin 简化）在此阶段同步完成。**

### 阶段 9：搬迁 services/

**移动文件：**
| 源 | 目标 |
|----|------|
| `backend/monitor_service.py` | `app/services/monitor.py` |
| `backend/config_service.py` | `app/services/config.py` |
| `backend/profile_service.py` | `app/services/profile.py` |
| `backend/task_service.py` | `app/services/task.py` |
| `backend/scheduler_service.py` | `app/services/scheduler.py` |
| `backend/login_history_service.py` | `app/services/login_history.py` |
| `backend/autostart_service.py` | `app/services/autostart.py` |
| `backend/uninstall_service.py` | `app/services/uninstall.py` |
| `backend/debug_manager.py` | `app/services/debug.py` |
| `backend/debug_session.py` | `app/services/debug_session.py` |

**每个 service 的导入变更模式：**
```python
from src.xxx import ...        → from app.xxx import ...
from src.utils.xxx import ...  → from app.utils.xxx import ...
from .constants import ...      → from app.constants import ...
from .schemas import ...        → from app.schemas import ...
from .profile_service import ...→ from .profile import ...
```

**具体变更：**

#### `app/services/monitor.py`
```python
from src.monitor_core import ...           → from app.core.monitor_core import ...
from src.playwright_worker import ...      → from app.workers.playwright_worker import ...
from src.network_decision import ...       → from app.network.decision import ...
from src.task_executor import TaskManager  → from app.tasks import TaskManager
from src.utils import ConfigValidator      → from app.utils import ConfigValidator
from src.utils.logging import get_logger   → from app.utils.logging import get_logger
from src.utils.login import ...            → from app.utils.login import ...
from src.utils.network_helpers import ...  → from app.utils.network_helpers import ...
from .config_service import ...            → from .config import ...
from .profile_service import ...           → from .profile import ...
from .schemas import ...                   → from app.schemas import ...
from .ws_manager import ...                → from app.ws_manager import ...
```

**优化 2（MonitorService 简化）在此阶段同步完成：**
- 提取 `_enqueue_cmd()` 方法
- 提取 `_record_login_result()` 方法
- 删除 `_copy_runtime_config()` 薄包装

#### `app/services/config.py`
```python
from src.utils.config_helpers import ...   → from app.utils.config_helpers import ...
from src.utils.crypto import ...           → from app.utils.crypto import ...
from src.utils.logging import get_logger   → from app.utils.logging import get_logger
from src.utils.exceptions import ...       → from app.utils.exceptions import ...
from .constants import ...                 → from app.constants import ...
from .profile_service import ...           → from .profile import ...
from .schemas import ...                   → from app.schemas import ...
```

**优化 3（解密逻辑统一）在此阶段同步完成。**

#### `app/services/profile.py`
```python
from src.network_detect import ...         → from app.network.detect import ...
from src.utils.file_helpers import ...     → from app.utils.file_helpers import ...
from src.utils.crypto import ...           → from app.utils.crypto import ...
from src.utils.logging import get_logger   → from app.utils.logging import get_logger
from .schemas import ...                   → from app.schemas import ...
```

#### `app/services/task.py`
```python
from src.task_executor import ...          → from app.tasks import ...
from src.utils.logging import get_logger   → from app.utils.logging import get_logger
```

#### `app/services/scheduler.py`
```python
from src.task_executor import ...          → from app.tasks import ...
from src.utils.logging import get_logger   → from app.utils.logging import get_logger
from src.utils.shell_policy import ...     → from app.utils.shell_policy import ...
```

**优化 10（惰性锁修复）在此阶段同步完成。**

#### `app/services/login_history.py`
```python
from src.utils.file_helpers import ...     → from app.utils.file_helpers import ...
from src.utils.logging import get_logger   → from app.utils.logging import get_logger
```

#### `app/services/autostart.py`
```python
from src.utils.platform_utils import ...   → from app.utils.platform_utils import ...
from src.utils.logging import get_logger   → from app.utils.logging import get_logger
```

**同步移除嵌入式 Python 回退逻辑。**

#### `app/services/uninstall.py`
```python
from .constants import ...                 → from app.constants import ...
from src.utils.platform_utils import ...   → from app.utils.platform_utils import ...
```

#### `app/services/debug.py`
```python
from src.playwright_worker import ...      → from app.workers.playwright_worker import ...
from src.utils.env import ...              → from app.utils.env import ...
from src.utils.logging import get_logger   → from app.utils.logging import get_logger
from .debug_session import ...             → from .debug_session import ...
```

### 阶段 10：搬迁 api/（路由层）

**移动文件：** `backend/routers/*.py` → `app/api/*.py`（13 个文件）

**`app/api/__init__.py` 路由注册方式：**

沿用原 `backend/routers/__init__.py` 的模式——在 `app/application.py` 中逐个 `include_router`，而非在 `__init__.py` 中汇总导出。`app/api/__init__.py` 保持空或仅包含 `APIRouter` 实例化：

```python
# app/api/__init__.py
# 路由在 app/application.py 中通过 include_router() 注册，此处无需汇总
```

> **迁移前须确认：** 检查 `backend/routers/__init__.py` 是否有汇总逻辑（如 `__all__` 或批量导出），如有则在 `app/api/__init__.py` 中保留。

**每个路由文件的导入变更模式：**
```python
from src.xxx import ...          → from app.xxx import ...
from src.utils.xxx import ...    → from app.utils.xxx import ...
from ..constants import ...       → from app.constants import ...
from ..deps import ...            → from app.deps import ...
from ..monitor_service import ... → from app.services.monitor import ...
from ..profile_service import ... → from app.services.profile import ...
from ..schemas import ...         → from app.schemas import ...
from ..config_service import ...  → from app.services.config import ...
from ..task_service import ...    → from app.services.task import ...
from ..debug_manager import ...   → from app.services.debug import ...
from ..login_history_service import ... → from app.services.login_history import ...
from ..scheduler_service import ...    → from app.services.scheduler import ...
```

### 阶段 11：搬迁 app 层文件

**移动文件：**
| 源 | 目标 |
|----|------|
| `backend/main.py` | `app/application.py`（改名，避免与 main.py 混淆） |
| `backend/container.py` | `app/container.py` |
| `backend/deps.py` | `app/deps.py` |
| `backend/ws_manager.py` | `app/ws_manager.py` |

**`app/application.py` 导入变更：**
```python
from src.utils.logging import ...  → from app.utils.logging import ...
from src.version import ...         → from app.version import ...
from .constants import ...          → from app.constants import ...
from .container import ...          → from app.container import ...
from .routers import ...            → from app.api import ...
```

**`app/container.py` 导入变更：**
```python
from src.playwright_worker import ... → from app.workers.playwright_worker import ...
from src.utils.logging import ...     → from app.utils.logging import ...
from .autostart_service import ...    → from app.services.autostart import ...
from .debug_manager import ...        → from app.services.debug import ...
from .login_history_service import ...→ from app.services.login_history import ...
from .monitor_service import ...      → from app.services.monitor import ...
from .profile_service import ...      → from app.services.profile import ...
from .scheduler_service import ...    → from app.services.scheduler import ...
from .task_service import ...         → from app.services.task import ...
from .ws_manager import ...           → from app.ws_manager import ...
```

**`app/deps.py` 导入变更：**
```python
from .autostart_service import ...    → from app.services.autostart import ...
from .container import ...            → from app.container import ...
from .debug_manager import ...        → from app.services.debug import ...
from .login_history_service import ...→ from app.services.login_history import ...
from .monitor_service import ...      → from app.services.monitor import ...
from .profile_service import ...      → from app.services.profile import ...
from .task_service import ...         → from app.services.task import ...
```

### 阶段 12：完成 main.py 导入清理 + PID 管理提取

> 入口文件已在阶段 1 重命名为 `main.py`，本阶段完成剩余工作。

**更新 `main.py` 内部导入（替换阶段 1 中暂时保留的旧路径）：**
```python
# 旧（阶段 1 暂时保留的旧导入）
from backend.constants import AUTH_DATA_DIR
from src.playwright_bootstrap import ensure_playwright_ready
from src.playwright_worker import cleanup_orphan_browsers
from src.utils.platform_utils import is_windows
from backend.main import run

# 新
from app.constants import AUTH_DATA_DIR
from app.workers.playwright_bootstrap import ensure_playwright_ready
from app.workers.playwright_worker import cleanup_orphan_browsers
from app.utils.platform_utils import is_windows
from app.application import run  # 注意：backend/main.py 已改名为 app/application.py
```

**删除：**
- `_is_packaged()` 函数
- `_setup_packaged_env()` 函数
- `main()` 中的 `_setup_packaged_env()` 调用

**优化 5（PID 管理提取）在此阶段完成：** 详见优化 5 的完整函数签名和消费者说明。

### 阶段 13：修复测试导入

**27 个测试文件需要修改导入路径。** 其余 12 个测试文件（如纯工具函数测试、前端无关测试）不涉及 `backend/` 或 `src/` 导入，无需修改。变更规则：

```python
from backend.xxx import ...        → from app.xxx import ...
from backend.xxx_service import ... → from app.services.xxx import ...
from backend.routers.xxx import ... → from app.api.xxx import ...
from src.xxx import ...             → from app.xxx import ...
from src.utils.xxx import ...       → from app.utils.xxx import ...
from src.task_executor import ...    → from app.tasks import ...
from src.monitor_core import ...     → from app.core.monitor_core import ...
from src.playwright_worker import ...→ from app.workers.playwright_worker import ...
from src.playwright_bootstrap import ... → from app.workers.playwright_bootstrap import ...
from src.script_runner import ...    → from app.workers.script_runner import ...
from src.network_xxx import ...      → from app.network.xxx import ...
from src.system_tray import ...      → from app.core.system_tray import ...
from app import xxx                 → from main import xxx
```

**mock.patch 路径：**
```python
patch('backend.main.app', ...)                    → patch('app.application.app', ...)
patch('src.playwright_worker.get_worker', ...)     → patch('app.workers.playwright_worker.get_worker', ...)
patch('app._is_service_running', ...)              → patch('main._is_service_running', ...)
# 或提取到 process.py 后：
patch('app.utils.process._is_service_running', ...)
```

**conftest.py：**
```python
monkeypatch.setattr("app.AUTH_DATA_DIR", pid_dir) → monkeypatch.setattr("main.AUTH_DATA_DIR", pid_dir)
```

**test_app.py 额外删除（入口已在阶段 1 重命名为 `main.py`，测试文件对应改名为 `test_main.py`）：**
- `TestIsPackaged` 类
- 所有 `patch("main._setup_packaged_env")` mock（原 `patch("app._setup_packaged_env")`，阶段 1 重命名后已变为 `main`）

### 阶段 14：清理旧目录

> **安全策略：** 先重命名，验证通过后再删除，避免遗漏导入时无法快速对比排查。

```bash
# 第一步：重命名为临时目录
mv backend/ _backend_old/
mv src/ _src_old/
rm -f Campus-Auth-Setup.spec

# 第二步：验证（阶段 15 的全部检查通过后）
rm -rf _backend_old/
rm -rf _src_old/
```

### 阶段 15：验证

> 阶段 14 已将旧目录重命名为 `_backend_old/`、`_src_old/`。以下检查全部通过后，再执行删除。

```bash
# 1. 启动测试
uv run main.py --no-browser

# 2. 运行全部测试
uv run pytest

# 3. 检查残留引用（不应有输出）
grep -r "from backend\." --include="*.py" . --exclude-dir=_backend_old --exclude-dir=_src_old
grep -r "from src\." --include="*.py" . --exclude-dir=_backend_old --exclude-dir=_src_old
grep -r "import backend\." --include="*.py" . --exclude-dir=_backend_old --exclude-dir=_src_old
grep -r "import src\." --include="*.py" . --exclude-dir=_backend_old --exclude-dir=_src_old

# 4. 检查嵌入式 Python 残留
grep -r "_is_packaged\|_setup_packaged_env" --include="*.py" . --exclude-dir=_backend_old --exclude-dir=_src_old
grep -r "sys\.frozen\|getattr.*frozen" --include="*.py" . --exclude-dir=_backend_old --exclude-dir=_src_old --exclude-dir=__pycache__ --exclude-dir=.venv
grep -r '"environment/python"' --include="*.py" . --exclude-dir=_backend_old --exclude-dir=_src_old

# 5. 测试 launcher
python launcher.py --no-browser

# 6. 重新生成 uv.lock
uv lock --upgrade

# ✅ 全部通过后，删除旧目录
rm -rf _backend_old/ _src_old/
```

---

## 导入变更速查表

| 旧路径 | 新路径 |
|--------|--------|
| **入口文件** | |
| `app.py`（文件） | `main.py` |
| `from app import xxx`（测试中） | `from main import xxx` |
| `patch("app.xxx")`（测试中） | `patch("main.xxx")` |
| **backend/ → app/ 包** | |
| `backend.constants` | `app.constants` |
| `backend.schemas` | `app.schemas` |
| `backend.main` | `app.application` |
| `backend.container` | `app.container` |
| `backend.deps` | `app.deps` |
| `backend.ws_manager` | `app.ws_manager` |
| `backend.monitor_service` | `app.services.monitor` |
| `backend.config_service` | `app.services.config` |
| `backend.profile_service` | `app.services.profile` |
| `backend.task_service` | `app.services.task` |
| `backend.scheduler_service` | `app.services.scheduler` |
| `backend.login_history_service` | `app.services.login_history` |
| `backend.autostart_service` | `app.services.autostart` |
| `backend.uninstall_service` | `app.services.uninstall` |
| `backend.debug_manager` | `app.services.debug` |
| `backend.debug_session` | `app.services.debug_session` |
| `backend.routers.*` | `app.api.*` |
| **src/ → app/ 包** | |
| `src.utils.*` | `app.utils.*` |
| `src.task_executor` | `app.tasks` |
| `src.monitor_core` | `app.core.monitor_core` |
| `src.system_tray` | `app.core.system_tray` |
| `src.playwright_worker` | `app.workers.playwright_worker` |
| `src.playwright_bootstrap` | `app.workers.playwright_bootstrap` |
| `src.script_runner` | `app.workers.script_runner` |
| `src.network_probes` | `app.network.probes` |
| `src.network_decision` | `app.network.decision` |
| `src.network_detect` | `app.network.detect` |
| `src.network_test` | `app.network.diagnostics` |
| `src.version` | `app.version` |

---

## 风险与注意事项

1. **⚠️ 阶段顺序不可调换：** `app.py` → `main.py` 的重命名**必须在创建 `app/` 目录之前完成**（阶段 1），否则 Python 会将 `app` 解析为包而非模块
2. **`app/tasks/__init__.py` 必须重新导出所有公开接口**，否则大量使用 `from src.task_executor import XXX` 的代码会断
3. **`app/utils/__init__.py` 保持原有导出**，`from app.utils import ConfigValidator` 等用法不能断
4. **测试中的 `mock.patch` 路径**必须同步更新
5. **`conftest.py` 中的 `sys.path` 操作**需要检查
6. **`pyproject.toml` 中 `pythonpath = ["."]`** 保持不变（确保 `app` 包可导入）
7. **launcher.py 的 uv 下载**使用锁定版本（`_UV_VERSION`），需要镜像回退，国内网络直连 GitHub 大概率超时
8. **`autostart_service.py` 的启动命令**需要探测 uv 路径（系统 PATH → 本地 `.uv/`）
9. **`.uv/` 目录**需要加入 `.gitignore`
10. **`backend/main.py` 改名为 `app/application.py`**，所有引用 `backend.main` 的地方（包括 mock.patch）都要更新
11. **`app/network/test.py` 改名为 `app/network/diagnostics.py`**，避免 pytest 误收集，也避免与 `app/services/debug.py` 命名重复
12. **版本号唯一来源：** `app/version.py`（从 `pyproject.toml` 读取），`app/__init__.py` 不定义 `__version__`
13. **`app/utils/process.py` 的函数签名**须在优化 5 和优化 11 之间保持一致，两个消费者的调用方式不能冲突
14. **阶段 14 使用安全删除策略：** 先重命名旧目录为 `_backend_old/`、`_src_old/`，阶段 15 验证通过后再删除
