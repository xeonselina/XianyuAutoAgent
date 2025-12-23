"""
Chat API routes.
T047 - POST /chat and POST /chat/stream endpoints.
"""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from ai_kefu.api.models import ChatRequest, ChatResponse
from ai_kefu.api.dependencies import get_session_store
from ai_kefu.agent.executor import AgentExecutor
from ai_kefu.storage.session_store import SessionStore
from ai_kefu.utils.logging import logger
from typing import AsyncGenerator
import json


router = APIRouter()


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
        
        # Create agent executor
        executor = AgentExecutor(session_store=session_store)
        
        # Run agent
        result = executor.run(
            query=request.query,
            session_id=request.session_id,
            user_id=request.user_id
        )
        
        # Check for errors
        if "error" in result:
            raise HTTPException(status_code=500, detail=result["error"])
        
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
                executor = AgentExecutor(session_store=session_store)
                
                # Stream response
                async for chunk in executor.stream(
                    query=request.query,
                    session_id=request.session_id,
                    user_id=request.user_id
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
