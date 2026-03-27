"""
System prompt management API routes.
CRUD endpoints for system prompts with version management.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime

from ai_kefu.storage.prompt_store import PromptStore, SystemPrompt
from ai_kefu.api.dependencies import get_prompt_store
from ai_kefu.utils.logging import logger
from ai_kefu.prompts.rental_system_prompt import get_rental_system_prompt_template


router = APIRouter()


# ============================================================
# Request/Response Models
# ============================================================

class PromptCreateRequest(BaseModel):
    """Create system prompt request."""
    prompt_key: str = Field(..., min_length=1, max_length=100)
    title: str = Field(..., min_length=1, max_length=200)
    content: str = Field(..., min_length=1)
    description: Optional[str] = None
    active: bool = Field(default=False)


class PromptUpdateRequest(BaseModel):
    """Update system prompt request."""
    title: Optional[str] = Field(None, min_length=1, max_length=200)
    content: Optional[str] = Field(None, min_length=1)
    description: Optional[str] = None
    active: Optional[bool] = None


class PromptResponse(BaseModel):
    """System prompt response."""
    id: int
    prompt_key: str
    title: str
    content: str
    description: Optional[str]
    active: bool
    created_at: Optional[datetime]
    updated_at: Optional[datetime]


class PromptListResponse(BaseModel):
    """List of system prompts."""
    total: int
    items: List[PromptResponse]
    offset: int = 0
    limit: int = 20


# ============================================================
# CRUD Endpoints
# ============================================================

@router.post("/", response_model=PromptResponse, status_code=201)
async def create_prompt(
    request: PromptCreateRequest,
    prompt_store: PromptStore = Depends(get_prompt_store)
):
    """Create a new system prompt."""
    try:
        prompt = SystemPrompt(
            prompt_key=request.prompt_key,
            title=request.title,
            content=request.content,
            description=request.description,
            active=request.active
        )

        result = prompt_store.create(prompt)
        if not result:
            raise HTTPException(status_code=500, detail="Failed to create system prompt")

        return _to_response(result)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating prompt: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/", response_model=PromptListResponse)
async def list_prompts(
    prompt_key: Optional[str] = None,
    offset: int = 0,
    limit: int = 20,
    prompt_store: PromptStore = Depends(get_prompt_store)
):
    """List system prompts with optional filtering."""
    try:
        items = prompt_store.list_all(prompt_key=prompt_key, limit=limit, offset=offset)
        total = prompt_store.count(prompt_key=prompt_key)

        return PromptListResponse(
            total=total,
            items=[_to_response(p) for p in items],
            offset=offset,
            limit=limit
        )

    except Exception as e:
        logger.error(f"Error listing prompts: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/active/{prompt_key}", response_model=PromptResponse)
async def get_active_prompt(
    prompt_key: str,
    prompt_store: PromptStore = Depends(get_prompt_store)
):
    """Get the active system prompt for a given key."""
    try:
        prompt = prompt_store.get_active(prompt_key)
        if not prompt:
            raise HTTPException(
                status_code=404,
                detail=f"No active prompt found for key: {prompt_key}"
            )
        return _to_response(prompt)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting active prompt: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{prompt_id}", response_model=PromptResponse)
async def get_prompt(
    prompt_id: int,
    prompt_store: PromptStore = Depends(get_prompt_store)
):
    """Get system prompt by ID."""
    try:
        prompt = prompt_store.get(prompt_id)
        if not prompt:
            raise HTTPException(status_code=404, detail=f"Prompt not found: {prompt_id}")
        return _to_response(prompt)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting prompt: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{prompt_id}", response_model=PromptResponse)
async def update_prompt(
    prompt_id: int,
    request: PromptUpdateRequest,
    prompt_store: PromptStore = Depends(get_prompt_store)
):
    """Update system prompt."""
    try:
        updates = {}
        if request.title is not None:
            updates['title'] = request.title
        if request.content is not None:
            updates['content'] = request.content
        if request.description is not None:
            updates['description'] = request.description
        if request.active is not None:
            updates['active'] = request.active

        result = prompt_store.update(prompt_id, updates)
        if not result:
            raise HTTPException(status_code=404, detail=f"Prompt not found: {prompt_id}")

        return _to_response(result)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating prompt: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{prompt_id}")
async def delete_prompt(
    prompt_id: int,
    prompt_store: PromptStore = Depends(get_prompt_store)
):
    """Delete system prompt."""
    try:
        success = prompt_store.delete(prompt_id)
        if not success:
            raise HTTPException(status_code=404, detail=f"Prompt not found: {prompt_id}")

        return {"success": True, "message": f"Prompt {prompt_id} deleted"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting prompt: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{prompt_id}/activate")
async def activate_prompt(
    prompt_id: int,
    prompt_store: PromptStore = Depends(get_prompt_store)
):
    """Set a prompt as the active version for its key."""
    try:
        success = prompt_store.set_active(prompt_id)
        if not success:
            raise HTTPException(status_code=404, detail=f"Prompt not found: {prompt_id}")

        return {"success": True, "message": f"Prompt {prompt_id} is now active"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error activating prompt: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# Initialize Defaults
# ============================================================

@router.post("/init-defaults")
async def initialize_default_prompts(
    prompt_store: PromptStore = Depends(get_prompt_store)
):
    """
    Initialize database with default system prompts from code.
    Idempotent: skips if active prompt already exists for each key.
    """
    try:
        initialized = 0
        skipped = 0

        defaults = [
            {
                "prompt_key": "rental_system",
                "title": "手机租赁客服 System Prompt",
                "content": get_rental_system_prompt_template(),
                "description": "闲鱼手机租赁业务的主 System Prompt，支持模板变量 {today_str} {today_date} {current_year} {current_month}",
                "active": True
            }
        ]

        for item in defaults:
            existing = prompt_store.get_active(item["prompt_key"])
            if existing:
                skipped += 1
                continue

            prompt = SystemPrompt(
                prompt_key=item["prompt_key"],
                title=item["title"],
                content=item["content"],
                description=item["description"],
                active=item["active"]
            )
            result = prompt_store.create(prompt)
            if result:
                initialized += 1

        message = f"初始化完成：新增 {initialized} 条，跳过 {skipped} 条"
        return {
            "initialized": initialized,
            "skipped": skipped,
            "message": message
        }

    except Exception as e:
        logger.error(f"Init defaults error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# Helper
# ============================================================

def _to_response(prompt: SystemPrompt) -> PromptResponse:
    """Convert SystemPrompt to response model."""
    return PromptResponse(
        id=prompt.id,
        prompt_key=prompt.prompt_key,
        title=prompt.title,
        content=prompt.content,
        description=prompt.description,
        active=prompt.active,
        created_at=prompt.created_at,
        updated_at=prompt.updated_at
    )
