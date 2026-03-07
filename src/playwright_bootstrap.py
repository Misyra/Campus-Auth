"""Playwright bootstrap utilities.

Used by packaged executables:
- Do not bundle playwright in Nuitka build.
- Install playwright package at first run.
- Install chromium browser at first run.
"""

from __future__ import annotations

import importlib
import os
import site
import subprocess
import sys
import threading
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable


_BOOTSTRAP_LOCK = threading.Lock()
_BOOTSTRAP_DONE = False

_DEFAULT_PIP_INDEX = "https://mirrors.tuna.tsinghua.edu.cn/pypi/simple"
_DEFAULT_PLAYWRIGHT_HOST = "https://npmmirror.com/mirrors/playwright"
_DEFAULT_PORTABLE_PYTHON = "3.10.18"


def _is_enabled() -> bool:
    value = os.getenv("AUTO_INSTALL_PLAYWRIGHT", "true").strip().lower()
    return value in {"1", "true", "yes", "on"}


def _is_frozen_runtime() -> bool:
    return bool(getattr(sys, "frozen", False) or globals().get("__compiled__"))


def _project_root() -> Path:
    env_root = os.getenv("JCU_PROJECT_ROOT", "").strip()
    if env_root:
        return Path(env_root).expanduser().resolve()
    if _is_frozen_runtime():
        return Path(sys.argv[0]).resolve().parent
    return Path.cwd().resolve()


def _runtime_site_packages() -> Path:
    return _project_root() / ".jcu_runtime" / "site-packages"


def _portable_python_dir() -> Path:
    return _project_root() / ".jcu_python"


def _portable_python_executable() -> Path:
    return _portable_python_dir() / "python.exe"


def _run(cmd: list[str], env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def _tail(text: str, lines: int = 12) -> str:
    rows = [row for row in (text or "").splitlines() if row.strip()]
    if not rows:
        return ""
    return "\n".join(rows[-lines:])


def _inject_runtime_site_packages() -> None:
    user_site = site.getusersitepackages()
    if user_site and user_site not in sys.path:
        sys.path.insert(0, user_site)

    runtime_site = _runtime_site_packages()
    runtime_site.mkdir(parents=True, exist_ok=True)
    runtime_site_str = str(runtime_site)
    if runtime_site_str not in sys.path:
        sys.path.insert(0, runtime_site_str)


def _run_playwright_driver(args: list[str]) -> subprocess.CompletedProcess[str]:
    from playwright._impl._driver import compute_driver_executable, get_driver_env

    driver_executable, driver_cli = compute_driver_executable()
    env = get_driver_env()
    return _run([driver_executable, driver_cli, *args], env=env)


def _has_chromium() -> bool:
    result = _run_playwright_driver(["install", "--list"])
    output = f"{result.stdout}\n{result.stderr}".lower()
    return result.returncode == 0 and "chromium-" in output


def _download_to_file(url: str, target: Path) -> bool:
    target.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "JCU-Auto-Network/1.0"})
    with urllib.request.urlopen(req, timeout=60) as resp, target.open("wb") as f:
        f.write(resp.read())
    return True


def _patch_embed_pth(embed_dir: Path) -> None:
    pth_files = sorted(embed_dir.glob("python*._pth"))
    if not pth_files:
        return

    pth_path = pth_files[0]
    content = pth_path.read_text(encoding="utf-8", errors="ignore").splitlines()

    required = ["Lib", "Lib\\site-packages", "import site"]
    for line in required:
        if line not in content:
            content.append(line)

    pth_path.write_text("\n".join(content) + "\n", encoding="utf-8")


def _ensure_portable_python(log: Callable[[str], None] | None = None) -> Path | None:
    exe_path = _portable_python_executable()
    if exe_path.exists():
        return exe_path

    portable_dir = _portable_python_dir()
    portable_dir.mkdir(parents=True, exist_ok=True)

    py_ver = os.getenv("JCU_PORTABLE_PY_VERSION", _DEFAULT_PORTABLE_PYTHON).strip()
    py_arch = "amd64" if sys.maxsize > 2**32 else "win32"

    custom_url = os.getenv("JCU_PORTABLE_PY_URL", "").strip()
    candidate_urls = (
        [custom_url]
        if custom_url
        else [
            f"https://mirrors.tuna.tsinghua.edu.cn/python-release/windows/python-{py_ver}-embed-{py_arch}.zip",
            f"https://www.python.org/ftp/python/{py_ver}/python-{py_ver}-embed-{py_arch}.zip",
        ]
    )

    archive_path = portable_dir / "python-embed.zip"
    last_error = ""
    for url in candidate_urls:
        try:
            if log:
                log(f"正在下载便携 Python: {url}")
            _download_to_file(url, archive_path)
            break
        except Exception as exc:
            last_error = str(exc)
    else:
        if log:
            log(f"便携 Python 下载失败: {last_error}")
        return None

    try:
        with zipfile.ZipFile(archive_path, "r") as zf:
            zf.extractall(portable_dir)
    except Exception as exc:
        if log:
            log(f"解压便携 Python 失败: {exc}")
        return None
    finally:
        archive_path.unlink(missing_ok=True)

    _patch_embed_pth(portable_dir)
    if not exe_path.exists():
        if log:
            log(f"便携 Python 初始化失败，未找到解释器: {exe_path}")
        return None
    return exe_path


