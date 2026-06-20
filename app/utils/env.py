"""登录模板变量构建工具"""

from typing import Any

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

# 预计算大写集合，避免每次比较时重复转换
_ENV_DENYLIST_UPPER = {k.upper() for k in _ENV_DENYLIST}


def build_login_template_vars(
    runtime_config: "RuntimeConfig | dict[str, Any]",
    task_url: str | None = None,
    custom_variables: dict[str, str] | None = None,
) -> dict[str, str]:
    """构建登录模板变量，用于任务步骤中的 {{VAR_NAME}} 替换。

    *runtime_config* 可以是 RuntimeConfig（Pydantic model）或旧版 dict。
    """
    template_vars: dict[str, str] = {}

    # 支持 RuntimeConfig 和旧版 dict 两种类型
    if hasattr(runtime_config, "credentials"):
        auth_url = runtime_config.credentials.auth_url
        isp = runtime_config.credentials.isp
        username = runtime_config.credentials.username
        password = runtime_config.credentials.password
        resolved_custom_vars = (
            custom_variables
            if custom_variables is not None
            else runtime_config.custom_variables
        )
    else:
        auth_url = runtime_config.get("auth_url", "")
        isp = runtime_config.get("isp", "")
        username = runtime_config.get("username", "")
        password = runtime_config.get("password", "")
        resolved_custom_vars = custom_variables

    if auth_url:
        template_vars["LOGIN_URL"] = auth_url

    # 在解析 task_url 之前注入运行时配置变量，
    # 确保 task_url 中的 {{USERNAME}}/{{PASSWORD}}/{{ISP}} 解析为校园网配置值
    if isp:
        template_vars["ISP"] = isp

    if username:
        template_vars["USERNAME"] = username

    if password:
        template_vars["PASSWORD"] = password

    # 内置变量集合，防止自定义变量覆盖 LOGIN_URL、ISP、USERNAME、PASSWORD
    _builtin_keys = {k for k in template_vars if k}

    if resolved_custom_vars and isinstance(resolved_custom_vars, dict):
        for k, v in resolved_custom_vars.items():
            if k.upper() in _ENV_DENYLIST_UPPER:
                logger.warning("自定义变量 '{}' 与系统保留名冲突，已跳过", k)
            elif k.upper() in _builtin_keys:
                logger.warning("自定义变量 '{}' 与内置变量冲突，已跳过", k)
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
