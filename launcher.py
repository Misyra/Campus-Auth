#!/usr/bin/env python3
import os
import sys
import subprocess
import urllib.request
import urllib.parse
import zipfile
import tempfile
import hashlib
import argparse
from pathlib import Path
import datetime

if sys.platform == "win32":
    os.system("chcp 65001 >nul 2>&1")

if getattr(sys, 'frozen', False):
    PROJECT_ROOT = Path(sys.executable).resolve().parent
else:
    PROJECT_ROOT = Path(__file__).resolve().parent

ENV_DIR = PROJECT_ROOT / "environment"
PYTHON_DIR = ENV_DIR / "python"
PYTHON_EXE = PYTHON_DIR / "python.exe"
PIP_EXE = PYTHON_DIR / "Scripts" / "pip.exe"
REQUIREMENTS_TXT = PROJECT_ROOT / "requirements.txt"
HASH_FILE = ENV_DIR / ".requirements_hash"
LOG_FILE = PROJECT_ROOT / "setup_env.log"


def get_timestamp():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def write_log(message, level="INFO"):
    timestamp = get_timestamp()
    log_entry = f"[{timestamp}] [{level}] {message}"
    print(log_entry)
    
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(log_entry + "\n")
    except:
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
        with open(file_path, 'rb') as f:
            file_hash = hashlib.sha256(f.read()).hexdigest()
        return file_hash
    except Exception as e:
        log_error(f"计算哈希失败: {e}")
        return None


def save_hash(hash_value):
    try:
        ENV_DIR.mkdir(parents=True, exist_ok=True)
        with open(HASH_FILE, 'w', encoding='utf-8') as f:
            f.write(hash_value)
        log_info(f"哈希值已保存: {hash_value[:8]}...")
        return True
    except Exception as e:
        log_error(f"保存哈希失败: {e}")
        return False


def load_hash():
    try:
        if HASH_FILE.exists():
            with open(HASH_FILE, 'r', encoding='utf-8') as f:
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
    needs_install = (last_hash is None) or (current_hash != last_hash) or FORCE_REINSTALL
    
    return {
        "requirements_exists": True,
        "needs_install": needs_install,
        "current_hash": current_hash,
        "last_hash": last_hash,
    }


