"""配置路由 — 配置的读取和保存。"""

from __future__ import annotations

from contextlib import contextmanager

from fastapi import APIRouter, HTTPException, Request

from app.deps import MonitorServiceDep, ProfileServiceDep
from app.schemas import (
    ApiResponse,
    AppSettings,
    BrowserSettings,
    ConfigPatchRequest,
    ConfigResponse,
    ConfigSaveRequest,
    LoggingSettings,
    LogLevelRequest,
    LogLevelResponse,
    MonitorSettings,
    PauseSettings,
    RetrySettings,
    StealthScriptResponse,
)
from app.services.profile_service import save_global_and_profile
from app.utils.logging import get_logger

router = APIRouter(tags=["配置"])
api_logger = get_logger("api", source="backend")
config_logger = get_logger("config", source="backend")


@contextmanager
def _handle_config_error(operation: str, *, log_warning: bool = False):
    """统一配置端点的 ValueError / 通用异常处理。"""
    try:
        yield
    except ValueError as exc:
        if log_warning:
            api_logger.warning("配置更新被拒绝: {}", exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        api_logger.warning("{}失败: {}", operation, exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"{operation}失败: {exc}") from exc


@router.get("/api/config/log-levels", response_model=LogLevelResponse)
def get_log_levels() -> LogLevelResponse:
    from app.utils.logging import LogConfigCenter

    config = LogConfigCenter.get_instance()
    return LogLevelResponse(level=config.get_config().get("level", "INFO"))


@router.put("/api/config/log-level", response_model=ApiResponse)
def set_log_level(payload: LogLevelRequest, request: Request) -> ApiResponse:
    from app.utils.logging import VALID_LOG_LEVELS, LogConfigCenter

    requested = payload.level.strip().upper()
    if requested not in VALID_LOG_LEVELS:
        # 无效级别直接拒绝，避免 set_level 静默降级后仍返回 success=True（BUG-081）
        raise HTTPException(status_code=400, detail=f"无效的日志级别: {payload.level}")
    config = LogConfigCenter.get_instance()
    config.set_level(requested)
    actual = config.get_config().get("level", "INFO")
    profile_service = request.app.state.services.profile_service
    profile_service.update(
        lambda d: d.model_copy(
            update={
                "global_config": d.global_config.model_copy(
                    update={
                        "logging": d.global_config.logging.model_copy(
                            update={"level": actual}
                        ),
                    }
                ),
            }
        )
    )
    # 同步更新引擎运行时配置（经公共方法，不再裸改私有属性）
    engine = request.app.state.services.engine
    engine.update_log_level(actual)
    return ApiResponse(success=True, message=f"已设置全局日志级别为 {actual}")


@router.get("/api/config", response_model=ConfigResponse)
def get_config(
    svc: MonitorServiceDep,
    profile_svc: ProfileServiceDep,
) -> ConfigResponse:
    data = profile_svc.load()
    cfg = profile_svc.build_runtime_config(data)

    profile = profile_svc.get_active_profile()
    carrier = profile.carrier or "无"
    isp = "" if carrier == "无" else carrier

    return ConfigResponse(
        browser=cfg.browser.model_dump(),
        monitor=cfg.monitor.model_dump(),
        retry=cfg.retry.model_dump(),
        pause=cfg.pause.model_dump(),
        logging=cfg.logging.model_dump(),
        app_settings=cfg.app_settings.model_dump(),
        username=cfg.credentials.username,
        password="",
        has_password=bool(profile.password),
        auth_url=cfg.credentials.auth_url,
        isp=isp,
        carrier_custom=cfg.credentials.carrier_custom,
        active_task=cfg.active_task,
    )


@router.get("/api/config/default-stealth-script", response_model=StealthScriptResponse)
def get_default_stealth_script() -> StealthScriptResponse:
    """获取默认反检测脚本内容。"""
    from app.utils.browser import STEALTH_INIT_SCRIPT

    return StealthScriptResponse(script=STEALTH_INIT_SCRIPT)


@router.get("/api/config/defaults")
def get_config_defaults() -> dict:
    """获取所有配置字段的默认值。"""
    return {
        "browser": BrowserSettings().model_dump(),
        "monitor": MonitorSettings().model_dump(),
        "retry": RetrySettings().model_dump(),
        "pause": PauseSettings().model_dump(),
        "logging": LoggingSettings().model_dump(),
        "app_settings": AppSettings().model_dump(),
    }


def _flatten_dict(d: dict, parent_key: str = "") -> dict:
    """将嵌套字典扁平化为点分键。"""
    items: list[tuple[str, object]] = []
    for k, v in d.items():
        new_key = f"{parent_key}.{k}" if parent_key else k
        if isinstance(v, dict):
            items.extend(_flatten_dict(v, new_key).items())
        else:
            items.append((new_key, v))
    return dict(items)


# 配置字段中文名称映射（用于变更日志）
_CONFIG_FIELD_NAMES = {
    "browser.headless": "无头模式",
    "browser.pure_mode": "纯净模式",
    "browser.stealth_mode": "反检测模式",
    "browser.low_resource_mode": "低资源模式",
    "browser.disable_web_security": "禁用同源策略",
    "monitor.enable_tcp_check": "TCP检测",
    "monitor.enable_http_check": "HTTP检测",
    "monitor.enable_local_check": "本地网络检测",
    "monitor.check_auth_url": "认证地址检测",
    "pause.enabled": "暂停时段",
    "app_settings.block_proxy": "屏蔽系统代理",
    "app_settings.minimize_to_tray": "最小化到托盘",
    "app_settings.auto_open_browser": "自动打开浏览器",
    "app_settings.runtime_mode": "自启动运行模式",
    "logging.access_log": "HTTP访问日志",
    "browser.browser_channel": "浏览器类型",
    "browser.timeout": "浏览器超时",
    "browser.navigation_timeout": "页面加载超时",
    "browser.login_timeout": "登录超时",
    "monitor.check_interval_seconds": "检测间隔",
    "retry.max_retries": "最大重试次数",
    "retry.retry_interval": "重试间隔",
    "logging.log_retention_days": "日志保留天数",
    "logging.level": "后端日志级别",
    "app_settings.app_port": "网页端口",
    "app_settings.proxy": "网络代理",
    "browser.viewport_width": "视口宽度",
    "browser.viewport_height": "视口高度",
    "pause.start_hour": "暂停开始时间",
    "pause.end_hour": "暂停结束时间",
    "monitor.network_check_timeout": "网络检测超时",
    "isp": "运营商",
    "carrier_custom": "自定义运营商",
}

# 变更日志中直接忽略的字段
_CONFIG_IGNORE_FIELDS = {"password"}


def _diff_config_changes(flat_old: dict, flat_new: dict) -> list[str]:
    """比较新旧扁平化配置，返回变更描述列表。"""
    changes: list[str] = []

    # 密码变更检测
    new_pw = flat_new.get("password", "")
    old_pw = flat_old.get("password", "")
    if new_pw and old_pw != new_pw:
        changes.append("密码已修改")

    for field_name in flat_old:
        if field_name in _CONFIG_IGNORE_FIELDS:
            continue
        old_val = flat_old.get(field_name)
        new_val = flat_new.get(field_name)
        if old_val == new_val:
            continue
        name = _CONFIG_FIELD_NAMES.get(field_name, field_name)
        if isinstance(new_val, bool):
            old_status = "开启" if old_val else "关闭"
            new_status = "开启" if new_val else "关闭"
            changes.append(f"{name}: {old_status} → {new_status}")
        else:
            changes.append(f"{name}已修改")

    for field_name in flat_new:
        if field_name in flat_old or field_name in _CONFIG_IGNORE_FIELDS:
            continue
        new_val = flat_new.get(field_name)
        if new_val:
            name = _CONFIG_FIELD_NAMES.get(field_name, field_name)
            changes.append(f"{name}已设置")

    return changes


def _log_config_changes(old_dict: dict, new_payload: ConfigSaveRequest) -> None:
    """记录配置变更日志。

    规则：
    - bool 字段：显示前后状态（开启/关闭）
    - int/float/string 字段：只记录"已修改"
    - password 字段：完全忽略
    """
    # BUG-005 修复：扁平化嵌套字典后再比较
    # old_dict 来自 RuntimeConfig（credentials 嵌套），new_payload 来自 ConfigSaveRequest（凭据平铺）
    # 需要将 old_dict 的 credentials 扁平化到顶层后再比较
    _old = dict(old_dict)
    _old_creds = _old.pop("credentials", {})
    _old.update(_old_creds)
    flat_old = _flatten_dict(_old)
    flat_new = _flatten_dict(new_payload.model_dump())

    changes = _diff_config_changes(flat_old, flat_new)
    if changes:
        config_logger.debug("配置变更: {}", "; ".join(changes))


@router.put("/api/config", response_model=ApiResponse)
def save_config(
    payload: ConfigSaveRequest,
    svc: MonitorServiceDep,
    profile_svc: ProfileServiceDep,
) -> ApiResponse:
    with _handle_config_error("配置保存", log_warning=True):
        old_data = profile_svc.load()
        old_cfg = profile_svc.build_runtime_config(old_data)
        old_dict = old_cfg.model_dump()

        result = save_global_and_profile(payload, profile_svc, svc.reload_config)
        if not result.success:
            raise ValueError(result.message)

        _log_config_changes(old_dict, payload)

        api_logger.info("保存配置成功")
        return ApiResponse(success=True, message="配置保存成功")


@router.patch("/api/config", response_model=ApiResponse)
def patch_config(
    payload: ConfigPatchRequest,
    svc: MonitorServiceDep,
    profile_svc: ProfileServiceDep,
) -> ApiResponse:
    """增量更新配置 — 仅修改 payload 中非 None 的字段。"""
    with _handle_config_error("配置增量保存"):
        old_data = profile_svc.load()
        old_cfg = profile_svc.build_runtime_config(old_data)

        current = old_cfg.model_dump()
        # 将 credentials 扁平化到顶层，与 ConfigSaveRequest/ConfigPatchRequest 的平铺结构对齐
        # 否则 merged 顶层缺失 username/auth_url/isp/carrier_custom，ConfigSaveRequest 取默认空串，
        # save_global_and_profile 会用空串覆盖已有凭据（BUG-027）
        creds = current.pop("credentials", {})
        current.update(creds)
        # password 空串语义为不修改（见 save_password_field），不回填运行时明文以免无谓重新加密
        current["password"] = ""

        patch_data = payload.model_dump(exclude_none=True)

        merged = {**current, **patch_data}
        for key in ("browser", "monitor", "retry", "pause", "logging", "app_settings"):
            if key in patch_data:
                merged[key] = {**current.get(key, {}), **patch_data[key]}

        full_request = ConfigSaveRequest.model_validate(merged)
        result = save_global_and_profile(full_request, profile_svc, svc.reload_config)
        if not result.success:
            raise ValueError(result.message)

        _log_config_changes(old_cfg.model_dump(), full_request)
        api_logger.info("配置增量保存成功 (fields={})", list(patch_data.keys()))
        return ApiResponse(
            success=True,
            message="配置保存成功",
            data={"patched": list(patch_data.keys())},
        )
