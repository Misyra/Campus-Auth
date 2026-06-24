import contextlib
import os
import tempfile
import time
from datetime import datetime
from pathlib import Path

from .logging import get_logger

logger = get_logger("files", source="backend")


def atomic_write(
    path: str | Path,
    content: str,
    encoding: str = "utf-8",
    errors: str = "strict",
    prefix: str = "tmp.",
    suffix: str = ".tmp",
) -> None:
    """原子写入文件：先写临时文件，再 os.replace 原子替换目标路径。

    临时文件始终在目标文件所在目录创建，确保 os.replace 在同一文件系统内操作。
    创建父目录（如果不存在），失败时清理临时文件。

    Args:
        path: 目标文件路径
        content: 要写入的文本内容
        encoding: 文件编码（默认 utf-8）
        errors: 编码错误处理方式（默认 "strict"，可选 "replace" 等）
        prefix: 临时文件前缀（默认 "tmp."）
        suffix: 临时文件后缀（默认 ".tmp"）
    """
    path = str(path)
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)

    tmp_fd, tmp_path = tempfile.mkstemp(
        dir=parent or ".", prefix=prefix, suffix=suffix
    )
    try:
        try:
            f = os.fdopen(tmp_fd, "w", encoding=encoding, errors=errors)
        except Exception:
            os.close(tmp_fd)
            raise
        with f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())

        # BUG-066 修复：Windows 上添加重试逻辑，处理文件锁定
        for attempt in range(3):
            try:
                os.replace(tmp_path, path)
                break
            except PermissionError:
                if attempt < 2:
                    time.sleep(0.1)
                else:
                    raise
    except Exception:
        with contextlib.suppress(OSError):
            os.unlink(tmp_path)
        raise


async def save_screenshot(
    page,
    output_dir: Path | str,
    prefix: str = "screenshot",
    task_id: str = "",
    step_id: str = "",
) -> str | None:
    """统一的页面截图保存函数。

    参数:
        page: Playwright Page 对象
        output_dir: 截图输出目录
        prefix: 文件名前缀
        task_id: 任务 ID（可选）
        step_id: 步骤 ID（可选）

    返回:
        截图文件的本地路径，失败时返回 None
    """
    try:
        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        parts = [p for p in (prefix, task_id, step_id, stamp) if p]
        filename = "_".join(parts) + ".png"
        local_path = str(out_dir / filename)

        await page.screenshot(path=local_path, full_page=True)
        return local_path
    except Exception as e:
        logger.warning("截图保存失败: {}", e)
        return None


def dir_size_mb(path: Path | str) -> float:
    """递归计算目录或文件的磁盘占用（MB）。

    使用 rglob + stat 遍历所有文件，累加大小后转换为 MB。
    OSError（权限不足等）的文件会被跳过。

    Args:
        path: 目录或文件路径。

    Returns:
        占用大小（MB），保留 1 位小数。路径不存在时返回 0.0。
    """
    p = Path(path)
    if not p.exists():
        return 0.0
    if p.is_file():
        return round(p.stat().st_size / (1024 * 1024), 1)

    total = 0
    try:
        for f in p.rglob("*"):
            if f.is_file():
                total += f.stat().st_size
    except OSError:
        pass
    return round(total / (1024 * 1024), 1)
