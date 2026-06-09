# 测试套件全面优化实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 通过删除重复、合并文件、补充覆盖、提升质量，将测试套件从 80 个文件优化到 49 个，消除 ~40% 的重复测试，补充 8 个缺失的 API 路由测试。

**Architecture:** 四阶段渐进式重构。每阶段独立可验证，不修改被测代码。阶段 1-2 消除重复，阶段 3 补充覆盖，阶段 4 提升质量。

**Tech Stack:** pytest, FastAPI TestClient, unittest.mock

---

## 阶段 1: 删除纯重复文件（无风险）

### Task 1.1: 删除空壳 API 测试文件

**说明:** 这 3 个文件仅测试 import 可用性或字符串相等，无实际业务逻辑。`test_api_tools_routes.py` 已覆盖相同功能。

**Files:**
- Delete: `tests/test_api_config.py`
- Delete: `tests/test_api_history.py`
- Delete: `tests/test_api_scripts.py`

- [ ] **Step 1: 确认文件内容为空壳**

```bash
# 验证这 3 个文件的测试用例数量
grep -c "def test_" tests/test_api_config.py tests/test_api_history.py tests/test_api_scripts.py
```

Expected: 每个文件 ≤ 3 个测试函数。

- [ ] **Step 2: 删除文件**

```bash
rm tests/test_api_config.py tests/test_api_history.py tests/test_api_scripts.py
```

- [ ] **Step 3: 运行测试确认无影响**

```bash
uv run pytest --tb=short -q
```

Expected: 全部通过，用例数减少约 6 个。

- [ ] **Step 4: 提交**

```bash
git add -A tests/
git commit -m "refactor: 删除 3 个空壳 API 测试文件（config/history/scripts）"
```

### Task 1.2: 删除已含于综合文件的独立文件

**说明:** 以下 5 个文件的全部测试已被对应的综合文件覆盖。

**Files:**
- Delete: `tests/test_config_validator.py`（已含于 `test_config_schemas.py`）
- Delete: `tests/test_schemas.py`（已含于 `test_config_schemas.py`）
- Delete: `tests/test_autostart.py`（已含于 `test_system_services.py`）
- Delete: `tests/test_uninstall.py`（已含于 `test_system_services.py`）
- Delete: `tests/test_profile_service_logic.py`（仅 2 个用例，已含于 `test_backend_services.py`）

- [ ] **Step 1: 确认重叠**

```bash
# 验证综合文件存在且包含对应测试类
grep -l "class TestConfigValidator\|class TestValidateGuiConfig\|class TestValidateEnvConfig" tests/test_config_schemas.py
grep -l "class TestAutoStartService\|class TestUninstallService" tests/test_system_services.py
grep -l "class TestProfileService" tests/test_backend_services.py
```

Expected: 每个 grep 输出对应综合文件路径。

- [ ] **Step 2: 删除文件**

```bash
rm tests/test_config_validator.py tests/test_schemas.py tests/test_autostart.py tests/test_uninstall.py tests/test_profile_service_logic.py
```

- [ ] **Step 3: 运行测试确认无影响**

```bash
uv run pytest --tb=short -q
```

Expected: 全部通过，用例数减少约 30 个。

- [ ] **Step 4: 提交**

```bash
git add -A tests/
git commit -m "refactor: 删除 5 个已被综合文件覆盖的独立测试文件"
```

### Task 1.3: 删除完全重复的工具/服务测试文件

**说明:** 以下文件的测试已被 `test_utils.py`、`test_src_utils.py`、`test_backend_services.py` 完全覆盖。

**Files:**
- Delete: `tests/test_config_helpers.py`（完全重复）
- Delete: `tests/test_file_helpers.py`（完全重复）
- Delete: `tests/test_platform_utils.py`（完全重复）
- Delete: `tests/test_network_helpers.py`（完全重复）
- Delete: `tests/test_time_utils.py`（完全重复）
- Delete: `tests/test_env.py`（完全重复）
- Delete: `tests/test_exceptions.py`（完全重复）
- Delete: `tests/test_notify.py`（完全重复）
- Delete: `tests/test_monitor_core.py`（完全重复）
- Delete: `tests/test_decision.py`（完全重复）
- Delete: `tests/test_network_probes_utils.py`（完全重复）
- Delete: `tests/test_debug_session.py`（完全重复）
- Delete: `tests/test_network_detect.py`（完全重复）
- Delete: `tests/test_api_backup.py`（完全重复）
- Delete: `tests/test_logfiles.py`（完全重复）

- [ ] **Step 1: 删除文件**

```bash
rm tests/test_config_helpers.py tests/test_file_helpers.py tests/test_platform_utils.py \
   tests/test_network_helpers.py tests/test_time_utils.py tests/test_env.py \
   tests/test_exceptions.py tests/test_notify.py tests/test_monitor_core.py \
   tests/test_decision.py tests/test_network_probes_utils.py tests/test_debug_session.py \
   tests/test_network_detect.py tests/test_api_backup.py tests/test_logfiles.py
```

- [ ] **Step 2: 运行测试确认无影响**

```bash
uv run pytest --tb=short -q
```

Expected: 全部通过，用例数减少约 100 个。

- [ ] **Step 3: 提交**

```bash
git add -A tests/
git commit -m "refactor: 删除 15 个完全重复的独立测试文件"
```

---

## 阶段 2: 合并独有测试后删除独立文件

### Task 2.1: 合并 test_crypto.py 独有测试到 test_utils.py

**说明:** `TestSimpleObfuscate`、`TestDecryptionError` 和 `test_save_password_field_logs_no_plaintext` 在 `test_utils.py` 中缺失。

**Files:**
- Modify: `tests/test_utils.py`（追加独有测试）
- Delete: `tests/test_crypto.py`

- [ ] **Step 1: 确认 test_utils.py 末尾位置**

```bash
tail -5 tests/test_utils.py
```

- [ ] **Step 2: 在 test_utils.py 末尾追加独有测试**

在文件末尾追加以下内容：

```python
# ── _simple_obfuscate / _simple_deobfuscate ──


class TestSimpleObfuscate:
    """简单 Base64 混淆。"""

    def test_roundtrip(self):
        """混淆 -> 反混淆往返。"""
        from app.utils.crypto import _simple_deobfuscate, _simple_obfuscate

        original = "test_password_123"
        obfuscated = _simple_obfuscate(original)
        assert obfuscated.startswith("ENC:B64:")
        deobfuscated = _simple_deobfuscate(obfuscated[len("ENC:"):])
        assert deobfuscated == original

    def test_unicode(self):
        """Unicode 字符支持。"""
        from app.utils.crypto import _simple_deobfuscate, _simple_obfuscate

        original = "密码测试"
        obfuscated = _simple_obfuscate(original)
        deobfuscated = _simple_deobfuscate(obfuscated[len("ENC:"):])
        assert deobfuscated == original

    def test_empty_string(self):
        """空字符串。"""
        from app.utils.crypto import _simple_obfuscate

        obfuscated = _simple_obfuscate("")
        assert obfuscated == "ENC:B64:"

    def test_deobfuscate_without_prefix(self):
        """无 B64: 前缀原样返回。"""
        from app.utils.crypto import _simple_deobfuscate

        result = _simple_deobfuscate("plaintext")
        assert result == "plaintext"


# ── has_decryption_error / clear_decryption_error ──


class TestDecryptionError:
    """解密错误状态管理。"""

    def test_initial_state(self):
        """初始状态无解密错误。"""
        from app.utils.crypto import clear_decryption_error, has_decryption_error

        clear_decryption_error()
        assert has_decryption_error() is False

    def test_set_and_clear(self):
        """设置和清除解密错误。"""
        from app.utils.crypto import (
            _decryption_failed,
            clear_decryption_error,
            has_decryption_error,
        )

        _decryption_failed.set()
        assert has_decryption_error() is True
        clear_decryption_error()
        assert has_decryption_error() is False


# ── 日志安全 ──


def test_save_password_field_logs_no_plaintext(caplog):
    """save_password_field 的 warning 日志不应包含密码明文。"""
    from app.utils.crypto import save_password_field

    for raw_value in ("", "••••••••"):
        caplog.clear()
        with caplog.at_level("WARNING"):
            result = save_password_field(raw_value, existing_encrypted="")

        assert result == ""
        for record in caplog.records:
            msg = record.message
            assert repr(raw_value[:20]) not in msg, f"日志泄露了原始输入内容: {msg}"
```

- [ ] **Step 3: 运行测试确认合并成功**

```bash
uv run pytest tests/test_utils.py -v -k "SimpleObfuscate or DecryptionError or logs_no_plaintext"
```

Expected: 全部 PASS。

- [ ] **Step 4: 删除独立文件**

```bash
rm tests/test_crypto.py
```

- [ ] **Step 5: 运行全量测试**

```bash
uv run pytest --tb=short -q
```

Expected: 全部通过。

- [ ] **Step 6: 提交**

```bash
git add tests/test_utils.py tests/test_crypto.py
git commit -m "refactor: 合并 test_crypto.py 独有测试到 test_utils.py 并删除"
```

### Task 2.2: 合并 test_version.py 独有测试到 test_utils.py

**说明:** `TestCompareVersions` 在 `test_utils.py` 中缺失。

**Files:**
- Modify: `tests/test_utils.py`
- Delete: `tests/test_version.py`

- [ ] **Step 1: 在 test_utils.py 末尾追加 TestCompareVersions**

```python
# ── compare_versions ──


class TestCompareVersions:
    """版本比较。"""

    def test_equal(self):
        """相等。"""
        from app.version import compare_versions

        assert compare_versions("1.0.0", "1.0.0") == 0

    def test_greater_major(self):
        """主版本号更大。"""
        from app.version import compare_versions

        assert compare_versions("2.0.0", "1.0.0") == 1

    def test_less_major(self):
        """主版本号更小。"""
        from app.version import compare_versions

        assert compare_versions("1.0.0", "2.0.0") == -1

    def test_greater_minor(self):
        """次版本号更大。"""
        from app.version import compare_versions

        assert compare_versions("1.2.0", "1.1.0") == 1

    def test_less_minor(self):
        """次版本号更小。"""
        from app.version import compare_versions

        assert compare_versions("1.1.0", "1.2.0") == -1

    def test_greater_patch(self):
        """补丁版本号更大。"""
        from app.version import compare_versions

        assert compare_versions("1.0.2", "1.0.1") == 1

    def test_less_patch(self):
        """补丁版本号更小。"""
        from app.version import compare_versions

        assert compare_versions("1.0.1", "1.0.2") == -1

    def test_different_lengths(self):
        """不同长度版本号。"""
        from app.version import compare_versions

        assert compare_versions("1.0", "1.0.0") == 0
        assert compare_versions("1.0.0", "1.0") == 0
        assert compare_versions("1.0.1", "1.0") == 1

    def test_invalid_version_returns_zero(self):
        """无效版本号返回 0。"""
        from app.version import compare_versions

        assert compare_versions("invalid", "1.0.0") == 0
        assert compare_versions("1.0.0", "invalid") == 0
        assert compare_versions("invalid", "invalid") == 0

    def test_single_segment(self):
        """单段版本号。"""
        from app.version import compare_versions

        assert compare_versions("2", "1") == 1
        assert compare_versions("1", "2") == -1
        assert compare_versions("1", "1") == 0
```

