"""仓库代理工具 — 远程 JSON 获取和 URL 规范化。

从 backend/main.py 提取，作为独立的工具模块。
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

import httpx
from fastapi import HTTPException

from .logging import get_logger

logger = get_logger("repo_proxy", source="backend")

# 允许的 URL scheme，防止 file://、ftp:// 等协议访问本地资源
_ALLOWED_SCHEMES = {"http", "https"}


def validate_url(url: str) -> str:
    """校验 URL scheme，仅允许 http/https，防止 SSRF 攻击。"""
    parsed = urlparse(url)
    if parsed.scheme.lower() not in _ALLOWED_SCHEMES:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的 URL 协议: {parsed.scheme or '无协议'}，仅支持 http/https",
        )
    return url


def _normalize_repo_url(url: str) -> str:
    """将 GitHub/Gitee 页面链接转换为 raw 链接，其他链接原样返回"""
    m = re.match(r"https?://github\.com/([^/]+)/([^/]+)/blob/([^/]+)/(.+)", url)
    if m:
        return f"https://raw.githubusercontent.com/{m.group(1)}/{m.group(2)}/{m.group(3)}/{m.group(4)}"
    m = re.match(r"https?://gitee\.com/([^/]+)/([^/]+)/blob/([^/]+)/(.+)", url)
    if m:
        return f"https://gitee.com/{m.group(1)}/{m.group(2)}/raw/{m.group(3)}/{m.group(4)}"
    return url


async def async_repo_fetch_json(url: str, expected_type: type, label: str, proxy: str = ""):
    """异步版本的远程 JSON 获取：校验类型 + 统一异常处理。供异步路由使用。"""
    url = _normalize_repo_url(url)
    logger.info("获取远程{}: {}", label, url)
    try:
        headers = {"User-Agent": "Campus-Auth"}
        async with httpx.AsyncClient(proxy=proxy or None, timeout=httpx.Timeout(15)) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, expected_type):
            type_name = "JSON 数组" if expected_type is list else "JSON 对象"
            raise HTTPException(
                status_code=422, detail=f"{label}格式不正确，应为 {type_name}"
            )
        logger.debug("远程{}获取成功", label)
        return data
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code if exc.response is not None else 502
        logger.warning("远程{}获取失败: HTTP {} ({})", label, status, url)
        raise HTTPException(
            status_code=status, detail=f"远程返回错误: {status} ({url})"
        ) from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("远程{}获取失败: {} ({})", label, exc, url)
        raise HTTPException(status_code=502, detail=f"获取{label}失败: {exc}") from exc
