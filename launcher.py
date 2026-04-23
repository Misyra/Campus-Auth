#!/usr/bin/env python3
import argparse
import datetime
import hashlib
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

if sys.platform == "win32":
    os.system("chcp 65001 >nul 2>&1")

if getattr(sys, "frozen", False):
    PROJECT_ROOT = Path(sys.executable).resolve().parent
else:
    PROJECT_ROOT = Path(__file__).resolve().parent

ENV_DIR = PROJECT_ROOT / "environment"
BOOTSTRAP_DIR = PROJECT_ROOT / "bootstrap"
LOCAL_GET_PIP = BOOTSTRAP_DIR / "get-pip.py"
PYTHON_DIR = ENV_DIR / "python"
PYTHON_EXE = PYTHON_DIR / "python.exe"
PIP_EXE = PYTHON_DIR / "Scripts" / "pip.exe"
REQUIREMENTS_TXT = PROJECT_ROOT / "requirements.txt"
HASH_FILE = ENV_DIR / ".requirements_hash"
LOG_FILE = PROJECT_ROOT / "logs" / "setup_env.log"

DEFAULT_PIP_MIRROR = "https://mirrors.tuna.tsinghua.edu.cn/simple"
FALLBACK_PIP_MIRRORS = [
    "https://mirrors.tuna.tsinghua.edu.cn/simple",
    "https://mirrors.aliyun.com/pypi/simple",
    "https://pypi.org/simple",
]

VERBOSE = False
FORCE_REINSTALL = False
PYTHON_VERSION = "3.10"
PIP_MIRROR = DEFAULT_PIP_MIRROR
PYTHON_MIRROR = "https://mirrors.tuna.tsinghua.edu.cn/python"
PYTHON_EMBED_URL = ""
USE_SYSTEM_PROXY = False


def resolve_port() -> int:
    env_port = os.getenv("APP_PORT", "").strip()
    if env_port:
        try:
            parsed = int(env_port)
            if 1 <= parsed <= 65535:
                return parsed
        except ValueError:
            pass

    env_file = PROJECT_ROOT / ".env"
    if env_file.exists():
        try:
            for line in env_file.read_text(encoding="utf-8").splitlines():
                row = line.strip()
                if not row or row.startswith("#") or "=" not in row:
                    continue
                key, value = row.split("=", 1)
                if key.strip() != "APP_PORT":
                    continue
                port = int(value.strip())
                if 1 <= port <= 65535:
                    return port
        except Exception:
            pass

    return 50721


def is_service_running(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.6):
            return True
    except OSError:
        return False


def has_playwright_chromium() -> bool:
    try:
        probe_code = (
            "from pathlib import Path\n"
            "from playwright.sync_api import sync_playwright\n"
            "with sync_playwright() as p:\n"
            "    exe = p.chromium.executable_path\n"
            "    print('1' if exe and Path(exe).exists() else '0')\n"
        )
        result = subprocess.run(
            [str(PYTHON_EXE), "-c", probe_code],
            capture_output=True,
            text=True,
        )
        return result.returncode == 0 and result.stdout.strip().endswith("1")
    except Exception:
        return False


def duplicate_exit_delay_seconds() -> int:
    raw = os.getenv("Campus-Auth_DUPLICATE_EXIT_DELAY", "10").strip()
    try:
        delay = int(raw)
        if delay >= 0:
            return delay
    except ValueError:
        pass
    return 10


def wait_before_duplicate_exit() -> None:
    delay = duplicate_exit_delay_seconds()
    if delay <= 0:
        return
    log_info(f"{delay} 秒后自动退出")
    try:
        time.sleep(delay)
    except KeyboardInterrupt:
        pass


def get_timestamp():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def write_log(message, level="INFO"):
    timestamp = get_timestamp()
    log_entry = f"[{timestamp}] [{level}] {message}"
    print(log_entry)

    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(log_entry + "\n")
    except Exception:
        pass


def log_info(message):
    write_log(message, "INFO")


def log_success(message):
    write_log(message, "SUCCESS")


def log_warning(message):
    write_log(message, "WARNING")


def log_error(message):
    write_log(message, "ERROR")