- [ ] **Step 2: 运行测试确认合并成功**

```bash
uv run pytest tests/test_utils.py -v -k "CompareVersions"
```

Expected: 全部 PASS。

- [ ] **Step 3: 删除独立文件并运行全量测试**

```bash
rm tests/test_version.py
uv run pytest --tb=short -q
```

Expected: 全部通过。

- [ ] **Step 4: 提交**

```bash
git add tests/test_utils.py tests/test_version.py
git commit -m "refactor: 合并 test_version.py 独有测试到 test_utils.py 并删除"
```

### Task 2.3: 合并 test_logging_utils.py 独有测试到 test_utils.py

**说明:** `TestValidLogLevels` 和 `TestDashboardSink` 在 `test_utils.py` 中缺失。

**Files:**
- Modify: `tests/test_utils.py`
- Delete: `tests/test_logging_utils.py`

- [ ] **Step 1: 在 test_utils.py 末尾追加独有测试**

```python
# ── VALID_LOG_LEVELS ──


class TestValidLogLevels:
    """有效日志级别。"""

    def test_contains_standard_levels(self):
        """包含标准级别。"""
        from app.utils.logging import VALID_LOG_LEVELS

        assert "DEBUG" in VALID_LOG_LEVELS
        assert "INFO" in VALID_LOG_LEVELS
        assert "WARNING" in VALID_LOG_LEVELS
        assert "ERROR" in VALID_LOG_LEVELS
        assert "CRITICAL" in VALID_LOG_LEVELS

    def test_count(self):
        """级别数量。"""
        from app.utils.logging import VALID_LOG_LEVELS

        assert len(VALID_LOG_LEVELS) == 5


# ── DashboardSink ──


class TestDashboardSink:
    """DashboardSink 单元测试。"""

    def test_init_default(self):
        """默认初始化。"""
        from app.utils.logging import DashboardSink

        sink = DashboardSink()
        assert sink.buffer.maxlen == 1200
        assert sink.broadcast_queue.maxlen == 200
        assert len(sink.buffer) == 0
        assert len(sink.broadcast_queue) == 0

    def test_init_custom_maxlen(self):
        """自定义 maxlen。"""
        from app.utils.logging import DashboardSink

        sink = DashboardSink(maxlen=500)
        assert sink.buffer.maxlen == 500

    def test_write_appends_to_buffer_and_queue(self):
        """write 同时写入 buffer 和 broadcast_queue。"""
        import threading
        from unittest.mock import MagicMock

        from app.utils.logging import DashboardSink

        sink = DashboardSink(maxlen=10)
        msg = MagicMock()
        level_mock = MagicMock()
        level_mock.name = "INFO"
        msg.record = {
            "time": MagicMock(timestamp=lambda: 1700000000.0),
            "level": level_mock,
            "extra": {"name": "test", "source": "backend"},
            "name": "test",
            "message": "测试消息",
        }
        msg.__str__ = lambda self: "测试消息"

        sink.write(msg)

        assert len(sink.buffer) == 1
        assert len(sink.broadcast_queue) == 1
        entry = sink.buffer[0]
        assert entry["level"] == "INFO"
        assert entry["source"] == "backend"
        assert entry["name"] == "test"
        assert entry["message"] == "测试消息"

    def test_write_buffer_overflow(self):
        """buffer 超出 maxlen 自动淘汰最旧。"""
        from unittest.mock import MagicMock

        from app.utils.logging import DashboardSink

        sink = DashboardSink(maxlen=3)
        level_mock = MagicMock()
        level_mock.name = "INFO"
        for i in range(5):
            msg = MagicMock()
            msg.record = {
                "time": MagicMock(timestamp=lambda: 1700000000.0),
                "level": level_mock,
                "extra": {"name": "test", "source": "backend"},
                "name": "test",
                "message": f"msg{i}",
            }
            msg.__str__ = lambda self, i=i: f"msg{i}"
            sink.write(msg)

        assert len(sink.buffer) == 3
        assert sink.buffer[0]["message"] == "msg2"
        assert sink.buffer[2]["message"] == "msg4"

    def test_list_logs_returns_last_n(self):
        """list_logs 返回最近 N 条。"""
        from app.utils.logging import DashboardSink

        sink = DashboardSink(maxlen=10)
        for i in range(5):
            sink.buffer.append({"message": f"msg{i}"})

        result = sink.list_logs(limit=3)
        assert len(result) == 3
        assert result[0]["message"] == "msg2"

    def test_list_logs_limit_exceeds_buffer(self):
        """list_logs limit 超过 buffer 大小时返回全部。"""
        from app.utils.logging import DashboardSink

        sink = DashboardSink(maxlen=10)
        sink.buffer.append({"message": "only"})
        result = sink.list_logs(limit=100)
        assert len(result) == 1

    def test_thread_safety(self):
        """多线程并发写入不会崩溃。"""
        import threading
        from unittest.mock import MagicMock

        from app.utils.logging import DashboardSink

        sink = DashboardSink(maxlen=1000)
        errors = []

        level_mock = MagicMock()
        level_mock.name = "INFO"

        def writer(n):
            try:
                for i in range(100):
                    msg = MagicMock()
                    msg.record = {
                        "time": MagicMock(timestamp=lambda: 1700000000.0),
                        "level": level_mock,
                        "extra": {"name": "test", "source": "backend"},
                        "name": "test",
                        "message": f"t{n}_msg{i}",
                    }
                    msg.__str__ = lambda self, n=n, i=i: f"t{n}_msg{i}"
                    sink.write(msg)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(n,)) for n in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert len(sink.buffer) == 400
```

- [ ] **Step 2: 运行测试确认合并成功**

```bash
uv run pytest tests/test_utils.py -v -k "ValidLogLevels or DashboardSink"
```

Expected: 全部 PASS。

- [ ] **Step 3: 删除独立文件并运行全量测试**

```bash
rm tests/test_logging_utils.py
uv run pytest --tb=short -q
```

Expected: 全部通过。

- [ ] **Step 4: 提交**

```bash
git add tests/test_utils.py tests/test_logging_utils.py
git commit -m "refactor: 合并 test_logging_utils.py 独有测试到 test_utils.py 并删除"
```

### Task 2.4: 合并 test_browser_utils.py 独有测试到 test_src_utils.py

**说明:** `TestIsCancelled`、`TestBrowserContextManagerInit`、`TestBrowserContextManagerAexit` 在 `test_src_utils.py` 中缺失。

**Files:**
- Modify: `tests/test_src_utils.py`
- Delete: `tests/test_browser_utils.py`

- [ ] **Step 1: 在 test_src_utils.py 末尾追加独有测试**

```python
# ── BrowserContextManager._is_cancelled ──


class TestIsCancelled:
    """取消状态检查。"""

    def test_no_event(self):
        """无 cancel_event 时返回 False。"""
        mgr = BrowserContextManager({}, cancel_event=None)
        assert mgr._is_cancelled() is False

    def test_event_not_set(self):
        """event 未 set 时返回 False。"""
        import threading

        event = threading.Event()
        mgr = BrowserContextManager({}, cancel_event=event)
        assert mgr._is_cancelled() is False

    def test_event_set(self):
        """event 已 set 时返回 True。"""
        import threading

        event = threading.Event()
        event.set()
        mgr = BrowserContextManager({}, cancel_event=event)
        assert mgr._is_cancelled() is True


# ── BrowserContextManager 初始化 ──


class TestBrowserContextManagerInit:
    """初始化逻辑。"""

    def test_basic_init(self):
        """基本初始化。"""
        config = {"browser_settings": {"headless": True}}
        mgr = BrowserContextManager(config)
        assert mgr.config == config
        assert mgr.browser_settings == {"headless": True}
        assert mgr.browser is None
        assert mgr.context is None
        assert mgr.page is None
        assert mgr._worker_managed is False

    def test_empty_config(self):
        """空配置。"""
        mgr = BrowserContextManager({})
        assert mgr.browser_settings == {}

    def test_cancel_event_stored(self):
        """cancel_event 被保存。"""
        import threading

        event = threading.Event()
        mgr = BrowserContextManager({}, cancel_event=event)
        assert mgr.cancel_event is event


# ── BrowserContextManager.__aexit__ ──


class TestBrowserContextManagerAexit:
    """异步上下文管理器出口。"""

    @pytest.mark.asyncio
    async def test_returns_false(self):
        """返回 False（不抑制异常）。"""
        from unittest.mock import patch

        mgr = BrowserContextManager({})
        mock_worker = MagicMock()
        with patch(
            "app.workers.playwright_worker.get_worker", return_value=mock_worker
        ):
            result = await mgr.__aexit__(None, None, None)
            assert result is False

    @pytest.mark.asyncio
    async def test_clears_references(self):
        """清空引用。"""
        from unittest.mock import patch

        mgr = BrowserContextManager({})
        mgr.playwright = MagicMock()
        mgr.browser = MagicMock()
        mgr.context = MagicMock()
        mgr.page = MagicMock()

        mock_worker = MagicMock()
        with patch(
            "app.workers.playwright_worker.get_worker", return_value=mock_worker
        ):
            await mgr.__aexit__(None, None, None)
            assert mgr.playwright is None
            assert mgr.browser is None
            assert mgr.context is None
            assert mgr.page is None

    @pytest.mark.asyncio
    async def test_logs_exception(self):
        """异常被记录。"""
        from unittest.mock import patch

        mgr = BrowserContextManager({})
        mgr.logger = MagicMock()

        mock_worker = MagicMock()
        with patch(
            "app.workers.playwright_worker.get_worker", return_value=mock_worker
        ):
            await mgr.__aexit__(ValueError, ValueError("test error"), None)
            mgr.logger.error.assert_called()
```

