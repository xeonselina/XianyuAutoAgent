"""
Chat API routes.
T047 - POST /chat and POST /chat/stream endpoints.
"""

import asyncio
import time
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from ai_kefu.api.models import ChatRequest, ChatResponse
from ai_kefu.api.dependencies import get_session_store, get_conversation_store
from ai_kefu.agent.executor import AgentExecutor
from ai_kefu.storage.session_store import SessionStore
from ai_kefu.utils.logging import logger
from typing import AsyncGenerator, Dict, Optional
import json


router = APIRouter()


# ============================================================
# Per-session concurrency guard
# ============================================================
# Prevents the same session_id from being processed concurrently.
# If a second request arrives while the first is still running,
# it returns immediately with a "busy" response instead of
# racing the first request and wasting LLM quota.
# ============================================================
_session_locks: Dict[str, asyncio.Lock] = {}
_session_locks_guard: Optional[asyncio.Lock] = None

# Limit total tracked sessions to prevent unbounded memory growth
_SESSION_LOCK_MAX_SIZE = 2000


def _ensure_session_locks_guard() -> asyncio.Lock:
    """Lazily create the guard lock inside a running event loop."""
    global _session_locks_guard
    if _session_locks_guard is None:
        _session_locks_guard = asyncio.Lock()
    return _session_locks_guard


async def _get_session_lock(session_id: str) -> asyncio.Lock:
    """Get or create an asyncio.Lock for the given session_id."""
    async with _ensure_session_locks_guard():
        if session_id not in _session_locks:
            # Evict oldest entries if we've grown too large
            if len(_session_locks) >= _SESSION_LOCK_MAX_SIZE:
                # Remove the first (oldest) entry
                oldest_key = next(iter(_session_locks))
                del _session_locks[oldest_key]
            _session_locks[session_id] = asyncio.Lock()
        return _session_locks[session_id]


@router.post("/", response_model=ChatResponse)
async def chat_sync(
    request: ChatRequest,
    session_store: SessionStore = Depends(get_session_store)
):
    """
    Synchronous chat endpoint.
    
    Args:
        request: Chat request with query and optional session_id
        session_store: Session store dependency
        
    Returns:
        ChatResponse with agent's response
    """
    try:
        logger.info(f"Chat request: query='{request.query[:50]}...', session_id={request.session_id}")
        
        # ============================================================
        # Per-session concurrency guard:
        # If the same session_id is already being processed, return
        # a "busy" response immediately instead of running in parallel.
        # ============================================================
        lock = None
        if request.session_id:
            lock = await _get_session_lock(request.session_id)
            if lock.locked():
                logger.warning(
                    f"Session {request.session_id} is already being processed, "
                    f"returning busy response for query='{request.query[:50]}...'"
                )
                return ChatResponse(
                    session_id=request.session_id,
                    response="",
                    status="active",
                    turn_counter=0,
                    metadata={"busy": True, "reason": "session_already_processing"}
                )

        # Acquire the session lock (non-blocking check above already passed)
        if lock:
            await lock.acquire()
        
        try:
            # Create agent executor
            conversation_store = get_conversation_store()
            executor = AgentExecutor(session_store=session_store, conversation_store=conversation_store)
            
            # Run agent in thread pool (pass context so executor can load chat history for new sessions)
            result = await asyncio.to_thread(
                executor.run,
                query=request.query,
                session_id=request.session_id,
                user_id=request.user_id,
                context=request.context
            )
        finally:
            # Always release the session lock
            if lock and lock.locked():
                lock.release()
        
        # If executor returned an error, return it as a normal response with error status
        # instead of HTTP 500, so the caller can distinguish between:
        # - Agent logic errors (LLM failures, tool errors) -> return in response body
        # - Server infrastructure errors (uncaught exceptions) -> HTTP 500
        if "error" in result:
            logger.warning(f"Agent returned error: {result['error']}")
            return ChatResponse(
                session_id=result.get("session_id", request.session_id or ""),
                response=result.get("response", ""),
                status=result.get("status", "error"),
                turn_counter=result.get("turn_counter", 0),
                metadata={"error": result["error"]}
            )
        
        # Return response
        return ChatResponse(
            session_id=result["session_id"],
            response=result.get("response", ""),
            status=result["status"],
            turn_counter=result.get("turn_counter", 0),
            metadata=result.get("metadata", {})
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Chat endpoint error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/stream")
async def chat_stream(
    request: ChatRequest,
    session_store: SessionStore = Depends(get_session_store)
):
    """
    Streaming chat endpoint (Server-Sent Events).
    
    Args:
        request: Chat request
        session_store: Session store dependency
        
    Returns:
        StreamingResponse with SSE
    """
    try:
        logger.info(f"Stream chat request: query='{request.query[:50]}...', session_id={request.session_id}")
        
        async def event_generator() -> AsyncGenerator[str, None]:
            """Generate SSE events."""
            try:
                # Create agent executor
                conversation_store = get_conversation_store()
                executor = AgentExecutor(session_store=session_store, conversation_store=conversation_store)
                
                # Stream response
                async for chunk in executor.stream(
                    query=request.query,
                    session_id=request.session_id,
                    user_id=request.user_id,
                    context=request.context
                ):
                    # Format as SSE
                    event_data = {
                        "text": chunk,
                        "type": "chunk"
                    }
                    yield f"data: {json.dumps(event_data, ensure_ascii=False)}\n\n"
                
                # Send completion event
                yield f"data: {json.dumps({'type': 'done'}, ensure_ascii=False)}\n\n"
                
            except Exception as e:
                logger.error(f"Stream error: {e}", exc_info=True)
                error_data = {
                    "type": "error",
                    "error": str(e)
                }
                yield f"data: {json.dumps(error_data, ensure_ascii=False)}\n\n"
        
        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream"
        )
        
    except Exception as e:
        logger.error(f"Stream endpoint error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
