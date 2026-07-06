"""统一的项目版本读取工具。"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path


def get_project_version(project_root: Path | None = None) -> str:
    """从 pyproject.toml 读取项目版本，读取失败时返回 unknown。

    使用 Python 3.11+ 标准库 tomllib 解析 TOML，
    替代旧的正则逐行扫描方式，确保对所有合法 TOML 语法正确。
    """
    root = project_root or Path(__file__).resolve().parents[1]
    pyproject = root / "pyproject.toml"
    try:
        text = pyproject.read_text(encoding="utf-8")
        data = tomllib.loads(text)
        return data.get("project", {}).get("version", "unknown")
    except (OSError, tomllib.TOMLDecodeError):
        return "unknown"


def _parse_version_segment(seg: str) -> int:
    """解析版本号片段，去掉预发布后缀（如 3-beta1 → 3）。"""
    return int(re.split(r"[-+]", seg, maxsplit=1)[0])


def compare_versions(a: str, b: str) -> int:
    """比较语义版本号，a > b 返回 1，a < b 返回 -1，相等时返回 0"""
    try:
        va = [_parse_version_segment(x) for x in a.split(".")]
        vb = [_parse_version_segment(x) for x in b.split(".")]
        # 补齐较短版本号的缺失段为 0
        max_len = max(len(va), len(vb))
        va.extend([0] * (max_len - len(va)))
        vb.extend([0] * (max_len - len(vb)))
        for x, y in zip(va, vb, strict=False):
            if x > y:
                return 1
            if x < y:
                return -1
        return 0
    except (ValueError, AttributeError):
        return 0
