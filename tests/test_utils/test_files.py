"""app/utils/files.py 测试

测试 save_screenshot 函数的 local_path 初始化修复，
以及 dir_size_mb 的 DirSizeResult 完整性标记。
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

# =====================================================================
# save_screenshot
# =====================================================================


class TestSaveScreenshot:
    """save_screenshot 函数测试。"""

    async def test_successful_screenshot(self, tmp_path):
        """正常截图应返回本地路径。"""
        from app.utils.files import save_screenshot

        mock_page = AsyncMock()
        mock_page.screenshot = AsyncMock()

        result = await save_screenshot(mock_page, tmp_path)

        assert result is not None
        assert result.endswith(".png")
        assert Path(result).parent == tmp_path
        mock_page.screenshot.assert_called_once()

    async def test_exception_before_local_path_assignment(self, tmp_path):
        """在 local_path 赋值前抛出异常，应返回 None 而非 UnboundLocalError。"""
        from app.utils.files import save_screenshot

        mock_page = AsyncMock()
        # 模拟 Path(output_dir) 抛出异常
        with patch("app.utils.files.Path", side_effect=OSError("disk error")):
            result = await save_screenshot(mock_page, tmp_path)

        assert result is None

    async def test_exception_during_mkdir(self, tmp_path):
        """mkdir 失败时应返回 None。"""
        from app.utils.files import save_screenshot

        mock_page = AsyncMock()
        mock_page.screenshot = AsyncMock()

        # 模拟 mkdir 抛出异常
        with patch(
            "app.utils.files.Path",
            side_effect=lambda p: MagicMock(
                mkdir=MagicMock(side_effect=OSError("permission denied"))
            ),
        ):
            result = await save_screenshot(mock_page, tmp_path)

        assert result is None

    async def test_exception_during_screenshot(self, tmp_path):
        """page.screenshot 失败时应返回 None。"""
        from app.utils.files import save_screenshot

        mock_page = AsyncMock()
        mock_page.screenshot = AsyncMock(side_effect=OSError("browser crashed"))

        result = await save_screenshot(mock_page, tmp_path)

        assert result is None

    async def test_creates_output_directory(self, tmp_path):
        """应自动创建输出目录。"""
        from app.utils.files import save_screenshot

        mock_page = AsyncMock()
        mock_page.screenshot = AsyncMock()
        output_dir = tmp_path / "nested" / "dir"

        result = await save_screenshot(mock_page, output_dir)

        assert result is not None
        assert output_dir.exists()

    async def test_custom_prefix(self, tmp_path):
        """自定义前缀应体现在文件名中。"""
        from app.utils.files import save_screenshot

        mock_page = AsyncMock()
        mock_page.screenshot = AsyncMock()

        result = await save_screenshot(mock_page, tmp_path, prefix="login")

        assert result is not None
        assert "login" in Path(result).name

    async def test_with_task_id_and_step_id(self, tmp_path):
        """task_id 和 step_id 应体现在文件名中。"""
        from app.utils.files import save_screenshot

        mock_page = AsyncMock()
        mock_page.screenshot = AsyncMock()

        result = await save_screenshot(
            mock_page, tmp_path, task_id="task1", step_id="step2"
        )

        assert result is not None
        filename = Path(result).name
        assert "task1" in filename
        assert "step2" in filename

    async def test_empty_output_dir_uses_current(self):
        """空字符串作为 output_dir 时，local_path 应为空字符串初始化。"""
        from app.utils.files import save_screenshot

        mock_page = AsyncMock()
        # 模拟 Path("") 抛出异常
        with patch("app.utils.files.Path", side_effect=ValueError("invalid path")):
            result = await save_screenshot(mock_page, "")

        assert result is None


# =====================================================================
# dir_size_mb / DirSizeResult
# =====================================================================


class TestDirSizeMb:
    """dir_size_mb 函数测试。"""

    def test_nonexistent_path_returns_zero_complete(self, tmp_path):
        """不存在的路径应返回 DirSizeResult(0.0, True)。"""
        from app.utils.files import DirSizeResult, dir_size_mb

        result = dir_size_mb(tmp_path / "nonexistent")
        assert isinstance(result, DirSizeResult)
        assert result.size_mb == 0.0
        assert result.complete is True

    def test_empty_dir(self, tmp_path):
        """空目录应返回 DirSizeResult(0.0, True)。"""
        from app.utils.files import DirSizeResult, dir_size_mb

        result = dir_size_mb(tmp_path)
        assert isinstance(result, DirSizeResult)
        assert result.size_mb == 0.0
        assert result.complete is True

    def test_file_path(self, tmp_path):
        """文件路径应返回该文件大小。"""
        from app.utils.files import DirSizeResult, dir_size_mb

        (tmp_path / "test.txt").write_bytes(b"x" * (1024 * 1024 + 1))
        result = dir_size_mb(tmp_path / "test.txt")
        assert isinstance(result, DirSizeResult)
        assert result.size_mb > 0
        assert result.complete is True

    def test_dir_with_files(self, tmp_path):
        """目录内有文件时应正确计算大小。"""
        from app.utils.files import DirSizeResult, dir_size_mb

        (tmp_path / "a.txt").write_bytes(b"x" * (1024 * 1024 + 1))
        (tmp_path / "b.txt").write_bytes(b"y" * (1024 * 1024 + 1))
        result = dir_size_mb(tmp_path)
        assert isinstance(result, DirSizeResult)
        assert result.size_mb > 0
        assert result.complete is True

    def test_nested_dirs(self, tmp_path):
        """嵌套目录应递归计算。"""
        from app.utils.files import DirSizeResult, dir_size_mb

        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "deep.txt").write_bytes(b"x" * (1024 * 1024 + 1))
        result = dir_size_mb(tmp_path)
        assert isinstance(result, DirSizeResult)
        assert result.size_mb > 0
        assert result.complete is True

    def test_oserror_marks_incomplete(self, tmp_path):
        """遍历过程中遇到 OSError 应标记 complete=False。"""
        from app.utils.files import dir_size_mb

        # 创建一个目录，在遍历时会触发 OSError
        target = tmp_path / "target"
        target.mkdir()
        (target / "ok.txt").write_bytes(b"data")

        original_rglob = type(target).rglob

        def patched_rglob(self, pattern):
            for item in original_rglob(self, pattern):
                if item.name == "ok.txt":
                    raise OSError("permission denied")
                yield item

        with patch.object(type(target), "rglob", patched_rglob):
            result = dir_size_mb(target)

        assert result.complete is False

    def test_string_path(self, tmp_path):
        """字符串路径参数应正常工作。"""
        from app.utils.files import DirSizeResult, dir_size_mb

        result = dir_size_mb(str(tmp_path))
        assert isinstance(result, DirSizeResult)
        assert result.size_mb == 0.0
        assert result.complete is True