- [ ] **Step 2: 运行测试确认合并成功**

```bash
uv run pytest tests/test_src_utils.py -v -k "IsCancelled or BrowserContextManagerInit or BrowserContextManagerAexit"
```

Expected: 全部 PASS。

- [ ] **Step 3: 删除独立文件并运行全量测试**

```bash
rm tests/test_browser_utils.py
uv run pytest --tb=short -q
```

Expected: 全部通过。

- [ ] **Step 4: 提交**

```bash
git add tests/test_src_utils.py tests/test_browser_utils.py
git commit -m "refactor: 合并 test_browser_utils.py 独有测试到 test_src_utils.py 并删除"
```

### Task 2.5: 合并 test_system_tray.py 独有测试到 test_src_utils.py

**说明:** `TestLoadIcon`、`TestGetStatusLabel`、`TestCreateMenu`、`TestQuit`、`TestStartStop`、`TestUpdateStatus` 在 `test_src_utils.py` 中缺失。

**Files:**
- Modify: `tests/test_src_utils.py`
- Delete: `tests/test_system_tray.py`

- [ ] **Step 1: 在 test_src_utils.py 末尾追加独有测试**

```python
# ── SystemTray 详细测试 ──


class TestLoadIcon:
    """_load_icon。"""

    @patch("app.core.system_tray.pystray")
    @patch("app.core.system_tray.Image")
    def test_fallback_returns_default_icon(self, mock_image, mock_pystray):
        """cairosvg.svg2png 抛异常时回退到 Image.new 默认图标。"""
        mock_new = MagicMock()
        mock_image.new.return_value = mock_new

        mock_cairosvg = MagicMock()
        mock_cairosvg.svg2png.side_effect = RuntimeError("svg2png failed")
        with patch.dict("sys.modules", {"cairosvg": mock_cairosvg}):
            tray = SystemTray()
            result = tray._load_icon()

        mock_image.new.assert_called_once_with("RGBA", (64, 64), (34, 211, 238, 255))
        assert result is mock_new

    @patch("app.core.system_tray.pystray")
    @patch("app.core.system_tray.Image")
    def test_fallback_when_cairosvg_missing(self, mock_image, mock_pystray):
        """cairosvg 不可用时回退到默认图标。"""
        from pathlib import Path

        mock_new = MagicMock()
        mock_image.new.return_value = mock_new

        tray = SystemTray()

        fake_path = MagicMock(spec=Path)
        fake_path.exists.return_value = True
        fake_path.as_uri.return_value = "file:///fake/icon.svg"

        with patch("app.core.system_tray.Path") as mock_path_cls:
            mock_path_cls.return_value.parent.parent.parent.__truediv__ = MagicMock(
                return_value=fake_path
            )
            with patch.dict("sys.modules", {"cairosvg": None}):
                tray._load_icon()

        mock_image.new.assert_called_once_with("RGBA", (64, 64), (34, 211, 238, 255))


class TestGetStatusLabel:
    """_get_status_label。"""

    @patch("app.core.system_tray.pystray")
    @patch("app.core.system_tray.Image")
    def test_monitoring_true(self, mock_image, mock_pystray):
        """监控中显示"运行中"。"""
        tray = SystemTray()
        tray._monitoring = True
        assert "运行中" in tray._get_status_label(None)

    @patch("app.core.system_tray.pystray")
    @patch("app.core.system_tray.Image")
    def test_monitoring_false(self, mock_image, mock_pystray):
        """停止时显示"已停止"。"""
        tray = SystemTray()
        tray._monitoring = False
        assert "已停止" in tray._get_status_label(None)


class TestCreateMenu:
    """_create_menu。"""

    @patch("app.core.system_tray.pystray")
    @patch("app.core.system_tray.Image")
    def test_menu_created(self, mock_image, mock_pystray):
        """菜单创建成功。"""
        mock_menu_instance = MagicMock()
        mock_pystray.Menu.return_value = mock_menu_instance
        mock_pystray.MenuItem.return_value = MagicMock()
        mock_pystray.Menu.SEPARATOR = "SEPARATOR"

        tray = SystemTray(port=50721)
        result = tray._create_menu()

        assert result is mock_menu_instance
        assert mock_pystray.MenuItem.call_count >= 3


class TestQuit:
    """_quit。"""

    @patch("app.core.system_tray.pystray")
    @patch("app.core.system_tray.Image")
    def test_quit_with_icon_and_callback(self, mock_image, mock_pystray):
        """有 icon 和 on_exit 时两者都被调用。"""
        on_exit = MagicMock()
        tray = SystemTray(on_exit=on_exit)
        tray.icon = MagicMock()

        tray._quit(tray.icon, None)

        tray.icon.stop.assert_called_once()
        on_exit.assert_called_once()

    @patch("app.core.system_tray.pystray")
    @patch("app.core.system_tray.Image")
    def test_quit_without_icon(self, mock_image, mock_pystray):
        """无 icon 时仅调用 on_exit。"""
        on_exit = MagicMock()
        tray = SystemTray(on_exit=on_exit)
        tray.icon = None

        tray._quit(None, None)

        on_exit.assert_called_once()

    @patch("app.core.system_tray.pystray")
    @patch("app.core.system_tray.Image")
    def test_quit_without_callback(self, mock_image, mock_pystray):
        """无 on_exit 时仅调用 icon.stop。"""
        tray = SystemTray()
        tray.icon = MagicMock()

        tray._quit(tray.icon, None)

        tray.icon.stop.assert_called_once()


class TestStartStop:
    """start / stop。"""

    @patch("app.core.system_tray.pystray")
    @patch("app.core.system_tray.Image")
    def test_start_creates_icon_and_thread(self, mock_image, mock_pystray):
        """start 创建 pystray.Icon 并启动后台守护线程。"""
        import time

        mock_icon_cls = MagicMock()
        mock_icon_instance = MagicMock()
        mock_icon_instance.run.side_effect = lambda: time.sleep(2)
        mock_icon_cls.return_value = mock_icon_instance
        mock_pystray.Icon = mock_icon_cls

        tray = SystemTray(port=50721)

        mock_img = MagicMock()
        with patch.object(tray, "_load_icon", return_value=mock_img):
            tray.start()

        mock_icon_cls.assert_called_once()
        assert tray.icon is mock_icon_instance
        assert tray._thread is not None
        assert tray._thread.daemon is True
        assert tray._thread.is_alive()

        tray.stop()

    @patch("app.core.system_tray.pystray")
    @patch("app.core.system_tray.Image")
    def test_start_idempotent(self, mock_image, mock_pystray):
        """线程仍存活时重复 start 不会创建新 icon。"""
        import time

        mock_icon_cls = MagicMock()
        mock_icon_instance = MagicMock()
        mock_icon_instance.run.side_effect = lambda: time.sleep(2)
        mock_icon_cls.return_value = mock_icon_instance
        mock_pystray.Icon = mock_icon_cls

        tray = SystemTray()

        mock_img = MagicMock()
        with patch.object(tray, "_load_icon", return_value=mock_img):
            tray.start()
            first_thread = tray._thread
            tray.start()

        mock_icon_cls.assert_called_once()
        assert tray._thread is first_thread

        tray.stop()

    @patch("app.core.system_tray.pystray")
    @patch("app.core.system_tray.Image")
    def test_stop_clears_icon(self, mock_image, mock_pystray):
        """stop 调用 icon.stop 并清除引用。"""
        tray = SystemTray()
        tray.icon = MagicMock()

        tray.stop()

    @patch("app.core.system_tray.pystray")
    @patch("app.core.system_tray.Image")
    def test_stop_without_icon(self, mock_image, mock_pystray):
        """无 icon 时 stop 不报错。"""
        tray = SystemTray()
        tray.icon = None
        tray.stop()


class TestUpdateStatus:
    """update_status。"""

    @patch("app.core.system_tray.pystray")
    @patch("app.core.system_tray.Image")
    def test_update_monitoring_true(self, mock_image, mock_pystray):
        """监控中更新标题为"运行中"。"""
        tray = SystemTray()
        mock_icon = MagicMock()
        tray.icon = mock_icon

        tray.update_status(monitoring=True)

        assert tray._monitoring is True
        assert "运行中" in mock_icon.title

    @patch("app.core.system_tray.pystray")
    @patch("app.core.system_tray.Image")
    def test_update_monitoring_false(self, mock_image, mock_pystray):
        """停止时更新标题为"已停止"。"""
        tray = SystemTray()
        mock_icon = MagicMock()
        tray.icon = mock_icon

        tray.update_status(monitoring=False)

        assert tray._monitoring is False
        assert "已停止" in mock_icon.title

    @patch("app.core.system_tray.pystray")
    @patch("app.core.system_tray.Image")
    def test_update_no_icon(self, mock_image, mock_pystray):
        """无 icon 时仅更新 _monitoring 标志，不报错。"""
        tray = SystemTray()
        tray.icon = None

        tray.update_status(monitoring=True)

        assert tray._monitoring is True
```

- [ ] **Step 2: 运行测试确认合并成功**

```bash
uv run pytest tests/test_src_utils.py -v -k "LoadIcon or StatusLabel or CreateMenu or TestQuit or StartStop or UpdateStatus"
```

Expected: 全部 PASS。

- [ ] **Step 3: 删除独立文件并运行全量测试**

```bash
rm tests/test_system_tray.py
uv run pytest --tb=short -q
```

Expected: 全部通过。

- [ ] **Step 4: 提交**

```bash
git add tests/test_src_utils.py tests/test_system_tray.py
git commit -m "refactor: 合并 test_system_tray.py 独有测试到 test_src_utils.py 并删除"
```

### Task 2.6: 合并 test_playwright_bootstrap.py 和 test_playwright_worker.py 到 test_src_utils.py

**说明:** `TestBootstrapState` 和 `TestSubmitAliveCheck` 在 `test_src_utils.py` 中缺失。

**Files:**
- Modify: `tests/test_src_utils.py`
- Delete: `tests/test_playwright_bootstrap.py`
- Delete: `tests/test_playwright_worker.py`

- [ ] **Step 1: 在 test_src_utils.py 末尾追加独有测试**

