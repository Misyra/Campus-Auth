"""Container ConfigService 注入测试 — 验证 Task 3.3 的注入行为。

覆盖：
- Container 创建 ConfigService 实例
- Container 将 config_service 注入 ScheduleEngine
- login_orchestrator 构造时注入 config_service.get_runtime_config
- task_executor 构造时注入 config_service.get_runtime_config
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.schemas import BrowserSettings, GlobalConfig, ProfilesData, RuntimeConfig


def _make_profile_service_mock() -> MagicMock:
    """创建支持 ConfigService 初始化的 ProfileService mock。

    ConfigService.__init__ 会调用 profile_service.load() 和 build_runtime_config()，
    因此需要返回有效的 ProfilesData 和 RuntimeConfig。
    """
    ps = MagicMock()
    data = ProfilesData(
        global_config=GlobalConfig(browser=BrowserSettings(pure_mode=False)),
    )
    ps.load.return_value = data
    ps.build_runtime_config.return_value = RuntimeConfig(
        browser=BrowserSettings(pure_mode=False)
    )
    return ps


@contextmanager
def _patch_container_externals() -> Iterator[dict[str, MagicMock]]:
    """patch Container 的外部依赖（避免启动真实服务）。

    保留 ConfigService、LoginOrchestrator、TaskExecutor、ScheduleEngine 为真实实例，
    以验证构造时注入 get_runtime_config 与 _config_service 注入行为。

    真实实例依赖：
    - ConfigService 需要 profile_service.load() / build_runtime_config() → mock 配置好返回值
    - TaskExecutor 需要 registry/history_store/worker_getter 等 → 均为 MagicMock
    - LoginOrchestrator 需要 executor（来自 TaskExecutor.login_executor，真实 BoundedExecutor）
    - ScheduleEngine 仅在 __init__ 中存储引用，不启动线程
    """
    profile_service_mock = _make_profile_service_mock()
    with (
        patch("app.container.WebSocketManager") as mock_ws_cls,
        patch(
            "app.container.get_profile_service",
            return_value=profile_service_mock,
        ) as mock_profile_cls,
        patch("app.container.LoginHistoryService") as mock_lh_cls,
        patch("app.container.TaskManager") as mock_task_cls,
        patch("app.container.AutoStartService") as mock_autostart_cls,
        patch("app.container.TaskRegistry") as mock_tr_cls,
        patch("app.container.TaskHistoryStore") as mock_ths_cls,
        patch("app.services.debug_service.DebugSessionManager") as mock_debug_cls,
        patch("app.services.browser_task_service.BrowserTaskService") as mock_bts_cls,
        patch("app.services.scheduler_service.SchedulerService") as mock_sched_cls,
    ):
        yield {
            "profile_service": profile_service_mock,
            "ws_cls": mock_ws_cls,
            "profile_cls": mock_profile_cls,
            "lh_cls": mock_lh_cls,
            "task_cls": mock_task_cls,
            "autostart_cls": mock_autostart_cls,
            "tr_cls": mock_tr_cls,
            "ths_cls": mock_ths_cls,
            "debug_cls": mock_debug_cls,
            "bts_cls": mock_bts_cls,
            "sched_cls": mock_sched_cls,
        }


class TestContainerConfigService:
    """验证 Container 正确创建并注入 ConfigService。"""

    def test_container_creates_config_service(self, tmp_path: Path):
        """Container 应创建 ConfigService 实例。"""
        with _patch_container_externals():
            from app.container import ServiceContainer

            container = ServiceContainer(tmp_path)
            assert container.config_service is not None
            from app.services.config_service import ConfigService

            assert isinstance(container.config_service, ConfigService)

    def test_config_service_uses_profile_service(self, tmp_path: Path):
        """ConfigService 应基于 container 的 profile_service 创建。"""
        with _patch_container_externals() as mocks:
            from app.container import ServiceContainer

            container = ServiceContainer(tmp_path)
            # ConfigService 内部持有的 profile_service 应与 container 的相同
            assert container.config_service._profile_service is mocks["profile_service"]

    def test_container_injects_config_service_to_engine(self, tmp_path: Path):
        """Engine 应接收 config_service 注入。"""
        with _patch_container_externals():
            from app.container import ServiceContainer

            container = ServiceContainer(tmp_path)
            # ScheduleEngine 是真实实例，_config_service 应指向 container.config_service
            assert container.engine._config_service is container.config_service

    def test_login_orchestrator_binds_config_service(self, tmp_path: Path):
        """login_orchestrator 应在构造时注入 config_service.get_runtime_config。"""
        with _patch_container_externals():
            from app.container import ServiceContainer

            container = ServiceContainer(tmp_path)
            # 注入的 getter 应是 config_service.get_runtime_config（同一绑方法对象）
            assert (
                container.login_orchestrator._get_runtime_config
                == container.config_service.get_runtime_config
            )

    def test_task_executor_binds_config_service(self, tmp_path: Path):
        """task_executor 应在构造时注入 config_service.get_runtime_config。"""
        with _patch_container_externals():
            from app.container import ServiceContainer

            container = ServiceContainer(tmp_path)
            assert (
                container.task_executor._get_runtime_config
                == container.config_service.get_runtime_config
            )

    def test_login_orchestrator_not_binds_engine_get_runtime_config(
        self, tmp_path: Path
    ):
        """login_orchestrator 不应绑定 engine.get_runtime_config（回归保护）。"""
        with _patch_container_externals():
            from app.container import ServiceContainer

            container = ServiceContainer(tmp_path)
            # engine.get_runtime_config 仍存在（向后兼容），但不应是 orchestrator 的注入源
            assert (
                container.login_orchestrator._get_runtime_config
                != container.engine.get_runtime_config
            )

    def test_task_executor_not_binds_engine_get_runtime_config(self, tmp_path: Path):
        """task_executor 不应绑定 engine.get_runtime_config（回归保护，对称保护）。"""
        with _patch_container_externals():
            from app.container import ServiceContainer

            container = ServiceContainer(tmp_path)
            assert (
                container.task_executor._get_runtime_config
                != container.engine.get_runtime_config
            )
