"""测试 config_service —— 配置读写分离逻辑。"""

from __future__ import annotations


from backend.config_service import (
    build_runtime_config,
    load_runtime_config,
    load_ui_config,
    save_config_combined,
)
from backend.schemas import (
    MonitorConfigPayload,
    ProfileSettings,
    ProfilesData,
    SystemSettings,
)


# ---------------------------------------------------------------------------
# 辅助工具
# ---------------------------------------------------------------------------

class FakeProfileService:
    """模拟 ProfileService，允许在测试中直接注入 ProfilesData。"""

    def __init__(self, data: ProfilesData):
        self._data = data

    def load(self) -> ProfilesData:
        return self._data.model_copy(deep=True)

    def save(self, data: ProfilesData) -> None:
        self._data = data.model_copy(deep=True)

    def get_active_profile(self) -> ProfileSettings | None:
        profiles = self._data.profiles
        active_id = self._data.active_profile
        if active_id in profiles:
            return profiles[active_id].model_copy(deep=True)
        if profiles:
            first_id = next(iter(profiles))
            return profiles[first_id].model_copy(deep=True)
        return None

    def get_active_profile_id(self) -> str:
        return self._data.active_profile

    def save_profile(self, profile_id: str, settings: ProfileSettings):
        self._data.profiles[profile_id] = settings.model_copy(deep=True)


def _make_data(
    active_profile: str = "default",
    *,
    sys_username: str = "system_user",
    sys_password: str = "system_pass",
    sys_auth_url: str = "http://system.url",
    sys_carrier: str = "移动",
    sys_carrier_custom: str = "",
    default_headless: bool = True,
    default_browser_timeout: int = 8000,
    default_pause_enabled: bool = False,
) -> ProfilesData:
    """构建一份带有 default 方案的测试数据。"""
    return ProfilesData(
        auto_switch=False,
        active_profile=active_profile,
        system=SystemSettings(
            username=sys_username,
            password=sys_password,
            auth_url=sys_auth_url,
            carrier=sys_carrier,
            carrier_custom=sys_carrier_custom,
        ),
        profiles={
            "default": ProfileSettings(
                name="默认方案",
                headless=default_headless,
                browser_timeout=default_browser_timeout,
                pause_enabled=default_pause_enabled,
                use_global_advanced=False,
            ),
        },
    )


# ---------------------------------------------------------------------------
# load_ui_config —— 始终返回全局设置
# ---------------------------------------------------------------------------

class TestLoadUiConfig:
    """设置页面：无论活动方案如何，始终返回 system + default 方案的全局配置。"""

    def test_returns_global_credentials_regardless_of_profile(self):
        """活动方案有自己的凭证时，UI 仍返回全局凭证。"""
        data = _make_data(active_profile="xft")
        data.profiles["xft"] = ProfileSettings(
            name="XFT 方案",
            username="xft_user",
            password="xft_pass",
            use_global_credentials=False,
            use_global_advanced=True,
        )
        svc = FakeProfileService(data)
        ui = load_ui_config(svc)

        assert ui.username == "system_user"
        assert ui.use_global_credentials is True

    def test_returns_global_auth_url_regardless_of_profile(self):
        """活动方案有独立认证地址时，UI 仍返回全局地址。"""
        data = _make_data(active_profile="xft")
        data.profiles["xft"] = ProfileSettings(
            name="XFT 方案",
            auth_url="http://xft.auth",
            use_global_auth_url=False,
            use_global_advanced=True,
        )
        svc = FakeProfileService(data)
        ui = load_ui_config(svc)

        assert ui.auth_url == "http://system.url"

    def test_returns_global_carrier_regardless_of_profile(self):
        """活动方案有独立运营商时，UI 仍返回全局运营商。"""
        data = _make_data(active_profile="xft")
        data.profiles["xft"] = ProfileSettings(
            name="XFT 方案",
            carrier="联通",
            use_global_credentials=False,
            use_global_advanced=True,
        )
        svc = FakeProfileService(data)
        ui = load_ui_config(svc)

        assert ui.carrier == "移动"

    def test_returns_default_profile_advanced_settings(self):
        """高级设置始终从 default 方案读取。"""
        data = _make_data(default_headless=False, default_browser_timeout=12000)
        data.profiles["xft"] = ProfileSettings(
            name="XFT 方案",
            headless=True,
            browser_timeout=5000,
            use_global_advanced=True,
        )
        data.active_profile = "xft"
        svc = FakeProfileService(data)
        ui = load_ui_config(svc)

        assert ui.headless is False       # 来自 default
        assert ui.browser_timeout == 12000  # 来自 default

    def test_active_task_is_always_empty(self):
        """全局设置不绑定特定任务。"""
        data = _make_data(active_profile="xft")
        data.profiles["xft"] = ProfileSettings(
            name="XFT 方案",
            active_task="custom_task",
            use_global_task=False,
            use_global_advanced=True,
        )
        svc = FakeProfileService(data)
        ui = load_ui_config(svc)

        assert ui.active_task == ""