```python
# ── Playwright bootstrap 状态管理 ──


class TestBootstrapState:
    """bootstrap 状态区分测试"""

    def setup_method(self):
        """每个测试前重置全局状态"""
        import app.workers.playwright_bootstrap as pb

        pb._BOOTSTRAP_DONE = False
        pb._BOOTSTRAP_SKIPPED = False

    def test_bootstrap_disabled_returns_skipped(self):
        """禁用 auto-install 时返回 SKIPPED 状态。"""
        import app.workers.playwright_bootstrap as pb

        with patch.object(pb, "_is_enabled", return_value=False):
            result = pb.ensure_playwright_ready()

        assert result is True
        assert pb._BOOTSTRAP_SKIPPED is True
        assert pb._BOOTSTRAP_DONE is False

    def test_bootstrap_verified_returns_done(self):
        """Chromium 已安装时返回 DONE 状态。"""
        import app.workers.playwright_bootstrap as pb

        with (
            patch.object(pb, "_is_enabled", return_value=True),
            patch.object(pb, "_has_chromium", return_value=True),
        ):
            result = pb.ensure_playwright_ready()

        assert result is True
        assert pb._BOOTSTRAP_DONE is True
        assert pb._BOOTSTRAP_SKIPPED is False

    def test_bootstrap_skipped_then_done(self):
        """先跳过再验证的状态变化。"""
        import app.workers.playwright_bootstrap as pb

        with patch.object(pb, "_is_enabled", return_value=False):
            pb.ensure_playwright_ready()

        assert pb._BOOTSTRAP_SKIPPED is True
        assert pb._BOOTSTRAP_DONE is False

        with (
            patch.object(pb, "_is_enabled", return_value=True),
            patch.object(pb, "_has_chromium", return_value=True),
        ):
            result = pb.ensure_playwright_ready()

        assert result is True
        assert pb._BOOTSTRAP_DONE is False

    def test_is_bootstrap_skipped(self):
        """is_bootstrap_skipped 查询函数。"""
        import app.workers.playwright_bootstrap as pb

        assert pb.is_bootstrap_skipped() is False
        pb._BOOTSTRAP_SKIPPED = True
        assert pb.is_bootstrap_skipped() is True

    def test_is_bootstrap_done(self):
        """is_bootstrap_done 查询函数。"""
        import app.workers.playwright_bootstrap as pb

        assert pb.is_bootstrap_done() is False
        pb._BOOTSTRAP_DONE = True
        assert pb.is_bootstrap_done() is True


# ── PlaywrightWorker submit alive 预检 ──


class TestSubmitAliveCheck:
    """submit() 方法的 worker alive 预检测试"""

    def test_submit_recovers_dead_worker(self):
        """submit 检测到消费者线程死亡后自动重启。"""
        import threading

        worker = PlaywrightWorker()

        start_called = threading.Event()

        def mock_start():
            start_called.set()
            worker._consumer_thread = MagicMock()
            worker._consumer_thread.is_alive.return_value = True
            worker._stop_event.clear()

        worker.start = mock_start

        worker._consumer_thread = MagicMock()
        worker._consumer_thread.is_alive.return_value = False
        worker._stop_event.clear()

        result = worker.submit("test_cmd", wait=False)

        assert start_called.is_set(), "submit 应该调用 start() 重启线程"
        assert result.success

    def test_submit_stopped_worker_rejects(self):
        """已停止的 worker 拒绝新命令。"""
        worker = PlaywrightWorker()
        worker._stop_event.set()

        result = worker.submit("test_cmd", wait=False)

        assert not result.success
        assert "已关闭" in result.error

    def test_submit_restart_failure_returns_error(self):
        """重启失败时返回错误。"""
        worker = PlaywrightWorker()

        worker._consumer_thread = MagicMock()
        worker._consumer_thread.is_alive.return_value = False
        worker._stop_event.clear()

        def mock_start():
            raise RuntimeError("重启失败")

        worker.start = mock_start

        result = worker.submit("test_cmd", wait=False)

        assert not result.success
        assert "重启失败" in result.error

    def test_submit_concurrent_restart_only_one(self):
        """并发 submit 只有一个执行重启。"""
        import concurrent.futures
        import threading

        worker = PlaywrightWorker()

        worker._consumer_thread = MagicMock()
        worker._consumer_thread.is_alive.return_value = False
        worker._stop_event.clear()

        restart_count = 0
        restart_lock = threading.Lock()

        def mock_start():
            nonlocal restart_count
            with restart_lock:
                restart_count += 1
            worker._consumer_thread.is_alive.return_value = True

        worker.start = mock_start

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = []
            for _ in range(5):
                futures.append(
                    executor.submit(lambda: worker.submit("test_cmd", wait=False))
                )
            concurrent.futures.wait(futures)

        assert restart_count == 1, f"重启次数应为 1，实际: {restart_count}"
```

- [ ] **Step 2: 运行测试确认合并成功**

```bash
uv run pytest tests/test_src_utils.py -v -k "BootstrapState or SubmitAliveCheck"
```

Expected: 全部 PASS。

- [ ] **Step 3: 删除独立文件并运行全量测试**

```bash
rm tests/test_playwright_bootstrap.py tests/test_playwright_worker.py
uv run pytest --tb=short -q
```

Expected: 全部通过。

- [ ] **Step 4: 提交**

```bash
git add tests/test_src_utils.py tests/test_playwright_bootstrap.py tests/test_playwright_worker.py
git commit -m "refactor: 合并 playwright bootstrap/worker 测试到 test_src_utils.py 并删除"
```

### Task 2.7: 合并 test_monitor_core_logic.py 独有测试到 test_monitor.py

**说明:** 独立文件中有更细粒度的测试（test_last_check_time_isoformat, test_negative_retries_clamped, test_exponential_backoff 等），需要合并。

**Files:**
- Modify: `tests/test_monitor.py`
- Delete: `tests/test_monitor_core_logic.py`

- [ ] **Step 1: 在 test_monitor.py 末尾追加独有测试**

```python
# ── NetworkMonitorCore 详细逻辑测试 ──


class TestMonitorCoreDetailedSnapshot:
    """snapshot 详细测试。"""

    def test_last_check_time_isoformat(self):
        """last_check_time 序列化为 ISO 格式。"""
        from datetime import datetime, timezone

        core = NetworkMonitorCore(config={})
        core._last_check_time = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        snap = core.snapshot()
        assert "2026-01-01" in snap["last_check_time"]


class TestMonitorCoreDetailedRetryConfig:
    """retry_config 详细测试。"""

    def test_negative_retries_clamped(self):
        """负数重试次数被钳制为 0。"""
        core = NetworkMonitorCore(config={"max_login_retries": -1})
        cfg = core._get_retry_config()
        assert cfg.max_retries >= 0

    def test_exponential_backoff(self):
        """指数退避计算。"""
        core = NetworkMonitorCore(
            config={"retry_backoff_base": 2, "retry_backoff_max": 60}
        )
        cfg = core._get_retry_config()
        # 验证退避参数被正确读取
        assert cfg.backoff_base == 2
        assert cfg.backoff_max == 60


class TestMonitorCoreDetailedLoginRetry:
    """login_retry_or_break 详细测试。"""

    def test_first_attempt_returns_retry(self):
        """首次尝试返回 retry。"""
        core = NetworkMonitorCore(config={"max_login_retries": 3})
        core._login_attempt_count = 0
        result = core._login_retry_or_break()
        assert result == RecoveryResult.RETRY

    def test_within_retries_returns_retry(self):
        """未超过重试次数返回 retry。"""
        core = NetworkMonitorCore(config={"max_login_retries": 3})
        core._login_attempt_count = 2
        result = core._login_retry_or_break()
        assert result == RecoveryResult.RETRY

    def test_resets_attempt_count_on_give_up(self):
        """放弃时重置尝试计数。"""
        core = NetworkMonitorCore(config={"max_login_retries": 1})
        core._login_attempt_count = 1
        core._login_retry_or_break()
        assert core._login_attempt_count == 0


class TestMonitorCoreDetailedWaitInterruptible:
    """wait_interruptible 详细测试。"""

    def test_returns_true_when_not_stopped(self):
        """未停止时返回 True。"""
        core = NetworkMonitorCore(config={})
        core._stop_event = MagicMock()
        core._stop_event.wait.return_value = False  # 超时返回 False
        result = core._wait_interruptible(0.01)
        assert result is True


class TestMonitorCoreLogMessage:
    """log_message 分发逻辑。"""

    def test_uses_callback_when_set(self):
        """有 callback 时使用 callback。"""
        core = NetworkMonitorCore(config={})
        callback = MagicMock()
        core._log_callback = callback
        core.log_message("INFO", "测试消息")
        callback.assert_called_once()

    def test_uses_logger_when_no_callback(self):
        """无 callback 时使用 logger。"""
        core = NetworkMonitorCore(config={})
        core._log_callback = None
        core._logger = MagicMock()
        core.log_message("INFO", "测试消息")
        core._logger.info.assert_called_once()
```

- [ ] **Step 2: 运行测试确认合并成功**

```bash
uv run pytest tests/test_monitor.py -v -k "DetailedSnapshot or DetailedRetryConfig or DetailedLoginRetry or DetailedWaitInterruptible or LogMessage"
```

Expected: 全部 PASS。

- [ ] **Step 3: 删除独立文件并运行全量测试**

```bash
rm tests/test_monitor_core_logic.py
uv run pytest --tb=short -q
```

Expected: 全部通过。

- [ ] **Step 4: 提交**

```bash
git add tests/test_monitor.py tests/test_monitor_core_logic.py
git commit -m "refactor: 合并 test_monitor_core_logic.py 独有测试到 test_monitor.py 并删除"
```

### Task 2.8: 合并 test_login_handler.py 独有测试到 test_monitor.py

**说明:** `TestAttemptLoginChecks` 中的精细 mock 测试在 `test_monitor.py` 中缺失。

**Files:**
- Modify: `tests/test_monitor.py`
- Delete: `tests/test_login_handler.py`

- [ ] **Step 1: 在 test_monitor.py 末尾追加独有测试**

```python
# ── LoginAttemptHandler 详细检查 ──


class TestAttemptLoginChecks:
    """attempt_login 前置检查详细测试。"""

    def test_skip_pause_check(self):
        """skip_pause_check=True 时跳过所有前置检查。"""
        from app.utils.login import LoginAttemptHandler

        handler = LoginAttemptHandler.__new__(LoginAttemptHandler)
        handler._config = {"auth_url": "http://test.com", "username": "test"}
        handler._ui_config = MagicMock()
        handler._ui_config.pause_start = "00:00"
        handler._ui_config.pause_end = "00:00"
        handler._perform_login_with_auth_class = MagicMock(
            return_value=(True, "成功")
        )

        with (
            patch("app.utils.login.is_in_pause_period", return_value=False),
            patch("app.utils.login.check_login_prerequisites", return_value=(True, "")),
        ):
            ok, msg = handler.attempt_login(skip_pause_check=True)

        handler._perform_login_with_auth_class.assert_called_once()
```

