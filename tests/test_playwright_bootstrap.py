"""Playwright bootstrap 状态管理测试"""
from __future__ import annotations

import threading
from unittest.mock import MagicMock, patch

import pytest

import app.workers.playwright_bootstrap as pb


class TestBootstrapState:
    """bootstrap 状态区分测试"""

    def setup_method(self):
        """每个测试前重置全局状态"""
        pb._BOOTSTRAP_DONE = False
        pb._BOOTSTRAP_SKIPPED = False

    def test_bootstrap_disabled_returns_skipped(self):
        """测试禁用 auto-install 时返回 SKIPPED 状态"""
        with patch.object(pb, '_is_enabled', return_value=False):
            result = pb.ensure_playwright_ready()

        assert result is True
        assert pb._BOOTSTRAP_SKIPPED is True
        assert pb._BOOTSTRAP_DONE is False

    def test_bootstrap_verified_returns_done(self):
        """测试 Chromium 已安装时返回 DONE 状态"""
        with patch.object(pb, '_is_enabled', return_value=True), \
             patch.object(pb, '_has_chromium', return_value=True):
            result = pb.ensure_playwright_ready()

        assert result is True
        assert pb._BOOTSTRAP_DONE is True
        assert pb._BOOTSTRAP_SKIPPED is False

    def test_bootstrap_skipped_then_done(self):
        """测试先跳过再验证的状态变化"""
        # 第一次：禁用
        with patch.object(pb, '_is_enabled', return_value=False):
            pb.ensure_playwright_ready()

        assert pb._BOOTSTRAP_SKIPPED is True
        assert pb._BOOTSTRAP_DONE is False

        # 第二次：仍然返回 True（因为 SKIPPED）
        with patch.object(pb, '_is_enabled', return_value=True), \
             patch.object(pb, '_has_chromium', return_value=True):
            result = pb.ensure_playwright_ready()

        # 由于 SKIPPED 为 True，第二次调用直接返回 True
        assert result is True
        # DONE 仍为 False（因为第二次调用被 SKIPPED 拦截）
        assert pb._BOOTSTRAP_DONE is False

    def test_is_bootstrap_skipped(self):
        """测试 is_bootstrap_skipped 查询函数"""
        assert pb.is_bootstrap_skipped() is False

        pb._BOOTSTRAP_SKIPPED = True
        assert pb.is_bootstrap_skipped() is True

    def test_is_bootstrap_done(self):
        """测试 is_bootstrap_done 查询函数"""
        assert pb.is_bootstrap_done() is False

        pb._BOOTSTRAP_DONE = True
        assert pb.is_bootstrap_done() is True
