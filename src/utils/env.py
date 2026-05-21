"""共享环境变量构建工具"""

import os
from typing import Any


_ENV_DENYLIST = {
    "PATH", "PYTHONPATH", "HOME", "USER", "USERNAME",
    "SYSTEMROOT", "TEMP", "TMP", "PATHEXT", "COMSPEC", "WINDIR",
    "LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH", "DISPLAY", "SHELL",
    "LANG", "LC_ALL",
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

    # Inject runtime config vars BEFORE task_url resolution,
    # so that {{USERNAME}}/{{PASSWORD}}/{{ISP}} in task_url resolve
    # to the campus-auth config values instead of OS env or staying unresolved.
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

    # Resolve task_url template AFTER all vars are injected
    if task_url:
        resolved_url = task_url
        for k, v in env_vars.items():
            resolved_url = resolved_url.replace("{{" + k + "}}", v)
        env_vars["LOGIN_URL"] = resolved_url

    if not env_vars.get("LOGIN_URL", "").strip() and auth_url:
        env_vars["LOGIN_URL"] = auth_url

    return env_vars