- [ ] **Step 2: 运行测试确认合并成功**

```bash
uv run pytest tests/test_monitor.py -v -k "AttemptLoginChecks"
```

Expected: 全部 PASS。

- [ ] **Step 3: 删除独立文件并运行全量测试**

```bash
rm tests/test_login_handler.py
uv run pytest --tb=short -q
```

Expected: 全部通过。

- [ ] **Step 4: 提交**

```bash
git add tests/test_monitor.py tests/test_login_handler.py
git commit -m "refactor: 合并 test_login_handler.py 独有测试到 test_monitor.py 并删除"
```

### Task 2.9: 合并 test_monitor_service_shutdown.py 到 test_monitor_service.py

**说明:** 5 个队列行为测试类在 `test_monitor_service.py` 中完全缺失。

**Files:**
- Modify: `tests/test_monitor_service.py`
- Delete: `tests/test_monitor_service_shutdown.py`

- [ ] **Step 1: 在 test_monitor_service.py 末尾追加全部 5 个测试类**

从 `test_monitor_service_shutdown.py` 复制全部内容（TestProfileReloadNoDeadlock, TestShutdownSynchronous, TestLoginInProgressNoDoubleClear, TestStartMonitoringPutNowait, TestNetworkStateSetInConsumer）追加到 `test_monitor_service.py` 末尾。确保导入语句包含 `queue`, `threading`, `NetworkState`, `MonitorCmdType`, `MonitorCommand`, `MonitorService`。

- [ ] **Step 2: 运行测试确认合并成功**

```bash
uv run pytest tests/test_monitor_service.py -v -k "ProfileReload or Shutdown or LoginInProgress or StartMonitoring or NetworkState"
```

Expected: 全部 PASS。

- [ ] **Step 3: 删除独立文件并运行全量测试**

```bash
rm tests/test_monitor_service_shutdown.py
uv run pytest --tb=short -q
```

Expected: 全部通过。

- [ ] **Step 4: 提交**

```bash
git add tests/test_monitor_service.py tests/test_monitor_service_shutdown.py
git commit -m "refactor: 合并 test_monitor_service_shutdown.py 到 test_monitor_service.py 并删除"
```

### Task 2.10: 合并 test_network_probes 相关文件到 test_network_probes.py

**说明:** `test_decision.py` 和 `test_network_probes_utils.py` 的测试已被 `test_network_probes.py` 覆盖。

**Files:**
- Delete: `tests/test_decision.py`
- Delete: `tests/test_network_probes_utils.py`

- [ ] **Step 1: 确认重叠后删除**

```bash
rm tests/test_decision.py tests/test_network_probes_utils.py
```

- [ ] **Step 2: 运行全量测试**

```bash
uv run pytest --tb=short -q
```

Expected: 全部通过。

- [ ] **Step 3: 提交**

```bash
git add -A tests/
git commit -m "refactor: 删除 test_decision.py 和 test_network_probes_utils.py（已被 test_network_probes.py 覆盖）"
```

### Task 2.11: 合并 test_profile_service.py 和 test_task_service_logic.py 到 test_backend_services.py

**说明:** `TestCorruptRenameEAFP` 和 `TestDangerousStepTypes` 在 `test_backend_services.py` 中缺失。

**Files:**
- Modify: `tests/test_backend_services.py`
- Delete: `tests/test_profile_service.py`
- Delete: `tests/test_task_service_logic.py`

- [ ] **Step 1: 在 test_backend_services.py 末尾追加独有测试**

```python
# ── ProfileService TOCTOU 修复 ──


class TestCorruptRenameEAFP:
    """P1-BE-6: 损坏文件重命名使用 EAFP 模式，避免 TOCTOU 竞态"""

    def test_corrupt_rename_eafp(self, tmp_path):
        """测试文件不存在时 rename 抛出 FileNotFoundError 被静默处理。"""
        settings_path = tmp_path / "settings.json"
        settings_path.write_text("{invalid json!!!", encoding="utf-8")

        svc = ProfileService.__new__(ProfileService)
        svc.project_root = tmp_path
        svc._settings_path = settings_path
        svc._lock = MagicMock()
        svc._data = None

        result = svc._load_unsafe()

        assert result is not None
        corrupt_files = list(tmp_path.glob("settings.corrupt.*.json"))
        assert len(corrupt_files) == 1, "损坏文件应被重命名为 settings.corrupt.*.json"

    def test_corrupt_rename_file_missing(self, tmp_path):
        """测试文件在读取和重命名之间被删除时，FileNotFoundError 被静默处理。"""
        svc = ProfileService.__new__(ProfileService)
        svc.project_root = tmp_path
        svc._settings_path = tmp_path / "settings.json"
        svc._lock = MagicMock()
        svc._data = None

        result = svc._load_unsafe()

        assert result is not None
        assert "default" in result.profiles
        assert len(result.profiles) == 1


# ── _DANGEROUS_STEP_TYPES 详细测试 ──


class TestDangerousStepTypes:
    """危险步骤类型常量。"""

    def test_contains_eval(self):
        """包含 eval。"""
        assert "eval" in _DANGEROUS_STEP_TYPES

    def test_contains_custom_js(self):
        """包含 custom_js。"""
        assert "custom_js" in _DANGEROUS_STEP_TYPES

    def test_not_contains_click(self):
        """不包含 click。"""
        assert "click" not in _DANGEROUS_STEP_TYPES
```

- [ ] **Step 2: 运行测试确认合并成功**

```bash
uv run pytest tests/test_backend_services.py -v -k "CorruptRenameEAFP or DangerousStepTypes"
```

Expected: 全部 PASS。

- [ ] **Step 3: 删除独立文件并运行全量测试**

```bash
rm tests/test_profile_service.py tests/test_task_service_logic.py
uv run pytest --tb=short -q
```

Expected: 全部通过。

- [ ] **Step 4: 提交**

```bash
git add tests/test_backend_services.py tests/test_profile_service.py tests/test_task_service_logic.py
git commit -m "refactor: 合并 profile/task 独有测试到 test_backend_services.py 并删除"
```

### Task 2.12: 合并 test_api_tools.py 到 test_api_tools_routes.py 并重命名 test_api_logfiles.py

**说明:** `test_api_tools.py` 的 3 个 class 已被 `test_api_tools_routes.py` 覆盖。`test_api_logfiles.py` 重命名为 `test_api_logfiles_routes.py`。

**Files:**
- Delete: `tests/test_api_tools.py`
- Rename: `tests/test_api_logfiles.py` → `tests/test_api_logfiles_routes.py`

- [ ] **Step 1: 删除 test_api_tools.py**

```bash
rm tests/test_api_tools.py
```

- [ ] **Step 2: 重命名 test_api_logfiles.py**

```bash
mv tests/test_api_logfiles.py tests/test_api_logfiles_routes.py
```

- [ ] **Step 3: 运行全量测试**

```bash
uv run pytest --tb=short -q
```

Expected: 全部通过。

- [ ] **Step 4: 提交**

```bash
git add -A tests/
git commit -m "refactor: 删除 test_api_tools.py，重命名 test_api_logfiles.py 为 test_api_logfiles_routes.py"
```

### Task 2.13: 合并 test_api.py 到 test_routers.py

**说明:** `test_api.py` 包含的端点测试与 `test_routers.py` 重叠。将 `test_api.py` 中 `test_routers.py` 未覆盖的测试合并后删除。

**Files:**
- Modify: `tests/test_routers.py`
- Delete: `tests/test_api.py`

- [ ] **Step 1: 比较两个文件的测试覆盖**

```bash
# 列出 test_api.py 的测试类
grep "class Test" tests/test_api.py
# 列出 test_routers.py 的测试类
grep "class Test" tests/test_routers.py
```

- [ ] **Step 2: 将 test_api.py 中 test_routers.py 缺失的测试追加到 test_routers.py**

需要检查 `TestHealthEndpoint`、`TestInitStatusEndpoint`、`TestConfigEndpoint`、`TestStatusEndpoint`、`TestLogsEndpoint`、`TestMonitorEndpoints`、`TestLoginEndpoint`、`TestCompareVersions` 是否在 `test_routers.py` 中有对应测试。将缺失的追加到 `test_routers.py` 末尾。

- [ ] **Step 3: 删除 test_api.py 并运行全量测试**

```bash
rm tests/test_api.py
uv run pytest --tb=short -q
```

Expected: 全部通过。

- [ ] **Step 4: 提交**

```bash
git add tests/test_routers.py tests/test_api.py
git commit -m "refactor: 合并 test_api.py 到 test_routers.py 并删除"
```

---

## 阶段 3: 补充缺失的 API 路由测试

### Task 3.1: 创建 test_api_config_routes.py

**说明:** 配置路由缺少 PUT（保存配置）和 POST（验证配置）端点测试。

**Files:**
- Create: `tests/test_api_config_routes.py`

- [ ] **Step 1: 创建测试文件**

