"""仓库代理工具 — 远程 JSON 获取和 URL 规范化。

从 backend/main.py 提取，作为独立的工具模块。
"""

from __future__ import annotations

import re

import httpx
from fastapi import HTTPException

from .logging import get_logger

logger = get_logger("repo_proxy", source="backend")


def normalize_repo_url(url: str) -> str:
    """将 GitHub/Gitee 页面链接转换为 raw 链接，其他链接原样返回"""
    m = re.match(r"https?://github\.com/([^/]+)/([^/]+)/blob/([^/]+)/(.+)", url)
    if m:
        return f"https://raw.githubusercontent.com/{m.group(1)}/{m.group(2)}/{m.group(3)}/{m.group(4)}"
    m = re.match(r"https?://gitee\.com/([^/]+)/([^/]+)/blob/([^/]+)/(.+)", url)
    if m:
        return (
            f"https://gitee.com/{m.group(1)}/{m.group(2)}/raw/{m.group(3)}/{m.group(4)}"
        )
    return url


def repo_get(url: str, proxy: str = ""):
    """请求远程 JSON，使用配置的代理（如有）"""
    headers = {"User-Agent": "Campus-Auth"}

    with httpx.Client(proxy=proxy or None, timeout=httpx.Timeout(15)) as client:
        resp = client.get(url, headers=headers)
        resp.raise_for_status()
        return resp


def repo_fetch_json(url: str, expected_type: type, label: str, proxy: str = ""):
    """通用的远程 JSON 获取：校验类型 + 统一异常处理。"""
    url = normalize_repo_url(url)
    logger.info("获取远程{}: {}", label, url)
    try:
        resp = repo_get(url, proxy=proxy)
        data = resp.json()
        if not isinstance(data, expected_type):
            type_name = "JSON 数组" if expected_type is list else "JSON 对象"
            raise HTTPException(
                status_code=422, detail=f"{label}格式不正确，应为 {type_name}"
            )
        logger.info("远程{}获取成功", label)
        return data
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code if exc.response is not None else 502
        logger.error("远程{}获取失败: HTTP {} ({})", label, status, url)
        raise HTTPException(
            status_code=status, detail=f"远程返回错误: {status} ({url})"
        ) from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("远程{}获取失败: {} ({})", label, exc, url)
        raise HTTPException(status_code=502, detail=f"获取{label}失败: {exc}") from exc
