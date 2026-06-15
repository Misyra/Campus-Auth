"""方案路由 — 配置方案的 CRUD、活动方案、网络检测、自动切换。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from app.deps import get_monitor_service, get_profile_service
from app.schemas import ActionResponse, ProfileSettings
from app.services.engine import ScheduleEngine
from app.services.profile_service import ProfileService
from app.utils.logging import get_logger

router = APIRouter()
api_logger = get_logger("api", source="backend")


def _safe_detect(func, label: str, default=None):
    """安全执行检测函数，异常时记录日志并返回默认值。"""
    try:
        return func()
    except Exception as exc:
        api_logger.error("{}检测异常: {}", label, exc)
        return default


@router.get("/api/profiles")
def list_profiles(
    profile_svc: ProfileService = Depends(get_profile_service),
) -> dict:
    data = profile_svc.load()
    result = {}
    for pid, settings in data.profiles.items():
        result[pid] = {
            "name": settings.name,
            "match_gateway_ip": settings.match_gateway_ip,
            "match_ssid": settings.match_ssid,
            "carrier": settings.carrier,
            "carrier_custom": settings.carrier_custom,
            "auth_url": settings.auth_url,
            "active_task": settings.active_task,
        }
    return {
        "profiles": result,
        "active_profile": data.active_profile,
        "auto_switch": data.auto_switch,
    }


@router.get("/api/profiles/{profile_id}")
def get_profile(
    profile_id: str,
    profile_svc: ProfileService = Depends(get_profile_service),
) -> dict:
    data = profile_svc.load()
    profile = data.profiles.get(profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="方案不存在")
    return {
        "profile_id": profile_id,
        "settings": profile.model_dump(),
    }


@router.put("/api/profiles/{profile_id}", response_model=ActionResponse)
def save_profile(
    profile_id: str,
    payload: ProfileSettings,
    profile_svc: ProfileService = Depends(get_profile_service),
    monitor_svc: ScheduleEngine = Depends(get_monitor_service),
) -> ActionResponse:
    ok, message = profile_svc.save_profile(profile_id, payload)
    api_logger.info("保存方案 {} -> success={}, message={}", profile_id, ok, message)
    if ok:
        data = profile_svc.load()
        if data.active_profile == profile_id:
            try:
                monitor_svc.apply_profile(profile_id)
            except Exception:
                api_logger.warning("保存方案后应用方案失败", exc_info=True)
    return ActionResponse(success=ok, message=message)


@router.delete("/api/profiles/{profile_id}", response_model=ActionResponse)
def delete_profile(
    profile_id: str,
    profile_svc: ProfileService = Depends(get_profile_service),
    monitor_svc: ScheduleEngine = Depends(get_monitor_service),
) -> ActionResponse:
    ok, message = profile_svc.delete_profile(profile_id)
    api_logger.info("删除方案 {} -> success={}, message={}", profile_id, ok, message)
    # 删除成功后始终通知监控重载配置（安全做法，避免 TOCTOU 竞态）
    if ok:
        try:
            new_data = profile_svc.load()
            monitor_svc.apply_profile(new_data.active_profile)
        except Exception:
            api_logger.warning("删除方案后应用方案失败", exc_info=True)
    return ActionResponse(success=ok, message=message)


@router.post("/api/profiles/active/{profile_id}", response_model=ActionResponse)
def set_active_profile(
    profile_id: str,
    profile_svc: ProfileService = Depends(get_profile_service),
    monitor_svc: ScheduleEngine = Depends(get_monitor_service),
) -> ActionResponse:
    ok, message = profile_svc.set_active_profile(profile_id)
    api_logger.info(
        "设置活动方案 {} -> success={}, message={}", profile_id, ok, message
    )
    if ok:
        try:
            # 统一传 profile_id，apply_profile 内部解析名称用于日志
            monitor_svc.apply_profile(profile_id)
        except Exception:
            api_logger.warning("应用方案失败", exc_info=True)
    return ActionResponse(success=ok, message=message)


@router.post("/api/profiles/detect")
def detect_network_profile(
    profile_svc: ProfileService = Depends(get_profile_service),
) -> dict:
    from app.network.detect import detect_gateway_ip, detect_wifi_ssid

    gateway = _safe_detect(detect_gateway_ip, "网关")
    ssid = _safe_detect(detect_wifi_ssid, "SSID")
    matched_id = _safe_detect(profile_svc.detect_matching_profile, "方案匹配")

    data = profile_svc.load()
    matched_name = None
    if matched_id and matched_id in data.profiles:
        matched_name = data.profiles[matched_id].name

    api_logger.info(
        "网络检测结果: gateway={}, ssid={}, matched={}",
        gateway,
        ssid,
        matched_id,
    )
    return {
        "gateway_ip": gateway,
        "ssid": ssid,
        "matched_profile_id": matched_id,
        "matched_profile_name": matched_name,
    }


@router.post("/api/profiles/auto-switch")
def toggle_auto_switch(
    enabled: str = Query(default="true"),
    profile_svc: ProfileService = Depends(get_profile_service),
    monitor_svc: ScheduleEngine = Depends(get_monitor_service),
) -> dict:
    enabled_bool = enabled.strip().lower() in ("true", "1", "yes", "on")
    profile_svc.set_auto_switch(enabled_bool)
    state = "开启" if enabled_bool else "关闭"
    api_logger.info("自动切换 {}", state)

    # 获取当前活动方案
    data = profile_svc.load()
    active_profile = data.active_profile

    # 开启自动切换时，立即进行一次检测
    warning = None
    if enabled_bool:
        try:
            matched_id = profile_svc.detect_matching_profile()
            if matched_id:
                if matched_id != data.active_profile:
                    profile = data.profiles.get(matched_id)
                    profile_name = profile.name if profile else matched_id
                    api_logger.info("自动切换检测到匹配方案: {}", profile_name)
                    profile_svc.set_active_profile(matched_id)
                    monitor_svc.apply_profile(matched_id)
                    active_profile = matched_id
                else:
                    api_logger.info("当前方案已匹配，无需切换")
            else:
                api_logger.info("未检测到匹配方案，保持当前方案")
        except Exception as exc:
            api_logger.warning("自动切换检测失败: {}", exc)
            warning = f"首次检测失败: {exc}"

    result = {
        "success": True,
        "message": f"自动切换已{state}",
        "active_profile": active_profile,
    }
    if warning:
        result["warning"] = warning
    return result
