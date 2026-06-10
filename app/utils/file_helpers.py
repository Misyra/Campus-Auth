import contextlib
import os
import tempfile
from datetime import datetime
from pathlib import Path

from .logging import get_logger

logger = get_logger("file_helpers", source="backend")


def atomic_write(
    path: str | Path,
    content: str,
    encoding: str = "utf-8",
    errors: str = "strict",
    prefix: str = "tmp.",
    suffix: str = ".tmp",
) -> None:
    """原子写入文件：先写临时文件，再 os.replace 原子替换目标路径。

    创建父目录（如果不存在），失败时清理临时文件。

    注意：当临时文件与目标路径不在同一文件系统时，os.replace 会抛出
    PermissionError 或 OSError，此时调用方应自行处理回退逻辑。因此本函数
    不保证在所有场景下都是原子的。

    Args:
        path: 目标文件路径
        content: 要写入的文本内容
        encoding: 文件编码（默认 utf-8）
        errors: 编码错误处理方式（默认 "strict"，可选 "replace" 等）
        prefix: 临时文件前缀（默认 "tmp."）
        suffix: 临时文件后缀（默认 ".tmp"）
    """
    if len(prefix) > 20 or len(suffix) > 20:
        raise ValueError("prefix/suffix 长度不能超过 20 字符")

    path = str(path)
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)

    tmp_fd, tmp_path = tempfile.mkstemp(
        dir=parent or None, prefix=prefix, suffix=suffix
    )
    try:
        with os.fdopen(tmp_fd, "w", encoding=encoding, errors=errors) as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())

        os.replace(tmp_path, path)
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
