"""MonitorService._on_profile_switch 回调测试

验证自动切换方案回调使用 put_nowait 而非阻塞的 put，
避免监控线程被阻塞。
"""
from __future__ import annotations

import queue
from unittest.mock import MagicMock

import pytest

from app.services.monitor import MonitorCmdType, MonitorCommand, MonitorService


class TestOnProfileSwitchUsesPutNowait:
    """P1-SR-1: 确认 _on_profile_switch 使用 put_nowait 而非阻塞 put。"""

    def test_on_profile_switch_uses_put_nowait(self):
        """_on_profile_switch 应通过 put_nowait 入队命令，不阻塞调用线程。"""
        service = object.__new__(MonitorService)
        # 仅初始化 _on_profile_switch 所需的最小状态
        mock_queue = MagicMock(spec=queue.Queue)
        service._cmd_queue = mock_queue

        # 调用 _on_profile_switch
        service._on_profile_switch("TestProfile")

        # 验证使用 put_nowait 而非 put
        mock_queue.put_nowait.assert_called_once()
        cmd = mock_queue.put_nowait.call_args[0][0]
        assert isinstance(cmd, MonitorCommand)
        assert cmd.type == MonitorCmdType.PROFILE_RELOAD
        assert cmd.data["profile_name"] == "TestProfile"

        # 确保未调用阻塞的 put
        mock_queue.put.assert_not_called()

    def test_on_profile_switch_handles_queue_full(self):
        """队列已满时 _on_profile_switch 应静默处理，不抛异常。"""
        service = object.__new__(MonitorService)
        mock_queue = MagicMock(spec=queue.Queue)
        mock_queue.put_nowait.side_effect = queue.Full()
        service._cmd_queue = mock_queue

        # 不应抛出异常
        service._on_profile_switch("TestProfile")

        mock_queue.put_nowait.assert_called_once()
