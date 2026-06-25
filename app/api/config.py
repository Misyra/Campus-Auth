"""配置路由 — 配置的读取和保存。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from app.deps import get_monitor_service, get_profile_service
from app.schemas import ActionResponse, ConfigResponseDTO
from app.services.config_service import save_global_and_profile
from app.services.engine import ScheduleEngine
from app.services.profile_service import ProfileService
from app.utils.logging import get_logger

router = APIRouter()
api_logger = get_logger("api", source="backend")
config_logger = get_logger("config", source="backend")


@router.get("/api/config/log-levels")
def get_log_levels():
    """获取日志级别配置"""
    from app.utils.logging import LogConfigCenter

    config = LogConfigCenter.get_instance()
    return {
        "global_level": config.get_config().get("level", "INFO"),
        "source_levels": config.get_all_source_levels(),
    }


@router.put("/api/config/source-level")
def set_source_level(payload: dict, request: Request):
    """设置日志级别。source='global' 时设置全局级别，否则设置来源级别。"""
    from app.utils.logging import LogConfigCenter

    source = payload.get("source")
    level = payload.get("level")

    if not source or not level:
        raise HTTPException(400, "缺少 source 或 level 参数")

    config = LogConfigCenter.get_instance()

    if source == "global":
        config.set_level(level)
        actual = config.get_config().get("level", "INFO")
        if actual != level.upper():
            return {"success": True, "message": f"无效级别 '{level}'，已降级为 {actual}"}
    else:
        try:
            config.set_source_level(source, level)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e

    _persist_source_levels(request, config)

    return {"success": True, "message": f"已设置 {source} 级别为 {level}"}


def _persist_source_levels(request: Request, config):
    """将 source_levels 持久化到 settings.json"""
    profile_service = request.app.state.services.profile_service
    profile_service.update(
        lambda d: setattr(d.global_config, "logging", d.global_config.logging.model_copy(update={"source_levels": config.get_all_source_levels()}))
    )


@router.get("/api/config")
def get_config(
    svc: ScheduleEngine = Depends(get_monitor_service),
    profile_svc: ProfileService = Depends(get_profile_service),
) -> dict:
    data = profile_svc.load()
    cfg = profile_svc.build_runtime_config(data)

    # 从 Profile 获取原始 carrier 值（前端下拉框需要 "自定义" 而不是转换后的 isp）
    profile = profile_svc.get_active_profile()
    carrier = profile.carrier or "无"
    # 映射到前端 isp 值：carrier 为 "无" 时返回空串，其他返回原值
    isp = "" if carrier == "无" else carrier

    dto = ConfigResponseDTO(
        browser=cfg.browser,
        monitor=cfg.monitor,
        retry=cfg.retry,
        pause=cfg.pause,
        logging=cfg.logging,
        app_settings=cfg.app_settings,
        username=cfg.credentials.username,
        password="••••••••" if cfg.credentials.password else "",
        auth_url=cfg.credentials.auth_url,
        isp=isp,
        carrier_custom=cfg.credentials.carrier_custom,
        active_task=cfg.active_task,
    )
    # 展平 app_settings 到顶层，保持前端兼容
    return _dto_to_flat_dict(dto)


def _dto_to_flat_dict(dto: ConfigResponseDTO) -> dict:
    """将 ConfigResponseDTO 转为前端兼容的扁平字典（app_settings 展开到顶层）。"""
    d = dto.model_dump()
    app = d.pop("app_settings", {})
    d.update(app)
    return d


# 前端扁平字段中属于 app_settings 的字段列表
_APP_SETTINGS_KEYS = {
    "block_proxy", "shell_path", "minimize_to_tray", "startup_action",
    "autostart_lightweight", "lightweight_tray", "auto_open_browser",
    "proxy", "app_port", "custom_variables",
}


def _flat_dict_to_dto(d: dict) -> ConfigResponseDTO:
    """将前端扁平字典转为 ConfigResponseDTO（提取 app_settings 子对象）。"""
    app_settings = {}
    rest = {}
    for k, v in d.items():
        if k in _APP_SETTINGS_KEYS:
            app_settings[k] = v
        else:
            rest[k] = v
    rest["app_settings"] = app_settings
    return ConfigResponseDTO(**rest)


@router.get("/api/config/default-stealth-script")
def get_default_stealth_script() -> dict:
    """获取默认反检测脚本内容。"""
    from app.utils.browser import STEALTH_INIT_SCRIPT

    return {"script": STEALTH_INIT_SCRIPT}


def _flatten_dict(d: dict, parent_key: str = "", sep: str = ".") -> dict:
    """将嵌套字典扁平化为点分键。"""
    items: list[tuple[str, object]] = []
    for k, v in d.items():
        new_key = f"{parent_key}{sep}{k}" if parent_key else k
        if isinstance(v, dict):
            items.extend(_flatten_dict(v, new_key, sep).items())
        else:
            items.append((new_key, v))
    return dict(items)


def _log_config_changes(old_dict: dict, new_payload: ConfigResponseDTO) -> None:
    """记录配置变更日志

    规则：
    - bool 字段：显示前后状态（开启/关闭）
    - int/float/string 字段：只记录"已修改"
    - password 字段：完全忽略
    """
    FIELD_NAMES = {
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
        "app_settings.autostart_lightweight": "自启动轻量模式",
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
        "logging.frontend_level": "前端日志级别",
        "app_settings.app_port": "网页端口",
        "app_settings.proxy": "网络代理",
        "app_settings.shell_path": "Shell路径",
        "browser.viewport_width": "视口宽度",
        "browser.viewport_height": "视口高度",
        "pause.start_hour": "暂停开始时间",
        "pause.end_hour": "暂停结束时间",
        "monitor.network_check_timeout": "网络检测超时",
        "isp": "运营商",
        "carrier_custom": "自定义运营商",
    }

    # 直接忽略的字段（不记录变更）
    IGNORE_FIELDS = {"password"}

    # BUG-005 修复：扁平化嵌套字典后再比较
    # old_dict 来自 RuntimeConfig（credentials 嵌套），new_payload 来自 ConfigResponseDTO（扁平）
    # 需要将 old_dict 的 credentials 扁平化到顶层后再比较
    _old = dict(old_dict)
    _old_creds = _old.pop("credentials", {})
    _old.update(_old_creds)
    flat_old = _flatten_dict(_old)
    flat_new = _flatten_dict(new_payload.model_dump())

    changes = []

    # 密码变更检测（顶层 password，不再嵌套在 credentials 下）
    new_pw = flat_new.get("password", "")
    old_pw = flat_old.get("password", "")
    if new_pw and not new_pw.startswith("•") and old_pw != new_pw:
        changes.append("密码已修改")

    for field_name in flat_old:
        if field_name in IGNORE_FIELDS:
            continue

        old_val = flat_old.get(field_name)
        new_val = flat_new.get(field_name)

        if old_val == new_val:
            continue

        name = FIELD_NAMES.get(field_name, field_name)

        # 布尔字段显示前后状态
        if isinstance(new_val, bool):
            old_status = "开启" if old_val else "关闭"
            new_status = "开启" if new_val else "关闭"
            changes.append(f"{name}: {old_status} → {new_status}")
        else:
            changes.append(f"{name}已修改")

    for field_name in flat_new:
        if field_name in flat_old or field_name in IGNORE_FIELDS:
            continue
        new_val = flat_new.get(field_name)
        if new_val:
            name = FIELD_NAMES.get(field_name, field_name)
            changes.append(f"{name}已设置")

    if changes:
        config_logger.info("配置变更: {}", "; ".join(changes))


@router.put("/api/config", response_model=ActionResponse)
def save_config(
    payload: dict,
    svc: ScheduleEngine = Depends(get_monitor_service),
    profile_svc: ProfileService = Depends(get_profile_service),
) -> ActionResponse:
    try:
        # 前端发送扁平字段，后端需嵌套 app_settings
        dto = _flat_dict_to_dto(payload)

        # 获取当前配置用于变更日志
        old_data = profile_svc.load()
        old_cfg = profile_svc.build_runtime_config(old_data)
        old_dict = old_cfg.model_dump()

        # 一次保存全局配置 + 方案凭据
        result = save_global_and_profile(dto, profile_svc, svc.reload_config)
        if not result.success:
            raise ValueError(result.message)

        # 记录配置变更
        _log_config_changes(old_dict, dto)

        api_logger.info("配置已保存 -> success=True")
        return ActionResponse(success=True, message="配置保存成功")
    except ValueError as exc:
        api_logger.warning("配置更新被拒绝: {}", exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        api_logger.error("配置保存失败: {}", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"配置保存失败: {exc}") from exc