def install_python():
    log_info("=== 安装 Python 嵌入式环境 ===")
    
    try:
        log_progress("Python", "创建 Python 目录...", 10)
        PYTHON_DIR.mkdir(parents=True, exist_ok=True)
        temp_dir = PROJECT_ROOT / "temp"
        temp_dir.mkdir(exist_ok=True)
        
        log_progress("Python", "下载 Python 嵌入式版本...", 30)
        python_version = PYTHON_VERSION
        python_url = f"https://www.python.org/ftp/python/{python_version}.0/python-{python_version}.0-embed-amd64.zip"
        log_info(f"下载地址: {python_url}")
        
        zip_path = temp_dir / "python.zip"
        try:
            urllib.request.urlretrieve(python_url, zip_path)
            log_success("Python 下载完成")
        except Exception as e:
            log_error(f"Python 下载失败: {e}")
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
        pth_file = PYTHON_DIR / f"python{python_version.replace('.', '')}._pth"
        
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
        
        log_progress("Pip", "下载 get-pip.py...", 20)
        log_info("下载地址: https://bootstrap.pypa.io/get-pip.py")
        
        try:
            urllib.request.urlretrieve("https://bootstrap.pypa.io/get-pip.py", get_pip_path)
            log_success("get-pip.py 下载完成")
        except Exception as e:
            log_error(f"get-pip.py 下载失败: {e}")
            return False
        
        log_progress("Pip", "安装 Pip...", 50)
        pip_mirror = "https://pypi.org/simple"
        pip_host = "pypi.org"
        
        log_info(f"使用镜像源: {pip_mirror}")
        log_info(f"镜像源主机: {pip_host}")
        
        try:
            proc = subprocess.run(
                [str(PYTHON_EXE), str(get_pip_path), "-i", pip_mirror, "--trusted-host", pip_host],
                capture_output=True, text=True,
            )
            
            if proc.returncode == 0:
                log_success("Pip 安装成功")
                _enable_import_site()
            else:
                log_error(f"Pip 安装失败: {proc.stderr}")
                return False
        except Exception as e:
            log_error(f"Pip 安装失败: {e}")
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
        
        mirror = "https://pypi.org/simple"
        mirror_host = "pypi.org"
        
        try:
            result1 = subprocess.run(
                [str(PYTHON_EXE), "-m", "pip", "install", "--upgrade", "setuptools", "wheel",
                 "-i", mirror, "--trusted-host", mirror_host],
                capture_output=True, text=True,
            )
            if result1.returncode == 0:
                log_success("基础工具安装完成")
            else:
                log_warning(f"基础工具安装失败: {result1.stderr[:500]}")
        except Exception as e:
            log_warning(f"基础工具安装异常: {e}")
        
        log_progress("依赖", "安装项目依赖...", 40)
        log_info("安装依赖包...")
        
        try:
            result2 = subprocess.run(
                [str(PYTHON_EXE), "-m", "pip", "install", "-r", str(REQUIREMENTS_TXT),
                 "-i", mirror, "--trusted-host", mirror_host, "--no-warn-script-location"],
                capture_output=True, text=True,
            )
            
            if result2.returncode == 0:
                log_success("项目依赖安装完成")
                if VERBOSE:
                    for line in result2.stdout.split('\n'):
                        if any(keyword in line for keyword in ["Successfully installed", "Requirement already satisfied", "Collecting"]):
                            log_info(line)
            else:
                log_error(f"项目依赖安装失败: {result2.stderr[:500]}")
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
    global VERBOSE, FORCE_REINSTALL, PYTHON_VERSION, PIP_MIRROR
    
    parser = argparse.ArgumentParser(description="Campus-Auth 环境初始化启动器")
    parser.add_argument("--python-version", default="3.10", help="Python版本 (默认: 3.10)")
    parser.add_argument("--pip-mirror", default="https://mirrors.tuna.tsinghua.edu.cn/simple", help="Pip镜像源")
    parser.add_argument("--force-reinstall", action="store_true", help="强制重新安装")
    parser.add_argument("--verbose", "-v", action="store_true", help="详细输出")
    
    args = parser.parse_args()
    VERBOSE = args.verbose
    FORCE_REINSTALL = args.force_reinstall
    PYTHON_VERSION = args.python_version
    PIP_MIRROR = args.pip_mirror
    
    print("=" * 40)
    print("Campus-Auth 校园网认证 - 启动器")
    print("=" * 40)
    
    log_info(f"项目根目录: {PROJECT_ROOT}")
    log_info(f"ENV目录: {ENV_DIR}")
    log_info(f"Python路径: {PYTHON_EXE}")
    log_info(f"Python版本: {PYTHON_VERSION}")
    log_info(f"Pip镜像源: {PIP_MIRROR}")
    print()
    
    log_info(">>> 阶段 1/3: 检查 Python 环境")
    python_result = check_python_environment()
    
    if not python_result["exe_exists"] or not python_result["can_run"] or FORCE_REINSTALL:
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
    
    playwright_chrome = list(PYTHON_DIR.glob("playwright/**/chrome.exe"))
    if not playwright_chrome:
        log_info(">>> 安装 Playwright 浏览器...")
        if not install_playwright():
            log_warning("Playwright 安装失败，但继续启动应用")
    else:
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
    os.environ["Campus-Auth_PROJECT_ROOT"] = str(PROJECT_ROOT)
    os.environ["Campus-Auth_ENV_FILE"] = str(PROJECT_ROOT / ".env")
    
    try:
        subprocess.run([str(PYTHON_EXE), str(PROJECT_ROOT / "app.py")])
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