# ---------------------------------------------------------------------------
# load_runtime_config —— 按 use_global_* 标志合并
# ---------------------------------------------------------------------------

class TestLoadRuntimeConfig:
    """运行时配置：根据活动方案的 use_global_* 标志决定取值来源。"""

    def test_uses_profile_credentials_when_not_global(self):
        """use_global_credentials=False 时使用方案独立凭证。"""
        data = _make_data(active_profile="xft")
        data.profiles["xft"] = ProfileSettings(
            name="XFT 方案",
            username="xft_user",
            password="xft_pass",
            use_global_credentials=False,
            use_global_advanced=True,
        )
        svc = FakeProfileService(data)
        rt = load_runtime_config(svc)

        assert rt.username == "xft_user"
        assert rt.use_global_credentials is False

    def test_uses_global_credentials_when_not_overridden(self):
        """use_global_credentials=True 时使用全局凭证。"""
        data = _make_data(active_profile="xft")
        data.profiles["xft"] = ProfileSettings(
            name="XFT 方案",
            use_global_credentials=True,
            use_global_advanced=True,
        )
        svc = FakeProfileService(data)
        rt = load_runtime_config(svc)

        assert rt.username == "system_user"
        assert rt.use_global_credentials is True

    def test_uses_profile_auth_url_when_not_global(self):
        """use_global_auth_url=False 时使用方案独立地址。"""
        data = _make_data(active_profile="xft")
        data.profiles["xft"] = ProfileSettings(
            name="XFT 方案",
            auth_url="http://xft.auth",
            use_global_auth_url=False,
            use_global_advanced=True,
        )
        svc = FakeProfileService(data)
        rt = load_runtime_config(svc)

        assert rt.auth_url == "http://xft.auth"

    def test_uses_profile_advanced_when_not_global(self):
        """use_global_advanced=False 时使用方案独立高级设置。"""
        data = _make_data(default_headless=True, default_browser_timeout=8000)
        data.profiles["xft"] = ProfileSettings(
            name="XFT 方案",
            headless=False,
            browser_timeout=3000,
            use_global_advanced=False,
        )
        data.active_profile = "xft"
        svc = FakeProfileService(data)
        rt = load_runtime_config(svc)

        assert rt.headless is False
        assert rt.browser_timeout == 3000

    def test_uses_default_advanced_when_global(self):
        """use_global_advanced=True 时使用 default 方案的高级设置。"""
        data = _make_data(default_headless=True)
        data.profiles["xft"] = ProfileSettings(
            name="XFT 方案",
            headless=False,
            use_global_advanced=True,
        )
        data.active_profile = "xft"
        svc = FakeProfileService(data)
        rt = load_runtime_config(svc)

        assert rt.headless is True  # 来自 default

    def test_falls_back_to_default_profile_when_default_missing(self):
        """没有 default 方案时使用 ProfileSettings 默认值。"""
        data = _make_data(active_profile="only")
        data.profiles = {
            "only": ProfileSettings(
                name="唯一方案",
                headless=False,
                use_global_advanced=True,
            ),
        }
        svc = FakeProfileService(data)
        rt = load_runtime_config(svc)

        # use_global_advanced=True 但没有 default 方案 → 走 else 分支，取 ProfileSettings() 默认值
        assert rt.headless is True  # ProfileSettings 默认值


