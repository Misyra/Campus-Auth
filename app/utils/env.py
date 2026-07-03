"""登录模板变量构建工具"""

import re

from .logging import get_logger

logger = get_logger("env", source="backend")


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


def build_login_template_vars(
    auth_url: str = "",
    username: str = "",
    password: str = "",
    isp: str = "",
    task_url: str | None = None,
    custom_variables: dict[str, str] | None = None,
) -> dict[str, str]:
    """构建登录模板变量，用于任务步骤中的 {{VAR_NAME}} 替换。"""
    template_vars: dict[str, str] = {}

    if auth_url:
        template_vars["LOGIN_URL"] = auth_url

    if isp:
        template_vars["ISP"] = isp

    if username:
        template_vars["USERNAME"] = username

    if password:
        template_vars["PASSWORD"] = password

    # 内置变量集合，防止自定义变量覆盖 LOGIN_URL、ISP、USERNAME、PASSWORD
    _builtin_keys = {k for k in template_vars if k}

    if custom_variables and isinstance(custom_variables, dict):
        for k, v in custom_variables.items():
            if k.upper() in _ENV_DENYLIST:
                logger.warning("自定义变量 '{}' 与系统保留名冲突，已跳过", k)
            elif k.upper() in _builtin_keys:
                logger.warning("自定义变量 '{}' 与内置变量冲突，已跳过", k)
            else:
                template_vars[k] = str(v)

    # 在所有变量注入后解析 task_url 模板（单次替换，避免双重替换）
    if task_url:
        _VAR_PATTERN = re.compile(r"\{\{(\w+)\}\}")

        def _replacer(match: re.Match) -> str:
            name = match.group(1)
            return template_vars.get(name, match.group(0))

        template_vars["LOGIN_URL"] = _VAR_PATTERN.sub(_replacer, task_url)

    if not template_vars.get("LOGIN_URL", "").strip() and auth_url:
        template_vars["LOGIN_URL"] = auth_url

    return template_vars
