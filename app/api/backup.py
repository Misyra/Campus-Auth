"""备份恢复路由 — 配置备份的创建、恢复、下载、删除。"""

from __future__ import annotations

import re
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from app.utils.file_helpers import atomic_write
from app.utils.logging import get_logger

from app.constants import BACKUP_DIR, BACKUP_FILENAME_PATTERN, MAX_BACKUPS, PROJECT_ROOT
from app.deps import get_profile_service, get_monitor_service
from app.services.monitor import MonitorService
from app.services.profile import ProfileService
from app.schemas import ActionResponse, ProfilesData

router = APIRouter()
api_logger = get_logger("backend.api", side="BACKEND")


def _cleanup_old_backups(max_backups: int = MAX_BACKUPS) -> None:
    """清理旧备份，仅保留最新的 max_backups 个文件"""
    backups = sorted(BACKUP_DIR.glob("settings_*.json"), reverse=True)
    for old in backups[max_backups:]:
        try:
            old.unlink()
        except OSError:
            pass


@router.get("/api/backup/list")
def list_backups() -> list[dict]:
    """列出所有备份"""
    backups = []
    for f in sorted(BACKUP_DIR.glob("settings_*.json"), reverse=True):
        stat = f.stat()
        backups.append(
            {
                "filename": f.name,
                "size": stat.st_size,
                "created": datetime.fromtimestamp(stat.st_mtime).strftime(
                    "%Y-%m-%d %H:%M:%S"
                ),
            }
        )
    return backups


@router.post("/api/backup/create", response_model=ActionResponse)
def create_backup() -> ActionResponse:
    """创建当前配置的备份"""
    settings_path = PROJECT_ROOT / "settings.json"
    if not settings_path.exists():
        raise HTTPException(status_code=404, detail="settings.json 不存在，无需备份")

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = BACKUP_DIR / f"settings_{stamp}.json"

    try:
        backup_path.write_bytes(settings_path.read_bytes())
        _cleanup_old_backups()
        api_logger.info("备份已创建: {}", backup_path.name)
        return ActionResponse(success=True, message=f"备份已创建: {backup_path.name}")
    except Exception as exc:
        api_logger.error("创建备份失败: {}", exc)
        raise HTTPException(status_code=500, detail=f"创建备份失败: {exc}")


@router.post("/api/backup/restore/{filename}", response_model=ActionResponse)
def restore_backup(
    filename: str,
    profile_svc: ProfileService = Depends(get_profile_service),
    monitor_svc: MonitorService = Depends(get_monitor_service),
) -> ActionResponse:
    """从备份恢复配置"""
    if not re.match(BACKUP_FILENAME_PATTERN, filename):
        raise HTTPException(status_code=400, detail="无效的备份文件名")

    backup_path = BACKUP_DIR / filename
    if not backup_path.exists():
        raise HTTPException(status_code=404, detail="备份文件不存在")

    # 恢复前先自动创建当前配置的备份
    settings_path = PROJECT_ROOT / "settings.json"
    if settings_path.exists():
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        auto_backup = BACKUP_DIR / f"settings_{stamp}_autosave.json"
        try:
            auto_backup.write_bytes(settings_path.read_bytes())
        except Exception:
            api_logger.debug("设置备份失败", exc_info=True)

    try:
        backup_content = backup_path.read_text(encoding="utf-8")
        ProfilesData.model_validate_json(backup_content)
    except Exception as exc:
        api_logger.error("备份文件校验失败: {} — {}", filename, exc)
        raise HTTPException(status_code=400, detail=f"备份文件格式错误: {exc}")

    try:
        old_active = profile_svc.load().active_profile
        atomic_write(settings_path, backup_content)
        profile_svc.invalidate_cache()
        monitor_svc.reload_config()
        _cleanup_old_backups()
        api_logger.info("配置已从备份恢复: {} (原活动方案: {})", filename, old_active)
        return ActionResponse(success=True, message="配置已从备份恢复，请刷新页面查看")
    except Exception as exc:
        api_logger.error("恢复备份失败: {}", exc)
        raise HTTPException(status_code=500, detail=f"恢复备份失败: {exc}")


@router.get("/api/backup/download/{filename}")
def download_backup(filename: str):
    """下载备份文件"""
    if not re.match(BACKUP_FILENAME_PATTERN, filename):
        raise HTTPException(status_code=400, detail="无效的备份文件名")
    backup_path = BACKUP_DIR / filename
    if not backup_path.exists():
        raise HTTPException(status_code=404, detail="备份文件不存在")
    return FileResponse(backup_path, media_type="application/json", filename=filename)


@router.delete("/api/backup/{filename}", response_model=ActionResponse)
def delete_backup(filename: str) -> ActionResponse:
    """删除备份"""
    if not re.match(BACKUP_FILENAME_PATTERN, filename):
        raise HTTPException(status_code=400, detail="无效的备份文件名")

    backup_path = BACKUP_DIR / filename
    if not backup_path.exists():
        raise HTTPException(status_code=404, detail="备份文件不存在")

    try:
        backup_path.unlink()
        api_logger.info("备份已删除: {}", filename)
        return ActionResponse(success=True, message="备份已删除")
    except Exception as exc:
        api_logger.error("删除备份失败: {}", exc)
        raise HTTPException(status_code=500, detail=f"删除备份失败: {exc}")
