#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Campus-Auth 卸载脚本

清理项目在系统中留下的外部残留：
- 运行中的进程
- 开机自启配置
- 用户数据目录（加密密钥、PID 文件）
- Playwright 浏览器缓存（可选）

最后提示用户手动删除项目目录。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from backend.uninstall_service import CleanupItem, detect, perform

PROJECT_ROOT = Path(__file__).parent.resolve()
PLATFORM = sys.platform


def _print_header():
    print()
    print("=" * 40)
    print("  Campus-Auth 卸载程序")
    print("=" * 40)
    print()


def _prompt_select(items: list[CleanupItem]) -> set[str]:
    """让用户选择要保留的项目编号，回车表示全部清理。"""
    print("输入要保留的项目编号（如 4），多个用逗号分隔。")
    print("直接回车表示全部清理：")
    print()
    raw = input("> ").strip()
    if not raw:
        return set()
    keep_indices = set()
    for part in raw.split(","):
        part = part.strip()
        if part.isdigit():
            keep_indices.add(int(part))
    # 将编号转为 key
    keep_keys = set()
    for idx in keep_indices:
        if 1 <= idx <= len(items):
            keep_keys.add(items[idx - 1].key)
    return keep_keys


def main():
    _print_header()

    # --- 检测 ---
    items = detect()
    active = [it for it in items if it.exists]
    inactive = [it for it in items if not it.exists]

    if not active:
        print("未检测到任何外部残留，无需清理。")
        print(f"\n请手动删除项目目录：{PROJECT_ROOT}")
        return

    for i, it in enumerate(active, 1):
        extra = ""
        if it.key == "playwright" and it.size_mb > 0:
            extra = f" — 约 {it.size_mb:.0f} MB"
        if it.path:
            print(f"  [{i}] {it.label} ({it.path}){extra}")
        else:
            print(f"  [{i}] {it.label}")
    for it in inactive:
        print(f"  [ ] {it.label}（未检测到）")
    print()

    keep = _prompt_select(active)
    keys_to_clean = [it.key for it in active if it.key not in keep]

    if not keys_to_clean:
        print("没有执行任何清理操作。")
        print(f"\n请手动删除项目目录：{PROJECT_ROOT}")
        return

    # --- 执行 ---
    results = perform(keys_to_clean)

    # --- 汇总 ---
    print()
    print("-" * 40)
    for r in results:
        icon = "OK" if r.success else "FAIL"
        print(f"  [{icon}] {r.label}: {r.message}")

    print()
    print("请手动删除项目目录：")
    print(f"  {PROJECT_ROOT}")
    print()
    if PLATFORM == "win32":
        print("在文件管理器中删除，或在终端执行：")
        print(f'  rmdir /s /q "{PROJECT_ROOT}"')
    else:
        print("在终端执行：")
        print(f'  rm -rf "{PROJECT_ROOT}"')
    print()


if __name__ == "__main__":
    main()
