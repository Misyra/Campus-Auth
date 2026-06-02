"""方案路由 — 配置方案的 CRUD、活动方案、网络检测、自动切换。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from src.utils.logging import get_logger

from ..deps import get_monitor_service, get_profile_service
from ..monitor_service import MonitorService
from ..profile_service import ProfileService
from ..schemas import ActionResponse, ProfileSettings

router = APIRouter()
api_logger = get_logger("backend.api", side="BACKEND")


def _safe_detect(func, label: str, default=None):
    """安全执行检测函数，异常时记录日志并返回默认值。"""
    try:
        return func()
    except Exception as exc:
        api_logger.error("%s检测异常: %s", label, exc, exc_info=True)
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
            "use_global_auth_url": settings.use_global_auth_url,
            "auth_url": settings.auth_url,
            "use_global_task": settings.use_global_task,
            "active_task": settings.active_task,
        }
    return {
        "profiles": result,
        "active_profile": data.active_profile,
        "auto_switch": data.auto_switch,
    }


@router.get("/api/profiles/active")
def get_active_profile(
    profile_svc: ProfileService = Depends(get_profile_service),
) -> dict:
    data = profile_svc.load()
    profile = profile_svc.get_active_profile()
    return {
        "profile_id": data.active_profile,
        "auto_switch": data.auto_switch,
        "settings": profile.model_dump(),
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
    monitor_svc: MonitorService = Depends(get_monitor_service),
) -> ActionResponse:
    ok, message = profile_svc.save_profile(profile_id, payload)
    api_logger.info(
        "Save profile %s -> success=%s, message=%s", profile_id, ok, message
    )
    if ok:
        data = profile_svc.load()
        if data.active_profile == profile_id:
            try:
                monitor_svc.apply_profile(profile_id)
            except Exception as exc:
                api_logger.warning("Apply profile failed: %s", exc)
    return ActionResponse(success=ok, message=message)


@router.delete("/api/profiles/{profile_id}", response_model=ActionResponse)
def delete_profile(
    profile_id: str,
    profile_svc: ProfileService = Depends(get_profile_service),
) -> ActionResponse:
    ok, message = profile_svc.delete_profile(profile_id)
    api_logger.info(
        "Delete profile %s -> success=%s, message=%s", profile_id, ok, message
    )
    return ActionResponse(success=ok, message=message)


@router.post("/api/profiles/active/{profile_id}", response_model=ActionResponse)
def set_active_profile(
    profile_id: str,
    profile_svc: ProfileService = Depends(get_profile_service),
    monitor_svc: MonitorService = Depends(get_monitor_service),
) -> ActionResponse:
    ok, message = profile_svc.set_active_profile(profile_id)
    api_logger.info(
        "Set active profile %s -> success=%s, message=%s", profile_id, ok, message
    )
    if ok:
        data = profile_svc.load()
        profile = data.profiles.get(profile_id)
        profile_name = profile.name if profile else profile_id
        try:
            monitor_svc.apply_profile(profile_name)
        except Exception as exc:
            api_logger.warning("Apply profile failed: %s", exc)
    return ActionResponse(success=ok, message=message)


@router.post("/api/profiles/detect")
def detect_network_profile(
    profile_svc: ProfileService = Depends(get_profile_service),
) -> dict:
    from src.network_detect import detect_gateway_ip, detect_wifi_ssid

    gateway = _safe_detect(detect_gateway_ip, "网关")
    ssid = _safe_detect(detect_wifi_ssid, "SSID")
    matched_id = _safe_detect(profile_svc.detect_matching_profile, "方案匹配")

    data = profile_svc.load()
    matched_name = None
    if matched_id and matched_id in data.profiles:
        matched_name = data.profiles[matched_id].name

    api_logger.info(
        "网络检测结果: gateway=%s, ssid=%s, matched=%s",
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


@router.post("/api/profiles/auto-switch", response_model=ActionResponse)
def toggle_auto_switch(
    enabled: str = Query(default="true"),
    profile_svc: ProfileService = Depends(get_profile_service),
) -> ActionResponse:
    enabled_bool = enabled.strip().lower() in ("true", "1", "yes", "on")
    profile_svc.set_auto_switch(enabled_bool)
    state = "开启" if enabled_bool else "关闭"
    api_logger.info("Auto-switch %s", state)
    return ActionResponse(success=True, message=f"自动切换已{state}")
