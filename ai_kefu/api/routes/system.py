"""
System and health check endpoints.
"""

from fastapi import APIRouter, Depends
from ai_kefu.api.models import HealthCheckResponse
from ai_kefu.storage.session_store import SessionStore
from ai_kefu.storage.knowledge_store import KnowledgeStore
from ai_kefu.llm.qwen_client import check_qwen_api
from ai_kefu.api.dependencies import get_session_store, get_knowledge_store
from datetime import datetime


router = APIRouter()


@router.get("/health", response_model=HealthCheckResponse)
async def health_check(
    session_store: SessionStore = Depends(get_session_store),
    knowledge_store: KnowledgeStore = Depends(get_knowledge_store)
):
    """
    Health check endpoint.
    
    Checks connectivity to:
    - Redis (session store)
    - Chroma (knowledge store)
    - Qwen API
    
    Returns:
        HealthCheckResponse with component status
    """
    checks = {}
    
    # Check Redis
    try:
        checks["redis"] = "ok" if session_store.ping() else "error"
    except Exception as e:
        checks["redis"] = f"error: {str(e)}"
    
    # Check Chroma
    try:
        checks["chroma"] = "ok" if knowledge_store.ping() else "error"
    except Exception as e:
        checks["chroma"] = f"error: {str(e)}"
    
    # Check Qwen API
    try:
        checks["qwen_api"] = "ok" if check_qwen_api() else "error"
    except Exception as e:
        checks["qwen_api"] = f"error: {str(e)}"
    
    # Determine overall status
    all_ok = all(status == "ok" for status in checks.values())
    overall_status = "healthy" if all_ok else "degraded"
    
    return HealthCheckResponse(
        status=overall_status,
        checks=checks,
        timestamp=datetime.utcnow()
    )
