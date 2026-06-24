"""端口解析工具测试 — 覆盖 resolve_port 所有分支。"""

from __future__ import annotations

from unittest.mock import patch

from app.utils.ports import _DEFAULT_PORT, resolve_port


class TestResolvePortFromEnv:
    """从环境变量 APP_PORT 解析端口。"""

    @patch.dict("os.environ", {"APP_PORT": "8080"}, clear=False)
    def test_valid_port(self):
        """有效端口号。"""
        assert resolve_port() == 8080

    @patch.dict("os.environ", {"APP_PORT": "1"}, clear=False)
    def test_min_port(self):
        """最小有效端口 1。"""
        assert resolve_port() == 1

    @patch.dict("os.environ", {"APP_PORT": "65535"}, clear=False)
    def test_max_port(self):
        """最大有效端口 65535。"""
        assert resolve_port() == 65535

    @patch.dict("os.environ", {"APP_PORT": " 8080 "}, clear=False)
    def test_port_with_whitespace(self):
        """带空格的端口号。"""
        assert resolve_port() == 8080


class TestResolvePortEnvInvalid:
    """环境变量 APP_PORT 无效值。"""

    @patch.dict("os.environ", {"APP_PORT": "abc"}, clear=False)
    def test_non_numeric(self):
        """非数字值回退到默认。"""
        assert resolve_port() == _DEFAULT_PORT

    @patch.dict("os.environ", {"APP_PORT": "0"}, clear=False)
    def test_port_zero(self):
        """端口 0 超出范围，回退到默认。"""
        assert resolve_port() == _DEFAULT_PORT

    @patch.dict("os.environ", {"APP_PORT": "99999"}, clear=False)
    def test_port_over_max(self):
        """端口超出 65535，回退到默认。"""
        assert resolve_port() == _DEFAULT_PORT

    @patch.dict("os.environ", {"APP_PORT": "-1"}, clear=False)
    def test_negative_port(self):
        """负端口，回退到默认。"""
        assert resolve_port() == _DEFAULT_PORT

    @patch.dict("os.environ", {"APP_PORT": ""}, clear=False)
    def test_empty_string(self):
        """空字符串回退到默认。"""
        assert resolve_port() == _DEFAULT_PORT

    @patch.dict("os.environ", {"APP_PORT": "   "}, clear=False)
    def test_whitespace_only(self):
        """纯空格回退到默认。"""
        assert resolve_port() == _DEFAULT_PORT


class TestResolvePortDefault:
    """默认端口。"""

    @patch.dict("os.environ", {"APP_PORT": ""}, clear=False)
    def test_default_port(self):
        """无环境变量时返回默认端口。"""
        assert resolve_port() == _DEFAULT_PORT == 50721