# ---------------------------------------------------------------------------
# save_config_combined —— 始终写入全局
# ---------------------------------------------------------------------------

class TestSaveConfigCombined:
    """设置页面保存：始终写入 system + default 方案，不修改活动方案独立字段。"""

    def test_saves_advanced_to_default_profile(self):
        """headless 等高级设置写入 default 方案。"""
        data = _make_data(default_headless=True, active_profile="xft")
        data.profiles["xft"] = ProfileSettings(
            name="XFT 方案",
            headless=True,
            use_global_advanced=True,
        )
        svc = FakeProfileService(data)

        payload = MonitorConfigPayload(headless=False, browser_timeout=5000)
        save_config_combined(payload, svc)

        saved = svc.load()
        assert saved.profiles["default"].headless is False
        assert saved.profiles["default"].browser_timeout == 5000

    def test_does_not_modify_active_profile_advanced_fields(self):
        """活动方案的高级字段保持不变。"""
        data = _make_data(default_headless=True, active_profile="xft")
        data.profiles["xft"] = ProfileSettings(
            name="XFT 方案",
            headless=True,
            browser_timeout=3000,
            use_global_advanced=True,
        )
        svc = FakeProfileService(data)

        payload = MonitorConfigPayload(headless=False, browser_timeout=5000)
        save_config_combined(payload, svc)

        saved = svc.load()
        # XFT 方案的高级字段仍保持原值
        assert saved.profiles["xft"].headless is True
        assert saved.profiles["xft"].browser_timeout == 3000

    def test_saves_credentials_to_system(self):
        """凭证始终写入 system。"""
        data = _make_data(active_profile="xft")
        svc = FakeProfileService(data)

        payload = MonitorConfigPayload(username="new_user", password="new_pass")
        save_config_combined(payload, svc)

        saved = svc.load()
        assert saved.system.username == "new_user"
        # 密码被加密为 ENC: 格式
        assert saved.system.password.startswith("ENC:")

    def test_saves_auth_url_to_system(self):
        """认证地址始终写入 system。"""
        data = _make_data(active_profile="xft")
        svc = FakeProfileService(data)

        payload = MonitorConfigPayload(auth_url="http://new.url")
        save_config_combined(payload, svc)

        saved = svc.load()
        assert saved.system.auth_url == "http://new.url"

    def test_saves_carrier_to_system(self):
        """运营商始终写入 system。"""
        data = _make_data(active_profile="xft")
        svc = FakeProfileService(data)

        payload = MonitorConfigPayload(carrier="联通")
        save_config_combined(payload, svc)

        saved = svc.load()
        assert saved.system.carrier == "联通"

    def test_keeps_password_when_masked(self):
        """掩码密码不覆盖已有加密密码。"""
        data = _make_data(active_profile="xft")
        # system_pass 是明文，需先将其变为 ENC 格式来模拟已有加密密码的场景
        from src.utils.crypto import encrypt_password
        data.system.password = encrypt_password("system_pass")
        svc = FakeProfileService(data)

        # 模拟前端返回掩码密码
        payload = MonitorConfigPayload(username="u", password="••••")
        save_config_combined(payload, svc)

        saved = svc.load()
        # 掩码应保留已有加密密码
        assert saved.system.password == data.system.password
        assert saved.system.password.startswith("ENC:")


# ---------------------------------------------------------------------------
# 端到端：设置页面关闭无头 → 保存 → 刷新
# ---------------------------------------------------------------------------

