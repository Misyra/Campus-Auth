"""配置路由 — 配置的读取和保存。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.deps import get_monitor_service, get_profile_service
from app.schemas import ActionResponse, MonitorConfigPayload
from app.services.config import save_config_combined
from app.services.engine import ScheduleEngine
from app.services.profile import ProfileService
from app.utils.logging import get_logger

router = APIRouter()
api_logger = get_logger("api", source="backend")


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


@router.put("/api/config", response_model=ActionResponse)
def save_config(
    payload: MonitorConfigPayload,
    svc: ScheduleEngine = Depends(get_monitor_service),
    profile_svc: ProfileService = Depends(get_profile_service),
) -> ActionResponse:
    try:
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
                profile_svc.update(lambda data: data.__dict__.update(backup_data.__dict__))
                svc.reload_config()
            except Exception:
                api_logger.error("回滚失败", exc_info=True)
            raise reload_exc

        api_logger.info("配置已保存 -> success=True")
        return ActionResponse(success=True, message="配置保存成功")
    except ValueError as exc:
        api_logger.warning("配置更新被拒绝: {}", exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        api_logger.error("配置保存失败: {}", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"配置保存失败: {exc}") from exc
