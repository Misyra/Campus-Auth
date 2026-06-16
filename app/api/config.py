"""配置路由 — 配置的读取和保存。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from app.deps import get_monitor_service, get_profile_service
from app.schemas import ActionResponse, MonitorConfigPayload, ProfilesData
from app.services.config_service import save_config_combined
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
        return {"success": True, "message": f"已设置全局级别为 {level}"}

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
        lambda d: setattr(d.global_settings, "source_levels", config.get_all_source_levels())
    )


@router.get("/api/config", response_model=MonitorConfigPayload)
def get_config(
    svc: ScheduleEngine = Depends(get_monitor_service),
) -> MonitorConfigPayload:
    return svc.get_config()


@router.get("/api/config/default-stealth-script")
def get_default_stealth_script() -> dict:
    """获取默认反检测脚本内容。"""
    from app.utils.browser import STEALTH_INIT_SCRIPT

    return {"script": STEALTH_INIT_SCRIPT}


def _log_config_changes(old_dict: dict, new_payload: MonitorConfigPayload) -> None:
    """记录配置变更日志

    规则：
    - bool 字段：显示前后状态（开启/关闭）
    - int/float/string 字段：只记录"已修改"
    - password 字段：完全忽略
    """
    FIELD_NAMES = {
        "headless": "无头模式",
        "pure_mode": "纯净模式",
        "stealth_mode": "反检测模式",
        "browser_low_resource_mode": "低资源模式",
        "browser_disable_web_security": "禁用同源策略",
        "enable_tcp_check": "TCP检测",
        "enable_http_check": "HTTP检测",
        "enable_local_check": "本地网络检测",
        "check_auth_url": "认证地址检测",
        "pause_enabled": "暂停时段",
        "block_proxy": "屏蔽系统代理",
        "minimize_to_tray": "最小化到托盘",
        "auto_open_browser": "自动打开浏览器",
        "autostart_lightweight": "自启动轻量模式",
        "access_log": "HTTP访问日志",
        "browser_channel": "浏览器类型",
        "browser_timeout": "浏览器超时",
        "browser_navigation_timeout": "页面加载超时",
        "login_timeout": "登录超时",
        "check_interval_seconds": "检测间隔",
        "max_retries": "最大重试次数",
        "retry_interval": "重试间隔",
        "log_retention_days": "日志保留天数",
        "backend_log_level": "后端日志级别",
        "frontend_log_level": "前端日志级别",
        "app_port": "网页端口",
        "proxy": "网络代理",
        "shell_path": "Shell路径",
        "browser_viewport_width": "视口宽度",
        "browser_viewport_height": "视口高度",
        "pause_start_hour": "暂停开始时间",
        "pause_end_hour": "暂停结束时间",
        "network_check_timeout": "网络检测超时",
    }

    # 直接忽略的字段（不记录变更）
    IGNORE_FIELDS = {"password"}

    new_dict = new_payload.model_dump()
    changes = []

    for field_name in old_dict:
        if field_name in IGNORE_FIELDS:
            continue

        old_val = old_dict.get(field_name)
        new_val = new_dict.get(field_name)

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

    if changes:
        config_logger.info("配置变更: {}", "; ".join(changes))


@router.put("/api/config", response_model=ActionResponse)
def save_config(
    payload: MonitorConfigPayload,
    svc: ScheduleEngine = Depends(get_monitor_service),
    profile_svc: ProfileService = Depends(get_profile_service),
) -> ActionResponse:
    try:
        # 获取当前配置用于比较（转为 dict）
        old_config = svc.get_config()
        old_dict = old_config.model_dump()

        # 备份当前配置，用于 reload 失败时回滚
        import copy

        backup_data = copy.deepcopy(profile_svc.load())

        # 原子化保存：系统设置 + 活动方案
        save_config_combined(payload, profile_svc)

        # 同步更新 MonitorService 运行时配置
        try:
            svc.reload_config()
        except Exception as reload_exc:
            # reload 失败：回滚磁盘配置并重新加载
            api_logger.error("配置重载失败，正在回滚: {}", reload_exc, exc_info=True)
            try:
                profile_svc.update(
                    lambda data: _rollback_config(data, backup_data)
                )
                svc.reload_config()
            except Exception as rollback_exc:
                api_logger.error(
                    "回滚失败（磁盘配置已回滚，运行时状态可能不一致）: {}",
                    rollback_exc,
                    exc_info=True,
                )
            raise reload_exc

        # 记录配置变更
        _log_config_changes(old_dict, payload)

        api_logger.info("配置已保存 -> success=True")
        return ActionResponse(success=True, message="配置保存成功")
    except ValueError as exc:
        api_logger.warning("配置更新被拒绝: {}", exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        api_logger.error("配置保存失败: {}", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"配置保存失败: {exc}") from exc


def _rollback_config(data: ProfilesData, backup_data: ProfilesData) -> None:
    """回滚配置到备份状态。

    使用逐字段赋值而非 __dict__.update，确保 Pydantic 内部状态
    （如 model_fields_set）保持一致。
    """
    for field_name in ProfilesData.model_fields:
        setattr(data, field_name, getattr(backup_data, field_name))
