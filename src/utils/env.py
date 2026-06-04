"""登录模板变量构建工具"""

import logging
from typing import Any

logger = logging.getLogger("env")


# Windows 保留环境变量 + Unix/Python 内置变量，防止 runtime vars 与系统变量冲突
_ENV_DENYLIST = {
    "PATH",
    "PYTHONPATH",
    "HOME",
    "USER",
    "USERNAME",
    "SYSTEMROOT",
    "TEMP",
    "TMP",
    "PATHEXT",
    "COMSPEC",
    "WINDIR",
    "LD_LIBRARY_PATH",
    "DYLD_LIBRARY_PATH",
    "DISPLAY",
    "SHELL",
    "LANG",
    "LC_ALL",
    "NODE_OPTIONS",
    "LD_PRELOAD",
    "PYTHONSTARTUP",
    "CLASSPATH",
    "NODE_PATH",
    "GOPATH",
}

# 预计算大写集合，避免每次比较时重复转换
_ENV_DENYLIST_UPPER = {k.upper() for k in _ENV_DENYLIST}


def build_login_template_vars(
    runtime_config: dict[str, Any],
    task_url: str | None = None,
    custom_variables: dict[str, str] | None = None,
) -> dict[str, str]:
    """构建登录模板变量，用于任务步骤中的 {{VAR_NAME}} 替换。"""
    template_vars: dict[str, str] = {}

    auth_url = runtime_config.get("auth_url", "")
    if auth_url:
        template_vars["LOGIN_URL"] = auth_url

    # 在解析 task_url 之前注入运行时配置变量，
    # 确保 task_url 中的 {{USERNAME}}/{{PASSWORD}}/{{ISP}} 解析为校园网配置值
    isp = runtime_config.get("isp", "")
    if isp:
        template_vars["ISP"] = isp

    username = runtime_config.get("username", "")
    if username:
        template_vars["USERNAME"] = username

    password = runtime_config.get("password", "")
    if password:
        template_vars["PASSWORD"] = password

    if custom_variables and isinstance(custom_variables, dict):
        for k, v in custom_variables.items():
            if k.upper() in _ENV_DENYLIST_UPPER:
                logger.warning("自定义变量 '%s' 与系统保留名冲突，已跳过", k)
            else:
                template_vars[k] = v

    # 在所有变量注入后解析 task_url 模板
    if task_url:
        resolved_url = task_url
        for k, v in template_vars.items():
            resolved_url = resolved_url.replace("{{" + k + "}}", v)
        template_vars["LOGIN_URL"] = resolved_url

    if not template_vars.get("LOGIN_URL", "").strip() and auth_url:
        template_vars["LOGIN_URL"] = auth_url

    return template_vars