def _ensure_pip_with_portable_python(
    python_exe: Path,
    log: Callable[[str], None] | None = None,
) -> bool:
    if _run([str(python_exe), "-c", "import pip"]).returncode == 0:
        return True

    get_pip_urls = []
    custom_get_pip_url = os.getenv("JCU_GET_PIP_URL", "").strip()
    if custom_get_pip_url:
        get_pip_urls.append(custom_get_pip_url)
    get_pip_urls.extend(
        [
            "https://bootstrap.pypa.io/pip/3.10/get-pip.py",
            "https://bootstrap.pypa.io/get-pip.py",
        ]
    )

    get_pip_path = _portable_python_dir() / "get-pip.py"
    last_error = ""
    for url in get_pip_urls:
        try:
            if log:
                log(f"正在下载 get-pip.py: {url}")
            _download_to_file(url, get_pip_path)
            break
        except Exception as exc:
            last_error = str(exc)
    else:
        if log:
            log(f"下载 get-pip.py 失败: {last_error}")
        return False

    env = os.environ.copy()
    env.setdefault("PIP_INDEX_URL", _DEFAULT_PIP_INDEX)
    result = _run(
        [str(python_exe), str(get_pip_path), "--disable-pip-version-check", "--no-warn-script-location"],
        env=env,
    )
    get_pip_path.unlink(missing_ok=True)
    if result.returncode != 0:
        if log:
            msg = _tail(f"{result.stdout}\n{result.stderr}")
            log(f"安装 pip 失败: {msg or 'unknown error'}")
        return False

    return _run([str(python_exe), "-c", "import pip"]).returncode == 0


def _install_playwright_via_portable_python(log: Callable[[str], None] | None = None) -> bool:
    python_exe = _ensure_portable_python(log)
    if not python_exe:
        return False

    if not _ensure_pip_with_portable_python(python_exe, log):
        return False

    runtime_site = _runtime_site_packages()
    runtime_site.mkdir(parents=True, exist_ok=True)

    index_url = os.getenv("PIP_INDEX_URL", _DEFAULT_PIP_INDEX)
    cmd = [
        str(python_exe),
        "-m",
        "pip",
        "install",
        "--upgrade",
        "--disable-pip-version-check",
        "--no-warn-script-location",
        "--index-url",
        index_url,
        "--target",
        str(runtime_site),
        "playwright>=1.55.0",
    ]

    if log:
        log("使用项目内便携 Python 安装 playwright...")
    result = _run(cmd)
    if result.returncode != 0:
        if log:
            msg = _tail(f"{result.stdout}\n{result.stderr}")
            log(f"playwright 安装失败: {msg or 'unknown error'}")
        return False

    importlib.invalidate_caches()
    _inject_runtime_site_packages()
    try:
        import playwright  # noqa: F401

        if log:
            log("playwright 包安装完成（便携 Python）")
        return True
    except Exception as exc:
        if log:
            log(f"playwright 安装后导入失败: {exc}")
        return False


def _install_playwright_with_current_runtime(log: Callable[[str], None] | None = None) -> bool:
    try:
        try:
            import pip  # noqa: F401
        except Exception:
            import ensurepip

            if log:
                log("检测到未安装 pip，正在初始化 pip 组件...")
            ensurepip.bootstrap(upgrade=True, user=True)

        _inject_runtime_site_packages()
        pip_main = importlib.import_module("pip._internal.cli.main").main
        index_url = os.getenv("PIP_INDEX_URL", _DEFAULT_PIP_INDEX)
        code = pip_main(
            [
                "install",
                "--upgrade",
                "--no-warn-script-location",
                "--disable-pip-version-check",
                "--index-url",
                index_url,
                "--user",
                "playwright>=1.55.0",
            ]
        )
        if int(code) != 0:
            if log:
                log("playwright 包安装失败")
            return False

        importlib.invalidate_caches()
        import playwright  # noqa: F401
        if log:
            log("playwright 包安装完成")
        return True
    except Exception as exc:
        if log:
            log(f"playwright 包安装异常: {exc}")
        return False


def _ensure_playwright_package(log: Callable[[str], None] | None = None) -> bool:
    _inject_runtime_site_packages()

    try:
        import playwright  # noqa: F401

        return True
    except Exception:
        pass

    if os.name == "nt" and _is_frozen_runtime():
        if log:
            log("检测到 Windows 打包环境，使用项目内便携 Python 安装依赖...")
        return _install_playwright_via_portable_python(log)

    return _install_playwright_with_current_runtime(log)


def ensure_playwright_ready(log: Callable[[str], None] | None = None) -> bool:
    """Ensure playwright package + chromium are installed."""
    global _BOOTSTRAP_DONE

    with _BOOTSTRAP_LOCK:
        if _BOOTSTRAP_DONE:
            return True

        if not _is_enabled():
            _BOOTSTRAP_DONE = True
            return True

        os.environ.setdefault("PLAYWRIGHT_DOWNLOAD_HOST", _DEFAULT_PLAYWRIGHT_HOST)

        if not _ensure_playwright_package(log):
            return False

        try:
            if _has_chromium():
                _BOOTSTRAP_DONE = True
                return True

            if log:
                log("首次运行，正在自动下载 Playwright Chromium 浏览器内核...")

            result = _run_playwright_driver(["install", "chromium"])
            if result.returncode == 0:
                _BOOTSTRAP_DONE = True
                if log:
                    log("Playwright Chromium 下载完成")
                return True

            if log:
                message = (result.stderr or result.stdout or "").strip()
                log(f"Playwright Chromium 下载失败: {message}")
            return False
        except Exception as exc:
            if log:
                log(f"Playwright 初始化失败: {exc}")
            return False


def ensure_chromium_installed(log: Callable[[str], None] | None = None) -> bool:
    """Backward-compatible alias."""
    return ensure_playwright_ready(log)
