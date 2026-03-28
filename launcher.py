#!/usr/bin/env python3
import os
import sys
import subprocess
import shutil
import urllib.request
import urllib.parse
import zipfile
import tempfile
from pathlib import Path
import datetime

if getattr(sys, 'frozen', False):
    PROJECT_ROOT = Path(sys.argv[0]).resolve().parent
else:
    PROJECT_ROOT = Path(__file__).resolve().parent

ENV_DIR = PROJECT_ROOT / "environment"
PYTHON_DIR = ENV_DIR
PYTHON_EXE = PYTHON_DIR / "python.exe"
PIP_EXE = PYTHON_DIR / "Scripts" / "pip.exe"
REQUIREMENTS_TXT = PROJECT_ROOT / "requirements.txt"
LOG_FILE = PROJECT_ROOT / "setup_launcher.log"
PYTHON_VERSION = "3.10"


def log(msg):
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_entry = f"[{timestamp}] {msg}"
    print(log_entry)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(log_entry + "\n")
    except:
        pass


def run_py(*args):
    cmd = [str(PYTHON_EXE)] + list(args)
    log(f"执行命令: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        log(f"命令失败: {result.stderr}")
        return False
    return True


def check_python():
    log(f"检查 Python: {PYTHON_EXE}")
    log(f"是否存在: {PYTHON_EXE.exists()}")
    if not PYTHON_EXE.exists():
        return False

    result = subprocess.run(
        [str(PYTHON_EXE), "--version"],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        log(f"Python 版本: {result.stdout.strip()}")
        return True
    return False


def download_python():
    log("开始下载 Python...")

    ENV_DIR.mkdir(exist_ok=True)

    urls = [
        f"https://www.python.org/ftp/python/{PYTHON_VERSION}.0/python-{PYTHON_VERSION}.0-embed-amd64.zip",
    ]

    with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as tmp:
        tmp_path = tmp.name

    try:
        for url in urls:
            try:
                log(f"下载: {url}")
                urllib.request.urlretrieve(url, tmp_path)
                break
            except Exception as e:
                log(f"下载失败: {e}")
                continue

        log("解压 Python...")
        with zipfile.ZipFile(tmp_path, "r") as z:
            z.extractall(ENV_DIR)

        for dll in ENV_DIR.glob("python3*.dll"):
            target = dll.name.replace("python3x", "python3")
            target_path = ENV_DIR / target
            if not target_path.exists():
                shutil.move(str(dll), str(target_path))

        log("Python 解压完成")
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


def get_fastest_mirror(urls, timeout=5):
    """测试多个镜像源，返回最快的一个"""
    import socket
    import time

    fastest_url = urls[0]
    fastest_time = float('inf')

    for url in urls:
        try:
            start = time.time()
            req = urllib.request.Request(url, method='HEAD')
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                elapsed = time.time() - start
                log(f"镜像 {url} 响应时间: {elapsed:.2f}s")
                if elapsed < fastest_time:
                    fastest_time = elapsed
                    fastest_url = url
        except Exception as e:
            log(f"镜像 {url} 不可用: {e}")

    log(f"选择最快镜像: {fastest_url} ({fastest_time:.2f}s)")
    return fastest_url


def install_pip():
    if PIP_EXE.exists():
        log("pip 已存在")
        return True

    log("安装 pip...")

    scripts_dir = PYTHON_DIR / "Scripts"
    scripts_dir.mkdir(exist_ok=True)

    # get-pip.py 镜像源列表
    get_pip_urls = [
        "https://mirrors.tuna.tsinghua.edu.cn/pypi/get-pip.py",
        "https://mirrors.aliyun.com/pypi/get-pip.py",
        "https://pypi.tuna.tsinghua.edu.cn/simple/pip/",
        "https://bootstrap.pypa.io/get-pip.py",
    ]

    get_pip_url = get_fastest_mirror(get_pip_urls)

    with tempfile.NamedTemporaryFile(delete=False, suffix=".py") as tmp:
        tmp_path = tmp.name

    try:
        urllib.request.urlretrieve(get_pip_url, tmp_path)
        log("运行 get-pip.py...")

        proc = subprocess.Popen(
            [str(PYTHON_EXE), tmp_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        stdout, stderr = proc.communicate()

        if proc.returncode != 0:
            log(f"pip 安装stderr: {stderr.decode()[:500]}")
        else:
            log("pip 安装成功")

        pth_file = PYTHON_DIR / f"python{PYTHON_VERSION.replace('.','')}._pth"
        if pth_file.exists():
            with open(pth_file, "r") as f:
                content = f.read()
            if "# import site" in content:
                content = content.replace("# import site", "import site")
                with open(pth_file, "w") as f:
                    f.write(content)
                log("已启用 _pth 中的 import site")

        return True
    except Exception as e:
        log(f"pip 安装异常: {e}")
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)

    return False


def install_requirements():
    if not PIP_EXE.exists():
        log("pip 不存在，跳过安装依赖")
        return False

    log("安装项目依赖...")

    mirrors = [
        "https://mirrors.tuna.tsinghua.edu.cn/simple",
        "https://mirrors.aliyun.com/pypi/simple",
        "https://pypi.tuna.tsinghua.edu.cn/simple",
    ]
    mirror = get_fastest_mirror(mirrors)
    mirror_host = urllib.parse.urlparse(mirror).hostname or "mirrors.tuna.tsinghua.edu.cn"

    subprocess.run(
        [str(PYTHON_EXE), "-m", "pip", "install", "--trusted-host", mirror_host,
         "-i", mirror, "setuptools", "wheel"],
        capture_output=True,
    )

    subprocess.run(
        [str(PYTHON_EXE), "-m", "pip", "install", "--trusted-host", mirror_host,
         "-i", mirror, "-r", str(REQUIREMENTS_TXT)],
        capture_output=True,
    )

    log("依赖安装完成")
    return True


def install_playwright():
    log("安装 Playwright 浏览器...")

    result = subprocess.run(
        [str(PYTHON_EXE), "-m", "playwright", "install", "chromium"],
        capture_output=True,
    )

    if result.returncode == 0:
        log("Playwright 安装完成")
    else:
        log(f"Playwright 安装失败: {result.stderr.decode()[:200]}")


def run_app():
    log("启动应用...")

    os.environ["Campus-Auth_PROJECT_ROOT"] = str(PROJECT_ROOT)
    os.environ["Campus-Auth_ENV_FILE"] = str(PROJECT_ROOT / ".env")

    subprocess.run([str(PYTHON_EXE), str(PROJECT_ROOT / "app.py")])


def main():
    print("=" * 40)
    print("Campus-Auth 校园网认证 - 启动器")
    print("=" * 40)

    log(f"项目根目录: {PROJECT_ROOT}")
    log(f"ENV目录: {ENV_DIR}")
    log(f"Python路径: {PYTHON_EXE}")

    if not check_python():
        log("需要下载 Python")
        download_python()

    log("检查 pip...")
    if not PIP_EXE.exists():
        install_pip()

    log("检查依赖...")
    deps = ["dotenv", "playwright", "fastapi"]
    missing = []
    for dep in deps:
        result = subprocess.run(
            [str(PYTHON_EXE), "-c", f"import {dep}"],
            capture_output=True,
        )
        if result.returncode != 0:
            missing.append(dep)
            log(f"缺少模块: {dep}")

    if missing:
        log(f"缺少依赖: {missing}")
        install_requirements()
    
    if not list(PYTHON_DIR.glob("playwright/**/chrome.exe")):
        install_playwright()

    run_app()


if __name__ == "__main__":
    main()