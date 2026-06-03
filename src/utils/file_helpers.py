import os
import tempfile

from src.utils.logging import get_logger

logger = get_logger("file_helpers", side="BACKEND")


def atomic_write(
    path: str,
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
    if len(prefix) > 5 or len(suffix) > 5:
        raise ValueError("prefix/suffix 长度不能超过 5 字符")

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
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
