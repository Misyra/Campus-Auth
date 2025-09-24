import socket
import subprocess
import platform
import sys
import time

def log(message, verbose=True):
    """可选的日志输出函数"""
    if verbose:
        print(message)

def is_local_network_connected(verbose=False):
    """
    检查是否连接到本地网络（是否获取到非回环IP）
    """
    try:
        hostname = socket.gethostname()
        ip_list = socket.gethostbyname_ex(hostname)[2]
        non_loopback_ips = [ip for ip in ip_list if not ip.startswith("127.")]
        if verbose:
            log(f"本地IP地址: {non_loopback_ips}", verbose)
        return len(non_loopback_ips) > 0
    except Exception as e:
        if verbose:
            log(f"获取本地IP失败: {e}", verbose)
        return False

def is_network_available_socket(test_sites=None, timeout=1, verbose=False):
    """
    方法1：使用Socket连接检测网络是否可用（TCP 443端口）
    """
    if test_sites is None:
        test_sites = [
            ("www.baidu.com", 443),
        ]

    for site, port in test_sites:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(timeout)
                result = s.connect_ex((site, port))
                if result == 0:
                    log(f"✅ Socket连接成功: {site}:{port}", verbose)
                    return True
                else:
                    log(f"❌ Socket连接失败: {site}:{port} (错误码: {result})", verbose)
        except Exception as e:
            log(f"⚠️ Socket连接异常: {site}:{port} ({e})", verbose)
            continue
    return False

def is_network_available_curl(test_urls=None, timeout=1, verbose=False):
    """
    方法2：使用curl命令检测网络是否可用（模拟真实HTTP请求）
    """
    if test_urls is None:
        test_urls = [
            "https://www.baidu.com",
        ]

    # 检测系统是否安装 curl
    try:
        subprocess.run(["curl", "--version"], capture_output=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        log("⚠️ curl 命令未找到，跳过 curl 测试", verbose)
        return False  # 或者你可以 fallback 到其他方法

    for url in test_urls:
        try:
            cmd = [
                "curl",
                "-s",           # 静默模式
                "-S",           # 显示错误
                "-f",           # 失败时返回非0
                "-m", str(timeout),  # 超时
                "--connect-timeout", str(timeout),
                url
            ]
            result = subprocess.run(cmd, capture_output=True, timeout=timeout + 2)
            if result.returncode == 0:
                log(f"✅ curl访问成功: {url}", verbose)
                return True
            else:
                log(f"❌ curl访问失败: {url} (返回码: {result.returncode})", verbose)
        except (subprocess.TimeoutExpired, subprocess.SubprocessError, OSError) as e:
            log(f"⚠️ curl执行异常: {url} ({e})", verbose)
            continue
    return False

def is_network_available(test_sites=None, test_urls=None, timeout=1, verbose=True, require_both=False):
    """
    综合网络检测：使用Socket和curl两种方法检测网络（简化版）
    
    参数:
        require_both: 是否要求两种方法都成功（默认False，任一成功即可）
    """
    log("正在进行 Socket 连接测试...", verbose)
    socket_result = is_network_available_socket(test_sites, timeout, verbose)

    log("正在进行 curl HTTP 测试...", verbose)
    curl_result = is_network_available_curl(test_urls, timeout, verbose)

    log(f"Socket测试结果: {'成功' if socket_result else '失败'}", verbose)
    log(f"curl测试结果: {'成功' if curl_result else '失败'}", verbose)

    # 灵活的策略选择
    if require_both:
        return socket_result and curl_result
    else:
        return socket_result or curl_result

def check_campus_network_status(verbose=True):
    """
    检查校园网状态并返回友好信息
    """
    log("正在检测网络状态...", verbose)

    is_local = is_local_network_connected(verbose)
    is_internet = is_network_available(None, None, 1, verbose)

    if not is_local:
        return "🔴 未连接到校园网，请检查网络连接（未获取到有效IP）"
    elif is_internet:
        return "🟢 已连接校园网并可访问互联网"
    else:
        return "🟡 已连接校园网，但无法访问互联网，请登录校园网认证页面"

if __name__ == "__main__":
    # 可选：接收命令行参数控制 verbose
    verbose = "-v" in sys.argv or "--verbose" in sys.argv

    status = check_campus_network_status(verbose=verbose)
    print("\n" + "="*50)
    print(status)
    print("="*50)