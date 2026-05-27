import os
import tempfile

from src.utils.logging import get_logger

logger = get_logger("file_helpers", side="BACKEND")


def atomic_write(
    path: str,
    content: str,
    encoding: str = "utf-8",
    prefix: str = "tmp.",
    suffix: str = ".tmp",
) -> None:
    """原子写入文件：先写临时文件，再 os.replace 原子替换目标路径。

    创建父目录（如果不存在），失败时清理临时文件。
    当 os.replace 因权限错误失败时，回退到直接写入。

    Args:
        path: 目标文件路径
        content: 要写入的文本内容
        encoding: 文件编码（默认 utf-8）
        prefix: 临时文件前缀（默认 "tmp."）
        suffix: 临时文件后缀（默认 ".tmp"）
    """
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)

    tmp_fd, tmp_path = tempfile.mkstemp(
        dir=parent or None, prefix=prefix, suffix=suffix
    )
    try:
        with os.fdopen(tmp_fd, "w", encoding=encoding, errors="replace") as f:
            f.write(content)

        try:
            os.replace(tmp_path, path)
        except PermissionError:
            logger.warning(
                "os.replace 权限错误 (%s)，回退到直接写入", path
            )
            with open(path, "w", encoding=encoding, errors="replace") as f:
                f.write(content)
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
