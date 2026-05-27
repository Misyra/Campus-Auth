"""共享环境变量构建工具"""

import os
from typing import Any


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
}


def build_login_env_vars(
    runtime_config: dict[str, Any],
    task_url: str | None = None,
    custom_variables: dict[str, str] | None = None,
) -> dict[str, str]:
    env_vars = dict(os.environ)

    auth_url = runtime_config.get("auth_url", "")
    if auth_url:
        env_vars["LOGIN_URL"] = auth_url

    # 在解析 task_url 之前注入运行时配置变量，
    # 确保 task_url 中的 {{USERNAME}}/{{PASSWORD}}/{{ISP}} 解析为校园网配置值
    isp = runtime_config.get("isp", "")
    if isp:
        env_vars["ISP"] = isp

    username = runtime_config.get("username", "")
    if username:
        env_vars["USERNAME"] = username

    password = runtime_config.get("password", "")
    if password:
        env_vars["PASSWORD"] = password

    if custom_variables and isinstance(custom_variables, dict):
        for k, v in custom_variables.items():
            if k.upper() not in _ENV_DENYLIST:
                env_vars[k] = v

    # 在所有变量注入后解析 task_url 模板
    if task_url:
        resolved_url = task_url
        for k, v in env_vars.items():
            # 跳过未覆盖的系统环境变量（PATH, TEMP 等），防止 URL 模板注入；
            # 如果 runtime_config 已显式覆盖（如 USERNAME），则保留其模板解析能力
            if k.upper() in _ENV_DENYLIST and os.environ.get(k) == v:
                continue
            resolved_url = resolved_url.replace("{{" + k + "}}", v)
        env_vars["LOGIN_URL"] = resolved_url

    if not env_vars.get("LOGIN_URL", "").strip() and auth_url:
        env_vars["LOGIN_URL"] = auth_url

    return env_vars