class TestHeadlessBugFix:
    """复现原 bug 场景：use_global_advanced=True 时，前端关掉无头保存后刷新不再还原。"""

    def test_headless_stays_off_after_save_and_reload(self):
        """核心场景：关闭无头 → 保存 → 刷新，headless 仍为 false。"""
        # 初始状态：default 方案 headless=true，XFT 方案 use_global_advanced=true
        data = _make_data(default_headless=True, active_profile="xft")
        data.profiles["xft"] = ProfileSettings(
            name="XFT 方案",
            use_global_advanced=True,
            headless=True,
        )
        svc = FakeProfileService(data)

        # 1. 设置页面显示 global headless=true
        ui_before = load_ui_config(svc)
        assert ui_before.headless is True

        # 2. 用户关闭无头并保存
        payload = MonitorConfigPayload(
            username="system_user",
            headless=False,
            use_global_credentials=True,
        )
        save_config_combined(payload, svc)

        # 3. 验证 default 方案的 headless 已更新
        saved = svc.load()
        assert saved.profiles["default"].headless is False

        # 4. 刷新设置页面 — headless 应仍是 false
        ui_after = load_ui_config(svc)
        assert ui_after.headless is False


# ---------------------------------------------------------------------------
# build_runtime_config —— 从 Payload 构建运行时配置字典
# ---------------------------------------------------------------------------

class TestBuildRuntimeConfig:
    """build_runtime_config：将 MonitorConfigPayload + SystemSettings 转为运行时 dict。"""

    def _make_payload(self, **overrides) -> MonitorConfigPayload:
        """构建带合理默认值的 payload，允许覆盖任意字段。"""
        defaults = dict(
            username="test_user",
            password="decrypted_pass",
            auth_url="http://test.auth",
            carrier="移动",
            carrier_custom="",
            auto_start=True,
            headless=False,
            browser_timeout=10000,
            browser_user_agent="TestAgent/1.0",
            browser_low_resource_mode=True,
            browser_disable_web_security=True,
            browser_extra_headers_json="",
            browser_args="--test-arg",
            stealth_mode=True,
            pause_enabled=True,
            pause_start_hour=1,
            pause_end_hour=5,
            check_interval_minutes=10,
            network_targets="1.1.1.1:53",
            network_strict_mode=False,
            backend_log_level="DEBUG",
            frontend_log_level="DEBUG",
            access_log=True,
            minimize_to_tray=False,
            login_then_exit=True,
            log_retention_days=14,
            screenshot_retention_days=14,
            custom_variables={"key": "val"},
            active_task="",
        )
        defaults.update(overrides)
        return MonitorConfigPayload(**defaults)

    def test_uses_decrypted_password_directly(self):
        """payload.password 是明文（非掩码）时，直接使用。"""
        payload = self._make_payload(password="plain_secret")
        sys = SystemSettings(password="")
        config = build_runtime_config(payload, sys)
        assert config["password"] == "plain_secret"

    def test_falls_back_to_sys_password_when_empty(self):
        """payload.password 为空且 sys.password 有值时，解密 sys.password。"""
        from src.utils.crypto import encrypt_password
        payload = self._make_payload(password="")
        sys = SystemSettings(password=encrypt_password("sys_secret"))
        config = build_runtime_config(payload, sys)
        assert config["password"] == "sys_secret"

    def test_empty_password_when_both_empty(self):
        """payload.password 和 sys.password 都为空时，密码为空字符串。"""
        payload = self._make_payload(password="")
        sys = SystemSettings(password="")
        config = build_runtime_config(payload, sys)
        assert config["password"] == ""

    def test_username_and_auth_url_passed_through(self):
        """username 和 auth_url 从 payload 正确传递到运行时配置。"""
        payload = self._make_payload(username="my_user", auth_url="http://my.auth/login")
        sys = SystemSettings(password="")
        config = build_runtime_config(payload, sys)
        assert config["username"] == "my_user"
        assert config["auth_url"] == "http://my.auth/login"

    def test_browser_settings_configured(self):
        """浏览器设置从 payload 正确填充到 browser_settings 子字典。"""
        payload = self._make_payload(
            headless=False,
            browser_timeout=15000,
            browser_user_agent="CustomAgent/2.0",
            browser_low_resource_mode=True,
            browser_disable_web_security=False,
            stealth_mode=True,
        )
        sys = SystemSettings(password="")
        config = build_runtime_config(payload, sys)
        browser = config["browser_settings"]
        assert browser["headless"] is False
        assert browser["timeout"] == 15000
        assert browser["user_agent"] == "CustomAgent/2.0"
        assert browser["low_resource_mode"] is True
        assert browser["disable_web_security"] is False
        assert browser["stealth_mode"] is True
