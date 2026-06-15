"""端口解析工具测试 — 覆盖 resolve_port 所有分支。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

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


class TestResolvePortFromSettings:
    """从 config/settings.json 读取端口。"""

    @patch.dict("os.environ", {"APP_PORT": ""}, clear=False)
    @patch("app.utils.ports.PROJECT_ROOT")
    def test_valid_settings(self, mock_root, tmp_path):
        """settings.json 包含有效端口。"""
        settings_file = tmp_path / "config" / "settings.json"
        settings_file.parent.mkdir(parents=True, exist_ok=True)
        settings_file.write_text('{"global_settings": {"app_port": 9090}}', encoding="utf-8")

        mock_root.__truediv__ = lambda self, x: tmp_path / x
        assert resolve_port() == 9090

    @patch.dict("os.environ", {"APP_PORT": ""}, clear=False)
    @patch("app.utils.ports.PROJECT_ROOT")
    def test_settings_no_global_settings(self, mock_root, tmp_path):
        """settings.json 缺少 global_settings 字段。"""
        settings_file = tmp_path / "config" / "settings.json"
        settings_file.parent.mkdir(parents=True, exist_ok=True)
        settings_file.write_text('{"other": {}}', encoding="utf-8")

        mock_root.__truediv__ = lambda self, x: tmp_path / x
        assert resolve_port() == _DEFAULT_PORT

    @patch.dict("os.environ", {"APP_PORT": ""}, clear=False)
    @patch("app.utils.ports.PROJECT_ROOT")
    def test_settings_no_app_port(self, mock_root, tmp_path):
        """global_settings 中无 app_port。"""
        settings_file = tmp_path / "config" / "settings.json"
        settings_file.parent.mkdir(parents=True, exist_ok=True)
        settings_file.write_text('{"global_settings": {}}', encoding="utf-8")

        mock_root.__truediv__ = lambda self, x: tmp_path / x
        assert resolve_port() == _DEFAULT_PORT

    @patch.dict("os.environ", {"APP_PORT": ""}, clear=False)
    @patch("app.utils.ports.PROJECT_ROOT")
    def test_settings_invalid_port(self, mock_root, tmp_path):
        """settings.json 中端口无效。"""
        settings_file = tmp_path / "config" / "settings.json"
        settings_file.parent.mkdir(parents=True, exist_ok=True)
        settings_file.write_text('{"global_settings": {"app_port": 99999}}', encoding="utf-8")

        mock_root.__truediv__ = lambda self, x: tmp_path / x
        assert resolve_port() == _DEFAULT_PORT

    @patch.dict("os.environ", {"APP_PORT": ""}, clear=False)
    @patch("app.utils.ports.PROJECT_ROOT")
    def test_settings_non_numeric_port(self, mock_root, tmp_path):
        """settings.json 中端口非数字。"""
        settings_file = tmp_path / "config" / "settings.json"
        settings_file.parent.mkdir(parents=True, exist_ok=True)
        settings_file.write_text('{"global_settings": {"app_port": "abc"}}', encoding="utf-8")

        mock_root.__truediv__ = lambda self, x: tmp_path / x
        assert resolve_port() == _DEFAULT_PORT


class TestResolvePortSettingsErrors:
    """settings.json 文件级错误。"""

    @patch.dict("os.environ", {"APP_PORT": ""}, clear=False)
    @patch("app.utils.ports.PROJECT_ROOT")
    def test_settings_not_exists(self, mock_root, tmp_path):
        """settings.json 不存在。"""
        mock_root.__truediv__ = lambda self, x: tmp_path / x
        assert resolve_port() == _DEFAULT_PORT

    @patch.dict("os.environ", {"APP_PORT": ""}, clear=False)
    @patch("app.utils.ports.PROJECT_ROOT")
    def test_settings_malformed_json(self, mock_root, tmp_path):
        """settings.json 格式错误。"""
        settings_file = tmp_path / "config" / "settings.json"
        settings_file.parent.mkdir(parents=True, exist_ok=True)
        settings_file.write_text("not json", encoding="utf-8")

        mock_root.__truediv__ = lambda self, x: tmp_path / x
        assert resolve_port() == _DEFAULT_PORT


class TestResolvePortPriority:
    """优先级测试：环境变量 > settings.json。"""

    @patch.dict("os.environ", {"APP_PORT": "3000"}, clear=False)
    @patch("app.utils.ports.PROJECT_ROOT")
    def test_env_overrides_settings(self, mock_root, tmp_path):
        """环境变量优先于 settings.json。"""
        settings_file = tmp_path / "config" / "settings.json"
        settings_file.parent.mkdir(parents=True, exist_ok=True)
        settings_file.write_text('{"global_settings": {"app_port": 9090}}', encoding="utf-8")

        mock_root.__truediv__ = lambda self, x: tmp_path / x
        assert resolve_port() == 3000


class TestResolvePortDefault:
    """默认端口。"""

    @patch.dict("os.environ", {"APP_PORT": ""}, clear=False)
    @patch("app.utils.ports.PROJECT_ROOT")
    def test_default_port(self, mock_root, tmp_path):
        """无环境变量且无 settings.json 时返回默认端口。"""
        mock_root.__truediv__ = lambda self, x: tmp_path / x
        assert resolve_port() == _DEFAULT_PORT == 50721