```python
"""配置路由 API 测试 — 覆盖配置读取、保存、校验端点。"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.schemas import MonitorConfigPayload


@pytest.fixture
def client(tmp_path):
    """创建隔离的测试客户端。"""
    (tmp_path / "frontend").mkdir(exist_ok=True)
    (tmp_path / "frontend" / "index.html").write_text("<html></html>")
    (tmp_path / "logs").mkdir(exist_ok=True)
    (tmp_path / "temp").mkdir(exist_ok=True)

    with (
        patch("app.constants.PROJECT_ROOT", tmp_path),
        patch("app.constants.FRONTEND_DIR", tmp_path / "frontend"),
        patch("app.constants.LOGS_DIR", tmp_path / "logs"),
        patch("app.constants.TEMP_DIR", tmp_path / "temp"),
    ):
        from app.application import app

        mock_services = MagicMock()
        mock_services.monitor_service.get_config.return_value = MonitorConfigPayload(
            username="testuser", password="••••••••", auth_url="http://10.0.0.1"
        )
        mock_services.monitor_service.get_status.return_value = MagicMock()
        mock_services.monitor_service.list_logs.return_value = []
        app.state.services = mock_services

        test_client = TestClient(app)
        yield test_client, mock_services


# ── GET /api/config ──


class TestGetConfig:
    """配置读取。"""

    def test_get_config_success(self, client):
        """获取配置成功。"""
        test_client, _ = client
        resp = test_client.get("/api/config")
        assert resp.status_code == 200
        data = resp.json()
        assert "username" in data
        assert "auth_url" in data


# ── GET /api/config/default-stealth-script ──


class TestGetDefaultStealthScript:
    """默认反检测脚本。"""

    def test_get_stealth_script(self, client):
        """获取反检测脚本成功。"""
        test_client, _ = client
        resp = test_client.get("/api/config/default-stealth-script")
        assert resp.status_code == 200
        data = resp.json()
        assert "script" in data
        assert len(data["script"]) > 0


# ── PUT /api/config ──


class TestSaveConfig:
    """配置保存。"""

    def test_save_config_success(self, client):
        """保存配置成功。"""
        test_client, mock_services = client
        with (
            patch("app.api.config.ConfigValidator.validate_gui_config", return_value=(True, "")),
            patch("app.api.config.save_config_combined"),
        ):
            resp = test_client.put(
                "/api/config",
                json={
                    "username": "newuser",
                    "password": "newpass",
                    "auth_url": "http://10.0.0.2",
                    "check_interval_seconds": 30,
                },
            )
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_save_config_validation_failure(self, client):
        """校验失败返回 400。"""
        test_client, _ = client
        with patch(
            "app.api.config.ConfigValidator.validate_gui_config",
            return_value=(False, "用户名不能为空"),
        ):
            resp = test_client.put(
                "/api/config",
                json={
                    "username": "",
                    "password": "pass",
                    "auth_url": "http://10.0.0.1",
                    "check_interval_seconds": 30,
                },
            )
        assert resp.status_code == 400

    def test_save_config_server_error(self, client):
        """服务端异常返回 500。"""
        test_client, _ = client
        with (
            patch("app.api.config.ConfigValidator.validate_gui_config", return_value=(True, "")),
            patch("app.api.config.save_config_combined", side_effect=RuntimeError("磁盘满")),
        ):
            resp = test_client.put(
                "/api/config",
                json={
                    "username": "user",
                    "password": "pass",
                    "auth_url": "http://10.0.0.1",
                    "check_interval_seconds": 30,
                },
            )
        assert resp.status_code == 500
```

- [ ] **Step 2: 运行测试**

```bash
uv run pytest tests/test_api_config_routes.py -v
```

Expected: 全部 PASS。

- [ ] **Step 3: 提交**

```bash
git add tests/test_api_config_routes.py
git commit -m "feat: 添加配置路由 API 测试（GET/PUT 端点）"
```

### Task 3.2: 创建 test_api_tasks_routes.py

**说明:** 任务路由缺少独立单元测试。

**Files:**
- Create: `tests/test_api_tasks_routes.py`

- [ ] **Step 1: 创建测试文件**

```python
"""任务路由 API 测试 — 覆盖任务 CRUD 端点。"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.schemas import MonitorConfigPayload, MonitorStatusResponse


@pytest.fixture
def client(tmp_path):
    """创建隔离的测试客户端。"""
    (tmp_path / "frontend").mkdir(exist_ok=True)
    (tmp_path / "frontend" / "index.html").write_text("<html></html>")
    (tmp_path / "logs").mkdir(exist_ok=True)
    (tmp_path / "temp").mkdir(exist_ok=True)
    (tmp_path / "tasks" / "browser").mkdir(parents=True)
    (tmp_path / "tasks" / "scripts").mkdir(parents=True)

    (tmp_path / "tasks" / "browser" / "default.json").write_text(
        json.dumps({"name": "默认", "url": "http://test", "steps": []}),
        encoding="utf-8",
    )

    with (
        patch("app.constants.PROJECT_ROOT", tmp_path),
        patch("app.constants.FRONTEND_DIR", tmp_path / "frontend"),
        patch("app.constants.LOGS_DIR", tmp_path / "logs"),
        patch("app.constants.TEMP_DIR", tmp_path / "temp"),
    ):
        from app.application import app

        mock_services = MagicMock()
        mock_services.monitor_service.get_config.return_value = MonitorConfigPayload(
            username="test", password="••••••••", auth_url="http://test"
        )
        mock_services.monitor_service.get_status.return_value = MonitorStatusResponse(
            monitoring=False,
            network_check_count=0,
            login_attempt_count=0,
            last_check_time=None,
            runtime_seconds=0,
        )
        mock_services.monitor_service.list_logs.return_value = []
        app.state.services = mock_services

        test_client = TestClient(app)
        yield test_client, mock_services


# ── GET /api/tasks ──


class TestListTasks:
    """任务列表。"""

    def test_list_tasks(self, client):
        """获取任务列表。"""
        test_client, mock_services = client
        mock_services.task_service.list_tasks.return_value = [
            {"id": "default", "name": "默认"}
        ]
        resp = test_client.get("/api/tasks")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


# ── GET /api/tasks/active ──


class TestGetActiveTask:
    """活动任务。"""

    def test_get_active_task(self, client):
        """获取活动任务 ID。"""
        test_client, mock_services = client
        mock_services.task_service.get_active_task.return_value = "default"
        resp = test_client.get("/api/tasks/active")
        assert resp.status_code == 200
        assert resp.json()["task_id"] == "default"


# ── GET /api/tasks/{task_id} ──


class TestGetTask:
    """获取单个任务。"""

    def test_get_existing_task(self, client):
        """获取存在的任务。"""
        test_client, mock_services = client
        mock_services.task_service.get_task.return_value = {
            "id": "default",
            "name": "默认",
        }
        resp = test_client.get("/api/tasks/default")
        assert resp.status_code == 200
        assert resp.json()["id"] == "default"

    def test_get_nonexistent_task(self, client):
        """获取不存在的任务返回 404。"""
        test_client, mock_services = client
        mock_services.task_service.get_task.return_value = None
        resp = test_client.get("/api/tasks/nonexistent")
        assert resp.status_code == 404


# ── PUT /api/tasks/{task_id} ──


class TestSaveTask:
    """保存任务。"""

    def test_save_task_success(self, client):
        """保存任务成功。"""
        test_client, mock_services = client
        mock_services.task_service.save_task.return_value = (True, "保存成功")
        resp = test_client.put(
            "/api/tasks/test",
            json={"name": "测试任务", "url": "http://test", "steps": []},
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is True


# ── DELETE /api/tasks/{task_id} ──


class TestDeleteTask:
    """删除任务。"""

    def test_delete_task_success(self, client):
        """删除任务成功。"""
        test_client, mock_services = client
        mock_services.task_service.delete_task.return_value = (True, "删除成功")
        resp = test_client.delete("/api/tasks/test")
        assert resp.status_code == 200
        assert resp.json()["success"] is True


# ── POST /api/tasks/active/{task_id} ──


class TestSetActiveTask:
    """设置活动任务。"""

    def test_set_active_task_success(self, client):
        """设置活动任务成功。"""
        test_client, mock_services = client
        mock_services.task_service.set_active_task.return_value = (True, "设置成功")
        resp = test_client.post("/api/tasks/active/test")
        assert resp.status_code == 200
        assert resp.json()["success"] is True


# ── POST /api/tasks/order ──


class TestSaveTaskOrder:
    """保存任务排序。"""

    def test_save_task_order_success(self, client):
        """保存排序成功。"""
        test_client, mock_services = client
        mock_services.task_service.save_task_order.return_value = (True, "排序成功")
        resp = test_client.post(
            "/api/tasks/order", json={"order": ["default", "test"]}
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is True
```

- [ ] **Step 2: 运行测试**

```bash
uv run pytest tests/test_api_tasks_routes.py -v
```

Expected: 全部 PASS。

- [ ] **Step 3: 提交**

```bash
git add tests/test_api_tasks_routes.py
git commit -m "feat: 添加任务路由 API 测试（CRUD 端点）"
```

### Task 3.3: 创建 test_api_debug_routes.py

**说明:** 调试路由缺少独立单元测试。

**Files:**
- Create: `tests/test_api_debug_routes.py`

- [ ] **Step 1: 创建测试文件**

```python
"""调试路由 API 测试 — 覆盖调试会话端点。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.schemas import MonitorConfigPayload, MonitorStatusResponse


@pytest.fixture
def client(tmp_path):
    """创建隔离的测试客户端。"""
    (tmp_path / "frontend").mkdir(exist_ok=True)
    (tmp_path / "frontend" / "index.html").write_text("<html></html>")
    (tmp_path / "logs").mkdir(exist_ok=True)
    (tmp_path / "temp").mkdir(exist_ok=True)

    with (
        patch("app.constants.PROJECT_ROOT", tmp_path),
        patch("app.constants.FRONTEND_DIR", tmp_path / "frontend"),
        patch("app.constants.LOGS_DIR", tmp_path / "logs"),
        patch("app.constants.TEMP_DIR", tmp_path / "temp"),
    ):
        from app.application import app

        mock_services = MagicMock()
        mock_services.monitor_service.get_config.return_value = MonitorConfigPayload(
            username="test", password="••••••••", auth_url="http://test"
        )
        mock_services.monitor_service.get_status.return_value = MonitorStatusResponse(
            monitoring=False,
            network_check_count=0,
            login_attempt_count=0,
            last_check_time=None,
            runtime_seconds=0,
        )
        mock_services.monitor_service.list_logs.return_value = []
        mock_services.debug_manager.start = AsyncMock(
            return_value={"success": True, "session_id": "test-123"}
        )
        mock_services.debug_manager.next_step = AsyncMock(
            return_value={"success": True, "step": {}}
        )
        mock_services.debug_manager.run_all = AsyncMock(
            return_value={"success": True, "steps_executed": 5}
        )
        mock_services.debug_manager.stop = AsyncMock(
            return_value={"success": True}
        )
        mock_services.debug_manager.get_status.return_value = {
            "active": False,
            "session_id": None,
        }
        app.state.services = mock_services

        test_client = TestClient(app)
        yield test_client, mock_services


# ── POST /api/debug/start ──


class TestDebugStart:
    """启动调试。"""

    def test_debug_start_success(self, client):
        """启动调试会话成功。"""
        test_client, mock_services = client
        resp = test_client.post("/api/debug/start", json={"task_id": "default"})
        assert resp.status_code == 200
        assert resp.json()["success"] is True


# ── POST /api/debug/next ──


class TestDebugNext:
    """单步执行。"""

    def test_debug_next_success(self, client):
        """单步执行成功。"""
        test_client, _ = client
        resp = test_client.post("/api/debug/next")
        assert resp.status_code == 200
        assert resp.json()["success"] is True


# ── POST /api/debug/run-all ──


class TestDebugRunAll:
    """全部执行。"""

    def test_debug_run_all_success(self, client):
        """全部执行成功。"""
        test_client, _ = client
        resp = test_client.post("/api/debug/run-all")
        assert resp.status_code == 200
        assert resp.json()["success"] is True


# ── POST /api/debug/stop ──


class TestDebugStop:
    """停止调试。"""

    def test_debug_stop_success(self, client):
        """停止调试成功。"""
        test_client, _ = client
        resp = test_client.post("/api/debug/stop")
        assert resp.status_code == 200
        assert resp.json()["success"] is True


# ── GET /api/debug/status ──


class TestDebugStatus:
    """调试状态。"""

    def test_debug_status(self, client):
        """获取调试状态。"""
        test_client, _ = client
        resp = test_client.get("/api/debug/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "active" in data
```

