"""统一的项目版本读取工具。"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

_VERSION_PATTERN = re.compile(r'^version\s*=\s*"([^\"]+)"\s*$')


@lru_cache(maxsize=1)
def get_project_version(project_root: Path | None = None) -> str:
    """从 pyproject.toml 读取项目版本，读取失败时返回 unknown。"""
    root = project_root or Path(__file__).resolve().parents[1]
    pyproject = root / "pyproject.toml"
    try:
        lines = pyproject.read_text(encoding="utf-8").splitlines()
    except OSError:
        return "unknown"

    in_project_block = False
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        if line.startswith("["):
            in_project_block = line == "[project]"
            continue
        if not in_project_block:
            continue

        match = _VERSION_PATTERN.match(line)
        if match:
            return match.group(1)

    return "unknown"


def compare_versions(a: str, b: str) -> int:
    """比较语义版本号，a > b 返回 1，a < b 返回 -1，相等时返回 0"""
    try:
        va = [int(x) for x in a.split(".")]
        vb = [int(x) for x in b.split(".")]
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
