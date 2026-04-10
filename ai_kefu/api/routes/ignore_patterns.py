"""
Ignore patterns management API routes.
CRUD endpoints for managing message patterns that should be skipped by AI agent.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime

from ai_kefu.storage.ignore_pattern_store import IgnorePatternStore, IgnorePattern
from ai_kefu.api.dependencies import get_ignore_pattern_store
from ai_kefu.utils.logging import logger


router = APIRouter()


# ============================================================
# Request/Response Models
# ============================================================

class IgnorePatternCreateRequest(BaseModel):
    """Create ignore pattern request."""
    pattern: str = Field(..., min_length=1, max_length=500, description="要忽略的消息内容")
    description: Optional[str] = Field(None, max_length=500, description="描述说明")
    active: bool = Field(default=True, description="是否启用")


class IgnorePatternUpdateRequest(BaseModel):
    """Update ignore pattern request."""
    pattern: Optional[str] = Field(None, min_length=1, max_length=500)
    description: Optional[str] = None
    active: Optional[bool] = None


class IgnorePatternResponse(BaseModel):
    """Ignore pattern response."""
    id: int
    pattern: str
    description: Optional[str]
    active: bool
    created_at: Optional[datetime]
    updated_at: Optional[datetime]


class IgnorePatternListResponse(BaseModel):
    """List of ignore patterns."""
    total: int
    items: List[IgnorePatternResponse]
    offset: int = 0
    limit: int = 100


# ============================================================
# CRUD Endpoints
# ============================================================

@router.post("/", response_model=IgnorePatternResponse, status_code=201)
async def create_ignore_pattern(
    request: IgnorePatternCreateRequest,
    store: IgnorePatternStore = Depends(get_ignore_pattern_store)
):
    """Create a new ignore pattern."""
    try:
        pattern = IgnorePattern(
            pattern=request.pattern,
            description=request.description,
            active=request.active
        )
        result = store.create(pattern)
        if not result:
            raise HTTPException(
                status_code=409,
                detail=f"Pattern already exists: '{request.pattern}'"
            )
        return _to_response(result)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating ignore pattern: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/", response_model=IgnorePatternListResponse)
async def list_ignore_patterns(
    active_only: bool = False,
    offset: int = 0,
    limit: int = 100,
    store: IgnorePatternStore = Depends(get_ignore_pattern_store)
):
    """List all ignore patterns."""
    try:
        items = store.list_all(active_only=active_only, limit=limit, offset=offset)
        total = store.count(active_only=active_only)

        return IgnorePatternListResponse(
            total=total,
            items=[_to_response(p) for p in items],
            offset=offset,
            limit=limit
        )

    except Exception as e:
        logger.error(f"Error listing ignore patterns: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{pattern_id}", response_model=IgnorePatternResponse)
async def get_ignore_pattern(
    pattern_id: int,
    store: IgnorePatternStore = Depends(get_ignore_pattern_store)
):
    """Get ignore pattern by ID."""
    try:
        pattern = store.get(pattern_id)
        if not pattern:
            raise HTTPException(status_code=404, detail=f"Pattern not found: {pattern_id}")
        return _to_response(pattern)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting ignore pattern: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{pattern_id}", response_model=IgnorePatternResponse)
async def update_ignore_pattern(
    pattern_id: int,
    request: IgnorePatternUpdateRequest,
    store: IgnorePatternStore = Depends(get_ignore_pattern_store)
):
    """Update ignore pattern."""
    try:
        updates = {}
        if request.pattern is not None:
            updates['pattern'] = request.pattern
        if request.description is not None:
            updates['description'] = request.description
        if request.active is not None:
            updates['active'] = request.active

        result = store.update(pattern_id, updates)
        if not result:
            raise HTTPException(status_code=404, detail=f"Pattern not found: {pattern_id}")
        return _to_response(result)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating ignore pattern: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{pattern_id}")
async def delete_ignore_pattern(
    pattern_id: int,
    store: IgnorePatternStore = Depends(get_ignore_pattern_store)
):
    """Delete ignore pattern."""
    try:
        success = store.delete(pattern_id)
        if not success:
            raise HTTPException(status_code=404, detail=f"Pattern not found: {pattern_id}")
        return {"success": True, "message": f"Pattern {pattern_id} deleted"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting ignore pattern: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{pattern_id}/toggle")
async def toggle_ignore_pattern(
    pattern_id: int,
    store: IgnorePatternStore = Depends(get_ignore_pattern_store)
):
    """Toggle ignore pattern active status."""
    try:
        pattern = store.get(pattern_id)
        if not pattern:
            raise HTTPException(status_code=404, detail=f"Pattern not found: {pattern_id}")

        result = store.update(pattern_id, {'active': not pattern.active})
        new_status = "启用" if result.active else "禁用"
        return {"success": True, "message": f"Pattern {pattern_id} 已{new_status}", "active": result.active}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error toggling ignore pattern: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# Helper
# ============================================================

def _to_response(pattern: IgnorePattern) -> IgnorePatternResponse:
    """Convert IgnorePattern to response model."""
    return IgnorePatternResponse(
        id=pattern.id,
        pattern=pattern.pattern,
        description=pattern.description,
        active=pattern.active,
        created_at=pattern.created_at,
        updated_at=pattern.updated_at
    )