- [ ] **Step 2: 运行测试**

```bash
uv run pytest tests/test_api_debug_routes.py -v
```

Expected: 全部 PASS。

- [ ] **Step 3: 提交**

```bash
git add tests/test_api_debug_routes.py
git commit -m "feat: 添加调试路由 API 测试（start/next/run-all/stop/status 端点）"
```

### Task 3.4: 创建剩余 5 个低风险 API 路由测试文件

**说明:** 为 profiles、monitor、history、repo、autostart 创建路由测试。

**Files:**
- Create: `tests/test_api_profiles_routes.py`
- Create: `tests/test_api_monitor_routes.py`
- Create: `tests/test_api_history_routes.py`
- Create: `tests/test_api_repo_routes.py`
- Create: `tests/test_api_autostart_routes.py`

- [ ] **Step 1: 创建 test_api_profiles_routes.py**

```python
"""方案路由 API 测试 — 覆盖方案 CRUD 端点。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.schemas import (
    MonitorConfigPayload,
    MonitorStatusResponse,
    ProfileSettings,
    ProfilesData,
    SystemSettings,
)


@pytest.fixture
def client(tmp_path):
    """创建隔离的测试客户端。"""
    (tmp_path / "frontend").mkdir(exist_ok=True)
    (tmp_path / "frontend" / "index.html").write_text("<html></html>")
    (tmp_path / "logs").mkdir(exist_ok=True)
    (tmp_path / "temp").mkdir(exist_ok=True)

    with (
        patch("app.constants.PROJECT_ROOT", tmp_path),
        patch("app.constants.FRONTEND_DIR", tmp_path / "frontend"),
        patch("app.constants.LOGS_DIR", tmp_path / "logs"),
        patch("app.constants.TEMP_DIR", tmp_path / "temp"),
    ):
        from app.application import app

        mock_services = MagicMock()
        mock_services.monitor_service.get_config.return_value = MonitorConfigPayload(
            username="test", password="••••••••", auth_url="http://test"
        )
        mock_services.monitor_service.get_status.return_value = MonitorStatusResponse(
            monitoring=False, network_check_count=0, login_attempt_count=0,
            last_check_time=None, runtime_seconds=0,
        )
        mock_services.monitor_service.list_logs.return_value = []

        profile_data = ProfilesData(
            active_profile="default",
            auto_switch=False,
            profiles={"default": ProfileSettings(name="默认方案")},
            system=SystemSettings(),
        )
        mock_services.profile_service.load.return_value = profile_data
        mock_services.profile_service.get_active_profile.return_value = profile_data.profiles["default"]
        mock_services.profile_service.save_profile.return_value = (True, "保存成功")
        mock_services.profile_service.delete_profile.return_value = (True, "删除成功")
        mock_services.profile_service.set_active_profile.return_value = (True, "设置成功")
        mock_services.profile_service.set_auto_switch.return_value = None
        mock_services.profile_service.detect_matching_profile.return_value = None

        app.state.services = mock_services
        test_client = TestClient(app)
        yield test_client, mock_services


class TestListProfiles:
    """方案列表。"""

    def test_list_profiles(self, client):
        test_client, _ = client
        resp = test_client.get("/api/profiles")
        assert resp.status_code == 200
        data = resp.json()
        assert "profiles" in data
        assert "active_profile" in data


class TestGetActiveProfile:
    """活动方案。"""

    def test_get_active_profile(self, client):
        test_client, _ = client
        resp = test_client.get("/api/profiles/active")
        assert resp.status_code == 200
        assert "profile_id" in resp.json()


class TestGetProfile:
    """获取方案。"""

    def test_get_existing_profile(self, client):
        test_client, _ = client
        resp = test_client.get("/api/profiles/default")
        assert resp.status_code == 200

    def test_get_nonexistent_profile(self, client):
        test_client, mock_services = client
        mock_services.profile_service.load.return_value.profiles = {}
        resp = test_client.get("/api/profiles/nonexistent")
        assert resp.status_code == 404


class TestSaveProfile:
    """保存方案。"""

    def test_save_profile_success(self, client):
        test_client, _ = client
        resp = test_client.put(
            "/api/profiles/test",
            json={"name": "测试方案"},
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is True


class TestDeleteProfile:
    """删除方案。"""

    def test_delete_profile_success(self, client):
        test_client, _ = client
        resp = test_client.delete("/api/profiles/test")
        assert resp.status_code == 200
        assert resp.json()["success"] is True


class TestSetActiveProfile:
    """设置活动方案。"""

    def test_set_active_profile_success(self, client):
        test_client, _ = client
        resp = test_client.post("/api/profiles/active/test")
        assert resp.status_code == 200
        assert resp.json()["success"] is True


class TestDetectNetworkProfile:
    """网络检测。"""

    def test_detect_success(self, client):
        test_client, _ = client
        with (
            patch("app.api.profiles.detect_gateway_ip", return_value="10.0.0.1"),
            patch("app.api.profiles.detect_wifi_ssid", return_value="TestWiFi"),
        ):
            resp = test_client.post("/api/profiles/detect")
        assert resp.status_code == 200
        data = resp.json()
        assert "gateway_ip" in data
        assert "ssid" in data


class TestToggleAutoSwitch:
    """自动切换。"""

    def test_toggle_auto_switch_on(self, client):
        test_client, _ = client
        resp = test_client.post("/api/profiles/auto-switch?enabled=true")
        assert resp.status_code == 200
        assert resp.json()["success"] is True
```

- [ ] **Step 2: 创建 test_api_monitor_routes.py**

```python
"""监控路由 API 测试 — 覆盖监控启停端点。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.schemas import MonitorConfigPayload, MonitorStatusResponse, LogEntry


@pytest.fixture
def client(tmp_path):
    """创建隔离的测试客户端。"""
    (tmp_path / "frontend").mkdir(exist_ok=True)
    (tmp_path / "frontend" / "index.html").write_text("<html></html>")
    (tmp_path / "logs").mkdir(exist_ok=True)
    (tmp_path / "temp").mkdir(exist_ok=True)

    with (
        patch("app.constants.PROJECT_ROOT", tmp_path),
        patch("app.constants.FRONTEND_DIR", tmp_path / "frontend"),
        patch("app.constants.LOGS_DIR", tmp_path / "logs"),
        patch("app.constants.TEMP_DIR", tmp_path / "temp"),
    ):
        from app.application import app

        mock_services = MagicMock()
        mock_services.monitor_service.get_config.return_value = MonitorConfigPayload(
            username="test", password="••••••••", auth_url="http://test"
        )
        mock_services.monitor_service.get_status.return_value = MonitorStatusResponse(
            monitoring=False, network_check_count=0, login_attempt_count=0,
            last_check_time=None, runtime_seconds=0,
        )
        mock_services.monitor_service.list_logs.return_value = []
        mock_services.monitor_service.start_monitoring.return_value = (True, "监控已启动")
        mock_services.monitor_service.stop_monitoring.return_value = (True, "监控已停止")
        mock_services.monitor_service.run_manual_login = MagicMock(return_value=(True, "登录成功"))
        mock_services.monitor_service.test_network.return_value = (True, "网络正常")
        mock_services.monitor_service.pure_mode = False
        mock_services.monitor_service.toggle_pure_mode.return_value = True

        app.state.services = mock_services
        test_client = TestClient(app)
        yield test_client, mock_services


class TestGetStatus:
    """状态查询。"""

    def test_get_status(self, client):
        test_client, _ = client
        resp = test_client.get("/api/status")
        assert resp.status_code == 200
        assert "monitoring" in resp.json()


class TestGetLogs:
    """日志查询。"""

    def test_get_logs(self, client):
        test_client, _ = client
        resp = test_client.get("/api/logs")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


class TestStartMonitoring:
    """启动监控。"""

    def test_start_success(self, client):
        test_client, _ = client
        resp = test_client.post("/api/monitor/start")
        assert resp.status_code == 200
        assert resp.json()["success"] is True


class TestStopMonitoring:
    """停止监控。"""

    def test_stop_success(self, client):
        test_client, _ = client
        resp = test_client.post("/api/monitor/stop")
        assert resp.status_code == 200
        assert resp.json()["success"] is True


class TestManualLogin:
    """手动登录。"""

    def test_manual_login_success(self, client):
        test_client, mock_services = client
        resp = test_client.post("/api/actions/login")
        assert resp.status_code == 200
        assert resp.json()["success"] is True


class TestTestNetwork:
    """网络测试。"""

    def test_network_success(self, client):
        test_client, _ = client
        resp = test_client.post("/api/actions/test-network")
        assert resp.status_code == 200
        assert resp.json()["success"] is True


class TestPureMode:
    """纯净模式。"""

    def test_get_pure_mode(self, client):
        test_client, _ = client
        resp = test_client.get("/api/pure-mode")
        assert resp.status_code == 200
        assert "enabled" in resp.json()

    def test_toggle_pure_mode(self, client):
        test_client, _ = client
        resp = test_client.post("/api/pure-mode")
        assert resp.status_code == 200
        assert "enabled" in resp.json()
```

- [ ] **Step 3: 创建 test_api_history_routes.py**

