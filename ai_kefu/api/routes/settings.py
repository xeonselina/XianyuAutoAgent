"""
Settings API routes — expose and update runtime configuration.

GET  /settings        → current (non-sensitive) settings snapshot
PATCH /settings       → update mutable runtime flags (e.g. enable_ai_reply)
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from ai_kefu.config.settings import settings

router = APIRouter()


class SettingsResponse(BaseModel):
    model_name: str
    model_name_light: str
    model_base_url: str
    enable_ai_reply: bool
    toggle_keywords: str
    suppress_keywords: str
    suppress_duration: int
    manual_mode_timeout: int
    max_turns: int
    log_level: str
    enable_confidence_guard: bool
    response_confidence_threshold: float
    session_mapper_type: str


class SettingsPatch(BaseModel):
    enable_ai_reply: Optional[bool] = None
    toggle_keywords: Optional[str] = None
    suppress_keywords: Optional[str] = None
    suppress_duration: Optional[int] = None
    manual_mode_timeout: Optional[int] = None
    log_level: Optional[str] = None
    enable_confidence_guard: Optional[bool] = None
    response_confidence_threshold: Optional[float] = None


@router.get("/", response_model=SettingsResponse)
async def get_settings():
    """Return current non-sensitive runtime settings."""
    return SettingsResponse(
        model_name=settings.model_name,
        model_name_light=settings.model_name_light,
        model_base_url=settings.model_base_url,
        enable_ai_reply=settings.enable_ai_reply,
        toggle_keywords=settings.toggle_keywords,
        suppress_keywords=settings.suppress_keywords,
        suppress_duration=settings.suppress_duration,
        manual_mode_timeout=settings.manual_mode_timeout,
        max_turns=settings.max_turns,
        log_level=settings.log_level,
        enable_confidence_guard=settings.enable_confidence_guard,
        response_confidence_threshold=settings.response_confidence_threshold,
        session_mapper_type=settings.session_mapper_type,
    )


@router.patch("/", response_model=SettingsResponse)
async def patch_settings(patch: SettingsPatch):
    """Update mutable runtime settings (takes effect immediately, not persisted across restarts)."""
    if patch.enable_ai_reply is not None:
        settings.enable_ai_reply = patch.enable_ai_reply
    if patch.toggle_keywords is not None:
        settings.toggle_keywords = patch.toggle_keywords
    if patch.suppress_keywords is not None:
        settings.suppress_keywords = patch.suppress_keywords
    if patch.suppress_duration is not None:
        settings.suppress_duration = patch.suppress_duration
    if patch.manual_mode_timeout is not None:
        settings.manual_mode_timeout = patch.manual_mode_timeout
    if patch.log_level is not None:
        settings.log_level = patch.log_level
    if patch.enable_confidence_guard is not None:
        settings.enable_confidence_guard = patch.enable_confidence_guard
    if patch.response_confidence_threshold is not None:
        if not (0.0 <= patch.response_confidence_threshold <= 1.0):
            raise HTTPException(status_code=422, detail="response_confidence_threshold must be between 0 and 1")
        settings.response_confidence_threshold = patch.response_confidence_threshold

    return await get_settings()
