"""登录模板变量构建工具"""

import re

from .logging import get_logger

logger = get_logger("env", source="backend")


def build_login_template_vars(
    auth_url: str = "",
    username: str = "",
    password: str = "",
    isp: str = "",
    task_url: str | None = None,
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
