"""uninstall.py — 危险删除操作路径校验测试"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch


class TestRemoveUserDataSafety:
    """_remove_user_data 应校验路径，防止误删非预期目录"""

    def test_rejects_non_standard_directory_name(self):
        """当 AUTH_DATA_DIR 名称不是 .campus_network_auth 时应拒绝删除"""
        from app.services import uninstall

        fake_dir = Path("/tmp/evil_directory")
        with patch.object(uninstall, "AUTH_DATA_DIR", fake_dir):
            # 即使目录存在，名称不匹配也应拒绝
            with patch.object(Path, "exists", return_value=True):
                success, message = uninstall._remove_user_data()
                assert success is False
                assert "安全检查失败" in message
                assert ".campus_network_auth" in message

    def test_accepts_correct_directory_name(self):
        """当 AUTH_DATA_DIR 名称是 .campus_network_auth 时应允许删除"""
        from app.services import uninstall

        correct_dir = Path("/tmp/.campus_network_auth")
        with patch.object(uninstall, "AUTH_DATA_DIR", correct_dir):
            with patch.object(Path, "exists", return_value=True):
                # mock shutil.rmtree 避免真实删除
                with patch("app.services.uninstall.shutil.rmtree") as mock_rmtree:
                    success, message = uninstall._remove_user_data()
                    assert success is True
                    mock_rmtree.assert_called_once_with(correct_dir)

    def test_skips_when_directory_not_exists(self):
        """目录不存在时应跳过并返回成功"""
        from app.services import uninstall

        with patch.object(Path, "exists", return_value=False):
            success, message = uninstall._remove_user_data()
            assert success is True
            assert "跳过" in message

    def test_logs_before_deletion(self):
        """删除前应记录日志"""
        from app.services import uninstall

        correct_dir = Path("/tmp/.campus_network_auth")
        with patch.object(uninstall, "AUTH_DATA_DIR", correct_dir):
            with patch.object(Path, "exists", return_value=True):
                with patch("app.services.uninstall.shutil.rmtree"):
                    with patch("app.services.uninstall.logger") as mock_logger:
                        uninstall._remove_user_data()
                        mock_logger.info.assert_called_once()
                        # 日志中应包含目录路径
                        call_args = mock_logger.info.call_args
                        assert ".campus_network_auth" in str(call_args)