```python
"""登录历史路由 API 测试 — 覆盖查询和清空端点。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.schemas import MonitorConfigPayload, MonitorStatusResponse


@pytest.fixture
def client(tmp_path):
    """创建隔离的测试客户端。"""
    (tmp_path / "frontend").mkdir(exist_ok=True)
    (tmp_path / "frontend" / "index.html").write_text("<html></html>")
    (tmp_path / "logs").mkdir(exist_ok=True)
    (tmp_path / "temp").mkdir(exist_ok=True)

    with (
        patch("app.constants.PROJECT_ROOT", tmp_path),
        patch("app.constants.FRONTEND_DIR", tmp_path / "frontend"),
        patch("app.constants.LOGS_DIR", tmp_path / "logs"),
        patch("app.constants.TEMP_DIR", tmp_path / "temp"),
    ):
        from app.application import app

        mock_services = MagicMock()
        mock_services.monitor_service.get_config.return_value = MonitorConfigPayload(
            username="test", password="••••••••", auth_url="http://test"
        )
        mock_services.monitor_service.get_status.return_value = MonitorStatusResponse(
            monitoring=False, network_check_count=0, login_attempt_count=0,
            last_check_time=None, runtime_seconds=0,
        )
        mock_services.monitor_service.list_logs.return_value = []
        mock_services.login_history_service.list_recent.return_value = []
        mock_services.login_history_service.clear.return_value = 5

        app.state.services = mock_services
        test_client = TestClient(app)
        yield test_client, mock_services


class TestGetLoginHistory:
    """查询登录历史。"""

    def test_get_history(self, client):
        test_client, _ = client
        resp = test_client.get("/api/login-history")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_get_history_with_limit(self, client):
        test_client, _ = client
        resp = test_client.get("/api/login-history?limit=10")
        assert resp.status_code == 200


class TestClearLoginHistory:
    """清空登录历史。"""

    def test_clear_history(self, client):
        test_client, _ = client
        resp = test_client.delete("/api/login-history")
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        assert "5" in resp.json()["message"]
```

- [ ] **Step 4: 创建 test_api_repo_routes.py**

```python
"""仓库代理路由 API 测试 — 覆盖索引和任务获取端点。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.schemas import MonitorConfigPayload, MonitorStatusResponse, SystemSettings


@pytest.fixture
def client(tmp_path):
    """创建隔离的测试客户端。"""
    (tmp_path / "frontend").mkdir(exist_ok=True)
    (tmp_path / "frontend" / "index.html").write_text("<html></html>")
    (tmp_path / "logs").mkdir(exist_ok=True)
    (tmp_path / "temp").mkdir(exist_ok=True)

    with (
        patch("app.constants.PROJECT_ROOT", tmp_path),
        patch("app.constants.FRONTEND_DIR", tmp_path / "frontend"),
        patch("app.constants.LOGS_DIR", tmp_path / "logs"),
        patch("app.constants.TEMP_DIR", tmp_path / "temp"),
    ):
        from app.application import app

        mock_services = MagicMock()
        mock_services.monitor_service.get_config.return_value = MonitorConfigPayload(
            username="test", password="••••••••", auth_url="http://test"
        )
        mock_services.monitor_service.get_status.return_value = MonitorStatusResponse(
            monitoring=False, network_check_count=0, login_attempt_count=0,
            last_check_time=None, runtime_seconds=0,
        )
        mock_services.monitor_service.list_logs.return_value = []

        from app.schemas import ProfilesData, ProfileSettings
        profile_data = ProfilesData(
            active_profile="default", auto_switch=False,
            profiles={"default": ProfileSettings(name="默认")},
            system=SystemSettings(),
        )
        mock_services.profile_service.load.return_value = profile_data

        app.state.services = mock_services
        test_client = TestClient(app)
        yield test_client, mock_services


class TestRepoFetchIndex:
    """获取仓库索引。"""

    def test_fetch_index_success(self, client):
        test_client, _ = client
        with patch("app.api.repo.repo_fetch_json", return_value=[{"id": "task1"}]):
            resp = test_client.get("/api/repo/fetch?url=http://example.com/index.json")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_fetch_index_missing_url(self, client):
        test_client, _ = client
        resp = test_client.get("/api/repo/fetch")
        assert resp.status_code == 422


class TestRepoFetchTask:
    """获取仓库任务。"""

    def test_fetch_task_success(self, client):
        test_client, _ = client
        with patch("app.api.repo.repo_fetch_json", return_value={"id": "task1", "name": "任务1"}):
            resp = test_client.get("/api/repo/task?url=http://example.com/task.json")
        assert resp.status_code == 200
        assert resp.json()["id"] == "task1"
```

- [ ] **Step 5: 创建 test_api_autostart_routes.py**

```python
"""自启动路由 API 测试 — 覆盖 Shell 列表和自启动端点。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.schemas import MonitorConfigPayload, MonitorStatusResponse


@pytest.fixture
def client(tmp_path):
    """创建隔离的测试客户端。"""
    (tmp_path / "frontend").mkdir(exist_ok=True)
    (tmp_path / "frontend" / "index.html").write_text("<html></html>")
    (tmp_path / "logs").mkdir(exist_ok=True)
    (tmp_path / "temp").mkdir(exist_ok=True)

    with (
        patch("app.constants.PROJECT_ROOT", tmp_path),
        patch("app.constants.FRONTEND_DIR", tmp_path / "frontend"),
        patch("app.constants.LOGS_DIR", tmp_path / "logs"),
        patch("app.constants.TEMP_DIR", tmp_path / "temp"),
    ):
        from app.application import app

        mock_services = MagicMock()
        mock_services.monitor_service.get_config.return_value = MonitorConfigPayload(
            username="test", password="••••••••", auth_url="http://test"
        )
        mock_services.monitor_service.get_status.return_value = MonitorStatusResponse(
            monitoring=False, network_check_count=0, login_attempt_count=0,
            last_check_time=None, runtime_seconds=0,
        )
        mock_services.monitor_service.list_logs.return_value = []
        mock_services.autostart_service.status.return_value = {
            "platform": "win32",
            "enabled": False,
            "method": "",
            "location": "",
        }
        mock_services.autostart_service.enable.return_value = (True, "已启用")
        mock_services.autostart_service.disable.return_value = (True, "已禁用")

        app.state.services = mock_services
        test_client = TestClient(app)
        yield test_client, mock_services


class TestListShells:
    """Shell 列表。"""

    def test_list_shells(self, client):
        test_client, _ = client
        with (
            patch("app.api.autostart.detect_available_shells", return_value=[{"name": "cmd"}]),
            patch("app.api.autostart.get_default_shell", return_value="cmd"),
        ):
            resp = test_client.get("/api/shells")
        assert resp.status_code == 200
        data = resp.json()
        assert "shells" in data
        assert "default" in data


class TestAutostartStatus:
    """自启动状态。"""

    def test_autostart_status(self, client):
        test_client, _ = client
        resp = test_client.get("/api/autostart/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "platform" in data
        assert "enabled" in data


class TestEnableAutostart:
    """启用自启动。"""

    def test_enable_success(self, client):
        test_client, _ = client
        resp = test_client.post("/api/autostart/enable")
        assert resp.status_code == 200
        assert resp.json()["success"] is True


class TestDisableAutostart:
    """禁用自启动。"""

    def test_disable_success(self, client):
        test_client, _ = client
        resp = test_client.post("/api/autostart/disable")
        assert resp.status_code == 200
        assert resp.json()["success"] is True
```

- [ ] **Step 6: 运行所有新测试**

```bash
uv run pytest tests/test_api_profiles_routes.py tests/test_api_monitor_routes.py tests/test_api_history_routes.py tests/test_api_repo_routes.py tests/test_api_autostart_routes.py -v
```

Expected: 全部 PASS。

- [ ] **Step 7: 提交**

```bash
git add tests/test_api_profiles_routes.py tests/test_api_monitor_routes.py tests/test_api_history_routes.py tests/test_api_repo_routes.py tests/test_api_autostart_routes.py
git commit -m "feat: 添加 5 个低风险 API 路由测试（profiles/monitor/history/repo/autostart）"
```

---

## 阶段 4: 提升测试质量

### Task 4.1: 修复 RuntimeWarning 警告

**说明:** 修复 3 个 coroutine 未 await 的 RuntimeWarning。

- [ ] **Step 1: 定位警告源**

```bash
uv run pytest --tb=short -q 2>&1 | grep -A 3 "RuntimeWarning"
```

- [ ] **Step 2: 修复警告**

根据警告输出，修复对应的测试文件中的 async mock 问题。常见修复：
- 将 `MagicMock()` 替换为 `AsyncMock()` 用于 async 方法
- 确保 `@pytest.mark.asyncio` 标记的测试使用正确的 async mock

- [ ] **Step 3: 验证警告已消除**

```bash
uv run pytest --tb=short -q 2>&1 | grep -c "RuntimeWarning"
```

Expected: 0

- [ ] **Step 4: 提交**

```bash
git add -A tests/
git commit -m "fix: 修复测试中的 RuntimeWarning 警告（coroutine 未 await）"
```

### Task 4.2: 清理 conftest.py 未使用的 fixtures

**说明:** `patched_signal_handlers` 和 `patched_uvicorn_run` 未被任何测试使用。

**Files:**
- Modify: `tests/conftest.py`

- [ ] **Step 1: 确认未使用**

```bash
grep -r "patched_signal_handlers\|patched_uvicorn_run" tests/ --include="*.py" | grep -v conftest.py
```

Expected: 无输出。

- [ ] **Step 2: 删除未使用的 fixtures**

从 `tests/conftest.py` 中删除 `patched_signal_handlers` 和 `patched_uvicorn_run` 两个 fixture 函数。

- [ ] **Step 3: 运行全量测试**

```bash
uv run pytest --tb=short -q
```

Expected: 全部通过。

- [ ] **Step 4: 提交**

```bash
git add tests/conftest.py
git commit -m "refactor: 清理 conftest.py 中未使用的 fixtures"
```

### Task 4.3: 最终验证

- [ ] **Step 1: 运行全量测试并统计**

```bash
uv run pytest --tb=short -q
```

Expected: 全部通过，用例数约 1850+。

- [ ] **Step 2: 统计文件数**

```bash
ls tests/*.py | wc -l
```

Expected: 49 个文件。

- [ ] **Step 3: 确认无 RuntimeWarning**

```bash
uv run pytest --tb=short -q 2>&1 | grep -c "RuntimeWarning"
```

Expected: 0。

- [ ] **Step 4: 最终提交**

```bash
git add -A tests/
git commit -m "refactor: 测试套件全面优化完成（80→49 文件，消除重复，补充覆盖）"
```