def log_progress(stage, message, percent):
    timestamp = get_timestamp()
    progress_msg = f"[{timestamp}] [{stage}] {message} ({percent}%)"
    print(progress_msg)
    write_log(f"[{stage}] {message} ({percent}%)", "PROGRESS")


def calculate_file_hash(file_path):
    try:
        with open(file_path, "rb") as f:
            file_hash = hashlib.sha256(f.read()).hexdigest()
        return file_hash
    except Exception as e:
        log_error(f"计算哈希失败: {e}")
        return None


def save_hash(hash_value):
    try:
        ENV_DIR.mkdir(parents=True, exist_ok=True)
        with open(HASH_FILE, "w", encoding="utf-8") as f:
            f.write(hash_value)
        log_info(f"哈希值已保存: {hash_value[:8]}...")
        return True
    except Exception as e:
        log_error(f"保存哈希失败: {e}")
        return False


def load_hash():
    try:
        if HASH_FILE.exists():
            with open(HASH_FILE, "r", encoding="utf-8") as f:
                hash_value = f.read().strip()
            log_info(f"读取到哈希值: {hash_value[:8]}...")
            return hash_value
    except Exception as e:
        log_warning(f"读取哈希失败: {e}")
    return None


def check_python_environment():
    log_info("=== 检查 Python 环境 ===")

    exe_exists = PYTHON_EXE.exists()
    log_info(f"Python 可执行文件存在: {exe_exists}")

    if not exe_exists:
        return {"exe_exists": False, "can_run": False, "version": None}

    try:
        result = subprocess.run(
            [str(PYTHON_EXE), "--version"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            version = result.stdout.strip()
            log_success(f"Python 版本: {version}")
            return {"exe_exists": True, "can_run": True, "version": version}
        else:
            log_warning(f"Python 无法正常运行: {result.stderr}")
            return {"exe_exists": True, "can_run": False, "version": None}
    except Exception as e:
        log_warning(f"Python 运行异常: {e}")
        return {"exe_exists": True, "can_run": False, "version": None, "error": e}


def check_pip_environment():
    log_info("=== 检查 Pip 环境 ===")

    exe_exists = PIP_EXE.exists()
    log_info(f"Pip 可执行文件存在: {exe_exists}")

    if not exe_exists:
        return {"exe_exists": False, "can_run": False, "version": None}

    try:
        result = subprocess.run(
            [str(PYTHON_EXE), "-m", "pip", "--version"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            version = result.stdout.strip()
            log_success(f"Pip 版本: {version}")
            return {"exe_exists": True, "can_run": True, "version": version}
        else:
            log_warning(f"Pip 无法正常运行: {result.stderr}")
            return {"exe_exists": True, "can_run": False, "version": None}
    except Exception as e:
        log_warning(f"Pip 运行异常: {e}")
        return {"exe_exists": True, "can_run": False, "version": None, "error": e}


def check_dependencies():
    log_info("=== 检查依赖状态 ===")

    if not REQUIREMENTS_TXT.exists():
        log_warning("requirements.txt 不存在")
        return {
            "requirements_exists": False,
            "needs_install": False,
            "current_hash": None,
            "last_hash": None,
        }

    current_hash = calculate_file_hash(REQUIREMENTS_TXT)
    if current_hash:
        log_info(f"当前哈希: {current_hash[:8]}...")
    else:
        log_error("无法计算当前哈希")
        return {
            "requirements_exists": True,
            "needs_install": True,
            "current_hash": None,
            "last_hash": None,
        }

    last_hash = load_hash()
    needs_install = (
        (last_hash is None) or (current_hash != last_hash) or FORCE_REINSTALL
    )

    return {
        "requirements_exists": True,
        "needs_install": needs_install,
        "current_hash": current_hash,
        "last_hash": last_hash,
    }


def _get_python_embed_urls() -> list[str]:
    version = f"{PYTHON_VERSION}.0"
    filename = f"python-{version}-embed-amd64.zip"

    configured_url = (PYTHON_EMBED_URL or "").strip()
    configured_mirror = (PYTHON_MIRROR or "").strip().rstrip("/")

    candidates = [
        configured_url,
        f"{configured_mirror}/{version}/{filename}" if configured_mirror else "",
        f"https://mirrors.tuna.tsinghua.edu.cn/python/{version}/{filename}",
        f"https://www.python.org/ftp/python/{version}/{filename}",
    ]

    unique: list[str] = []
    seen = set()
    for url in candidates:
        if not url or url in seen:
            continue
        seen.add(url)
        unique.append(url)
    return unique


def _get_pip_mirror_candidates() -> list[str]:
    configured = (PIP_MIRROR or "").strip()
    merged = [configured, *FALLBACK_PIP_MIRRORS]
    unique: list[str] = []
    seen = set()
    for mirror in merged:
        if not mirror or mirror in seen:
            continue
        seen.add(mirror)
        unique.append(mirror)
    return unique


def _get_network_env() -> dict[str, str]:
    """安装相关子进程的网络环境：默认忽略系统代理，避免无效代理导致失败。"""
    env = os.environ.copy()
    if USE_SYSTEM_PROXY:
        return env

    for key in [
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "NO_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
        "no_proxy",
    ]:
        env.pop(key, None)
    return env


def _download_file(url: str, destination: Path) -> None:
    """下载文件。默认禁用系统代理，必要时可通过参数启用。"""
    if USE_SYSTEM_PROXY:
        urllib.request.urlretrieve(url, destination)
        return

    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(url, timeout=60) as resp, open(destination, "wb") as fp:
        shutil.copyfileobj(resp, fp)


def _run_pip_with_mirror(base_args: list[str], stage: str):
    """按镜像候选顺序执行 pip 命令，失败时自动切换镜像重试。"""
    errors = []
    for mirror in _get_pip_mirror_candidates():
        parsed = urllib.parse.urlparse(mirror)
        host = parsed.hostname or "pypi.org"
        log_info(f"[{stage}] 尝试镜像源: {mirror}")
        proc = subprocess.run(
            [
                str(PYTHON_EXE),
                "-m",
                "pip",
                *base_args,
                "-i",
                mirror,
                "--trusted-host",
                host,
            ],
            capture_output=True,
            text=True,
            env=_get_network_env(),
        )
        if proc.returncode == 0:
            return proc, mirror

        stderr = (proc.stderr or "")[:500]
        errors.append((mirror, stderr))
        log_warning(f"[{stage}] 镜像失败: {mirror}")

    if errors:
        last_mirror, last_stderr = errors[-1]
        log_error(f"[{stage}] 所有镜像均失败，最后一次镜像: {last_mirror}")
        if last_stderr:
            log_error(last_stderr)
    return None, None


def install_python():
    log_info("=== 安装 Python 嵌入式环境 ===")

    try:
        log_progress("Python", "创建 Python 目录...", 10)
        PYTHON_DIR.mkdir(parents=True, exist_ok=True)
        temp_dir = PROJECT_ROOT / "temp"
        temp_dir.mkdir(exist_ok=True)

        log_progress("Python", "下载 Python 嵌入式版本...", 30)
        zip_path = temp_dir / "python.zip"

        downloaded = False
        for python_url in _get_python_embed_urls():
            log_info(f"下载地址: {python_url}")
            try:
                _download_file(python_url, zip_path)
                log_success("Python 下载完成")
                downloaded = True
                break
            except Exception as e:
                log_warning(f"Python 下载失败，尝试下一个源: {e}")

        if not downloaded:
            log_error("Python 下载失败：所有下载源均不可用")
            return False

        log_progress("Python", "正在解压 Python...", 60)
        log_info(f"解压到: {PYTHON_DIR}")

        try:
            with zipfile.ZipFile(zip_path, "r") as z:
                z.extractall(PYTHON_DIR)
            log_success("Python 解压完成")
        except Exception as e:
            log_error(f"Python 解压失败: {e}")
            return False

        log_progress("Python", "配置 Python 环境...", 80)
        pth_file = PYTHON_DIR / f"python{PYTHON_VERSION.replace('.', '')}._pth"

        if pth_file.exists():
            log_info(f"配置文件: {pth_file}")
            try:
                with open(pth_file, "r") as f:
                    content = f.read()
                content = content.replace("#import site", "import site")
                with open(pth_file, "w") as f:
                    f.write(content)
                log_success("已启用 site-packages 支持")
            except Exception as e:
                log_warning(f"配置 .pth 文件失败: {e}")
        else:
            log_warning("未找到 .pth 配置文件")

        log_progress("Python", "清理临时文件...", 95)
        if zip_path.exists():
            zip_path.unlink()
            log_info(f"清理临时文件: {zip_path}")

        log_progress("Python", "Python 安装完成", 100)
        return True

    except Exception as e:
        log_error(f"Python 安装失败: {e}")
        return False


def install_pip():
    log_info("=== 安装 Pip ===")

    try:
        temp_dir = PROJECT_ROOT / "temp"
        temp_dir.mkdir(exist_ok=True)
        get_pip_path = temp_dir / "get-pip.py"

        if LOCAL_GET_PIP.exists():
            log_progress("Pip", "使用项目内 get-pip.py...", 20)
            log_info(f"本地文件: {LOCAL_GET_PIP}")
            try:
                shutil.copy2(LOCAL_GET_PIP, get_pip_path)
                log_success("已复制本地 get-pip.py")
            except Exception as e:
                log_error(f"复制本地 get-pip.py 失败: {e}")
                return False
        else:
            log_progress("Pip", "下载 get-pip.py...", 20)
            log_info("下载地址: https://bootstrap.pypa.io/get-pip.py")
            try:
                _download_file("https://bootstrap.pypa.io/get-pip.py", get_pip_path)
                log_success("get-pip.py 下载完成")
            except Exception as e:
                log_error(f"get-pip.py 下载失败: {e}")
                log_error("请将 get-pip.py 放到项目目录 bootstrap/get-pip.py 后重试")
                return False

        log_progress("Pip", "安装 Pip...", 50)
        installed = False
        for mirror in _get_pip_mirror_candidates():
            parsed = urllib.parse.urlparse(mirror)
            pip_host = parsed.hostname or "pypi.org"
            log_info(f"使用镜像源: {mirror}")
            log_info(f"镜像源主机: {pip_host}")
            try:
                proc = subprocess.run(
                    [
                        str(PYTHON_EXE),
                        str(get_pip_path),
                        "-i",
                        mirror,
                        "--trusted-host",
                        pip_host,
                    ],
                    capture_output=True,
                    text=True,
                    env=_get_network_env(),
                )
            except Exception as e:
                log_warning(f"Pip 安装异常，镜像 {mirror}: {e}")
                continue

            if proc.returncode == 0:
                log_success("Pip 安装成功")
                _enable_import_site()
                installed = True
                break

            log_warning(f"Pip 安装失败，镜像 {mirror}: {(proc.stderr or '')[:300]}")

        if not installed:
            log_error("Pip 安装失败：所有镜像均不可用")
            return False

        log_progress("Pip", "清理临时文件...", 90)
        if get_pip_path.exists():
            get_pip_path.unlink()
            log_info(f"清理临时文件: {get_pip_path}")

        log_progress("Pip", "Pip 安装完成", 100)
        return True

    except Exception as e:
        log_error(f"Pip 安装失败: {e}")
        return False


def _enable_import_site():
    python_version = PYTHON_VERSION
    pth_file = PYTHON_DIR / f"python{python_version.replace('.', '')}._pth"
    if pth_file.exists():
        try:
            with open(pth_file, "r") as f:
                content = f.read()
            if "#import site" in content:
                content = content.replace("#import site", "import site")
                with open(pth_file, "w") as f:
                    f.write(content)
                log_success("已启用 import site")
        except Exception as e:
            log_warning(f"启用 import site 失败: {e}")


def install_requirements():
    log_info("=== 安装项目依赖 ===")

    try:
        if not REQUIREMENTS_TXT.exists():
            log_error("requirements.txt 不存在")
            return False

        log_progress("依赖", "安装基础工具 (setuptools, wheel)...", 10)
        log_info("升级 setuptools 和 wheel...")

        try:
            result1, mirror1 = _run_pip_with_mirror(
                ["install", "--upgrade", "setuptools", "wheel"],
                stage="基础工具",
            )
            if result1 is not None:
                log_success(f"基础工具安装完成 (镜像: {mirror1})")
            else:
                log_warning("基础工具安装失败，继续尝试安装项目依赖")
        except Exception as e:
            log_warning(f"基础工具安装异常: {e}")

        log_progress("依赖", "安装项目依赖...", 40)
        log_info("安装依赖包...")

        try:
            result2, mirror2 = _run_pip_with_mirror(
                [
                    "install",
                    "-r",
                    str(REQUIREMENTS_TXT),
                    "--no-warn-script-location",
                ],
                stage="项目依赖",
            )

            if result2 is not None:
                log_success(f"项目依赖安装完成 (镜像: {mirror2})")
                if VERBOSE:
                    for line in result2.stdout.split("\n"):
                        if any(
                            keyword in line
                            for keyword in [
                                "Successfully installed",
                                "Requirement already satisfied",
                                "Collecting",
                            ]
                        ):
                            log_info(line)
            else:
                return False
        except Exception as e:
            log_error(f"项目依赖安装异常: {e}")
            return False

        log_progress("依赖", "保存哈希值...", 95)
        current_hash = calculate_file_hash(REQUIREMENTS_TXT)
        if current_hash:
            save_hash(current_hash)

        log_progress("依赖", "依赖安装完成", 100)
        return True

    except Exception as e:
        log_error(f"依赖安装失败: {e}")
        return False


def install_playwright():
    log_info("=== 安装 Playwright 浏览器 ===")

    try:
        result = subprocess.run(
            [str(PYTHON_EXE), "-m", "playwright", "install", "chromium"],
            capture_output=True,
        )

        if result.returncode == 0:
            log_success("Playwright 安装完成")
            return True
        else:
            log_error(f"Playwright 安装失败: {result.stderr.decode()[:200]}")
            return False
    except Exception as e:
        log_error(f"Playwright 安装异常: {e}")
        return False


def main():
    global \
        VERBOSE, \
        FORCE_REINSTALL, \
        PYTHON_VERSION, \
        PIP_MIRROR, \
        PYTHON_MIRROR, \
        PYTHON_EMBED_URL, \
        USE_SYSTEM_PROXY

    parser = argparse.ArgumentParser(description="Campus-Auth 环境初始化启动器")
    parser.add_argument(
        "--python-version", default="3.10", help="Python版本 (默认: 3.10)"
    )
    parser.add_argument(
        "--pip-mirror",
        default=DEFAULT_PIP_MIRROR,
        help="Pip镜像源",
    )
    parser.add_argument(
        "--python-mirror",
        default="https://mirrors.tuna.tsinghua.edu.cn/python",
        help="Python嵌入包镜像根地址（示例: https://mirrors.tuna.tsinghua.edu.cn/python）",
    )
    parser.add_argument(
        "--python-embed-url",
        default="",
        help="Python嵌入包完整下载地址（优先级最高）",
    )
    parser.add_argument(
        "--use-system-proxy",
        action="store_true",
        help="安装阶段使用系统代理（默认关闭，避免无效代理导致安装失败）",
    )
    parser.add_argument("--force-reinstall", action="store_true", help="强制重新安装")
    parser.add_argument("--verbose", "-v", action="store_true", help="详细输出")

    args = parser.parse_args()
    VERBOSE = args.verbose
    FORCE_REINSTALL = args.force_reinstall
    PYTHON_VERSION = args.python_version
    PIP_MIRROR = args.pip_mirror
    PYTHON_MIRROR = args.python_mirror
    PYTHON_EMBED_URL = args.python_embed_url
    USE_SYSTEM_PROXY = args.use_system_proxy

    print("=" * 40)
    print("Campus-Auth 校园网认证 - 启动器")
    print("=" * 40)

    port = resolve_port()
    if is_service_running(port):
        log_success(f"检测到服务已在运行: http://127.0.0.1:{port}")
        log_info("请勿重复启动")
        wait_before_duplicate_exit()
        return

    log_info(f"项目根目录: {PROJECT_ROOT}")
    log_info(f"ENV目录: {ENV_DIR}")
    log_info(f"Python路径: {PYTHON_EXE}")
    log_info(f"Python版本: {PYTHON_VERSION}")
    log_info(f"Python镜像源: {PYTHON_MIRROR}")
    if PYTHON_EMBED_URL:
        log_info(f"Python嵌入包直链: {PYTHON_EMBED_URL}")
    log_info(f"Pip镜像源: {PIP_MIRROR}")
    log_info(
        f"安装阶段代理: {'系统代理' if USE_SYSTEM_PROXY else '直连(忽略系统代理)'}"
    )
    print()

    log_info(">>> 阶段 1/3: 检查 Python 环境")
    python_result = check_python_environment()

    if (
        not python_result["exe_exists"]
        or not python_result["can_run"]
        or FORCE_REINSTALL
    ):
        log_info(">>> 开始安装 Python...")
        if not install_python():
            log_error("Python 安装失败")
            sys.exit(1)
    else:
        log_success(f"Python 已就绪 (版本: {python_result['version']})，跳过安装")
    print()

    log_info(">>> 阶段 2/3: 检查 Pip 环境")
    pip_result = check_pip_environment()

    if not pip_result["exe_exists"] or not pip_result["can_run"] or FORCE_REINSTALL:
        log_info(">>> 开始安装 Pip...")
        if not install_pip():
            log_error("Pip 安装失败")
            sys.exit(1)
    else:
        log_success(f"Pip 已就绪 (版本: {pip_result['version']})，跳过安装")
    print()

    log_info(">>> 阶段 3/3: 检查依赖状态")
    dep_result = check_dependencies()

    if not dep_result["requirements_exists"]:
        log_error("requirements.txt 不存在，无法安装依赖")
        sys.exit(1)

    if dep_result["needs_install"] or FORCE_REINSTALL:
        log_info(">>> 开始安装依赖...")
        if not install_requirements():
            log_error("依赖安装失败")
            sys.exit(1)
    else:
        log_success("依赖已是最新，跳过安装")
    print()

    playwright_ready = False
    if not has_playwright_chromium():
        log_info(">>> 安装 Playwright 浏览器...")
        if install_playwright():
            playwright_ready = True
        else:
            log_warning("Playwright 安装失败，但继续启动应用")
    else:
        playwright_ready = True
        log_success("Playwright 浏览器已安装")
    print()

    print("=" * 40)
    log_success("环境初始化完成！")
    print("=" * 40)
    print()
    log_info(f"Python 路径: {PYTHON_EXE}")
    log_info(f"Pip 路径: {PIP_EXE}")
    print()
    log_info("使用方法:")
    log_info(f"  运行项目: {PYTHON_EXE} app.py")
    log_info(f"  安装新依赖: {PYTHON_EXE} -m pip install <包名> -i {PIP_MIRROR}")
    log_info(f"  查看已安装包: {PYTHON_EXE} -m pip list")
    print()
    log_info(f"日志文件: {LOG_FILE}")
    print()

    log_info(">>> 启动应用...")
    if is_service_running(port):
        log_success(f"检测到服务已在运行: http://127.0.0.1:{port}")
        log_info("已跳过重复启动")
        wait_before_duplicate_exit()
        return

    launch_env = os.environ.copy()
    launch_env["Campus-Auth_PROJECT_ROOT"] = str(PROJECT_ROOT)
    launch_env["Campus-Auth_ENV_FILE"] = str(PROJECT_ROOT / ".env")
    if playwright_ready:
        # 启动器已确保浏览器可用，避免 app.py 再次执行同样安装流程
        launch_env["AUTO_INSTALL_PLAYWRIGHT"] = "false"

    try:
        subprocess.run([str(PYTHON_EXE), str(PROJECT_ROOT / "app.py")], env=launch_env)
    except KeyboardInterrupt:
        log_info("应用被用户中断")
    except Exception as e:
        log_error(f"应用启动失败: {e}")
        sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n程序被用户中断")
        sys.exit(0)
    except Exception as e:
        print(f"\n未处理的错误: {e}")
        sys.exit(1)
